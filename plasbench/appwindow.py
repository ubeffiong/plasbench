"""Open the PlasBench window as an app-style window (no tabs or address bar), after GenoSuv's appwindow.py.

A Chromium-based browser (Edge or Chrome) in --app mode, with its own profile so it never touches the user's normal
browser windows, sized to 2/3 of the screen width and 3/4 of its height, centred (the normal maximise button works).
Inside WSL2 it starts the WINDOWS browser (localhost is forwarded from WSL2 to Windows). With no Chromium browser, the
default browser opens the page in a tab.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

WIDTH_FRAC, HEIGHT_FRAC = 0.66, 0.78


def screen_size() -> tuple:
    try:
        if os.name == "nt":
            import ctypes
            u = ctypes.windll.user32
            return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        if sys.platform == "darwin":
            out = subprocess.run(["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
                                 capture_output=True, text=True, timeout=5).stdout.replace(",", " ").split()
            return int(out[2]), int(out[3])
        out = subprocess.run(["xdpyinfo"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"dimensions:\s+(\d+)x(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:  # noqa: BLE001
        pass
    return 1920, 1080


def window_geometry(sw: int, sh: int) -> tuple:
    w, h = max(1100, int(sw * WIDTH_FRAC)), max(720, int(sh * HEIGHT_FRAC))
    w, h = min(w, sw), min(h, sh)
    return w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 2)


def _in_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def find_browser():
    """(executable, is_windows_exe_from_wsl) or (None, False)."""
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        cands = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                 Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                 Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    elif _in_wsl():
        for base in ("/mnt/c/Program Files (x86)", "/mnt/c/Program Files"):
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
        for c in cands:
            if c.exists():
                return str(c), True
        return None, False
    for c in cands:
        if c.exists():
            return str(c), False
    for name in ("microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found, False
    return None, False


def _windows_profile_dir() -> str:
    """From WSL, the app profile must be a Windows path (the browser is a Windows program)."""
    try:
        out = subprocess.run(["cmd.exe", "/c", "echo", "%LOCALAPPDATA%"], capture_output=True, text=True, timeout=10,
                             cwd="/mnt/c").stdout.strip()
        if out and "%" not in out:
            return out + "\\PlasBench\\app-window"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def open_app_window(url: str, profile_dir: Path, tab: bool = False) -> str:
    """Open the window; returns a short description of what was opened."""
    if not tab:
        exe, from_wsl = find_browser()
        if exe:
            w, h, x, y = window_geometry(*screen_size())
            profile = _windows_profile_dir() if from_wsl else str(profile_dir)
            if not from_wsl:
                Path(profile).mkdir(parents=True, exist_ok=True)
            args = [exe, f"--app={url}", f"--window-size={w},{h}", f"--window-position={x},{y}",
                    "--no-first-run", "--no-default-browser-check"] + ([f"--user-data-dir={profile}"] if profile else [])
            try:
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                 start_new_session=os.name != "nt")
                return f"app window via {Path(exe).name}" + (" (Windows, from WSL)" if from_wsl else "")
            except OSError:
                pass
    if _in_wsl() and shutil.which("wslview"):
        subprocess.Popen(["wslview", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Windows default browser (wslview)"
    webbrowser.open(url)
    return "default browser"
