#!/usr/bin/env python3
"""The (?) help tooltips (hover, keyboard focus, tap, Escape, kept on screen) and the phone layout (no sideways scrolling on any page) in a REAL browser
(test/ui_cleanup_browser.mjs), against a real server. Needs Node 22+ (the built-in WebSocket) and Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1.
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
        print("  n/a   set PLASBENCH_BROWSER_TESTS=1 to run the real-browser tooltip checks (needs Node 22+ and Chrome or Edge)")
        print("ALL UI CLEANUP BROWSER TESTS PASSED (not run)")
        return 0
    from plasbench import appwindow
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  n/a   node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    port = 9351
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), PYTHONIOENCODING="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", str(port + 100), "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(80):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={tmp}/chrome", "--window-size=1400,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        done = subprocess.run([node, str(ROOT / "test" / "ui_cleanup_browser.mjs"), url, str(port)], capture_output=True, text=True, timeout=300)
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-800:])
        return done.returncode
    finally:
        chrome.terminate()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
