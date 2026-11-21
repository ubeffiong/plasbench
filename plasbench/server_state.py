"""Is this running window server running different code from what a restart would load? And restarting it safely.

The server's Python code is fixed in memory when it starts, but the page (plasbench/data/ui.html) is re-read from disk. After an update (plasbench upgrade, update.sh, a source update, a
release install) while a window is open, the NEW page is therefore served by the OLD server, and the page calls routes the old server does not have ("no such API: workflow").

What counts as stale (and nothing else does):
  - loaded_code: the package this server imported (PKG, the folder of plasbench/__init__.py it runs from, wherever that is: site-packages, an editable checkout) now holds a different
    `__version__`, or the CONTENT (sha256) of a plasbench module this server has already imported differs from what it had at start. A file that was only touched (same content: OneDrive,
    an antivirus, git, a copy) is not stale; neither is a file the server never imported, a *.pyc, a cache, or ui.html (the page is meant to change; see API_LEVEL).
  - two_installs: the project folder (--project-root) holds a plasbench package of a different version than the one this server imported (a copy in site-packages from `pip install .`
    next to a newer checkout). Restarting the window cannot fix that: the same Python would import the same old copy. It needs the install command.
`state()` compares without importing anything and without starting a process. `restart()` starts a replacement server that loads the SAME package folder as this one and leaves the old one
to exit; runs are detached (plasbench/jobrunner.py) and are never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__

PKG = Path(__file__).resolve().parent
API_LEVEL = 2   # raised when the page needs a route or a field an older server lacks; the page carries the level it needs (meta plasbench-api-level) and the server substitutes its own
_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.M)
_RESTART_LOCK = threading.Lock()
_HASHES: dict = {}   # path -> ((size, mtime_ns), sha256): a hash is recomputed only when the size or mtime changed
_BOOT = ("import sys, runpy; sys.path.insert(0, sys.argv[1]); sys.argv = ['plasbench'] + sys.argv[2:]; "
         "runpy.run_module('plasbench', run_name='__main__', alter_sys=True)")


def file_hash(path) -> str:
    """sha256 of a file's bytes, cached by (size, mtime): a touched file is re-read once, an untouched one never. '' when unreadable."""
    path = str(path)
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (st.st_size, st.st_mtime_ns)
    hit = _HASHES.get(path)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""
    _HASHES[path] = (key, digest)
    return digest


def loaded_modules(pkg=None) -> dict:
    """{path relative to the package folder: absolute path} of the plasbench modules this process has imported from `pkg` (source files only)."""
    pkg = Path(pkg).resolve() if pkg else PKG
    out = {}
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f or not str(f).endswith(".py"):
            continue
        try:
            rel = Path(f).resolve().relative_to(pkg)
        except (ValueError, OSError):
            continue
        out[rel.as_posix()] = str(Path(f).resolve())
    return out


def module_hashes(pkg=None) -> dict:
    return {rel: file_hash(path) for rel, path in loaded_modules(pkg).items()}


