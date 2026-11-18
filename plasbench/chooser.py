"""The window's "Choose a folder": what it lists first (quick places and the PC's drives, also the Windows drives when PlasBench runs in WSL),
and how a typed Windows path or a \\\\wsl.localhost\\... path becomes the Linux path PlasBench really uses.

Everything that touches the system takes its source as an argument (`mounts_text`, `mnt_dir`, `run`), so tests can mock /proc/mounts and a temp /mnt tree.
Nothing here ever mounts anything: a drive that Ubuntu has not mounted is explained with the exact command for the user to run (`mount_help`).
Standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WSL_MOUNT_TYPES = ("drvfs", "9p", "virtiofs")
DRIVE_RE = re.compile(r"^([A-Za-z]):([\\/].*)?$")
UNC_WSL_RE = re.compile(r"^[\\/]{2}wsl(?:\.localhost|\$)[\\/]+([^\\/]+)(?:[\\/]+(.*))?$", re.I)
UNC_RE = re.compile(r"^[\\/]{2}[^\\/]+[\\/]+[^\\/]+")
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def in_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def mount_command(letter: str = "E") -> str:
    letter = (letter or "E").upper()[:1]
    return f"sudo mkdir -p /mnt/{letter.lower()} && sudo mount -t drvfs {letter}: /mnt/{letter.lower()}"


def mount_help(letter: str = "E") -> str:
    letter = (letter or "E").upper()[:1]
    return f"{letter}: is not mounted in Ubuntu. To mount it, run this in the Terminal tab (PlasBench never runs it for you): {mount_command(letter)}"


# ---------------------------------------------------------------- Windows <-> Linux paths (WSL)
def _wslpath(flag: str, text: str, run=subprocess.run) -> str | None:
    try:
        done = run(["wslpath", flag, text], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (getattr(done, "stdout", "") or "").strip()
    return out if getattr(done, "returncode", 1) == 0 and out else None


def to_linux(text: str, wsl: bool | None = None, run=subprocess.run) -> str:
    """The Linux path for what the user typed. Outside WSL the text is returned unchanged. A Windows drive path (C:\\Users\\me, D:/x) or a \\\\wsl.localhost\\<distro>\\... path
    is converted with `wslpath -u` (5 s), and by plain rules when that is unavailable: C:\\x -> /mnt/c/x; \\\\wsl.localhost\\Ubuntu\\home\\me -> /home/me."""
    raw = (text or "").strip().strip('"').strip("'").strip()
    wsl = in_wsl() if wsl is None else wsl
    if not wsl or not raw:
        return raw
    m_unc = UNC_WSL_RE.match(raw)
    m_drive = DRIVE_RE.match(raw)
    if not (m_unc or m_drive):
        if UNC_RE.match(raw):
            raise ValueError("a network share (\\\\server\\share) is not mounted in Ubuntu: map it to a drive letter in Windows and mount that drive, "
                             "or choose a folder on a drive or in Ubuntu")
        return raw
    converted = _wslpath("-u", raw, run)
    if converted:
        return converted
    if m_unc:
        rest = (m_unc.group(2) or "").replace("\\", "/").strip("/")
        return "/" + rest if rest else "/"
    rest = (m_drive.group(2) or "").replace("\\", "/").strip("/")
    return f"/mnt/{m_drive.group(1).lower()}" + (f"/{rest}" if rest else "")


def to_windows(path: str, wsl: bool | None = None, run=subprocess.run, distro: str | None = None) -> str:
    """The Windows spelling of a Linux path in WSL ('' outside WSL): `wslpath -w`, else /mnt/c/x -> C:\\x and the rest -> \\\\wsl.localhost\\<distro>\\..."""
    wsl = in_wsl() if wsl is None else wsl
    if not wsl or not path:
        return ""
    converted = _wslpath("-w", path, run)
    if converted:
        return converted
    m = re.match(r"^/mnt/([A-Za-z])(/.*)?$", path)
    if m:
        return f"{m.group(1).upper()}:" + (m.group(2) or "\\").replace("/", "\\")
    distro = distro or os.environ.get("WSL_DISTRO_NAME") or "Ubuntu"
    return f"\\\\wsl.localhost\\{distro}" + path.replace("/", "\\")


# ---------------------------------------------------------------- what is listed first
def _free(path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def wsl_drives(mounts_text: str | None = None, mnt_dir: str = "/mnt", free=_free) -> list:
    """Windows drives as Ubuntu sees them: /proc/mounts entries of type drvfs / 9p / virtiofs under /mnt or /media, and single-letter folders in /mnt."""
    if mounts_text is None:
        try:
            mounts_text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
        except OSError:
            mounts_text = ""
    found = {}
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] not in WSL_MOUNT_TYPES:
            continue
        mount = str(Path(parts[1].replace("\\040", " ")))
        if Path(mount).parent == Path(mnt_dir) or str(Path(mount).parent) == "/media" or str(Path(mount).parent.parent) == "/media":
            found[mount] = parts[2]
    try:
        for child in Path(mnt_dir).iterdir():
            if len(child.name) == 1 and child.name.isalpha() and child.is_dir():
                found.setdefault(str(child), "folder")
    except OSError:
        pass
    out = []
    for mount in sorted(found):
        letter = Path(mount).name
        label = f"{letter.upper()}: (Windows)" if len(letter) == 1 and letter.isalpha() else f"{Path(mount).name} (Windows drive)"
        out.append({"name": label, "path": mount, "dir": True, "free": free(mount), "kind": "drive", "windows": f"{letter.upper()}:\\" if len(letter) == 1 else ""})
    return out


def pc_places(platform: str | None = None, wsl: bool | None = None, env=None, mounts_text: str | None = None, mnt_dir: str = "/mnt", free=_free) -> list:
    """"This PC": native Windows drive letters; WSL the Windows drives; Linux /mnt, /media/$USER, /run/media/$USER mounts; macOS /Volumes."""
    env = os.environ if env is None else env
    platform = platform or ("windows" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux")
    if platform == "windows":
        import string
        return [{"name": f"{d}:", "path": f"{d}:\\", "dir": True, "free": free(f"{d}:\\"), "kind": "drive"} for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
    if platform == "mac":
        base = Path("/Volumes")
        return [{"name": c.name, "path": str(c), "dir": True, "free": free(str(c)), "kind": "drive"} for c in sorted(base.iterdir()) if c.is_dir()] if base.is_dir() else []
    wsl = in_wsl() if wsl is None else wsl
    if wsl:
        return wsl_drives(mounts_text, mnt_dir, free)
    user = env.get("USER") or env.get("LOGNAME") or ""
    out = []
    for base in (mnt_dir, f"/media/{user}" if user else "", f"/run/media/{user}" if user else ""):
        if base and Path(base).is_dir():
            try:
                for c in sorted(Path(base).iterdir()):
                    if c.is_dir() and not c.name.startswith("."):
                        out.append({"name": c.name, "path": str(c), "dir": True, "free": free(str(c)), "kind": "drive"})
            except OSError:
                continue
    return out


def quick_places(root, workspace, data_dir=None) -> list:
    out = [{"name": "Home", "path": str(Path.home()), "dir": True, "kind": "place"}, {"name": "Workspace (studies)", "path": str(workspace), "dir": True, "kind": "place"},
           {"name": "PlasBench folder", "path": str(root), "dir": True, "kind": "place"}]
    if data_dir and Path(data_dir).is_dir():
        out.append({"name": "Shared data folder", "path": str(data_dir), "dir": True, "kind": "place"})
    return [p for p in out if Path(p["path"]).is_dir()]


def clean_folder_name(name: str) -> str:
    """A name for a new folder: one segment, no separators or characters Windows forbids, not a reserved name; raises ValueError with the reason."""
    name = (name or "").strip()
    if not name or name in (".", ".."):
        raise ValueError("type a name for the new folder")
    if len(name) > 80:
        raise ValueError("the folder name is too long (at most 80 characters)")
    if BAD_NAME.search(name):
        raise ValueError('a folder name cannot contain / \\ : * ? " < > | or control characters')
    if name.endswith((".", " ")) or name.split(".")[0].upper() in RESERVED:
        raise ValueError("that name is not allowed on Windows (reserved name, or ends with a dot or a space)")
    return name


def make_folder(parent: str, name: str) -> str:
    """Create `name` directly inside the existing folder `parent` (never several levels, never outside it)."""
    name = clean_folder_name(name)
    base = Path(parent)
    if not base.is_dir():
        raise FileNotFoundError(f"{parent} is not a folder")
    target = base / name
    if target.exists():
        raise ValueError(f"{name} already exists in {base}")
    try:
        target.mkdir()
    except PermissionError:
        raise PermissionError(f"no permission to create a folder in {base}")
    except OSError as exc:
        raise ValueError(f"cannot create {target}: {exc.strerror or exc}")
    return str(target)
