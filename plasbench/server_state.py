"""Is this running window server older than the files on disk? And restarting it safely.

The server's Python code is fixed in memory when it starts, but the page (plasbench/data/ui.html) is re-read from disk. After an update (plasbench upgrade, update.sh, a git pull, a
release install) while a window is open, the NEW page is therefore served by the OLD server, and the page calls routes the old server does not have ("no such API: workflow").
At start the server records a fingerprint of its code (the package version and the size and modification time of every plasbench/*.py file); `state()` compares it with the disk
without importing anything and without starting a process. `restart()` starts a replacement server and leaves the old one to exit; runs are detached (plasbench/jobrunner.py) and
are never touched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__

PKG = Path(__file__).resolve().parent
_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.M)
_RESTART_LOCK = threading.Lock()


def code_fingerprint() -> dict:
    """{file name: [mtime_ns, size]} of every plasbench/*.py (the server imports them lazily, so all of them count)."""
    out = {}
    for path in PKG.glob("*.py"):
        try:
            st = path.stat()
        except OSError:
            continue
        out[path.name] = [st.st_mtime_ns, st.st_size]
    return out


def disk_version() -> str:
    """The version written in the package files on disk (read as text, never imported)."""
    try:
        m = _VERSION_RE.search((PKG / "__init__.py").read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


START = {"version": __version__, "files": code_fingerprint(), "at": time.time()}


def reset(version: str | None = None, files: dict | None = None) -> None:
    """Record 'now' as the start (used by tests that simulate a start)."""
    START.update(version=version or __version__, files=files if files is not None else code_fingerprint(), at=time.time())


def compare(started: dict, version_now: str, files_now: dict) -> tuple[bool, str]:
    if version_now and version_now != started["version"]:
        return True, f"the files on disk are version {version_now}, this window was started from {started['version']}"
    old, new = started["files"], files_now
    changed = sorted(n for n in new if n in old and new[n] != old[n])
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    if changed or added or removed:
        names = changed + added + removed
        return True, "program files changed on disk since this window started (" + ", ".join(names[:3]) + (", ..." if len(names) > 3 else "") + ")"
    return False, ""


def restart_support() -> tuple[bool, str]:
    """(ok, why not). A restart starts the same Python on the same package; it is refused where that cannot be trusted."""
    if os.environ.get("PLASBENCH_NO_RESTART") == "1":
        return False, "automatic restart is switched off (PLASBENCH_NO_RESTART=1)"
    if getattr(sys, "frozen", False):
        return False, "this PlasBench is a packaged program, which cannot start itself again"
    exe = sys.executable
    if not exe or not os.path.exists(exe):
        return False, "the Python that runs PlasBench cannot be found again"
    return True, ""


def state() -> dict:
    """The answer of GET /api/server-state."""
    disk = disk_version()
    stale, reason = compare(START, disk, code_fingerprint())
    return {"started_version": START["version"], "disk_version": disk or START["version"], "stale": stale, "reason": reason, "started_at": START["at"],
            "restart_supported": restart_support()[0]}


def replacement_command(root: Path, port: int) -> list[str]:
    return [sys.executable, "-m", "plasbench", "--project-root", str(root), "ui", "--new-instance", "--no-browser", "--port", str(port)]


def spawn_detached(cmd: list[str], cwd) -> subprocess.Popen:
    """Start `cmd` so that it outlives this server (own session / process group, no console, no inherited pipes)."""
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kw)


def _healthy(info: dict) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(info['port'])}/healthz", timeout=2) as r:
            return r.status == 200
    except (OSError, ValueError, KeyError):
        return False


def restart(root: Path, port: int, record_file: Path, spawn=spawn_detached, healthy=None, wait: float = 30.0) -> dict:
    """Start a replacement server and wait until it answers. {"ok": True, "url": new address (with its new key)} or {"ok": False, "message", "manual": True}.

    The caller shuts THIS server down after the answer has been sent (the same keep-running shutdown as Quit: runs are detached and are not stopped)."""
    ok, why = restart_support()
    if not ok:
        return {"ok": False, "manual": True, "message": why}
    if not _RESTART_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "a restart is already in progress"}
    try:
        try:
            child = spawn(replacement_command(root, port), root)
        except OSError as exc:
            return {"ok": False, "manual": True, "message": f"could not start the new PlasBench: {exc}"}
        end = time.time() + wait
        while time.time() < end:
            code = child.poll()
            if code is not None:
                return {"ok": False, "manual": True, "message": f"the new PlasBench stopped while starting (exit code {code}); this window is unchanged"}
            try:
                info = json.loads(record_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if info.get("pid") == child.pid and info.get("url") and (healthy or _healthy)(info):
                return {"ok": True, "url": info["url"], "pid": info["pid"]}
            time.sleep(0.25)
        return {"ok": False, "manual": True, "message": "the new PlasBench did not answer in time; this window is unchanged"}
    finally:
        _RESTART_LOCK.release()
