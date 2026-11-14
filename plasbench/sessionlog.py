"""The session log of the PlasBench window, and the run script made from it (after GenoSuv's session log).

A session is one start of `plasbench ui`. Everything that happens in it is one timestamped line in
~/.plasbench/ui/sessions.jsonl: the window started or stopped, a command started from a page, how it ended,
answers typed into its questions, a cancel, commands typed in the Terminal tab, settings, workspace and study
changes. The console's Session log tab shows it as readable lines.

`script()` turns a session into a bash script that repeats it: every command started from the window's pages, and
every command typed in its Terminal, in order and in the folder each ran in. Commands that failed or were
cancelled are kept as comments. So are PowerShell commands and the answers typed into questions, because they cannot
be replayed safely. The script is a record, so read it before you run it.

Secrets: answers typed with "hide" are masked here as in the job log. Settings record the setting's name, and its
value only when the name does not look like a key, token, secret or password.
"""
from __future__ import annotations

import json
import re
import shlex
import threading
import time
from pathlib import Path, PureWindowsPath

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASS\b", re.I)
MAX_READ = 5 * 2**20          # read at most the last 5 MB of the log


class SessionLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.session = time.strftime("%Y%m%d-%H%M%S")
        self.lock = threading.Lock()

    # ---------------------------------------------------------------------------------------------- writing
    def event(self, kind: str, **fields) -> dict:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "session": self.session, "kind": kind}
        rec.update({k: v for k, v in fields.items() if v is not None})
        try:
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(rec, default=str) + "\n")
        except OSError:
            pass                       # the log is a record, never a reason for a command to fail
        return rec

    def settings(self, changes: dict):
        shown = {k: ("(hidden)" if SECRET_NAME.search(k) and v not in (None, "") else
                     "(default)" if v in (None, "") else str(v)) for k, v in changes.items()}
        self.event("settings", changes=shown)

    # ---------------------------------------------------------------------------------------------- reading
    def _read(self) -> list:
        try:
            with open(self.path, "rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - MAX_READ))
                raw = handle.read().decode("utf-8", "replace")
        except OSError:
            return []
        out = []
        for line in raw.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                 # the first line of a cut read, or a torn write
        return out

    def sessions(self) -> list:
        """[{id, start, end, events}] newest first."""
        seen: dict = {}
        for e in self._read():
            s = seen.setdefault(e.get("session", "?"), {"id": e.get("session", "?"), "start": e["t"], "end": e["t"], "events": 0})
            s["end"] = e["t"]
            s["events"] += 1
        if self.session not in seen:
            seen[self.session] = {"id": self.session, "start": "", "end": "", "events": 0}
        return sorted(seen.values(), key=lambda s: s["id"], reverse=True)

    def events(self, session: str = "", limit: int = 500) -> list:
        session = session or self.session
        return [e for e in self._read() if e.get("session") == session][-max(1, min(int(limit), 5000)):]

    # ---------------------------------------------------------------------------------------------- the script
    def script(self, root: Path, session: str = "") -> str:
        session = session or self.session
        events = self.events(session, 5000)
        root = str(Path(root).resolve())
        first = events[0]["t"] if events else time.strftime("%Y-%m-%d %H:%M:%S")
        last = events[-1]["t"] if events else first
        lines = [
            "#!/usr/bin/env bash",
            f"# PlasBench session {session} ({first} to {last}), saved from the PlasBench window.",
            "#",
            "# Repeats this session: each command started from the window's pages, and each command typed in its",
            "# Terminal tab, in order, in the folder it ran in. Commands that failed or were cancelled, PowerShell",
            "# commands, and the answers typed into a command's questions are kept as comments.",
            "# Read it before running it: it is a record of what was done, not a tested pipeline.",
            "#",
            "#   bash " + f"plasbench-session-{session}.sh",
            "set -uo pipefail",
            "",
            f"PB={shlex.quote(root)}",
            'cd "$PB" || exit 1',
            '# `plasbench` here is this PlasBench folder, as in the window.',
            'command -v plasbench >/dev/null 2>&1 || plasbench() { python3 -m plasbench --project-root "$PB" "$@"; }',
            "",
        ]
        ends = {e.get("job"): e for e in events if e["kind"] == "job_end"}
        n_active = 0
        for e in events:
            kind, when = e["kind"], e["t"][11:]
            if kind == "job_start":
                end = ends.get(e.get("job"))
                state = end["state"] if end else "still running when this script was saved"
                how = f"{state}" + (f", exit {end.get('exit')}, {end.get('seconds')} s" if end else "")
                lines.append(f"# {when}  {e.get('label', '')}  ({how})")
                env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in (e.get("env") or {}).items())
                cmd = (env + " " if env else "") + e.get("command", "")
                cwd = e.get("cwd")
                if cwd and Path(cwd).resolve() != Path(root):
                    cmd = f"(cd {shlex.quote(cwd)} && {cmd})"
                if end and end["state"] == "done" or not end:
                    lines.append(cmd)
                    n_active += 1
                else:
                    lines.append(_comment(cmd))
            elif kind == "job_input":
                lines.append(f"#   answered: {e.get('answer', '')}")
            elif kind == "terminal":
                shell, code = e.get("shell", ""), e.get("exit", 0)
                cmd = e.get("command", "")
                lines.append(f"# {when}  terminal ({e.get('shell_label', shell)})" + (f", exit {code}" if code else ""))
                if shell == "powershell":
                    lines.append(_comment("PowerShell: " + cmd))
                    continue
                if re.match(r"^(cd|chdir)(\s|$)", cmd):
                    lines.append(f"#   (the terminal moved to {e.get('cwd', '')})")
                    continue
                cwd = e.get("cwd", root)
                if shell == "wsl":
                    cwd = _wsl(cwd) or cwd
                full = cmd if Path(str(cwd)) == Path(root) and shell != "wsl" else f"(cd {shlex.quote(str(cwd))} && {cmd})"
                if code:
                    lines.append(_comment(full))
                else:
                    lines.append(full)
                    n_active += 1
            elif kind == "settings":
                ch = ", ".join(f"{k}={v}" for k, v in (e.get("changes") or {}).items())
                lines.append(f"# {when}  settings saved to config/local.env: {ch}")
            elif kind == "workspace":
                lines.append(f"# {when}  workspace set to {e.get('path', '')}")
                lines.append(f"export PLASBENCH_WORKSPACE={shlex.quote(str(e.get('path', '')))}")
            elif kind == "study_created":
                lines.append(f"# {when}  study folder created: {e.get('path', '')}")
            elif kind in ("server_start", "server_stop", "quit"):
                lines.append(f"# {when}  {describe(e)}")
        lines += ["", f"# {n_active} command(s) to run; the rest are comments.", ""]
        return "\n".join(lines)


