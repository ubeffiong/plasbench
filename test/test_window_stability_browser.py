#!/usr/bin/env python3
"""Window stability in a REAL browser (test/window_stability_browser.mjs): the window is opened against a real server and shows NO stale banner (the v0.5.5 false positive), a stale key with
a valid cookie recovers silently, and a key AND cookie refused show one persistent bar and no polling.

It needs Node 22+ (for the built-in WebSocket) and Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1. Otherwise it prints a skip and passes.
"""
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


def main():
    if os.environ.get("PLASBENCH_BROWSER_TESTS") != "1":
        print("  skip  set PLASBENCH_BROWSER_TESTS=1 to run the real-browser window stability checks (needs Node 22+ and Chrome or Edge)")
        print("ALL WINDOW STABILITY BROWSER TESTS PASSED (skipped)")
        return 0
    from plasbench import appwindow
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  skip  node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, PLASBENCH_UI_HOME=str(Path(tmp) / "ui"), HOME=tmp, USERPROFILE=tmp, PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", "8881", "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(80):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--remote-debugging-port=9334", f"--user-data-dir={tmp}/chrome", "--window-size=1280,800", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen("http://127.0.0.1:9334/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        done = subprocess.run([node, str(ROOT / "test" / "window_stability_browser.mjs"), url, "9334"], capture_output=True, text=True, timeout=300)
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-500:])
        return done.returncode
    finally:
        chrome.kill()
        server.kill()


if __name__ == "__main__":
    sys.exit(main())
