"""`plasbench stop` and the window's "Stop all PlasBench on this computer": end every PlasBench window server of this user, safely.

Why it exists: stale window servers and app windows can pile up (ports 8770 -> 8771 -> 8770, several app windows from one profile). Quit in a window stops only THAT server. This module is
the recovery tool for "everything PlasBench-related on this computer".

SAFETY RULES (they are the contract; test/test_stop_all.py checks each one)
  1. Only processes PlasBench ITSELF recorded are ever signalled, and only after they are verified: the pid exists, its command line is a PlasBench server (contains `plasbench` and a
     `ui`/`webui` argument), and, when both are known, the process start time agrees with the recorded start (a reused pid fails this). The check is repeated right before every signal.
  2. Never by name pattern, never by port number alone: a program that holds a PlasBench port is REPORTED ("port 8770 is held by another program (name, pid)") and left alone. wslrelay, Docker,
     browsers that PlasBench did not open: untouched.
  3. Polite first, escalate after a grace period: ask the server to quit over its own quit route (keeping runs going), then SIGTERM (Windows: taskkill without /F), and SIGKILL (taskkill /F) only
     after the grace (default 10 s) and only if the same verified process is still there.
  4. Runs and jobs are left running unless `--runs`/the red switch says otherwise. A run is cancelled by signalling its recorded process group after verifying it is a PlasBench run, and a
     `stopped_by_user` event is recorded. Finished work is kept and the run can be resumed.
  5. Windows (`--windows`): only browser processes whose command line carries `--app=<a PlasBench server's address>` AND the PlasBench profile folder (`...PlasBench/app-window`).
  6. No sudo; this user's processes only (a process of another user is never signalled; a root caller does not widen that); never this process or its own process group.
  7. Every stop is written to ~/.plasbench/ui/stop.log and sessions.jsonl (a `stop` event with what was ended).
  8. `wsl --shutdown` (WSL only; opt-in; never the default) ends EVERY WSL distribution and Docker Desktop's engine. It needs the runs switch when runs are active, and it is launched from
     the Windows side, detached, after a delay, only after the servers and runs of the chosen scope were stopped.

Process listing, signalling, time, the quit request and the Windows launcher are injectable (`Procs`, `Env`), so tests use fakes. Standard library only (psutil is not needed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

GRACE_SECONDS = 10.0
POLITE_SECONDS = 5.0
KILL_WAIT_SECONDS = 3.0
START_TOLERANCE = 1800.0         # seconds the recorded start and the process start may differ: the wall clock jumps after a sleep (8 minutes were seen on WSL2), so only a clearly different start counts as a reused pid
WSL_DELAY_SECONDS = 3
EXIT_OK, EXIT_USAGE, EXIT_LEFT = 0, 2, 3
DEFAULT_PORTS = range(8770, 8790)
WSL_MANUAL = "wsl --shutdown"
_SERVER_WORDS = re.compile(r"(^|[\s\"'/\\])(ui|webui)([\s\"']|$)|plasbench[\\/]webui|plasbench\.webui")


# ------------------------------------------------------------------------------------------------------------------------------ process backends
class Procs:
    """Process table and signalling. A process entry: {"pid", "ppid", "pgid", "name", "cmdline", "start" (epoch or None), "uid"}."""
    name = "base"

    def list(self) -> dict:
        raise NotImplementedError

    def get(self, pid):
        try:
            return self.list().get(int(pid))
        except (TypeError, ValueError):
            return None

    def alive(self, pid) -> bool:
        return self.get(pid) is not None

    def signal(self, pid, force: bool = False) -> bool:
        raise NotImplementedError

    def signal_group(self, pgid, force: bool = False) -> bool:
        return self.signal(pgid, force)

    def current_uid(self):
        return None


class LinuxProcs(Procs):
    """/proc: Linux and WSL."""
    name = "linux"

    def __init__(self, proc="/proc"):
        self.proc = proc

    def _boot(self) -> float:
        try:
            for line in Path(self.proc, "stat").read_text().splitlines():
                if line.startswith("btime "):
                    return float(line.split()[1])
        except (OSError, ValueError, IndexError):
            pass
        return 0.0

    def _hz(self) -> float:
        try:
            return float(os.sysconf("SC_CLK_TCK"))
        except (AttributeError, ValueError, OSError):
            return 100.0

    def _entry(self, pid: int, boot: float, hz: float):
        base = Path(self.proc, str(pid))
        try:
            stat = (base / "stat").read_bytes().decode("utf-8", "replace")
            rest = stat.rsplit(")", 1)[1].split()
            cmd = (base / "cmdline").read_bytes().decode("utf-8", "replace").replace("\0", " ").strip()
            name = stat.split("(", 1)[1].rsplit(")", 1)[0]
            if rest[0] == "Z":
                return None
            try:
                uid = base.stat().st_uid
            except OSError:
                uid = None
            return {"pid": pid, "ppid": int(rest[1]), "pgid": int(rest[2]), "name": name, "cmdline": cmd or f"[{name}]",
                    "start": (boot + int(rest[19]) / hz) if boot else None, "uid": uid}
        except (OSError, IndexError, ValueError):
            return None

    def list(self) -> dict:
        boot, hz, out = self._boot(), self._hz(), {}
        try:
            names = [n for n in os.listdir(self.proc) if n.isdigit()]
        except OSError:
            return out
        for n in names:
            e = self._entry(int(n), boot, hz)
            if e:
                out[e["pid"]] = e
        return out

    def get(self, pid):
        try:
            return self._entry(int(pid), self._boot(), self._hz())
        except (TypeError, ValueError):
            return None

    def signal(self, pid, force=False) -> bool:
        try:
            os.kill(int(pid), signal.SIGKILL if force else signal.SIGTERM)
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def signal_group(self, pgid, force=False) -> bool:
        try:
            os.killpg(int(pgid), signal.SIGKILL if force else signal.SIGTERM)
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def current_uid(self):
        return os.getuid() if hasattr(os, "getuid") else None


class MacProcs(LinuxProcs):
    """`ps` (macOS and other BSDs); signalling is the same as on Linux."""
    name = "mac"

    def __init__(self, run=subprocess.run):
        self.run = run

    def list(self) -> dict:
        out = {}
        try:
            done = self.run(["ps", "-axo", "pid=,ppid=,pgid=,uid=,lstart=,command="], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return out
        for line in (done.stdout or "").splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\w{3}\s+\w{3}\s+\d+\s+[\d:]{8}\s+\d{4})\s+(.*)$", line)
            if not m:
                continue
            try:
                start = time.mktime(time.strptime(re.sub(r"\s+", " ", m.group(5)), "%a %b %d %H:%M:%S %Y"))
            except ValueError:
                start = None
            cmd = m.group(6)
            out[int(m.group(1))] = {"pid": int(m.group(1)), "ppid": int(m.group(2)), "pgid": int(m.group(3)), "uid": int(m.group(4)),
                                    "name": cmd.split()[0].rsplit("/", 1)[-1] if cmd else "", "cmdline": cmd, "start": start}
        return out

    def get(self, pid):
        try:
            return self.list().get(int(pid))
        except (TypeError, ValueError):
            return None


class WindowsProcs(Procs):
    """Windows processes: command lines from PowerShell Get-CimInstance Win32_Process; taskkill without /F first (asks the program to close), /F to force. Used on native Windows, and
    from WSL (through interop) to look at the Windows browser windows PlasBench opened."""
    name = "windows"
    SCRIPT = ("Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{p=$_.ProcessId; pp=$_.ParentProcessId; n=$_.Name; c=$_.CommandLine; "
              "t=([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds()} } | ConvertTo-Json -Compress")

    def __init__(self, powershell=None, taskkill=None, run=subprocess.run):
        self.powershell, self.taskkill, self.run = powershell, taskkill or "taskkill", run

    def list(self) -> dict:
        out = {}
        if not self.powershell:
            return out
        from . import native_picker
        try:
            done = self.run(native_picker.encoded_argv(self.powershell, self.SCRIPT), capture_output=True, text=True, timeout=60)
            rows = json.loads(done.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return out
        if isinstance(rows, dict):
            rows = [rows]
        for r in rows:
            try:
                pid = int(r["p"])
            except (KeyError, TypeError, ValueError):
                continue
            t = r.get("t")
            out[pid] = {"pid": pid, "ppid": r.get("pp"), "pgid": None, "name": r.get("n") or "", "cmdline": r.get("c") or "",
                        "start": (t / 1000.0) if isinstance(t, (int, float)) else None, "uid": None}
        return out

    def _kill(self, args, force):
        try:
            return self.run([self.taskkill] + args + (["/F"] if force else []), capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    def signal(self, pid, force=False) -> bool:
        return self._kill(["/PID", str(int(pid))], force)

    def signal_group(self, pgid, force=False) -> bool:
        return self._kill(["/T", "/PID", str(int(pgid))], force)


def platform_kind(platform=None) -> str:
    from . import native_picker
    return native_picker._platform(platform)


def default_procs(platform=None, run=subprocess.run) -> Procs:
    plat = platform_kind(platform)
    if plat == "windows":
        from . import native_picker
        exe, _ = native_picker.find_powershell(dict(os.environ), shutil.which, plat="windows")
        return WindowsProcs(exe, "taskkill", run)
    if plat == "mac":
        return MacProcs(run)
    return LinuxProcs()


def windows_side_procs(platform=None, env=None, which=shutil.which, run=subprocess.run, exists=os.path.exists):
    """Where the browser windows PlasBench opened live: native Windows, the Windows host from WSL (through interop), or the local process table (Linux, macOS)."""
    plat = platform_kind(platform)
    env = dict(os.environ if env is None else env)
    if plat == "windows":
        return default_procs(plat, run)
    if plat == "wsl":
        from . import native_picker
        exe, _ = native_picker.find_powershell(env, which, exists, run, plat="wsl")
        if not exe:
            return None
        tk = which("taskkill.exe") or ("/mnt/c/Windows/System32/taskkill.exe" if exists("/mnt/c/Windows/System32/taskkill.exe") else None)
        return WindowsProcs(exe, tk or "taskkill.exe", run)
    return default_procs(plat, run)


# ------------------------------------------------------------------------------------------------------------------------------ verification
def is_server_cmdline(cmd: str) -> bool:
    """A PlasBench window server: the command line names plasbench AND runs its `ui` (or webui) command (`python -m plasbench ui`, `plasbench ui --port ..`, the restart bootstrap)."""
    low = (cmd or "").lower()
    return "plasbench" in low and bool(_SERVER_WORDS.search(low))


def is_runner_cmdline(cmd: str) -> bool:
    low = (cmd or "").lower()
    return "plasbench" in low and "jobrunner" in low


def is_run_cmdline(cmd: str) -> bool:
    """A PlasBench run started from a terminal: scripts/run_all.sh, one of its stage scripts, or `plasbench run|demo|...`."""
    low = (cmd or "").lower().replace("\\", "/")
    return "run_all" in low or bool(re.search(r"scripts/0\d_[a-z_]+\.sh", low)) or bool(re.search(r"plasbench\S*\s.*\b(run|demo|reconstruct|depth-ladder|read-quality-ladder)\b", low))


def start_agrees(recorded, actual, tolerance=START_TOLERANCE) -> bool:
    """True when either start time is unknown or they are within `tolerance` seconds (a reused pid started at another time)."""
    if recorded in (None, "") or actual is None:
        return True
    try:
        return abs(float(recorded) - float(actual)) <= tolerance
    except (TypeError, ValueError):
        return True


def _shown_name(entry) -> str:
    return str((entry or {}).get("name") or str((entry or {}).get("cmdline", "")).split(" ")[0] or "unknown")[:60]


def verify_server(rec: dict, procs: Procs):
    """(ok, reason, process entry). Used before the plan and again before every signal."""
    try:
        pid = int(rec.get("pid"))
    except (TypeError, ValueError):
        return False, "the record has no process id", None
    entry = procs.get(pid)
    if entry is None:
        return False, f"process {pid} is gone", None
    uid = procs.current_uid()
    if uid is not None and entry.get("uid") is not None and entry["uid"] != uid:
        return False, f"process {pid} belongs to another user", entry
    if not is_server_cmdline(entry.get("cmdline", "")):
        return False, f"process {pid} is now another program ({_shown_name(entry)}), not a PlasBench window server (the pid was reused)", entry
    if not start_agrees(rec.get("started"), entry.get("start")):
        return False, f"process {pid} started at a different time than the recorded server (the pid was reused)", entry
    return True, "", entry


def own_pids() -> set:
    out = {os.getpid()}
    if hasattr(os, "getpgrp"):
        out.add(os.getpgrp())
    return out


# ------------------------------------------------------------------------------------------------------------------------------ environment
class Env:
    """Everything the plan and the execution touch outside the process table, replaceable in tests."""

    def __init__(self, procs=None, win_procs=None, clock=time.time, sleep=time.sleep, ask=None, probe=None, listeners=None, ui_homes=None, ports=None, platform=None,
                 run=subprocess.run, launcher=None, which=shutil.which, environ=None, exists=os.path.exists, self_pid=None, roots=None, cancel_job=None, now_text=None, interop=None):
        self.environ = dict(os.environ if environ is None else environ)
        self.platform = platform_kind(platform)
        self.procs = procs or default_procs(self.platform, run)
        self._win_procs, self._win_given = win_procs, win_procs is not None
        self.clock, self.sleep, self.run, self.which, self.exists = clock, sleep, run, which, exists
        self.self_pid = self_pid
        self.roots = list(roots or [])
        self._ask, self._probe, self._listeners, self._homes, self._ports = ask, probe, listeners, ui_homes, ports
        self.launcher, self.cancel_job, self.interop = launcher, cancel_job, interop
        self.now_text = now_text or (lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def win_procs(self):
        if not self._win_given:
            self._win_procs = windows_side_procs(self.platform, self.environ, self.which, self.run, self.exists)
            self._win_given = True
        return self._win_procs

    def ask(self, url, route, body=None, timeout=4.0):
        if self._ask:
            return self._ask(url, route, body)
        from . import webui
        return webui._call_old_server(url, route, body, timeout)

    def probe(self, port):
        if self._probe:
            return self._probe(port)
        from . import webui
        return webui._page_seen_of(port)

    def listeners(self, port):
        if self._listeners:
            return self._listeners(port)
        from . import webui
        return webui.port_listeners(port, self.run)

    def ui_homes(self) -> list:
        if self._homes is not None:
            return [Path(h) for h in self._homes]
        override = self.environ.get("PLASBENCH_STOP_HOMES")      # a test hook: only these UI homes
        if override:
            return [Path(h) for h in override.split(os.pathsep) if h]
        homes = []
        for h in (self.environ.get("PLASBENCH_UI_HOME"), str(Path.home() / ".plasbench" / "ui")):
            if h and Path(h) not in homes:
                homes.append(Path(h))
        return homes

    def ports(self):
        if self._ports is not None:
            return self._ports
        text = self.environ.get("PLASBENCH_STOP_PORTS", "").strip().lower()      # a test hook: "none" or "lo-hi"
        if text == "none":
            return []
        m = re.match(r"^(\d+)-(\d+)$", text)
        return range(int(m.group(1)), int(m.group(2)) + 1) if m else DEFAULT_PORTS

    def is_self(self, pid) -> bool:
        try:
            return int(pid) in own_pids() or (self.self_pid is not None and int(pid) == int(self.self_pid))
        except (TypeError, ValueError):
            return False


# ------------------------------------------------------------------------------------------------------------------------------ discovery
def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_records(env: Env) -> list:
    """Every server record (each home's servers/*.json and server.json), one per (home, port, pid): {"rec", "home", "files"}."""
    out, index = [], {}
    for home in env.ui_homes():
        for f in sorted((home / "servers").glob("*.json")) + [home / "server.json"]:
            rec = _read_json(f)
            if not isinstance(rec, dict):
                continue
            try:
                port = int(rec["port"])
            except (KeyError, TypeError, ValueError):
                continue
            key = (str(home), port, rec.get("pid"))
            if key in index:
                index[key]["files"].append(f)
                continue
            index[key] = {"rec": rec, "home": home, "files": [f]}
            out.append(index[key])
    return out


def _elapsed(started, now):
    try:
        return max(0, int(now - float(started)))
    except (TypeError, ValueError):
        return None


def human_elapsed(seconds) -> str:
    if seconds is None:
        return "unknown time"
    s = int(seconds)
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def plan_servers(env: Env, records) -> tuple:
    """(server targets, skips of other programs / unrecorded servers)."""
    now = env.clock()
    targets, skips, seen_ports = [], [], set()
    for item in records:
        rec, home = item["rec"], item["home"]
        port = int(rec["port"])
        seen_ports.add(port)
        ok, reason, entry = verify_server(rec, env.procs)
        alive, instance, _seen = env.probe(port)
        answers = bool(alive) and (rec.get("started") is None or str(rec.get("started")) == str(instance))
        t = {"kind": "server", "port": port, "pid": rec.get("pid"), "version": rec.get("version") or "", "started": rec.get("started"), "home": str(home), "root": rec.get("root"),
             "answers": answers, "windows_alive": None, "self": env.is_self(rec.get("pid")), "action": "stop", "reason": "", "stale_record": False, "verified": True,
             "_url": rec.get("url"), "_files": [str(f) for f in item["files"]]}
        if t["self"] or ok:
            if answers and rec.get("url"):
                t["windows_alive"] = (env.ask(rec["url"], "windows", None, 2.0) or {}).get("alive")
        else:
            t.update(verified=False, action="skip", reason=reason)
            t["stale_record"] = entry is None or "another program" in reason or "different time" in reason
            t["left_running"] = bool(answers) and not t["stale_record"]
            if t["stale_record"]:
                t["reason"] += "; the stale record is removed"
            elif answers:
                t["reason"] += "; a PlasBench server answers on this port but could not be verified, so it was not touched"
            for lst in env.listeners(port):
                if lst.get("pid") and lst["pid"] == rec.get("pid"):
                    continue
                skips.append({"kind": "listener", "port": port, "pid": lst.get("pid"), "name": lst.get("name"), "action": "skip",
                              "reason": f"port {port} is held by another program ({lst.get('name')}, pid {lst.get('pid')}); left alone"})
        t["started_text"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t["started"]))) if isinstance(t["started"], (int, float)) else ""
        t["elapsed_seconds"] = _elapsed(t["started"], now)
        targets.append(t)
    for port in env.ports():
        if port in seen_ports:
            continue
        alive, _instance, _seen = env.probe(port)
        if alive:
            skips.append({"kind": "server", "port": port, "pid": None, "name": "PlasBench", "action": "skip", "left_running": True, "verified": False,
                          "reason": f"port {port}: a PlasBench server answers but PlasBench has no record of it (started by an older version): use Quit in its window"})
    return targets, skips


