#!/usr/bin/env python3
"""Run control (audit AU-009, AU-010, AU-011 window side): plasbench/jobrunner.py and the Jobs class in plasbench/webui.py.

  - a run that is going but prints nothing for the stall window is shown as `stalled` (its stored state stays `running`); a chatty run is not; the
    runner's own "still working" notices do not count as output; a SIGSTOPped command becomes stalled too;
  - a run that finishes with exit 0 while the pipeline left .completed_with_warnings in its results folder reads `completed_with_warnings`;
  - the command runs in its own process group (recorded in JOB_ID.pid); SIGTERM to the runner stops the whole group;
  - SIGKILL of the runner (nothing can catch it) leaves the command running: the next server stops the orphaned group, marks the run interrupted,
    and Resume is refused while any member of the group is alive and offered once none is;
  - a benchmark run cannot be started over a results folder whose lock (.run.lock) names a live process.
POSIX-only parts are skipped on Windows. Standard library only.
"""
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(Path(tmp) / "home")
os.environ["PLASBENCH_STALL_SECONDS"] = "2"
from plasbench import jobrunner, webui  # noqa: E402

POSIX = os.name != "nt"
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
        time.sleep(0.2)
    return False


def server():
    return webui.Jobs(webui.Project(ROOT))


def launch(jobs, code, argv=("demo", "--help"), label="t"):
    return jobs._launch([sys.executable, "-u", "-c", code], "python -c ...", label, None, list(argv), "plasbench", ROOT)


def state(jobs, job_id):
    return jobs.get(job_id)["display_state"]


