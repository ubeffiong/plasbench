#!/usr/bin/env python3
"""Clicking the PlasBench icon always ends with a window, or says why not (plasbench/appwindow.py, plasbench/webui.py serve(), scripts/plasbench_launcher.sh).

The failure: the icon did nothing, however many times it was clicked. The window is opened by starting Chrome or Edge with a PlasBench-only profile. If that profile still holds the lock
of a browser that crashed or was killed (or whose process id was reused by another program), the next start believes the profile is in use, hands the URL to a browser that is not
there and exits without opening anything. PlasBench fired that command and never checked that a window appeared, so every click repeated the same no-op.

Now:
  - stale profile locks are cleared before launching (a lock whose process really is this browser is left alone);
  - the launch is VERIFIED: the server records when a window last loaded the page (visible in /healthz); a launch that produced no window is retried a different way (a fresh profile, then
    the default browser in a tab) without a second click, and if nothing works the message says so and gives the address;
  - a record file left by a crashed server is recognised as stale (nothing answers, or a different server answers) and removed, so the icon starts PlasBench instead of "bringing back" a
    window of a server that is gone;
  - two clicks in quick succession start ONE server (the second waits for the first, then only brings the window back);
  - the launcher script no longer `exec`s: if PlasBench cannot start or stops unexpectedly it shows a notification with the log to read, instead of vanishing silently.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
from plasbench import appwindow, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    print("stale profile locks")
    prof = Path(tmp) / "profile"
    prof.mkdir()
    lock_target = {"v": ""}
    real_read, real_alive, real_is_browser = appwindow._read_lock, appwindow._pid_alive, appwindow._pid_is_browser
    appwindow._read_lock = lambda lock: lock_target["v"]   # the lock's "host-pid", without needing to create symlinks (Windows cannot)

    def make_files():
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (prof / name).write_text("x")
    try:
        make_files()
        lock_target["v"] = "somehost-999999"
        appwindow._pid_alive = lambda pid: False
        removed = appwindow.clear_stale_profile_locks(str(prof))
        check("a lock whose process is gone is removed (with its cookie and socket)", sorted(removed) == ["SingletonCookie", "SingletonLock", "SingletonSocket"] and not (prof / "SingletonLock").exists(), removed)
        make_files()
        appwindow._pid_alive = lambda pid: True
        appwindow._pid_is_browser = lambda pid, profile: False
        removed = appwindow.clear_stale_profile_locks(str(prof))
        check("a lock whose process id now belongs to another program is removed too (ids are reused)", "SingletonLock" in removed, removed)
        make_files()
        appwindow._pid_is_browser = lambda pid, profile: True
        kept = appwindow.clear_stale_profile_locks(str(prof))
        check("a lock held by a live browser using this profile is left alone", kept == [] and (prof / "SingletonLock").exists(), kept)
        lock_target["v"] = "malformed"
        check("a lock that cannot be read is treated as stale", "SingletonLock" in appwindow.clear_stale_profile_locks(str(prof)))
    finally:
        appwindow._read_lock, appwindow._pid_alive, appwindow._pid_is_browser = real_read, real_alive, real_is_browser
    if hasattr(os, "symlink"):
        try:
            os.symlink("somehost-999999", prof / "SingletonLock")
            removed = appwindow.clear_stale_profile_locks(str(prof))
            check("a real SingletonLock symlink to a dead process is removed", "SingletonLock" in removed, removed)
        except (OSError, NotImplementedError):
            print("  skip  symlinks are not allowed here (the real-symlink check runs on Linux and macOS)")
    check("with no lock there is nothing to do", appwindow.clear_stale_profile_locks(str(Path(tmp) / "none")) == [])

    print("the verified launch")
    calls, opened = [], []
    saved = (appwindow.find_browser, appwindow._launch, appwindow.webbrowser.open, appwindow.screen_size)
    appwindow.find_browser = lambda: ("/usr/bin/google-chrome", False)
    appwindow._launch = lambda exe, url, profile, wsl: calls.append(profile)
    appwindow.webbrowser.open = lambda url: opened.append(url) or True
    appwindow.screen_size = lambda: (1920, 1080)
    try:
        profile_dir = Path(tmp) / "app-window"

        def run(works_on):
            """seen() turns true only once launch number `works_on` (1 = the app window, 2 = a fresh profile, 3 = the default browser) has been made."""
            calls.clear(); opened.clear()
            def seen(since):
                made = len(calls) + len(opened)
                return made >= works_on
            return appwindow.open_app_window("http://127.0.0.1:8770/?t=k", profile_dir, False, seen=seen, wait=0.6)
        first = run(1)
        check("the app window opens and is seen: one launch, no fallback", first.startswith("app window via google-chrome") and len(calls) == 1 and not opened, (first, calls, opened))
        second = run(2)
        check("no window appeared: it retries with a FRESH profile (no second click needed)", "with a fresh profile" in second and len(calls) == 2 and calls[1] != calls[0] and not opened, (second, calls))
        third = run(3)
        check("still none: it falls back to the default browser in a tab", third.startswith("default browser") and len(calls) == 2 and len(opened) == 1, (third, calls, opened))
        fourth = run(99)
        check("nothing works: it says so plainly and gives the address to open by hand", fourth.startswith("NO WINDOW APPEARED") and "http://127.0.0.1:8770/?t=k" in fourth, fourth)
        calls.clear()
        plain = appwindow.open_app_window("http://127.0.0.1:8770/", profile_dir, False)
        check("without a way to verify (older callers, tests) it launches once, as before", plain.startswith("app window") and len(calls) == 1)
    finally:
        appwindow.find_browser, appwindow._launch, appwindow.webbrowser.open, appwindow.screen_size = saved

    print("a record left by a server that is gone")
    import json
    record = webui._instance_file()
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"url": "http://127.0.0.1:1/?t=x", "port": 1, "pid": 1, "started": 1, "root": str(ROOT.resolve())}), encoding="utf-8")
    check("nothing answers on the recorded port: not 'running', and the stale record is removed", webui.running_instance(ROOT) is None and not record.exists())
    # a real server on a real port, with the record naming a different start time
    import http.server, socketserver
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Length", "2"); self.send_header("X-PlasBench-Instance", "222"); self.send_header("X-PlasBench-Page-Seen", "0"); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    record.write_text(json.dumps({"url": f"http://127.0.0.1:{port}/?t=x", "port": port, "pid": 1, "started": 111, "root": str(ROOT.resolve())}), encoding="utf-8")
    check("something else answers on the port (a different server instance): not this PlasBench", webui.running_instance(ROOT) is None)
    record.write_text(json.dumps({"url": f"http://127.0.0.1:{port}/?t=x", "port": port, "pid": 1, "started": 222, "root": str(ROOT.resolve())}), encoding="utf-8")
    check("the recorded server answers and is the one named: it is running", webui.running_instance(ROOT) == f"http://127.0.0.1:{port}/?t=x")
    srv.shutdown()

    print("two quick clicks")
    lock_path = Path(tmp) / "ui" / "launch.lock"
    with webui._LaunchLock(wait=5) as first_lock:
        check("the first click takes the launch lock", first_lock.held and lock_path.exists())
        order = []
        def second_click():
            with webui._LaunchLock(wait=10) as second:
                order.append(("second", second.held))
        t = threading.Thread(target=second_click)
        t.start()
        time.sleep(1.0)
        check("the second click waits while the first is still starting PlasBench", t.is_alive() and not order)
    t.join(timeout=10)
    check("when the first finishes the second proceeds (and then only brings the window back)", order == [("second", True)], order)
    lock_path.write_text("999999")
    os.utime(lock_path, (time.time() - 300, time.time() - 300))
    with webui._LaunchLock(wait=3) as recovered:
        check("a lock left by a launch that died is cleared, not waited on forever", recovered.held)

    print("the launcher script and the wiring")
    script = (ROOT / "scripts" / "plasbench_launcher.sh").read_text(encoding="utf-8")
    check("the launcher no longer execs away: a failed start is reported with a notification and the log path", "exec \"$PY\" -m plasbench" not in script and "notify-send" in script and "could not start or stopped unexpectedly" in script)
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("serve() verifies both a new and an existing window (and /api/reopen verifies the window it opens: three), and takes the launch lock", src.count("seen=lambda since") == 3 and "_LaunchLock()" in src and '"started": int(SERVER_STARTED)' in src)
    print("ALL APP LAUNCH TESTS PASSED" if not FAILED else f"APP LAUNCH TESTS FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