def _tail_line(path, size=4096) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - size))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()[:110]
    return ""


def plan_jobs(env: Env) -> list:
    """Active jobs (detached runners) of every UI home: running or cancelling with a live runner."""
    from . import jobrunner
    now, out, seen = env.clock(), [], set()
    for home in env.ui_homes():
        jdir = home / "jobs"
        index = _read_json(jdir / "jobs.json")
        for job in index if isinstance(index, list) else []:
            if not isinstance(job, dict) or job.get("state") not in ("running", "cancelling") or "id" not in job:
                continue
            jid = str(job["id"])
            if (str(jdir), jid) in seen:
                continue
            seen.add((str(jdir), jid))
            st = jobrunner.run_state(str(jdir), jid)
            if not (jobrunner.is_alive(str(jdir), jid) or st["runner_alive"]):
                continue
            p = jobrunner.paths(str(jdir), jid)
            info = jobrunner.read_json(p["pid"]) or {}
            out.append({"kind": "job", "id": jid, "label": job.get("label") or jid, "started": job.get("started"), "elapsed_seconds": _elapsed(job.get("started"), now),
                        "step": _tail_line(p["log"]), "runner": info.get("runner") or job.get("pid"), "pgid": info.get("pgid"), "child": info.get("child"), "job_dir": str(jdir),
                        "home": str(home), "action": "keep", "reason": "", "verified": True})
    return out


