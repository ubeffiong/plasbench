"""The computer's own folder / file window, opened by the server on the machine's desktop, so "Browse..." looks and works like Explorer.

A browser never hands a web page a real path (`showDirectoryPicker` gives a handle, not a path), and the window's server often runs inside WSL while the user's
files and drives are on Windows. So the dialog is opened BY THE SERVER (this module), on its own desktop, and only the chosen path is returned:

  - Windows, and WSL through `powershell.exe` interop: the real Windows dialog (IFileOpenDialog with FOS_PICKFOLDERS for folders, OpenFileDialog / SaveFileDialog for
    files): This PC, every drive including USB and network, Quick access, search, the real capacity bars. The script is a small embedded C# type compiled by `Add-Type`
    and sent with -EncodedCommand; the title, start folder and filters travel inside it as base64 JSON, so no text is ever spliced into a command line or a script.
  - macOS: `osascript` (`choose folder` / `choose file` / `choose file name`) with the title and start folder as argv items of an AppleScript `run` handler.
  - Linux desktop: `zenity`, `kdialog` or `yad` when a DISPLAY or WAYLAND_DISPLAY exists and the program is installed.
  - Anything else (no desktop session, SSH, a headless server): `available: False` with the reason; nothing ever hangs.

A path from the Windows dialog is converted for the server by the chooser's helpers (D:\\x -> /mnt/d/x in WSL; an unmounted drive gets the same `mount -t drvfs`
hint as the built-in chooser, never run for the user; a network share \\\\server\\share is explained, not mounted). No path is ever executed. One dialog at a time (a lock);
a dialog can be cancelled, is killed at its timeout, and is cleaned up when the server exits.

Every system fact (platform, environment, which programs exist, how a process is started) is an argument, so tests drive this with fake powershell.exe / osascript / zenity.
Standard library only.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import chooser

CTRL = re.compile(r"[\x00-\x1f\x7f]")
EXIT_CHOSEN, EXIT_CANCELLED, EXIT_ERROR = 0, 3, 4
DEFAULT_TIMEOUT = 600
POWERSHELL_ENV = "PLASBENCH_NATIVE_PICKER_POWERSHELL"     # override the powershell executable (odd installs, tests)
POWERSHELL_FALLBACK = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


# ---------------------------------------------------------------- what exists here
def _platform(platform: str | None = None, wsl: bool | None = None) -> str:
    """'windows' | 'wsl' | 'mac' | 'linux'."""
    if platform:
        return platform
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "wsl" if (chooser.in_wsl() if wsl is None else wsl) else "linux"


def _find_powershell(env, which) -> str | None:
    override = (env.get(POWERSHELL_ENV) or "").strip()
    if override:
        return override if (Path(override).exists() or which(override)) else None
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = which(name)
        if found:
            return found
    return POWERSHELL_FALLBACK if Path(POWERSHELL_FALLBACK).exists() else None


def capabilities(platform: str | None = None, env=None, which=shutil.which, wsl: bool | None = None) -> dict:
    """{'available': bool, 'via': program or None, 'kind': 'windows'|'wsl'|'mac'|'zenity'|'kdialog'|'yad'|None, 'platform', 'reason': why not, 'exe': path}. Only looks for programs; starts nothing."""
    env = os.environ if env is None else env
    plat = _platform(platform, wsl)
    out = {"available": False, "via": None, "kind": None, "platform": plat, "reason": "", "exe": None}
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY") or env.get("SSH_CLIENT"):
        out["reason"] = "this window runs over SSH: a folder window would open on the remote computer's desktop, not yours"
        return out
    if plat in ("windows", "wsl"):
        exe = _find_powershell(env, which)
        if not exe:
            out["reason"] = ("powershell.exe was not found: PlasBench opens the Windows folder window through it"
                             + (" (WSL interop may be off: check `interop` and `appendWindowsPath` in /etc/wsl.conf)" if plat == "wsl" else ""))
            return out
        out.update(available=True, via=Path(exe).name, kind=plat, exe=exe)
        return out
    if plat == "mac":
        exe = which("osascript")
        if not exe:
            out["reason"] = "osascript was not found"
            return out
        out.update(available=True, via="osascript", kind="mac", exe=exe)
        return out
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        out["reason"] = "no desktop session (no DISPLAY or WAYLAND_DISPLAY)"
        return out
    for tool in ("zenity", "kdialog", "yad"):
        exe = which(tool)
        if exe:
            out.update(available=True, via=tool, kind=tool, exe=exe)
            return out
    out["reason"] = "no desktop folder window program found (install zenity, kdialog or yad)"
    return out


# ---------------------------------------------------------------- clean inputs
def clean_text(text, limit: int) -> str:
    return CTRL.sub(" ", str(text or "")).strip()[:limit]


def clean_filters(filters) -> list:
    """[(label, 'pat1 pat2')] with only letters, digits, . * ? _ - and spaces in a pattern."""
    out = []
    for item in filters or []:
        try:
            label, pats = (item if isinstance(item, (list, tuple)) else (str(item), str(item)))[:2]
        except (TypeError, ValueError):
            continue
        pats = [re.sub(r"[^\w.*?\- ]", "", p) for p in re.split(r"[;\s,]+", str(pats)) if p]
        pats = [p for p in pats if p]
        if pats:
            out.append((clean_text(label, 60) or " ".join(pats), pats))
    return out[:12]


def start_folder(initial, plat: str, wsl_run=subprocess.run) -> str:
    """The folder the window starts in, as the DIALOG needs it: a Windows path for Windows and WSL (a Linux path converted), the nearest existing parent otherwise; '' when unknown."""
    text = clean_text(initial, 1000)
    if not text:
        return ""
    if plat == "windows":
        return text
    if plat == "wsl":
        if chooser.DRIVE_RE.match(text) or chooser.UNC_RE.match(text):
            return text
        p = Path(text).expanduser()
        while str(p) not in ("", "/") and not p.is_dir():
            p = p.parent
        return chooser.to_windows(str(p), wsl=True, run=wsl_run) if str(p) != "/" else ""
    p = Path(text).expanduser()
    while str(p) not in ("", "/", ".") and not p.is_dir():
        p = p.parent
    return str(p) if p.is_dir() else ""


# ---------------------------------------------------------------- the Windows dialog
CSHARP = r'''
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public static class PBPick {
  [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")] class FileOpenDialogCoClass { }
  [ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr hwnd);
    void SetFileTypes(uint c, IntPtr f); void SetFileTypeIndex(uint i); void GetFileTypeIndex(out uint i);
    void Advise(IntPtr p, out uint c); void Unadvise(uint c);
    void SetOptions(uint o); void GetOptions(out uint o);
    void SetDefaultFolder(IShellItem s); void SetFolder(IShellItem s); void GetFolder(out IShellItem s); void GetCurrentSelection(out IShellItem s);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n); void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t); void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem s);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv); void GetParent(out IShellItem p);
    void GetDisplayName(uint sigdn, out IntPtr name); void GetAttributes(uint mask, out uint attrs); void Compare(IShellItem o, uint hint, out int order);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, out IShellItem item);
  static IShellItem Item(string path) {
    Guid g = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"); IShellItem it;
    try { SHCreateItemFromParsingName(path, IntPtr.Zero, ref g, out it); return it; } catch { return null; }
  }
  static void Say(string tag, string text) {
    Console.Out.WriteLine(tag + ":" + Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(text ?? "")));
    Console.Out.Flush();
  }
  static int Folder(IntPtr owner, string title, string initial, bool dry) {
    IFileDialog d = (IFileDialog)new FileOpenDialogCoClass();
    uint o; d.GetOptions(out o); d.SetOptions(o | 0x20 | 0x40 | 0x800);
    d.SetTitle(title);
    if (initial.Length > 0) { IShellItem s = Item(initial); if (s != null) { d.SetFolder(s); } }
    if (dry) { d.GetOptions(out o); Say("PB_RESULT", "dry-run options=0x" + o.ToString("x")); return 0; }
    int hr = d.Show(owner);
    if (unchecked((uint)hr) == 0x800704C7u) return 3;
    if (hr != 0) { Say("PB_ERROR", "the folder window failed (HRESULT 0x" + hr.ToString("x") + ")"); return 4; }
    IShellItem r; d.GetResult(out r); IntPtr p;
    try { r.GetDisplayName(0x80058000u, out p); } catch { Say("PB_ERROR", "that item is not a folder on a disk (choose a folder, not This PC)"); return 4; }
    string path = Marshal.PtrToStringUni(p); Marshal.FreeCoTaskMem(p);
    Say("PB_RESULT", path); return 0;
  }
  public static int Run(string kind, string title, string initial, string filter, int timeout, bool dry) {
    Console.Out.WriteLine("PB_PID:" + System.Diagnostics.Process.GetCurrentProcess().Id); Console.Out.Flush();
    new System.Threading.Timer(delegate { Environment.Exit(3); }, null, (timeout + 5) * 1000, -1);
    Application.EnableVisualStyles();
    Form owner = new Form();
    owner.TopMost = true; owner.ShowInTaskbar = false; owner.FormBorderStyle = FormBorderStyle.None; owner.StartPosition = FormStartPosition.Manual;
    owner.Location = new System.Drawing.Point(-32000, -32000); owner.Size = new System.Drawing.Size(1, 1);
    owner.Show(); owner.Activate();
    try {
      if (kind == "folder") return Folder(owner.Handle, title, initial, dry);
      FileDialog fd; if (kind == "save") fd = new SaveFileDialog(); else fd = new OpenFileDialog();
      fd.Title = title; if (filter.Length > 0) fd.Filter = filter;
      if (initial.Length > 0) { if (System.IO.Directory.Exists(initial)) fd.InitialDirectory = initial; else { try { fd.InitialDirectory = System.IO.Path.GetDirectoryName(initial); fd.FileName = System.IO.Path.GetFileName(initial); } catch { } } }
      if (dry) { Say("PB_RESULT", "dry-run " + kind); return 0; }
      DialogResult r = fd.ShowDialog(owner);
      if (r != DialogResult.OK) return 3;
      Say("PB_RESULT", fd.FileName); return 0;
    } catch (Exception e) { Say("PB_ERROR", e.Message); return 4; }
    finally { owner.Dispose(); }
  }
}
'''


def windows_script(kind: str, title: str, initial: str, filters: list, timeout: int, dry: bool = False) -> str:
    """The PowerShell text sent with -EncodedCommand. The user's text is only ever the base64 payload; the rest is fixed."""
    flt = "|".join(f"{label} ({';'.join(p)})|{';'.join(p)}" for label, p in filters)
    payload = json.dumps({"kind": kind, "title": title, "initial": initial, "filter": flt, "timeout": int(timeout), "dry": bool(dry)})
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return ("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';\n"
            f"$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))|ConvertFrom-Json\n"
            "Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'\n" + CSHARP.strip() + "\n'@\n"
            "$code=[PBPick]::Run([string]$p.kind,[string]$p.title,[string]$p.initial,[string]$p.filter,[int]$p.timeout,[bool]$p.dry)\n"
            "exit $code\n")


