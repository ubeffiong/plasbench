"""The Terminal tab of the PlasBench window's footer console (after GenoSuv's terminal.py).

What it is for: the things a wizard never covers. You can list what a run produced, look inside a log, rerun one
`plasbench` subcommand with an unusual option, or tidy up after a failed attempt. Commands run in the PlasBench folder,
or a folder inside it or inside the studies workspace. Each one is recorded in ~/.plasbench/ui/terminal_history.jsonl.
The command line itself stays fully supported: this is the same shell, just next to the window.

Which shell (what the window's computer is decides the list; `available_shells` has the rules):
  * Linux, macOS: the login shell (Bash, Zsh). PATH already holds the plasbench environment's tools, because
    `plasbench ui` puts them there. `plasbench` is defined as a function that runs this very PlasBench folder.
  * Linux inside WSL: the login shell, labelled with the distribution ("Ubuntu-24.04 (Bash)"), and, while WSL interop is
    on, Windows PowerShell (pwsh.exe when installed), Windows Command Prompt (cmd) and Git Bash (Windows). They run
    through interop; `plasbench` there is a shim that calls back into the distribution. See `windows_side`.
  * Windows (native): Ubuntu (WSL) when it is installed, because the benchmark tools only exist there; then Git Bash,
    PowerShell and Command Prompt (cmd).
  * PowerShell (pwsh) is also offered anywhere it is installed.

What it is NOT: a sandbox. A command can do anything you can. Four limits are enforced here:
  * every request needs this session's key;
  * the server only listens on 127.0.0.1;
  * `cd` stays inside the PlasBench folder or the workspace;
  * output is capped, and a command is stopped after a timeout.
Commands get no keyboard input (stdin is empty), so an interactive program ends instead of hanging. Run interactive
or long jobs from the window's pages instead; their questions can be answered in the Job output tab.
"""
from __future__ import annotations

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
import uuid
from pathlib import Path, PureWindowsPath

from . import chooser, loadcache, native_picker
from .sessionlog import redact_command

MAX_OUTPUT = 200_000
DEFAULT_TIMEOUT = 600
MAX_COMMAND = 8_000
IS_WIN = os.name == "nt"


class TerminalError(ValueError):
    """A refused terminal request: the user's error (HTTP 400), not the server's."""


def _which_wsl():
    return shutil.which("wsl") if IS_WIN else None


_wsl_cache: dict = {}
WSL_TTL = 30.0


