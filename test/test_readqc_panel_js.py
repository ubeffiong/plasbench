#!/usr/bin/env python3
"""The pure JavaScript helpers of the QC panel, under node (skipped with a printed reason when node is absent), plus a syntax check of the whole page script."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_readqc_panel as qp  # noqa: E402

node = shutil.which("node")
if not node:
    print("SKIP: node is not installed, so the panel's JavaScript helpers were not run (install Node.js to run them)")
    sys.exit(0)
with tempfile.TemporaryDirectory() as tmp:
    helpers = os.path.join(tmp, "helpers.js")
    full = os.path.join(tmp, "panel_full.js")
    open(helpers, "w", encoding="utf-8").write(qp.HELPERS_JS)
    open(full, "w", encoding="utf-8").write(qp.JS)
    syntax = subprocess.run([node, "--check", full], capture_output=True, text=True)
    print(f"  {'ok  ' if syntax.returncode == 0 else 'FAIL'}  the whole page script is valid JavaScript" + ("" if syntax.returncode == 0 else " -> " + syntax.stderr[:300]))
    done = subprocess.run([node, os.path.join(ROOT, "test", "test_readqc_panel_js.mjs"), helpers], capture_output=True, text=True)
    print(done.stdout + done.stderr)
    sys.exit(0 if syntax.returncode == 0 and done.returncode == 0 else 1)
