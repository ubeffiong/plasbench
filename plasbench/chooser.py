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
from urllib.parse import unquote
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
FILE_URL_RE = re.compile(r"^file:(?://)?(?P<host>[^/\\]*)(?P<rest>/.*)?$", re.I)
EXPLORER_ROOT_RE = re.compile(r"^(?:this pc|my computer|computer|network)\s*(?:[\\/>]|$)\s*", re.I)
DRIVE_IN_NAME_RE = re.compile(r"\(([A-Za-z]):\)\s*$")


def normalize_typed(text: str) -> str:
    r"""What the user pasted -> a plain path. Explorer gives several spellings, all accepted: 'Copy as path' (a double-quoted "D:\data\x"), the address bar (D:\data\x),
    \\wsl.localhost\... and \\wsl$\..., file:///D:/data/x (also file://server/share; %20 is decoded) and the breadcrumb form 'This PC\Data (D:)\x' or 'This PC > Data (D:) > x'
    (the drive letter in brackets is used). A breadcrumb that names no drive ('This PC\Downloads') raises ValueError saying what to do instead."""
    raw = (text or "").strip()
    while len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1].strip()
    raw = raw.strip('"').strip("'").strip()
    m = FILE_URL_RE.match(raw)
    if m:
        host, rest = m.group("host"), unquote(m.group("rest") or "")
        if host and host.lower() != "localhost":
            return "\\\\" + host + rest.replace("/", "\\")
        if re.match(r"^/[A-Za-z]:(/|$)", rest):
            return rest[1:]
        return rest or "/"
    if EXPLORER_ROOT_RE.match(raw):
        body = EXPLORER_ROOT_RE.sub("", raw)
        parts = [x.strip() for x in re.split(r"\s*(?:[\\/>])\s*", body) if x.strip()]
        if parts:
            dm = DRIVE_IN_NAME_RE.search(parts[0])
            if dm and not raw.lower().startswith("network"):
                return f"{dm.group(1).upper()}:\\" + "\\".join(parts[1:])
        raise ValueError("that is the name Explorer shows in its breadcrumb bar, not a path: in Explorer click the empty part of the address bar (it turns into the real path, "
                         "such as D:\\data), or hold Shift, right-click the folder and choose Copy as path, then paste it here")
    return raw


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
    raw = normalize_typed(text)
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


def drive_mounted(letter: str, mounts_text: str | None = None, mnt_dir: str = "/mnt") -> bool:
    """True when /mnt/<letter> is a real Windows-drive mount (a drvfs / 9p / virtiofs entry in /proc/mounts), not just a folder.
    A leftover empty /mnt/e (made by `mkdir -p`, or by an earlier mount) is a folder of Ubuntu's own disk: it is NOT the E: drive."""
    if mounts_text is None:
        try:
            mounts_text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
        except OSError:
            mounts_text = ""
    target = str(Path(mnt_dir) / (letter or "").lower()[:1])
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in WSL_MOUNT_TYPES and str(Path(parts[1].replace("\\040", " "))) == target:
            return True
    return False


def wsl_drives(mounts_text: str | None = None, mnt_dir: str = "/mnt", free=_free) -> list:
    """Windows drives as Ubuntu sees them: /proc/mounts entries of type drvfs / 9p / virtiofs under /mnt or /media, and single-letter folders in /mnt.
    Only a real mount gets a capacity: the free space of an empty folder such as /mnt/e (left by `mkdir -p`) is the space of Ubuntu's own virtual disk, which is what used to be shown
    as the drive's size; such a folder is listed as 'not mounted' with the mount command instead."""
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
        is_letter = len(letter) == 1 and letter.isalpha()
        mounted = found[mount] != "folder"
        label = f"{letter.upper()}: (Windows)" if is_letter else f"{Path(mount).name} (Windows drive)"
        row = {"name": label, "path": mount, "dir": True, "free": free(mount) if mounted else None, "kind": "drive", "windows": f"{letter.upper()}:\\" if is_letter else "", "mounted": mounted}
        if not mounted:
            row["hint"] = mount_command(letter)
        out.append(row)
    return out


def volume_kind(drive_type, bus=None) -> str:
    kind = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "virtual"}.get(drive_type, "unknown")
    if drive_type == 3 and bus and str(bus).upper() in ("USB", "1394", "SD", "MMC"):
        kind = "removable"
    return kind