def _comment(text: str) -> str:
    """Every line commented out (a multi-line command must not run half of itself)."""
    return "\n".join("# " + line for line in str(text).splitlines() or [""])


def _wsl(path: str):
    w = PureWindowsPath(str(path))
    if not w.drive or not w.drive.endswith(":"):
        return None
    return "/mnt/" + w.drive[0].lower() + "/" + "/".join(w.parts[1:])


def describe(e: dict) -> str:
    """One readable sentence per event (the Session log tab uses the same wording)."""
    k = e.get("kind")
    if k == "server_start":
        return f"PlasBench {e.get('version', '')} started for {e.get('root', '')}"
    if k == "server_stop":
        return "PlasBench stopped"
    if k == "quit":
        return "Quit pressed" + (" (running jobs were stopped)" if e.get("forced") else "")
    if k == "job_start":
        return f"started {e.get('label', '')}: {e.get('command', '')}"
    if k == "job_end":
        return f"{e.get('state', '')}: {e.get('label', '')} (exit {e.get('exit')}, {e.get('seconds')} s)"
    if k == "job_cancel":
        return f"cancel requested: {e.get('label', '')}"
    if k == "job_input":
        return f"answered {e.get('label', '')}: {e.get('answer', '')}"
    if k == "terminal":
        return f"$ {e.get('command', '')}" + (f"   (exit {e.get('exit')})" if e.get("exit") else "") + f"  · {e.get('seconds', 0)} s"
    if k == "settings":
        return "settings saved: " + ", ".join(f"{a}={b}" for a, b in (e.get("changes") or {}).items())
    if k == "workspace":
        return f"workspace set to {e.get('path', '')}"
    if k == "study_created":
        return f"study folder created: {e.get('path', '')}"
    return k + " " + " ".join(f"{a}={b}" for a, b in e.items() if a not in ("t", "session", "kind"))