def wsl_distros() -> list:
    """The Linux distributions installed in WSL ([{name, default, state}]), default first; Docker Desktop's internal
    ones are left out. `wsl -l -v` answers in a fraction of a second, even when a distribution is stopped."""
    if not IS_WIN:
        return []
    now = time.time()
    if _wsl_cache.get("at", 0) + WSL_TTL > now:
        return _wsl_cache["list"]
    out = []
    exe = _which_wsl()
    if exe:
        try:
            p = subprocess.run([exe, "-l", "-v"], capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            raw = p.stdout
            text = raw.decode("utf-16-le", errors="replace") if raw[1:2] == b"\0" else raw.decode("utf-8", errors="replace")
            for line in text.replace("\0", "").splitlines()[1:]:
                parts = line.replace("*", " * ", 1).split() if line.strip() else []
                if not parts:
                    continue
                default = parts[0] == "*"
                parts = parts[1:] if default else parts
                name = parts[0]
                if name.lower().startswith("docker-desktop"):
                    continue
                out.append({"name": name, "default": default, "state": parts[1] if len(parts) > 1 else ""})
        except (OSError, subprocess.TimeoutExpired, IndexError):
            out = []
    out.sort(key=lambda d: not d["default"])
    _wsl_cache.update(at=now, list=out)
    return out


def git_for_windows_bash():
    """Git Bash's bash.exe from Git for Windows (never C:\\Windows\\System32\\bash.exe, the WSL launcher)."""
    if not IS_WIN:
        return None
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            for rel in (("Git", "bin", "bash.exe"), ("Programs", "Git", "bin", "bash.exe")):
                cand = Path(base, *rel)
                if cand.is_file():
                    return str(cand)
    found = shutil.which("bash")
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        return found
    return None


def git_path_dirs() -> list:
    """Folders that hold git on Windows (Git for Windows' cmd and bin), to put on the terminal's PATH."""
    bash = git_for_windows_bash()
    if not bash:
        return []
    top = Path(bash).parent.parent
    return [str(d) for d in (top / "cmd", top / "bin", top / "usr" / "bin") if d.is_dir()]


def powershell_argv():
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return [found, "-NoProfile", "-NonInteractive", "-Command"]
    return None


def posix_argv():
    if IS_WIN:
        bash = git_for_windows_bash()
        return [bash, "-lc"] if bash else None
    cands = [os.environ.get("SHELL", "")] + (["zsh"] if sys.platform == "darwin" else []) + ["bash", "sh"]
    for c in cands:
        if not c:
            continue
        found = c if os.path.isabs(c) and os.path.exists(c) else shutil.which(Path(c).name)
        if found:
            return [found, "-lc"]
    return None


# ----------------------------------------------------------------------------------------------- which shells exist here
PROBE_KEY = "terminal-shells"
PROBE_TTL = 60.0
WINDOWS_ONLY = ("winps", "cmd", "wingit")        # shells that are Windows programs (cmd also exists on a Windows host)
FIXED_GIT = ("/mnt/c/Program Files/Git/bin/bash.exe", "/mnt/c/Program Files/Git/usr/bin/bash.exe",
             "/mnt/c/Program Files (x86)/Git/bin/bash.exe")
USER_GIT = ("AppData", "Local", "Programs", "Git", "bin", "bash.exe")


def host_kind() -> str:
    """'windows' | 'wsl' | 'mac' | 'linux': where this window's server runs."""
    return native_picker._platform(wsl=chooser.in_wsl() or bool(os.environ.get("WSL_DISTRO_NAME")))


def _login_name(path) -> str:
    return Path(str(path or "bash")).stem.capitalize() or "Bash"


def _short_reason(text: str, limit: int = 220) -> str:
    return " ".join(str(text or "").split())[:limit]


def windows_side(env=None, which=shutil.which, exists=os.path.exists, run=subprocess.run, listdir=os.listdir, interop=None) -> dict:
    """The Windows programs a WSL window can start, found by absolute path (the lookup PlasBench's folder window already uses, native_picker.find_powershell):
    {'ps': path|None, 'ps_kind': 'pwsh'|'powershell', 'cmd': path|None, 'git': path|None, 'why': {id: reason}}. With interop off nothing is looked for and every
    Windows entry gets the reason. No process is started unless the usual places fail (then cmd.exe or reg.exe is asked once, in the background probe)."""
    env = os.environ if env is None else env
    out = {"ps": None, "ps_kind": "", "cmd": None, "git": None, "why": {}}
    if interop and interop.get("enabled") is False:
        why = "WSL interop is off, so Linux programs cannot start Windows programs: " + _short_reason(interop.get("detail"))
        out["why"] = {"winps": why, "cmd": why, "wingit": why}
        return out
    ps, tried = native_picker.find_powershell(env, which, exists, run, listdir, "wsl")
    pwsh = which("pwsh.exe") or next((c for c in native_picker.POWERSHELL_FIXED if c.lower().endswith("pwsh.exe") and exists(c)), None)
    chosen = pwsh or ps
    if chosen:
        out["ps"], out["ps_kind"] = chosen, ("pwsh" if Path(chosen).name.lower().startswith("pwsh") else "powershell")
    else:
        out["why"]["winps"] = ("powershell.exe was not found (looked in " + ", ".join(tried[:4]) + "); if /etc/wsl.conf has appendWindowsPath=false, "
                               "Windows programs are not on PATH and C: may not be mounted")
    cmd = which("cmd.exe")
    if not cmd and ps:
        try:                                    # powershell.exe lives in <System32>\WindowsPowerShell\v1.0
            cand = Path(ps).parents[2] / "cmd.exe"
            cmd = str(cand) if cand.name == "cmd.exe" and exists(str(cand)) else None
        except IndexError:
            cmd = None
    if not cmd and exists("/mnt/c/Windows/System32/cmd.exe"):
        cmd = "/mnt/c/Windows/System32/cmd.exe"
    out["cmd"] = cmd
    if not cmd:
        out["why"]["cmd"] = "cmd.exe was not found in /mnt/c/Windows/System32 or on PATH"
    out["git"] = _windows_git(which, exists, run, listdir, [p for p in (cmd, ps) if p])
    return out


def _windows_git(which, exists, run, listdir, anchors) -> str | None:
    """Git for Windows' bash.exe as a Linux path, or None (Git is optional, so no reason is recorded). Fixed folders first, then a per-user install, PATH,
    and last the registry (reg.exe, one question per hive)."""
    for cand in FIXED_GIT:
        if exists(cand):
            return cand
    try:
        for user in sorted(listdir("/mnt/c/Users"))[:40]:
            cand = "/mnt/c/Users/" + user + "/" + "/".join(USER_GIT)
            if exists(cand):
                return cand
    except OSError:
        pass
    found = which("bash.exe")
    if found and "system32" not in found.lower() and "windowsapps" not in found.lower():
        return found
    reg = which("reg.exe")
    if not reg:
        for a in anchors:
            try:
                cand = str(Path(a).parents[2] / "reg.exe") if "WindowsPowerShell" in a else str(Path(a).parent / "reg.exe")
            except IndexError:
                continue
            if exists(cand):
                reg = cand
                break
    if not reg:
        return None
    for hive in ("HKLM", "HKCU"):
        try:
            got = run([reg, "query", hive + "\\SOFTWARE\\GitForWindows", "/v", "InstallPath"], capture_output=True, timeout=8)
            text = got.stdout.decode("utf-8", "replace") if got.returncode == 0 else ""
            m = re.search(r"InstallPath\s+REG_SZ\s+(.+)", text)
            if m:
                top = chooser.to_linux(m.group(1).strip(), wsl=True, run=run).rstrip("/")
                for rel in ("/bin/bash.exe", "/usr/bin/bash.exe"):
                    if exists(top + rel):
                        return top + rel
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def probe_shells(host: str | None = None, env=None, which=shutil.which, exists=os.path.exists, run=subprocess.run, read=None, listdir=os.listdir) -> dict:
    """Everything `available_shells` needs, found once (and cached in the background by `current_probe`; nothing here runs on the page-load path):
    {'host', 'distro', 'distros', 'login', 'login_name', 'pwsh', 'git_bash', 'cmd', 'interop', 'win': windows_side(), 'why': {id: reason}}."""
    env = os.environ if env is None else env
    host = host or host_kind()
    p = {"host": host, "distro": env.get("WSL_DISTRO_NAME", "") if host == "wsl" else "", "distros": [], "login": None, "login_name": "", "pwsh": None,
         "git_bash": None, "cmd": None, "interop": None, "win": None, "why": {}}
    if host == "windows":
        p["distros"] = wsl_distros()
        p["git_bash"] = git_for_windows_bash()
        ps = powershell_argv()
        p["pwsh"] = ps[0] if ps else None
        p["cmd"] = shutil.which("cmd") or (os.environ.get("ComSpec") if os.environ.get("ComSpec") and os.path.exists(os.environ["ComSpec"]) else None)
        return p
    sh = posix_argv()
    p["login"] = sh[0] if sh else None
    p["login_name"] = _login_name(sh[0]) if sh else "Bash"
    ps = powershell_argv()
    p["pwsh"] = ps[0] if ps else None
    if host == "wsl":
        kw = {"read": read} if read else {}
        p["interop"] = native_picker.interop_state(env, **kw)
        p["win"] = windows_side(env, which, exists, run, listdir, p["interop"])
        p["why"] = dict(p["win"]["why"])
    return p


def current_probe(block: bool = True, wait: float = 0.0) -> tuple:
    """(probe, ready): the cached probe, refreshed in the background once it is older than PROBE_TTL. block=False never waits longer than `wait` seconds."""
    return loadcache.swr(PROBE_KEY, PROBE_TTL, probe_shells, block=block, wait=wait)


def reset_probe():
    loadcache.forget(PROBE_KEY)
    _wsl_cache.clear()


def _probe(probe=None) -> dict:
    return probe if probe is not None else current_probe()[0]


def available_shells(probe=None) -> dict:
    """{id: what it reaches}, in the order they are offered.
    Windows host: each WSL distribution (where the benchmark tools run), Git Bash, PowerShell, cmd.
    WSL host: the login shell, pwsh if installed in Linux, then (interop on) Windows PowerShell, cmd and Git Bash (Windows).
    Linux or Mac host: the login shell, and PowerShell if pwsh is installed."""
    p = _probe(probe)
    out = {}
    if p["host"] == "windows":
        for d in p["distros"]:
            out["wsl:" + d["name"]] = (f"{d['name']} (Linux in WSL{', the default distribution' if d['default'] else ''}): "
                                       "where the benchmark tools, conda and git run on Windows")
        if p["git_bash"]:
            out["posix"] = "Git Bash (Git for Windows): bash and git on Windows; no access to the WSL tools"
        if p["pwsh"]:
            out["powershell"] = "PowerShell: Windows programs, drive letters, and git when Git for Windows is installed"
        if p["cmd"]:
            out["cmd"] = "Command Prompt (cmd): Windows programs and batch files; plasbench runs this PlasBench folder"
        return out
    if p["login"]:
        out["posix"] = ("your login shell in " + (p["distro"] or "WSL") + ": the plasbench environment's tools and git are on its PATH"
                        if p["host"] == "wsl" else "your login shell: the plasbench environment's tools and git are on its PATH")
    if p["pwsh"]:
        out["powershell"] = "PowerShell (pwsh in Linux)" if p["host"] == "wsl" else "PowerShell (pwsh)"
    win = p.get("win")
    if p["host"] == "wsl" and win:
        if win["ps"]:
            exe = Path(win["ps"]).name
            out["winps"] = (f"Windows PowerShell ({exe}), started from Ubuntu: Windows programs and files; plasbench calls back into "
                            f"{p['distro'] or 'Ubuntu'}")
        if win["cmd"] and "cmd" not in p["why"]:
            out["cmd"] = ("Windows Command Prompt (cmd.exe), started from Ubuntu: Windows programs and batch files; plasbench calls back into "
                          f"{p['distro'] or 'Ubuntu'}. In an Ubuntu folder it works through a temporary drive letter (pushd)")
        if win["git"]:
            out["wingit"] = "Git Bash (Git for Windows), started from Ubuntu: Windows' bash and git; it cannot see the Ubuntu tools"
    return out


def unavailable_shells(probe=None) -> dict:
    """{id: {'label', 'why'}} for Windows shells a WSL window would offer but cannot (interop off, program not found): the window shows them
    disabled, with the reason in the tooltip."""
    p = _probe(probe)
    return {k: {"label": shell_label(k, p), "why": v} for k, v in p.get("why", {}).items() if k in WINDOWS_ONLY}


def default_shell(probe=None) -> str:
    p = _probe(probe)
    shells = available_shells(p)
    if p["host"] == "windows":
        for name in shells:                   # the default WSL distribution comes first
            if name.startswith("wsl:"):
                return name
        order = ("posix", "powershell", "cmd")
    else:
        order = ("posix", "powershell", "winps", "cmd")
    for name in order:
        if name in shells:
            return name
    return ""


def shell_label(name: str, probe=None) -> str:
    if name.startswith("wsl:"):
        return f"{name[4:]} (WSL)"
    p = _probe(probe)
    host = p["host"]
    if name == "posix":
        if host == "windows":
            return "Git Bash"
        if host == "wsl":
            return f"{p['distro'] or 'Ubuntu'} ({p['login_name'] or 'Bash'})"
        return p["login_name"] or "Bash"
    return {"wsl": "Ubuntu (WSL)", "powershell": "PowerShell (Linux)" if host == "wsl" else "PowerShell", "winps": "Windows PowerShell",
            "cmd": "Windows Command Prompt (cmd)" if host == "wsl" else "Command Prompt (cmd)", "wingit": "Git Bash (Windows)"}.get(name, name or "none")


# ----------------------------------------------------------------------------------------------- quoting
def to_msys_path(p) -> str:
    r"""C:\x\y -> /c/x/y, the form Git Bash expects; \\server\share\x -> //server/share/x."""
    if str(p).startswith("\\\\"):
        return str(p).replace("\\", "/")
    w = PureWindowsPath(str(p))
    if not w.drive or not w.drive.endswith(":"):
        return str(p).replace("\\", "/")
    return "/" + w.drive[0].lower() + "/" + "/".join(w.parts[1:])


def to_wsl_path(p: Path):
    """C:\\x\\y -> /mnt/c/x/y; None for a network share (WSL cannot see it as a /mnt path)."""
    w = PureWindowsPath(str(p))
    if not w.drive or not w.drive.endswith(":"):
        return None
    return "/mnt/" + w.drive[0].lower() + "/" + "/".join(w.parts[1:])


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


PS_QUOTES = "'\u2018\u2019\u201a\u201b"      # PowerShell treats all four typographic single quotes as a single quote


def _psq(s: str) -> str:
    """A PowerShell single-quoted string: every kind of single quote (ASCII and the typographic ones PowerShell also accepts) is doubled."""
    return "'" + "".join(c * 2 if c in PS_QUOTES else c for c in str(s)) + "'"


SAFE_ARG = re.compile(r"^[A-Za-z0-9_.:/+@,-]+$")


def cmd_quote(s: str) -> str:
    """One argument inside a .cmd file line. Plain words (options such as -d, -e, wsl.exe) stay bare: wsl.exe does not recognise a quoted "-d" as its option.
    Anything else gets double quotes, % doubled and a trailing backslash doubled (so the program's own argument parser does not read it as an escaped quote).
    A double quote, newline or NUL cannot be written safely and is refused."""
    s = str(s)
    if SAFE_ARG.match(s):
        return s
    if any(c in s for c in '"\r\n\x00'):
        raise TerminalError("a path with a double quote or a line break cannot be used with Command Prompt")
    s = s.replace("%", "%%")
    return '"' + s + "\\" * (len(s) - len(s.rstrip("\\"))) + '"'


def cmd_shim_text(argv: list) -> str:
    """The text of plasbench.cmd: `argv` (the fixed program and its fixed arguments) then %* (what the user typed after `plasbench`)."""
    return ("@echo off\r\nsetlocal DisableDelayedExpansion\r\n" + " ".join(cmd_quote(a) for a in argv) + " %*\r\n"
            "exit /b %ERRORLEVEL%\r\n")


def cmd_payload(command: str, shim_dir: str, unc=None) -> str:
    """The text between the outer quotes of `cmd.exe /d /s /c "..."`: UTF-8 code page, the shim folder first on PATH, the folder (pushd for a network or
    \\wsl.localhost path, which cmd cannot start in), then the user's command. Several lines become one line joined with `&`. cmd gets it as a raw command line
    (Popen given a string on Windows; ProcessStartInfo.Arguments from PowerShell under WSL: interop would re-quote a list), so %VAR% still expands and quotes mean
    what the user typed."""
    if any(c in shim_dir for c in '"%\r\n'):
        raise TerminalError("the temporary folder's name has a character Command Prompt cannot take (a quote or %)")
    lines = [ln.strip() for ln in command.replace("\r", "").split("\n") if ln.strip()]
    steps = ["chcp 65001>nul", f'set "PATH={shim_dir};%PATH%"']
    if unc:
        if any(c in unc for c in '"\r\n'):
            raise TerminalError("that folder's name has a double quote or a line break, which Command Prompt cannot take")
        steps.append(f'pushd "{unc}" || exit 1')
    return " & ".join(steps + [" & ".join(lines)])


def ps_encoded(exe: str, script: str) -> list:
    """Windows PowerShell or pwsh started with the whole script as -EncodedCommand (UTF-16, base64): no quoting layer can touch it, which is what makes it safe
    through WSL interop. -OutputFormat Text keeps errors as text (with an encoded command PowerShell would answer in CLIXML)."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    if len(enc) > 30000:
        raise TerminalError("that command is too long for PowerShell's command line; run it from a script file instead")
    return [exe, "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", enc]


PS_UTF8 = ("$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
           "$OutputEncoding=[Console]::OutputEncoding;")
PID_LINE = b"PB_PID:"


def wsl_call(distro: str, py: str, root: str, linux_path: str = "", cd: str = "") -> list:
    """The fixed part of the `plasbench` shim that calls back into Ubuntu from Windows: wsl.exe starts python directly (-e, no shell), through /usr/bin/env so
    that the window's PATH (the plasbench environment's tools) is the PATH there too; --cd only when given (a Linux folder)."""
    argv = ["wsl.exe"] + (["-d", distro] if distro else []) + (["--cd", cd] if cd else []) + ["-e"]
    if linux_path and len(linux_path) < 6000 and not any(c in linux_path for c in '"\r\n\x00'):
        argv += ["/usr/bin/env", "PATH=" + linux_path]
    return argv + [py, "-m", "plasbench", "--project-root", root]


# ----------------------------------------------------------------------------------------------- output
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>MNOP78c]")


def _codepages() -> tuple:
    """(OEM code page for console programs, ANSI code page for GUI programs), as Python codec names; the usual Western ones where Windows cannot be asked."""
    oem, ansi = "cp437", "cp1252"
    if IS_WIN:
        try:
            import ctypes
            oem, ansi = f"cp{ctypes.windll.kernel32.GetOEMCP()}", f"cp{ctypes.windll.kernel32.GetACP()}"
        except (AttributeError, OSError, ValueError):
            pass
    return oem, ansi


def decode_output(raw: bytes, kind: str = "utf8", oem: str | None = None, ansi: str | None = None) -> str:
    """Windows programs answer in UTF-16 (a BOM, or NUL after every ASCII letter), UTF-8 (what the shim asks for with chcp 65001 / [Console]::OutputEncoding), or the
    old code page they started with: the OEM one for cmd, the ANSI one for PowerShell. Never raises."""
    raw = raw or b""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    odd, even = raw[1::2], raw[0::2]
    if len(raw) >= 4 and odd.count(0) * 2 > len(odd) and even.count(0) * 4 < len(even):
        return raw.decode("utf-16-le", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    o, a = _codepages()
    codec = (oem or o) if kind == "cmd" else (ansi or a) if kind == "powershell" else ""
    if codec:
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            pass
    return raw.decode("utf-8", errors="replace")


def clean_output(text: str) -> str:
    """Terminal noise out (NUL, colour and cursor codes, window-title codes), Windows line ends as \\n."""
    return ANSI.sub("", text.replace("\x00", "")).replace("\r\n", "\n")


def _pump(stream, buf: bytearray, cap: int, holder: dict, marker: bool):
    try:
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
            if not chunk:
                break
            if len(buf) < cap:
                buf += chunk[:cap - len(buf)]
            if marker and holder.get("pid") is None:
                m = re.match(rb"PB_PID:(\d+)\r?\n", bytes(buf[:40]))
                if m:
                    holder["pid"] = int(m.group(1))
    except (OSError, ValueError):
        pass


def run_process(argv, cwd, env, timeout: float, cancel, popen=subprocess.Popen, marker: bool = False, kill_exe=None, plat: str = "linux") -> tuple:
    """Run one command to the end: (returncode | None, stdout bytes, stderr bytes, reason in '' | 'timeout' | 'cancelled'). The whole process tree is stopped on a
    timeout or a cancel: taskkill /T on Windows, the process group elsewhere, and for a Windows program started from WSL also taskkill.exe on the Windows process id
    the script printed first (PB_PID:), because stopping the Linux stub does not stop the Windows process behind it."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": cwd, "env": env}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True
    proc = popen(argv, **kw)
    out, err, holder = bytearray(), bytearray(), {"pid": None}
    cap = MAX_OUTPUT * 4
    threads = [threading.Thread(target=_pump, args=(proc.stdout, out, cap, holder, marker), daemon=True),
               threading.Thread(target=_pump, args=(proc.stderr, err, cap, {}, False), daemon=True)]
    for t in threads:
        t.start()
    deadline, reason = time.time() + timeout, ""
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            reason = "cancelled"
        elif time.time() >= deadline:
            reason = "timeout"
        if reason:
            native_picker._kill(proc, holder["pid"], plat, kill_exe)
            break
        time.sleep(0.03)
    for t in threads:
        t.join(2)
    data = bytes(out)
    m = re.match(rb"PB_PID:\d+\r?\n", data) if marker else None
    if m:
        data = data[m.end():]
    return (proc.returncode if not reason else None), data, bytes(err), reason



