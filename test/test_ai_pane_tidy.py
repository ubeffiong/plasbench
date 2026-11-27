#!/usr/bin/env python3
"""The tidied AI pane loses nothing, and the AI help is its own right-hand drawer (test/ai_pane_tidy.mjs, run in a bare node VM): every string and control that used to be
visible is still in the DOM (shown, folded or in an (i) tooltip), the risk badge and the consent path are intact. Runs where node exists (skipped, loudly, where it does not)."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
node = shutil.which("node")
if not node:
    print("  n/a   node is not installed; the pane logic checks are skipped")
    print("PASS (not run)")
    sys.exit(0)
done = subprocess.run([node, str(ROOT / "test" / "ai_pane_tidy.mjs"), str(ROOT / "plasbench" / "data" / "ui.html")], capture_output=True, text=True, timeout=180, encoding="utf-8")
out = done.stdout
print("\n".join(l for l in out.splitlines() if not l.startswith("  ok")))
if done.returncode != 0:
    print(done.stderr[-1500:])
print("PASS" if done.returncode == 0 else "FAIL")
sys.exit(done.returncode)
