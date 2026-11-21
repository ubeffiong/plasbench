#!/usr/bin/env python3
"""The AI help tab in a REAL browser (test/ai_ui_browser.mjs), against a real window server pointed at the local stub services (test/ai_stub.py): the notice, the pop-up sign-in,
a streamed answer with sources and an action card, the consent dialog before a run, the redacted Send result, escaping, shortcut, light/dark and phone width.
Needs Node 22+ (the built-in WebSocket) and Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1 (PB_SHOTS=<folder> keeps screenshots)."""
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
        print("  n/a   set PLASBENCH_BROWSER_TESTS=1 to run the real-browser AI help checks (needs Node 22+ and Chrome or Edge)")
        print("ALL AI UI BROWSER TESTS PASSED (not run)")
        return 0
    from plasbench import appwindow
    import ai_stub
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  n/a   node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    stub = ai_stub.Stub()
    port = 9361
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, **stub.env(), PLASBENCH_UI_HOME=str(tmp / "ui"), PLASBENCH_AI_HOME=str(tmp / "ai"), PYTHONIOENCODING="utf-8", PLASBENCH_LOCAL_SETTINGS=str(tmp / "local.env"))
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
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        shots = os.environ.get("PB_SHOTS") or "-"
        if shots != "-":
            Path(shots).mkdir(parents=True, exist_ok=True)
        done = subprocess.run([node, str(ROOT / "test" / "ai_ui_browser.mjs"), url, str(port), shots], capture_output=True, text=True, timeout=420)
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-1200:])
        return done.returncode
    finally:
        chrome.terminate()
        server.terminate()
        stub.stop()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