class Terminal:
    """One terminal per window, with its own current folder inside the PlasBench folder or the workspace."""

    def __init__(self, root: Path, history_file: Path, workspace=None, on_record=None, popen=None, run_fn=None):
        self.root = Path(root).resolve()
        self.workspace = workspace          # a callable returning the current workspace folder (it can change)
        self.cwd = self.root
        self._shell = None                  # the default is chosen on first use: finding it asks the (cached) shell probe, which can start `wsl -l -v`
        self.host = host_kind()
        self.history_file = Path(history_file)
        self.on_record = on_record          # called with each command's record (the window's session log)
        self.history: list = []
        self.history_by: dict = {}          # shell id -> its own commands (Up/Down recall in the shell you are in)
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.popen = popen or subprocess.Popen
        self.run_fn = run_fn or subprocess.run
        self.noticed: set = set()
        try:
            for line in self.history_file.read_text(encoding="utf-8").splitlines()[-200:]:
                rec = json.loads(line)
                self.history.append(rec["command"])
                self.history_by.setdefault(rec.get("shell", ""), []).append(rec["command"])
            del self.history[:-50]
        except (OSError, ValueError, KeyError):
            pass

    @property
    def shell(self) -> str:
        if self._shell is None:
            self._shell = default_shell()
        return self._shell

    @shell.setter
    def shell(self, name: str):
        self._shell = name

    # ------------------------------------------------------------------------------------------- folders
    def roots(self) -> list:
        out = [self.root]
        try:
            ws = Path(self.workspace()).resolve() if self.workspace else None
        except (OSError, TypeError, ValueError):
            ws = None
        if ws and ws not in out:
            out.append(ws)
        return out

    def _inside(self, p: Path) -> bool:
        for r in self.roots():
            try:
                p.relative_to(r)
                return True
            except ValueError:
                continue
        return False

    def set_cwd(self, target: str) -> Path:
        target = target.strip().strip('"').strip("'")
        if target in ("", "~"):
            new = self.root
        elif target.startswith("~/"):
            new = (self.root / target[2:]).resolve()
        else:
            new = Path(target)
            new = (new if new.is_absolute() else self.cwd / new).resolve()
        if not new.is_dir():
            raise TerminalError(f"no such folder: {new}")
        if not self._inside(new):
            raise TerminalError(f"{new} is outside the PlasBench folder and the workspace; the terminal stays inside them "
                                "so a mistyped path cannot act on the rest of the disk.")
        self.cwd = new
        return new

    def shown_cwd(self) -> str:
        for r, name in zip(self.roots(), ("PlasBench", "workspace")):
            try:
                rel = self.cwd.relative_to(r)
                return name if str(rel) == "." else f"{name}/{rel.as_posix()}"
            except ValueError:
                continue
        return str(self.cwd)

    def prompt(self) -> str:
        where = self.shown_cwd()
        if self.shell in ("powershell", "winps"):
            return f"PS {where}>"
        if self.shell == "cmd":
            return f"{where}>"
        if self.shell.startswith("wsl:"):
            return f"{self.shell[4:]}:{where}$"
        if self.shell == "posix" and self.host == "wsl":
            return f"{os.environ.get('WSL_DISTRO_NAME') or 'Ubuntu'}:{where}$"
        return f"{where}$"

    # ------------------------------------------------------------------------------------------- running
    def use_shell(self, name: str):
        p = _probe()
        shells = available_shells(p)
        if name == "wsl":                     # the default distribution
            name = next((k for k in shells if k.startswith("wsl:")), name)
        if name not in shells:
            why = unavailable_shells(p).get(name)
            if why:
                raise TerminalError(f"{why['label']} is not available here: {why['why']}")
            raise TerminalError(f"'{name}' is not available here; this computer offers: " + (", ".join(shells) or "none"))
        self.shell = name

    def cancel(self):
        """Stop the command that is running (its whole process tree). Safe to call from another thread; does nothing when nothing runs."""
        self.cancel_event.set()

    def win_cwd(self) -> str:
        """The current folder as Windows writes it: `wslpath -w` on a WSL host (\\\\wsl.localhost\\<distro>\\... inside Ubuntu, C:\\... under /mnt/c), the path itself
        on Windows."""
        if self.host == "wsl":
            return chooser.to_windows(str(self.cwd), wsl=True, run=self.run_fn, distro=os.environ.get("WSL_DISTRO_NAME") or None)
        return str(self.cwd)

    def _plan(self, command: str, dry: bool = False) -> dict:
        """How to run `command` in the current shell: {'argv', 'cwd', 'env' (extra variables), 'files' ({path: text} the shim needs), 'cleanup' (folder to remove),
        'notice', 'decode', 'marker' (the first line is PB_PID:), 'kill_exe', 'plat'}. Nothing is written or started here."""
        plan = {"argv": [], "cwd": str(self.cwd), "env": {}, "files": {}, "cleanup": "", "notice": "", "decode": "utf8", "marker": False,
                "kill_exe": None, "plat": "windows" if IS_WIN else "linux"}
        shell, p = self.shell, _probe()
        py, root = sys.executable, str(self.root)
        if shell == "powershell":
            ps = powershell_argv()
            if not ps:
                raise TerminalError("PowerShell was not found")
            prelude = (PS_UTF8 if self.host == "windows" else "") + f"function plasbench {{ & {_psq(py)} -m plasbench --project-root {_psq(root)} @args }}; "
            plan.update(argv=ps + [prelude + command], decode="powershell")
            return plan
        if shell.startswith("wsl"):
            distro = shell[4:] if shell.startswith("wsl:") else ""
            where = to_wsl_path(self.cwd)
            if not where:
                raise TerminalError(f"WSL cannot reach {self.cwd}; switch the terminal to PowerShell.")
            wroot = to_wsl_path(self.root) or ""
            # `plasbench` inside Ubuntu runs this same PlasBench folder with Ubuntu's Python, unless Ubuntu has its own.
            prelude = (f"command -v plasbench >/dev/null 2>&1 || plasbench() {{ python3 -m plasbench --project-root {_q(wroot)} \"$@\"; }}; "
                       if wroot else "")
            plan.update(argv=[_which_wsl() or "wsl"] + (["-d", distro] if distro else []) + ["-e", "bash", "-lc", f"{prelude}cd {_q(where)} && {command}"], cwd=None)
            return plan
        if shell == "cmd":
            return self._plan_cmd(plan, command, p, py, root, dry)
        if shell in ("winps", "wingit"):
            return self._plan_interop(plan, shell, command, p, py, root)
        sh = posix_argv()
        if not sh:
            raise TerminalError("no shell was found on this computer")
        if IS_WIN:                            # Git Bash wants /c/... paths
            py, root = to_msys_path(py), to_msys_path(root)
        prelude = f"plasbench() {{ {_q(py)} -m plasbench --project-root {_q(root)} \"$@\"; }}; "
        plan["argv"] = sh + [prelude + command]
        return plan

    def _wsl_target(self, p: dict) -> tuple:
        """(distro, python, project folder, PATH) as the Linux side sees them, for the shims that call back into this distribution."""
        return os.environ.get("WSL_DISTRO_NAME", p.get("distro", "")), sys.executable, str(self.root), os.environ.get("PATH", "")

    def _plan_interop(self, plan: dict, shell: str, command: str, p: dict, py: str, root: str) -> dict:
        win = p.get("win") or {}
        distro, py, root, path = self._wsl_target(p)
        call = wsl_call(distro, py, root, path, cd=str(self.cwd) if shell == "winps" and self.win_cwd().startswith("\\\\") else "")
        if shell == "winps":
            exe = win.get("ps")
            if not exe:
                raise TerminalError("Windows PowerShell is not available here: " + p.get("why", {}).get("winps", "powershell.exe was not found"))
            script = (PS_UTF8 + "[Console]::Out.WriteLine('PB_PID:'+$PID);function plasbench { & " + " ".join(_psq(a) for a in call)
                      + " @args }; " + command + "\nif(-not $? -and $LASTEXITCODE){exit $LASTEXITCODE}")
            plan.update(argv=ps_encoded(exe, script), decode="powershell", marker=True, kill_exe=exe, plat="wsl")
        else:
            exe = win.get("git")
            if not exe:
                raise TerminalError("Git Bash (Windows) is not installed or not reachable from here")
            wcwd = self.win_cwd()
            func = "plasbench() { MSYS2_ARG_CONV_EXCL='*' " + " ".join(_q(a) for a in call) + " \"$@\"; }; "
            plan.update(argv=[exe, "-lc", 'echo "PB_PID:$(cat /proc/$$/winpid)"; ' + func + f"cd {_q(to_msys_path(wcwd))} && {command}"],
                        marker=True, kill_exe=exe, plat="wsl")
        if (win.get("ps") or win.get("git")) and self.win_cwd().startswith("\\\\") and (shell, "unc") not in self.noticed:
            self.noticed.add((shell, "unc"))
            plan["notice"] = ("[This folder is inside Ubuntu (a \\\\wsl.localhost path). Windows programs that do not understand network paths may start in "
                              "C:\\Windows instead; cd to a folder under /mnt/c to run them there.]")
        return plan

    def _plan_cmd(self, plan: dict, command: str, p: dict, py: str, root: str, dry: bool) -> dict:
        """Command Prompt, native or through WSL interop: the command runs by `cmd /d /s /c "..."` (see cmd_payload) with a per-command folder that holds the
        plasbench.cmd shim, removed afterwards. cmd cannot start in a UNC folder (it falls back to C:\\Windows and says so), so such a folder is entered with pushd."""
        wsl = self.host == "wsl"
        exe = (p.get("win") or {}).get("cmd") if wsl else p.get("cmd")
        if not exe:
            raise TerminalError("Command Prompt was not found" + (": " + p["why"]["cmd"] if p.get("why", {}).get("cmd") else ""))
        name = "plasbench-term-" + uuid.uuid4().hex[:8]
        if wsl:
            ps = (p.get("win") or {}).get("ps")
            win_tmp, local_tmp = native_picker.windows_temp(ps, "wsl", self.run_fn) if ps and not dry else ("", "")
            if not (win_tmp and local_tmp):
                win_tmp, local_tmp = "C:\\Windows\\Temp", "/mnt/c/Windows/Temp"
            wcwd = self.win_cwd()
            distro, lpy, lroot, lpath = self._wsl_target(p)
            unc = wcwd if wcwd.startswith("\\\\") else None
            argv = wsl_call(distro, lpy, lroot, lpath, cd=str(self.cwd) if unc else "")
            shim_dir, shim_local = win_tmp.rstrip("\\") + "\\" + name, str(Path(local_tmp) / name)
            plan.update(cwd=(("/mnt/c" if os.path.isdir("/mnt/c") else str(self.cwd)) if unc else str(self.cwd)), plat="wsl", kill_exe=exe)
            if unc and ("cmd", "unc") not in self.noticed:
                self.noticed.add(("cmd", "unc"))
                plan["notice"] = ("[This folder is inside Ubuntu, and Command Prompt cannot start in a network path: it works through a temporary drive letter "
                                  "(pushd). Programs that insist on a real drive: cd to a folder under /mnt/c.]")
        else:
            argv = [py, "-m", "plasbench", "--project-root", root]
            shim_dir = str(Path(tempfile.gettempdir()) / name)
            shim_local = shim_dir
            unc = self.cwd.as_posix().startswith("//") and str(self.cwd) or None
            if unc:
                plan.update(cwd=tempfile.gettempdir())
        payload = cmd_payload(command, shim_dir, unc)
        plan["files"] = {str(Path(shim_local) / "plasbench.cmd"): cmd_shim_text(argv)}
        plan["cleanup"] = shim_local
        plan["decode"] = "cmd"
        line = '/d /s /c "' + payload + '"'          # the raw command line cmd receives: /s strips exactly these outer quotes
        if wsl and (p.get("win") or {}).get("ps"):
            # PowerShell starts cmd with ProcessStartInfo.Arguments (a raw command line: WSL interop would otherwise re-quote every double quote of the command),
            # waits for it, and prints its own process id first: that is what a cancel or timeout kills (taskkill /T takes cmd and its children with it).
            ps = p["win"]["ps"]
            script = (PS_UTF8 + "[Console]::Out.WriteLine('PB_PID:'+$PID);$i=New-Object Diagnostics.ProcessStartInfo;$i.FileName=$env:ComSpec;$i.Arguments="
                      + _psq(line) + ";$i.UseShellExecute=$false;$q=[Diagnostics.Process]::Start($i);$q.WaitForExit();exit $q.ExitCode")
            plan.update(argv=ps_encoded(ps, script), marker=True, kill_exe=ps)
        else:
            plan["argv"] = [exe, "/d", "/s", "/c", '"' + payload + '"']
            if not wsl:
                plan["cmdline"] = subprocess.list2cmdline([exe]) + " " + line
        return plan

    def _argv(self, command: str) -> list:
        """The argument list that runs `command` in the current shell (nothing is written; `run` makes the shim files)."""
        return self._plan(command, dry=True)["argv"]

    def _materialize(self, plan: dict):
        for path, text in plan["files"].items():
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(text.encode("utf-8"))

    @staticmethod
    def _cleanup(plan: dict):
        if plan.get("cleanup"):
            shutil.rmtree(plan["cleanup"], ignore_errors=True)

    def run(self, command: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
        command = (command or "").strip()
        if not command:
            raise TerminalError("type a command first")
        if len(command) > MAX_COMMAND:
            raise TerminalError(f"that command is longer than {MAX_COMMAND} characters")
        if not self.shell:
            raise TerminalError("no shell was found on this computer")
        with self.lock:
            # `cd` is handled here: a child process cannot change the folder of the next command.
            parts = command.split(maxsplit=1)
            if (parts[0].lower() in ("cd", "chdir", "set-location") and "&&" not in command and ";" not in command
                    and "\n" not in command):
                self.set_cwd(parts[1] if len(parts) > 1 else "")
                self._record(command, 0, 0.0)
                return {"exit": 0, "output": str(self.cwd), "prompt": self.prompt(), "seconds": 0.0, "shell": self.shell}
            started = time.time()
            self.cancel_event.clear()
            plan = {"files": {}, "cleanup": "", "notice": "", "decode": "utf8"}
            try:
                plan = self._plan(command)
                self._materialize(plan)
                env = dict(os.environ, PLASBENCH_TERMINAL="1", **plan["env"])
                extra = [d for d in git_path_dirs() if d not in env.get("PATH", "").split(os.pathsep)]
                if extra:                     # git (and Git Bash's tools) on PATH for PowerShell and Git Bash
                    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + extra)
                rc, out, err, reason = run_process(plan.get("cmdline") or plan["argv"], plan["cwd"], env, timeout, self.cancel_event, self.popen, plan["marker"],
                                                   plan["kill_exe"], plan["plat"])
                if reason == "timeout":
                    code, text = 124, f"(stopped after {timeout:g} s: start long work from the window's pages instead)"
                elif reason == "cancelled":
                    code, text = 130, "(stopped)"
                else:
                    code = rc if rc is not None else 1
                    text = decode_output(out, plan["decode"]) + decode_output(err, plan["decode"])
            except OSError as exc:
                code, text = 127, str(exc)
            finally:
                self._cleanup(plan)
            seconds = round(time.time() - started, 2)
            text = clean_output(text)
            if plan["notice"]:
                text = (text + "\n" if text else "") + plan["notice"]
            if self.shell.startswith("wsl") and (code in (-1, 4294967295) or "connection attempt failed" in text.lower()
                                                 or "wsl/service" in text.lower()):
                text += ("\n[WSL did not respond. In PowerShell run  wsl --shutdown  then try again (Docker Desktop "
                         "restarts its own WSL parts). Git Bash and PowerShell still work from the shell list.]")
            if len(text) > MAX_OUTPUT:
                text = text[:MAX_OUTPUT] + f"\n... output cut at {MAX_OUTPUT} characters"
            self._record(command, code, seconds)
            return {"exit": code, "output": text, "prompt": self.prompt(), "seconds": seconds, "shell": self.shell}

    def _record(self, command: str, code: int, seconds: float):
        if self.on_record:
            try:
                self.on_record({"shell": self.shell, "shell_label": shell_label(self.shell), "cwd": str(self.cwd),
                                "command": redact_command(command[:2000]), "exit": code, "seconds": seconds})
            except Exception:  # noqa: BLE001 - the record never stops a command
                pass
        self.history.append(command)
        del self.history[:-200]
        mine = self.history_by.setdefault(self.shell, [])
        mine.append(command)
        del mine[:-200]
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "shell": self.shell,
                                         "cwd": str(self.cwd), "command": redact_command(command[:2000]), "exit": code,
                                         "seconds": seconds}) + "\n")
        except OSError:
            pass

    def about(self) -> str:
        interop = self.shell in WINDOWS_ONLY and self.host == "wsl"
        git = "" if self.shell.startswith("wsl") or interop or self._git_here() else \
            " Git was not found: Set up this computer > Git > Install (optional)."
        if self.shell.startswith("wsl"):
            return (f"{shell_label(self.shell)}: Linux, where the benchmark tools live on Windows; git, bash and conda run "
                    "here. `plasbench` runs this PlasBench folder.")
        return {"powershell": "PowerShell. `plasbench` runs this PlasBench folder; `git` works when Git for Windows is installed.",
                "cmd": ("Windows Command Prompt, started from Ubuntu. `plasbench` calls back into Ubuntu and runs this PlasBench folder. In an Ubuntu folder it "
                        "works through a temporary drive letter (pushd)." if self.host == "wsl" else
                        "Command Prompt. `plasbench` runs this PlasBench folder; `git` works when Git for Windows is installed."),
                "winps": ("Windows PowerShell, started from Ubuntu: Windows programs and files. `plasbench` calls back into Ubuntu and runs this PlasBench "
                          "folder; the Ubuntu tools are not on its PATH."),
                "wingit": ("Git Bash (Windows), started from Ubuntu: Windows' bash and git, without the Ubuntu tools. `plasbench` calls back into Ubuntu and "
                           "runs this PlasBench folder."),
                "posix": ("Git Bash: bash and git on Windows, without the WSL tools. `plasbench` runs this PlasBench folder."
                          if IS_WIN else
                          "Your login shell, with the plasbench environment's tools and git on PATH. `plasbench` runs this "
                          "PlasBench folder.")}.get(self.shell, "") + git

    def _git_here(self) -> bool:
        path = os.pathsep.join([os.environ.get("PATH", "")] + git_path_dirs())
        return bool(shutil.which("git", path=path))

    def state(self, block: bool = True) -> dict:
        """What the Terminal tab shows. With block=False a probe that has not finished (it runs in the background) answers {'pending': true} so the page asks again."""
        p, ready = current_probe(block=block, wait=0.0 if block else 1.0)
        if not ready:
            return {"pending": True, "shell": "", "shell_label": "", "shells": [], "unavailable": [], "cwd": str(self.cwd), "shown_cwd": self.shown_cwd(),
                    "prompt": "", "roots": [str(r) for r in self.roots()], "enabled": False, "about": "", "history": [], "note": "looking for shells"}
        shells = available_shells(p)
        if self._shell is not None and self._shell not in shells and shells:
            self._shell = None                # the shell it was on is gone (a distribution was removed): back to the default
        shell = self.shell
        return {"pending": False, "shell": shell, "shell_label": shell_label(shell, p),
                "shells": [{"id": k, "label": shell_label(k, p), "what": v} for k, v in shells.items()],
                "unavailable": [dict(id=k, **v) for k, v in unavailable_shells(p).items()],
                "cwd": str(self.cwd), "shown_cwd": self.shown_cwd(), "prompt": self.prompt(),
                "roots": [str(r) for r in self.roots()], "enabled": bool(shells), "about": self.about(),
                "history": (self.history_by.get(shell) or [])[-50:],
                "note": "" if shells else "no shell was found on this computer"}
