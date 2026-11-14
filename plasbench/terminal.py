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


def wsl_available() -> bool:
    if not IS_WIN:
        return False
    if "ok" not in _wsl_cache:
        exe = _which_wsl()
        ok = False
        if exe:
            try:
                ok = subprocess.run([exe, "-e", "true"], capture_output=True, timeout=60,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        _wsl_cache["ok"] = ok
    return _wsl_cache["ok"]


def powershell_argv():
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return [found, "-NoProfile", "-NonInteractive", "-Command"]
    return None


def posix_argv():
    cands = [os.environ.get("SHELL", "")] + (["zsh"] if sys.platform == "darwin" else []) + ["bash", "sh"]
    for c in cands:
        if not c:
            continue
        found = c if os.path.isabs(c) and os.path.exists(c) else shutil.which(Path(c).name)
        if found:
            return [found, "-lc"]
    return None


def available_shells() -> dict:
    out = {}
    if wsl_available():
        out["wsl"] = "Ubuntu (WSL): where the benchmark tools run on Windows"
    if posix_argv():
        out["posix"] = ("a POSIX shell on Windows (Git Bash): no access to the WSL tools" if IS_WIN
                        else "the login shell: the plasbench environment's tools are on its PATH")
    if powershell_argv():
        out["powershell"] = "PowerShell: drive letters, Explorer, Windows programs" if IS_WIN else "PowerShell (pwsh)"
    return out


def default_shell() -> str:
    shells = available_shells()
    for name in (("wsl", "powershell", "posix") if IS_WIN else ("posix", "powershell")):
        if name in shells:
            return name
    return ""


def shell_label(name: str) -> str:
    return {"wsl": "Ubuntu (WSL)", "posix": "Shell", "powershell": "PowerShell"}.get(name, name or "none")


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

    def __init__(self, root: Path, history_file: Path, workspace=None):
        self.root = Path(root).resolve()
        self.workspace = workspace          # a callable returning the current workspace folder (it can change)
        self.cwd = self.root
        self.shell = default_shell()
        self.history_file = Path(history_file)
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
        return f"{self.shown_cwd()}$"

    # ------------------------------------------------------------------------------------------- running
    def use_shell(self, name: str):
        shells = available_shells()
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
        if self.shell == "wsl":
            where = to_wsl_path(self.cwd)
            if not where:
                raise TerminalError(f"WSL cannot reach {self.cwd}; switch the terminal to PowerShell.")
            wroot = to_wsl_path(self.root) or ""
            # `plasbench` inside Ubuntu runs this same PlasBench folder with Ubuntu's Python, unless Ubuntu has its own.
            prelude = (f"command -v plasbench >/dev/null 2>&1 || plasbench() {{ python3 -m plasbench --project-root {_q(wroot)} \"$@\"; }}; "
                       if wroot else "")
            return [_which_wsl() or "wsl", "-e", "bash", "-lc", f"{prelude}cd {_q(where)} && {command}"]
        sh = posix_argv()
        if not sh:
            raise TerminalError("no shell was found on this computer")
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
            if parts[0].lower() in ("cd", "chdir", "set-location") and "&&" not in command and ";" not in command:
                self.set_cwd(parts[1] if len(parts) > 1 else "")
                self._record(command, 0, 0.0)
                return {"exit": 0, "output": str(self.cwd), "prompt": self.prompt(), "seconds": 0.0, "shell": self.shell}
            started = time.time()
            try:
                p = subprocess.run(self._argv(command), cwd=None if self.shell == "wsl" else str(self.cwd),
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                                   timeout=timeout, env=dict(os.environ, PLASBENCH_TERMINAL="1"),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                code, text = p.returncode, (p.stdout or "") + (p.stderr or "")
            except subprocess.TimeoutExpired:
                code, text = 124, f"(stopped after {timeout:g} s: start long work from the window's pages instead)"
            except OSError as exc:
                code, text = 127, str(exc)
            seconds = round(time.time() - started, 2)
            text = text.replace("\x00", "").replace("\r\n", "\n")
            if len(text) > MAX_OUTPUT:
                text = text[:MAX_OUTPUT] + f"\n... output cut at {MAX_OUTPUT} characters"
            self._record(command, code, seconds)
            return {"exit": code, "output": text, "prompt": self.prompt(), "seconds": seconds, "shell": self.shell}

    def _record(self, command: str, code: int, seconds: float):
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
        return {"wsl": "Ubuntu (WSL): where the benchmark tools live on Windows. `plasbench` runs this PlasBench folder.",
                "powershell": "PowerShell. `plasbench` runs this PlasBench folder.",
                "posix": ("Git Bash: a Windows shell without the WSL tools. `plasbench` runs this PlasBench folder." if IS_WIN
                          else "Your login shell, with the plasbench environment's tools on PATH. `plasbench` runs this PlasBench folder.")
                }.get(self.shell, "")

    def state(self) -> dict:
        shells = available_shells()
        return {"shell": self.shell, "shell_label": shell_label(self.shell),
                "shells": [{"id": k, "label": shell_label(k), "what": v} for k, v in shells.items()],
                "cwd": str(self.cwd), "shown_cwd": self.shown_cwd(), "prompt": self.prompt(),
                "roots": [str(r) for r in self.roots()], "enabled": bool(shells), "about": self.about(),
                "history": self.history[-50:],
                "note": "" if shells else "no shell was found on this computer"}
