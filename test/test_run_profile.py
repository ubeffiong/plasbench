#!/usr/bin/env python3
"""`plasbench profile-run` (python/run_profile.py): where the time of a run went.

The fixture is shaped like a real laptop run (public-v4, five isolates, data folder on a Windows drive): a long stage 1 download, a stage 2 whose time is almost all one
annotation caller (ISEScan), a fastp step in stage 3 that straddled a 2 h 47 min sleep, and an annotation log in which three quick callers hit their time limit. The numbers
are made up to keep the same proportions; they are not the owner's data."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import run_profile as rp  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


T0 = 1_800_000_000


def ev(offset, event, **kw):
    return {"ts": "t", "epoch": T0 + offset, "pid": 1, "event": event, **kw}


def build_events(with_suspend_event=False):
    rows = [ev(0, "run_start"), ev(10, "stage_start", stage="1")]
    for i, (name, seconds) in enumerate([("a", 60), ("b", 120), ("c", 15_000)]):
        start = 20 + sum(s for _, s in [("a", 60), ("b", 120), ("c", 15_000)][:i])
        rows.append(ev(start, "sample_start", stage="1", sample=name, step="download"))
        rows.append(ev(start + seconds, "download_end", stage="1", sample=name, status="ok"))
    s1_end = 20 + 15_180
    # (stage 1 has no heartbeat commands: the download code writes its own progress)
    rows.append(ev(s1_end, "stage_end", stage="1", seconds="15190"))
    rows.append(ev(s1_end + 10, "stage_start", stage="2"))
    cursor = s1_end + 20
    for name, annotation in (("a", 1200), ("b", 1300), ("c", 2100)):
        rows.append(ev(cursor, "sample_start", stage="2", sample=name, step="truth"))
        rows.append(ev(cursor + 5, "command_start", stage="2", what=f"{name} / reference annotation", typical="665"))
        for beat in range(180, annotation, 60):          # a heartbeat a minute, after the first three minutes, as the real run wrote
            rows.append(ev(cursor + 5 + beat, "heartbeat", stage="2", what=f"{name} / reference annotation", elapsed=str(beat)))
        rows.append(ev(cursor + 5 + annotation, "command_end", stage="2", what=f"{name} / reference annotation", seconds=str(annotation), exit="0"))
        cursor += annotation + 60
    s2_end = cursor
    rows.append(ev(s2_end, "stage_end", stage="2", seconds=str(s2_end - s1_end - 10)))
    rows.append(ev(s2_end + 5, "stage_start", stage="3"))
    # fastp: started, then silence for 10,000 s (the computer slept), then a heartbeat and the end
    fastp = s2_end + 60
    rows.append(ev(fastp, "command_start", stage="3", what="a / fastp trimming", typical="120"))
    rows.append(ev(fastp + 10_060, "heartbeat", stage="3", what="a / fastp trimming", elapsed="10060"))
    rows.append(ev(fastp + 10_110, "command_end", stage="3", what="a / fastp trimming", seconds="10110", exit="0"))
    rows.append(ev(fastp + 10_120, "stage_end", stage="3", seconds="10180"))
    if with_suspend_event:
        rows.insert(-1, ev(fastp + 60, "system_suspend", start_epoch=str(T0 + fastp + 60), end_epoch=str(T0 + fastp + 10_050), gap_seconds="9990"))
    return rows, s1_end, s2_end, fastp


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    study = tmp / "study"
    results, logs, data = study / "results", study / "logs", tmp / "data"
    results.mkdir(parents=True)
    logs.mkdir()
    events, s1_end, s2_end, fastp = build_events()
    with open(results / "run_events.jsonl", "w", encoding="utf-8") as handle:
        for row in events:
            handle.write(json.dumps(row) + "\n")
        handle.write('{"ts": "cut off')
    for name, caller_lines in (
            ("a", ["isfinder finished in 0 s (not_evaluated, 0 feature(s))", "abricate_amr finished in 40 s (ok, 3 feature(s))", "isescan finished in 1190 s (ok, 30 feature(s))"]),
            ("b", ["mob_typer finished in 850 s (timed_out, 0 feature(s))", "isescan finished in 1290 s (ok, 59 feature(s))"]),
            ("c", ["amrfinder finished in 300 s (ok, 2 feature(s))", "isescan finished in 2090 s (ok, 37 feature(s))"])):
        (logs / f"{name}.annotation.log").write_text("".join(f"  annotation: {line}\n" for line in caller_lines), encoding="utf-8")
        (data / name).mkdir(parents=True)
        (data / name / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t900000\npl\tPLASMID\t100000\n", encoding="utf-8")

    profile = rp.build_profile(rp.run_status.read_events(results / "run_events.jsonl"), data, logs, str(results / ".suspend_gaps"))
    run = profile["run"]
    check("the run's clock time is the first to the last event", abs(run["wall_seconds"] - (fastp + 10_120)) < 2, run)
    check("one sleep is found, inferred from the silence while fastp was running", len(profile["suspends"]) == 1 and profile["suspends"][0]["source"] == "inferred", profile["suspends"])
    gap = profile["suspends"][0]["seconds"]
    check("... its length is the silence minus the last heartbeat's minute (about 10,000 s)", 9_900 <= gap <= 10_100, gap)
    stage3 = [s for s in profile["stages"] if s["stage"] == "3"][0]
    check("stage 3's awake time leaves the sleep out", stage3["awake_seconds"] < 300 and stage3["suspended_seconds"] > 9_900, stage3)
    stage2 = [s for s in profile["stages"] if s["stage"] == "2"][0]
    check("stage 2 is all awake", stage2["suspended_seconds"] == 0, stage2)
    fastp_step = [a for a in profile["steps"] if a["step"] == "fastp trimming"][0]
    check("fastp is a minute or two awake, not 10,000 s", fastp_step["awake_seconds"] < 300 and fastp_step["seconds"] > 10_000, fastp_step)
    annotation = [a for a in profile["steps"] if a["step"] == "reference annotation"][0]
    check("annotation is 100% of stage 2's steps here and sums the three isolates", annotation["seconds"] == 4600 and annotation["count"] == 3, annotation)
    check("the biggest cost is the long download", profile["top"][0]["step"] == "download", profile["top"][:2])
    ann_top = [t for t in profile["top"] if t["step"] == "reference annotation"][0]
    check("the annotation suggestion names ISEScan's share, the scope switch and a saving", "ISEScan alone was" in ann_top["suggestion"] and "ISESCAN_SCOPE=plasmids" in ann_top["suggestion"]
          and "estimated saving" in ann_top["suggestion"], ann_top["suggestion"])
    check("... and says which callers were stopped at their time limit (missing, not zero)", "b: mob_typer" in ann_top["suggestion"] and "missing, not zero" in ann_top["suggestion"], ann_top["suggestion"])
    check("the per-caller table comes from the annotation logs", profile["callers"]["c"][0]["caller"] == "amrfinder" or any(c["caller"] == "isescan" and c["seconds"] == 2090 for c in profile["callers"]["c"]), profile["callers"])
    check("at most five top costs", len(profile["top"]) <= 5)

    # a recorded system_suspend event (from the run's sentinel) is used as it is, not inferred twice
    events2, *_ = build_events(with_suspend_event=True)
    profile2 = rp.build_profile(events2, data, logs, None)
    check("a recorded system_suspend event is used and not duplicated by inference", len(profile2["suspends"]) == 1 and profile2["suspends"][0]["source"] == "recorded", profile2["suspends"])

    # the text and JSON outputs, and the CLI
    text = rp.render(profile)
    for needle in ("Stages", "Steps (all isolates together", "Annotation callers", "Top costs", "Computer asleep", "inferred from a silence in the event log"):
        check(f"the text table has '{needle}'", needle in text, text[:300])
    check("the sleep is never listed as a cost", "asleep" not in "\n".join(t["step"] for t in profile["top"]))
    cli = subprocess.run([sys.executable, str(ROOT / "python" / "run_profile.py"), "--results-dir", str(results), "--data-dir", str(data), "--json"], capture_output=True, text=True, timeout=120)
    check("run_profile.py --json prints valid JSON with the same top costs", cli.returncode == 0 and json.loads(cli.stdout)["top"][0]["step"] == "download", cli.stderr[-300:])
    cli = subprocess.run([sys.executable, "-m", "plasbench", "profile-run", "--results-dir", str(results), "--data-dir", str(data)], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    check("plasbench profile-run prints the table", cli.returncode == 0 and "Top costs" in cli.stdout, cli.stderr[-300:])
    summary = rp.time_spent_summary(profile)
    check("the short end-of-run lines say where stage 2's time went", any(line.startswith("stage 2:") and "% in reference annotation" in line for line in summary), summary)
    empty = subprocess.run([sys.executable, str(ROOT / "python" / "run_profile.py"), "--results-dir", str(tmp / "nowhere")], capture_output=True, text=True, timeout=60)
    check("an empty results folder gives a plain message, not a traceback", empty.returncode == 1 and "nothing to profile" in empty.stdout and "Traceback" not in empty.stderr)

print("\nall run-profile checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
