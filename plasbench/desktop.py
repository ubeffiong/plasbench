"""`plasbench desktop-icon`: a PlasBench icon on the desktop and in the applications menu, on every kind of computer.

Clicking it starts PlasBench (scripts/plasbench_launcher.sh: finds and activates the plasbench conda environment, then
`plasbench ui`) and opens its window; if PlasBench is already running it only brings the window back.

  Linux                    ~/.local/share/applications/plasbench.desktop (applications menu) and a copy on the desktop
  macOS                    ~/Applications/PlasBench.app, and a link to it on the desktop
  Windows, PlasBench in WSL a Windows desktop + Start-menu shortcut that runs the launcher inside that WSL distribution
  Windows, native          a desktop + Start-menu shortcut to %LOCALAPPDATA%\\PlasBench\\PlasBench.cmd

The icon itself (a plasmid map) is drawn here and written as PNG, ICO and ICNS: nothing is downloaded. install.sh calls
this; `plasbench desktop-icon --remove` takes everything away again.
"""
from __future__ import annotations

import math
import os
import plistlib
import shlex
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ICON_DIR = Path(os.environ.get("PLASBENCH_UI_HOME", Path.home() / ".plasbench" / "ui")).parent / "icons"
APP_NAME = "PlasBench"
COMMENT = "Benchmark plasmid reconstruction tools"


# ------------------------------------------------------------------------------------------------ the icon
# The same geometry as plasbench/data/logo.svg (a 64-unit square): a plasmid map, backbone ring with two gene arcs and an
# origin tick, holding three rising benchmark bars. Drawn with signed distances, so every size is sharp and anti-aliased.
RING_R, RING_W, ARC_W = 22.0, 4.5, 9.0
ARCS = ((25.0, 115.0), (210.0, 255.0))            # degrees clockwise from 12 o'clock
TICK = (32.0, 10.0, 1.4, 5.0)                     # centre x, centre y, half width, half height
BARS = (((24.5, 38.5, 2.5, 4.5), (157, 187, 224)),
        ((32.0, 35.5, 2.5, 7.5), (79, 134, 194)),
        ((39.5, 32.5, 2.5, 10.5), (29, 95, 167)))
BLUE, DARK, TILE_LINE = (29, 95, 167), (18, 63, 114), (200, 210, 222)
MARK_SCALE = 0.84                                  # the mark inside the white tile, as in docs/images/plasbench-icon.svg


def _box(px, py, cx, cy, hx, hy, r=0.0):
    qx, qy = abs(px - cx) - hx + r, abs(py - cy) - hy + r
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _cover(dist_px):
    return min(1.0, max(0.0, 0.5 - dist_px))


def _over(dst, rgb, a):
    return tuple(round(rgb[i] * a + dst[i] * (1 - a)) for i in range(3))


def icon_rgba(size: int = 256, tile: bool = True) -> bytes:
    """RGBA pixels of the PlasBench icon: the mark on a white rounded tile (tile=False: the mark alone)."""
    unit = size / 64.0                              # pixels per tile unit
    scale = MARK_SCALE if tile else 1.0
    mpx = unit * scale                              # pixels per mark unit
    out = bytearray()
    for y in range(size):
        for x in range(size):
            u, v = (x + 0.5) / unit, (y + 0.5) / unit
            if tile:
                a_tile = _cover(_box(u, v, 32, 32, 30, 30, 13) * unit)
                if a_tile <= 0:
                    out += b"\0\0\0\0"
                    continue
                border = _cover((abs(_box(u, v, 32, 32, 30, 30, 13)) - 0.5) * unit)
                col = _over((255, 255, 255), TILE_LINE, border)
            else:
                a_tile, col = 0.0, (255, 255, 255)
            mx, my = 32 + (u - 32) / scale, 32 + (v - 32) / scale
            d = math.hypot(mx - 32, my - 32)
            ang = (math.degrees(math.atan2(mx - 32, 32 - my)) + 360) % 360
            ring = _cover((abs(d - RING_R) - RING_W / 2) * mpx)
            in_arc = any(a0 <= ang <= a1 for a0, a1 in ARCS)
            arc = _cover((abs(d - RING_R) - ARC_W / 2) * mpx) if in_arc else 0.0
            tick = _cover(_box(mx, my, *TICK) * mpx)
            layers = [(BLUE, ring), (DARK, arc), (DARK, tick)]
            layers += [(rgb, _cover(_box(mx, my, *b, r=1.0) * mpx)) for b, rgb in BARS]
            alpha = a_tile
            for rgb, a in layers:
                if a > 0:
                    col = _over(col, rgb, a)
                    alpha = alpha + a * (1 - alpha)
            if not tile and alpha > 0:              # un-premultiply against the white we composited over
                col = tuple(min(255, max(0, round((c - 255 * (1 - alpha)) / alpha))) for c in col)
            out += bytes((*col, round(255 * alpha)))
    return bytes(out)


