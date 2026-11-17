#!/usr/bin/env python3
"""A laptop that sleeps must not turn a live run into "interrupted + Resume" (plasbench/webui.py Jobs._watch_loop and Jobs.resume).

When the computer sleeps or hibernates the detached runner and the window's server stop together. On waking, the heartbeat file looks old for a
few seconds, before the runner writes its next one. The watcher used to mark the run `interrupted` and then stop watching, so the page kept saying
"Interrupted" after the runner was going again, and Resume (which only refused an identical command that was `running`) started a SECOND pipeline
into the same results folder.

This test plays the wake-up with a real runner process: it makes the heartbeat look old, waits for the run to be called interrupted, then lets the
runner write its next heartbeat. It checks that
  - the run goes back to `running` by itself (and says so in its log), and finishes as `done`;
  - Resume is refused while the original runner is alive, including in the moment before the watcher has noticed;
  - no second job was started;
(A runner that really is gone staying `interrupted` and resumable is covered by test_job_survival.py.)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(Path(tmp) / "home")
from plasbench import jobrunner, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def wait(cond, seconds=40):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def main():
    jobs = webui.Jobs(webui.Project(ROOT))
    command = [sys.executable, "-u", "-c", "import time; time.sleep(22)"]
    job = jobs._launch(command, "python -c ...", "sleepy run", None, ["demo", "--help"], "plasbench", ROOT)
    job_id = job["id"]
    alive_file = jobrunner.paths(str(jobs.dir), job_id)["alive"]
    check("the run starts and writes a heartbeat", wait(lambda: os.path.exists(alive_file), 20))

    print("the computer sleeps: the heartbeat looks old")
    went_interrupted = False
    for _ in range(8):   # the runner refreshes its heartbeat every few seconds; try until the watcher sees the stale one first
        old = time.time() - 120
        os.utime(alive_file, (old, old))
        if wait(lambda: jobs.jobs[job_id]["state"] == "interrupted", 3):
            went_interrupted = True
            break
    check("a stale heartbeat marks the run interrupted (as before)", went_interrupted, jobs.jobs[job_id]["state"])

    print("the computer wakes: the runner writes its next heartbeat")
    check("the run goes back to running by itself", wait(lambda: jobs.jobs[job_id]["state"] == "running", 15), jobs.jobs[job_id]["state"])
    log_file = Path(jobrunner.paths(str(jobs.dir), job_id)["log"])
    read_log = lambda: log_file.read_text(encoding="utf-8", errors="replace")
    wait(lambda: "nothing to resume" in read_log(), 10)   # the state flips a moment before the note is written
    check("the log says it was only paused", "still going" in read_log() and "nothing to resume" in read_log(), read_log()[-300:])
    check("it is not offered for Resume any more", not jobs.jobs[job_id]["state"] in webui.RESUMABLE_STATES)

    before = len(jobs.jobs)
    try:
        jobs.resume(job_id)
        refused = False
    except ValueError:
        refused = True   # it is `running` again, so the state check refuses it ("only a failed, interrupted or cancelled run can be resumed")
    check("Resume is refused while the original runner is alive", refused)

    print("the window before the watcher has noticed: state says interrupted but the runner is alive")
    jobs.jobs[job_id]["state"] = "interrupted"
    try:
        jobs.resume(job_id)
        refused = False
    except ValueError as error:
        refused = "still going" in str(error)
    check("Resume checks the heartbeat itself, not only the recorded state", refused)
    check("no second job was started", len(jobs.jobs) == before, f"{before} -> {len(jobs.jobs)}")

    check("the run finishes and is recorded as done", wait(lambda: jobs.jobs[job_id]["state"] == "done", 40), jobs.jobs[job_id]["state"])
    for j in list(jobs.jobs.values()):
        if j['state'] in ('running', 'cancelling'):
            jobs.cancel(j['id'])
    time.sleep(1)

main()
print("ALL JOB SLEEP/RESUME TESTS PASSED" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
