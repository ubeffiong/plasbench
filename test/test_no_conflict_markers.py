#!/usr/bin/env python3
"""Also: no compiled Python cache file (__pycache__/*.pyc) is tracked (they are in .gitignore, and 14 then 25 of them were committed by mistake).

No tracked text file holds an unresolved merge-conflict marker (a line that starts with <<<<<<< or >>>>>>> followed by a space). One slipped into test/run_tests.sh once and
every CI shard died on a syntax error; the test list itself cannot report that, so this guard reads the files directly."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = ("cohorts/", "results", "docs/images/", "docs/sample_report/", "tmp/")
files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
bad = []
for name in files:
    if name.startswith(SKIP_PARTS) or name.endswith((".png", ".jpg", ".gz", ".zip", ".docx", ".pdf", ".svg", ".html", ".fasta", ".fna")):
        continue
    try:
        text = (ROOT / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "<<<<<<<":
            bad.append(f"{name}:{number}")
tracked_pyc = [n for n in files if n.endswith(".pyc") or "/__pycache__/" in n]
for item in tracked_pyc:
    print("TRACKED COMPILED FILE (git rm --cached it):", item)
bad += tracked_pyc
print("files scanned:", len(files))
for item in bad:
    print("CONFLICT MARKER:", item)
print("ALL CONFLICT-MARKER TESTS PASSED" if not bad else "CONFLICT-MARKER TESTS FAILED")
sys.exit(1 if bad else 0)
