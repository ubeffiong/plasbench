#!/usr/bin/env python3
"""The AI help pane's new flows and the UI review in a REAL browser (test/ai_ui_review.mjs): folder grant, scan, share, file plans (preview, apply, undo), sheet fix, window-action
cards, guided flows, focus, keyboard, contrast, zoom, 320 px, reduced motion, long text, many cards, scroll and reload. Opt-in: PLASBENCH_BROWSER_TESTS=1 (needs Node 22+ and Chrome or
Edge); PB_SHOTS=<folder> keeps the screenshots and ui-review-results.json."""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))


def main():
    if os.environ.get("PLASBENCH_BROWSER_TESTS") != "1":
        print("  n/a   set PLASBENCH_BROWSER_TESTS=1 to run the real-browser AI UI review (needs Node 22+ and Chrome or Edge)")
        print("ALL AI UI REVIEW TESTS PASSED (not run)")
        return 0
    from plasbench import appwindow
    import ai_stub
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  n/a   node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    stub = ai_stub.Stub()
    stub.pieces = ["Sure. ", "I can take you there.\n", "```pb-ui\n", '{"ui":"go","target":"settings","why":"the Settings page"}\n', "```\n", "```pb-files\n",
                   '{"ops":[{"op":"mkdir","path":"data/Z1"}],"why":"make a folder"}\n', "```\n"]
    port = 9371
    tmp = Path(tempfile.mkdtemp())
    data = tmp / "mydata"
    (data / "reads").mkdir(parents=True)
    for n in ("A1_R1", "A1_R2", "S2_1", "S2_2", "lone_1"):
        with gzip.open(data / "reads" / (n + ".fastq.gz"), "wb") as fh:
            fh.write(b"@r\nACGTACGTAC\n+\nIIIIIIIIII\n" * 3)
    (data / "evil```pb-action.txt").write_text("x", encoding="utf-8") if os.name != "nt" else None
    env = dict(os.environ, **stub.env(), AI_PROVIDER="local", PLASBENCH_UI_HOME=str(tmp / "ui"), PLASBENCH_AI_HOME=str(tmp / "ai"), PYTHONIOENCODING="utf-8", PLASBENCH_LOCAL_SETTINGS=str(tmp / "local.env"))
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", str(port + 100), "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(120):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={tmp}/chrome", "--window-size=1500,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        shots = os.environ.get("PB_SHOTS") or "-"
        if shots != "-":
            Path(shots).mkdir(parents=True, exist_ok=True)
        done = subprocess.run([node, str(ROOT / "test" / "ai_ui_review.mjs"), url, str(port), shots, str(data)], capture_output=True, text=True, timeout=600, encoding="utf-8")
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-1500:])
        return done.returncode
    finally:
        if os.name == "nt":      # terminate() ends only the launcher: the browser's own processes would keep the debugging port and the profile
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(chrome.pid)], capture_output=True)
        chrome.terminate()
        server.terminate()
        stub.stop()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
