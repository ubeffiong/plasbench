#!/usr/bin/env python3
"""What is this run doing right now, and why might it look stuck?

  plasbench status   [--study NAME | --results-dir DIR] [--json]
  plasbench diagnose [--study NAME | --results-dir DIR] [--json]     (the same, plus the process list and the full hint set)

A long run is quiet by nature: a download, a trim or an assembly writes to its own log, not to the run's. Every stage now also appends one JSON line per step to
RESULTS_DIR/run_events.jsonl (scripts/lib.sh run_event: stage start and end, isolate steps, command start and end, heartbeats with CPU and memory), and a run holds
RESULTS_DIR/.run.lock with a heartbeat file. This reads those, the status tables, the process tree under the run's lock and the machine's memory and disk, and says
in plain words: the state (running, finished, stopped without recording why), the stage, isolate and step it is in and for how long, progress so far, what the
processes are doing, and hints that follow from the evidence. A hint is only given when the figures behind it are shown beside it; nothing is guessed.

Standard library only. The process table is read with `ps`, so on Windows (outside WSL) it reports what the files say and no process figures.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HEARTBEAT_FRESH_SECONDS = 90          # a run whose lock heartbeat is younger than this is alive
QUIET_AFTER_SECONDS = 900             # no event for this long while a process lives: say so
LONG_STEP_SECONDS = 3 * 3600          # a single step this long deserves a plain note
BIG_READS_BYTES = 5 * 10**9           # compressed paired reads above this are "very large"


# --------------------------------------------------------------------------------------------------------------------------- reading
def read_events(path, max_lines=20000):
    """The last `max_lines` events of run_events.jsonl; lines that are not valid JSON (a write cut off mid-line) are skipped."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 8_000_000))
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in data.splitlines()[-max_lines:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and "event" in row:
            out.append(row)
    return out


def read_lock(results_dir, now=None):
    """{'pid', 'pgid', 'started', 'what', 'heartbeat_age'} from .run.lock and its heartbeat file, or None when there is no lock."""
    now = time.time() if now is None else now
    lock = {}
    try:
        with open(os.path.join(results_dir, ".run.lock"), encoding="utf-8") as handle:
            for line in handle:
                if "=" in line:
                    key, value = line.rstrip("\n").split("=", 1)
                    lock[key] = value
    except OSError:
        return None
    try:
        lock["heartbeat_age"] = max(0.0, now - os.path.getmtime(os.path.join(results_dir, ".run.lock.heartbeat")))
    except OSError:
        lock["heartbeat_age"] = None
    return lock


def read_tsv(path):
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [line.rstrip("\n").split("\t") for line in handle if line.strip()]
    except OSError:
        return []
    if not lines:
        return []
    header = lines[0]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in lines[1:]]


def process_table():
    """[{pid, ppid, cpu, rss_kb, seconds, args}] from ps; [] when ps is not available (native Windows)."""
    if not shutil.which("ps"):
        return []
    for fmt in ("pid=,ppid=,pcpu=,rss=,etimes=,args=", "pid=,ppid=,pcpu=,rss=,args="):
        try:
            out = subprocess.run(["ps", "-eo", fmt], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return []
        if out.returncode != 0:
            continue
        rows = []
        for line in out.stdout.splitlines():
            parts = line.split(None, 5 if "etimes" in fmt else 4)
            try:
                if "etimes" in fmt and len(parts) >= 6:
                    rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "cpu": float(parts[2]), "rss_kb": int(parts[3]), "seconds": int(parts[4]), "args": parts[5]})
                elif "etimes" not in fmt and len(parts) >= 5:
                    rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "cpu": float(parts[2]), "rss_kb": int(parts[3]), "seconds": None, "args": parts[4]})
            except ValueError:
                continue
        return rows
    return []


def descendants(table, root_pid):
    """The rows of root_pid and everything it started (a cycle or a missing parent ends the walk)."""
    by_parent = {}
    for row in table:
        by_parent.setdefault(row["ppid"], []).append(row)
    out, stack, seen = [], [root_pid], set()
    index = {row["pid"]: row for row in table}
    if root_pid in index:
        out.append(index[root_pid])
        seen.add(root_pid)
    while stack:
        pid = stack.pop()
        for child in by_parent.get(pid, []):
            if child["pid"] in seen:        # each process once, and a cycle ends the walk
                continue
            seen.add(child["pid"])
            out.append(child)
            stack.append(child["pid"])
    return out


