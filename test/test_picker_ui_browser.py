#!/usr/bin/env python3
"""The folder window flows in a REAL browser (test/picker_ui_browser.mjs), against real servers started three ways:

  unavailable  PLASBENCH_NATIVE_PICKER_POWERSHELL points at nothing: Browse -> built-in browser with the reason, Why?, Copy diagnostics, and the Test button's FAIL report
  docker       PLASBENCH_IN_DOCKER=1: Browse -> built-in browser with the banner; Add another folder -> the docker run command (a UNC share refused)
  native       only on a Windows computer: the REAL PowerShell route. Settings > Test the folder window opens a real folder window that closes itself and reports PASS;
               Browse opens the real window, the page says it opened, Cancel closes it

It needs Node 22+ (the built-in WebSocket) and Chrome or Edge, so it only runs when asked: PLASBENCH_BROWSER_TESTS=1.
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


def run_mode(mode, node, browser, port, extra_env):
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), PYTHONIOENCODING="utf-8", **extra_env)
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", str(port + 100), "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(80):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    chrome = subprocess.Popen([browser, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={tmp}/chrome", "--window-size=1280,900", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        done = subprocess.run([node, str(ROOT / "test" / "picker_ui_browser.mjs"), url, mode, str(port), str(tmp / "picker.png")], capture_output=True, text=True, timeout=300)
        print(f"[{mode}]")
        print(done.stdout)
        if done.returncode != 0:
            print(done.stderr[-800:])
        return done.returncode == 0
    finally:
        chrome.terminate()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


def main():
    if os.environ.get("PLASBENCH_BROWSER_TESTS") != "1":
        print("  n/a   set PLASBENCH_BROWSER_TESTS=1 to run the real-browser folder window checks (needs Node 22+ and Chrome or Edge)")
        print("ALL PICKER UI BROWSER TESTS PASSED (not run)")
        return 0
    from plasbench import appwindow
    node, (browser, _wsl) = shutil.which("node"), appwindow.find_browser()
    if not node or not browser:
        print(f"  n/a   node or a Chromium browser was not found (node={node}, browser={browser})")
        return 0
    ok = run_mode("unavailable", node, browser, 9341, {"PLASBENCH_NATIVE_PICKER_POWERSHELL": str(Path(tempfile.gettempdir()) / "no-such-powershell.exe"), "DISPLAY": ""})
    ok = run_mode("docker", node, browser, 9342, {"PLASBENCH_IN_DOCKER": "1"}) and ok
    if os.name == "nt" and shutil.which("powershell.exe"):
        ok = run_mode("native", node, browser, 9343, {}) and ok
    else:
        print("  n/a   not a Windows computer: the real native-window flow is not run here")
    print("ALL PICKER UI BROWSER TESTS PASSED" if ok else "PICKER UI BROWSER TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
