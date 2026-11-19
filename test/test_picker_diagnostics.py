#!/usr/bin/env python3
"""Why Browse did not open the folder window, and Docker (plasbench/native_picker.py, picker_check.py, docker_helper.py, the page).

What this covers, and how:

  WSL            interop state (wsl.conf, binfmt_misc, WSL_INTEROP), every place powershell.exe is looked for, the loopback rule for a WSL2 localhost-forwarded browser
                 (with injected files, environment and `which`: the real WSL cannot run here, so these are fakes)
  command line   the script is far longer than 8191 characters as -EncodedCommand: it goes as a short gzip unpacker, a .ps1 file in the Windows temp folder, or on stdin
  fallbacks      the order in the script: Explorer dialog (C#), FolderBrowserDialog, Shell.Application, then an error that makes the page offer the built-in browser
  opened signal  the job says 'opened' only when the script does (so the page can warn after 8 s); the page code for it
  picker-check   the report for each simulated environment: WSL ok, no interop, no powershell, locked-down PowerShell, Docker, headless, SSH, Windows, macOS, Linux desktop
  Docker         detection (cgroup v1 and v2, /.dockerenv, the environment), /proc/self/mountinfo parsing, the docker run command for Windows paths, spaces, unicode and UNC,
                 and when 'run in Docker instead' is offered
  the page       no browser dialogs, the Why? fold, Copy diagnostics, the Test button, the Docker dialog
  real Windows   on a Windows computer the real PowerShell route is run end to end: each strategy in dry-run, the temp .ps1 route with unicode and spaces, the stdin route,
                 and the real folder window found through UI Automation (visible, titled as requested, foreground), closed with WM_CLOSE and reported as cancelled.
                 Elsewhere those lines print n/a.

Standard library only (node for the page syntax check; n/a without it).
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
from plasbench import chooser, docker_helper as dh, loadcache, native_picker as np, picker_check as pc, webui  # noqa: E402

FAILED = []
IS_NT = os.name == "nt"
REAL_KILL = np._kill


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def b64(text):
    import base64
    return base64.b64encode(text.encode("utf-8")).decode()


class FakeProc:
    """A process that has already said what it will say; `linger` seconds before it 'exits' with rc. Never a real pid."""
    n = 7000

    def __init__(self, out=b"", err=b"", rc=0, linger=0.0):
        FakeProc.n += 1
        self.pid = FakeProc.n
        self.stdout, self.stderr, self.stdin = io.BytesIO(out), io.BytesIO(err), io.BytesIO()
        self.returncode = None
        self._rc, self._end = rc, time.time() + linger

    def poll(self):
        if self.returncode is None and time.time() >= self._end:
            self.returncode = self._rc
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def popen_saying(out_lines, rc=0, err=b"", linger=0.0):
    seen = []

    def popen(argv, **kw):
        seen.append(list(argv))
        return FakeProc(("\n".join(out_lines) + "\n").encode("utf-8") if out_lines else b"", err, rc, linger)
    popen.seen = seen
    return popen


def ex_true(path):
    return path not in ("/.dockerenv", "/run/.containerenv")      # everything exists except the markers of a container


def which_of(table):
    return lambda n: table.get(n)


def main():
    np._kill = lambda proc, win_pid=None, plat="linux", exe=None: proc.kill()     # fake processes must never reach a real taskkill / killpg

    print("WSL: wsl.conf, interop, where powershell.exe is looked for")
    conf = np.parse_wsl_conf("[automount]\nenabled=true\n[interop]\nenabled = false # no\nappendWindowsPath=False\n")
    check("wsl.conf: [interop] enabled=false and appendWindowsPath=False are read; [automount] enabled is not confused with it", conf == {"interop_enabled": False, "append_windows_path": False}, conf)
    check("wsl.conf: nothing set means None (the default, on)", np.parse_wsl_conf("") == {"interop_enabled": None, "append_windows_path": None})
    files = {"/proc/sys/fs/binfmt_misc/WSLInterop": "enabled\ninterpreter /init\nflags: PF\n"}
    st = np.interop_state({}, lambda p: files.get(p))
    check("interop on (WSLInterop says enabled)", st["enabled"] is True, st)
    st = np.interop_state({}, lambda p: {"/proc/sys/fs/binfmt_misc/WSLInterop": "disabled\n"}.get(p))
    check("interop off (WSLInterop says disabled), with the way to fix it", st["enabled"] is False and "wsl --shutdown" in st["detail"], st)
    st = np.interop_state({}, lambda p: {"/etc/wsl.conf": "[interop]\nenabled=false\n", "/proc/sys/fs/binfmt_misc/WSLInterop": "enabled\n"}.get(p))
    check("interop off by /etc/wsl.conf even when the kernel file says enabled", st["enabled"] is False and "wsl.conf" in st["detail"], st)
    st = np.interop_state({"WSL_INTEROP": "/run/WSL/12_interop"}, lambda p: None)
    check("only WSL_INTEROP set: on", st["enabled"] is True, st)
    st = np.interop_state({}, lambda p: None)
    check("nothing readable: unknown (None), not a false 'off'", st["enabled"] is None, st)
    st = np.interop_state({}, lambda p: {"/etc/wsl.conf": "[interop]\nappendWindowsPath=false\n", "/proc/sys/fs/binfmt_misc/WSLInterop": "enabled\n"}.get(p))
    check("appendWindowsPath=false is explained (PATH has no Windows programs)", st["enabled"] is True and "appendWindowsPath=false" in st["detail"], st)

    ps_fixed = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    none_which = which_of({})
    exe, tried = np.find_powershell({}, which_of({"powershell.exe": "/mnt/c/WIN/powershell.exe"}), lambda p: False, listdir=lambda d: [])
    check("powershell.exe found on PATH is used as returned", exe == "/mnt/c/WIN/powershell.exe", (exe, tried))
    exe, tried = np.find_powershell({}, none_which, lambda p: p == ps_fixed, listdir=lambda d: ["c"])
    check("not on PATH (appendWindowsPath=false): the /mnt/c System32 location is found", exe == ps_fixed, (exe, tried))
    other = "/mnt/d/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    exe, tried = np.find_powershell({}, none_which, lambda p: p == other, listdir=lambda d: ["c", "d"])
    check("Windows on another drive: /mnt/<drive>/Windows is scanned", exe == other, (exe, tried))
    calls = []

    def run_cmd(argv, **kw):
        calls.append(list(argv))
        if argv[0].endswith("cmd.exe"):
            return subprocess.CompletedProcess(argv, 0, b"E:\\WinNT\r\n", b"")
        if argv[0] == "wslpath":
            return subprocess.CompletedProcess(argv, 0, "/mnt/e/WinNT\n", "")
        raise OSError(argv)
    viaenv = "/mnt/e/WinNT/System32/WindowsPowerShell/v1.0/powershell.exe"
    exe, tried = np.find_powershell({}, which_of({"cmd.exe": "/mnt/c/Windows/System32/cmd.exe"}), lambda p: p == viaenv, run=run_cmd, listdir=lambda d: [])
    check("%SystemRoot% asked of cmd.exe (and wslpath) when the usual places fail", exe == viaenv and any(c[0].endswith("cmd.exe") for c in calls), (exe, tried, calls))
    calls.clear()
    np.find_powershell({}, which_of({"powershell.exe": "/p"}), lambda p: True, run=run_cmd, listdir=lambda d: [])
    check("cmd.exe is not started when the usual places already work", not calls, calls)
    exe, tried = np.find_powershell({"PLASBENCH_NATIVE_PICKER_POWERSHELL": "/nope"}, none_which, lambda p: False, listdir=lambda d: [])
    check("an override that does not exist is reported, not silently replaced", exe is None and tried == ["/nope"], (exe, tried))
    caps = np.capabilities("wsl", {}, none_which, True, exists=lambda p: False, read=lambda p: None, listdir=lambda d: [], run=run_cmd)
    check("no powershell anywhere: unavailable, and the reason lists where it looked and names wsl.conf", not caps["available"] and "wsl.conf" in caps["reason"] and "/mnt/c/Windows" in caps["reason"] and caps["tried"], caps["reason"])
    caps = np.capabilities("wsl", {}, which_of({"powershell.exe": "/p"}), True, exists=ex_true, read=lambda p: {"/etc/wsl.conf": "[interop]\nenabled=false\n"}.get(p), listdir=lambda d: [])
    check("interop disabled: unavailable with the interop reason (before looking for powershell)", not caps["available"] and "interop is off" in caps["reason"], caps)
    caps = np.capabilities("wsl", {}, which_of({"powershell.exe": "/p"}), True, exists=ex_true, read=lambda p: None, listdir=lambda d: [])
    check("interop unknown but powershell found: available", caps["available"] and caps["kind"] == "wsl" and caps["exe"] == "/p", caps)

    print("the loopback rule")
    for addr in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "127.0.0.5", "::1%lo", "localhost"):
        check(f"loopback address {addr} is this computer", np.is_local_client(addr, "linux"))
    for addr in ("8.8.8.8", "192.168.1.20", "172.17.0.1", "10.0.0.5", "", None, "fe80::1"):
        check(f"{addr!r} is refused on Linux", not np.is_local_client(addr, "linux"))
    check("WSL2: the Windows host (the default gateway of the VM) is this computer", np.is_local_client("172.20.208.1", "wsl", gateways=["172.20.208.1"]))
    check("WSL2: the ::ffff: form of the gateway too", np.is_local_client("::ffff:172.20.208.1", "wsl", gateways=["172.20.208.1"]))
    check("WSL2: one of the VM's own addresses", np.is_local_client("172.20.210.5", "wsl", gateways=[], local_ips=["172.20.210.5"]))
    check("WSL2: a remote host is still refused", not np.is_local_client("192.168.1.20", "wsl", gateways=["172.20.208.1"], local_ips=["172.20.210.5"]))
    check("outside WSL the gateway rule does not apply (a Docker bridge address is refused)", not np.is_local_client("172.17.0.1", "linux", gateways=["172.17.0.1"]))
    route = "Iface\tDestination\tGateway\tFlags\neth0\t00000000\t01D014AC\t0003\neth0\t00D014AC\t00000000\t0001\n"
    check("the gateway is read from /proc/net/route (01D014AC is 172.20.208.1)", np._gateway_ips(lambda p: route) == ["172.20.208.1"], np._gateway_ips(lambda p: route))
    page = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("the server uses the one rule for every native-picker route", "native_picker.is_local_client(" in page and "def loopback(self)" in page)

    print("the command line: a long script never depends on a command-line limit")
    script = np.windows_script("folder", "Choose a folder", "C:\\data", [], 600)
    plain = np.encoded_argv("powershell.exe", script)
    check("the real script is longer than the 8191-character limit as -EncodedCommand (so the plain route is NOT used)", len(plain[-1]) > 8191, len(plain[-1]))
    routes = np.windows_routes("powershell.exe", script)
    check("the first route is the short ASCII unpacker, within the limit", routes[0][0] == "gzip" and len(routes[0][1][-1]) <= np.COMMAND_LINE_LIMIT, [(r[0], len(r[1][-1])) for r in routes])
    check("  the unpacker carries the whole script (it round-trips)", __import__("gzip").decompress(__import__("base64").b64decode(re.search(r"FromBase64String\('([^']+)'", routes[0][1][-1]).group(1))).decode() == script)
    check("  the unpacker has no double quote (it travels as one -Command argument)", '"' not in routes[0][1][-1])
    check("stdin is always the last resort and is the same one-line unpacker", routes[-1][0] == "stdin" and routes[-1][1][-2:] == ["-Command", "-"])
    small = np.windows_script("folder", "t", "", [], 5)
    check("a script that fits the limit goes as a plain -EncodedCommand", np.windows_routes("powershell.exe", small, limit=10**6)[0][0] == "encoded")
    written = {}

    def writer(name, text):
        written[name] = text
        return str(tmp / name)
    r = np.windows_routes("powershell.exe", script, limit=10, win_temp="C:\\Users\\J\u00fcrgen B\\AppData\\Local\\Temp", write_file=writer)
    names = [x[0] for x in r]
    check("both too long for the limit: a .ps1 file in the Windows temp folder, then stdin", names[:2] == ["file", "stdin"], names)
    file_route = r[0]
    check("  the file route is -File with the Windows path (spaces and unicode intact), not a \\\\wsl$ path", file_route[1][-2] == "-File" and file_route[1][-1].startswith("C:\\Users\\J\u00fcrgen B\\AppData\\Local\\Temp\\plasbench-pick-") and file_route[1][-1].endswith(".ps1"), file_route[1])
    check("  and its cleanup path is the local file", file_route[2] == str(tmp / list(written)[0]))
    f = np._write_script_file(str(tmp))("x\u00e9 y.ps1", "Write-Output 'h\u00e9'")
    raw = Path(f).read_bytes()
    check("a script file starts with a UTF-8 BOM and keeps unicode (PowerShell 5.1 reads it correctly)", raw[:3] == b"\xef\xbb\xbf" and "h\u00e9".encode() in raw)

    print("fallbacks: the order in the script")
    i1, i2, i3, i4 = (script.index(k) for k in ("PBPick]::Run", "'winforms'", "Shell.Application", "no Windows folder window could be opened"))
    check("Explorer dialog (C#) first, then FolderBrowserDialog, then Shell.Application, then the error that makes the page offer the built-in browser", i1 > script.index("function PBFallback") and script.index("FolderBrowserDialog") < script.index("Shell.Application") < i4, (i1, i2, i3, i4))
    check("a compile failure falls through (catch sets the code to 5, which runs PBFallback)", "catch { PBSay 'PB_NOTE'" in script and "if ($code -eq 5)" in script and "PBFallback $p" in script)
    check("the script starts the dialog in a single-threaded apartment (-STA) and says PB_OPENED when the window exists", "-STA" in plain and "PB_OPENED" in script)
    check("a forced strategy skips the better windows", '"strategy": "winforms"' in __import__("base64").b64decode(re.search(r"FromBase64String\('([^']+)'", np.windows_script("folder", "t", "", [], 5, strategy="winforms")).group(1)).decode())
    check("the dialog is brought forward: Alt key trick, AttachThreadInput, SetForegroundWindow, FlashWindow as the last resort", all(k in np.CSHARP for k in ("keybd_event", "AttachThreadInput", "SetForegroundWindow", "FlashWindow", "GetWindow(owner, 6)")))
    check("the owner is a top-most, invisible form centred on the screen (not at -32000)", "owner.TopMost = true" in np.CSHARP and "-32000" not in np.CSHARP and "CenterScreen" in np.CSHARP)

    print("the 'opened' signal")
    np.reset()
    out = ["PB_PID:99", "PB_ENV:" + b64("ps=5.1"), "PB_STRATEGY:" + b64("ifiledialog"), "PB_OPENED:" + b64("ifiledialog"), "PB_FOCUS:" + b64("flashed"), "PB_RESULT:" + b64("D:\\data\\x")]
    res = np.pick_folder("t", None, "folder", None, 20, platform="windows", env={}, which=which_of({"powershell.exe": "powershell.exe"}), popen=popen_saying(out, 0))
    v = np.last_view()
    check("the job says opened, with the window used and the focus result", res["ok"] and v["opened"] is True and v["strategy"] == "ifiledialog" and v["focus"] == "flashed" and v["opened_after"] is not None, v)
    np.reset()
    res = np.pick_folder("t", None, "folder", None, 20, platform="windows", env={}, which=which_of({"powershell.exe": "powershell.exe"}),
                         popen=popen_saying(["PB_PID:99", "PB_ENV:" + b64("ps=5.1"), "PB_NOTE:" + b64("compile failed: blocked"), "PB_ERROR:" + b64("no Windows folder window could be opened here")], 6))
    v = np.last_view()
    check("no PB_OPENED: opened stays False, the notes and the exact error are kept", not res["ok"] and v["opened"] is False and "no Windows folder window" in res["error"] and any("compile failed" in n for n in v["notes"]), (res, v))
    np.reset()
    res = np.pick_folder("t", None, "folder", None, 20, platform="windows", env={}, which=which_of({"powershell.exe": "powershell.exe"}), popen=popen_saying([], 1, b"Cannot invoke method. Method invocation is supported only on core types in this language mode.\n"))
    check("a locked-down PowerShell (Constrained Language Mode) is named as such", not res["ok"] and "locked down" in res["error"], res)
    np.reset()
    res = np.pick_folder("t", None, "folder", None, 20, platform="windows", env={}, which=which_of({"powershell.exe": "powershell.exe"}), popen=popen_saying([], 1, b""))
    check("PowerShell that exits without running the script is reported with its exit code, not as a silent nothing", not res["ok"] and "exit 1" in res["error"], res)
    np.reset()
    res = np.pick_folder("t", None, "folder", None, 20, platform="linux", env={"DISPLAY": ":0"}, which=which_of({"zenity": "/usr/bin/zenity"}), popen=popen_saying(["/home/u/data"], 0))
    check("zenity and the others give no signal: opened is True from the start (the program started)", res["ok"] and np.last_view()["opened"] is True)
    # a server-side view the page polls: still open and not yet opened
    np.reset()
    job_started = np.start("folder", "t", None, None, 20, platform="windows", env={}, which=which_of({"powershell.exe": "powershell.exe"}),
                           popen=popen_saying(["PB_PID:99", "PB_ENV:" + b64("ps=5.1")], 0, linger=1.5))
    time.sleep(0.4)
    s1 = np.status(job_started["id"])
    check("while the script has not said it is open: state open, opened False, elapsed counting (the page warns at 8 s)", s1["state"] == "open" and s1["opened"] is False and s1["elapsed"] >= 0, s1)
    np.cancel(job_started["id"])
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("page: no signal for 8 s opens the failure dialog with 'Keep waiting' and the built-in browser", "s.elapsed >= 8" in html and "npFailDialog(" in html and 'label: "Keep waiting"' in html and "Use the built-in browser" in html)
    check("page: an unknown job id or a lost server (4 failed polls) ends the wait with a message", "++bad >= 4" in html and "lost contact with PlasBench" in html)

    print("picker-check for each simulated environment")
    ps_ok = "hello\n5.1.26100.1\nFullLanguage\nSTA\nRemoteSigned\nC:\\Users\\me\\AppData\\Local\\Temp\\\n"

    def run_for(hello=ps_ok, compile_out="42\n"):
        def run(argv, **kw):
            if argv[0] == "wslpath":
                m = re.match(r"^([A-Za-z]):[\\/]*(.*)$", argv[-1])
                return subprocess.CompletedProcess(argv, 0, f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/") + "\n", "")
            text = " ".join(str(a) for a in argv)
            if "PBProbe" in text:
                return subprocess.CompletedProcess(argv, 0 if compile_out else 1, compile_out.encode(), b"" if compile_out else b"Add-Type : Cannot add type")
            if "'hello'" in text:
                return subprocess.CompletedProcess(argv, 0 if hello else 1, hello.encode(), b"" if hello else b"The term is not recognized")
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        return run

    good_dialog = ["PB_PID:1", "PB_ENV:" + b64("ps=5.1"), "PB_STRATEGY:" + b64("ifiledialog"), "PB_OPENED:" + b64("ifiledialog"), "PB_FOCUS:" + b64("foreground"), "PB_SELFTEST:" + b64("closed"), "PB_RESULT:" + b64("dry-run")]

    def steps_of(rep):
        return {s["name"]: s for s in rep["steps"]}

    wsl_files = {"/proc/sys/fs/binfmt_misc/WSLInterop": "enabled\n"}
    reps = {}
    np.reset()
    reps["wsl_ok"] = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(), read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    r = reps["wsl_ok"]
    check("WSL ok: environment, interop, powershell, hello, compile, window, front and conversion all PASS, and the verdict says Explorer window", r["environment"] == "wsl" and r["ok"] and r["native"] == "ifiledialog"
          and all(s["status"] in ("PASS", "INFO", "n/a") for s in r["steps"]) and "Explorer folder window" in r["verdict"], pc.format_report(r))
    check("  the hello step reports PowerShell version, language mode, policy and apartment", "FullLanguage" in steps_of(r)["A minimal PowerShell script runs"]["detail"] and "5.1.26100.1" in steps_of(r)["A minimal PowerShell script runs"]["detail"])
    check("  the conversion step shows C:\\Windows -> /mnt/c/Windows", "/mnt/c/Windows" in steps_of(r)["Windows path -> Linux path conversion"]["detail"])
    np.reset()
    reps["wsl_nointerop"] = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(),
                                          read=lambda p: {"/etc/wsl.conf": "[interop]\nenabled=false\n"}.get(p), exists=ex_true, listdir=lambda d: [])
    r = reps["wsl_nointerop"]
    check("WSL, interop off: the interop step FAILs with the exact setting and the verdict is the built-in browser", steps_of(r)["WSL interop (Linux can start Windows programs)"]["status"] == "FAIL" and "enabled=false" in steps_of(r)["WSL interop (Linux can start Windows programs)"]["detail"] and "built-in browser" in r["verdict"] and not r["ok"], pc.format_report(r))
    np.reset()
    reps["wsl_nops"] = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=none_which, popen=popen_saying(good_dialog, 0), run=run_for(), read=lambda p: wsl_files.get(p), exists=lambda p: False, listdir=lambda d: [])
    r = reps["wsl_nops"]
    check("WSL, no powershell.exe: the step FAILs and lists the places it tried", steps_of(r)["powershell.exe is found"]["status"] == "FAIL" and "/mnt/c/Windows" in steps_of(r)["powershell.exe is found"]["detail"] and not r["ok"], pc.format_report(r))
    np.reset()
    reps["wsl_clm"] = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(hello=ps_ok.replace("FullLanguage", "ConstrainedLanguage")),
                                    read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    r = reps["wsl_clm"]
    check("WSL, locked-down PowerShell (ConstrainedLanguage): FAIL with the language mode, and Browse uses the built-in browser", steps_of(r)["PowerShell is not locked down"]["status"] == "FAIL" and "ConstrainedLanguage" in steps_of(r)["PowerShell is not locked down"]["detail"] and not r["ok"], pc.format_report(r))
    np.reset()
    reps["wsl_nohello"] = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(hello=""),
                                        read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    check("WSL, PowerShell found but cannot be started: the hello step FAILs with PowerShell's own error", steps_of(reps["wsl_nohello"])["A minimal PowerShell script runs"]["status"] == "FAIL" and "not recognized" in steps_of(reps["wsl_nohello"])["A minimal PowerShell script runs"]["detail"], pc.format_report(reps["wsl_nohello"]))
    np.reset()
    r = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(compile_out=""), read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    check("WSL, Add-Type blocked: the compile step FAILs but the older windows are tried and Browse still has a native window", steps_of(r)["PowerShell can compile the Explorer-style window (Add-Type)"]["status"] == "FAIL" and "older Windows folder window" in steps_of(r)["PowerShell can compile the Explorer-style window (Add-Type)"]["detail"], pc.format_report(r))
    np.reset()
    r = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(["PB_PID:1", "PB_ENV:" + b64("x"), "PB_ERROR:" + b64("no Windows folder window could be opened here")], 6), run=run_for(), read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    check("WSL, the window never opens: 'The folder window opens' FAILs with the script's error", steps_of(r)["The folder window opens"]["status"] == "FAIL" and "no Windows folder window" in steps_of(r)["The folder window opens"]["detail"] and not r["ok"], pc.format_report(r))

    np.reset()
    mi = ("700 600 0:55 / / rw - overlay overlay rw\n"
          "701 700 0:56 / /proc rw - proc proc rw\n"
          "702 700 8:1 /home/me/data /mnt/data rw,relatime - ext4 /dev/sda1 rw\n"
          "703 700 8:1 /var/lib/docker/containers/abc/hosts /etc/hosts rw - ext4 /dev/sda1 rw\n")
    r = pc.run_checks(False, 2, platform="linux", wsl=False, env={"PLASBENCH_IN_DOCKER": "1"}, which=none_which, mounts_text=mi, read=lambda p: None, exists=lambda p: False)
    check("Docker: no native window (n/a), the mounts are listed, and the verdict says the built-in browser starts at them", r["environment"] == "docker" and r["ok"] and "/mnt/data" in steps_of(r)["Folders mounted into this container"]["detail"] and "built-in browser" in r["verdict"] and r["native"] == "", pc.format_report(r))
    r = pc.run_checks(False, 2, platform="linux", wsl=False, env={"PLASBENCH_IN_DOCKER": "1"}, which=none_which, mounts_text="700 600 0:55 / / rw - overlay overlay rw\n", read=lambda p: None, exists=lambda p: False)
    check("Docker with nothing mounted: FAIL that says how to mount a folder", steps_of(r)["Folders mounted into this container"]["status"] == "FAIL" and "-v <host folder>" in steps_of(r)["Folders mounted into this container"]["detail"] and not r["ok"])
    r = pc.run_checks(False, 2, platform="linux", wsl=False, env={}, which=none_which, read=lambda p: None, exists=lambda p: False)
    check("Linux without a desktop: n/a for the window, the verdict names the reason, and it is not a failure", r["environment"] == "linux-headless" and r["ok"] and "no desktop session" in r["verdict"], pc.format_report(r))
    r = pc.run_checks(False, 2, platform="linux", wsl=False, env={"SSH_CONNECTION": "1 2 3 4", "DISPLAY": ":0"}, which=none_which, read=lambda p: None, exists=lambda p: False)
    check("SSH: n/a, explained (the window would open on the remote desktop)", r["environment"] == "ssh" and r["ok"] and "remote" in steps_of(r)["A desktop folder window is possible"]["detail"])

    def run_tool(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, b"3.44.0\n", b"")
    np.reset()
    r = pc.run_checks(False, 1, platform="linux", wsl=False, env={"DISPLAY": ":0"}, which=which_of({"zenity": "/usr/bin/zenity"}), popen=popen_saying([], 0, linger=30), run=run_tool, read=lambda p: None, exists=lambda p: False)
    check("Linux desktop with zenity: the program runs, its window stays up for the test, then it is closed: PASS", r["environment"] == "linux-desktop" and r["ok"] and r["native"] == "zenity", pc.format_report(r))
    np.reset()
    r = pc.run_checks(False, 1, platform="linux", wsl=False, env={"DISPLAY": ":0"}, which=which_of({"zenity": "/usr/bin/zenity"}), popen=popen_saying([], 1, b"Gtk-WARNING: cannot open display: :0\n"), run=run_tool, read=lambda p: None, exists=lambda p: False)
    check("Linux desktop, zenity cannot open the display: FAIL with zenity's own message", steps_of(r)["The folder window opens"]["status"] == "FAIL" and "cannot open display" in steps_of(r)["The folder window opens"]["detail"] and not r["ok"], pc.format_report(r))
    np.reset()
    r = pc.run_checks(False, 2, platform="linux", wsl=False, env={"DISPLAY": ":0"}, which=none_which, read=lambda p: None, exists=lambda p: False)
    check("Linux desktop with no zenity/kdialog/yad: FAIL naming them", steps_of(r)["A folder window program is found"]["status"] == "FAIL" and "zenity" in steps_of(r)["A folder window program is found"]["detail"] and not r["ok"])
    np.reset()
    r = pc.run_checks(False, 1, platform="mac", wsl=False, env={}, which=which_of({"osascript": "/usr/bin/osascript"}), popen=popen_saying([], 0, linger=30), run=run_tool, read=lambda p: None, exists=lambda p: False)
    check("macOS: osascript runs and its window stays up for the test: PASS", r["environment"] == "mac" and r["ok"] and r["native"] == "mac", pc.format_report(r))
    np.reset()
    r = pc.run_checks(False, 2, platform="windows", wsl=False, env={}, which=which_of({"powershell.exe": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"}), popen=popen_saying(good_dialog, 0), run=run_for(), read=lambda p: None, exists=ex_true)
    check("Windows: powershell, hello, compile, window PASS; the conversion step is n/a", r["environment"] == "windows" and r["ok"] and steps_of(r)["Windows path -> Linux path conversion"]["status"] == "n/a", pc.format_report(r))
    np.reset()
    real_mounted = chooser.drive_mounted
    chooser.drive_mounted = lambda letter, text=None, mnt_dir="/mnt": True       # the test machine has no /mnt/d
    interactive_out = ["PB_PID:1", "PB_ENV:" + b64("x"), "PB_STRATEGY:" + b64("ifiledialog"), "PB_OPENED:" + b64("ifiledialog"), "PB_FOCUS:" + b64("foreground"), "PB_RESULT:" + b64("D:\\data\\x")]
    r = pc.run_checks(True, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(interactive_out, 0), run=run_for(), read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    ch = steps_of(r)["The chosen folder is returned"]
    check("--interactive: the chosen folder is reported as the Windows path and the Linux path PlasBench will use", ch["status"] == "PASS" and "D:\\data\\x" in ch["detail"] and "/mnt/d/x" not in ch["detail"] and "/mnt/d/data/x" in ch["detail"], ch)
    chooser.drive_mounted = real_mounted
    text = pc.format_report(reps["wsl_nointerop"])
    check("the printed report has one [PASS]/[FAIL] line per step and a Result line", re.search(r"^\[FAIL\] WSL interop", text, re.M) and re.search(r"^Result: ", text, re.M), text)
    check("the JSON form is the same report", json.loads(json.dumps(reps["wsl_ok"]))["environment"] == "wsl")
    np.reset()
    r = pc.run_checks(False, 2, platform="wsl", wsl=True, env={}, which=which_of({"powershell.exe": "/mnt/c/p.exe"}), popen=popen_saying(good_dialog[:4] + ["PB_FOCUS:" + b64("flashed"), "PB_RESULT:" + b64("dry-run")], 0), run=run_for(), read=lambda p: wsl_files.get(p), exists=ex_true, listdir=lambda d: [])
    check("focus 'flashed' is a FAIL step that says the taskbar button flashes", steps_of(r)["The window comes to the front"]["status"] == "FAIL" and "flash" in steps_of(r)["The window comes to the front"]["detail"])
    np._kill = REAL_KILL

    print("Docker detection")
    cg1 = "12:cpu:/docker/3f9a0b\n11:memory:/docker/3f9a0b\n"
    cg2 = "0::/\n"
    mi2 = "1 2 0:3 /docker/containers/abc/resolv.conf /etc/resolv.conf rw - ext4 /dev/sda1 rw\n"
    check("PLASBENCH_IN_DOCKER=1", dh.in_docker({"PLASBENCH_IN_DOCKER": "1"}, lambda p: False, lambda p: None))
    check("PLASBENCH_IN_DOCKER=0 wins over the files", not dh.in_docker({"PLASBENCH_IN_DOCKER": "0"}, lambda p: True, lambda p: cg1))
    check("/.dockerenv", dh.in_docker({}, lambda p: p == "/.dockerenv", lambda p: None))
    check("/run/.containerenv (podman)", dh.in_docker({}, lambda p: p == "/run/.containerenv", lambda p: None))
    check("cgroup v1 (/docker/<id> in /proc/1/cgroup)", dh.in_docker({}, lambda p: False, lambda p: cg1 if p == "/proc/1/cgroup" else None))
    check("cgroup v1 kubepods", dh.in_docker({}, lambda p: False, lambda p: "1:name=systemd:/kubepods/burstable/pod1/abc\n" if p == "/proc/1/cgroup" else None))
    check("cgroup v2 ('0::/'): Docker's per-container mounts in mountinfo", dh.in_docker({}, lambda p: False, lambda p: {"/proc/1/cgroup": cg2, "/proc/self/mountinfo": mi2}.get(p)))
    check("a plain host is not Docker", not dh.in_docker({}, lambda p: False, lambda p: {"/proc/1/cgroup": "0::/init.scope\n", "/proc/self/mountinfo": "1 2 0:3 / / rw - ext4 /dev/sda1 rw\n"}.get(p)))
    check("nothing readable is not Docker", not dh.in_docker({}, lambda p: False, lambda p: None))
    caps = np.capabilities("linux", {"PLASBENCH_IN_DOCKER": "1", "DISPLAY": ":0"}, which_of({"zenity": "/z"}), False, exists=lambda p: False, read=lambda p: None)
    check("capabilities in Docker: unavailable (even with a DISPLAY), docker True, the stated reason", not caps["available"] and caps["docker"] and "no desktop to open a folder window in" in caps["reason"] and "mounted into the container" in caps["reason"], caps)
    caps = np.capabilities("wsl", {"PLASBENCH_IN_DOCKER": "1"}, which_of({"powershell.exe": "/p"}), True, exists=ex_true, read=lambda p: None)
    check("Docker is detected before WSL (Docker Desktop's WSL backend)", caps["docker"] and not caps["available"])

    print("/proc/self/mountinfo")
    sample = (r"""700 600 0:55 / / rw,relatime - overlay overlay rw,lowerdir=/x