def windows_drive_rows(disks: list, wsl: bool, mounts_text: str | None = None, mnt_dir: str = "/mnt") -> list:
    """The chooser's This PC rows from the Windows host's own list of volumes (computer_info.windows_disks: every letter the machine has, USB sticks and network drives included,
    with the real size and free space as Windows reports them). In WSL each row says whether Ubuntu has it mounted; one that is not carries the exact mount command.
    Native Windows rows open at the letter; a drive with no media (empty card reader) is listed but cannot be opened."""
    rows = []
    for dk in sorted(disks, key=lambda d: d["letter"]):
        letter = dk["letter"].upper()
        total, free = dk.get("total"), dk.get("free")
        media = total is not None
        kind = volume_kind(dk.get("drive_type"), dk.get("bus"))
        label = dk.get("label") or dk.get("provider") or {"removable": "Removable disk", "internal": "Local disk", "network": "Network drive", "optical": "Optical drive"}.get(kind, "Drive")
        if wsl:
            mounted = drive_mounted(letter, mounts_text, mnt_dir) and media
            path = f"{mnt_dir}/{letter.lower()}" if mounted else ""
        else:
            mounted, path = media, f"{letter}:\\" if media else ""
        row = {"name": f"{letter}: {label}", "path": path, "dir": True, "kind": "drive", "windows": f"{letter}:\\", "mounted": mounted, "media": media, "type": kind, "label": label,
               "total": total, "free": free, "used": (total - free) if media and free is not None else None, "fs": dk.get("fs")}
        if wsl and media and not mounted:
            row["hint"] = mount_command(letter)
        rows.append(row)
    return rows


def pc_places(platform: str | None = None, wsl: bool | None = None, env=None, mounts_text: str | None = None, mnt_dir: str = "/mnt", free=_free, disks: list | None = None) -> list:
    """"This PC": native Windows drive letters; WSL the Windows drives; Linux /mnt, /media/$USER, /run/media/$USER mounts; macOS /Volumes."""
    env = os.environ if env is None else env
    platform = platform or ("windows" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux")
    wsl = in_wsl() if wsl is None else wsl
    if disks and (platform == "windows" or (platform == "linux" and wsl)):
        return windows_drive_rows(disks, platform != "windows", mounts_text, mnt_dir)
    if platform == "windows":
        import string
        return [{"name": f"{d}:", "path": f"{d}:\\", "dir": True, "free": free(f"{d}:\\"), "kind": "drive"} for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
    if platform == "mac":
        base = Path("/Volumes")
        return [{"name": c.name, "path": str(c), "dir": True, "free": free(str(c)), "kind": "drive"} for c in sorted(base.iterdir()) if c.is_dir()] if base.is_dir() else []
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


def windows_home(users_dir: str = "/mnt/c/Users", env=None) -> str:
    """WSL: the Windows user's profile folder as Ubuntu sees it (/mnt/c/Users/<name>): the folder named like $USER / $LOGNAME, else the only real profile there."""
    env = os.environ if env is None else env
    try:
        names = [c.name for c in Path(users_dir).iterdir() if c.is_dir() and c.name.lower() not in ("public", "default", "default user", "all users", "defaultuser0") and (c / "Desktop").exists()]
    except OSError:
        return ""
    for key in ("USER", "LOGNAME", "USERNAME"):
        for n in names:
            if env.get(key) and n.lower() == env[key].lower():
                return str(Path(users_dir) / n)
    return str(Path(users_dir) / names[0]) if len(names) == 1 else ""


def quick_places(root, workspace, data_dir=None, wsl: bool = False, users_dir: str = "/mnt/c/Users") -> list:
    """Home, Desktop, Documents, Downloads (in WSL also the Windows ones), the workspace, the PlasBench folder and the shared data folder: those that exist."""
    home = Path.home()
    out = [{"name": "Home", "path": str(home), "dir": True, "kind": "place"}]
    for n in ("Desktop", "Documents", "Downloads"):
        out.append({"name": n, "path": str(home / n), "dir": True, "kind": "place"})
    if wsl:
        wh = windows_home(users_dir)
        for n in ("Desktop", "Documents", "Downloads"):
            if wh:
                out.append({"name": f"Windows {n}", "path": str(Path(wh) / n), "dir": True, "kind": "place"})
    out += [{"name": "Workspace (studies)", "path": str(workspace), "dir": True, "kind": "place"}, {"name": "PlasBench folder", "path": str(root), "dir": True, "kind": "place"}]
    if data_dir and Path(data_dir).is_dir():
        out.append({"name": "Shared data folder", "path": str(data_dir), "dir": True, "kind": "place"})
    seen, res = set(), []
    for p in out:
        if Path(p["path"]).is_dir() and p["path"] not in seen:
            seen.add(p["path"])
            res.append(p)
    return res


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
