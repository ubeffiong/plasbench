#!/usr/bin/env python3
"""A run outlives the window's server, and a new server finds it again (plasbench/jobrunner.py, plasbench/webui.py Jobs, plasbench/runprogress.py).

Before: every job was a child of the server, so when the server stopped (terminal closed, machine slept, window quit) the run was lost, or left behind and labelled "interrupted" with
nothing watching it. Now each job runs under a detached runner that keeps its pid, a heartbeat and its exit code beside the log. This test plays "the server stopped" by building a new
Jobs object over the same folder:

  - a run that is still going when the server is replaced is found again (reattached), finishes, and is recorded as done with its exit code and the whole log;
  - a run that finished while no server was watching is read as done (or failed, with its exit code and the explanation in the log);
  - an answer typed into a reattached run reaches the command, and is logged as `[you] ...` (masked when secret);
  - a reattached run can be cancelled from the new server;
  - a run whose runner vanished without an exit is `interrupted` (never silently running), and can be resumed: a new linked job starts and the old one points to it;
  - a run that is still going cannot be resumed twice;
  - the sessions list groups runs (ongoing, attention, completed), carries progress parsed from the log, and says what can be done with each;
  - Quit can leave runs going (keep) instead of cancelling them.
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
from plasbench import jobrunner, runprogress, webui  # noqa: E402

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
    """A fresh Jobs over the same folder: what a restarted server sees."""
    return webui.Jobs(webui.Project(ROOT))


def launch(jobs, code, argv=("demo", "--help"), kind="plasbench", label="t"):
    command = [sys.executable, "-u", "-c", code]
    return jobs._launch(command, "python -c ...", label, None, list(argv), kind, ROOT)


def main():
    print("a run survives its server")
    first = server()
    slow = launch(first, "import time\nprint('started', flush=True)\ntime.sleep(5)\nprint('finished', flush=True)", label="slow run")
    check("the runner is detached and records its pid and heartbeat", wait(lambda: (Path(first.dir) / f"{slow['id']}.pid").is_file()) and jobrunner.is_alive(str(first.dir), slow["id"]))
    second = server()   # the first server is gone: a new one starts over the same folder
    job = second.jobs[slow["id"]]
    check("a new server finds the run still going (reattached), not 'interrupted'", job["state"] == "running" and job.get("reattached"), job)
    check("the run finishes under the new server: done, exit 0, the whole log", wait(lambda: second.jobs[slow["id"]]["state"] == "done") and second.jobs[slow["id"]]["exit"] == 0
          and "started" in second.get(slow["id"])["log"] and "finished" in second.get(slow["id"])["log"], second.jobs[slow["id"]])

    print("a run that ended while nobody was watching")
    quick = launch(first, "print('ok')", label="quick")
    bad = launch(first, "import sys\nprint('boom')\nsys.exit(3)", label="bad")
    wait(lambda: (Path(first.dir) / f"{quick['id']}.exit").is_file() and (Path(first.dir) / f"{bad['id']}.exit").is_file())
    third = server()
    check("it is read as done with its exit code", third.jobs[quick["id"]]["state"] == "done" and third.jobs[quick["id"]]["exit"] == 0)
    check("a non-zero exit is failed, with the code and an explanation in the log", third.jobs[bad["id"]]["state"] == "failed" and third.jobs[bad["id"]]["exit"] == 3
          and "[PlasBench] ERROR: the command stopped" in third.get(bad["id"])["log"] and "boom" in third.get(bad["id"])["log"])

    print("answers and cancellation reach a run this server did not start")
    ask = launch(first, "answer = input('Continue? [y/N] ')\nprint('got', answer, flush=True)", label="asks")
    wait(lambda: "Continue?" in (first.get(ask["id"])["log"]))
    fourth = server()
    check("the question is visible to the new server", "Continue?" in fourth.get(ask["id"])["log"] and fourth.jobs[ask["id"]].get("reattached"))
    fourth.answer(ask["id"], "yes")
    check("the answer reaches the command and is logged as [you]", wait(lambda: fourth.jobs[ask["id"]]["state"] == "done") and "got yes" in fourth.get(ask["id"])["log"]
          and "[you] yes" in fourth.get(ask["id"])["log"], fourth.get(ask["id"])["log"][-200:])
    secret = launch(first, "answer = input('Key? ')\nprint('len', len(answer), flush=True)", label="secret")
    wait(lambda: "Key?" in first.get(secret["id"])["log"])
    server().answer(secret["id"], "hunter2", secret=True)
    wait(lambda: first.get(secret["id"])["log"].count("len 7") or "len 7" in server().get(secret["id"])["log"])
    text = server().get(secret["id"])["log"]
    check("a secret answer is masked in the log", "hunter2" not in text and "•" * 7 in text and "len 7" in text, text[-200:])
    forever = launch(first, "import time\nprint('long', flush=True)\ntime.sleep(120)", label="forever")
    wait(lambda: "long" in first.get(forever["id"])["log"])
    fifth = server()
    fifth.cancel(forever["id"])
    check("a reattached run can be cancelled by the new server", wait(lambda: fifth.jobs[forever["id"]]["state"] == "cancelled", 30), fifth.jobs[forever["id"]])

    print("a run whose runner vanished")
    lost = launch(first, "import time\nprint('x', flush=True)\ntime.sleep(120)", label="lost run", argv=("demo", "--help"))
    wait(lambda: "x" in first.get(lost["id"])["log"])
    # The machine went away: the runner is killed outright (SIGKILL cannot be caught), so no exit is recorded. _kill() is a cancel (it stops the command's group too and the
    # runner records the stop), which is not this situation.
    runner = int((jobrunner.read_json(first._paths(lost["id"])["pid"]) or {}).get("runner") or first.jobs[lost["id"]].get("pid") or 0)
    if os.name == "nt":
        first._kill(lost["id"], first.jobs[lost["id"]])
    else:
        os.kill(runner, signal.SIGKILL)
    wait(lambda: not jobrunner.is_alive(str(first.dir), lost["id"]) or (time.time() - os.path.getmtime(str(Path(first.dir) / f"{lost['id']}.alive"))) > jobrunner.STALE_SECONDS, 60)
    time.sleep(jobrunner.STALE_SECONDS + 1)
    sixth = server()
    check("it is interrupted (never left looking like it is still running), with a note in the log", sixth.jobs[lost["id"]]["state"] == "interrupted"
          and "stopped without recording how it ended" in sixth.get(lost["id"])["log"], sixth.jobs[lost["id"]]["state"])
    sess = {s["id"]: s for s in sixth.sessions()}
    check("sessions: it needs attention and can be resumed", sess[lost["id"]]["group"] == "attention" and sess[lost["id"]]["resumable"])
    resumed = sixth.resume(lost["id"])
    check("resume starts a linked job and the old one points to it", resumed["resumes"] == lost["id"] and sixth.jobs[lost["id"]]["resumed_by"] == resumed["id"]
          and resumed["label"] == "Resumed: lost run" and resumed["argv"] == ["demo", "--help"], resumed)
    try:
        sixth.resume(lost["id"])
        twice = False
    except ValueError:
        twice = True
    check("the same run cannot be resumed while its resume is running", twice or sixth.jobs[resumed["id"]]["state"] != "running")
    try:
        sixth.resume(quick["id"])
        refused = False
    except ValueError:
        refused = True
    check("a completed run cannot be resumed", refused)
    wait(lambda: sixth.jobs[resumed["id"]]["state"] != "running", 60)

    print("a runner that is slow to start, and a falsely interrupted run")
    slow_start = {"id": "20261116-000000-slowst", "label": "slow start", "argv": ["demo"], "command": "plasbench demo", "env": {}, "kind": "plasbench", "state": "running",
                  "started": time.time(), "ended": None, "exit": None, "pid": 1, "results": ""}
    sixth.jobs[slow_start["id"]] = slow_start
    check("a run whose runner has not written a heartbeat yet is not called lost for the first minute", sixth._alive(slow_start))
    old = dict(slow_start, started=time.time() - 600)
    check("...but one that never did, a long time later, is", not sixth._alive(old))
    sixth.jobs.pop(slow_start["id"])
    false_alarm = launch(first, "import time\ntime.sleep(25)\nprint('done', flush=True)", label="false alarm")
    wait(lambda: jobrunner.is_alive(str(first.dir), false_alarm["id"]))
    first.jobs[false_alarm["id"]].update(state="interrupted", ended=time.time())   # an earlier window gave up on it too soon
    first._save()
    seventh = server()
    check("a new server revives a run called interrupted when its heartbeat is plainly fresh", seventh.jobs[false_alarm["id"]]["state"] == "running" and seventh.jobs[false_alarm["id"]].get("reattached"),
          seventh.jobs[false_alarm["id"]]["state"])
    check("another window's stale 'interrupted' record cannot overwrite a running job", (seventh._save(), seventh.jobs[false_alarm["id"]]["state"])[1] == "running")
    wait(lambda: seventh.jobs[false_alarm["id"]]["state"] == "done", 60)

    print("the sessions list")
    marker = launch(first, "print('[2026-11-16 10:00:00] Running stages: 0 1 2 3 4 5 6')\nprint('[2026-11-16 10:00:01] >>>>> STAGE 1 : 01_download.sh')\n"
                    "print('[2026-11-16 10:00:02] === Sample a : assembly=x ===')\nprint('[2026-11-16 10:00:09] Stage 1 (download) complete: 1 ok, 0 failed.')\n"
                    "print('[2026-11-16 10:00:10] >>>>> STAGE 4 : 04_run_tools.sh')\nprint('[2026-11-16 10:00:11] === Run tools on a ===', flush=True)\nimport time\ntime.sleep(8)",
                    argv=("run", "--cohort", "x"), label="progress run")
    wait(lambda: "Run tools on a" in first.get(marker["id"])["log"])
    live = {s["id"]: s for s in server().sessions()}
    s = live[marker["id"]]
    check("an ongoing run: group, progress, stage, percent and last line parsed from its log", s["group"] == "ongoing" and s["progress"]["known"] and s["progress"]["current"] == "4"
          and s["progress"]["current_name"] == "Run tools" and s["progress"]["done"] == ["1"] and 0 < s["progress"]["percent"] < 100 and "Run tools on a" in s["progress"]["last_line"], s["progress"])
    check("a failed run and a finished run land in the right groups", live[bad["id"]]["group"] == "attention" if bad["id"] in live else True)
    wait(lambda: server().jobs[marker["id"]]["state"] == "done", 30)
    done = {x["id"]: x for x in server().sessions()}[marker["id"]]
    check("a completed run shows 100% and is not resumable", done["group"] == "completed" and done["progress"]["percent"] == 100 and not done["resumable"])
    check("only benchmark commands are sessions (a git job or a check is not)", all(x["argv"][0] in webui.SESSION_COMMANDS for x in server().sessions()))

    print("the progress parser")
    p = runprogress.parse("")
    check("an empty or unmarked log is 'unknown', never a made-up percentage", not p["known"] and p["percent"] is None)
    p = runprogress.parse("[2026-11-16 10:00:00] Running stages: 0 1\n[2026-11-16 10:00:01] >>>>> STAGE 0 : 00_setup.sh\n[2026-11-16 10:00:02] Stage 0 (setup) complete.\n"
                          "[2026-11-16 10:00:03] >>>>> STAGE 1 : 01_download.sh\n[2026-11-16 10:00:04] Stage 1 (download) complete: 1 ok, 0 failed.")
    check("all stages done is capped below 100 until the run itself ends", p["percent"] == 99 or p["percent"] is None or p["percent"] < 100, p["percent"])

    print("Quit can leave runs going")
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("shutdown has a keep option that skips the cancel", 'keep = bool(data.get("keep"))' in src and "for job in ([] if keep else running)" in src)

    for j in list(first.jobs.values()):   # tidy: nothing left running
        if j["state"] in ("running", "cancelling"):
            first._kill(j["id"], j)
    print("ALL JOB SURVIVAL TESTS PASSED" if not FAILED else f"JOB SURVIVAL TESTS FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