def results_dirs(env: Env, records) -> list:
    roots = [Path(r) for r in env.roots]
    for item in records:
        r = item["rec"].get("root")
        if r and Path(r) not in roots:
            roots.append(Path(r))
    out = []
    for root in roots:
        cands = [root / "results"]
        try:
            from . import studies
            cands += [Path(s["results"]) for s in studies.list_studies(root) if s.get("available") is not False]
        except Exception:  # noqa: BLE001 - a workspace that cannot be read must not stop the stop command
            pass
        for c in cands:
            if c not in out and (c / ".run.lock").is_file():
                out.append(c)
    return out


def _lock_time(text):
    try:
        return time.mktime(time.strptime(str(text), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _tail_event(path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 8192))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("what") and e.get("event") == "heartbeat":
            return str(e["what"])[:110]
    return ""


def plan_terminal_runs(env: Env, records, jobs) -> list:
    """Runs started outside the window: found through RESULTS/.run.lock (pid + heartbeat). A run that is one of the window's own jobs is not listed twice."""
    from . import jobrunner
    now = env.clock()
    mine = {str(j.get(k)) for j in jobs for k in ("pgid", "child", "runner") if j.get(k)}
    out = []
    for results in results_dirs(env, records):
        lock = jobrunner.lock_holder(str(results))
        if not lock:
            continue
        pid, pgid = lock.get("pid"), lock.get("pgid") or ""
        if str(pid) in mine or (pgid and str(pgid) in mine):
            continue
        entry = env.procs.get(pid)
        started = _lock_time(lock.get("started"))
        t = {"kind": "run", "id": f"run:{results}", "label": results.parent.name if results.name == "results" else results.name, "results": str(results), "pid": pid, "pgid": pgid,
             "started": lock.get("started"), "elapsed_seconds": _elapsed(started, now), "step": _tail_event(results / "run_events.jsonl") or lock.get("what") or "",
             "action": "keep", "reason": "", "verified": False}
        if entry is None:
            continue
        if not is_run_cmdline(entry.get("cmdline", "")):
            t.update(action="skip", reason=f"process {pid} is not a PlasBench run (the pid was reused or the record is stale); not touched")
        elif entry.get("start") is not None and started is not None and entry["start"] > started + START_TOLERANCE:
            t.update(action="skip", reason=f"process {pid} started after the run lock was written (the pid was reused); not touched")
        elif env.is_self(pid) or (pgid and env.is_self(pgid)):
            t.update(action="skip", reason="this is the command itself; not touched")
        else:
            t["verified"] = True
        out.append(t)
    return out


def app_window_match(cmd: str, ports) -> int:
    """The port when `cmd` is a browser process PlasBench opened for one of `ports` (--app=http://127.0.0.1:PORT AND the PlasBench app-window profile), else 0. Text that merely
    contains 'plasbench' never matches, and neither does any other browser window."""
    if not cmd:
        return 0
    m = re.search(r"--app=\"?(https?://(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)[^\s\"]*)", cmd)
    if not m or int(m.group(2)) not in set(ports):
        return 0
    prof = re.search(r"--user-data-dir=\"?([^\"\n]*?app-window)\"?(?=\s|$)", cmd)
    if not prof or not prof.group(1).replace("\\", "/").lower().rstrip("/").endswith("plasbench/app-window"):
        return 0
    exe = cmd.strip().strip('"').replace("\\", "/").lower().split(" --", 1)[0]
    if not re.search(r"(msedge|chrome|chromium|brave)[^/ ]*?(\.exe)?\"?\s*$", exe):
        return 0
    return int(m.group(2))


def plan_windows(env: Env, ports) -> list:
    procs = env.win_procs
    if procs is None or not ports:
        return []
    out = []
    for pid, e in sorted(procs.list().items()):
        port = app_window_match(e.get("cmdline", ""), ports)
        if port:
            out.append({"kind": "window", "pid": pid, "name": e.get("name") or "browser", "port": port, "action": "close", "reason": "", "backend": procs.name})
    return out


# ------------------------------------------------------------------------------------------------------------------------------ WSL
def wsl_support(env: Env, interop=None, list_distros=True) -> dict:
    """Is `wsl --shutdown` offered here? Offered only inside WSL; available only with Windows interop and a findable powershell.exe."""
    out = {"offered": env.platform == "wsl", "available": False, "reason": "", "manual": f"{WSL_MANUAL}   (run it in Windows PowerShell)", "distributions": [], "distributions_note": "",
           "powershell": None, "wsl_exe": None}
    if not out["offered"]:
        out["reason"] = "not running inside WSL"
        return out
    from . import native_picker
    state = interop or env.interop or native_picker.interop_state(env.environ)
    if state.get("enabled") is False:
        out["reason"] = "Windows interop is off in this WSL (" + str(state.get("detail", "")).split(";")[0] + "), so PlasBench cannot start wsl.exe"
        return out
    exe, _tried = native_picker.find_powershell(env.environ, env.which, env.exists, env.run, plat="wsl")
    if not exe:
        out["reason"] = "powershell.exe could not be found from WSL, so PlasBench cannot start wsl.exe"
        return out
    wsl_exe = env.which("wsl.exe") or ("/mnt/c/Windows/System32/wsl.exe" if env.exists("/mnt/c/Windows/System32/wsl.exe") else None)
    out.update(available=True, powershell=exe, wsl_exe=wsl_exe)
    if list_distros:
        out["distributions"], out["distributions_note"] = list_distributions(env, wsl_exe)
    return out


def decode_wsl_text(raw) -> str:
    if isinstance(raw, str):
        return raw
    if b"\x00" in raw[:64]:
        return raw.decode("utf-16-le", "replace").lstrip("﻿")
    return raw.decode("utf-8", "replace")


def list_distributions(env: Env, wsl_exe) -> tuple:
    """(names, note) from `wsl.exe -l -v` (read-only; its output is UTF-16). An unreadable listing is a note, never an error."""
    note = "the list of distributions could not be read"
    if not wsl_exe:
        return [], note + " (wsl.exe was not found)"
    try:
        text = decode_wsl_text(env.run([wsl_exe, "-l", "-v"], capture_output=True, timeout=15).stdout or b"")
    except (OSError, subprocess.SubprocessError, ValueError):
        return [], note
    names = []
    for line in text.splitlines()[1:]:
        parts = line.replace("\x00", "").strip().lstrip("*").split()
        if len(parts) >= 3 and parts[-1].isdigit():
            names.append(f"{parts[0]} ({parts[1].lower()})")
    return (names, "") if names else ([], note)


def wsl_shutdown_argv(powershell) -> list:
    """The Windows-side launch: a hidden PowerShell that starts ANOTHER detached hidden PowerShell, which waits WSL_DELAY_SECONDS and runs `wsl.exe --shutdown`. Fixed text only."""
    inner = f"Start-Sleep -Seconds {WSL_DELAY_SECONDS}; & wsl.exe --shutdown"
    script = f"Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList '-NoProfile','-NonInteractive','-WindowStyle','Hidden','-Command','{inner}'"
    return [powershell, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]


def launch_wsl_shutdown(env: Env, powershell) -> dict:
    """Start the Windows-side shutdown. In tests `env.launcher` is a fake: a real `wsl --shutdown` is never run by the test suite."""
    argv = wsl_shutdown_argv(powershell)
    try:
        if env.launcher:
            env.launcher(argv)
        else:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return {"ok": True, "argv": argv, "delay_seconds": WSL_DELAY_SECONDS}
    except OSError as exc:
        return {"ok": False, "argv": argv, "error": str(exc)}


# ------------------------------------------------------------------------------------------------------------------------------ the plan
def build_plan(env: Env, runs=False, windows=False, wsl=False, wsl_info=False) -> dict:
    """What `plasbench stop` would do. `runs`: cancel active runs and jobs; `windows`: also close the browser windows PlasBench opened; `wsl`: also run wsl --shutdown (WSL only)."""
    records = read_records(env)
    servers, skips = plan_servers(env, records)
    jobs = plan_jobs(env)
    all_runs = jobs + plan_terminal_runs(env, records, jobs)
    for r in all_runs:
        if r["action"] == "keep" and runs and r.get("verified"):
            r["action"] = "cancel"
    ports = sorted({int(item["rec"]["port"]) for item in records})
    if wsl or wsl_info:   # only a window that shows the WSL choice (or --wsl-shutdown) looks at interop and lists the distributions
        support = wsl_support(env, list_distros=True)
    else:
        support = {"offered": env.platform == "wsl", "available": False, "reason": "", "manual": f"{WSL_MANUAL}   (run it in Windows PowerShell)", "distributions": [], "distributions_note": "", "powershell": None}
    return {"servers": servers, "skipped": skips, "runs": all_runs, "windows": plan_windows(env, ports) if windows else [],
            "wsl": dict({k: v for k, v in support.items() if k != "powershell"}, requested=bool(wsl)),
            "options": {"runs": bool(runs), "windows": bool(windows), "wsl_shutdown": bool(wsl)}, "platform": env.platform, "_powershell": support.get("powershell")}


def public(plan):
    """The plan without anything private (keys, record file names)."""
    if isinstance(plan, dict):
        return {k: public(v) for k, v in plan.items() if not str(k).startswith("_")}
    if isinstance(plan, list):
        return [public(v) for v in plan]
    return plan


def active_runs(plan) -> list:
    return [r for r in plan["runs"] if r.get("action") in ("keep", "cancel")]


# ------------------------------------------------------------------------------------------------------------------------------ execution
def _server_gone(env: Env, rec, seconds) -> bool:
    end = env.clock() + seconds
    while True:
        ok, _r, entry = verify_server(rec, env.procs)
        if entry is None or not ok:
            return True
        if env.clock() >= end:
            return False
        env.sleep(0.2)


def stop_server(env: Env, t: dict, grace=GRACE_SECONDS, polite=POLITE_SECONDS) -> dict:
    """Polite quit request, then SIGTERM (taskkill), then SIGKILL (taskkill /F), each only after re-verifying the process. {"ended": bool, "how": text}."""
    rec, steps = {"pid": t["pid"], "started": t.get("started")}, []
    if t.get("_url") and t.get("answers"):
        res = env.ask(t["_url"], "shutdown", {"keep": True, "stopping": True})   # keep: runs go on; stopping: its windows show the final state
        steps.append("asked it to quit" + ("" if (res or {}).get("ok") else " (no answer)"))
        if (res or {}).get("ok") and _server_gone(env, rec, polite):
            return {"ended": True, "how": "quit when asked"}
    for force, wait in ((False, grace), (True, KILL_WAIT_SECONDS)):
        ok, reason, entry = verify_server(rec, env.procs)
        if entry is None:
            return {"ended": True, "how": "; ".join(steps) or "already gone"}
        if not ok:
            return {"ended": False, "how": f"not signalled: {reason}"}
        if env.is_self(t["pid"]):
            return {"ended": False, "how": "this process; not signalled"}
        env.procs.signal(t["pid"], force)
        steps.append("sent " + ("a forced stop (kill)" if force else "a stop request (terminate)"))
        if _server_gone(env, rec, wait):
            return {"ended": True, "how": "; ".join(steps)}
    return {"ended": False, "how": "; ".join(steps) + "; it did not end"}


def remove_records(t: dict):
    for f in t.get("_files", []):
        rec = _read_json(f)
        if isinstance(rec, dict) and rec.get("pid") == t.get("pid"):
            try:
                os.unlink(f)
            except OSError:
                pass


def _write_run_event(results, event):
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()), "pid": os.getpid(), "event": event, "by": "plasbench stop"}
    try:
        with open(os.path.join(results, "run_events.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


def _stop_group(env: Env, pgid, pid, alive, grace) -> tuple:
    """TERM then KILL the process group (or only the pid when there is no group of its own) until `alive()` is false. (ended, how)."""
    if env.is_self(pid) or (pgid and env.is_self(pgid)):
        return False, "this process; not signalled"
    for force, wait in ((False, grace), (True, KILL_WAIT_SECONDS)):
        if not alive():
            return True, "ended"
        env.procs.signal_group(pgid, force) if pgid else env.procs.signal(pid, force)
        end = env.clock() + wait
        while env.clock() < end and alive():
            env.sleep(0.2)
        if not alive():
            return True, "ended (" + ("forced stop" if force else "stop request") + ")"
    return False, "it did not end"


def mark_job_cancelled(job_dir, job_id, now=None):
    """Write `cancelled` into the job's index and meta files (what the window reads), under the window's index lock, and note it in the job's log."""
    now = time.time() if now is None else now
    jdir = Path(job_dir)
    lock, got = jdir / "jobs.lock", False
    for _ in range(100):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            got = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 15:
                    os.unlink(lock)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
        except OSError:
            break
    try:
        index = _read_json(jdir / "jobs.json")
        if isinstance(index, list):
            for j in index:
                if isinstance(j, dict) and j.get("id") == job_id and j.get("state") in ("running", "cancelling"):
                    j.update(state="cancelled", ended=now, exit=None, stopped_by="plasbench stop")
            tmp = jdir / f"jobs.json.stop{os.getpid()}.tmp"
            tmp.write_text(json.dumps(index, indent=1), encoding="utf-8")
            os.replace(tmp, jdir / "jobs.json")
        meta = _read_json(jdir / f"{job_id}.meta.json")
        if isinstance(meta, dict):
            meta.update(state="cancelled", ended=now, exit=None, stopped_by="plasbench stop")
            tmp = jdir / f"{job_id}.meta.json.stop{os.getpid()}.tmp"
            tmp.write_text(json.dumps(meta, sort_keys=True, indent=1), encoding="utf-8")
            os.replace(tmp, jdir / f"{job_id}.meta.json")
        try:
            with open(jdir / f"{job_id}.log", "ab") as fh:
                fh.write("\n[PlasBench] Stopped by `plasbench stop`. Finished work is kept: use Resume to continue.\n".encode("utf-8"))
        except OSError:
            pass
    finally:
        if got:
            try:
                os.unlink(lock)
            except OSError:
                pass


def cancel_job(env: Env, t: dict, grace=GRACE_SECONDS) -> dict:
    """Stop a detached job: verify its runner is a PlasBench job runner, stop its container, TERM then KILL its group, record the end (state cancelled)."""
    runner, pgid = t.get("runner"), t.get("pgid")
    entry = env.procs.get(runner) if runner else None
    if entry is not None and not is_runner_cmdline(entry.get("cmdline", "")):
        return {"ended": False, "how": f"process {runner} is not the PlasBench job runner (the pid was reused); not touched"}

    def alive():
        return env.procs.alive(runner) or (bool(pgid) and any(e.get("pgid") == pgid for e in env.procs.list().values()))
    if not alive():
        mark_job_cancelled(t["job_dir"], t["id"], env.clock())
        return {"ended": True, "how": "already gone"}
    try:
        from . import jobrunner
        jobrunner.stop_job_container(t["job_dir"], t["id"])
    except Exception:  # noqa: BLE001
        pass
    if env.cancel_job:
        env.cancel_job(t)
    ok, how = _stop_group(env, pgid, runner, alive, grace)
    if ok:
        mark_job_cancelled(t["job_dir"], t["id"], env.clock())
    return {"ended": ok, "how": how}


def cancel_run(env: Env, t: dict, grace=GRACE_SECONDS) -> dict:
    """Stop a terminal-started run: re-verify, record `stopped_by_user`, then TERM/KILL its recorded process group."""
    entry = env.procs.get(t["pid"])
    if entry is None:
        return {"ended": True, "how": "already gone"}
    if not is_run_cmdline(entry.get("cmdline", "")):
        return {"ended": False, "how": f"process {t['pid']} is no longer a PlasBench run; not touched"}
    _write_run_event(t["results"], "stopped_by_user")
    pgid = int(t["pgid"]) if str(t.get("pgid") or "").isdigit() else None
    ok, how = _stop_group(env, pgid, t["pid"], lambda: env.procs.alive(t["pid"]), grace)
    return {"ended": ok, "how": how}


def close_window(env: Env, w: dict, grace=5.0) -> dict:
    procs = env.win_procs
    if procs is None:
        return {"ended": False, "how": "no way to reach the Windows side"}
    for force, wait in ((False, grace), (True, KILL_WAIT_SECONDS)):
        e = procs.get(w["pid"])
        if e is None:
            return {"ended": True, "how": "closed"}
        if app_window_match(e.get("cmdline", ""), [w["port"]]) != w["port"]:
            return {"ended": False, "how": "no longer a PlasBench app window; not touched"}
        procs.signal(w["pid"], force)
        end = env.clock() + wait
        while env.clock() < end and procs.alive(w["pid"]):
            env.sleep(0.2)
        if not procs.alive(w["pid"]):
            return {"ended": True, "how": "closed" + (" (forced)" if force else "")}
    return {"ended": False, "how": "it did not close"}


def execute(env: Env, plan: dict, grace=GRACE_SECONDS, polite=POLITE_SECONDS, skip_pids=(), progress=None) -> dict:
    """Carry the plan out: servers (`skip_pids`: this process's own server is left to its caller), then the runs marked `cancel`, then windows. The WSL shutdown is NOT started here
    (`launch_wsl_shutdown`, after logging). Adds a `result` to every target and a `summary`."""
    say = progress or (lambda text: None)
    skip = {int(p) for p in skip_pids if p is not None}
    if plan["options"].get("wsl_shutdown") and any(r["action"] == "keep" for r in plan["runs"]):
        raise ValueError("wsl --shutdown ends every run: it needs the runs to be stopped too")
    for t in plan["servers"]:
        if t["action"] == "stop" and not t.get("self") and t.get("pid") not in skip:
            res = stop_server(env, t, grace, polite)
            t["result"], t["detail"] = ("stopped" if res["ended"] else "left running"), res["how"]
            if res["ended"]:
                remove_records(t)
            say(f"port {t['port']} (pid {t['pid']}): {res['how']}")
        elif t["action"] == "stop":
            t["result"] = "stopping (this window)" if t.get("self") else "skipped"
        elif t.get("stale_record"):
            remove_records(t)
            t["result"] = "stale record removed"
        else:
            t["result"] = "skipped"
    for r in plan["runs"]:
        if r["action"] != "cancel":
            r["result"] = "left running" if r["action"] == "keep" else "skipped"
            continue
        res = cancel_job(env, r, grace) if r["kind"] == "job" else cancel_run(env, r, grace)
        r["result"], r["detail"] = ("stopped" if res["ended"] else "left running"), res["how"]
        say(f"{r['kind']} {r['label']}: {res['how']}")
    for w in plan["windows"]:
        res = close_window(env, w)
        w["result"], w["detail"] = ("closed" if res["ended"] else "left open"), res["how"]
    plan["summary"] = summarize(plan)
    return plan


def _n(n, one):
    return f"{n} {one}" if n == 1 else f"{n} {one}s"


def summarize(plan) -> dict:
    stopped = [t for t in plan["servers"] if str(t.get("result", "")).startswith(("stopped", "stopping"))]
    failed = [t for t in plan["servers"] if t.get("result") == "left running" or (t.get("action") == "skip" and t.get("left_running"))]
    failed += [s for s in plan["skipped"] if s.get("kind") == "server" and s.get("left_running")]
    runs_stopped = [r for r in plan["runs"] if r.get("result") == "stopped"]
    runs_left = [r for r in plan["runs"] if r.get("result") == "left running"]
    runs_failed = [r for r in runs_left if r["action"] == "cancel"]
    wins = [w for w in plan["windows"] if w.get("result") == "closed"]
    wins_left = [w for w in plan["windows"] if w.get("result") == "left open"]
    n_failed = len(failed) + len(runs_failed) + len(wins_left)
    kept = len(runs_left) - len(runs_failed) + len([r for r in plan["runs"] if r.get("result") == "skipped"])
    parts = [f"Stopped {_n(len(stopped), 'PlasBench server')}", f"{_n(len(wins), 'window')} closed"]
    if runs_stopped:
        parts.append(f"{_n(len(runs_stopped), 'run')} stopped")
    parts.append(f"{_n(kept, 'run')} left running")
    text = "; ".join(parts) + "." + (f" {_n(n_failed, 'item')} could not be ended." if n_failed else "")
    return {"servers_stopped": len(stopped), "windows_closed": len(wins), "runs_stopped": len(runs_stopped), "runs_left_running": kept, "failed": n_failed, "text": text}


def log_stop(env: Env, plan: dict, by="plasbench stop", extra=None):
    """One line in stop.log and a `stop` event in sessions.jsonl of the first UI home."""
    homes = env.ui_homes()
    if not homes:
        return
    home, summary = homes[0], plan.get("summary") or {}
    ended = {"servers": [{"port": t["port"], "pid": t["pid"]} for t in plan["servers"] if str(t.get("result", "")).startswith(("stopped", "stopping"))],
             "runs": [{"kind": r["kind"], "label": r["label"]} for r in plan["runs"] if r.get("result") == "stopped"],
             "windows": [w["pid"] for w in plan["windows"] if w.get("result") == "closed"]}
    try:
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "stop.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict({"t": env.now_text(), "by": by, "summary": summary.get("text"), "ended": ended}, **(extra or {}))) + "\n")
    except OSError:
        pass
    try:
        from .sessionlog import SessionLog
        SessionLog(home / "sessions.jsonl").event("stop", by=by, ended=ended, summary=summary.get("text"), **(extra or {}))
    except Exception:  # noqa: BLE001 - the record is never a reason to fail
        pass


def log_wsl_shutdown(env: Env, launched=None, stage="requested"):
    """`wsl_shutdown` in stop.log and sessions.jsonl: written BEFORE the launch (stage requested) and after it (stage launched)."""
    homes = env.ui_homes()
    if not homes:
        return
    try:
        homes[0].mkdir(parents=True, exist_ok=True)
        with open(homes[0] / "stop.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": env.now_text(), "event": "wsl_shutdown", "stage": stage, "launched": launched}) + "\n")
    except OSError:
        pass
    try:
        from .sessionlog import SessionLog
        SessionLog(homes[0] / "sessions.jsonl").event("wsl_shutdown", stage=stage, launched=launched)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------------------------------------------------------------------ the command