701 700 0:56 / /proc rw,nosuid - proc proc rw
702 700 0:57 / /dev rw,nosuid - tmpfs tmpfs rw
703 700 8:1 /home/me/data /mnt/data rw,relatime - ext4 /dev/sda1 rw
704 700 8:1 /home/me/My\040Data /mnt/my\040data ro,relatime - ext4 /dev/sda1 rw
705 700 0:60 /run/desktop/mnt/host/d/Projects/\344\270\255 /mnt/proj rw - virtiofs virtiofs rw
706 700 8:1 /var/lib/docker/volumes/plasdb/_data /opt/db rw - ext4 /dev/sda1 rw
707 700 8:1 /var/lib/docker/containers/abc/hosts /etc/hosts rw - ext4 /dev/sda1 rw
708 700 0:61 / /tmp rw - tmpfs tmpfs rw
709 700 0:62 /host_mnt/c/Users/me /mnt/winhome rw - fuse.grpcfuse grpcfuse rw
""")
    rows = dh.parse_mountinfo(sample)
    check("parse: every line becomes a row with mount point, root, fstype, source", len(rows) == 10 and rows[3]["mount_point"] == "/mnt/data" and rows[3]["root"] == "/home/me/data" and rows[3]["fstype"] == "ext4" and rows[3]["source"] == "/dev/sda1")
    check("parse: octal escapes (\\040) are spaces and the read-only flag is read", rows[4]["mount_point"] == "/mnt/my data" and rows[4]["root"] == "/home/me/My Data" and rows[4]["readonly"] and not rows[3]["readonly"], rows[4])
    um = dh.user_mounts(sample)
    byp = {m["container_path"]: m for m in um}
    check("user mounts: system mounts (/, /proc, /dev, /etc/hosts, tmpfs) are left out", set(byp) == {"/mnt/data", "/mnt/my data", "/mnt/proj", "/opt/db", "/mnt/winhome"}, sorted(byp))
    check("a Linux bind mount shows the host path", byp["/mnt/data"]["kind"] == "bind" and byp["/mnt/data"]["host_path"] == "/home/me/data")
    check("a volume shows its name and no host path", byp["/opt/db"]["kind"] == "volume" and byp["/opt/db"]["name"] == "plasdb" and byp["/opt/db"]["host_path"] == "")
    check("Docker Desktop on Windows: /run/desktop/mnt/host/d/... is D:\\...", byp["/mnt/proj"]["host_path"].startswith("D:\\Projects\\") and byp["/mnt/proj"]["host_path"].endswith("\u4e2d"), byp["/mnt/proj"])
    check("Docker Desktop /host_mnt/c/... is C:\\...", byp["/mnt/winhome"]["host_path"] == "C:\\Users\\me")
    check("read-only is kept", byp["/mnt/my data"]["readonly"])
    check("the roots the browser starts from carry a plain label", any("volume plasdb" in r["label"] for r in dh.mount_roots(um)) and any("from /home/me/data" in r["label"] for r in dh.mount_roots(um)))
    check("an empty or garbage mountinfo gives no mounts", dh.user_mounts("") == [] and dh.user_mounts("garbage\n\n1 2 3") == [])

    print("the docker run command")
    def cmd(path, shell="posix", **kw):
        return dh.run_command([dict({"path": path}, **kw)], shell)
    r = cmd("D:\\data")
    check("posix (WSL): D:\\data -> /mnt/d/data mounted at /mnt/data", r["ok"] and r["mounts"][0] == {"host": "/mnt/d/data", "container": "/mnt/data", "readonly": False} and "-v /mnt/d/data:/mnt/data" in r["command"], r)
    r = cmd("D:\\data", "powershell")
    check("PowerShell (Docker Desktop): D:\\data stays D:\\data", r["ok"] and r["mounts"][0]["host"] == "D:\\data" and '-v "D:\\data:/mnt/data"' in r["command"] and "`" in r["command"], r)
    r = cmd("/home/me/data")
    check("Linux path on posix is kept; the command ends with the image and the command", r["ok"] and r["command"].startswith("docker run --rm -it") and r["command"].rstrip().endswith("plasbench:local bash"), r)
    r = cmd("D:\\My Data\\run 1")
    check("spaces: the argument is quoted for the shell (posix)", r["ok"] and "'/mnt/d/My Data/run 1:/mnt/my_data_run_1'" in r["command"] or "'/mnt/d/My Data/run 1:/mnt/run_1'" in r["command"], r["command"])
    r = cmd("D:\\My Data\\run 1", "powershell")
    check("spaces: quoted for PowerShell", r["ok"] and '"D:\\My Data\\run 1:/mnt/run_1"' in r["command"], r["command"])
    r = cmd("/home/me/d\u00e9j\u00e0 \u4e2d\u6587")
    check("unicode in the host path is kept; the container name is safe ASCII", r["ok"] and "d\u00e9j\u00e0 \u4e2d\u6587" in r["command"] and re.fullmatch(r"/mnt/[A-Za-z0-9._-]+", r["mounts"][0]["container"]), r)
    r = cmd("\\\\fileserver\\share\\data")
    check("UNC share is refused with an explanation and no command", not r["ok"] and r["command"] == "" and "network share" in r["errors"][0] and "drive letter" in r["errors"][0], r)
    r = cmd("\\\\wsl.localhost\\Ubuntu-24.04\\home\\me\\data")
    check("a \\\\wsl.localhost path is the Linux path on posix", r["ok"] and r["mounts"][0]["host"] == "/home/me/data", r)
    r = cmd("\\\\wsl.localhost\\Ubuntu\\home\\me", "powershell")
    check("a \\\\wsl.localhost path is refused for PowerShell with the reason", not r["ok"] and "WSL" in r["errors"][0])
    r = cmd("/home/me/data", "powershell")
    check("a Linux path for PowerShell is refused (not a Windows folder)", not r["ok"] and "Linux path" in r["errors"][0])
    r = cmd("/mnt/d/data", "powershell")
    check("/mnt/d/data for PowerShell becomes D:\\data", r["ok"] and r["mounts"][0]["host"] == "D:\\data", r)
    r = cmd("data/relative")
    check("a relative path is refused", not r["ok"] and "full path" in r["errors"][0])
    r = cmd("")
    check("an empty path is refused", not r["ok"])
    r = cmd("/srv/a:b")
    check("a colon in a host path is refused (docker -v cannot take it)", not r["ok"] and "colon" in r["errors"][0])
    r = dh.run_command([{"path": "D:\\data"}, {"path": "E:\\data"}, {"path": "/x/data", "readonly": True}], "posix")
    names = [m["container"] for m in r["mounts"]]
    check("two folders called 'data' get distinct container names; read-only adds :ro", len(set(names)) == 3 and ":ro" in r["command"] and r["command"].count("-v ") == 3, names)
    check("the compose snippet lists the same volumes", r["compose"].startswith("services:") and "/mnt/d/data:/mnt/data" in r["compose"], r["compose"])
    r = dh.run_command([{"path": "D:\\x"}], "posix", existing=[{"kind": "bind", "container_path": "/mnt/data", "host_path": "/home/me/data", "readonly": False}, {"kind": "volume", "name": "plasdb", "container_path": "/opt/db", "host_path": "", "readonly": False}])
    check("mounts the container already has are kept in the command", "/home/me/data:/mnt/data" in r["command"] and "plasdb:/opt/db" in r["command"], r["command"])
    src = (ROOT / "plasbench" / "docker_helper.py").read_text(encoding="utf-8")
    check("docker_helper never starts a process (no subprocess, os.system or Popen)", not re.search(r"import subprocess|os\.system|Popen|os\.exec", src))
    sw = dh.switch_plan("/home/me/PlasBench", "/mnt/d/data", "/mnt/d/studies", "posix")
    check("switch plan (posix): cd into the project, PLASBENCH_WORKSPACE and PLASBENCH_DATA_DIR, then scripts/docker_run.sh", sw["ok"] and "PLASBENCH_WORKSPACE=/mnt/d/studies" in sw["command"] and "PLASBENCH_DATA_DIR=/mnt/d/data" in sw["command"] and "scripts/docker_run.sh plasbench" in sw["command"] and sw["command"].startswith("cd /home/me/PlasBench && "), sw)
    check("  with the steps and the 'tools run inside the image' note", any("image" in x for x in sw["steps"]) and any("not start containers" in x or "does not start" in x for x in sw["notes"]), sw)
    sw = dh.switch_plan("C:\\Users\\me\\PlasBench", "D:\\My Data", "", "powershell")
    check("switch plan (PowerShell): a docker run with the mounts, spaces quoted", sw["ok"] and 'docker run --rm' in sw["command"] and '-v "D:\\My Data:/work/data"' in sw["command"] and '"C:\\Users\\me\\PlasBench\\studies:/work/studies"' in sw["command"], sw)
    sw = dh.switch_plan("C:\\PlasBench", "\\\\nas\\share\\data", "", "powershell")
    check("switch plan with a UNC data folder is refused", not sw["ok"] and sw["command"] == "")
    shtext = (ROOT / "scripts" / "docker_run.sh").read_text(encoding="utf-8")
    check("scripts/docker_run.sh takes PLASBENCH_DATA_DIR (default: <root>/data) and creates it", 'HOST_DATA="${PLASBENCH_DATA_DIR:-$HOST_ROOT/data}"' in shtext and '-v "$HOST_DATA:/work/data"' in shtext and 'mkdir -p "$HOST_WORKSPACE" "$HOST_DATA"' in shtext)
    check("  the script is LF (a CR would break bash)", b"\r" not in (ROOT / "scripts" / "docker_run.sh").read_bytes())

    print("'run in Docker instead' is offered only when it can work")
    check("Docker not installed: not offered, with the reason", dh.switch_offer({"installed": False, "running": False}, True) == {"offered": False, "reason": "Docker is not installed on this computer"})
    o = dh.switch_offer({"installed": True, "running": False}, True)
    check("Docker installed but not running: not offered, says to start it", not o["offered"] and "not running" in o["reason"], o)
    o = dh.switch_offer({"installed": True, "running": True}, False)
    check("no scripts/docker_run.sh: not offered", not o["offered"] and "docker_run.sh" in o["reason"], o)
    o = dh.switch_offer({"installed": True, "running": True, "image": False}, True)
    check("Docker answering and the script present: offered", o["offered"] and o["image_ready"] is False, o)
    from plasbench import platform_info
    real_docker, real_in = platform_info.docker, dh.in_docker
    try:
        loadcache.clear()
        platform_info.docker = lambda: {"installed": False, "running": False, "image": False}
        loadcache.reset_all()
        o = webui.docker_offer_state(ROOT)
        deadline = time.time() + 5
        while o.get("pending") and time.time() < deadline:
            time.sleep(0.1)
            o = webui.docker_offer_state(ROOT)
        check("the route: docker absent -> not offered", o["offered"] is False and "not installed" in o["reason"], o)
        loadcache.reset_all()
        platform_info.docker = lambda: time.sleep(1.0) or {"installed": True, "running": True, "image": True}
        t0 = time.time()
        o = webui.docker_offer_state(ROOT)
        check("the docker probe never blocks the call (answers 'checking' at once)", o["pending"] is True and time.time() - t0 < 0.5, (o, time.time() - t0))
        deadline = time.time() + 6
        while o.get("pending") and time.time() < deadline:
            time.sleep(0.1)
            o = webui.docker_offer_state(ROOT)
        check("  and the answer arrives from the background probe: offered", o["offered"] is True and o["docker"]["running"], o)
        dh.in_docker = lambda *a, **k: True
        o = webui.docker_offer_state(ROOT)
        check("inside Docker the offer is never made (already there)", o["offered"] is False and o["in_docker"], o)
    finally:
        platform_info.docker, dh.in_docker = real_docker, real_in
        loadcache.reset_all()
    wsrc = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("the docker probe is never on the page-load path: only /api/docker/offer reads it, through loadcache.swr(block=False)", wsrc.count("docker_offer_state(") == 2 and "block=False" in wsrc[wsrc.index("def docker_offer_state"):wsrc.index("# ---- end folder window extras")])

    print("the built-in browser in Docker")
    real_in, real_um = dh.in_docker, dh.user_mounts
    try:
        loadcache.reset_all()
        dh.in_docker = lambda *a, **k: True
        dh.user_mounts = lambda *a, **k: [{"container_path": "/mnt/data", "kind": "bind", "name": "", "host_path": "D:\\data", "readonly": False, "fstype": "virtiofs"}]
        root = webui.browse("", True, None)
        check("the root view in Docker lists the mounts (not the host's drives) and says folders outside them are not visible", root["docker"] is True and [e["path"] for e in root["pc"]] == ["/mnt/data"] and "not visible" in root["help"] and "from D:\\data" in root["pc"][0]["name"], root)
        extras = webui.native_picker_extras({"docker": True, "platform": "linux"})
        check("the capabilities carry the mounts and the banner in Docker", extras["mounts"][0]["container_path"] == "/mnt/data" and "outside these mounts" in extras["banner"], extras)
        dh.user_mounts = lambda *a, **k: []
        check("no mounts: the banner says no folder is visible", "No folder is mounted" in webui.native_picker_extras({"docker": True})["banner"])
    finally:
        dh.in_docker, dh.user_mounts = real_in, real_um
        loadcache.reset_all()

    print("the page")
    check("no browser dialogs in the folder code (alert, confirm, prompt)", not re.search(r"(?<![\w.])(alert|confirm|prompt)\(", html[html.index("native-picker helpers (pure)"):html.index("/* ---- the built-in browser")]))
    check("a Why? fold (details/summary) and the exact diagnostics in the failure dialog", "<summary>Why?</summary>" in html and "function npDiag" in html and 'id="fs_why"' in html)
    check("Copy diagnostics button in the built-in browser and in the failure dialog (copy:)", 'id="fs_diag"' in html and "copy: diag" in html and 'copyText(npDiag(), "Diagnostics copied")' in html)
    check("a Test the folder window button in Settings that calls the job-less route", 'id="np_test"' in html and "Test the folder window" in html and 'api("native-picker/selftest", {})' in html)
    check("Browse in Docker goes straight to the built-in browser with the banner", "if (caps.docker) return pickInline(" in html and "caps.banner" in html)
    check("an unavailable window shows its reason with Why? (not a silent fallback)", "{why: !caps.available}" in html and "caps.reason" in html)
    check("the capabilities are looked at again when the window was unavailable (15 s), so a fix needs no reload", "Date.now() - (NP.capsAt || 0) > 15000" in html)
    check("Bring it to front, and the message that says where the window is", 'id="np_front"' in html and "click the PowerShell or Explorer icon in the taskbar" in html)
    check("the Docker dialog: Add another folder (in Docker) and Run in Docker instead (elsewhere), with Copy and no run button", all(k in html for k in ('id="dkdlg"', 'id="dk_copy"', 'id="fs_adddk"', 'id="fs_docker"', 'id="np_dk_switch"', 'id="np_dk_add"')) and 'id="dk_run"' not in html)
    check("'Run in Docker instead' stays hidden until docker/offer says offered, and the probe starts only from Settings or a chooser", 'api("docker/offer")' in html and '$("#fs_docker").hidden = true' in html and "npLoadOffer(true);" in html)
    check("the Docker dialog says the command is not run for the user", "never run for you" in html and "does not start Docker for you" in html)
    from plasbench import ui_help
    for k in ("why", "diagnostics", "test", "docker_add", "docker_switch", "in_docker"):
        check(f"ui_help has a tooltip for '{k}'", ui_help.NATIVE_PICKER.get(k, {}).get("summary"))
    check("the native picker help reaches the page through the schema", "native_picker_help" in (ROOT / "plasbench" / "ui_schema.py").read_text(encoding="utf-8"))
    node = shutil.which("node")
    if node:
        js = max(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S), key=len)
        (tmp / "page.js").write_text(js, encoding="utf-8")
        done = subprocess.run([node, "--check", str(tmp / "page.js")], capture_output=True, text=True)
        check("the page script has no syntax error", done.returncode == 0, done.stderr[:300])
    else:
        print("  n/a   node not found: page syntax not checked")

    print("the routes over HTTP")
    os.environ["PLASBENCH_NATIVE_PICKER_POWERSHELL"] = "/nonexistent/powershell.exe"
    loadcache.clear()
    from http.server import ThreadingHTTPServer
    import urllib.error
    import urllib.request
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
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
    check("docker/plan, docker/offer and native-picker/selftest need the token", all(call(p, b, tok=False)[0] == 403 for p, b in (("/api/docker/offer", None), ("/api/docker/plan", {}), ("/api/native-picker/selftest", {}))))
    code, plan = call("/api/docker/plan", {"folders": [{"path": "D:\\data"}], "shell": "posix"})
    check("docker/plan returns the command for a folder (and runs nothing)", code == 200 and plan["ok"] and "/mnt/d/data" in plan["command"], plan)
    code, plan = call("/api/docker/plan", {"folders": [{"path": "\\\\srv\\share"}], "shell": "posix"})
    check("docker/plan refuses a UNC share with the reason", code == 200 and not plan["ok"] and "network share" in plan["errors"][0], plan)
    code, plan = call("/api/docker/plan", {"mode": "switch", "data_dir": "/mnt/d/data", "workspace": "/mnt/d/studies", "shell": "posix"})
    check("docker/plan mode=switch returns the docker_run.sh command", code == 200 and plan["ok"] and "scripts/docker_run.sh" in plan["command"], plan)
    code, off = call("/api/docker/offer")
    check("docker/offer answers at once (pending or a verdict), never blocks", code == 200 and ("pending" in off) and "offered" in off, off)
    code, caps = call("/api/native-picker/capabilities")
    check("capabilities carry the diagnostics (what was tried) and the reason, with no path leak", code == 200 and caps["available"] is False and caps["reason"] and "diagnostics" in caps and caps.get("exe") is None, caps)
    code, rep = call("/api/native-picker/selftest", {})
    check("selftest: a job-less, bounded call that returns the report with its text", code == 200 and rep.get("steps") and "text" in rep and "verdict" in rep, rep)
    server.shutdown()

    print("real Windows: the real PowerShell route, end to end")
    if not (IS_NT and shutil.which("powershell.exe")):
        print("  n/a   not a Windows computer with powershell.exe: the real-window checks run only there")
    else:
        os.environ.pop("PLASBENCH_NATIVE_PICKER_POWERSHELL", None)
        np.reset()
        for strategy, want in (("", "ifiledialog"), ("winforms", "winforms"), ("shell", "shell")):
            for kind in ("folder", "file"):
                np.reset()
                res = np.pick_folder("PlasBench t\u00eest \u4e2d", None, kind, None, 60, platform="windows", env=dict(os.environ), dry=True, strategy=strategy)
                v = np.last_view()
                if strategy == "shell" and kind == "file":
                    check("real: Shell.Application has no file window, so the chain ends in the error that offers the built-in browser", not res["ok"] and "built-in browser" in res["error"], res)
                else:
                    check(f"real: dry-run, strategy '{strategy or 'best'}', {kind}: the window object is created ({want})", res["ok"] and v["strategy"] == want, (res, v))
        np.reset()
        with tempfile.TemporaryDirectory(prefix="pb sp\u00e4ce \u4e2d ") as spaced:
            old = {k: os.environ.get(k) for k in ("TEMP", "TMP")}
            os.environ["TEMP"] = os.environ["TMP"] = spaced
            try:
                res = np.pick_folder("t\u00e9st", None, "folder", None, 60, platform="windows", env=dict(os.environ), dry=True, limit=10)
                v = np.last_view()
                check("real: the temp .ps1 route works from a folder with spaces and unicode, and the file is removed afterwards", res["ok"] and v["route"] == "file" and not list(Path(spaced).glob("plasbench-pick-*.ps1")), (res, v))
            finally:
                for k, val in old.items():
                    if val is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = val
        np.reset()
        job = np.Job("folder", "t")
        sc = np.windows_script("folder", "t\u00e9", "", [], 30, dry=True)
        stdin_route = [r for r in np.windows_routes("powershell.exe", sc, 10) if r[0] == "stdin"][0]
        rc, out, err, reason = np._run_argv(stdin_route[1], 60, job, "windows", stdin_text=np.gzip_bootstrap(sc) + "\n")
        check("real: the stdin route runs the script (a one-line unpacker on standard input)", rc == 0 and job.strategy == "ifiledialog" and "PB_RESULT:" in out, (rc, out[:200], err[:200]))
        np.reset()
        sc = "$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage'\n" + np.windows_script("folder", "t", "", [], 30, dry=True)
        done = subprocess.run(np.encoded_argv("powershell.exe", sc), capture_output=True, timeout=90)
        check("real: in Constrained Language Mode the script fails with a message the code recognises as a locked-down PowerShell", done.returncode != 0 and b"language mode" in done.stderr.lower(), (done.returncode, done.stderr[:200]))
        np.reset()
        title = "PlasBench UIA probe \u00fc\u4e2d " + str(os.getpid())
        holder = {}
        th = threading.Thread(target=lambda: holder.update(r=np.pick_folder(title, None, "folder", None, 90, platform="windows", env=dict(os.environ))))
        th.start()
        uia = r'''
Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes
$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s'))
$deadline=(Get-Date).AddSeconds(60); $w=$null
while((Get-Date) -lt $deadline){
  $c=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$t)
  $w=[System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$c)
  if($w){break}; Start-Sleep -Milliseconds 300 }
if(-not $w){ 'NOTFOUND'; exit 2 }
'FOUND offscreen=' + $w.Current.IsOffscreen + ' enabled=' + $w.Current.IsEnabled
$p=$w.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)
'visual=' + $p.Current.WindowVisualState
$p.Close(); 'CLOSED'
''' % b64(title)
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", uia], capture_output=True, timeout=120)
        said = done.stdout.decode("utf-8", "replace")
        th.join(60)
        v = np.last_view()
        res = holder.get("r", {})
        check("real: UI Automation finds a top-level window with the requested title (unicode), on screen and enabled", "FOUND offscreen=False enabled=True" in said, said + done.stderr.decode("utf-8", "replace")[:200])
        check("real: the script said PB_OPENED and brought the window to the foreground", v["opened"] is True and v["focus"] == "foreground" and v["strategy"] == "ifiledialog", v)
        check("real: closing it with WM_CLOSE (WindowPattern.Close) is reported as cancelled, not an error", "CLOSED" in said and res.get("cancelled") is True and not res.get("error") and v["state"] == "cancelled", (said, res, v))
        np.reset()
        res = pc.run_checks(False, 2)
        check("real: `plasbench picker-check` passes on this computer (window opens, comes forward, closes itself)", res["native"] == "ifiledialog" and res["ok"], pc.format_report(res))
    print("  NOTE: no person clicked a folder in the real dialog; the WSL parts (interop, wslpath, \\\\wsl.localhost paths) are only simulated here")
    np.reset()
    print("ALL PASS" if not FAILED else "FAILED: " + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
