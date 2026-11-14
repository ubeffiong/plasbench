"""The workspace: the folder that holds every study (plasbench/studies.py), chosen and checked from the window.

Choosing it decides where benchmark outputs (often hundreds of GB) are written, so the checks are defensive, after
GenoSuv's working-folder design: the path is normalised; system folders, files and disconnected drives are refused;
writing is really tested; free space, drive type (this computer / external / network), cloud-sync folders and long
paths are reported. A saved workspace that has gone missing (an unplugged drive) is reported as unavailable, never
silently replaced. The choice is saved as PLASBENCH_WORKSPACE in config/local.env (read by the CLI and the pipeline);
recent choices are remembered for the window in ~/.plasbench/ui/state.json.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

IS_WIN = os.name == "nt"
LOW_SPACE = 100 * 2**30
SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync", "sync.com", "nextcloud")
SYSTEM_DIRS = [r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData", "/bin", "/boot", "/dev",
               "/etc", "/lib", "/proc", "/sys", "/usr", "/sbin", "/System"]


def _key(p) -> str:
    s = str(p).rstrip("\\/")
    return s.lower() if IS_WIN else s


def normalise(raw: str) -> Path:
    """User text -> absolute path. Strips quotes and spaces, expands ~ and variables; refuses relative paths."""
    s = (raw or "").strip().strip('"').strip("'").strip()
    if not s:
        raise ValueError("enter a folder path")
    s = os.path.expandvars(os.path.expanduser(s))
    if "\x00" in s or any(c in s for c in '<>|*?"'):
        raise ValueError('the path contains characters that are not allowed (< > | * ? ")')
    p = Path(s)
    if not p.is_absolute():
        raise ValueError("give the full path (for example D:\\PlasBenchStudies or /data/plasbench), not a relative one")
    return Path(os.path.normpath(str(p)))


def drive_kind(p: Path) -> tuple:
    """(code, label): internal | external | network | unknown."""
    if IS_WIN and str(p).startswith("\\\\"):
        return "network", "network share"
    if IS_WIN:
        try:
            import ctypes
            t = ctypes.windll.kernel32.GetDriveTypeW(p.anchor or "C:\\")
            return {2: ("external", "external / removable drive"), 3: ("internal", "this computer's disk"),
                    4: ("network", "mapped network drive")}.get(t, ("unknown", "unknown drive type"))
        except Exception:  # noqa: BLE001
            return "unknown", "unknown drive type"
    try:
        best = ("", "")
        with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                _dev, mnt, fs = line.split()[:3]
                if (str(p) == mnt or str(p).startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best[0]):
                    best = (mnt, fs)
        if best[1] in ("nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs"):
            return "network", "network share"
        if best[0].startswith(("/media", "/run/media")) or best[1] in ("vfat", "exfat", "fuseblk"):
            return "external", "external / removable drive"
        return "internal", "this computer's disk"
    except OSError:
        pass
    if sys.platform == "darwin":
        return ("external", "external / removable drive") if str(p).startswith("/Volumes/") else ("internal", "this computer's disk")
    return "unknown", "unknown drive type"


def _existing_ancestor(p: Path):
    q = p
    while not q.exists():
        if q.parent == q:
            return None
        q = q.parent
    return q


def _is_system(p: Path) -> bool:
    k = _key(p)
    return any(k == _key(s) or k.startswith(_key(s) + os.sep) for s in SYSTEM_DIRS)


def check(raw: str) -> dict:
    """Validate a candidate workspace WITHOUT creating anything. The window shows the report: ok, errors (blockers),
    warnings, whether it will be created, drive kind, free and total bytes, and the normalised path."""
    out = {"input": raw, "ok": False, "errors": [], "warnings": [], "will_create": False, "exists": False,
           "kind": "unknown", "kind_label": "", "free": None, "total": None, "path": "", "studies": 0}
    try:
        p = normalise(raw)
    except ValueError as exc:
        out["errors"].append(str(exc))
        return out
    out["path"] = str(p)
    out["kind"], out["kind_label"] = drive_kind(p)
    if _is_system(p):
        out["errors"].append("that is an operating-system folder: choose a normal data folder")
        return out
    if p.exists() and not p.is_dir():
        out["errors"].append("that path is a file, not a folder")
        return out
    anc = _existing_ancestor(p)
    if anc is None or (IS_WIN and p.drive and not Path(p.drive + "\\").exists()):
        out["errors"].append(f"drive {p.drive or str(p)[:3]} is not connected or does not exist: connect it, then check again")
        return out
    out["exists"] = p.is_dir()
    out["will_create"] = not p.exists()
    try:
        usage = shutil.disk_usage(anc)
        out["free"], out["total"] = usage.free, usage.total
    except OSError:
        out["warnings"].append("could not read the free space of that location")
    probe = (p if p.exists() else anc) / f".plasbench_write_test_{os.getpid()}"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        out["errors"].append(f"cannot write to {probe.parent}: {exc.strerror or exc}. Choose a folder you can write to"
                             + (" (the drive may be read-only or full)" if out["kind"] in ("external", "network") else ""))
        return out
    if p.is_dir():
        out["studies"] = sum(1 for c in p.iterdir() if c.is_dir() and (c / "study.json").is_file())
        others = sum(1 for c in p.iterdir() if not c.name.startswith(".")) - out["studies"]
        if others > 0:
            out["warnings"].append(f"the folder already holds {others} other item(s); they are left alone, and only "
                                   "study folders appear in PlasBench")
    if out["free"] is not None and out["free"] < LOW_SPACE:
        out["warnings"].append(f"only {out['free'] / 2**30:.0f} GB free; a public cohort needs hundreds of GB for reads, "
                               "assemblies and results")
    if any(m in str(p).lower() for m in SYNC_MARKERS):
        out["warnings"].append("this folder is inside a cloud-sync folder (OneDrive, Dropbox, ...): syncing large read and "
                               "assembly files is slow and can lock files mid-run. A plain local folder is safer.")
    if out["kind"] == "external":
        out["warnings"].append("external drive: keep it connected while benchmarks run; a disconnected drive stops the run "
                               "(re-running continues from the finished steps).")
    if out["kind"] == "network":
        out["warnings"].append("network location: slower, and a dropped connection stops the run. Large files are better "
                               "on a local or external disk.")
    if len(str(p)) > 150:
        out["warnings"].append("the path is long; Windows tools can fail on paths over 260 characters once study and "
                               "sample folder names are added")
    out["ok"] = True
    return out


def describe(root) -> dict:
    """The active workspace for the window: path, where the choice comes from, whether it is there, drive, free space."""
    from . import studies
    path = studies.workspace(root)
    if os.environ.get("PLASBENCH_WORKSPACE"):
        source = "environment variable PLASBENCH_WORKSPACE"
    elif studies._local_env(root).get("PLASBENCH_WORKSPACE"):
        source = "saved for this computer (config/local.env)"
    else:
        source = "default (inside the PlasBench folder)"
        # The default lives inside the PlasBench folder: create it rather than call it missing. A chosen folder that is
        # missing is NOT created here: it is reported, since it may be a disconnected drive.
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    available = path.is_dir()
    free = None
    if available:
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            pass
    kind, label = drive_kind(path)
    return {"path": str(path), "source": source, "default": str(Path(root) / "studies"), "available": available,
            "kind": kind, "kind_label": label, "free": free,
            "env_override": bool(os.environ.get("PLASBENCH_WORKSPACE"))}
