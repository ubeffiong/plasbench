#!/usr/bin/env python3
"""Ask the operating system not to put the computer to sleep while a PlasBench run is active, and let go when the run ends or dies.

What it does and does not do
  - It asks for "system required" only: the screen may still turn off. Nothing outside the run's life is changed: the request is released when the run ends, when
    the run's process disappears (a watchdog checks it) and automatically if this helper is killed (Windows drops the request with its thread, systemd and
    caffeinate watch the run's pid themselves, the WSL helper ends when its input pipe closes).
  - It needs NO administrator rights: SetThreadExecutionState (Windows), a "sleep" delay inhibitor of systemd-inhibit (Linux, normally allowed for the logged-in
    user) and caffeinate (macOS) are all ordinary user calls. It does not change any power setting.
  - It is a request. Windows "Modern Standby" laptops can still sleep on a lid close or battery saver however the request is made; the suspend detector
    (awake_clock.py) then records the pause so it is never reported as slowness.

Methods (first that applies):
  windows   native Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) on a thread of this helper (ctypes)
  wsl       WSL with Windows interop: powershell.exe calls SetThreadExecutionState and waits on its standard input
  linux     systemd-inhibit --what=sleep around a loop that ends with the run
  macos     caffeinate -i -w <pid>
  none      nothing available: a plain note says what to set instead (never an error)

KEEP_AWAKE=0 turns it off. PB_KEEP_AWAKE_PLATFORM (windows|wsl|linux|macos) overrides the detection, for tests.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import threading
import time

NOTE_ON = "keeping this computer awake while the run is active; it can still turn the screen off"
NOTE_OFF = "KEEP_AWAKE=0: not asking the computer to stay awake; if it goes to sleep the run pauses and is reported as paused, not slow"
NOTE_NONE = ("cannot prevent sleep here: set Windows power settings: powercfg /change standby-timeout-ac 0 (and standby-timeout-dc 0 on battery); "
             "if the computer sleeps the run pauses and is reported as paused, not slow")
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

POWERSHELL_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "Add-Type -Namespace PB -Name Pw -MemberDefinition '[DllImport(\"kernel32.dll\")] public static extern uint SetThreadExecutionState(uint f);';"
    "$r=[PB.Pw]::SetThreadExecutionState([uint32]2147483649);"
    "if($r -eq 0){Write-Output 'PB_KEEP_AWAKE_FAILED'; exit 1};"
    "Write-Output 'PB_KEEP_AWAKE_ON';"
    "try{ while($null -ne [Console]::In.ReadLine()){} } finally { [void][PB.Pw]::SetThreadExecutionState([uint32]2147483648) }")


def is_wsl():
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def platform_name(environ=None):
    environ = os.environ if environ is None else environ
    forced = (environ.get("PB_KEEP_AWAKE_PLATFORM") or "").strip().lower()
    if forced:
        return forced
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "wsl" if is_wsl() else "linux"


def enabled(environ=None):
    environ = os.environ if environ is None else environ
    return str(environ.get("KEEP_AWAKE", "1")).strip().lower() not in ("0", "no", "off", "false")


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259                                         # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                   # a finished process nobody has collected yet (a zombie) is not running
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            return handle.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


class Holder:
    """One request not to sleep. start() returns (method, note); stop() releases it. Never raises."""

    def __init__(self, pid, environ=None, which=shutil.which):
        self.pid, self.environ, self.which = pid, os.environ if environ is None else environ, which
        self.method, self.process, self._thread, self._stop = "none", None, None, threading.Event()

    def start(self):
        if not enabled(self.environ):
            return "off", NOTE_OFF
        kind = platform_name(self.environ)
        try:
            if kind == "windows" and self._start_windows():
                return self._on("windows")
            if kind == "wsl" and self._start_powershell():
                return self._on("wsl")
            if kind == "linux" and self._start_inhibit():
                return self._on("linux")
            if kind == "macos" and self._start_caffeinate():
                return self._on("macos")
        except Exception:  # noqa: BLE001 - keeping awake is a convenience: it must never stop a run
            pass
        return "none", NOTE_NONE if kind in ("wsl", "windows") else (
            "cannot prevent sleep here (no systemd-inhibit or caffeinate): turn off automatic sleep in the system's power settings for long runs; "
            "if the computer sleeps the run pauses and is reported as paused, not slow")

    def _on(self, method):
        self.method = method
        return method, NOTE_ON

    def _start_windows(self):
        import ctypes

        def hold():
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            self._stop.wait()
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

        self._thread = threading.Thread(target=hold, daemon=True)
        self._thread.start()
        return True

    def _start_powershell(self):
        exe = self.which("powershell.exe") or self.which("pwsh.exe")
        if not exe:
            return False
        encoded = base64.b64encode(POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")      # no shell-quoting trouble through the WSL interop
        self.process = subprocess.Popen([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        answer = {}

        def read():
            answer["line"] = (self.process.stdout.readline() or "").strip()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(float(self.environ.get("PB_KEEP_AWAKE_START_TIMEOUT", "30")))
        if answer.get("line") != "PB_KEEP_AWAKE_ON":
            self._kill()
            return False
        return True

    def _start_inhibit(self):
        exe = self.which("systemd-inhibit")
        if not exe:
            return False
        waiter = f'while kill -0 {int(self.pid)} 2>/dev/null; do sleep 5; done'
        self.process = subprocess.Popen([exe, "--what=sleep", "--who=PlasBench", "--why=A PlasBench run is active", "--mode=block", "sh", "-c", waiter],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)
        if self.process.poll() not in (None, 0):          # refused (no permission, no logind): not an error, just no inhibitor
            self.process = None
            return False
        return True

    def _start_caffeinate(self):
        exe = self.which("caffeinate")
        if not exe:
            return False
        self.process = subprocess.Popen([exe, "-i", "-w", str(int(self.pid))], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def _kill(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        self._kill()
        self.method = "none"


if __name__ == "__main__":
    print(__doc__)
