"""`plasbench picker-check`: why does (or does not) Browse open the computer's own folder window?

Runs the whole chain one step at a time and says PASS or FAIL for each with the exact error: what kind of computer this is, whether WSL interop is on, which
powershell.exe is used, a minimal PowerShell script, a C# compile test, the real folder window opened and closed again after a few seconds (or, with
--interactive, left open for you to choose a folder and report what came back), the conversion to a Linux path, and what the window will do when you press Browse.
The same checks run from the window (Settings > Test the folder window), so a failure can be pasted into a bug report as it is.

Every system fact is an argument (like native_picker), so tests drive each environment with fakes. Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from . import chooser, docker_helper, native_picker as np

PASS, FAIL, INFO, NA = "PASS", "FAIL", "INFO", "n/a"


def environment_kind(plat: str, caps: dict, env) -> str:
    """'docker' | 'ssh' | 'wsl' | 'windows' | 'mac' | 'linux-desktop' | 'linux-headless'."""
    if caps.get("docker"):
        return "docker"
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY") or env.get("SSH_CLIENT"):
        return "ssh"
    if plat in ("wsl", "windows", "mac"):
        return plat
    return "linux-desktop" if (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) else "linux-headless"


def _step(steps: list, name: str, status: str, detail: str = "") -> dict:
    row = {"name": name, "status": status, "detail": detail}
    steps.append(row)
    return row


def _ps(exe: str, command: str, run, timeout: float = 30) -> tuple:
    """(returncode, stdout, stderr) of one short PowerShell command; (None, '', error) when it could not be started or timed out."""
    try:
        got = run([exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-Command", command], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"no answer within {int(timeout)} seconds"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", str(exc)
    dec = lambda b: (b if isinstance(b, str) else (b or b"").decode("utf-8", "replace")).replace("\r", "")  # noqa: E731
    return got.returncode, dec(got.stdout), dec(got.stderr)


def _first_error(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#< CLIXML")]
    return (lines[0] if lines else "")[:300]


def _windows_checks(steps, plat, caps, exe, interactive, seconds, run, popen, which, env, wsl, timeout) -> str:
    """The PowerShell chain. Returns the window that Browse will use: 'ifiledialog' | 'winforms' | 'shell' | ''."""
    rc, out, err = _ps(exe, np.CHECK_SCRIPT, run)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if rc != 0 or not lines or lines[0] != "hello":
        _step(steps, "A minimal PowerShell script runs", FAIL,
              (_first_error(err) or f"PowerShell exited with code {rc}") + (" (WSL interop is on but starting the Windows program failed)" if plat == "wsl" else ""))
        return ""
    ps_version, lang = (lines + ["", "", ""])[1], (lines + ["", "", ""])[2]
    apartment, policy = (lines + [""] * 5)[3], (lines + [""] * 5)[4]
    _step(steps, "A minimal PowerShell script runs", PASS, f"PowerShell {ps_version}, language mode {lang}, execution policy {policy}, apartment {apartment}")
    if lang and lang != "FullLanguage":
        _step(steps, "PowerShell is not locked down", FAIL, f"language mode is {lang}: a security policy blocks the code a folder window needs; Browse will use the built-in browser")
        return ""
    rc, out, err = _ps(exe, np.COMPILE_TEST, run)
    compiled = rc == 0 and out.strip().endswith("42")
    _step(steps, "PowerShell can compile the Explorer-style window (Add-Type)", PASS if compiled else FAIL,
          "compiled and ran" if compiled else (_first_error(err) or f"exit code {rc}") + " (the older Windows folder window is tried instead)")
    script = np.windows_script("folder", "PlasBench folder window test", "", [], 60)
    routes = np.windows_routes(exe, script)
    _step(steps, "How the script reaches PowerShell", INFO,
          f"script {len(script)} characters; first route '{routes[0][0]}' ({len(routes[0][1][-1])} characters on the command line, limit {np.COMMAND_LINE_LIMIT}); fallbacks: "
          + ", ".join(r[0] for r in routes[1:]))
    for strategy, label in (("winforms", "the older Windows folder window (FolderBrowserDialog)"), ("shell", "Shell.Application BrowseForFolder")):
        res = np.pick_folder("PlasBench folder window test", None, "folder", None, 40, platform=plat, env=env, which=which, popen=popen, run=run, wsl=wsl, dry=True, strategy=strategy)
        _step(steps, f"Fallback available: {label}", PASS if res.get("ok") else FAIL, "can be created" if res.get("ok") else (res.get("error") or "")[:300])
    used = ""
    if interactive:
        print("  A folder window is opening: choose any folder (or Cancel). It waits up to 3 minutes.", flush=True)
        res = np.pick_folder("PlasBench folder window test: choose any folder", None, "folder", None, 180, platform=plat, env=env, which=which, popen=popen, run=run, wsl=wsl)
    else:
        res = np.pick_folder("PlasBench folder window test", None, "folder", None, max(30, seconds + 25), platform=plat, env=env, which=which, popen=popen, run=run, wsl=wsl, selftest=seconds)
    view = np.last_view()
    used = view.get("strategy", "")
    opened = view.get("opened")
    extra = f"window: {used or 'unknown'}, opened after {view.get('opened_after')} s, focus {view.get('focus') or 'unknown'}, route {view.get('route')}"
    if view.get("notes"):
        extra += "; notes: " + " | ".join(view["notes"][:4])
    if opened and (res.get("cancelled") or res.get("ok")):
        _step(steps, "The folder window opens" + ("" if interactive else f" and closes itself after {seconds} s"), PASS, extra)
    elif opened:
        _step(steps, "The folder window opens", FAIL, (res.get("error") or "it opened but ended with an error") + "; " + extra)
    else:
        _step(steps, "The folder window opens", FAIL, (res.get("error") or "the script never said the window was open") + "; " + extra)
        used = ""
    if view.get("focus") == "flashed":
        _step(steps, "The window comes to the front", FAIL, "Windows would not let it take the foreground; its taskbar button flashes (click it)")
    elif view.get("focus") == "foreground":
        _step(steps, "The window comes to the front", PASS, "it is the foreground window")
    if interactive:
        if res.get("ok"):
            _step(steps, "The chosen folder is returned", PASS, f"Windows path {res.get('windows_path') or res.get('display')} -> path used by PlasBench {res.get('path')}")
        elif res.get("cancelled"):
            _step(steps, "The chosen folder is returned", INFO, "you cancelled: nothing was chosen")
        else:
            _step(steps, "The chosen folder is returned", FAIL, res.get("error") or "nothing came back")
    return used


def _conversion_checks(steps, plat, run, read_exists=os.path.exists):
    if plat != "wsl":
        _step(steps, "Windows path -> Linux path conversion", NA, "only needed under WSL")
        return
    try:
        linux = chooser.to_linux("C:\\Windows", wsl=True, run=run)
        _step(steps, "Windows path -> Linux path conversion", PASS if linux.lower() == "/mnt/c/windows" else FAIL, f"C:\\Windows -> {linux}" + ("" if read_exists("/mnt/c") else "  (/mnt/c is not mounted)"))
    except (ValueError, OSError) as exc:
        _step(steps, "Windows path -> Linux path conversion", FAIL, str(exc))


def _argv_program_checks(steps, caps, plat, seconds, popen, run) -> bool:
    """zenity / kdialog / yad / osascript: the program starts and (after `seconds`) is still showing its window, which is then closed."""
    exe, kind = caps["exe"], caps["kind"]
    ver = ["--version"] if kind != "mac" else ["-e", "return 1"]
    try:
        got = run([exe] + ver, capture_output=True, timeout=15)
        text = ((got.stdout or b"") + (got.stderr or b"")).decode("utf-8", "replace").strip().splitlines()
        ok = got.returncode == 0
        _step(steps, f"{caps['via']} runs", PASS if ok else FAIL, (text[0] if text else f"exit code {got.returncode}")[:200])
        if not ok:
            return False
    except (OSError, subprocess.SubprocessError) as exc:
        _step(steps, f"{caps['via']} runs", FAIL, str(exc))
        return False
    argv = np.mac_argv(exe, "folder", "PlasBench folder window test", "", []) if kind == "mac" else np.linux_argv(kind, exe, "folder", "PlasBench folder window test", "", [])
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name != "nt":
        kw["start_new_session"] = True
    try:
        proc = popen(argv, **kw)
    except OSError as exc:
        _step(steps, "The folder window opens", FAIL, str(exc))
        return False
    end = time.time() + seconds
    while time.time() < end and proc.poll() is None:
        time.sleep(0.1)
    if proc.poll() is None:
        np._kill(proc, None, plat, exe)
        _step(steps, "The folder window opens and closes itself after %d s" % seconds, PASS, "the program was still showing its window when the test closed it")
        return True
    err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace").strip()
    _step(steps, "The folder window opens", FAIL, (_first_error(err) or f"it exited at once with code {proc.returncode}") + (" (is the desktop session reachable from this terminal?)" if plat == "linux" else ""))
    return False


def run_checks(interactive: bool = False, seconds: int = 2, *, platform: str | None = None, env=None, which=shutil.which, popen=subprocess.Popen, run=subprocess.run,
               wsl: bool | None = None, read=np._read, exists=os.path.exists, listdir=os.listdir, mounts_text: str | None = None) -> dict:
    """-> {'environment', 'steps': [{'name', 'status', 'detail'}], 'verdict': what Browse will do, 'ok': bool (nothing that matters failed), 'native': 'windows'|... or ''}."""
    env = os.environ if env is None else env
    steps: list = []
    plat = np._platform(platform, wsl)
    caps = np.capabilities(plat, env, which, wsl, exists=exists, run=run, read=read, listdir=listdir)
    kind = environment_kind(plat, caps, env)
    labels = {"docker": "Docker container", "ssh": "SSH session", "wsl": "WSL (Linux on Windows)", "windows": "Windows", "mac": "macOS", "linux-desktop": "Linux desktop",
              "linux-headless": "Linux without a desktop"}
    _step(steps, "Environment", INFO, labels[kind] + f" (platform {plat})")
    native = ""
    reason = caps.get("reason") or ""
    if kind == "docker":
        mounts = docker_helper.user_mounts(mounts_text, read=read)
        _step(steps, "A desktop folder window is possible", NA, docker_helper.DOCKER_REASON)
        _step(steps, "Folders mounted into this container", PASS if mounts else FAIL,
              "; ".join(m["container_path"] + (f" (from {m['host_path']})" if m["host_path"] else f" (volume {m['name']})" if m["name"] else "") for m in mounts[:8])
              or "none: no folder of yours is visible; restart the container with -v <host folder>:/mnt/<name>")
        verdict = "Browse opens the built-in browser, starting at the mounted folders. Folders outside the mounts are not visible to this window."
        return {"environment": kind, "steps": steps, "verdict": verdict, "ok": bool(mounts), "native": ""}
    if kind == "ssh":
        _step(steps, "A desktop folder window is possible", NA, reason)
        return {"environment": kind, "steps": steps, "verdict": "Browse opens the built-in browser (a folder window would appear on the remote computer, not on yours).", "ok": True, "native": ""}
    if plat == "wsl":
        inter = caps.get("interop") or np.interop_state(env, read)
        _step(steps, "WSL interop (Linux can start Windows programs)", {True: PASS, False: FAIL, None: INFO}[inter["enabled"]], inter["detail"])
    if plat in ("windows", "wsl"):
        tried = caps.get("tried") or []
        if caps["available"]:
            _step(steps, "powershell.exe is found", PASS, f"{caps['exe']}" + (f" (looked at {len(tried)} places)" if len(tried) > 1 else ""))
            native = _windows_checks(steps, plat, caps, caps["exe"], interactive, seconds, run, popen, which, env, wsl, 60)
            _conversion_checks(steps, plat, run, exists)
        else:
            _step(steps, "powershell.exe is found", FAIL, reason + ("" if not tried else "  Tried: " + ", ".join(tried[:8])))
    elif plat == "mac" or kind == "linux-desktop":
        if caps["available"]:
            _step(steps, f"{caps['via']} is found", PASS, caps["exe"])
            if _argv_program_checks(steps, caps, plat, seconds, popen, run):
                native = caps["kind"]
        else:
            _step(steps, "A folder window program is found", FAIL, reason)
    else:
        _step(steps, "A desktop folder window is possible", NA, reason or "no desktop session")
    if native:
        names = {"ifiledialog": "the Windows Explorer folder window", "winforms": "the older Windows folder window (no search box, tree view)", "shell": "the Windows Shell.Application folder window"}
        verdict = "Browse opens " + names.get(native, "the computer's own folder window (" + native + ")") + "."
        if native in ("winforms", "shell"):
            verdict += " The Explorer-style window could not be created here, see the failed steps above."
    elif kind in ("linux-headless",):
        verdict = "Browse opens the built-in browser: " + reason + "."
    else:
        verdict = "Browse opens the built-in browser" + (": " + reason if reason else "") + ". Fix the FAIL steps above to get the computer's own folder window."
    failed = [s for s in steps if s["status"] == FAIL and not s["name"].startswith("Fallback available") and not s["name"].startswith("PowerShell can compile")]
    ok = bool(native) or kind in ("linux-headless", "ssh")
    return {"environment": kind, "steps": steps, "verdict": verdict, "ok": ok and not [s for s in failed if s["name"].startswith("The folder window opens")],
            "native": native}


def format_report(report: dict) -> str:
    lines = [f"PlasBench folder window check ({report['environment']})", ""]
    for s in report["steps"]:
        lines.append(f"[{s['status']:>4}] {s['name']}" + (f": {s['detail']}" if s["detail"] else ""))
    lines += ["", "Result: " + report["verdict"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="plasbench picker-check", description="Check, step by step, whether Browse can open this computer's own folder window.")
    ap.add_argument("--interactive", action="store_true", help="leave the folder window open so you can choose a folder; prints the path that comes back")
    ap.add_argument("--seconds", type=int, default=2, help="how long the self-test leaves its window open before closing it (default 2)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    report = run_checks(interactive=args.interactive, seconds=max(1, min(args.seconds, 30)))
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