def render_text(plan: dict, dry: bool) -> str:
    lines = []
    srv = [t for t in plan["servers"] if t["action"] == "stop"]
    lines.append((("Would end " if dry else "Will end ") + _n(len(srv), "PlasBench server") + ":") if srv else "No running PlasBench server was recorded.")
    for t in srv:
        lines.append(f"  port {t['port']}  pid {t['pid']}  version {t.get('version') or '?'}" + (f"  started {t['started_text']}" if t.get("started_text") else "")
                     + (f"  windows alive {t['windows_alive']}" if t.get("windows_alive") is not None else "") + ("  (this window's server)" if t.get("self") else ""))
    skipped = [t for t in plan["servers"] if t["action"] == "skip"]
    if skipped or plan["skipped"]:
        lines.append("Skipped (not touched):")
        for t in skipped:
            lines.append(f"  port {t['port']} (pid {t['pid']}): {t['reason']}")
        for t in plan["skipped"]:
            lines.append("  " + t["reason"])
    cancel = [r for r in plan["runs"] if r["action"] == "cancel"]
    keep = [r for r in plan["runs"] if r["action"] == "keep"]
    if cancel:
        lines.append(("Would stop " if dry else "Will stop ") + _n(len(cancel), "run") + " (finished work is kept; you can resume):")
    if keep:
        lines.append(f"{_n(len(keep), 'run')} keep{'s' if len(keep) == 1 else ''} going in the background (add --runs to stop {'it' if len(keep) == 1 else 'them'}):")
    for r in plan["runs"]:
        lines.append(f"  {r['label']}  running for {human_elapsed(r.get('elapsed_seconds'))}" + (f"  last step: {r['step']}" if r.get("step") else "") + (f"  [{r['reason']}]" if r.get("reason") else ""))
    if plan["windows"]:
        lines.append(("Would close " if dry else "Will close ") + _n(len(plan["windows"]), "PlasBench app window") + ":")
        lines += [f"  {w['name']} pid {w['pid']} (address port {w['port']})" for w in plan["windows"]]
    elif plan["options"].get("windows"):
        lines.append("No PlasBench app window to close.")
    if plan["options"].get("wsl_shutdown"):
        w = plan["wsl"]
        lines += ["", ("Would run" if dry else "WILL RUN") + " `wsl --shutdown`: it ends EVERY WSL distribution" + (f" ({', '.join(w['distributions'])})" if w.get("distributions") else "")
                  + ", Docker Desktop's engine, every terminal open in WSL and anything unsaved there. Finished work and files are kept."]
        if w.get("distributions_note"):
            lines.append("  note: " + w["distributions_note"])
    return "\n".join(lines)


