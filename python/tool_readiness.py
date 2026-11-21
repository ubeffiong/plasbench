#!/usr/bin/env python3
"""Is an annotation tool READY to work, not just present on PATH?

`[ok] amrfinder` used to mean only that the program starts. In a real run AMRFinderPlus (database never downloaded) failed in 0 s, and ISEScan ran 11 minutes and
then died with `ValueError: NoneType copy mode not allowed` (fastcluster 1.3.0, built for NumPy 2, installed beside NumPy 1.26). Both would have been found in a second
by asking the tool what it needs:

  python3 -I python/tool_readiness.py amrfinder           the AMRFinderPlus database is installed (amrfinder --database_version)
  python3 -I python/tool_readiness.py abricate [--db ncbi --db plasmidfinder]   abricate --list names the databases the run will use
  python3 -I python/tool_readiness.py isescan             ISEScan's own Python can run its clustering step (the fastcluster/NumPy pairing), and isescan.py --help works

Output: one line, `ok<TAB>detail` or `miss<TAB>what is wrong<TAB>how to fix it`; exit 0 when ready, 1 when not, 2 when the tool is not installed. Nothing is
installed or changed. A probe that cannot run at all (a timeout) says `unknown` and exits 0: an unanswered question is not a failure. Standard library only.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

FASTCLUSTER_FIX = ('pip install "fastcluster<1.3"  (or: conda install -n plasbench "fastcluster<1.3"; plasbench install-tools reference-annotation does it). '
                   "fastcluster 1.3.0 was built for NumPy 2 and fails with NumPy 1.x")


def _run(argv, timeout=30, env=None):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    except OSError as exc:
        return None, str(exc)
    return done, ""


def amrfinder_db_dir(environ=None):
    """The database folder PlasBench passes to AMRFinderPlus (-d) in Docker mode, else None (the tool's own default folder)."""
    environ = os.environ if environ is None else environ
    if str(environ.get("PLASBENCH_IN_DOCKER", "")) != "1":
        return None
    base = environ.get("PLASBENCH_DB_DIR") or os.path.join(os.path.expanduser("~"), ".plasbench", "databases")
    latest = os.path.join(base, "amrfinder", "latest")
    return latest if os.path.isdir(latest) else None


def amrfinder():
    exe = shutil.which("amrfinder")
    if not exe:
        return ("absent", "amrfinder is not installed", "plasbench install-tools reference-annotation --yes")
    argv = [exe, "--database_version"]
    db = amrfinder_db_dir()
    if db:
        argv += ["-d", db]
    done, err = _run(argv, 60)
    if done is None:
        return ("unknown", "amrfinder --database_version did not answer (%s)" % err, "")
    text = (done.stdout or "") + "\n" + (done.stderr or "")
    version_line = next((ln for ln in text.splitlines() if ln.lower().startswith("database version")), "")
    if done.returncode == 0 and version_line:
        return ("ok", version_line.strip(), "")
    said = next((ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("Running:") and ("database" in ln.lower() or "error" in ln.lower())), "")
    return ("miss", "amrfinder database not installed" + (" (the tool says: %s)" % said if said else ""),
            "run amrfinder -u (needs the internet, about 100 MB; once per machine), or: plasbench check --yes")


def abricate(databases=("ncbi", "plasmidfinder")):
    exe = shutil.which("abricate")
    if not exe:
        return ("absent", "abricate is not installed", "plasbench install-tools reference-annotation --yes")
    done, err = _run([exe, "--list"], 60)
    if done is None:
        return ("unknown", "abricate --list did not answer (%s)" % err, "")
    names = {ln.split("\t")[0].strip().lower() for ln in (done.stdout or "").splitlines()[1:] if ln.strip()}
    missing = [d for d in databases if d.lower() not in names]
    if done.returncode == 0 and names and not missing:
        return ("ok", "databases: " + ", ".join(sorted(names)), "")
    if not names:
        return ("miss", "abricate lists no databases", "abricate --setupdb")
    return ("miss", "abricate has no database named %s (it lists: %s)" % (", ".join(missing), ", ".join(sorted(names))), "abricate --setupdb")


def isescan():
    exe = shutil.which("isescan.py") or shutil.which("isescan")
    if not exe:
        return ("absent", "isescan is not installed", "plasbench install-tools reference-annotation --yes")
    python = sys.executable
    try:
        with open(exe, "rb") as handle:
            first = handle.readline().decode("utf-8", "replace").strip()
        if first.startswith("#!") and "env" not in first.split()[0]:
            python = first[2:].split()[0]
    except OSError:
        pass
    # The step ISEScan reaches only after its slow search (minutes): average-linkage clustering with preserve_input=False. Try it on three numbers.
    code = ("import numpy, fastcluster\n"
            "fastcluster.linkage(numpy.array([1.0, 2.0, 3.0]), method='average', preserve_input=False)\n"
            "print(numpy.__version__, fastcluster.__version__)\n")
    done, err = _run([python, "-I", "-c", code], 30)
    if done is None:
        return ("unknown", "the ISEScan Python check did not answer (%s)" % err, "")
    if done.returncode != 0:
        last = (done.stderr or "").strip().splitlines()[-1:] or ["failed"]
        return ("miss", "ISEScan would fail after its long search: its clustering step does not work with the installed packages (%s)" % last[0].strip(), FASTCLUSTER_FIX)
    done, err = _run([exe, "--help"], 30)
    if done is None or done.returncode != 0:
        return ("miss", "isescan.py --help does not run (%s)" % (err or ((done.stderr or "").strip().splitlines() or ["failed"])[-1]), "plasbench install-tools reference-annotation --yes")
    return ("ok", "ISEScan's clustering step works with the installed numpy and fastcluster", "")


def check(tool, databases=None):
    if os.environ.get("PLASBENCH_TOOL_READINESS", "on").strip().lower() in ("off", "0", "no"):
        return ("unknown", "readiness probes switched off (PLASBENCH_TOOL_READINESS=off)", "")
    if tool == "amrfinder":
        return amrfinder()
    if tool == "abricate":
        return abricate(tuple(databases) if databases else ("ncbi", "plasmidfinder"))
    if tool in ("isescan", "isescan.py"):
        return isescan()
    return ("unknown", "no readiness check for %s" % tool, "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool", choices=("amrfinder", "abricate", "isescan"))
    ap.add_argument("--db", action="append", help="abricate database the run will use (repeatable)")
    args = ap.parse_args(argv)
    status, detail, fix = check(args.tool, args.db)
    print("\t".join(x for x in (status if status != "absent" else "miss", detail, fix) if x != ""))
    return {"ok": 0, "unknown": 0, "miss": 1, "absent": 2}[status]


if __name__ == "__main__":
    sys.exit(main())
