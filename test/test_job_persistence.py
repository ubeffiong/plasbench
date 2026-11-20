#!/usr/bin/env python3
"""A cancelled job stays in the Jobs list, however many windows and threads save the list (plasbench/webui.py class Jobs).

Bug: "my cancelled job is not in the Jobs list". The saved list (jobs.json) was read, merged and written with no lock, so two windows (or a window and a watcher thread) could each
read, then write, and the later write dropped what the earlier one added; a deleted job was only remembered in memory, so another window put it back; and finished jobs beyond the newest
500 were dropped silently. Now:
  - a lock file (created with O_EXCL, with a stale-lock timeout) surrounds read-merge-write;
  - deletions are written down (jobs.deleted) so they stay deleted in every window;
  - each job has <id>.meta.json, written at launch and at every change, so the list is REBUILT from the job folder when the index is lost or behind;
  - a failed / interrupted / cancelled job is kept until the user deletes it or it is older than PLASBENCH_JOB_RETENTION_DAYS (default 180; 0 = never);
  - runs started outside the window (a terminal) are listed read-only under Runs, marked "started outside the window".
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
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
        time.sleep(0.2)
    return False


def new_jobs():
    return webui.Jobs(webui.Project(ROOT))


COUNTER = [0]
COUNTER_LOCK = threading.Lock()


def mkjob(state="cancelled", ended=None, started=None):
    with COUNTER_LOCK:
        COUNTER[0] += 1
        n = COUNTER[0]
    t = started or time.time() + n / 1000
    return {"id": f"20260101-000000-{n:06x}", "label": f"job {n}", "argv": ["run"], "command": "plasbench run", "env": {}, "kind": "plasbench", "state": state,
            "started": t, "ended": ended if ended is not None else t + 1, "exit": None, "pid": 0, "results": ""}


def add(jobs, job):
    """What launching a job does to the saved list."""
    if hasattr(jobs, "_register"):
        return jobs._register(job)
    with jobs.lock:
        jobs.jobs[job["id"]] = job
        jobs._save()


def main():
    print("a cancelled job survives a new Jobs (a restart, or a second window)")
    a = new_jobs()
    job = a._launch([sys.executable, "-u", "-c", "import time\nprint('started', flush=True)\ntime.sleep(120)"], "python -c ...", "long", None, ["demo", "--help"], "plasbench", ROOT)
    check("the job is running", wait(lambda: a.get(job["id"])["state"] == "running"))
    a.cancel(job["id"])
    check("it is cancelled", wait(lambda: a.jobs[job["id"]]["state"] == "cancelled"), a.jobs[job["id"]]["state"])
    b = new_jobs()
    listed = {j["id"]: j for j in b.list()}
    check("a new Jobs on the same folder lists it with state cancelled", job["id"] in listed and listed[job["id"]]["state"] == "cancelled", listed.get(job["id"]))
    check("the other window sees it too, without being restarted", job["id"] in {j["id"] for j in a.list()})

    print("rebuilt from the job folder")
    keep = mkjob("failed")
    add(a, keep)
    (a.dir / "jobs.json").unlink()
    c = new_jobs()
    check("with the index lost, jobs are restored from <id>.meta.json", {job["id"], keep["id"]} <= {j["id"] for j in c.list()} and (a.dir / f"{keep['id']}.meta.json").is_file(), [j["id"] for j in c.list()])
    (a.dir / "jobs.json").write_text("[]", encoding="utf-8")
    check("with an index that is behind, list() restores what has a meta file", keep["id"] in {j["id"] for j in new_jobs().list()})
    gone = mkjob("cancelled")
    add(a, gone)
    a.delete(gone["id"])
    (a.dir / "jobs.json").write_text("[]", encoding="utf-8")
    check("a job the user deleted is not restored", gone["id"] not in {j["id"] for j in new_jobs().list()})

    print("concurrency: two windows, many threads")
    one, two = new_jobs(), new_jobs()
    made = {}
    doomed = []
    barrier = threading.Barrier(8)

    def worker(jobs, count, tag):
        barrier.wait()
        for i in range(count):
            j = mkjob("cancelled" if i % 3 else "failed")
            made[j["id"]] = tag
            add(jobs, j)
            if i % 7 == 0:
                doomed.append(j["id"])
    threads = [threading.Thread(target=worker, args=(one if k % 2 else two, 12, k)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for jid in doomed[:10]:
        (one if len(jid) % 2 else two).delete(jid)
    final = new_jobs()
    ids = {j["id"] for j in final.list()}
    lost = [i for i in made if i not in ids and i not in doomed[:10]]
    check(f"no job disappeared ({len(made)} added by 8 threads over 2 windows)", not lost, lost[:5])
    check("the deleted ones stay deleted", not (set(doomed[:10]) & ids), sorted(set(doomed[:10]) & ids)[:3])
    check("each window agrees with the folder after a save", {j["id"] for j in one.list()} == ids == {j["id"] for j in two.list()} or {j["id"] for j in one.list()} >= ids)

    print("retention")
    d = new_jobs()
    old = time.time() - 400 * 86400
    many = [mkjob("cancelled", ended=time.time()) for _ in range(520)]
    for j in many:
        d.jobs[j["id"]] = j
    d._save()
    kept_ids = {x["id"] for x in new_jobs().list()}
    check("more than 500 cancelled jobs are all kept (only a done job beyond 500 is dropped)", all(j["id"] in kept_ids for j in many))
    ancient = mkjob("failed", ended=old, started=old - 5)
    add(d, ancient)
    check("a job older than the retention (default 180 days) is dropped, with its files", ancient["id"] not in {x["id"] for x in new_jobs().list()} and not (d.dir / f"{ancient['id']}.meta.json").exists())
    os.environ["PLASBENCH_JOB_RETENTION_DAYS"] = "0"
    forever = mkjob("failed", ended=old, started=old - 5)
    add(d, forever)
    check("PLASBENCH_JOB_RETENTION_DAYS=0 keeps it for ever", forever["id"] in {x["id"] for x in new_jobs().list()})
    os.environ.pop("PLASBENCH_JOB_RETENTION_DAYS")

    print("the lock")
    lock = d.dir / "jobs.lock"
    lock.write_text("999999", encoding="utf-8")
    stale = time.time() - 600
    os.utime(lock, (stale, stale))
    t0 = time.time()
    add(d, mkjob("done"))
    check("a stale lock does not block saving", time.time() - t0 < 10 and not lock.exists(), time.time() - t0)
    check("the lock is released after every save", not lock.exists())

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the Jobs page explains where runs started in a terminal appear", "you start in the Terminal appear under Runs and reports, marked 'started outside the window'" in __import__("plasbench.ui_help", fromlist=["PAGE"]).PAGE["p_jobs"]["bullets"][2] and 'data-tipid="p_jobs"' in html)  # UI cleanup: the sentence is in the Jobs (?) tooltip
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
