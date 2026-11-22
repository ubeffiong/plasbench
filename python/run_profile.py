#!/usr/bin/env python3
"""`plasbench profile-run`: where did the time of a run go?

Reads results/run_events.jsonl (and, when present, the logs folder, the data folder's per-isolate stage2_timing.tsv / truth.tsv and results/.suspend_gaps) and prints
  - a per-stage table, a per-step table (all isolates together, with each step's share of its stage and of the whole run) and a per-isolate table,
  - the annotation callers' own timings (from the annotation logs),
  - the times the computer was asleep (recorded by the run's sentinel as `system_suspend`, or inferred from a silence in the event log while a command was running;
    inferred ones are labelled), which are left out of every "awake" figure: a pause is not a cost,
  - the five biggest costs with a plain-language suggestion for each.

Every figure is a measurement from the event log unless it is labelled estimated. Nothing here changes a run.

  python3 python/run_profile.py --results-dir DIR [--data-dir DIR] [--log-dir DIR] [--json]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import OrderedDict, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import awake_clock  # noqa: E402
import run_status  # noqa: E402

INFER_GAP_SECONDS = 300          # silence this long between two events while a command is open (heartbeats come every 60 s) is called a sleep
SUSPECT_FACTOR = 10              # a step this many times its usual time (and over SUSPECT_MIN seconds) is flagged as a possible pause
SUSPECT_MIN_SECONDS = 600
CALLER_LINE = re.compile(r"annotation: (\w+) finished in (\d+) s \((\w+),")


def human(seconds):
    return awake_clock.human(seconds)


# --------------------------------------------------------------------------------------------------------------------------- reading
def read_tsv(path):
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, UnicodeDecodeError):
        return []


def event_epoch(row):
    try:
        return float(row.get("epoch"))
    except (TypeError, ValueError):
        return None


def number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def split_what(what):
    """'klebsiella_x / fastp trimming' -> ('klebsiella_x', 'fastp trimming')."""
    if " / " in (what or ""):
        sample, step = what.split(" / ", 1)
        return sample.strip(), step.strip()
    return "", (what or "").strip()


def suspend_gaps(events, gaps_file=None):
    """[(start, end, source)] merged: recorded ones (system_suspend events and the gaps file) and gaps inferred from an event-log silence inside an open command."""
    recorded = []
    for row in events:
        if row.get("event") == "system_suspend":
            start, end = number(row.get("start_epoch")), number(row.get("end_epoch"))
            if start and end and end > start:
                recorded.append((start, end))
    if gaps_file:
        recorded.extend(awake_clock.read_gaps(gaps_file))
    recorded = awake_clock.merge(recorded)
    inferred = []
    open_command, previous = None, None
    heartbeats_on = any(r.get("event") == "heartbeat" for r in events)   # a run with no heartbeats at all says nothing about silence
    for row in sorted((r for r in events if event_epoch(r) is not None), key=event_epoch):
        epoch = event_epoch(row)
        kind = row.get("event")
        if heartbeats_on and previous is not None and open_command and epoch - previous > INFER_GAP_SECONDS:
            start = previous + 60            # the last heartbeat was seen at `previous`; the next one was due a minute later
            if awake_clock.overlap_seconds(recorded, start, epoch) < 0.5 * (epoch - start):
                inferred.append((start, epoch))
        if kind == "command_start":
            open_command = row.get("what")
        elif kind == "command_end":
            open_command = None
        previous = epoch
    out = [(s, e, "recorded") for s, e in recorded] + [(s, e, "inferred") for s, e in awake_clock.merge(inferred)
                                                      if awake_clock.overlap_seconds(recorded, s, e) < 0.5 * (e - s)]
    return sorted(out)


def intervals(gaps):
    return [(s, e) for s, e, _ in gaps]


def stage_table(events, gaps):
    starts, stages = {}, OrderedDict()
    last_epoch = max((event_epoch(r) or 0 for r in events), default=0)
    for row in events:
        epoch, kind, stage = event_epoch(row), row.get("event"), str(row.get("stage") or "")
        if epoch is None or not stage:
            continue
        if kind == "stage_start":
            starts[stage] = epoch
            stages.setdefault(stage, {"stage": stage, "start": epoch, "end": None})
            stages[stage].update(start=epoch, end=None)
        elif kind == "stage_end" and stage in stages:
            stages[stage]["end"] = epoch
    out = []
    for stage, info in stages.items():
        end = info["end"] or last_epoch
        wall = max(0.0, end - info["start"])
        asleep = awake_clock.overlap_seconds(intervals(gaps), info["start"], end)
        out.append({"stage": stage, "start": info["start"], "end": end, "seconds": wall, "suspended_seconds": asleep, "awake_seconds": max(0.0, wall - asleep),
                    "finished": info["end"] is not None})
    return out


def command_steps(events, gaps):
    """One row per finished long command (the heartbeat-watched ones: fastp, SPAdes, reference annotation, ...)."""
    rows, opened = [], {}
    for row in events:
        epoch = event_epoch(row)
        if epoch is None:
            continue
        if row.get("event") == "command_start":
            opened[row.get("what")] = (epoch, str(row.get("stage") or ""))
        elif row.get("event") == "command_end" and row.get("what") in opened:
            start, stage = opened.pop(row.get("what"))
            sample, step = split_what(row.get("what"))
            wall = number(row.get("seconds"), epoch - start)
            asleep = awake_clock.overlap_seconds(intervals(gaps), start, epoch)
            rows.append({"stage": stage, "sample": sample, "step": step, "seconds": wall, "awake_seconds": max(0.0, wall - asleep), "start": start, "end": epoch, "source": "command"})
    return rows


def download_steps(events, gaps):
    rows, opened = [], {}
    for row in events:
        epoch = event_epoch(row)
        if epoch is None:
            continue
        if row.get("event") == "sample_start" and row.get("step") == "download":
            opened[row.get("sample")] = epoch
        elif row.get("event") == "download_end" and row.get("sample") in opened:
            start = opened.pop(row.get("sample"))
            asleep = awake_clock.overlap_seconds(intervals(gaps), start, epoch)
            rows.append({"stage": str(row.get("stage") or "1"), "sample": row.get("sample"), "step": "download", "seconds": epoch - start,
                         "awake_seconds": max(0.0, epoch - start - asleep), "start": start, "end": epoch, "source": "events", "status": row.get("status")})
    return rows


def stage2_steps(events, data_dir, gaps):
    """The per-step table each isolate's stage 2 wrote (stage2_timing.tsv). The steps run in order from the isolate's `truth` sample_start, which gives each one a time
    window, so the sleep inside it can be taken out. Tables from before the awake_seconds column have only `seconds`."""
    rows = []
    if not data_dir:
        return rows
    starts = {}
    for row in events:
        if row.get("event") == "sample_start" and row.get("step") == "truth" and str(row.get("stage")) == "2" and event_epoch(row) is not None:
            starts[row.get("sample")] = event_epoch(row)
    for sample, start in starts.items():
        table = read_tsv(Path(data_dir) / sample / "stage2_timing.tsv")
        cursor = start
        for entry in table:
            if entry.get("step") == "total":
                continue
            seconds = number(entry.get("seconds"), 0.0)
            end = cursor + seconds
            if entry.get("awake_seconds") not in (None, ""):
                awake = number(entry.get("awake_seconds"), seconds)
            else:
                awake = max(0.0, seconds - awake_clock.overlap_seconds(intervals(gaps), cursor, end))
            rows.append({"stage": "2", "sample": sample, "step": entry.get("step"), "seconds": seconds, "awake_seconds": awake, "start": cursor, "end": end, "source": "stage2_timing.tsv"})
            cursor = end
    return rows


def caller_times(log_dir, samples):
    """{sample: [{caller, seconds, status}]} from the annotation logs ('annotation: isescan finished in 2292 s (ok, ...')."""
    out = {}
    if not log_dir:
        return out
    for sample in samples:
        path = Path(log_dir) / f"{sample}.annotation.log"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rows = [{"caller": m.group(1), "seconds": int(m.group(2)), "status": m.group(3)} for m in CALLER_LINE.finditer(text) if m.group(1) != "isfinder" or int(m.group(2))]
        if rows:
            out[sample] = rows
    return out


def plasmid_share(data_dir, sample):
    """Share of the reference's bases on truth plasmids, or None: what a plasmid-only ISEScan search would keep."""
    if not data_dir:
        return None
    total = plasmid = 0
    for row in read_tsv(Path(data_dir) / sample / "truth.tsv"):
        length = number(row.get("length"), 0)
        total += length
        if (row.get("molecule_type") or "").upper() == "PLASMID":
            plasmid += length
    return (plasmid / total) if total else None