def machine(path):
    """{'mem_avail_mb', 'swap_used_mb', 'disk_free_gb'}: whatever can be read (Linux /proc/meminfo; shutil for the disk)."""
    out = {}
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
        if "MemAvailable" in info:
            out["mem_avail_mb"] = info["MemAvailable"] // 1024
        if "SwapTotal" in info and "SwapFree" in info:
            out["swap_used_mb"] = (info["SwapTotal"] - info["SwapFree"]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        out["disk_free_gb"] = shutil.disk_usage(path).free // 10**9
    except OSError:
        pass
    return out


# ------------------------------------------------------------------------------------------------------------------------- summarising
def human_seconds(seconds):
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def human_bytes(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def event_time(row):
    try:
        return float(row.get("epoch"))
    except (TypeError, ValueError):
        return None


def progress(results_dir):
    """Counts per stage from the status tables the stages write."""
    out = {}
    tables = (("download", "download_status.tsv", "status", ("ok",)), ("assembly", "assembly_status.tsv", "status", ("completed", "reused")),
              ("tools", "tool_status.tsv", "status", ("completed", "reused")))
    for name, filename, column, good in tables:
        rows = read_tsv(os.path.join(results_dir, filename))
        if not rows:
            continue
        total = len(rows)
        done = sum(1 for r in rows if (r.get(column) or "") in good)
        failed = sum(1 for r in rows if (r.get(column) or "") in ("failed", "infrastructure_failure"))
        out[name] = {"rows": total, "ok": done, "failed": failed}
    return out


def assembly_failures(results_dir, log_dir=None):
    """Why isolates failed to assemble: the cause and advice stage 3 wrote into assembly_status.tsv (columns `cause`, `advice`), or, for a status file from before
    those columns existed, the classifier's reading of the isolate's own log. {} when nothing failed."""
    rows = [r for r in read_tsv(os.path.join(results_dir, "assembly_status.tsv")) if (r.get("status") or "") == "failed"]
    if not rows:
        return {}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import assembler_diagnosis
    except ImportError:
        assembler_diagnosis = None
    items = []
    for r in rows:
        item = {"sample": r.get("sample", ""), "cause": r.get("cause") or "", "advice": r.get("advice") or "", "reason": r.get("reason") or "", "title": "", "evidence": ""}
        if (not item["cause"]) and assembler_diagnosis and log_dir:
            newest = None
            for tool in ("spades", "unicycler", "fastp"):
                f = Path(log_dir) / f"{item['sample']}.{tool}.log"
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if newest is None or m > newest[0]:
                    newest = (m, f)
            if newest:
                d = assembler_diagnosis.diagnose(assembler_diagnosis.read_tail(str(newest[1])), {"log": str(newest[1]), "sample": item["sample"]})
                item.update(cause=d["cause"], advice=d["advice"], title=d["title"], evidence=d["evidence_lines"][-1] if d["evidence_lines"] else "", log=str(newest[1]))
        items.append(item)
    causes = sorted({i["cause"] for i in items if i["cause"]})
    return {"failed": len(items), "items": items[:20], "same_cause": causes[0] if len(causes) == 1 and len(items) > 1 else ""}


def reads_size(data_dir, sample):
    """Compressed bytes of the sample's paired read files in the data folder (0 when not there)."""
    total = 0
    d = Path(data_dir) / sample if data_dir and sample else None
    if d and d.is_dir():
        for f in d.glob("*_[12].fastq.gz"):
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def active_downloads(results_dir, now):
    """Reads being downloaded now, from results/download_progress.json (written by python/fetch_ena_reads.py: bytes actually received): [{run, line, state, done_bytes, total_bytes}]."""
    try:
        with open(os.path.join(str(results_dir), "download_progress.json"), encoding="utf-8") as handle:
            entries = json.load(handle).get("isolates", {})
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for run, e in entries.items():
        try:
            if e.get("state") in ("downloading", "stalled", "verifying", "moving") and now - float(e.get("updated", 0)) < 300:
                out.append({"run": run, "sample": e.get("sample", ""), "line": e.get("line", ""), "state": e.get("state"), "done_bytes": e.get("done_bytes", 0), "total_bytes": e.get("total_bytes", 0)})
        except (TypeError, ValueError):
            continue
    return out


def summarize(results_dir, log_dir=None, data_dir=None, now=None, procs=None, mach=None):
    """Everything status/diagnose knows, as one dict (also what --json prints)."""
    now = time.time() if now is None else now
    results_dir = str(results_dir)
    events = read_events(os.path.join(results_dir, "run_events.jsonl"))
    lock = read_lock(results_dir, now)
    table = process_table() if procs is None else procs
    summary = {"results_dir": results_dir, "now": now, "events": len(events), "lock": lock, "progress": progress(results_dir)}

    # --- state -------------------------------------------------------------------------------------------------------------------
    lock_pid = None
    try:
        lock_pid = int((lock or {}).get("pid", ""))
    except ValueError:
        pass
    alive_rows = descendants(table, lock_pid) if lock_pid and table else []
    heartbeat_age = (lock or {}).get("heartbeat_age")
    fresh = heartbeat_age is not None and heartbeat_age < HEARTBEAT_FRESH_SECONDS
    last_event = events[-1] if events else None
    ended = next((e for e in reversed(events) if e["event"] == "run_end"), None)
    started = next((e for e in reversed(events) if e["event"] == "run_start"), None)
    if lock and (fresh or alive_rows):
        state = "running"
    elif ended and (not started or (event_time(ended) or 0) >= (event_time(started) or 0)):
        state = "finished"
    elif lock or os.path.exists(os.path.join(results_dir, ".run_in_progress")):
        state = "stopped"      # it left its markers and nothing is alive: the run was cut off
    elif events:
        state = "idle"
    else:
        state = "no-run"
    summary["state"] = state
    summary["last_event"] = last_event

    # --- where it is -------------------------------------------------------------------------------------------------------------
    # The LATEST event of any kind decides; an older stage's sample or step never answers for the current one (it used to: during stage 2 the status said
    # "stage 1, step download" because only stage 1 wrote sample events). Events written by a stage that did not mark its start (older logs) belong to the stage
    # after the last stage that did.
    stage_list = (started or {}).get("stages", "").split()
    last_stage_idx, stage = None, None
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("stage"):
            last_stage_idx, stage = i, str(events[i]["stage"])
            break
    scope_from = 0 if last_stage_idx is None else last_stage_idx
    if last_stage_idx is not None:
        later = [e for e in events[last_stage_idx + 1:] if e["event"] not in ("run_end",)]
        if events[last_stage_idx]["event"] == "stage_end" and later:
            if stage in stage_list and stage_list.index(stage) + 1 < len(stage_list):
                stage = stage_list[stage_list.index(stage) + 1]
            scope_from = last_stage_idx + 1
        elif events[last_stage_idx]["event"] == "stage_start":
            scope_from = last_stage_idx
        else:   # an event inside the stage: the stage began at its stage_start
            for j in range(last_stage_idx, -1, -1):
                if events[j]["event"] == "stage_start" and str(events[j].get("stage")) == stage:
                    scope_from = j
                    break
    elif stage_list and events:
        stage = None
    scoped = events[scope_from:]
    sample = step = None
    sample_t = None
    for e in reversed(scoped):
        if e["event"] == "sample_start":
            sample, step, sample_t = e.get("sample"), e.get("step"), event_time(e)
            break
    starts = {}
    for e in events:
        if e["event"] == "command_start":
            starts[e.get("what", "")] = e
        elif e["event"] == "command_end":
            starts.pop(e.get("what", ""), None)
    open_command = list(starts.values())[-1] if starts else None
    since = sample_t
    typical = None
    if open_command is not None:
        cmd_t = event_time(open_command)
        what = open_command.get("what", "")
        prefix, sep, label = what.partition(" / ")
        if sample_t is None or (cmd_t or 0) >= sample_t:
            # the command is the more specific (and newer) answer: "<isolate> / ISEScan-style label"
            if sep:
                sample, step = sample or prefix, label
                if sample_t is not None and sample != prefix:
                    sample = prefix
            else:
                step = step or what
        since = cmd_t or since
        try:
            typical = float(open_command.get("typical")) if open_command.get("typical") else None
        except ValueError:
            typical = None
    last_beat_any = next((e for e in reversed(scoped) if e["event"] == "heartbeat"), None)
    if step is None and last_beat_any:
        step = (last_beat_any.get("what") or "").partition(" / ")[2] or last_beat_any.get("what")
        sample = sample or (last_beat_any.get("what") or "").partition(" / ")[0] or None
    summary.update(stage=stage, sample=sample, step=step, command=(open_command or {}).get("what"), step_seconds=(now - since) if since else None,
                   step_typical_seconds=typical)
    slow = [e for e in events if e["event"] == "slow_step" and (not open_command or e.get("what") == open_command.get("what"))]
    summary["slow_step"] = slow[-1] if (slow and open_command) else None
    beats = [e for e in events if e["event"] == "heartbeat" and (not open_command or e.get("what") == open_command.get("what"))]
    summary["last_heartbeat"] = beats[-1] if beats else None
    summary["seconds_since_event"] = (now - event_time(last_event)) if last_event and event_time(last_event) else None

    # --- processes and machine -----------------------------------------------------------------------------------------------------
    cpu = sum(r["cpu"] for r in alive_rows)
    rss = sum(r["rss_kb"] for r in alive_rows)
    top = sorted(alive_rows, key=lambda r: -r["cpu"])[:6]
    summary["processes"] = {"count": len(alive_rows), "cpu_percent": round(cpu), "rss_mb": rss // 1024,
                            "top": [{"pid": r["pid"], "cpu": r["cpu"], "rss_mb": r["rss_kb"] // 1024, "seconds": r["seconds"], "args": r["args"][:160]} for r in top]}
    summary["machine"] = machine(results_dir) if mach is None else mach

    # --- the sample's reads (for the big-read-set hint) ------------------------------------------------------------------------------
    summary["reads_bytes"] = reads_size(data_dir, sample) if sample else 0
    if log_dir and sample:
        newest = None
        for f in Path(log_dir).glob(f"{sample}.*.log"):
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest[0]:
                newest = (m, f)
        if newest:
            summary["newest_log"] = {"file": str(newest[1]), "idle_seconds": round(now - newest[0])}
            try:
                lines = [ln for ln in newest[1].read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
                summary["newest_log"]["last_line"] = lines[-1][:200] if lines else ""
            except OSError:
                pass
    summary["downloads"] = active_downloads(results_dir, now)
    summary["adjustments"] = [{"sample": e.get("sample", ""), "tool": e.get("tool", ""), "what": e.get("what", ""), "message": e.get("message", ""), "from": e.get("from", ""),
                               "to": e.get("to", "")} for e in events if e["event"] == "resource_adjust"][-10:]
    summary["assembly_failures"] = assembly_failures(results_dir, log_dir)
    asm = (summary.get("progress") or {}).get("assembly")
    summary["assembly_partial"] = {"assembled": asm["ok"], "total": asm["rows"], "failed": asm["failed"]} if asm and 0 < asm["ok"] < asm["rows"] else None
    summary["hints"] = hints(summary)
    return summary


def hints(s):
    """Plain statements that follow from the figures in the summary; each carries its evidence."""
    out = []
    state = s["state"]
    m = s.get("machine") or {}
    procs = s.get("processes") or {}
    secs = s.get("step_seconds")
    if state == "stopped":
        out.append("The run left its markers (.run.lock or .run_in_progress) but no process of it is alive: it was cut off (the terminal, WSL or the computer ended it, or it was "
                   "killed) without a chance to say why. Re-running resumes: finished isolates and tool results are reused.")
    if state == "running":
        if procs.get("count") and procs.get("cpu_percent", 0) >= 50:
            out.append(f"It is working: the run's processes use {procs['cpu_percent']}% CPU and {procs['rss_mb']} MB of memory.")
        elif procs.get("count"):
            out.append(f"The run's processes use only {procs['cpu_percent']}% CPU. That is normal while it waits on the network (a download) and unusual during an assembly. "
                       "If the newest log below has not changed for a long time as well, it may be waiting on something.")
        since_event = s.get("seconds_since_event")
        if since_event is not None and since_event > QUIET_AFTER_SECONDS and procs.get("count"):
            out.append(f"No event for {human_seconds(since_event)}, but its processes are alive: a long single step (a download, a trim, an assembly) writes to its own log, not to the run's.")
    if secs and secs > LONG_STEP_SECONDS:
        out.append(f"This step has run for {human_seconds(secs)}.")
    reads = s.get("reads_bytes") or 0
    if reads > BIG_READS_BYTES:
        out.append(f"This isolate's reads are {human_bytes(reads)} compressed (above {human_bytes(BIG_READS_BYTES)}). Trimming and assembling a read set that large can take many hours and "
                   "a great deal of memory. PlasBench does not skip an isolate for its size. READ_DEPTH_CAP_X (default 150) downloads only the first read pairs of a run deeper than that, "
                   "when the reference size is known; if this set was downloaded whole, delete its two .fastq.gz files and run again, or set READ_DEPTH_CAP_X lower.")
    avail = m.get("mem_avail_mb")
    if avail is not None and avail < 500:
        out.append(f"Only {avail} MB of memory is available on this computer: a tool may be killed (exit 137) or crawl. Lower THREADS or ASSEMBLY_MEMORY_GB.")
    if m.get("swap_used_mb", 0) > 1000 and (avail is None or avail < 2000):
        out.append(f"{m['swap_used_mb']} MB of swap is in use while little memory is free: the machine is swapping, which makes everything very slow.")
    for adj in (s.get("adjustments") or [])[-3:]:
        if adj.get("what") == "skipped" or adj.get("what") == "memory" and adj.get("to") == "":
            out.append(f"Resource adjustment: {adj.get('message') or adj.get('what')}")
        elif adj.get("message"):
            out.append(f"Resources adjusted automatically (AUTO_RESOURCES): {adj['message']}")
        elif adj.get("what") == "memory":
            out.append(f"Resources adjusted automatically (AUTO_RESOURCES): memory raised to {adj.get('to')} GB for isolate {adj.get('sample')} (from {adj.get('from')} GB)")
        elif adj.get("what") == "skipped":
            out.append(f"Isolate {adj.get('sample')} was skipped: it needs more memory than is free.")
    part = s.get("assembly_partial")
    if part:
        causes = sorted({i["cause"] for i in (s.get("assembly_failures") or {}).get("items", []) if i.get("cause")})
        out.append(f"Partial assembly: {part['assembled']} of {part['total']} isolates assembled; {part['failed']} failed" + (f" ({', '.join(causes)})" if causes else "")
                   + ". The isolates that assembled go on to the tools; the failed ones are listed with their cause in assembly_status.tsv.")
    slow = s.get("slow_step")
    if slow:
        out.append(f"Slow step: {slow.get('what')} has run for {human_seconds(float(slow.get('elapsed') or 0))}, more than {slow.get('factor', 3)}x its typical {human_seconds(float(slow.get('typical') or 0))}. "
                   "If its log has not changed and the CPU is near 0% it may be stuck; otherwise it may just be a big isolate.")
    asm = s.get("assembly_failures") or {}
    if asm.get("same_cause"):
        first = asm["items"][0]
        out.append(f"All {asm['failed']} failed assemblies have the same cause ({asm['same_cause']}), so it is the computer or the settings, not the isolates: {first['advice']}")
    for item in (asm.get("items") or [])[:3] if not asm.get("same_cause") else []:
        if item.get("cause"):
            out.append(f"Assembly of {item['sample']} failed ({item['cause']}): {item['advice']}")
    disk = m.get("disk_free_gb")
    if disk is not None and disk < 5:
        out.append(f"Only {disk} GB of disk is free where the results are: downloads and assemblies need several times the size of the reads.")
    return out


# ----------------------------------------------------------------------------------------------------------------------------- output
def render(s, diagnose=False):
    lines = []
    state_text = {"running": "RUNNING", "finished": "FINISHED", "stopped": "STOPPED (cut off, no record of why)", "idle": "not running", "no-run": "no run found here"}[s["state"]]
    lines.append(f"Run in {s['results_dir']}: {state_text}")
    lock = s.get("lock") or {}
    if lock:
        age = lock.get("heartbeat_age")
        lines.append(f"  lock: pid {lock.get('pid', '?')}, started {lock.get('started', '?')}, heartbeat {human_seconds(age) + ' ago' if age is not None else 'none'}")
    if s.get("stage") or s.get("sample"):
        where = f"stage {s['stage']}" if s.get("stage") else "stage ?"
        if s.get("sample"):
            where += f", isolate {s['sample']}"
        if s.get("step"):
            where += f", step {s['step']}"
        lines.append(f"  now: {where}" + (f" (running for {human_seconds(s['step_seconds'])}" + (f", typical {human_seconds(s['step_typical_seconds'])}" if s.get("step_typical_seconds") else "") + ")" if s.get("step_seconds") is not None else ""))
    if s.get("command"):
        lines.append(f"  command: {s['command']}")
    beat = s.get("last_heartbeat")
    if beat:
        lines.append(f"  last heartbeat {human_seconds(s['now'] - (event_time(beat) or s['now']))} ago: {beat.get('stats', '')} | {beat.get('system', '')}")
    elif s.get("last_event"):
        e = s["last_event"]
        lines.append(f"  last event {human_seconds(s['seconds_since_event'] or 0)} ago: {e.get('event')} {e.get('what') or e.get('sample') or ''}".rstrip())
    for d in s.get("downloads") or []:
        lines.append(f"  download: {d['line']}")
    for name, p in (s.get("progress") or {}).items():
        lines.append(f"  {name}: {p['ok']} of {p['rows']} ok" + (f", {p['failed']} failed" if p["failed"] else ""))
    procs = s.get("processes") or {}
    if procs.get("count"):
        lines.append(f"  processes: {procs['count']} ({procs['cpu_percent']}% CPU, {procs['rss_mb']} MB)")
        if diagnose:
            for r in procs["top"]:
                lines.append(f"    pid {r['pid']:>7}  cpu {r['cpu']:>6.1f}%  {r['rss_mb']:>6} MB  {r['args']}")
    m = s.get("machine") or {}
    if m:
        lines.append("  machine: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in m.items()))
    asm = s.get("assembly_failures") or {}
    if asm:
        lines.append(f"  assembly failures: {asm['failed']}" + (f", all for the same reason: {asm['same_cause']}" if asm.get("same_cause") else ""))
        for item in asm["items"][:5]:
            lines.append(f"    {item['sample']}: {item['cause'] or 'cause not recorded'}" + (f" ({item['evidence']})" if item.get("evidence") else ""))
    log = s.get("newest_log")
    if log:
        lines.append(f"  newest log for this isolate: {log['file']} (changed {human_seconds(log['idle_seconds'])} ago)" + (f": {log['last_line']}" if log.get("last_line") else ""))
    if s.get("reads_bytes"):
        lines.append(f"  this isolate's reads: {human_bytes(s['reads_bytes'])} compressed")
    for adj in (s.get("adjustments") or [])[-3:]:
        lines.append("  adjusted: " + (adj.get("message") or f"{adj.get('what')} for {adj.get('sample')}: {adj.get('from')} -> {adj.get('to')}"))
    if s["hints"]:
        lines.append("What this means:")
        lines.extend(f"  - {h}" for h in s["hints"])
    elif s["state"] == "running":
        lines.append("Nothing in the figures suggests a problem.")
    if s["events"] == 0 and s["state"] != "no-run":
        lines.append("(No run_events.jsonl yet: this run started before PlasBench kept one, so only the lock and the tables are shown.)")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--log-dir")
    ap.add_argument("--data-dir")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--diagnose", action="store_true", help="also list the busiest processes")
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="repeat every SECONDS until interrupted")
    args = ap.parse_args(argv)
    log_dir = args.log_dir or str(Path(args.results_dir).parent / "logs")
    data_dir = args.data_dir or os.environ.get("DATA_DIR") or str(Path.home() / ".local" / "share" / "plasbench" / "data")
    while True:
        summary = summarize(args.results_dir, log_dir=log_dir, data_dir=data_dir)
        print(json.dumps(summary, indent=2, default=str) if args.json else render(summary, args.diagnose))
        if not args.watch:
            return 0
        try:
            time.sleep(max(2, args.watch))
        except KeyboardInterrupt:
            return 0
        print()


if __name__ == "__main__":
    sys.exit(main())
