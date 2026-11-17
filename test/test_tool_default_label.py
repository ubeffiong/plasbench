#!/usr/bin/env python3
"""The Tools page and New benchmark say whether a tool's default is on or off, not just "default"."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


check("the Tools column says what it is", "Runs by default</th>" in HTML)
check("the switch is followed by on or off", 'data-flagtxt="' in HTML and '${t.enabled ? "on" : "off"}</b>' in HTML)
check("flipping the switch updates the text and the loaded list", "showFlag(f, e.target.checked)" in HTML and "row.enabled = on" in HTML)
check("the toast says which way it went", "runs by default" in HTML and "skipped by default" in HTML)
check("the on / default / off control shows the default's state", HTML.count("defaultWord(a.dest)") == 2)
check("the New benchmark Tools step explains it", "default · on or default · off" in HTML)
node = shutil.which("node")
if node:
    done = subprocess.run([node, str(ROOT / "test" / "tool_default_render.js"), str(ROOT / "plasbench" / "data" / "ui.html")], capture_output=True, text=True)
    print(done.stdout.rstrip())
    check("the label reads default · on / default · off for a tool with a run setting, plain default otherwise", done.returncode == 0, done.stdout + done.stderr)
else:
    print("  SKIP: node is not installed, so the label function was not run")

print("ALL TOOL DEFAULT LABEL TESTS PASSED" if not failures else "TOOL DEFAULT LABEL TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