def windows_argv(exe: str, script: str) -> list:
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", enc]


# ---------------------------------------------------------------- the other platforms' argv
def mac_argv(exe: str, kind: str, title: str, initial: str, filters: list) -> list:
    verb = {"folder": "choose folder with prompt", "file": "choose file with prompt", "save": "choose file name with prompt"}[kind]
    script = ["on run argv", f"if (item 2 of argv) is \"\" then", f"return POSIX path of ({verb} (item 1 of argv))", "else",
              f"return POSIX path of ({verb} (item 1 of argv) default location (POSIX file (item 2 of argv)))", "end if", "end run"]
    argv = [exe]
    for line in script:
        argv += ["-e", line]
    return argv + [title, initial]


def linux_argv(tool: str, exe: str, kind: str, title: str, initial: str, filters: list) -> list:
    start = initial.rstrip("/") + "/" if initial else ""
    if tool == "kdialog":
        verb = {"folder": "--getexistingdirectory", "file": "--getopenfilename", "save": "--getsavefilename"}[kind]
        argv = [exe, "--title", title, verb, start or os.path.expanduser("~") + "/"]
        if kind != "folder" and filters:
            argv.append("\n".join(f"{' '.join(p)}|{label}" for label, p in filters))
        return argv
    argv = [exe, "--file-selection" if tool == "zenity" else "--file", f"--title={title}"]
    if kind == "folder":
        argv.append("--directory")
    elif kind == "save":
        argv += ["--save", "--confirm-overwrite"] if tool == "zenity" else ["--save"]
    if start:
        argv.append(f"--filename={start}")
    for label, pats in (filters if kind != "folder" else []):
        argv.append(f"--file-filter={label} | {' '.join(pats)}")
    return argv


