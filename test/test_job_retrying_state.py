#!/usr/bin/env python3
"""A run whose last output line is stage 4's "failed (exit N); retry K of M" notice reads `retrying` (audit AU-010); any later output ends it.
The stored state stays `running`. The window knows the word (chip, console state, colour)."""
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
os.environ["PLASBENCH_STALL_SECONDS"] = "0"
from plasbench import webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def wait(cond, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


jobs = webui.Jobs(webui.Project(ROOT))
code = ("import sys,time\n"
        "print('[2026-11-17 10:00:00] === Run tools on s1 ===', flush=True)\n"
        "print('[2026-11-17 10:00:01] WARNING: s1 / mob_recon failed (exit 1); retry 1 of 2', flush=True)\n"
        "time.sleep(4)\n"
        "print('[2026-11-17 10:00:05] mob_recon (s1) ...', flush=True)\n"
        "time.sleep(4)\n")
job = jobs._launch([sys.executable, "-u", "-c", code], "python -c ...", "t", None, ["demo", "--help"], "plasbench", ROOT)
state = lambda: jobs.get(job["id"])["display_state"]  # noqa: E731
check("a run whose last line is the retry notice reads retrying", wait(lambda: state() == "retrying"), state())
check("its stored state stays running", jobs.jobs[job["id"]]["state"] == "running")
check("later output ends retrying", wait(lambda: state() == "running"), state())
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the window words and colours the state", 'retrying:"Retrying a failed tool"' in html and "#cstate.retrying" in html and ".sdot.retrying" in html)
print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL JOB RETRYING STATE TESTS PASSED")
sys.exit(1 if FAILED else 0)
