#!/usr/bin/env python3
"""Computer sleep bookkeeping (python/awake_clock.py) and its use by the annotation callers' time limits (python/annotate_reference.py).

Simulated clocks only: a sleep is a jump of the wall clock; the monotonic clock either stops during sleep (some kernels and WSL2 versions) or counts it, and the detector must
find the sleep either way, must not mistake an ordinary slow poll for a sleep, and a caller must not be killed for the time the computer was asleep."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import awake_clock as ac  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


# ---- detect_gap: both behaviours of the monotonic clock ----
check("a 5 s poll that took 5 s is no sleep", ac.detect_gap(5, 5, 5) == 0.0)
check("a slow poll (40 s on a loaded machine) is below the 60 s threshold", ac.detect_gap(45, 45, 5) == 0.0)
gap = ac.detect_gap(10_005, 5, 5)
check("monotonic clock stopped during sleep: the wall-clock jump is the gap", 9_990 < gap < 10_010, gap)
gap = ac.detect_gap(10_005, 10_005, 5)
check("monotonic clock counted the sleep: the overshoot of the wait is the gap", 9_990 < gap < 10_010, gap)
check("a clock set backwards is no sleep", ac.detect_gap(-30, -30, 5) == 0.0)

# ---- AwakeTimer with injected clocks ----
class Clock:
    def __init__(self):
        self.wall, self.mono = 1_800_000_000.0, 1000.0
    def advance(self, seconds, mono_too=True):
        self.wall += seconds
        if mono_too:
            self.mono += seconds

c = Clock()
timer = ac.AwakeTimer(gaps_file=None, threshold=60, expected=5, wall=lambda: c.wall, mono=lambda: c.mono)
for _ in range(3):
    c.advance(5); timer.tick()
c.advance(7200, mono_too=False)           # the computer sleeps for 2 hours
check("the sleep is found at the next tick", 7190 < timer.tick() < 7210)
for _ in range(2):
    c.advance(5); timer.tick()
check("elapsed leaves the sleep out (25 s of real work)", 24 <= timer.elapsed() <= 26, timer.elapsed())
check("suspended reports the sleep", 7190 < timer.suspended() < 7210, timer.suspended())

# ---- the gaps file: record once, merge overlaps, sum a window ----
with tempfile.TemporaryDirectory() as tmp:
    gaps, events = os.path.join(tmp, ".suspend_gaps"), os.path.join(tmp, "run_events.jsonl")
    t0 = 1_800_000_000
    check("a new gap is recorded", ac.record_gap(gaps, t0 + 100, t0 + 7300, events, "sentinel"))
    check("the same sleep seen by a second watcher is not recorded twice", not ac.record_gap(gaps, t0 + 110, t0 + 7290, events, "heartbeat"))
    rows = [json.loads(line) for line in open(events, encoding="utf-8")]
    check("exactly one system_suspend event, with the plain sentence", len(rows) == 1 and rows[0]["event"] == "system_suspend" and "paused, not slow" in rows[0]["message"], rows)
    check("the window t0..t0+8000 contains 7200 s of sleep", ac.overlap_seconds(ac.read_gaps(gaps), t0, t0 + 8000) == 7200)
    check("a step wholly after the sleep has none", ac.overlap_seconds(ac.read_gaps(gaps), t0 + 7300, t0 + 8000) == 0)
    check("awake_seconds of a step that straddled it", ac.awake_seconds(ac.read_gaps(gaps), t0, t0 + 7400) == 200)
    check("human text", ac.human(10_020) == "2 h 47 min" and ac.human(45) == "45 s", ac.human(10_020))
    check("describe gives the sentence the window and status show",
          ac.describe(t0, t0 + 10_020).endswith("(2 h 47 min); the run was paused, not slow.") and ac.describe(t0, t0 + 1).startswith("The computer was asleep from"))

    # ---- a caller is not killed for the time the computer slept ----
    import annotate_reference as ar
    ar.POLL_SECONDS = 0.4
    os.environ["RESULTS_DIR"] = tmp
    cmd = [sys.executable, "-c", "import time; time.sleep(2.5); print('done')"]
    out, error = ar.run(cmd, 1)
    check("without a recorded sleep a 2.5 s command is stopped at a 1 s limit", out is None and "timed out" in error, (out, error))
    now = time.time()
    with open(gaps, "a", encoding="utf-8") as handle:        # the sentinel recorded a sleep that covers the whole wait
        handle.write(f"{now - 5:.0f} {now + 600:.0f} sentinel\n")
    out, error = ar.run(cmd, 1)
    check("with the wait inside a recorded sleep the same command finishes and is not timed out", out is not None and "done" in out and not error, (out, error))
    del os.environ["RESULTS_DIR"]

# ---- `plasbench status` leaves the sleep out and says so ----
import run_status as rs  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    results = Path(tmp) / "results"
    results.mkdir()
    N = 1_800_000_000
    rows = [{"ts": "t", "epoch": N, "pid": 1, "event": "run_start", "stages": "3"},
            {"ts": "t", "epoch": N + 1, "pid": 1, "event": "stage_start", "stage": "3"},
            {"ts": "t", "epoch": N + 2, "pid": 1, "event": "command_start", "stage": "3", "what": "kleb / fastp trimming", "typical": "120"},
            {"ts": "t", "epoch": N + 62, "pid": 1, "event": "heartbeat", "stage": "3", "what": "kleb / fastp trimming", "elapsed": "60"},
            {"ts": "t", "epoch": N + 10_050, "pid": 1, "event": "system_suspend", "start_epoch": str(N + 120), "end_epoch": str(N + 10_040), "gap_seconds": "9920"},
            {"ts": "t", "epoch": N + 10_052, "pid": 1, "event": "slow_step", "stage": "3", "what": "kleb / fastp trimming", "elapsed": "10050", "typical": "120", "factor": "3"}]
    (results / "run_events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    summary = rs.summarize(results, now=N + 10_100, procs=[], mach={})
    check("status: the step's running time is awake time (about 180 s, not 10,100 s)", 100 <= summary["step_seconds"] <= 260, summary["step_seconds"])
    check("status: a slow-step note caused only by the sleep is not shown", summary["slow_step"] is None, summary["slow_step"])
    check("status: the sleep is named plainly in the summary and the hints",
          summary["suspends"] and "The computer was asleep from" in summary["suspends"][0]["sentence"] and any("paused, not slow" in h for h in summary["hints"]), summary["hints"])
    check("status: the text output has the sentence", "paused, not slow" in rs.render(summary))
    check("status: no 'no event for N minutes' complaint comes from the sleep", not any(h.startswith("No event for") for h in summary["hints"]), summary["hints"])

# ---- CPU and memory are shown as cores and GB (owner request); the raw figures stay in the JSON ----
check("475% of 6 cores reads 'about 4.8 of 6 CPU cores busy (79% of this computer)'", rs.cpu_phrase(475, 6) == "about 4.8 of 6 CPU cores busy (79% of this computer)", rs.cpu_phrase(475, 6))
check("a low figure reads '1 of 6' style", rs.cpu_phrase(100, 6).startswith("about 1 of 6 CPU cores busy"), rs.cpu_phrase(100, 6))
check("almost nothing reads as almost no CPU", rs.cpu_phrase(3, 6).startswith("almost no CPU"), rs.cpu_phrase(3, 6))
check("memory above 1 GB is in GB, below in MB", rs.human_mb(2705) == "2.6 GB" and rs.human_mb(512) == "512 MB", rs.human_mb(2705))
f = rs.cpu_figures(475, 6)
check("the JSON gets cores_busy, cpu_cores and cpu_share_of_computer", f == {"cores_busy": 4.75, "cpu_cores": 6, "cpu_share_of_computer": 79}, f)
check("a heartbeat's stats text is humanised", rs.human_stats("cpu=421% rss=1619MB procs=20").startswith("about 4.2 of "), rs.human_stats("cpu=421% rss=1619MB procs=20"))

print("\nall suspend checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