def png_bytes(size: int = 256, tile: bool = True) -> bytes:
    raw = icon_rgba(size, tile)
    rows = b"".join(b"\0" + raw[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def ico_bytes() -> bytes:
    """A Windows icon holding a 256x256 PNG (Windows Vista and later) and a 48x48 PNG."""
    images = [(256, png_bytes(256)), (48, png_bytes(48))]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, png in images:
        entries += struct.pack("<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size, 0, 0, 1, 32,
                               len(png), offset + len(data))
        data += png
    return header + entries + data


def icns_bytes() -> bytes:
    """A macOS icon: 256x256 ('ic08') and 512x512 ('ic09') PNG entries."""
    body = b""
    for kind, size in ((b"ic08", 256), (b"ic09", 512)):
        png = png_bytes(size)
        body += kind + struct.pack(">I", len(png) + 8) + png
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def write_icons(folder: Path = ICON_DIR) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    files = {"png": folder / "plasbench.png", "ico": folder / "plasbench.ico", "icns": folder / "plasbench.icns"}
    files["png"].write_bytes(png_bytes(256))
    files["ico"].write_bytes(ico_bytes())
    if sys.platform == "darwin":
        files["icns"].write_bytes(icns_bytes())
    return files


# ------------------------------------------------------------------------------------------------ where am I
def in_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kw)


def _launcher(root: Path) -> Path:
    return Path(root).resolve() / "scripts" / "plasbench_launcher.sh"


# ------------------------------------------------------------------------------------------------ Linux
def linux_entry(root: Path, icon: Path) -> str:
    return "\n".join([
        "[Desktop Entry]", "Type=Application", "Version=1.0", f"Name={APP_NAME}", f"Comment={COMMENT}",
        f"Exec=bash {shlex.quote(str(_launcher(root)))}", f"Icon={icon}", "Terminal=false",
        "Categories=Science;Biology;Education;", "StartupNotify=true", "StartupWMClass=PlasBench", ""])


def linux_desktop_dir() -> Path:
    try:
        out = _run(["xdg-user-dir", "DESKTOP"]).stdout.strip()
        if out and Path(out).is_dir() and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.home() / "Desktop"


def install_linux(root: Path, icons: dict, desktop: bool = True) -> list:
    made = []
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "plasbench.desktop"
    entry.write_text(linux_entry(root, icons["png"]), encoding="utf-8")
    entry.chmod(0o755)
    made.append(str(entry))
    if desktop and linux_desktop_dir().is_dir():
        copy = linux_desktop_dir() / "plasbench.desktop"
        shutil.copyfile(entry, copy)
        copy.chmod(0o755)
        if shutil.which("gio"):                  # GNOME: allow launching without the "untrusted" prompt
            _run(["gio", "set", str(copy), "metadata::trusted", "true"])
        made.append(str(copy))
    if shutil.which("update-desktop-database"):
        _run(["update-desktop-database", str(apps)])
    return made


# ------------------------------------------------------------------------------------------------ macOS
def install_macos(root: Path, icons: dict, desktop: bool = True) -> list:
    app = Path.home() / "Applications" / f"{APP_NAME}.app"
    macos_dir, res = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    exe = macos_dir / APP_NAME
    exe.write_text("#!/bin/bash\n# PlasBench: start it (or bring its window back).\n"
                   f"exec /bin/bash {shlex.quote(str(_launcher(root)))}\n", encoding="utf-8")
    exe.chmod(0o755)
    shutil.copyfile(icons["icns"], res / "plasbench.icns")
    with open(app / "Contents" / "Info.plist", "wb") as handle:
        plistlib.dump({"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME, "CFBundleExecutable": APP_NAME,
                       "CFBundleIdentifier": "org.plasbench.window", "CFBundleIconFile": "plasbench.icns",
                       "CFBundlePackageType": "APPL", "CFBundleShortVersionString": _version(),
                       "LSUIElement": False, "NSHighResolutionCapable": True}, handle)
    made = [str(app)]
    link = Path.home() / "Desktop" / f"{APP_NAME}.app"
    if desktop and link.parent.is_dir():
        if link.is_symlink() or link.exists():
            link.unlink() if link.is_symlink() else None
        if not link.exists():
            link.symlink_to(app)
            made.append(str(link))
    return made


# ------------------------------------------------------------------------------------------------ Windows
PS_SHORTCUT = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$made = @()
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) '')) ) {
  if ($env:PB_NO_DESKTOP -eq '1' -and $folder -eq [Environment]::GetFolderPath('Desktop')) { continue }
  $lnk = Join-Path $folder 'PlasBench.lnk'
  $s = $shell.CreateShortcut($lnk)
  $s.TargetPath = $env:PB_TARGET
  $s.Arguments = $env:PB_ARGS
  $s.WorkingDirectory = $env:PB_WORKDIR
  $s.IconLocation = $env:PB_ICON
  $s.Description = 'Benchmark plasmid reconstruction tools'
  $s.WindowStyle = 7
  $s.Save()
  $made += $lnk
}
$made -join "`n"
"""


def _powershell():
    return shutil.which("powershell.exe") or shutil.which("powershell") or ("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
                                                                             if Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe").exists() else None)


def _make_shortcuts(target: str, args: str, workdir: str, icon: str, desktop: bool) -> list:
    ps = _powershell()
    if not ps:
        raise RuntimeError("PowerShell was not found, so no Windows shortcut could be made")
    env = dict(os.environ, PB_TARGET=target, PB_ARGS=args, PB_WORKDIR=workdir, PB_ICON=icon,
               PB_NO_DESKTOP="" if desktop else "1")
    if in_wsl():   # pass the values through to the Windows process
        env["WSLENV"] = ":".join(filter(None, [os.environ.get("WSLENV", ""), "PB_TARGET", "PB_ARGS", "PB_WORKDIR",
                                                "PB_ICON", "PB_NO_DESKTOP"]))
    p = _run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", PS_SHORTCUT], env=env,
             cwd="/mnt/c" if in_wsl() else None)
    if p.returncode != 0:
        raise RuntimeError("PowerShell could not make the shortcut: " + (p.stderr or p.stdout).strip()[-400:])
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def _windows_localappdata_from_wsl():
    p = _run(["cmd.exe", "/c", "echo", "%LOCALAPPDATA%"], cwd="/mnt/c")
    win = p.stdout.strip()
    if not win or "%" in win:
        raise RuntimeError("could not find the Windows user folder from WSL")
    unix = _run(["wslpath", "-u", win]).stdout.strip()
    return win, Path(unix)


def install_windows_from_wsl(root: Path, icons: dict, desktop: bool = True) -> list:
    win_dir, unix_dir = _windows_localappdata_from_wsl()
    folder = unix_dir / "PlasBench"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icons["ico"], folder / "plasbench.ico")
    distro = os.environ.get("WSL_DISTRO_NAME", "")
    launcher = shlex.quote(str(_launcher(root)))
    args = (f"-d {distro} " if distro else "") + f'--cd ~ -- bash -lc "bash {launcher}"'
    return _make_shortcuts("C:\\Windows\\System32\\wsl.exe", args, "C:\\Windows\\System32",
                           f"{win_dir}\\PlasBench\\plasbench.ico", desktop)


def install_windows_native(root: Path, icons: dict, desktop: bool = True) -> list:
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "PlasBench"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icons["ico"], folder / "plasbench.ico")
    cmd = folder / "PlasBench.cmd"
    cmd.write_text("@echo off\r\nrem PlasBench: start it (or bring its window back). Written by plasbench desktop-icon.\r\n"
                   f'"{sys.executable}" -m plasbench --project-root "{Path(root).resolve()}" ui\r\n', encoding="utf-8")
    return [str(cmd)] + _make_shortcuts(str(cmd), "", str(Path(root).resolve()), str(folder / "plasbench.ico"), desktop)


# ------------------------------------------------------------------------------------------------ entry points
def _version() -> str:
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "0"


def install(root, desktop: bool = True) -> dict:
    """Make the icon for this computer. Returns {'platform', 'made': [paths], 'note'}."""
    root = Path(root).resolve()
    icons = write_icons()
    if os.name == "nt":
        return {"platform": "Windows", "made": install_windows_native(root, icons, desktop),
                "note": "Benchmark runs need the tools that only WSL2 provides on Windows; see Set up this computer."}
    if in_wsl():
        made = install_windows_from_wsl(root, icons, desktop)
        try:
            made += install_linux(root, icons, desktop=False)   # also in WSLg's Linux application menu
        except OSError:
            pass
        return {"platform": "Windows (PlasBench inside WSL)", "made": made, "note": ""}
    if sys.platform == "darwin":
        return {"platform": "macOS", "made": install_macos(root, icons, desktop), "note": ""}
    return {"platform": "Linux", "made": install_linux(root, icons, desktop), "note": ""}


def remove() -> list:
    removed = []
    cands = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications" / "plasbench.desktop",
             Path.home() / "Desktop" / "plasbench.desktop", Path.home() / "Applications" / f"{APP_NAME}.app",
             Path.home() / "Desktop" / f"{APP_NAME}.app"]
    if os.name != "nt" and not in_wsl() and sys.platform != "darwin":
        cands.append(linux_desktop_dir() / "plasbench.desktop")
    for p in cands:
        if p.is_symlink() or p.is_file():
            p.unlink()
            removed.append(str(p))
        elif p.is_dir() and p.suffix == ".app":
            shutil.rmtree(p)
            removed.append(str(p))
    if os.name == "nt" or in_wsl():
        ps = _powershell()
        if ps:
            script = ("foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) "
                      "{ $l = Join-Path $f 'PlasBench.lnk'; if (Test-Path $l) { Remove-Item $l; $l } }")
            p = _run([ps, "-NoProfile", "-NonInteractive", "-Command", script], cwd="/mnt/c" if in_wsl() else None)
            removed += [line.strip() for line in p.stdout.splitlines() if line.strip()]
    return removed


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="plasbench desktop-icon", description=__doc__.splitlines()[0])
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--no-desktop", action="store_true", help="Applications menu / Start menu only, not the desktop.")
    args = ap.parse_args(argv)
    if args.remove:
        gone = remove()
        print("Removed:\n  " + "\n  ".join(gone) if gone else "No PlasBench icon was found.")
        return 0
    try:
        res = install(args.project_root, desktop=not args.no_desktop)
    except (OSError, RuntimeError) as exc:
        print(f"Could not make the PlasBench icon: {exc}", file=sys.stderr)
        return 1
    print(f"PlasBench icon for {res['platform']}:\n  " + "\n  ".join(res["made"]))
    if res["note"]:
        print(res["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