# ---------------------------------------------------------------- results
def convert_result(raw: str, plat: str, kind: str = "folder", run=subprocess.run, mounts_text: str | None = None) -> dict:
    """What the dialog returned -> {'ok', 'path' (for the server), 'display' (as the user sees it), 'windows_path', 'error', 'mount_hint', 'warning'}."""
    raw = (raw or "").strip().strip('"')
    out = {"ok": False, "path": "", "display": raw, "windows_path": "", "error": "", "mount_hint": "", "warning": ""}
    if not raw:
        out["error"] = "nothing was chosen"
        return out
    if plat == "wsl":
        out["windows_path"] = raw
        m = chooser.DRIVE_RE.match(raw)
        try:
            linux = chooser.to_linux(raw, wsl=True, run=run)
        except ValueError as exc:
            out["error"] = str(exc)
            if chooser.UNC_RE.match(raw) and not chooser.UNC_WSL_RE.match(raw):
                out["warning"] = "network shares cannot be mounted automatically"
            return out
        if m:
            letter = m.group(1)
            if not chooser.drive_mounted(letter, mounts_text):
                out["error"] = chooser.mount_help(letter)
                out["mount_hint"] = chooser.mount_command(letter)
                return out
        out.update(ok=True, path=linux)
        return out
    out.update(ok=True, path=raw, windows_path=raw if plat == "windows" else "")
    if kind == "folder" and len(raw) > 1:
        out["path"] = raw.rstrip("/") or "/"
    return out


