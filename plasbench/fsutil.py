"""Open a folder in the computer's file manager, from the setup window ("Open folder").

`open_command` only CHOOSES the program (testable with a mocked `which`, platform and WSL flag); `reveal` runs it. A missing program is never an error
(never FileNotFoundError): the answer says `{"ok": false, "opened": false, "reason": "no file manager is available here"}` and the window shows the path
with a Copy button. A missing PATH is the caller's 404.

Order: Windows `explorer` (selects a file, opens a folder); macOS `open`; WSL `wslview`, else `explorer.exe` with the path converted by `wslpath -w` (explorer.exe
exits 1 even when it worked, so its exit code is never read); then `xdg-open`, `gio open`, `kde-open`, `gnome-open`, whichever exists.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

NO_MANAGER = "no file manager is available here"


def in_wsl() -> bool:
    """True inside Windows Subsystem for Linux (the same test as plasbench/appwindow.py)."""
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def wslpath_windows(path: str, run=subprocess.run) -> str | None:
    """The Windows spelling of a WSL path (`wslpath -w`), or None when it cannot be converted within 5 seconds."""
    try:
        done = run(["wslpath", "-w", path], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (getattr(done, "stdout", "") or "").strip()
    return text if getattr(done, "returncode", 1) == 0 and text else None


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def open_command(path, platform: str | None = None, which=None, wsl: bool | None = None, wslpath=None):
    """The argv that shows `path` in a file manager, or None when nothing here can. A file is selected in its folder where the manager supports it."""
    platform = platform or platform_name()
    which = which or shutil.which
    wslpath = wslpath or wslpath_windows
    target = Path(str(path))
    is_file = target.is_file()
    folder = str(target.parent if is_file else target)
    if platform == "windows":
        return ["explorer", "/select,", str(target)] if is_file else ["explorer", str(target)]
    if platform == "mac":
        return ["open", "-R", str(target)] if is_file else ["open", str(target)]
    wsl = in_wsl() if wsl is None else wsl
    if wsl:
        if which("wslview"):
            return ["wslview", folder]
        if which("explorer.exe"):
            win = wslpath(str(target if is_file else folder))
            if win:
                return ["explorer.exe", "/select,", win] if is_file else ["explorer.exe", win]
    for argv in (["xdg-open"], ["gio", "open"], ["kde-open"], ["gnome-open"]):
        if which(argv[0]):
            return argv + [folder]
    return None


def reveal(path, popen=subprocess.Popen, **kwargs) -> dict:
    """Open `path` (which must exist; the caller answers 404 otherwise). Returns the JSON the window shows; never raises for a missing program."""
    argv = open_command(path, **kwargs)
    base = {"path": str(path)}
    if not argv:
        return dict(base, ok=False, opened=False, reason=NO_MANAGER)
    try:
        popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return dict(base, ok=False, opened=False, reason=f"{argv[0]} could not be started: {exc.strerror or exc}")
    return dict(base, ok=True, opened=True, opener=argv[0])


def reveal_typed(text, popen=subprocess.Popen, which=None, wsl: bool | None = None, **kwargs) -> dict:
    r"""The window's "Open in Explorer" next to a path box: `text` is whatever is in the box (a Linux path, C:\x, \\wsl.localhost\..., a pasted Explorer path).
    A path that exists opens as `reveal` does (WSL: wslview, else explorer.exe with `wslpath -w`, so /mnt/<drive> and \wsl.localhost paths work). A Windows drive that is plugged in
    but not mounted in Ubuntu has no Linux path: its Windows letter (E:\...) is opened with explorer.exe. Raises FileNotFoundError / ValueError for the caller's 404 / 400."""
    from . import chooser
    which = which or shutil.which
    wsl = in_wsl() if wsl is None else wsl
    raw = chooser.normalize_typed(text)
    m = chooser.DRIVE_RE.match(raw)
    if wsl and m:
        linux = chooser.to_linux(raw, wsl=True)
        if Path(linux).exists() and chooser.drive_mounted(m.group(1)):
            return reveal(linux, popen=popen, which=which, wsl=True, **kwargs)
        exe = which("explorer.exe")
        if not exe:
            raise FileNotFoundError(chooser.mount_help(m.group(1)))
        win = m.group(1).upper() + ":" + (m.group(2) or "\\").replace("/", "\\")
        try:
            popen([exe, win], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return {"path": win, "ok": False, "opened": False, "reason": f"explorer.exe could not be started: {exc.strerror or exc}"}
        return {"path": win, "ok": True, "opened": True, "opener": "explorer.exe", "windows": True}
    path = chooser.to_linux(raw, wsl=wsl)
    if not Path(path).expanduser().exists():
        raise FileNotFoundError(f"{path} does not exist")
    return reveal(Path(path).expanduser(), popen=popen, which=which, wsl=wsl, **kwargs)
