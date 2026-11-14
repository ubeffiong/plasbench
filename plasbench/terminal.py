"""The Terminal tab of the PlasBench window's footer console (after GenoSuv's terminal.py).

What it is for: the things a wizard never covers. You can list what a run produced, look inside a log, rerun one
`plasbench` subcommand with an unusual option, or tidy up after a failed attempt. Commands run in the PlasBench folder,
or a folder inside it or inside the studies workspace. Each one is recorded in ~/.plasbench/ui/terminal_history.jsonl.
The command line itself stays fully supported: this is the same shell, just next to the window.

Which shell:
  * Linux, macOS, and Linux inside WSL: the login shell. PATH already holds the plasbench environment's tools, because
    `plasbench ui` puts them there. `plasbench` is defined as a function that runs this very PlasBench folder.
  * Windows (native): Ubuntu (WSL) when it is installed, because the benchmark tools only exist there. PowerShell is
    offered for the Windows side.
  * PowerShell is offered anywhere `pwsh` exists.

What it is NOT: a sandbox. A command can do anything you can. Four limits are enforced here:
  * every request needs this session's key;
  * the server only listens on 127.0.0.1;
  * `cd` stays inside the PlasBench folder or the workspace;
  * output is capped, and a command is stopped after a timeout.
Commands get no keyboard input (stdin is empty), so an interactive program ends instead of hanging. Run interactive
or long jobs from the window's pages instead; their questions can be answered in the Job output tab.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path, PureWindowsPath

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


def wsl_available() -> bool:
    return bool(wsl_distros())


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


def available_shells() -> dict:
    """{id: what it reaches}, in the order they are offered. On Windows: each WSL distribution (where the benchmark
    tools run), Git Bash, PowerShell. Elsewhere: the login shell, and PowerShell if pwsh is installed."""
    out = {}
    for d in wsl_distros():
        out["wsl:" + d["name"]] = (f"{d['name']} (Linux in WSL{', the default distribution' if d['default'] else ''}): "
                                   "where the benchmark tools, conda and git run on Windows")
    if posix_argv():
        out["posix"] = ("Git Bash (Git for Windows): bash and git on Windows; no access to the WSL tools" if IS_WIN
                        else "your login shell: the plasbench environment's tools and git are on its PATH")
    if powershell_argv():
        out["powershell"] = "PowerShell: Windows programs, drive letters, and git when Git for Windows is installed" if IS_WIN \
            else "PowerShell (pwsh)"
    return out


def default_shell() -> str:
    shells = available_shells()
    if IS_WIN:
        for name in shells:                   # the default WSL distribution comes first
            if name.startswith("wsl:"):
                return name
        for name in ("posix", "powershell"):
            if name in shells:
                return name
        return ""
    for name in ("posix", "powershell"):
        if name in shells:
            return name
    return ""


def shell_label(name: str) -> str:
    if name.startswith("wsl:"):
        return f"{name[4:]} (WSL)"
    return {"wsl": "Ubuntu (WSL)", "posix": "Git Bash" if IS_WIN else Path((posix_argv() or ["bash"])[0]).stem.capitalize(),
            "powershell": "PowerShell"}.get(name, name or "none")


def to_msys_path(p) -> str:
    """C:\\x\\y -> /c/x/y, the form Git Bash expects."""
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


def _psq(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


class Terminal:
    """One terminal per window, with its own current folder inside the PlasBench folder or the workspace."""

    def __init__(self, root: Path, history_file: Path, workspace=None, on_record=None):
        self.root = Path(root).resolve()
        self.workspace = workspace          # a callable returning the current workspace folder (it can change)
        self.cwd = self.root
        self.shell = default_shell()
        self.history_file = Path(history_file)
        self.on_record = on_record          # called with each command's record (the window's session log)
        self.history: list = []
        self.lock = threading.Lock()
        try:
            for line in self.history_file.read_text(encoding="utf-8").splitlines()[-50:]:
                self.history.append(json.loads(line)["command"])
        except (OSError, ValueError, KeyError):
            pass

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
        if self.shell == "powershell":
            return f"PS {self.shown_cwd()}>"
        if self.shell.startswith("wsl:"):
            return f"{self.shell[4:]}:{self.shown_cwd()}$"
        return f"{self.shown_cwd()}$"

    # ------------------------------------------------------------------------------------------- running
    def use_shell(self, name: str):
        shells = available_shells()
        if name == "wsl":                     # the default distribution
            name = next((k for k in shells if k.startswith("wsl:")), name)
        if name not in shells:
            raise TerminalError(f"'{name}' is not available here; this computer offers: " + (", ".join(shells) or "none"))
        self.shell = name

    def _argv(self, command: str) -> list:
        py, root = sys.executable, str(self.root)
        if self.shell == "powershell":
            ps = powershell_argv()
            if not ps:
                raise TerminalError("PowerShell was not found")
            prelude = f"function plasbench {{ & {_psq(py)} -m plasbench --project-root {_psq(root)} @args }}; "
            return ps + [prelude + command]
        if self.shell.startswith("wsl"):
            distro = self.shell[4:] if self.shell.startswith("wsl:") else ""
            where = to_wsl_path(self.cwd)
            if not where:
                raise TerminalError(f"WSL cannot reach {self.cwd}; switch the terminal to PowerShell.")
            wroot = to_wsl_path(self.root) or ""
            # `plasbench` inside Ubuntu runs this same PlasBench folder with Ubuntu's Python, unless Ubuntu has its own.
            prelude = (f"command -v plasbench >/dev/null 2>&1 || plasbench() {{ python3 -m plasbench --project-root {_q(wroot)} \"$@\"; }}; "
                       if wroot else "")
            return ([_which_wsl() or "wsl"] + (["-d", distro] if distro else [])
                    + ["-e", "bash", "-lc", f"{prelude}cd {_q(where)} && {command}"])
        sh = posix_argv()
        if not sh:
            raise TerminalError("no shell was found on this computer")
        if IS_WIN:                            # Git Bash wants /c/... paths
            py, root = to_msys_path(py), to_msys_path(root)
        prelude = f"plasbench() {{ {_q(py)} -m plasbench --project-root {_q(root)} \"$@\"; }}; "
        return sh + [prelude + command]

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
            try:
                env = dict(os.environ, PLASBENCH_TERMINAL="1")
                extra = [d for d in git_path_dirs() if d not in env.get("PATH", "").split(os.pathsep)]
                if extra:                     # git (and Git Bash's tools) on PATH for PowerShell and Git Bash
                    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + extra)
                p = subprocess.run(self._argv(command), cwd=None if self.shell.startswith("wsl") else str(self.cwd),
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                                   timeout=timeout, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                code, text = p.returncode, (p.stdout or "") + (p.stderr or "")
            except subprocess.TimeoutExpired:
                code, text = 124, f"(stopped after {timeout:g} s: start long work from the window's pages instead)"
            except OSError as exc:
                code, text = 127, str(exc)
            seconds = round(time.time() - started, 2)
            text = text.replace("\x00", "").replace("\r\n", "\n")
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
                                "command": command[:2000], "exit": code, "seconds": seconds})
            except Exception:  # noqa: BLE001 - the record never stops a command
                pass
        self.history.append(command)
        del self.history[:-200]
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "shell": self.shell,
                                         "cwd": str(self.cwd), "command": command[:2000], "exit": code,
                                         "seconds": seconds}) + "\n")
        except OSError:
            pass

    def about(self) -> str:
        git = "" if self.shell.startswith("wsl") or self._git_here() else \
            " Git was not found: Set up this computer > Git > Install (optional)."
        if self.shell.startswith("wsl"):
            return (f"{shell_label(self.shell)}: Linux, where the benchmark tools live on Windows; git, bash and conda run "
                    "here. `plasbench` runs this PlasBench folder.")
        return {"powershell": "PowerShell. `plasbench` runs this PlasBench folder; `git` works when Git for Windows is installed.",
                "posix": ("Git Bash: bash and git on Windows, without the WSL tools. `plasbench` runs this PlasBench folder."
                          if IS_WIN else
                          "Your login shell, with the plasbench environment's tools and git on PATH. `plasbench` runs this "
                          "PlasBench folder.")}.get(self.shell, "") + git

    def _git_here(self) -> bool:
        path = os.pathsep.join([os.environ.get("PATH", "")] + git_path_dirs())
        return bool(shutil.which("git", path=path))

    def state(self) -> dict:
        shells = available_shells()
        return {"shell": self.shell, "shell_label": shell_label(self.shell),
                "shells": [{"id": k, "label": shell_label(k), "what": v} for k, v in shells.items()],
                "cwd": str(self.cwd), "shown_cwd": self.shown_cwd(), "prompt": self.prompt(),
                "roots": [str(r) for r in self.roots()], "enabled": bool(shells), "about": self.about(),
                "history": self.history[-50:],
                "note": "" if shells else "no shell was found on this computer"}