# ---------------------------------------------------------------- running one dialog
class Busy(Exception):
    def __init__(self, job_id):
        super().__init__("a folder dialog is already open")
        self.job_id = job_id


class Job:
    def __init__(self, kind: str, title: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.title = kind, title
        self.state = "open"            # open | chosen | cancelled | error
        self.result: dict = {}
        self.proc = None
        self.win_pid = None
        self.cancel_event = threading.Event()
        self.started = time.time()
        self.thread = None

    def view(self) -> dict:
        out = {"id": self.id, "state": self.state, "kind": self.kind, "elapsed": round(time.time() - self.started, 1)}
        out.update({k: v for k, v in self.result.items() if k != "available"})
        return out


_lock = threading.Lock()
_jobs: dict = {}
_active: Job | None = None


def _kill(proc, win_pid=None, plat="linux"):
    """Stop the process and whatever it started (a Windows process tree, or the Windows process behind a WSL interop stub)."""
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            try:
                os.killpg(proc.pid, 9)
            except (OSError, ProcessLookupError):
                proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    if plat == "wsl" and win_pid:
        tk = shutil.which("taskkill.exe")
        if tk:
            try:
                subprocess.run([tk, "/F", "/T", "/PID", str(win_pid)], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _run_argv(argv: list, timeout: float, job: Job, plat: str, popen=subprocess.Popen) -> tuple:
    """Run one dialog process: (returncode | None, stdout, stderr, reason in '' | 'timeout' | 'cancelled'). Reading never blocks the timeout."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True
    proc = popen(argv, **kw)
    job.proc = proc
    bufs = {"out": [], "err": []}

    def pump(stream, key):
        try:
            for chunk in iter(lambda: stream.readline(), b""):
                bufs[key].append(chunk)
                if key == "out" and chunk.startswith(b"PB_PID:"):
                    try:
                        job.win_pid = int(chunk.split(b":", 1)[1].strip())
                    except ValueError:
                        pass
        except (OSError, ValueError):
            pass
    readers = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True), threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    for t in readers:
        t.start()
    deadline = time.time() + timeout
    reason = ""
    while proc.poll() is None:
        if job.cancel_event.is_set():
            reason = "cancelled"
        elif time.time() >= deadline:
            reason = "timeout"
        if reason:
            _kill(proc, job.win_pid, plat)
            break
        time.sleep(0.05)
    for t in readers:
        t.join(2)
    dec = lambda parts: b"".join(parts).decode("utf-8", "replace")  # noqa: E731
    return (proc.returncode if not reason else None), dec(bufs["out"]), dec(bufs["err"]), reason


def _decode_tag(out: str, tag: str) -> str | None:
    for line in out.replace("\r", "").split("\n"):
        if line.startswith(tag + ":"):
            try:
                return base64.b64decode(line.split(":", 1)[1].strip()).decode("utf-8", "replace")
            except (ValueError, TypeError):
                return None
    return None


def _execute(job: Job, kind: str, title: str, initial, filters, timeout: float, caps: dict, plat: str, popen, run) -> dict:
    title = clean_text(title, 120) or {"folder": "Choose a folder", "file": "Choose a file", "save": "Save as"}[kind]
    flt = clean_filters(filters)
    start = start_folder(initial, plat, run)
    exe = caps["exe"]
    if caps["kind"] in ("windows", "wsl"):
        argv = windows_argv(exe, windows_script(kind, title, start, flt, int(timeout)))
    elif caps["kind"] == "mac":
        argv = mac_argv(exe, kind, title, start, flt)
    else:
        argv = linux_argv(caps["kind"], exe, kind, title, start, flt)
    try:
        rc, out, err, reason = _run_argv(argv, timeout, job, plat, popen)
    except OSError as exc:
        return {"ok": False, "cancelled": False, "error": f"could not start the folder window ({exc})"}
    if reason == "cancelled":
        return {"ok": False, "cancelled": True, "error": ""}
    if reason == "timeout":
        return {"ok": False, "cancelled": False, "timed_out": True, "error": f"the folder window was closed after {int(timeout)} seconds without a choice"}
    if caps["kind"] in ("windows", "wsl"):
        if rc == EXIT_CANCELLED:
            return {"ok": False, "cancelled": True, "error": ""}
        raw = _decode_tag(out, "PB_RESULT")
        if rc != EXIT_CHOSEN or raw is None:
            msg = _decode_tag(out, "PB_ERROR") or (err.strip().splitlines() or [""])[-1][:300] or f"the folder window ended with code {rc}"
            return {"ok": False, "cancelled": False, "error": msg}
    else:
        if rc != 0:
            if rc == 1 or "cancel" in err.lower():      # zenity, kdialog, yad and osascript (-128 'User canceled') all end like this
                return {"ok": False, "cancelled": True, "error": ""}
            return {"ok": False, "cancelled": False, "error": (err.strip().splitlines() or [f"exit code {rc}"])[-1][:300]}
        raw = out.strip("\r\n").split("\n")[0].strip() if out.strip() else ""
        if not raw:
            return {"ok": False, "cancelled": True, "error": ""}
    got = convert_result(raw, plat, kind, run)
    return {"ok": got["ok"], "cancelled": False, "error": got["error"], "path": got["path"], "display": got["display"], "windows_path": got["windows_path"],
            "mount_hint": got["mount_hint"], "warning": got["warning"]}


def _result(base: dict, caps: dict) -> dict:
    out = {"ok": False, "path": "", "display": "", "windows_path": "", "cancelled": False, "error": "", "available": caps["available"]}
    out.update(base)
    out["available"] = caps["available"]
    return out


def pick_folder(title: str = "", initial=None, kind: str = "folder", filters=None, timeout: float = DEFAULT_TIMEOUT, *, platform: str | None = None, env=None,
                which=shutil.which, popen=subprocess.Popen, run=subprocess.run, wsl: bool | None = None) -> dict:
    """Open the computer's dialog and wait: {'ok', 'path', 'display', 'windows_path', 'cancelled', 'error', 'available'} (+ 'mount_hint', 'warning').
    Refuses while another dialog is open. `kind` is 'folder', 'file' or 'save'."""
    job = _begin(kind, title, platform, env, which, wsl)
    if isinstance(job, dict):
        return job
    return _finish(job, kind, title, initial, filters, timeout, platform, env, which, popen, run, wsl)


def _begin(kind, title, platform, env, which, wsl):
    global _active
    caps = capabilities(platform, env, which, wsl)
    if kind not in ("folder", "file", "save"):
        return _result({"error": "kind must be folder, file or save"}, caps)
    if not caps["available"]:
        return _result({"error": caps["reason"]}, caps)
    with _lock:
        if _active is not None and _active.state == "open":
            return _result({"error": "a folder dialog is already open", "busy": True, "id": _active.id}, caps)
        job = Job(kind, title)
        _jobs[job.id] = job
        _active = job
        for old in [j for j in _jobs.values() if j.state != "open"][:-20]:
            _jobs.pop(old.id, None)
    return job


def _finish(job, kind, title, initial, filters, timeout, platform, env, which, popen, run, wsl) -> dict:
    global _active
    caps = capabilities(platform, env, which, wsl)
    plat = _platform(platform, wsl)
    try:
        res = _execute(job, kind, title, initial, filters, timeout, caps, plat, popen, run)
    except Exception as exc:  # noqa: BLE001 - the page gets a message, never a hang
        res = {"ok": False, "cancelled": False, "error": f"{type(exc).__name__}: {exc}"}
    out = _result(res, caps)
    job.result = out
    job.state = "chosen" if out["ok"] else "cancelled" if out["cancelled"] else "error"
    with _lock:
        if _active is job:
            _active = None
    return out


def start(kind: str = "folder", title: str = "", initial=None, filters=None, timeout: float = DEFAULT_TIMEOUT, **inject) -> dict:
    """Start a dialog in a background thread and return at once: {'id', 'state': 'open'} or {'error', 'busy': True, 'id': <the open one>}."""
    platform, env, which = inject.get("platform"), inject.get("env"), inject.get("which", shutil.which)
    wsl, popen, run = inject.get("wsl"), inject.get("popen", subprocess.Popen), inject.get("run", subprocess.run)
    job = _begin(kind, title, platform, env, which, wsl)
    if isinstance(job, dict):
        return job
    job.thread = threading.Thread(target=_finish, args=(job, kind, title, initial, filters, timeout, platform, env, which, popen, run, wsl), daemon=True)
    job.thread.start()
    return {"id": job.id, "state": "open", "available": True}


def status(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id or "")
    return job.view() if job else {"id": job_id, "state": "error", "error": "that folder window is no longer known (the window may have been restarted)"}


def cancel(job_id: str | None = None) -> dict:
    """Cancel the open dialog (`job_id`, or whichever is open). Returns the job's view, or {'state': 'none'}."""
    with _lock:
        job = _jobs.get(job_id) if job_id else _active
    if job is None or job.state != "open":
        return {"state": "none", "id": job_id}
    job.cancel_event.set()
    if job.thread:
        job.thread.join(8)
    return job.view()


def bring_to_front(job_id: str | None = None, which=shutil.which, env=None, platform: str | None = None, run=subprocess.run, wsl=None) -> dict:
    """Windows and WSL: ask Windows to activate the open dialog (matched by its title). Other platforms cannot be raised from here."""
    with _lock:
        job = _jobs.get(job_id) if job_id else _active
    if job is None or job.state != "open":
        return {"ok": False, "error": "no folder window is open"}
    caps = capabilities(platform, env, which, wsl)
    if caps["kind"] not in ("windows", "wsl"):
        return {"ok": False, "error": "this computer's folder window cannot be raised from here: look for it in the taskbar or the dock"}
    title = clean_text(job.title, 120) or {"folder": "Choose a folder", "file": "Choose a file", "save": "Save as"}[job.kind]
    b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
    script = (f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'));"
              "[void](New-Object -ComObject WScript.Shell).AppActivate($t)")
    try:
        run(windows_argv(caps["exe"], script), capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


def cleanup():
    """Kill any open dialog (the server is exiting)."""
    with _lock:
        jobs = [j for j in _jobs.values() if j.state == "open"]
    for job in jobs:
        job.cancel_event.set()
        _kill(job.proc, job.win_pid, "windows" if os.name == "nt" else "linux")


atexit.register(cleanup)


def reset():
    """Forget every job (tests)."""
    global _active
    cleanup()
    with _lock:
        _jobs.clear()
        _active = None
