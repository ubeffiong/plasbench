#!/usr/bin/env python3
"""Open folder: choose the file manager per platform (plasbench/fsutil.py) and never turn a missing PROGRAM into "No such file or directory".

The old /api/reveal ran `xdg-open` and raised FileNotFoundError inside WSL, where it is not installed, so the toast read as if the folder were missing. Now:
windows -> explorer; mac -> open; WSL -> wslview, else explorer.exe with `wslpath -w`, else xdg-open / gio open / kde-open / gnome-open; nothing -> a clear
200 {"ok": false, "opened": false, "reason": ...} that the window shows with a Copy button. A missing PATH is still a 404 that names the path.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
from plasbench import fsutil, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def having(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


def main():
    folder = tmp / "d"
    folder.mkdir()
    file = folder / "f.txt"
    file.write_text("x")
    print("choice")
    check("windows: explorer opens a folder", fsutil.open_command(folder, platform="windows") == ["explorer", str(folder)])
    check("windows: explorer selects a file", fsutil.open_command(file, platform="windows") == ["explorer", "/select,", str(file)])
    check("mac: open", fsutil.open_command(folder, platform="mac") == ["open", str(folder)] and fsutil.open_command(file, platform="mac") == ["open", "-R", str(file)])
    check("WSL with wslview: wslview", fsutil.open_command(folder, platform="linux", wsl=True, which=having("wslview", "explorer.exe", "xdg-open")) == ["wslview", str(folder)])
    check("WSL without wslview but with explorer.exe: explorer.exe with the wslpath -w path",
          fsutil.open_command(folder, platform="linux", wsl=True, which=having("explorer.exe", "xdg-open"), wslpath=lambda p: r"\\wsl$\Ubuntu" + p.replace("/", "\\")) == ["explorer.exe", r"\\wsl$\Ubuntu" + str(folder).replace("/", "\\")])
    check("WSL, explorer.exe but wslpath fails: falls on to xdg-open", fsutil.open_command(folder, platform="linux", wsl=True, which=having("explorer.exe", "xdg-open"), wslpath=lambda p: None) == ["xdg-open", str(folder)])
    check("plain Linux: xdg-open", fsutil.open_command(folder, platform="linux", wsl=False, which=having("xdg-open")) == ["xdg-open", str(folder)])
    check("Linux: a file opens its folder", fsutil.open_command(file, platform="linux", wsl=False, which=having("xdg-open")) == ["xdg-open", str(folder)])
    check("Linux without xdg-open: gio open", fsutil.open_command(folder, platform="linux", wsl=False, which=having("gio")) == ["gio", "open", str(folder)])
    check("Linux: kde-open, then gnome-open", fsutil.open_command(folder, platform="linux", wsl=False, which=having("kde-open")) == ["kde-open", str(folder)]
          and fsutil.open_command(folder, platform="linux", wsl=False, which=having("gnome-open")) == ["gnome-open", str(folder)])
    check("nothing available: None", fsutil.open_command(folder, platform="linux", wsl=False, which=having()) is None and fsutil.open_command(folder, platform="linux", wsl=True, which=having()) is None)

    print("reveal")
    calls = []
    out = fsutil.reveal(folder, popen=lambda argv, **k: calls.append(argv), platform="linux", wsl=False, which=having("xdg-open"))
    check("an available manager is started and reported", out["ok"] and out["opened"] and calls == [["xdg-open", str(folder)]], out)
    out = fsutil.reveal(folder, platform="linux", wsl=False, which=having())
    check("no manager: ok false, opened false, the path and a clear reason (no exception)", out == {"path": str(folder), "ok": False, "opened": False, "reason": "no file manager is available here"}, out)

    def boom(argv, **k):
        raise FileNotFoundError(2, "No such file or directory")
    out = fsutil.reveal(folder, popen=boom, platform="linux", wsl=False, which=having("xdg-open"))
    check("a program that vanishes is reported, not raised", not out["opened"] and "could not be started" in out["reason"], out)

    print("route")
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def post(path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/reveal", data=json.dumps({"path": path}).encode(), method="POST",
                                     headers={"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    real_which, real_platform, real_wsl = fsutil.shutil.which, fsutil.platform_name, fsutil.in_wsl
    fsutil.shutil.which, fsutil.platform_name, fsutil.in_wsl = (lambda n: None), (lambda: "linux"), (lambda: False)
    try:
        code, body = post(str(folder))
        check("POST /api/reveal with no file manager: 200 and ok false / opened false", code == 200 and body["ok"] is False and body["opened"] is False and body["path"] == str(folder), (code, body))
        code, body = post(str(tmp / "missing"))
        check("a missing path stays a 404 that names the path", code == 404 and str(tmp / "missing") in body["error"], (code, body))
    finally:
        fsutil.shutil.which, fsutil.platform_name, fsutil.in_wsl = real_which, real_platform, real_wsl
        server.shutdown()
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the page shows the path with a Copy button instead of a toast", "No file manager is available here" in html and "copy: r.path || p" in html)
    check("every reveal caller goes through the one reveal()", html.count('api("reveal"') == 1)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
