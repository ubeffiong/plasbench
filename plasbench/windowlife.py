"""Window stability: which PlasBench windows are open, what the served page may contain, and bringing an open window back instead of opening another.

Three small, separately testable parts (webui.py wires them in):

  * render_page(): the ONLY place the server fills the page's placeholders (__VERSION__, __PAGE_VERSION__, __API_LEVEL__). The substitution is a plain text replace over the whole file, so a
    placeholder spelled anywhere else in ui.html (a regular expression, a comment) would be rewritten too: v0.5.5 shipped `/^__API_LEVEL__$/.test(...)`, which became `/^2$/.test("2")` and
    showed "program files changed" on every load of a healthy server. test/test_window_stability.py renders the real page and checks every placeholder appears only where it is meant to.
  * Registry: a window pings the server every ~10 s with a random id (sessionStorage); a window is alive when its last ping is recent. `plasbench ui` asks it before opening another window.
  * bring_to_front(): best effort, per platform, to raise the already-open window ('PlasBench' in the title bar).

Nothing here holds a key; the registry holds random window ids and times only.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

PLACEHOLDERS = ("__VERSION__", "__PAGE_VERSION__", "__API_LEVEL__")
# where each placeholder is meant to appear in plasbench/data/ui.html (the test counts them in the source and in the served page)
ALLOWED_PLACEHOLDER_COUNTS = {"__VERSION__": 2, "__PAGE_VERSION__": 1, "__API_LEVEL__": 1}   # meta + the title line; meta; meta
VISIBLE_SECONDS = 25.0      # a visible window pings every 10 s
HIDDEN_SECONDS = 150.0      # a minimised or background window's timers are throttled by the browser (about once a minute)
REOPEN_EVERY = 10.0         # the token-free /api/reopen helps at most once per this many seconds


def render_page(html: str, version: str, disk_version: str, api_level) -> str:
    """The page as served. __PAGE_VERSION__ first (it contains __VERSION__ no more, but the order is kept explicit)."""
    return html.replace("__PAGE_VERSION__", disk_version or version).replace("__API_LEVEL__", str(api_level)).replace("__VERSION__", version)


class Registry:
    """The windows that pinged recently. Thread-safe; bounded."""

    def __init__(self, clock=time.time, limit: int = 64):
        self.clock = clock
        self.limit = limit
        self.lock = threading.Lock()
        self.seen = {}      # id -> (last ping, visible)

    def ping(self, window_id, visible=True) -> int:
        wid = str(window_id or "")
        if not wid or len(wid) > 64 or not all(c.isalnum() or c in "-_" for c in wid):
            raise ValueError("a window id is 1-64 letters, digits, - or _")
        now = self.clock()
        with self.lock:
            self.seen[wid] = (now, bool(visible))
            self._prune(now)
            return len(self._alive(now))

    def _alive(self, now):
        return [w for w, (t, vis) in self.seen.items() if now - t < (VISIBLE_SECONDS if vis else HIDDEN_SECONDS)]

    def _prune(self, now):
        for w in [w for w, (t, _v) in self.seen.items() if now - t > HIDDEN_SECONDS * 4]:
            del self.seen[w]
        while len(self.seen) > self.limit:
            del self.seen[min(self.seen, key=lambda w: self.seen[w][0])]

    def alive(self) -> list:
        with self.lock:
            return sorted(self._alive(self.clock()))

    def count(self) -> int:
        return len(self.alive())


class RateLimit:
    """At most one True per `every` seconds."""

    def __init__(self, every: float = REOPEN_EVERY, clock=time.time):
        self.every, self.clock, self.last = every, clock, None
        self.lock = threading.Lock()

    def allow(self) -> bool:
        now = self.clock()
        with self.lock:
            if self.last is not None and now - self.last < self.every:
                return False
            self.last = now
            return True


def bring_to_front(title: str = "PlasBench", platform: str = None, env=None, which=shutil.which, run=subprocess.run, find_powershell=None) -> bool:
    """Raise the open window whose title bar says `title`. True when the platform tool reported success; False when nothing could be done (the caller then only says it is open)."""
    from . import native_picker
    env = os.environ if env is None else env
    plat = native_picker._platform(platform)
    try:
        if plat in ("windows", "wsl"):
            exe, _tried = (find_powershell or native_picker.find_powershell)(env, which, plat=plat)
            if not exe:
                return False
            script = ("$s = New-Object -ComObject WScript.Shell; "
                      f"if ($s.AppActivate('{title}')) {{ 'activated' }} else {{ 'none' }}")
            done = run(native_picker.encoded_argv(exe, script), capture_output=True, text=True, timeout=15)
            return "activated" in (done.stdout or "")
        if plat == "mac":
            exe = which("osascript")
            if not exe:
                return False
            for app in ("Microsoft Edge", "Google Chrome", "Chromium"):   # only a browser that is already running is activated (never started)
                done = run([exe, "-e", f'if application "{app}" is running then tell application "{app}" to activate'], capture_output=True, text=True, timeout=10)
                if done.returncode == 0 and "is running" not in (done.stderr or ""):
                    return True
            return False
        for tool, argv in (("wmctrl", ["-a", title]), ("xdotool", ["search", "--name", title, "windowactivate"])):
            exe = which(tool)
            if exe and run([exe] + argv, capture_output=True, text=True, timeout=10).returncode == 0:
                return True
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return False
