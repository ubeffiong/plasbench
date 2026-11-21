#!/usr/bin/env python3
"""DOM-free tests of the AI pane's pure functions in a bare node VM (test/ai_pane_logic.mjs): Markdown rendering and every card that shows model, provider or folder text, against an
XSS corpus, and the renderer's speed on adversarial input. Runs where node exists (skipped, loudly, where it does not)."""
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
done = subprocess.run([node, str(ROOT / "test" / "ai_pane_logic.mjs"), str(ROOT / "plasbench" / "data" / "ui.html")], capture_output=True, text=True, timeout=180, encoding="utf-8")
out = done.stdout
print("\n".join(l for l in out.splitlines() if not l.startswith("  ok")))
if done.returncode != 0:
    print(done.stderr[-1500:])
print("PASS" if done.returncode == 0 else "FAIL")
sys.exit(done.returncode)