# ------------------------------------------------------------------------------------------------------------------------- aggregation
def key_of(step):
    text = (step or "").lower()
    for needle, key in (("download", "download"), ("annotation", "annotation"), ("fastp", "fastp"), ("spades", "assembly"), ("unicycler", "assembly"),
                        ("repeat_content", "repeat_content"), ("read_depth", "read_depth"), ("mob", "mob_recon"), ("platon", "platon")):
        if needle in text:
            return key
    return text


def suspected_pauses(step_rows):
    """Steps far beyond the usual time of the same step on the other isolates, with no recorded sleep inside: flagged, never subtracted. (Evidence of a pause that left no
    heartbeat, such as a step with no heartbeat running through a sleep.)"""
    by_step = defaultdict(list)
    for row in step_rows:
        by_step[(row["stage"], row["step"])].append(row)
    flagged = []
    for (_, step), rows in by_step.items():
        if len(rows) < 3:
            continue
        values = sorted(r["awake_seconds"] for r in rows)
        median = values[len(values) // 2]
        for r in rows:
            if r["awake_seconds"] >= SUSPECT_MIN_SECONDS and r["awake_seconds"] > SUSPECT_FACTOR * max(median, 30):
                flagged.append({"sample": r["sample"], "step": step, "seconds": r["awake_seconds"], "median_seconds": median})
    return flagged


def suggestion(item, ctx):
    key, share = item["key"], item["share_of_run"]
    pct = f"{100 * share:.0f}%"
    callers, isolates = ctx.get("callers", {}), ctx.get("isolates", {})
    if key == "annotation":
        total = {}
        for rows in callers.values():
            for c in rows:
                total[c["caller"]] = total.get(c["caller"], 0) + c["seconds"]
        ann_total = item["seconds"] or 1
        isescan = total.get("isescan", 0)
        timed_out = sorted({f"{s}: {c['caller']}" for s, rows in callers.items() for c in rows if c["status"] == "timed_out"})
        text = f"Reference annotation took {pct} of the run."
        if isescan:
            text += f" ISEScan alone was {100 * min(1.0, isescan / ann_total):.0f}% of it ({human(isescan)} over {len(callers)} isolate(s))."
            saving, kept, known = 0.0, 0.0, 0.0
            for sample, rows in callers.items():
                share = plasmid_share(ctx.get("data_dir"), sample)
                seconds = sum(c["seconds"] for c in rows if c["caller"] == "isescan")
                if share is not None and seconds:
                    saving += seconds * (1 - share)
                    kept += seconds * share
                    known += seconds
            if known:
                text += (f" ISESCAN_SCOPE=plasmids (the default now) searches only the truth plasmids, {100 * kept / known:.0f}% of the bases here (time-weighted): estimated saving about "
                         f"{human(saving)} (ISEScan time is roughly proportional to the bases searched); ANNOTATE_WITH_ISESCAN=0 saves all of it.")
            else:
                text += " ISESCAN_SCOPE=plasmids (the default now) searches only the plasmids; ANNOTATE_WITH_ISESCAN=0 turns it off."
        if timed_out:
            text += f" Callers stopped at their time limit (their results are missing, not zero): {', '.join(timed_out[:6])}."
        return text
    if key == "download":
        worst = max((r for r in isolates.get("1", []) if r["step"] == "download"), key=lambda r: r["awake_seconds"], default=None)
        extra = f" The slowest was {worst['sample']} at {human(worst['awake_seconds'])}." if worst else ""
        return f"Downloads took {pct} of the run, limited by the network and the size of the read sets.{extra} MAX_RUN_DOWNLOAD_GB skips very large isolates."
    if key == "repeat_content":
        return (f"Repeat-content analysis took {pct}. Usually it takes seconds; a step this long with no heartbeat inside is most often the computer asleep (a pause that left "
                "no record). KEEP_AWAKE=1 (the default) prevents that. RUN_REPEAT_CONTENT=0 skips the step.")
    if key == "fastp":
        return f"Read trimming took {pct}. It is I/O-bound on a slow data folder: WORK_DIR=auto keeps a fast local copy (the default for Windows drives seen from WSL)."
    if key == "assembly":
        return f"Assembly took {pct}, the normal heavy step. A local working folder (WORK_DIR=auto) and enough free memory help most; ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1 is faster but changes the assembly."
    if key == "read_depth":
        return f"Read-depth measurement took {pct}; it reads every read once. It is slow only for very large read sets (MAX_RUN_DOWNLOAD_GB skips them)."
    return f"{item['label']} took {pct} of the run."


def build_profile(events, data_dir=None, log_dir=None, gaps_file=None):
    gaps = suspend_gaps(events, gaps_file)
    stages = stage_table(events, gaps)
    steps = download_steps(events, gaps) + command_steps(events, gaps)
    s2 = stage2_steps(events, data_dir, gaps)
    if s2:       # the stage-2 table already contains the annotation step, and more of stage 2 than the heartbeat-watched command
        steps = [r for r in steps if not (r["stage"] == "2" and key_of(r["step"]) == "annotation")] + s2
    epochs = [event_epoch(r) for r in events if event_epoch(r) is not None]
    start, end = (min(epochs), max(epochs)) if epochs else (0, 0)
    wall = max(0.0, end - start)
    asleep = awake_clock.overlap_seconds(intervals(gaps), start, end)
    awake = max(0.0, wall - asleep)
    samples = sorted({r["sample"] for r in steps if r.get("sample")})
    callers = caller_times(log_dir, samples)
    by_step = OrderedDict()
    for r in steps:
        key = (r["stage"], r["step"])
        agg = by_step.setdefault(key, {"stage": r["stage"], "step": r["step"], "key": key_of(r["step"]), "count": 0, "seconds": 0.0, "awake_seconds": 0.0})
        agg["count"] += 1
        agg["seconds"] += r["seconds"]
        agg["awake_seconds"] += r["awake_seconds"]
    stage_awake = {s["stage"]: s["awake_seconds"] for s in stages}
    table = []
    for agg in sorted(by_step.values(), key=lambda a: (a["stage"], -a["awake_seconds"])):
        agg["share_of_stage"] = agg["awake_seconds"] / stage_awake[agg["stage"]] if stage_awake.get(agg["stage"]) else None
        agg["share_of_run"] = agg["awake_seconds"] / awake if awake else 0.0
        table.append(agg)
    merged = OrderedDict()                       # the same kind of step in several rows (e.g. 'reference annotation' and 'annotation') counts once in the top list
    for agg in table:
        if agg["awake_seconds"] <= 0:
            continue
        slot = (agg["stage"], agg["key"])
        if slot not in merged:
            merged[slot] = dict(agg, label=agg["step"])
        else:
            cur = merged[slot]
            cur["awake_seconds"] += agg["awake_seconds"]; cur["seconds"] += agg["seconds"]; cur["share_of_run"] += agg["share_of_run"]
    isolates = defaultdict(list)
    for r in steps:
        isolates[r["stage"]].append(r)
    ctx = {"callers": callers, "data_dir": data_dir, "isolates": isolates}
    top = []
    for item in sorted(merged.values(), key=lambda a: -a["awake_seconds"])[:5]:
        item = dict(item, seconds=item["awake_seconds"])
        top.append({"stage": item["stage"], "step": item["label"], "awake_seconds": item["awake_seconds"], "share_of_run": item["share_of_run"], "suggestion": suggestion(item, ctx)})
    return {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "run": {"start": start, "end": end, "wall_seconds": wall, "suspended_seconds": asleep, "awake_seconds": awake},
            "suspends": [{"start": s, "end": e, "seconds": e - s, "source": src, "sentence": awake_clock.describe(s, e) + ("" if src == "recorded" else " (inferred from a silence in the event log)")}
                         for s, e, src in gaps],
            "stages": stages, "steps": table, "isolate_steps": sorted(steps, key=lambda r: (r["stage"], r["sample"] or "", r["start"])), "callers": callers,
            "suspected_pauses": suspected_pauses([r for r in steps if r["stage"] == "2"]), "top": top}


# ------------------------------------------------------------------------------------------------------------------------- rendering
def render(profile):
    run, lines = profile["run"], []
    clock = awake_clock.clock_time
    lines.append(f"Run profile: {time.strftime('%Y-%m-%d %H:%M', time.localtime(run['start']))} to {time.strftime('%Y-%m-%d %H:%M', time.localtime(run['end']))}: "
                 f"{human(run['wall_seconds'])} on the clock, {human(run['awake_seconds'])} awake, {human(run['suspended_seconds'])} asleep.")
    lines.append("")
    if profile["suspends"]:
        lines.append("Computer asleep (the run was paused, not slow; left out of the awake figures):")
        for s in profile["suspends"]:
            lines.append(f"  {clock(s['start'])} to {clock(s['end'])} ({human(s['seconds'])}), " + ("recorded by the run" if s["source"] == "recorded" else "inferred from a silence in the event log while a command was running"))
        lines.append("")
    lines.append("Stages")
    lines.append(f"  {'stage':<6}{'clock':>12}{'awake':>12}{'asleep':>12}{'share of awake':>16}")
    for s in profile["stages"]:
        share = s["awake_seconds"] / run["awake_seconds"] if run["awake_seconds"] else 0
        lines.append(f"  {s['stage']:<6}{human(s['seconds']):>12}{human(s['awake_seconds']):>12}{human(s['suspended_seconds']):>12}{100 * share:>15.0f}%" + ("" if s["finished"] else "  (not finished)"))
    lines.append("")
    lines.append("Steps (all isolates together; awake time)")
    lines.append(f"  {'stage':<6}{'step':<28}{'isolates':>9}{'awake':>12}{'of stage':>10}{'of run':>8}")
    for a in profile["steps"]:
        if a["awake_seconds"] < 1:
            continue
        of_stage = f"{100 * a['share_of_stage']:.0f}%" if a["share_of_stage"] is not None else ""
        lines.append(f"  {a['stage']:<6}{a['step'][:27]:<28}{a['count']:>9}{human(a['awake_seconds']):>12}{of_stage:>10}{100 * a['share_of_run']:>7.0f}%")
    lines.append("")
    if profile["callers"]:
        lines.append("Annotation callers (from the annotation logs; they run at the same time)")
        for sample, rows in profile["callers"].items():
            lines.append(f"  {sample}: " + ", ".join(f"{r['caller']} {human(r['seconds'])}" + ("" if r["status"] == "ok" else f" ({r['status']})") for r in sorted(rows, key=lambda r: -r["seconds"])))
        lines.append("")
    lines.append("Per isolate (awake time, steps over 60 s)")
    per = defaultdict(list)
    for r in profile["isolate_steps"]:
        if r["awake_seconds"] >= 60:
            per[r["sample"]].append(f"stage {r['stage']} {r['step']} {human(r['awake_seconds'])}")
    for sample, parts in per.items():
        lines.append(f"  {sample}: " + "; ".join(parts))
    lines.append("")
    if profile["suspected_pauses"]:
        lines.append("Possible pauses (not confirmed: no heartbeat was running; the step took far longer than the same step on other isolates)")
        for p in profile["suspected_pauses"]:
            lines.append(f"  {p['sample']}: {p['step']} took {human(p['seconds'])} against a typical {human(p['median_seconds'])}")
        lines.append("")
    lines.append("Top costs")
    for rank, t in enumerate(profile["top"], 1):
        lines.append(f"  {rank}. stage {t['stage']}, {t['step']}: {human(t['awake_seconds'])} ({100 * t['share_of_run']:.0f}% of awake time)")
        lines.append(f"     {t['suggestion']}")
    return "\n".join(lines)


def time_spent_summary(profile, limit=4):
    """The short lines for the end of a run: 'stage 2: 2 h 39 min, 74% in reference annotation'."""
    lines = []
    for s in profile["stages"]:
        steps = [a for a in profile["steps"] if a["stage"] == s["stage"] and a["awake_seconds"] > 0]
        best = max(steps, key=lambda a: a["awake_seconds"], default=None)
        text = f"stage {s['stage']}: {human(s['awake_seconds'])}"
        if s["suspended_seconds"] >= 60:
            text += f" (+ {human(s['suspended_seconds'])} asleep)"
        if best and s["awake_seconds"] and best["awake_seconds"] / s["awake_seconds"] >= 0.3:
            text += f", {100 * best['awake_seconds'] / s['awake_seconds']:.0f}% in {best['step']}"
        lines.append(text)
    return lines[:max(limit, len(lines))]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary", action="store_true", help="only the short 'time spent' lines")
    args = parser.parse_args(argv)
    events = run_status.read_events(args.results_dir / "run_events.jsonl", max_lines=10**9)
    if not events:
        print(f"No run events found in {args.results_dir / 'run_events.jsonl'}: nothing to profile.")
        return 1
    log_dir = args.log_dir or (args.results_dir.parent / "logs")
    profile = build_profile(events, args.data_dir, log_dir if log_dir.is_dir() else None, str(args.results_dir / ".suspend_gaps"))
    if args.json:
        print(json.dumps(profile, indent=2, default=str))
    elif args.summary:
        print("\n".join(time_spent_summary(profile)))
    else:
        print(render(profile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
