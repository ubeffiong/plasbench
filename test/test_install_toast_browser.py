#!/usr/bin/env python3
"""The installing toast in a REAL browser (test/install_toast_browser.mjs) against a real window whose installs are fake long-running commands (test/install_toast_server.py).

Starts an install from the page, checks the toast appears at once, stays across page navigation and a reload, shows the phase line, hides to a chip and comes back, asks before
cancelling, flips to Done and auto-dismisses; a second install fails and stays until dismissed; a third waits for the user (Docker handoff). Needs Node 22+ (built-in WebSocket) and
Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1. CI does not run it.
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
        print("  n/a   set PLASBENCH_BROWSER_TESTS=1 to run the real-browser installing-toast checks (needs Node 22+ and Chrome or Edge)")
        print("ALL INSTALL TOAST BROWSER TESTS PASSED (not run)")
        return 0
    from plasbench import appwindow
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  n/a   node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    port = 9361
    tmp = Path(tempfile.mkdtemp())
    (tmp / "fake").mkdir()
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), PYTHONIOENCODING="utf-8", IT_FAKE_DIR=str(tmp / "fake"))
    server = subprocess.Popen([sys.executable, str(ROOT / "test" / "install_toast_server.py"), "ui", "--no-browser", "--port", str(port + 100), "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(120):
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
        done = subprocess.run([node, str(ROOT / "test" / "install_toast_browser.mjs"), url, str(port), str(tmp / "fake")], capture_output=True, text=True, timeout=420)
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
