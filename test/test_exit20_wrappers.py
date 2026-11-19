#!/usr/bin/env python3
"""Exit code 20 (a manual step is needed) and 21 (consent is needed) are information, never an ERROR, in every wrapper that reports an exit code.

A FAKE command returns 20 or 21 and the test runs it through each wrapper: the window's job console (plasbench/webui.py), its display state, the exit-code
explanations (plasbench/exitcodes.py, scripts/lib.sh explain_exit and the ERR trap), the terminal page's rendering, plus a real exit 1 to prove errors are still errors.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(Path(tmp) / "home")
from plasbench import exitcodes, webui  # noqa: E402

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


def job_with_exit(jobs, code, argv):
    job = jobs._launch([sys.executable, "-u", "-c", f"import sys\nprint('the notice')\nsys.exit({code})"], "fake", "fake", None, list(argv), "plasbench", ROOT)
    wait(lambda: jobs.jobs[job["id"]]["state"] in ("done", "failed"))
    wait(lambda: "[PlasBench]" in jobs.get(job["id"])["log"] or jobs.jobs[job["id"]]["state"] == "done", 10)   # the closing line is appended just after the state changes
    return job["id"]


def main():
    jobs = webui.Jobs(webui.Project(ROOT))
    for code, word in ((20, "Manual step needed"), (21, "Consent needed")):
        for argv in (("install-tools", "gplas2", "--yes"), ("check", "--yes"), ("run", "--tool", "x")):
            jid = job_with_exit(jobs, code, argv)
            log = jobs.get(jid)["log"]
            check(f"window console, exit {code} from `{argv[0]}`: no ERROR line", "ERROR" not in log and word in log and "nothing failed" in log, log)
            shown = jobs.display_state(jobs.jobs[jid])
            check(f"window state, exit {code} from `{argv[0]}`: not Failed", shown in ("manual_step", "consent_needed"), shown)
    jid = job_with_exit(jobs, 1, ("install-tools", "x"))
    check("a real failure (exit 1) is still an ERROR", "[PlasBench] ERROR: the command stopped" in jobs.get(jid)["log"])

    check("exitcodes.explain(20) and (21) are plain sentences without 'failed'", all("failed" not in exitcodes.explain(c).replace("nothing failed", "") for c in (20, 21)))
    check("exitcodes.is_informational", exitcodes.is_informational(20) and exitcodes.is_informational(21) and not exitcodes.is_informational(1) and not exitcodes.is_informational(None))

    # scripts/lib.sh: explain_exit and the ERR trap stay silent for 20 and 21 even under set -e
    script = (f'set -e; source "{ROOT.as_posix()}/scripts/lib.sh" 2>/dev/null; '
              'explain_exit 20; explain_exit 21; (exit 20) || true; fake() { return "$1"; }; fake 21 || echo "after-21"; echo done')
    bash = os.environ.get("PLASBENCH_BASH") or "bash"
    out = subprocess.run([bash, "-c", script], capture_output=True, text=True, cwd=ROOT)
    text = out.stdout + out.stderr
    check("scripts/lib.sh: explain_exit knows 20 and 21", "manual installation step" in text and "consent is needed" in text, text)
    check("scripts/lib.sh: the ERR trap prints no ERROR for 20 or 21", "ERROR" not in text, text)
    other = subprocess.run([bash, "-c", f'source "{ROOT.as_posix()}/scripts/lib.sh" 2>/dev/null; explain_exit 9'], capture_output=True, text=True, cwd=ROOT).stdout
    check("scripts/lib.sh: another code still reads as a failure", "failed with exit code 9" in other, other)

    ui = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the terminal page prints exit 20 and 21 as information, not as an error", 'r.exit === 20 || r.exit === 21' in ui and "t-err" in ui)
    check("the window labels the two states", "consent_needed" in ui and "manual_step" in ui)

    print("ALL EXIT-20 WRAPPER TESTS PASSED" if not FAILED else f"FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