def read_version(pkg) -> str:
    """The version written in `pkg`/__init__.py (read as text, never imported); '' when there is none."""
    try:
        m = _VERSION_RE.search((Path(pkg) / "__init__.py").read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


def disk_version() -> str:
    """The version written in the package files this server imported (read as text, never imported)."""
    return read_version(PKG)


START = {"version": __version__, "modules": module_hashes(), "at": time.time(), "pid": os.getpid(), "port": None, "root": None}


def reset(version=None, modules=None, root=None, port=None) -> None:
    """Record 'now' as the start (the server calls it once it is listening; tests use it to simulate a start)."""
    START.update(version=version or __version__, modules=modules if modules is not None else module_hashes(), at=time.time(), pid=os.getpid(),
                 port=port if port is not None else START.get("port"), root=str(root) if root else START.get("root"))


def changed_modules(started: dict, pkg=None) -> list:
    """The modules this server had imported (hash recorded at start, or the first time it was seen) whose content on disk now differs. A module first seen later is recorded, not
    flagged: it was imported from the files as they are."""
    base = started["modules"]
    found = []
    for rel, path in loaded_modules(pkg).items():
        now = file_hash(path)
        if rel not in base:
            base[rel] = now
        elif now != base[rel]:
            found.append({"module": rel, "old": (base[rel] or "missing")[:12], "new": (now or "missing")[:12]})
    return sorted(found, key=lambda x: x["module"])


def compare(started: dict, version_now: str, changed: list) -> tuple[bool, str]:
    if version_now and version_now != started["version"]:
        return True, f"the files on disk are version {version_now}, this window was started from {started['version']}"
    if changed:
        names = [c["module"] for c in changed]
        return True, "program files changed on disk since this window started (" + ", ".join(names[:3]) + (", ..." if len(names) > 3 else "") + ")"
    return False, ""


def install_command(root) -> str:
    """The command that refreshes the installed copy from the project folder (run it in the plasbench environment)."""
    return f"conda activate plasbench && cd {shlex.quote(str(root))} && python -m pip install --no-deps ."


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


def state(root=None) -> dict:
    """The answer of GET /api/server-state."""
    root = root if root is not None else START.get("root")
    disk = disk_version()
    changed = changed_modules(START)
    stale, reason = compare(START, disk, changed)
    kind = "loaded_code" if stale else "none"
    root_version, root_path = "", ""
    try:
        root_pkg = Path(root) / "plasbench" if root else None
        if root_pkg and (root_pkg / "__init__.py").is_file() and root_pkg.resolve() != PKG:
            root_version, root_path = read_version(root_pkg), str(root_pkg.resolve())
    except OSError:
        pass
    fix = ""
    if kind == "none" and root_version and root_version != START["version"]:
        kind, stale = "two_installs", True
        fix = install_command(root)
        reason = (f"PlasBench is installed in two places with different versions (running: {START['version']} from {PKG}; project folder: {root_version} at {root_path}). "
                  f"Restarting the window cannot fix this; run: {fix}")
    return {"started_version": START["version"], "disk_version": disk or START["version"], "stale": stale, "reason": reason, "started_at": START["at"],
            "restart_supported": restart_support()[0], "kind": kind, "api_level": API_LEVEL,
            "running_version": START["version"], "running_path": str(PKG), "disk_path": str(PKG),
            "project_root_version": root_version, "project_root_path": root_path, "project_root": str(root) if root else "",
            "changed_modules": changed[:20], "fix_command": fix, "restart_helps": kind == "loaded_code",
            "server": {"pid": START.get("pid"), "port": START.get("port"), "started_at": START["at"]}}


def replacement_command(root: Path, port: int, handoff_file: str = "") -> list[str]:
    """The same Python, started on the package folder THIS server runs from (not whatever `-m plasbench` finds first in the current directory).
    With `handoff_file` the replacement waits up to 25 s for THIS server's port (so the window keeps its address) and creates that file just before it binds."""
    extra = ["--port-wait", "25", "--handoff-file", handoff_file] if handoff_file else []
    return [sys.executable, "-c", _BOOT, str(PKG.parent), "--project-root", str(root), "ui", "--new-instance", "--no-browser", "--port", str(port)] + extra


def group_launch(cmd: list[str], root=None, membership=None, which=shutil.which) -> tuple[list[str], bool, str]:
    """(argv, wrapped, problem). A process keeps the groups it was started with, so after `sudo usermod -aG docker $USER` a restarted window would still lack the group. When the
    account IS in the docker group now but this process is not, the replacement is started as `sg docker -c 'exec <argv>'` (each word shell-quoted); without `sg` the answer is a
    problem sentence and the caller falls back to the manual instructions. Nothing changes when the group is already applied or the account is not a member."""
    try:
        if membership is None:
            folder = str(Path(root) / "python") if root else str(PKG.parent / "python")
            if folder not in sys.path:
                sys.path.insert(0, folder)
            import docker_setup
            membership = docker_setup.group_membership()
    except Exception:  # noqa: BLE001 - detection is optional: without it the restart is the plain one
        return cmd, False, ""
    if not (membership.get("in_group") and not membership.get("process_has")):
        return cmd, False, ""
    sg = which("sg")
    if not sg:
        return cmd, False, ("You are in the docker group but `sg` is not available to start PlasBench with it. Restart the window from a terminal where the group applies "
                            "(newgrp docker, then plasbench ui), or run wsl --shutdown in Windows PowerShell and reopen Ubuntu.")
    return [sg, str(membership.get("group") or "docker"), "-c", "exec " + shlex.join(cmd)], True, ""


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


def restart(root: Path, port: int, record_file: Path, spawn=spawn_detached, healthy=None, wait: float = 30.0, membership=None, which=shutil.which, release=None) -> dict:
    """Start a replacement server and wait until it answers. {"ok": True, "url": new address (with its new key)} or {"ok": False, "message", "manual": True}.

    The caller shuts THIS server down after the answer has been sent (the same keep-running shutdown as Quit: runs are detached and are not stopped)."""
    ok, why = restart_support()
    if not ok:
        return {"ok": False, "manual": True, "message": why}
    if not _RESTART_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "a restart is already in progress"}
    try:
        handoff = ""
        if release is not None:   # window stability: the replacement binds the SAME port; `release` makes this server stop listening once the replacement says it is loaded
            handoff = str(Path(record_file).parent / f"handoff-{os.getpid()}-{int(time.time() * 1000)}.ready")
            try:
                Path(handoff).unlink()
            except OSError:
                pass
        released = False
        argv, wrapped, problem = group_launch(replacement_command(root, port, handoff), root, membership, which)
        if problem:
            return {"ok": False, "manual": True, "message": problem}
        try:
            child = spawn(argv, root)
        except OSError as exc:
            return {"ok": False, "manual": True, "message": f"could not start the new PlasBench: {exc}"}
        end = time.time() + wait
        while time.time() < end:
            code = child.poll()
            if code is not None:
                return {"ok": False, "manual": True, "message": f"the new PlasBench stopped while starting (exit code {code}); " + ("this window has stopped listening: start PlasBench again" if released else "this window is unchanged")}
            if handoff and not released and os.path.exists(handoff):
                released = True
                release()
            try:
                info = json.loads(record_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if (info.get("pid") != os.getpid() if wrapped else info.get("pid") == child.pid) and info.get("url") and (healthy or _healthy)(info):      # through sg the recorded pid is the shell's child
                return {"ok": True, "url": info["url"], "pid": info["pid"]}
            time.sleep(0.25)
        return {"ok": False, "manual": True, "message": "the new PlasBench did not answer in time; " + ("this window has stopped listening: start PlasBench again" if released else "this window is unchanged")}
    finally:
        if handoff:
            try:
                Path(handoff).unlink()
            except OSError:
                pass
        _RESTART_LOCK.release()