def main():
    jobs = server()

    print("stalled is derived from output, not from the heartbeat")
    silent = launch(jobs, "import time\nprint('started', flush=True)\ntime.sleep(60)", label="silent")
    chatty = launch(jobs, "import time\nwhile True:\n    print('tick', flush=True)\n    time.sleep(0.4)", label="chatty")
    notices = launch(jobs, "import time\nwhile True:\n    print('[2026-01-01 00:00:00] still working: s1 / mob_recon (60s elapsed)', flush=True)\n    time.sleep(0.4)", label="notices")
    check("a run that has just printed is plainly running", wait(lambda: state(jobs, silent["id"]) == "running"))
    check("a silent run becomes stalled within the window while its stored state stays running",
          wait(lambda: state(jobs, silent["id"]) == "stalled", 20) and jobs.jobs[silent["id"]]["state"] == "running", jobs.get(silent["id"]))
    check("the runner's heartbeat is still fresh (the old liveness check cannot tell it from a working run)", jobrunner.is_alive(str(jobs.dir), silent["id"]))
    check("a run that keeps printing is never stalled", state(jobs, chatty["id"]) == "running", state(jobs, chatty["id"]))
    check("'still working' notices from the shell do not count as output",
          wait(lambda: state(jobs, notices["id"]) == "stalled", 20), state(jobs, notices["id"]))
    check("the job list carries the derived state too", {j["id"]: j["display_state"] for j in jobs.list()}[silent["id"]] == "stalled")
    check("PLASBENCH_STALL_SECONDS=0 turns detection off", not jobrunner.is_stalled(str(jobs.dir), silent["id"], window=0))
    if POSIX:
        info = jobrunner.read_json(jobs._paths(chatty["id"])["pid"])
        os.killpg(info["pgid"], signal.SIGSTOP)
        check("a SIGSTOPped command becomes stalled (its runner is alive and heartbeating)", wait(lambda: state(jobs, chatty["id"]) == "stalled", 20), state(jobs, chatty["id"]))
        os.killpg(info["pgid"], signal.SIGCONT)
    for job in (silent, chatty, notices):
        try:
            jobs.cancel(job["id"])
        except KeyError:
            pass

    print("completed with warnings")
    results = Path(tmp) / "results_w"
    results.mkdir()
    warned = launch(jobs, f"from pathlib import Path\nPath({str(results / '.completed_with_warnings')!r}).write_text('2 tool run(s) failed; see tool_status.tsv')",
                    argv=("run", "--results-dir", str(results)), label="warned")
    check("an exit-0 run with the pipeline's warning note is completed_with_warnings", wait(lambda: jobs.jobs[warned["id"]]["state"] == "done")
          and state(jobs, warned["id"]) == "completed_with_warnings" and "2 tool run(s) failed" in jobs.jobs[warned["id"]].get("warnings", ""), jobs.get(warned["id"]))
    clean = launch(jobs, "print('ok')", argv=("run", "--results-dir", str(Path(tmp) / "results_clean")), label="clean")
    check("an exit-0 run without the note is plain done", wait(lambda: jobs.jobs[clean["id"]]["state"] == "done") and state(jobs, clean["id"]) == "done")
    from plasbench.exitcodes import explain
    check("exit code 4 reads 'every tool run of stage 4 failed'", "every tool run" in explain(4))

    if not POSIX:
        print("SKIP: process-group checks need POSIX")
        return finish()

    print("the command leads its own process group; SIGTERM to the runner stops the group")
    spawn = ("import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
             "print('child up', flush=True)\ntime.sleep(120)")
    term = launch(jobs, spawn, label="term")
    p = jobs._paths(term["id"])
    check("pgid is recorded and is the command's own group (not the runner's)", wait(lambda: (jobrunner.read_json(p["pid"]) or {}).get("pgid")) and
          jobrunner.read_json(p["pid"])["pgid"] == jobrunner.read_json(p["pid"])["child"] != os.getpgid(jobrunner.read_json(p["pid"])["runner"]))
    info = jobrunner.read_json(p["pid"])
    wait(lambda: "child up" in jobs.get(term["id"])["log"])
    time.sleep(0.5)
    check("the grandchild is in the group", jobrunner.group_alive(info["pgid"]))
    os.kill(info["runner"], signal.SIGTERM)
    check("SIGTERM to the runner leaves no member of the group alive and records the exit", wait(lambda: not jobrunner.group_alive(info["pgid"]), 30)
          and wait(lambda: os.path.exists(p["exit"])), jobrunner.run_state(str(jobs.dir), term["id"]))

    print("SIGKILL of the runner: orphans are stopped by the next server; resume refuses while any member is alive")
    victim = launch(jobs, spawn, label="victim")
    p = jobs._paths(victim["id"])
    wait(lambda: "child up" in jobs.get(victim["id"])["log"])
    info = jobrunner.read_json(p["pid"])
    os.kill(info["runner"], signal.SIGKILL)
    time.sleep(1.0)
    check("setup: the runner is gone but the command's group is still running (the orphan)", not jobrunner.pid_alive(info["runner"]) and jobrunner.group_alive(info["pgid"]))
    # a server that cannot stop them (simulated) must refuse to resume while a member is alive
    stopped = []
    original = webui.Jobs._reap_orphans
    webui.Jobs._reap_orphans = lambda self, job_id: stopped.append(job_id)
    time.sleep(jobrunner.STALE_SECONDS + 1)   # the heartbeat must read stale
    try:
        second = server()
    finally:
        webui.Jobs._reap_orphans = original
    check("the run is interrupted, never silently running", second.jobs[victim["id"]]["state"] == "interrupted", second.jobs[victim["id"]]["state"])
    refused = ""
    try:
        second.resume(victim["id"])
    except ValueError as exc:
        refused = str(exc)
    check("Resume is refused while a member of the group is alive", "still running" in refused, refused)
    second._reap_orphans(victim["id"])
    check("the orphaned group is stopped (and the log says so)", not jobrunner.group_alive(info["pgid"]) and "its processes were stopped" in second.get(victim["id"])["log"])
    new = second.resume(victim["id"])
    check("once nothing is alive, Resume works", new["resumes"] == victim["id"])
    # the normal path: a server that starts after the kill does the reaping itself
    victim2 = launch(second, spawn, label="victim2")
    p2 = second._paths(victim2["id"])
    wait(lambda: "child up" in second.get(victim2["id"])["log"])
    info2 = jobrunner.read_json(p2["pid"])
    os.kill(info2["runner"], signal.SIGKILL)
    time.sleep(jobrunner.STALE_SECONDS + 1)
    third = server()
    check("a restarted server stops the orphans by itself: no member survives and the run is interrupted",
          wait(lambda: not jobrunner.group_alive(info2["pgid"]), 20) and third.jobs[victim2["id"]]["state"] == "interrupted")

    print("a benchmark run cannot start over a live lock")
    locked = Path(tmp) / "results_locked"
    locked.mkdir()
    (locked / ".run.lock").write_text(f"pid={os.getpid()}\npgid=\nstarted=now\nwhat=run_all.sh stages 4\n")
    refused = ""
    try:
        third.start(["run", "--results-dir", str(locked)], label="over a lock")
    except ValueError as exc:
        refused = str(exc)
    check("start refuses and names the holder", "another run is using this results folder" in refused and str(os.getpid()) in refused, refused)
    (locked / ".run.lock").write_text("pid=999999\npgid=\nstarted=long ago\nwhat=dead run\n")
    check("a lock whose process is gone does not block", third._lock_refusal(["run", "--results-dir", str(locked)]) == "")
    return finish()


def finish():
    print("ALL JOB STALL AND GROUP TESTS PASSED" if not FAILED else "FAILED: " + "; ".join(FAILED))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
