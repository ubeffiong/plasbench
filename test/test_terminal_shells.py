#!/usr/bin/env python3
"""The Terminal tab's shell list and how each shell runs a command (plasbench/terminal.py).

Table-driven over probes for every kind of host (Windows, WSL with interop on / off / appendWindowsPath=false, Linux with and without pwsh, Mac), then the
argument lists, quoting of hostile text, cwd translation, the plasbench shims, kill path, output decoding, prompts, the terminal/shell route and the page.
WSL itself is only simulated here (fake probes, fake wslpath, fake taskkill); the real Windows host paths are exercised by test_desktop_window.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import native_picker, terminal as T, ui_help  # noqa: E402

OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


def probe(host, **kw):
    p = {"host": host, "distro": "", "distros": [], "login": None, "login_name": "", "pwsh": None, "git_bash": None, "cmd": None, "interop": None, "win": None, "why": {}}
    p.update(kw)
    return p


WIN_OK = {"ps": "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "ps_kind": "powershell", "cmd": "/mnt/c/Windows/System32/cmd.exe",
          "git": "/mnt/c/Program Files/Git/bin/bash.exe", "why": {}}
WSL = dict(distro="Ubuntu-24.04", login="/bin/bash", login_name="Bash", interop={"enabled": True, "detail": "x"})
DISTROS = [{"name": "Ubuntu", "default": True, "state": "Running"}, {"name": "Debian", "default": False, "state": "Stopped"}]
off = "WSL interop is off, so Linux programs cannot start Windows programs: x"
CASES = [
    ("windows full", probe("windows", distros=DISTROS, git_bash="C:\\Git\\bin\\bash.exe", pwsh="C:\\pwsh.exe", cmd="C:\\Windows\\System32\\cmd.exe"),
     ["wsl:Ubuntu", "wsl:Debian", "posix", "powershell", "cmd"], "wsl:Ubuntu", {"posix": "Git Bash", "cmd": "Command Prompt (cmd)", "powershell": "PowerShell", "wsl:Debian": "Debian (WSL)"}),
    ("windows no wsl", probe("windows", git_bash="b", pwsh="p", cmd="c"), ["posix", "powershell", "cmd"], "posix", {}),
    ("wsl interop on, git present", probe("wsl", win=WIN_OK, **WSL), ["posix", "winps", "cmd", "wingit"], "posix",
     {"posix": "Ubuntu-24.04 (Bash)", "winps": "Windows PowerShell", "cmd": "Windows Command Prompt (cmd)", "wingit": "Git Bash (Windows)"}),
    ("wsl interop on, git absent", probe("wsl", win=dict(WIN_OK, git=None), **WSL), ["posix", "winps", "cmd"], "posix", {}),
    ("wsl with linux pwsh", probe("wsl", win=WIN_OK, pwsh="/usr/bin/pwsh", **WSL), ["posix", "powershell", "winps", "cmd", "wingit"], "posix", {"powershell": "PowerShell (Linux)"}),
    ("wsl interop off", probe("wsl", win={"ps": None, "ps_kind": "", "cmd": None, "git": None, "why": {k: off for k in ("winps", "cmd", "wingit")}}, why={k: off for k in ("winps", "cmd", "wingit")},
                              **dict(WSL, interop={"enabled": False, "detail": "x"})), ["posix"], "posix", {}),
    ("linux no pwsh", probe("linux", login="/bin/bash", login_name="Bash"), ["posix"], "posix", {"posix": "Bash"}),
    ("linux pwsh", probe("linux", login="/usr/bin/zsh", login_name="Zsh", pwsh="/usr/bin/pwsh"), ["posix", "powershell"], "posix", {"posix": "Zsh", "powershell": "PowerShell"}),
    ("mac zsh", probe("mac", login="/bin/zsh", login_name="Zsh"), ["posix"], "posix", {"posix": "Zsh"}),
]
print("shell lists")
for name, p, ids, default, labels in CASES:
    check(f"{name}: offered", list(T.available_shells(p)) == ids, list(T.available_shells(p)))
    check(f"{name}: default {default}", T.default_shell(p) == default, T.default_shell(p))
    check(f"{name}: labels", all(T.shell_label(k, p) == v for k, v in labels.items()), {k: T.shell_label(k, p) for k in labels})
un = T.unavailable_shells(CASES[5][1])
check("interop off: Windows shells listed as unavailable with the reason", set(un) == {"winps", "cmd", "wingit"} and "interop is off" in un["winps"]["why"], un)
check("a Linux host has nothing unavailable", T.unavailable_shells(CASES[6][1]) == {})
check("no shell at all: default is empty", T.default_shell(probe("linux")) == "")

print("probing a WSL host (fakes, no process started)")
files = {"/mnt/c/Windows/System32/cmd.exe", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "/mnt/c/Program Files/Git/usr/bin/bash.exe",
         "/mnt/c/Program Files/PowerShell/7/pwsh.exe"}
spawned = []


def fake_run(*a, **k):
    spawned.append(a)
    raise OSError("no process in this test")


def wsl_probe(files, conf="", interop="enabled\n", which=lambda n: None, listdir=lambda p: ["c"]):
    def read(path):
        if path == "/etc/wsl.conf":
            return conf or None
        return interop if path.endswith("WSLInterop") else None
    return T.probe_shells("wsl", {"WSL_DISTRO_NAME": "Ubuntu-24.04", "SHELL": "/bin/bash"}, which, lambda p: p in files, fake_run, read, listdir)


with mock.patch.object(T, "posix_argv", lambda: ["/bin/bash", "-lc"]), mock.patch.object(T, "powershell_argv", lambda: None):
    pr = wsl_probe(files)
    check("pwsh.exe is preferred when installed", pr["win"]["ps"].endswith("pwsh.exe") and pr["win"]["ps_kind"] == "pwsh", pr["win"])
    check("cmd.exe and Git Bash (usr/bin) found by absolute path", pr["win"]["cmd"].endswith("cmd.exe") and pr["win"]["git"].endswith("usr/bin/bash.exe"))
    pr = wsl_probe(files - {"/mnt/c/Program Files/PowerShell/7/pwsh.exe"})
    check("without pwsh.exe, powershell.exe", pr["win"]["ps"].endswith("powershell.exe"))
    pr = wsl_probe({"/mnt/c/Windows/System32/cmd.exe"}, which=lambda n: None)
    check("PowerShell missing: reason recorded, cmd kept", "winps" in pr["why"] and pr["win"]["cmd"] and "cmd" not in pr["why"], pr["why"])
    pr = wsl_probe(files, conf="[interop]\nenabled=false\n")
    check("wsl.conf interop=false: nothing looked for, every Windows entry has the reason", set(pr["why"]) == {"winps", "cmd", "wingit"} and not pr["win"]["ps"], pr["why"])
    pr = wsl_probe(files, conf="[interop]\nappendWindowsPath=false\n")
    check("appendWindowsPath=false still finds /mnt/c/Windows programs", bool(pr["win"]["cmd"]) and not pr["why"])
    pr = wsl_probe(set(), interop="disabled\n")
    check("interop disabled by the kernel: reasons", set(pr["why"]) == {"winps", "cmd", "wingit"})
    check("the probe uses the distribution name", pr["distro"] == "Ubuntu-24.04" and T.shell_label("posix", pr) == "Ubuntu-24.04 (Bash)")

print("cwd translation, quoting, shims")
wp = {"-w": {"/home/u": r"\\wsl.localhost\Ubuntu\home\u", "/mnt/c/Users/u": r"C:\Users\u", "/mnt/e/x": r"E:\x"}}


def fake_wslpath(argv, **k):
    return subprocess.CompletedProcess(argv, 0, stdout=wp["-w"][argv[2]] + "\n", stderr="")


tmp = Path(tempfile.mkdtemp(prefix="tshell"))
home, drive = tmp / "pb", tmp / "ws"
home.mkdir()
drive.mkdir()
term = T.Terminal(home, tmp / "h.jsonl", lambda: drive, run_fn=fake_wslpath)
term.host = "wsl"
for lin, win in wp["-w"].items():
    term.cwd = PurePosixPath(lin)
    check(f"wslpath {lin} -> {win}", term.win_cwd() == win, term.win_cwd())
check("msys path of a UNC folder", T.to_msys_path(r"\\wsl.localhost\Ubuntu\home\u") == "//wsl.localhost/Ubuntu/home/u")
check("msys path of a drive folder", T.to_msys_path(r"E:\x y") == "/e/x y")
hostile = ["a b", "it's", 'say "hi"', "$(rm -rf x)", "`id`", "a&b", "a;b", "ünï 日本", "C:\\x\\", "100%", "\u2019quote", "a^b", "!x!"]
check("PowerShell single quotes: ASCII and typographic ones are doubled", T._psq("it's \u2019x") == "'it''s \u2019\u2019x'" and T._psq("\u2018") == "'\u2018\u2018'")
check("PowerShell quote round trip for every hostile string",
      all(T._psq(h).startswith("'") and T._psq(h).endswith("'") and not re.search(r"(?<!['\u2018\u2019\u201a\u201b])['\u2018\u2019\u201a\u201b](?!['\u2018\u2019\u201a\u201b])", T._psq(h)[1:-1].replace("''", "").replace("\u2019\u2019", ""))
          for h in hostile))
check("bash quoting", T._q("it's") == "'it'\\''s'" and T._q("$(x)") == "'$(x)'")
check("cmd quoting: % doubled, trailing backslash doubled, plain words bare", T.cmd_quote("100%") == '"100%%"' and T.cmd_quote("C:\\x\\") == '"C:\\x\\\\"'
      and T.cmd_quote("-d") == "-d" and T.cmd_quote("a b&c^d") == '"a b&c^d"' and T.cmd_quote("ünï") == '"ünï"')
for bad in ('a"b', "a\nb"):
    try:
        T.cmd_quote(bad)
        check("cmd quoting refuses " + repr(bad), False)
    except T.TerminalError:
        check("cmd quoting refuses " + repr(bad), True)
shim = T.cmd_shim_text(T.wsl_call("Ubuntu", "/home/u/my env/bin/python", "/home/u/pb dir", "/usr/bin:/mnt/c/Program Files/x", cd="/home/u/pb dir"))
check("cmd shim: wsl.exe, bare options, quoted values, %* last", "wsl.exe -d Ubuntu --cd \"/home/u/pb dir\" -e /usr/bin/env \"PATH=/usr/bin:/mnt/c/Program Files/x\"" in shim
      and shim.splitlines()[2].endswith("--project-root \"/home/u/pb dir\" %*") and shim.rstrip().endswith("exit /b %ERRORLEVEL%"), shim)
check("shim without a usable PATH skips env", "/usr/bin/env" not in T.cmd_shim_text(T.wsl_call("U", "/p", "/r", 'bad"path')))
pl = T.cmd_payload("echo a\n\necho \"b & c\"", "C:\\T\\plasbench-term-1", r"\\wsl.localhost\U\home\u")
check("cmd payload: utf-8, shim first on PATH, pushd for UNC, lines joined, quotes kept",
      pl == 'chcp 65001>nul & set "PATH=C:\\T\\plasbench-term-1;%PATH%" & pushd "\\\\wsl.localhost\\U\\home\\u" || exit 1 & echo a & echo "b & c"', pl)
for bad in (("echo", 'C:\\a"b'), ("echo", "C:\\a%b")):
    try:
        T.cmd_payload(*bad)
        check("payload refuses a shim folder " + bad[1], False)
    except T.TerminalError:
        check("payload refuses a shim folder " + bad[1], True)
for h in hostile:
    ps = T.ps_encoded("pwsh.exe", "write-output " + h)
    check(f"encoded PowerShell command survives {h!a}", base64.b64decode(ps[-1]).decode("utf-16-le") == "write-output " + h and ps[-2] == "-EncodedCommand" and "-OutputFormat" in ps)
try:
    T.ps_encoded("p.exe", "x" * 20000)
    check("an over-long encoded command is refused", False)
except T.TerminalError:
    check("an over-long encoded command is refused", True)

print("_argv per shell")
os.environ["WSL_DISTRO_NAME"] = "Ubuntu-24.04"
winp = probe("wsl", win=WIN_OK, **WSL)
with mock.patch.object(T, "_probe", lambda probe=None: probe or winp), mock.patch.object(native_picker, "windows_temp", lambda *a, **k: ("C:\\Users\\u\\AppData\\Local\\Temp", str(tmp / "wintemp"))), \
        mock.patch.object(T, "git_path_dirs", lambda: []), mock.patch.object(os.path, "isdir", lambda p: p == "/mnt/c"):
    term.cwd = PurePosixPath("/mnt/c/Users/u")
    term.shell = "winps"
    a = term._argv('echo "x" ; $(date) `id` & é')
    script = base64.b64decode(a[-1]).decode("utf-16-le")
    check("winps: powershell.exe -EncodedCommand with the command last, pid line, wsl.exe shim function",
          a[0].endswith("powershell.exe") and "PB_PID:" in script and "function plasbench { & 'wsl.exe' '-d' 'Ubuntu-24.04' '-e' '/usr/bin/env' 'PATH=" in script
          and script.rstrip().endswith("exit $LASTEXITCODE}") and 'echo "x" ; $(date) `id` & é' in script, script[:400])
    check("winps in a drive folder has no --cd; in a UNC folder it has the Linux folder", "'--cd'" not in script)
    term.cwd = PurePosixPath("/home/u")
    script = base64.b64decode(term._argv("ls")[-1]).decode("utf-16-le")
    check("winps in an Ubuntu folder passes --cd", "'--cd' '/home/u'" in script)
    term.noticed.clear()
    pl = term._plan("ls")
    check("first notice about a UNC folder is given once", "wsl.localhost" in pl["notice"] and term._plan("ls")["notice"] == "")
    term.shell = "wingit"
    a = term._argv("echo $HOME; ls 'a b'")
    check("wingit: bash.exe -lc, pid line, MSYS path conversion off, cd to the UNC folder in msys form, command last",
          a[0].endswith("bash.exe") and a[1] == "-lc" and "winpid" in a[2] and "MSYS2_ARG_CONV_EXCL='*' 'wsl.exe' '-d' 'Ubuntu-24.04' '-e' '/usr/bin/env'" in a[2]
          and "cd '//wsl.localhost/Ubuntu/home/u' &&" in a[2] and a[2].endswith("echo $HOME; ls 'a b'"), a[2])
    term.shell = "cmd"
    term.cwd = PurePosixPath("/mnt/c/Users/u")
    pl = term._plan('echo "q" %USERNAME% & dir')
    check("cmd via WSL: PowerShell supervises cmd through ProcessStartInfo.Arguments (raw command line)", pl["marker"] and pl["argv"][0].endswith("powershell.exe")
          and "/d /s /c" in base64.b64decode(pl["argv"][-1]).decode("utf-16-le") and pl["cwd"] == "/mnt/c/Users/u", pl)
    check("cmd shim written under the Windows temp folder, cleaned afterwards", list(pl["files"])[0].endswith("plasbench.cmd") and str(tmp / "wintemp") in pl["cleanup"])
    term.cwd = PurePosixPath("/home/u")
    term.noticed.clear()
    pl = term._plan("dir")
    check("cmd in an Ubuntu folder: process starts in a Windows folder, pushd, shim has --cd", pl["cwd"] != "/home/u" and "pushd" in base64.b64decode(pl["argv"][-1]).decode("utf-16-le")
          and "--cd /home/u" in list(pl["files"].values())[0] and "UNC" not in pl["notice"] and "pushd" in pl["notice"], pl["notice"])
    # posix on a WSL host
    term.shell = "posix"
    a = term._argv("echo $(date) 'x y'")
    check("posix on WSL: login shell -lc, plasbench function, command last", a[1] == "-lc" and "plasbench() {" in a[2] and a[2].endswith("echo $(date) 'x y'"))
    check("prompts", (setattr(term, "shell", "winps") or term.prompt()).startswith("PS ") and (setattr(term, "shell", "cmd") or term.prompt()).endswith(">")
          and (setattr(term, "shell", "wingit") or term.prompt()).endswith("$") and (setattr(term, "shell", "posix") or term.prompt()).startswith("Ubuntu-24.04:")
          and (setattr(term, "shell", "wsl:Debian") or term.prompt()).startswith("Debian:"), term.prompt())

print("native Windows cmd shim text and command line")
winh = probe("windows", cmd="C:\\Windows\\System32\\cmd.exe", distros=[], git_bash=None)
with mock.patch.object(T, "_probe", lambda probe=None: probe or winh), mock.patch.object(T, "git_path_dirs", lambda: []):
    t2 = T.Terminal(home, tmp / "h2.jsonl")
    t2.host = "windows"
    t2.shell = "cmd"
    pl = t2._plan('echo "a b" & plasbench --version')
    check("native cmd: one raw command line, /d /s /c, outer quotes", pl["cmdline"].startswith("C:\\Windows\\System32\\cmd.exe /d /s /c \"chcp 65001>nul & set \"PATH=") and pl["cmdline"].endswith('plasbench --version"'), pl["cmdline"])
    check("native cmd shim runs this python on this folder", "-m plasbench --project-root" in list(pl["files"].values())[0])

print("running, kill path, timeouts")
t0 = time.time()
cancel = threading.Event()
rc, out, err, reason = T.run_process([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(60)"], None, None, 1.0, cancel)
check("a timeout stops the process quickly", reason == "timeout" and time.time() - t0 < 15 and rc is None, (reason, time.time() - t0))
cancel.clear()
threading.Timer(0.8, cancel.set).start()
rc, out, err, reason = T.run_process([sys.executable, "-c", "import time; time.sleep(60)"], None, None, 30, cancel)
check("cancel stops it", reason == "cancelled")
calls = []


class FakePopen:
    pid = 4321
    returncode = None
    stdout = stderr = None

    def __init__(self, *a, **k):
        import io
        self.stdout = io.BytesIO(b"PB_PID:777\r\nhello\r\n")
        self.stderr = io.BytesIO(b"")
        self.n = 0

    def poll(self):
        self.n += 1
        return None if self.n < 5 else self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return 0


def fake_kill_run(argv, **k):
    calls.append(argv)
    return subprocess.CompletedProcess(argv, 0)


with mock.patch.object(subprocess, "run", fake_kill_run), mock.patch.object(native_picker, "_taskkill", lambda exe, which=None: "/mnt/c/Windows/System32/taskkill.exe"), \
        mock.patch.object(os, "killpg", lambda *a: None, create=True):
    rc, out, err, reason = T.run_process(["x"], None, None, 0.05, None, FakePopen, True, "/mnt/c/x/powershell.exe", "wsl" if os.name != "nt" else "wsl")
check("timeout of a Windows program started from WSL runs taskkill.exe /F /T /PID <the Windows pid>", reason == "timeout"
      and ["/mnt/c/Windows/System32/taskkill.exe", "/F", "/T", "/PID", "777"] in calls, calls)
check("the PB_PID line is not part of the output", out == b"hello\r\n", out)

print("output decoding")
samples = [(b"caf\xe9 r\xe9sum\xe9\r\n", "powershell", "café résumé\n"), (b"caf\x82\r\n", "cmd", "café\n"), ("héllo 日本\r\n".encode("utf-16"), "powershell", "héllo 日本\n"),
           ("héllo".encode("utf-16-le"), "cmd", "héllo"), ("héllo 日本".encode("utf-8"), "cmd", "héllo 日本"), (b"\xef\xbb\xbfok", "powershell", "ok"), (b"", "cmd", ""),
           (b"\xff\xfe\x00", "utf8", None)]
for raw, kind, want in samples:
    got = T.clean_output(T.decode_output(raw, kind, oem="cp437", ansi="cp1252"))
    check(f"decode {raw[:12]!r} as {kind}", want is None or got == want, got)
check("ANSI and title codes are stripped, NUL removed", T.clean_output("\x1b[31mred\x1b[0m\x1b]0;title\x07 ok\x00\r\n") == "red ok\n")

print("per-shell history, route, page")
t3 = T.Terminal(home, tmp / "h3.jsonl", lambda: drive)
with mock.patch.object(T, "_probe", lambda probe=None: probe or CASES[2][1]):
    t3.shell = "posix"
    t3._record("ls", 0, 0.0)
    t3.shell = "cmd"
    t3._record("dir", 0, 0.0)
    check("history is kept per shell", t3.history_by["posix"] == ["ls"] and t3.history_by["cmd"] == ["dir"] and t3.history == ["ls", "dir"])
    t3b = T.Terminal(home, tmp / "h3.jsonl", lambda: drive)
    check("history per shell is reloaded from the file", t3b.history_by.get("cmd") == ["dir"])
    try:
        t3.use_shell("nope")
        check("an unknown shell is refused", False)
    except T.TerminalError:
        check("an unknown shell is refused", True)
    for ok in ("winps", "cmd", "wingit", "posix"):
        t3.use_shell(ok)
        check(f"use_shell accepts {ok}", t3.shell == ok)
with mock.patch.object(T, "_probe", lambda probe=None: probe or CASES[5][1]):
    try:
        t3.use_shell("winps")
        check("an unavailable shell is refused with the reason", False)
    except T.TerminalError as exc:
        check("an unavailable shell is refused with the reason", "interop is off" in str(exc), exc)
with mock.patch.object(T, "current_probe", lambda block=True, wait=0.0: (CASES[5][1], True)):
    st = t3.state(block=False)
    check("state lists shells, unavailable ones and this shell's history", [s["id"] for s in st["shells"]] == ["posix"] and len(st["unavailable"]) == 3
          and st["pending"] is False and "history" in st, st)
with mock.patch.object(T, "current_probe", lambda block=True, wait=0.0: (None, False)):
    check("a probe that is not ready answers pending without starting anything", t3.state(block=False)["pending"] is True)
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the page fills the dropdown from the server and greys unavailable shells", 'id="tsh"' in html and "st.shells.map" in html and "st.unavailable" in html and "disabled" in html)
check("the page asks again while the probe is pending", "st.pending" in html and "setTimeout(termState" in html)
check("the shell tooltip exists and is on the page", "term_shell" in ui_help.PAGE and 'data-tipid="term_shell"' in html)
check("no browser dialogs in the terminal code", not re.search(r"\b(alert|confirm|prompt)\(", html[html.index("terminal: your own commands"):html.index("async function askQuit")]))
web = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
check("the terminal state route never waits for the probe, the shell route is token protected", "terminal.state(block=False)" in web and 'route == "terminal/shell"' in web)

print("ALL TERMINAL SHELL TESTS PASSED" if OK else "TERMINAL SHELL TESTS FAILED")
sys.exit(0 if OK else 1)
