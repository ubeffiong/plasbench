#!/usr/bin/env python3
"""Browse opens the computer's own folder window (plasbench/native_picker.py, the /api/native-picker routes, plasbench/data/ui.html).

  - path conversion of what the dialog returns (drive letters, lowercase, UNC, \\\\wsl.localhost\\Ubuntu-24.04\\..., \\\\wsl$\\..., spaces, unicode, trailing slash, drive root, an unmounted drive);
  - what Explorer gives the user (Copy as path with quotes, the address bar, file:/// links, 'This PC\\Data (D:)\\x') -> a path, and Open in Explorer for /mnt/<drive>, an unmounted drive;
  - capability detection with an injected environment (Windows, WSL, mac, Linux with and without DISPLAY, SSH, no powershell.exe);
  - pick_folder driven by FAKE powershell / osascript / zenity programs (chosen, cancelled, error, timeout kills the process, non-ASCII, a second request refused, cancel);
  - argv construction with hostile titles (no shell string is ever built);
  - the routes over HTTP (token, loopback only, open / status polling / cancel);
  - the Windows volume parsers on recorded Get-Volume / Win32_LogicalDisk / wmic output (USB stick, network drive, unmounted letter, drive with no media) and the capacity maths;
  - the page: Browse at every former pickPath site, the built-in fallback, no browser dialogs; pure helpers under node;
  - on a Windows computer the real embedded C# script is compiled and run in dry-run (everything except a person clicking in the dialog).
Standard library only; node and Windows checks print n/a when they cannot run here.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
from plasbench import chooser, computer_info, fsutil, loadcache, native_picker as np, ui_help, webui  # noqa: E402

FAILED = []
IS_NT = os.name == "nt"


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def boom(*a, **k):
    raise OSError("no wslpath")


# ---------------------------------------------------------------- fakes
FAKE_PY = tmp / "fake_dialog.py"
FAKE_PY.write_text(r'''
import base64, json, os, re, sys, time
name, args = sys.argv[1], sys.argv[2:]
sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
mode = os.environ.get("FAKE_MODE", "choose")
b64 = lambda t: base64.b64encode(t.encode("utf-8")).decode()
def log(**kw):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(name=name, args=args, pid=os.getpid(), **kw)) + "\n")
if name == "powershell":
    script = base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16-le")
    payload = json.loads(base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", script).group(1)))
    log(payload=payload)
    print("PB_PID:%d" % os.getpid(), flush=True)
    if mode == "sleep": time.sleep(60)
    if mode == "cancel": sys.exit(3)
    if mode == "error": print("PB_ERROR:" + b64("the fake dialog failed"), flush=True); sys.exit(4)
    print("PB_RESULT:" + b64(os.environ["FAKE_PATH"]), flush=True); sys.exit(0)
log()
if mode == "sleep": time.sleep(60)
if mode == "cancel": sys.stderr.write("User canceled. (-128)\n"); sys.exit(1)
if mode == "error": sys.stderr.write("zenity: cannot open display\n"); sys.exit(5)
print(os.environ["FAKE_PATH"], flush=True)
''', encoding="utf-8")
FAKE_LOG = tmp / "fake.log"
FAKE_BIN = tmp / "bin"
FAKE_BIN.mkdir()
os.environ["FAKE_LOG"] = str(FAKE_LOG)
REAL_POPEN = subprocess.Popen


def fake_name(argv0):
    base = Path(str(argv0)).name.lower()
    return "powershell" if base.startswith(("powershell", "pwsh")) or base == FAKE_PY.name else base.rsplit(".", 1)[0]


if IS_NT:
    # Windows cannot run a shell wrapper under the name powershell.exe, so every process the picker starts is rerouted to the fake program (same arguments)
    def fake_popen(argv, **kw):
        if Path(str(argv[0])).stem.lower() in ("taskkill", "tasklist"):
            return REAL_POPEN(argv, **kw)
        return REAL_POPEN([sys.executable, str(FAKE_PY), fake_name(argv[0])] + list(argv[1:]), **kw)
    subprocess.Popen = fake_popen
    PK = {"popen": fake_popen}
else:
    for n in ("powershell.exe", "zenity", "osascript", "kdialog"):
        w = FAKE_BIN / n
        w.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_PY}" "{"powershell" if n == "powershell.exe" else n}" "$@"\n')
        w.chmod(0o755)
    os.environ["PLASBENCH_NATIVE_PICKER_POWERSHELL"] = str(FAKE_BIN / "powershell.exe")
    PK = {}


def fakes(mode="choose", path="/home/u/data"):
    os.environ["FAKE_MODE"], os.environ["FAKE_PATH"] = mode, path
    FAKE_LOG.write_text("")


def logged():
    return [json.loads(x) for x in FAKE_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]


def alive(pid):
    if IS_NT:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def which_for(*names):
    table = {n: str(FAKE_BIN / n) for n in names}
    return lambda n: table.get(n)


def main():
    print("path conversion of dialog results (WSL)")
    mounts = "C: /mnt/c 9p rw 0 0\nD: /mnt/d drvfs rw 0 0\n"
    conv = lambda raw, **kw: np.convert_result(raw, "wsl", run=boom, mounts_text=kw.get("mounts", mounts))
    cases = [(r"D:\data\x", "/mnt/d/data/x"), (r"d:\data\x", "/mnt/d/data/x"), ("D:\\", "/mnt/d"), ("D:\\data\\", "/mnt/d/data"), (r"C:\Users\me\My Data", "/mnt/c/Users/me/My Data"),
             ("D:\\donn\u00e9es\\\u00e9t\u00e9 \u4e2d\u6587", "/mnt/d/donn\u00e9es/\u00e9t\u00e9 \u4e2d\u6587"), (r"\\wsl.localhost\Ubuntu-24.04\home\u", "/home/u"),
             (r"\\wsl$\Ubuntu\home\u\my dir", "/home/u/my dir"), ('"D:\\data"', "/mnt/d/data")]
    for raw, want in cases:
        got = conv(raw)
        check(f"{raw!r} -> {want}", got["ok"] and got["path"] == want and got["windows_path"] == raw.strip('"'), got)
    got = conv("E:\\photos")
    check("an unmounted drive: not ok, the same mount hint as the chooser, never run", not got["ok"] and got["mount_hint"] == chooser.mount_command("E") and "sudo mount -t drvfs E: /mnt/e" in got["error"], got)
    got = conv(r"\\fileserver\share\x")
    check("a network share: explained, not mounted", not got["ok"] and "network share" in got["error"] and got["warning"], got)
    got = np.convert_result("/Users/me/data/", "mac")
    check("mac / linux: the path is used as it is (trailing slash dropped)", got["ok"] and got["path"] == "/Users/me/data", got)
    got = np.convert_result("D:\\data", "windows")
    check("native Windows: the Windows path is both", got["ok"] and got["path"] == "D:\\data" and got["windows_path"] == "D:\\data", got)

    print("what Explorer gives the user")
    nt = chooser.normalize_typed
    for raw, want in [('"D:\\data\\x"', "D:\\data\\x"), ("D:\\data\\x", "D:\\data\\x"), ("file:///D:/data/My%20x", "D:/data/My x"), ("file:///home/u/x", "/home/u/x"),
                      ("file://srv/share/a", "\\\\srv\\share\\a"), ("This PC\\Data (D:)\\x", "D:\\x"), ("This PC > Data (D:) > x > y", "D:\\x\\y"), ("This PC\\USB Drive (E:)", "E:\\"),
                      ("\\\\wsl.localhost\\Ubuntu\\home\\u", "\\\\wsl.localhost\\Ubuntu\\home\\u"), ("  /home/u/x  ", "/home/u/x")]:
        check(f"normalize_typed({raw!r})", nt(raw) == want, nt(raw))
    try:
        nt("This PC\\Downloads")
        hint = ""
    except ValueError as exc:
        hint = str(exc)
    check("a breadcrumb that names no drive gives a clear hint", "address bar" in hint and "Copy as path" in hint, hint)
    check("to_linux converts a pasted 'Copy as path' and a file:/// link in WSL", chooser.to_linux('"D:\\data\\x"', wsl=True, run=boom) == "/mnt/d/data/x"
          and chooser.to_linux("file:///D:/data/x", wsl=True, run=boom) == "/mnt/d/data/x" and chooser.to_linux("This PC\\Data (D:)\\x", wsl=True, run=boom) == "/mnt/d/x")
    dest = tmp / "mounted"
    dest.mkdir()
    calls = []
    fake_pop = lambda argv, **kw: calls.append(argv)  # noqa: E731
    real_to_linux, real_mounted = chooser.to_linux, chooser.drive_mounted
    chooser.to_linux, chooser.drive_mounted = lambda *a, **k: str(dest), lambda *a, **k: True
    try:
        r = fsutil.reveal_typed("D:\\data", popen=fake_pop, which=lambda n: "/x/" + n, wsl=True, platform="linux")
        check("Open in Explorer: a mounted /mnt/<drive> folder opens through wslview", r["opened"] and calls[-1][0] == "wslview" and calls[-1][1] == str(dest), (r, calls))
        chooser.drive_mounted = lambda *a, **k: False
        r = fsutil.reveal_typed('"E:\\photos"', popen=fake_pop, which=lambda n: "/x/" + n, wsl=True, platform="linux")
        check("Open in Explorer: a plugged-in but unmounted drive opens the Windows letter with explorer.exe", r["opened"] and calls[-1] == ["/x/explorer.exe", "E:\\photos"], (r, calls))
        r = fsutil.reveal_typed("\\\\wsl.localhost\\Ubuntu\\home\\u", popen=fake_pop, which=lambda n: "/x/" + n, wsl=True, platform="linux")
        check("Open in Explorer: a \\\\wsl.localhost path becomes its Linux folder first", r["opened"] and calls[-1][1] == str(dest), (r, calls))
    finally:
        chooser.to_linux, chooser.drive_mounted = real_to_linux, real_mounted
    try:
        fsutil.reveal_typed(str(tmp / "nothing-here"), popen=fake_pop, which=lambda n: None, wsl=False)
        missing = False
    except FileNotFoundError:
        missing = True
    check("Open in Explorer: a folder that does not exist is a clear error", missing)

    print("capabilities")
    which_none = lambda n: None  # noqa: E731
    cap = lambda plat, env, which, **kw: np.capabilities(platform=plat, env=env, which=which, **kw)
    c = cap("windows", {}, which_for("powershell.exe"))
    check("Windows with powershell.exe", c["available"] and c["kind"] == "windows" and c["via"] == "powershell.exe", c)
    c = cap("wsl", {}, which_for("powershell.exe"))
    check("WSL with powershell.exe interop", c["available"] and c["kind"] == "wsl", c)
    c = cap("wsl", {}, which_none)
    check("WSL without powershell.exe: unavailable, reason names interop", not c["available"] and "interop" in c["reason"], c)
    c = cap("mac", {}, which_for("osascript"))
    check("macOS with osascript", c["available"] and c["kind"] == "mac", c)
    c = cap("linux", {"DISPLAY": ":0"}, which_for("zenity"))
    check("Linux with DISPLAY and zenity", c["available"] and c["kind"] == "zenity", c)
    c = cap("linux", {"WAYLAND_DISPLAY": "wayland-0"}, which_for("kdialog"))
    check("Linux with WAYLAND_DISPLAY and kdialog", c["available"] and c["kind"] == "kdialog", c)
    c = cap("linux", {}, which_for("zenity"))
    check("Linux without DISPLAY: unavailable with the reason", not c["available"] and "no desktop session" in c["reason"], c)
    c = cap("linux", {"DISPLAY": ":0"}, which_none)
    check("Linux with DISPLAY but no zenity / kdialog / yad", not c["available"] and "zenity" in c["reason"], c)
    c = cap("linux", {"DISPLAY": ":0", "SSH_CONNECTION": "1.2.3.4 5 6 7"}, which_for("zenity"))
    check("over SSH: unavailable (the dialog would open on the other desktop)", not c["available"] and "SSH" in c["reason"], c)
    check("a power override that does not exist is not used", not cap("windows", {np.POWERSHELL_ENV: str(tmp / "nope.exe")}, which_none)["available"])

    print("argv construction: nothing is spliced into a command line or a script")
    hostile = ['"; calc.exe; "', "$(calc.exe)", "`calc`", "'; rm -rf / #", "a\nb\rc\x00d", "--help"]
    for h in hostile:
        title = np.clean_text(h, 120)
        script = np.windows_script("folder", title, "C:\\x", [], 30)
        check(f"Windows script: {h!r} travels only inside the base64 payload", "calc.exe" not in script and "rm -rf" not in script and "\n" not in title and "\x00" not in title, script[:80])
        payload = json.loads(base64.b64decode(re.search(r"FromBase64String\('([^']+)'\)", script).group(1)))
        check("  the payload gives the title back unchanged", payload["title"] == title and payload["kind"] == "folder")
        argv = np.windows_argv("powershell.exe", script)
        check("  the argv is a list whose only variable part is -EncodedCommand", argv[-2] == "-EncodedCommand" and all(isinstance(a, str) for a in argv) and "calc" not in " ".join(argv[:-1]))
        mac = np.mac_argv("osascript", "folder", title, "/Users/me", [])
        check("  osascript: the title is its own argv item after the script", mac[-2:] == [title, "/Users/me"] and title not in " ".join(mac[:-2]))
        for tool in ("zenity", "yad"):
            lin = np.linux_argv(tool, tool, "folder", title, "/home/u", [])
            check(f"  {tool}: the title is one --title= argument", f"--title={title}" in lin and sum(title in a for a in lin if title) == 1 or not title, lin)
        lin = np.linux_argv("kdialog", "kdialog", "folder", title, "/home/u", [])
        check("  kdialog: the title follows --title as its own argument", lin[lin.index("--title") + 1] == title)
    check("start folder: control characters are removed", "\n" not in np.clean_text("C:\\a\nb", 100) and np.clean_text("x" * 5000, 1000).__len__() == 1000)
    check("filters keep only safe pattern characters", np.clean_filters([("FASTA", "*.fa;*.fasta; $(x)")]) == [("FASTA", ["*.fa", "*.fasta", "x"])], np.clean_filters([("FASTA", "*.fa;*.fasta; $(x)")]))
    check("the script source has no Invoke-Expression and never runs the chosen path", "Invoke-Expression" not in np.CSHARP and "Process.Start" not in np.CSHARP and "iex " not in np.windows_script("folder", "t", "", [], 5).lower())

    print("pick_folder with fake dialog programs")
    plat_cases = [("zenity", "linux", {"DISPLAY": ":0"}, which_for("zenity"), "/home/u/data"), ("osascript", "mac", {}, which_for("osascript"), "/Users/me/data/"),
                  ("powershell", "windows", {}, which_for("powershell.exe"), "D:\\data\\x")]
    for label, plat, env, wh, path in plat_cases:
        for mode in ("choose", "cancel", "error"):
            np.reset()
            fakes(mode, path)
            r = np.pick_folder("Pick \u00e9", "/tmp", "folder", timeout=60, platform=plat, env=env, which=wh, **PK,
                               **({"which": wh} if False else {}))
            if mode == "choose":
                want = path.rstrip("/") if plat != "windows" else path
                check(f"{label}: chosen path comes back", r["ok"] and r["path"] == want and not r["cancelled"] and r["available"], r)
            elif mode == "cancel":
                check(f"{label}: cancel is not an error", not r["ok"] and r["cancelled"] and r["error"] == "", r)
            else:
                check(f"{label}: an error is reported with its message", not r["ok"] and not r["cancelled"] and r["error"], r)
    np.reset()
    fakes("choose", "/home/u/d\u00e9j\u00e0 \u4e2d\u6587/\U0001f9ec")
    r = np.pick_folder("t", None, "folder", platform="linux", env={"DISPLAY": ":0"}, which=which_for("zenity"), **PK)
    check("non-ASCII output is decoded as UTF-8", r["ok"] and r["path"] == "/home/u/d\u00e9j\u00e0 \u4e2d\u6587/\U0001f9ec", r)
    np.reset()
    fakes("choose", "\u00e9t\u00e9\\\u4e2d\u6587")
    r = np.pick_folder("Titre \u00e9\u4e2d", "C:\\Users", "folder", platform="windows", env={}, which=which_for("powershell.exe"), **PK)
    entry = [e for e in logged() if e["name"] == "powershell"][0]
    check("Windows: the title and start folder reach the dialog script intact (unicode)", entry["payload"]["title"] == "Titre \u00e9\u4e2d" and entry["payload"]["initial"] == "C:\\Users", entry["payload"])
    np.reset()
    fakes("choose", "/Users/me/x")
    np.pick_folder('"; calc.exe; "', None, "folder", platform="mac", env={}, which=which_for("osascript"), **PK)
    check("the hostile title reached osascript as one argument", '"; calc.exe; "' in logged()[0]["args"], logged()[0]["args"])
    np.reset()
    fakes("choose", "/x")
    r = np.pick_folder("t", None, "bogus", platform="mac", env={}, which=which_for("osascript"))
    check("an unknown kind is refused", not r["ok"] and "kind" in r["error"])
    r = np.pick_folder("t", None, "folder", platform="linux", env={}, which=which_none)
    check("headless: available False with the reason, nothing started", not r["ok"] and r["available"] is False and "no desktop session" in r["error"], r)

    print("timeout, cancel, one dialog at a time")
    np.reset()
    fakes("sleep")
    t0 = time.time()
    r = np.pick_folder("t", None, "folder", timeout=1.5, platform="linux", env={"DISPLAY": ":0"}, which=which_for("zenity"), **PK)
    pid = logged()[0]["pid"]
    time.sleep(0.5)
    check("a dialog nobody answers is closed at the timeout, with a message", not r["ok"] and r.get("timed_out") and "seconds" in r["error"] and time.time() - t0 < 20, r)
    check("  and its process is dead", not alive(pid), pid)
    np.reset()
    fakes("sleep")
    kw = dict(platform="linux", env={"DISPLAY": ":0"}, which=which_for("zenity"), **PK)
    a = np.start("folder", "first", None, None, 60, **kw)
    b = np.start("folder", "second", None, None, 60, **kw)
    check("the first request is open", a.get("state") == "open" and a["id"], a)
    check("a second request is refused with 'a folder dialog is already open' and the id of the first", b.get("busy") and b["id"] == a["id"] and "already open" in b["error"], b)
    time.sleep(1.0)
    pid = logged()[0]["pid"]
    check("status says open", np.status(a["id"])["state"] == "open")
    out = np.cancel(a["id"])
    time.sleep(0.3)
    check("cancel ends it: state cancelled, process dead", out["state"] == "cancelled" and not alive(pid), (out, pid))
    check("a later request is accepted again", np.start("folder", "third", None, None, 60, **kw).get("state") == "open")
    np.cancel()
    check("cancel with nothing open is harmless", np.cancel()["state"] == "none")
    check("an unknown id is an error, not a crash", np.status("nope")["state"] == "error")
    np.reset()

    print("routes over HTTP")
    os.environ.setdefault("DISPLAY", ":0")
    os.environ["PATH"] = str(FAKE_BIN) + os.pathsep + os.environ["PATH"]
    loadcache.clear()
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    handler = webui.make_handler(project, jobs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, tok=True):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if tok:
            h["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except ValueError:
                return e.code, {"error": raw.decode("utf-8", "replace")}
    check("capabilities need the token", call("/api/native-picker/capabilities", tok=False)[0] == 403)
    check("open needs the token", call("/api/native-picker/open", {"kind": "folder"}, tok=False)[0] == 403)
    code, caps = call("/api/native-picker/capabilities")
    check("capabilities: answered from the cache, no path of the program leaks", code == 200 and caps["available"] is True and caps.get("exe") is None and "kind" in caps, caps)
    fakes("sleep")
    code, started = call("/api/native-picker/open", {"kind": "folder", "title": "Pick", "initial": ""})
    check("open returns an id at once (never blocks the request)", code == 200 and started.get("id") and started["state"] == "open", (code, started))
    code, again = call("/api/native-picker/open", {"kind": "folder"})
    check("a second open is 409 and names the first", code == 409 and again.get("busy") and again["id"] == started["id"], (code, again))
    check("status polling: open", call(f"/api/native-picker/status?id={started['id']}")[1]["state"] == "open")
    code, out = call("/api/native-picker/cancel", {"id": started["id"]})
    check("cancel over HTTP", code == 200 and out["state"] == "cancelled", out)
    check("status after cancel", call(f"/api/native-picker/status?id={started['id']}")[1]["state"] == "cancelled")
    fakes("choose", "/home/u/chosen")
    code, started = call("/api/native-picker/open", {"kind": "folder", "title": "Pick"})
    final = {}
    for _ in range(100):
        final = call(f"/api/native-picker/status?id={started['id']}")[1]
        if final["state"] != "open":
            break
        time.sleep(0.1)
    check("status polling reaches chosen with the path", final.get("state") == "chosen" and final.get("ok") and final.get("path") == "/home/u/chosen", final)
    code, out = call("/api/native-picker/front", {})
    check("bring to front with nothing open is a clean answer", code == 200 and out["ok"] is False, out)
    h = object.__new__(handler)
    h.client_address = ("192.168.1.20", 5555)
    check("a request from another address is not loopback", h.loopback() is False)
    h.client_address = ("127.0.0.1", 5555)
    check("127.0.0.1 is loopback", h.loopback() is True)
    h.client_address = ("::1", 5555, 0, 0)
    check("::1 is loopback", h.loopback() is True)
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    blocks = re.findall(r"# ---- native folder window.*?# ---- end native folder window ----", src, re.S)
    check("both route blocks refuse a non-loopback client", len(blocks) == 2 and all("self.loopback()" in b for b in blocks))
    check("the capabilities route does not start a program (no probe on the window load path)", "which" not in blocks[0].replace("capabilities", "") or "subprocess" not in blocks[0])
    server.shutdown()
    np.reset()
    check("loading the page schema does not call the picker", "native-picker" not in (ROOT / "plasbench" / "ui_schema.py").read_text(encoding="utf-8"))

    print("Windows volumes: parsers and capacity")
    TB = 1_000_203_091_968
    disks_json = json.dumps([
        {"DeviceID": "C:", "VolumeName": "OS", "DriveType": 3, "FileSystem": "NTFS", "Size": 511_000_000_000, "FreeSpace": 120_000_000_000, "ProviderName": None, "Access": 0, "Bus": "NVMe"},
        {"DeviceID": "D:", "VolumeName": "Data", "DriveType": 3, "FileSystem": "NTFS", "Size": TB, "FreeSpace": 400_000_000_000, "ProviderName": None, "Access": 0, "Bus": "USB"},
        {"DeviceID": "E:", "VolumeName": "", "DriveType": 2, "FileSystem": None, "Size": None, "FreeSpace": None, "ProviderName": None, "Access": 0, "Bus": None},
        {"DeviceID": "F:", "VolumeName": "STICK", "DriveType": 2, "FileSystem": "exFAT", "Size": 31_000_000_000, "FreeSpace": 30_000_000_000, "ProviderName": None, "Access": 0, "Bus": None},
        {"DeviceID": "Z:", "VolumeName": "", "DriveType": 4, "FileSystem": "NTFS", "Size": 2_000_000_000_000, "FreeSpace": 1_000_000_000_000, "ProviderName": r"\\nas\lab", "Access": 0, "Bus": None}])
    parsed = computer_info.parse_windows_disks(disks_json)
    check("Win32_LogicalDisk JSON: five volumes with their letters", [d["letter"] for d in parsed] == list("CDEFZ"), parsed)
    check("a drive with no media has no size and says so", next(d for d in parsed if d["letter"] == "E")["media"] is False and next(d for d in parsed if d["letter"] == "F")["media"])
    gv = json.dumps([{"DriveLetter": "D", "FileSystemLabel": "USB", "DriveType": "Removable", "FileSystem": "exFAT", "Size": 64_000_000_000, "SizeRemaining": 10_000_000_000},
                     {"DriveLetter": "", "FileSystemLabel": "Recovery", "DriveType": "Fixed", "Size": 1, "SizeRemaining": 1},
                     {"DriveLetter": "Y", "FileSystemLabel": "NAS", "DriveType": "Network", "FileSystem": "NTFS", "Size": 5, "SizeRemaining": 2}])
    g = computer_info.parse_get_volume(gv)
    check("Get-Volume JSON: USB (Removable) and network; a volume without a letter is skipped", [(d["letter"], d["drive_type"]) for d in g] == [("D", 2), ("Y", 4)], g)
    wmic = "Node,Access,DeviceID,DriveType,FileSystem,FreeSpace,ProviderName,Size,VolumeName\r\nPC,0,C:,3,NTFS,100,,500,OS\r\nPC,0,E:,2,,,,,\r\nPC,0,Z:,4,NTFS,5,\\\\nas\\lab,10,\r\n"
    rows = computer_info.parse_wmic_csv(wmic)
    check("wmic CSV: three drives, the empty one with blank size", len(rows) == 3 and rows[1]["Size"] == "" and rows[2]["ProviderName"] == "\\\\nas\\lab", rows)
    mounts_c = "C: /mnt/c 9p rw 0 0\n"
    pcs = chooser.windows_drive_rows(parsed, True, mounts_c)
    byl = {r["windows"][0]: r for r in pcs}
    check("WSL rows: C is mounted and opens at /mnt/c", byl["C"]["mounted"] and byl["C"]["path"] == "/mnt/c", byl["C"])
    check("WSL rows: a USB stick plugged after WSL started is LISTED, marked not mounted, with the exact mount command", byl["F"]["mounted"] is False and byl["F"]["type"] == "removable"
          and byl["F"]["hint"] == "sudo mkdir -p /mnt/f && sudo mount -t drvfs F: /mnt/f" and byl["F"]["path"] == "", byl["F"])
    check("WSL rows: a fixed disk on a USB bus is shown as removable", byl["D"]["type"] == "removable")
    check("WSL rows: a network drive is listed as network with its capacity", byl["Z"]["type"] == "network" and byl["Z"]["total"] == 2_000_000_000_000 and byl["Z"]["free"] == 1_000_000_000_000)
    check("WSL rows: a card reader with no disk has no capacity and no mount command", byl["E"]["media"] is False and byl["E"]["total"] is None and "hint" not in byl["E"])
    winrows = chooser.windows_drive_rows(parsed, False)
    check("native Windows rows open at the letter; no media cannot be opened", {r["windows"][0]: r["path"] for r in winrows} == {"C": "C:\\", "D": "D:\\", "E": "", "F": "F:\\", "Z": "Z:\\"})
    check("the chooser's This PC takes the host's list (pc_places with disks)", [p["windows"] for p in chooser.pc_places("linux", True, mounts_text=mounts_c, disks=parsed)] == [f"{c}:\\" for c in "CDEFZ"])
    check("capacity: used = size - free, from Windows' own numbers", byl["D"]["used"] == TB - 400_000_000_000 and byl["D"]["total"] == TB)
    gib = lambda n: round(n / 2 ** 30, 1)  # noqa: E731
    check("units: a '1 TB' disk is 931.5 GB where GB = 2^30 (as Explorer says) and 1000.2 GB in decimal units; the code says which", gib(TB) == 931.5 and round(TB / 1e9, 1) == 1000.2
          and computer_info.GB == 2 ** 30 and "2^30" in Path(computer_info.__file__).read_text(encoding="utf-8"))
    print("the false capacity: an empty /mnt/e folder reports Ubuntu's own virtual disk")
    mnt = tmp / "mnt"
    for n in "ce":
        (mnt / n).mkdir(parents=True)
    fake_free = lambda p: {str(mnt / "c"): 120_000_000_000}.get(str(p), 1_000_000_000_000)  # noqa: E731  (an unmounted folder would answer with the VHD's free space)
    drives = chooser.wsl_drives(f"C: {mnt / 'c'} 9p rw 0 0\n", str(mnt), fake_free)
    e = next(d for d in drives if Path(d["path"]).name == "e")
    c = next(d for d in drives if Path(d["path"]).name == "c")
    check("a mounted drive shows its free space", c["free"] == 120_000_000_000 and c["mounted"], c)
    check("a leftover empty /mnt/e is NOT given the virtual disk's size: not mounted, no capacity, mount command offered", e["free"] is None and e["mounted"] is False and "drvfs E:" in e["hint"], e)
    check("drive_mounted tells a real mount from a folder", chooser.drive_mounted("c", f"C: {mnt / 'c'} 9p rw 0 0\n", str(mnt)) and not chooser.drive_mounted("e", f"C: {mnt / 'c'} 9p rw 0 0\n", str(mnt)))
    check("computer_info reads the same disks (one function)", hasattr(computer_info, "windows_disks") and "windows_disks(run)" in Path(computer_info.__file__).read_text(encoding="utf-8"))
    check("the browse root view reads windows_disks, the card reads windows_disks", "computer_info.windows_disks" in src)

    print("the page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    for needle in ('$("#in_addf").onclick = () => pickPath(', '$("#in_sheet_b").onclick = () => pickPath(', '$("#sc_pick").onclick = () => pickPath(', '$("#st_addex").onclick = () => pickPath(', '$("#runadd").onclick = () => pickPath('):
        check(f"former direct site still goes through pickPath: {needle[:22]}", needle in html)
    sites = re.findall(r'data-browse="', html)
    check("every Browse button (data-browse) is drawn on the pages and handled by the one click handler", len(sites) >= 10 and 'e.target.closest("[data-browse]")' in html and html.count("pickPath(b.dataset.dir") == 1, len(sites))
    check("pickPath asks for the native window first and falls back to the built-in browser with a reason", all(k in html for k in ("async function pickPath", "caps.available && npPref() !== \"inline\"", "pickNative(", "pickInline(", "using the built-in browser")))
    check("the capabilities are asked only when Browse is used (never on the load path)", html.count('"native-picker/capabilities"') == 1 and html.count("await npCaps()") == 1 and "async function npCaps" in html)
    check("the waiting dialog: message, Cancel, Bring it to front, built-in browser", all(k in html for k in ("Waiting for the folder window... (it may be behind this window)", 'id="np_cancel"', 'id="np_front"', 'id="np_inline"')))
    check("the choice is remembered in localStorage inside try/catch", "pb_picker" in html and re.search(r'const npPref = \(\) => \{ try \{ return localStorage\.getItem\("pb_picker"\)', html) and "const npSetPref = v => { try {" in html)
    check("the chosen path is validated with the existing folder check", "async function npValidate" in html and "workspace/check?path=" in html)
    check("Open in Explorer is added next to every Browse button and reuses reveal()", "data-openexp" in html and "window.reveal(String(path).trim())" in html and "function decorateBrowse" in html)
    check("pasting an Explorer path is normalised", "function normPasted" in html and 'document.addEventListener("paste"' in html)
    check("the built-in browser has Back / Forward / Up / Refresh, filter, sort, hidden files, copy of the mount command, recent folders", all(k in html for k in ('id="fs_back"', 'id="fs_fwd"', 'id="fs_refresh"', 'id="fs_filter"', 'id="fs_sort"', 'id="fs_hidden"', "data-copy", "Recent folders", "not mounted in Ubuntu yet")))
    check("no browser dialogs were added", not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", html.replace("askConfirm(", "").replace("showConfirm(", "")), "")
    for key in ("browse", "inline", "open_explorer", "drive_capacity", "drive_unmounted", "paste_path"):
        check(f"tooltip text from ui_help: {key}", ui_help.NATIVE_PICKER[key]["summary"])
    from plasbench import ui_schema
    check("the schema carries the picker help to the page", "native_picker_help" in ui_schema.schema() and "browse" in ui_schema.schema()["native_picker_help"])
    check("the page reads the tooltips from the schema", "native_picker_help" in html)

    subprocess.Popen = REAL_POPEN
    print("pure helpers under node")
    node = shutil.which("node")
    if node:
        a = html.index("/* native-picker helpers (pure) */")
        b = html.index("/* end native-picker helpers */")
        fm = re.search(r"const fmtGBytes = .*", html).group(0)
        js = fm + "\n" + html[a:b] + r'''
const assert = (c, m) => { if (!c) { console.log("FAIL " + m); process.exitCode = 1; } else console.log("ok " + m); };
assert(normPasted('"D:\\data\\x"').path === "D:\\data\\x", "Copy as path");
assert(normPasted("file:///D:/data/My%20x").path === "D:/data/My x", "file URL");
assert(normPasted("file:///home/u").path === "/home/u", "file URL linux");
assert(normPasted("file://srv/share/a").path === "\\\\srv\\share\\a", "file URL unc");
assert(normPasted("This PC\\Data (D:)\\x").path === "D:\\x", "breadcrumb with a drive");
assert(normPasted("This PC > Data (D:) > x").path === "D:\\x", "breadcrumb with >");
assert(/address bar/.test(normPasted("This PC\\Downloads").hint), "breadcrumb without a drive gives a hint");
assert(normPasted("  /home/u/x ").path === "/home/u/x", "plain");
assert(normPasted("\\\\wsl.localhost\\Ubuntu\\home\\u").path === "\\\\wsl.localhost\\Ubuntu\\home\\u", "wsl.localhost kept");
const rows = [{name: "b", dir: false, size: 5, mtime: 1}, {name: "a10", dir: true, mtime: 5}, {name: "a2", dir: true, mtime: 9}, {name: "c", dir: false, size: 50, mtime: 3}];
assert(fsSortRows(rows, "name").map(r => r.name).join() === "a2,a10,b,c", "sort by name: folders first, numbers natural");
assert(fsSortRows(rows, "size").map(r => r.name).join() === "a2,a10,c,b", "sort by size");
assert(fsSortRows(rows, "mtime").map(r => r.name).join() === "a2,a10,c,b", "sort by modified");
assert(fsFilterRows(rows, " A1 ").map(r => r.name).join() === "a10", "filter");
assert(fsPct({total: 1000, free: 250}) === 75, "capacity bar");
assert(fsSizeText(512) === "512 B" && fsSizeText(2048) === "2 KB", "sizes");
assert(fmtGBytes(1000203091968) === "931.51 GB", "1 TB drive = 931.51 GB (2^30), as Explorer");
'''
        f = tmp / "helpers.js"
        f.write_text(js, encoding="utf-8")
        done = subprocess.run([node, str(f)], capture_output=True, text=True)
        out = done.stdout
        check("node: pure helpers (normPasted, sort, filter, capacity)", done.returncode == 0 and "FAIL" not in out and out.count("ok ") >= 15, out + done.stderr[-300:])
        script = max(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S), key=len)
        pf = tmp / "page.js"
        pf.write_text(script, encoding="utf-8")
        done = subprocess.run([node, "--check", str(pf)], capture_output=True, text=True)
        check("node --check of the page script", done.returncode == 0, done.stderr[:300])
    else:
        print("  n/a   node not found")

    print("the real Windows dialog script on this computer (compiled and run in dry-run; no person clicks the dialog)")
    ps = shutil.which("powershell.exe") if IS_NT else None
    if ps:
        subprocess.Popen = REAL_POPEN
        for kind in ("folder", "file", "save"):
            script = np.windows_script(kind, "Titre \u00e9 \u4e2d \"; calc.exe; \"", "C:\\Windows", [("FASTA", ["*.fa"])], 20, dry=True)
            done = subprocess.run(np.windows_argv(ps, script), capture_output=True, timeout=180)
            out = done.stdout.decode("utf-8", "replace")
            res = np._decode_tag(out, "PB_RESULT")
            check(f"the C# script compiles with Add-Type and the {kind} dialog is configured (dry run, exit 0)", done.returncode == 0 and res and res.startswith("dry-run"), (done.returncode, out[:200], done.stderr[:300]))
        folder_script = np.windows_script("folder", "t", "C:\\Windows", [], 20, dry=True)
        out = subprocess.run(np.windows_argv(ps, folder_script), capture_output=True, timeout=180).stdout.decode()
        opts = int(re.search(r"options=0x([0-9a-f]+)", np._decode_tag(out, "PB_RESULT")).group(1), 16)
        check("  FOS_PICKFOLDERS (0x20), FOS_FORCEFILESYSTEM (0x40) and FOS_PATHMUSTEXIST (0x800) are set", opts & 0x20 and opts & 0x40 and opts & 0x800, hex(opts))
        # a real start, cancelled at once: the process must be gone and the state cancelled
        np.reset()
        j = np.start("folder", "smoke", "C:\\Windows", None, 30, platform="windows", env={}, which=lambda n: ps if n == "powershell.exe" else None)
        time.sleep(0.4)
        out = np.cancel(j["id"])
        proc = next(iter(np._jobs.values())).proc
        check("a real dialog process killed straight away: cancelled, no process left", out["state"] == "cancelled" and proc.poll() is not None, out)
        np.reset()
        t0 = time.time()
        r = np.pick_folder("smoke", "C:\\Windows", "folder", timeout=1, platform="windows", env={}, which=lambda n: ps if n == "powershell.exe" else None)
        check("a real dialog with a 1 second timeout is killed and reported", r.get("timed_out") and time.time() - t0 < 30, r)
        print("  NOTE: the real Explorer dialog was NOT clicked by a person; only the script, the COM setup and the process control were exercised")
    else:
        print("  n/a   not a Windows computer with powershell.exe")
    np.reset()
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
