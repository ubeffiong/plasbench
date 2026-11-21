#!/usr/bin/env python3
"""`plasbench status` names the CURRENT step, from the latest event of any kind (python/run_status.py).

The incident: during stage 2 (reference annotation, 11 minutes) `plasbench status` said "now: stage 1, isolate X, step download", because only stage 1 wrote stage and
sample events and the status took the last sample_start it had seen. The fixture below is the shape of that run's run_events.jsonl: stage 1 events, then a stage 2
that wrote only command events. The same status is checked for the log a fixed PlasBench writes (stage_start 2, sample_start steps), for a slow-step event and for
a partial assembly (2 of 3 assembled).
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import run_status as rs  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


T0 = 1_800_000_000.0
ISO = "negctl_acinetobacter_baumannii_gcf_008244905_1"


def ev(offset, event, **kw):
    return {"ts": "t", "epoch": T0 + offset, "pid": 1, "event": event, **kw}


def summary_of(events, tables=None, now=None):
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results"
        results.mkdir()
        (results / "run_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        for name, rows in (tables or {}).items():
            (results / name).write_text("\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8")
        (results / ".run.lock").write_text("pid=1\n", encoding="utf-8")
        (results / ".run.lock.heartbeat").write_text("x")
        import os
        os.utime(results / ".run.lock.heartbeat", (T0 + 1000, T0 + 1000))
        return rs.summarize(results, None, None, now=now or T0 + 1010, procs=[{"pid": 1, "ppid": 0, "cpu": 300.0, "rss_kb": 1000, "seconds": 5, "args": "x"}],
                            mach={})


# --- the old log shape: stage 1 events, stage 2 without any stage or sample event --------------------------------------------------------
old = [
    ev(0, "run_start", stages="0 1 2 3 4 7 5 6"),
    ev(10, "stage_start", stage="1"),
    ev(20, "sample_start", stage="1", sample=ISO, step="download", reads="SRR5739106"),
    ev(300, "download_end", stage="1", sample=ISO, status="ok"),
    ev(310, "stage_end", stage="1", seconds="300", exit="0"),
    ev(330, "command_start", what=f"{ISO} / reference annotation"),
    ev(390, "heartbeat", what=f"{ISO} / reference annotation", elapsed="60", stats="cpu=300%", system="mem_avail=6000MB"),
]
s = summary_of(old)
check("stage 2 is derived from the stage list after the last finished stage", s["stage"] == "2", s["stage"])
check("the step is the running command's label, not stage 1's 'download'", s["step"] == "reference annotation", s["step"])
check("the isolate comes from the command", s["sample"] == ISO, s["sample"])
text = rs.render(s)
check("the text says: now: stage 2 ... step reference annotation", "now: stage 2, isolate " + ISO + ", step reference annotation" in text, text)
check("the elapsed time is that of the command (680 s), not of stage 1", 670 < s["step_seconds"] < 690, s["step_seconds"])

# --- the log a fixed PlasBench writes ---------------------------------------------------------------------------------------------------
new = old[:5] + [
    ev(311, "stage_start", stage="2"),
    ev(312, "sample_start", stage="2", sample=ISO, step="truth"),
    ev(320, "sample_start", stage="2", sample=ISO, step="reference annotation"),
    ev(330, "command_start", stage="2", what=f"{ISO} / reference annotation", typical="665"),
]
s = summary_of(new)
check("with stage_start 2 the stage is 2 and the step is the annotation", s["stage"] == "2" and s["step"] == "reference annotation", (s["stage"], s["step"]))
check("the typical duration of the step is carried and shown", s["step_typical_seconds"] == 665 and "typical 11 min" in rs.render(s), rs.render(s))

between = old[:5] + [ev(311, "stage_start", stage="2"), ev(312, "sample_start", stage="2", sample=ISO, step="truth")]
s = summary_of(between)
check("a sample_start of the current stage answers (truth)", s["stage"] == "2" and s["step"] == "truth", (s["stage"], s["step"]))
check("an earlier stage's isolate and step never answer for a stage that has none", summary_of(old[:5] + [ev(311, "stage_start", stage="2")])["step"] in (None, ""),
      summary_of(old[:5] + [ev(311, "stage_start", stage="2")])["step"])

# --- a slow-step event, and a partial assembly ----------------------------------------------------------------------------------------------
slow = new + [ev(2400, "slow_step", what=f"{ISO} / reference annotation", elapsed="2000", typical="665", factor="3")]
s = summary_of(slow, now=T0 + 2410)
check("a slow_step event is shown in the summary and in the hints", s["slow_step"] and any("Slow step" in h for h in s["hints"]), s["hints"])
tables = {"assembly_status.tsv": [["sample", "status", "contigs", "reason", "runtime_seconds", "cause", "advice"],
                                   ["a", "completed", "c", "", "10", "", ""], ["b", "completed", "c", "", "10", "", ""],
                                   ["c", "failed", "", "SPAdes: spades_needs_memory", "130", "spades_needs_memory", "raise MEMORY_GB"]]}
s = summary_of(new, tables)
check("a partial assembly is said as '2 of 3 assembled; 1 failed'", s["assembly_partial"] == {"assembled": 2, "total": 3, "failed": 1}
      and any("2 of 3 isolates assembled; 1 failed" in h for h in s["hints"]), (s["assembly_partial"], s["hints"]))
# the window's run panel shows the same summary: it carries exactly these fields
for field in ("stage", "sample", "step", "step_seconds", "step_typical_seconds", "slow_step", "assembly_partial", "hints"):
    check(f"summary field '{field}' exists (the window panel reads the same summary)", field in s)
print("ALL RUN STATUS STAGE TESTS PASSED" if ok else "RUN STATUS STAGE TESTS FAILED")
sys.exit(0 if ok else 1)