def _payload(plan, code, dry, wsl_result=None) -> dict:
    p = public(plan)
    return {"ok": code == EXIT_OK, "exit_code": code, "dry_run": dry, "servers": p["servers"], "skipped": p["skipped"], "runs": p["runs"], "windows": p["windows"], "wsl": p["wsl"],
            "options": p["options"], "platform": p["platform"], "summary": p.get("summary") or {}, "wsl_shutdown": wsl_result}


JSON_SHAPE = ("{ok, exit_code, dry_run, servers:[{port,pid,version,started,windows_alive,action: stop|skip,reason,result}], skipped:[{kind,port,pid,name,reason}], "
              "runs:[{kind: job|run,label,elapsed_seconds,step,action: cancel|keep,result}], windows:[{pid,name,port,action,result}], wsl:{offered,available,reason,manual,distributions}, "
              "summary:{servers_stopped,windows_closed,runs_stopped,runs_left_running,failed,text}}")


def command(args, out=print, err=None, env=None, input_fn=input, isatty=None) -> int:
    """`plasbench stop`. Exit 0: nothing is left running (or only runs you chose to keep); 3: something could not be ended; 2: usage."""
    err = err or (lambda text: print(text, file=sys.stderr))
    env = env or Env()
    runs, windows, wsl = bool(args.runs), bool(args.windows), bool(getattr(args, "wsl_shutdown", False))
    as_json, dry, yes = bool(args.json), bool(args.dry_run), bool(args.yes)
    if wsl:
        support = wsl_support(env, list_distros=False)
        if not support["offered"]:
            err("[plasbench] ERROR: --wsl-shutdown only exists inside WSL (this PlasBench is not running in WSL).")
            return EXIT_USAGE
        if not support["available"]:
            err(f"[plasbench] ERROR: cannot run wsl --shutdown from here: {support['reason']}.\n  Run it yourself in Windows PowerShell:  {WSL_MANUAL}")
            return EXIT_USAGE
    plan = build_plan(env, runs=runs, windows=windows, wsl=wsl)
    active = active_runs(plan)
    if wsl and active and not runs and not dry:
        err(f"[plasbench] ERROR: {_n(len(active), 'run')} {'is' if len(active) == 1 else 'are'} active and wsl --shutdown ends every run. Add --runs to stop them first "
            "(finished work is kept; you can resume).")
        return EXIT_USAGE
    targets = [t for t in plan["servers"] if t["action"] == "stop"] + [r for r in plan["runs"] if r["action"] == "cancel"] + plan["windows"]
    if as_json and not dry and not yes and targets:
        err("[plasbench] ERROR: --json with something to end needs --yes (there is no one to ask).")
        return EXIT_USAGE
    if not as_json:
        out(render_text(plan, dry))
    if dry:
        out(json.dumps(_payload(plan, EXIT_OK, True), indent=2, default=str) if as_json else "Dry run: nothing was changed.")
        return EXIT_OK
    if wsl and not yes:
        err("[plasbench] ERROR: --wsl-shutdown needs --yes: it is the most destructive option.")
        return EXIT_USAGE
    if targets and not yes:
        tty = sys.stdin.isatty() if isatty is None else isatty
        if not tty:
            err("[plasbench] Nothing was changed (not a terminal: add --yes to proceed).")
            return EXIT_USAGE
        try:
            agreed = input_fn("Go ahead? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            agreed = False
        if not agreed:
            out("Nothing was changed.")
            return EXIT_OK
    execute(env, plan, getattr(args, "grace", GRACE_SECONDS), progress=None if as_json else (lambda text: out("  " + text)))
    summary = plan["summary"]
    log_stop(env, plan, extra={"wsl_shutdown": True} if wsl else None)
    wsl_result = None
    if wsl:
        if summary["failed"]:
            err("[plasbench] wsl --shutdown was NOT started: something above could not be ended.")
        else:
            log_wsl_shutdown(env, None, "requested")
            wsl_result = launch_wsl_shutdown(env, plan["_powershell"])
            log_wsl_shutdown(env, wsl_result["ok"], "launched")
    code = EXIT_LEFT if summary["failed"] or (wsl and not (wsl_result and wsl_result["ok"])) else EXIT_OK
    if as_json:
        out(json.dumps(_payload(plan, code, False, wsl_result), indent=2, default=str))
    else:
        out(summary["text"])
        if wsl_result and wsl_result["ok"]:
            out(f"WSL shuts down in {WSL_DELAY_SECONDS} s. Reopen Ubuntu (or run plasbench ui) to start again; the next WSL start takes a few seconds.")
    return code


def add_arguments(p):
    """The `stop` sub-command's options (cli.py calls this)."""
    p.add_argument("--all", action="store_true", help="Stop every PlasBench window server of this user on this computer (the default; the flag only says so).")
    p.add_argument("--runs", action="store_true", help="Also cancel active runs and jobs (without it they keep going in the background and are listed).")
    p.add_argument("--windows", action="store_true", help="Also close the app windows PlasBench opened (they normally close themselves when their server ends).")
    p.add_argument("--dry-run", action="store_true", help="Print exactly what would be ended and skipped, and change nothing.")
    p.add_argument("--yes", action="store_true", help="Do not ask before ending things.")
    p.add_argument("--json", action="store_true", help="Print the result as JSON.")
    p.add_argument("--wsl-shutdown", action="store_true", help="WSL only: finally run `wsl --shutdown` from Windows (ends EVERY WSL distribution and Docker Desktop's engine). Needs --yes, and --runs when runs are active.")
    p.add_argument("--grace", type=float, default=GRACE_SECONDS, help=argparse.SUPPRESS)
