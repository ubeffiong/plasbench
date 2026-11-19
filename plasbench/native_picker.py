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

from . import chooser, docker_helper

CTRL = re.compile(r"[\x00-\x1f\x7f]")
EXIT_CHOSEN, EXIT_CANCELLED, EXIT_ERROR = 0, 3, 4
DEFAULT_TIMEOUT = 600
POWERSHELL_ENV = "PLASBENCH_NATIVE_PICKER_POWERSHELL"     # override the powershell executable (odd installs, tests)


# ---------------------------------------------------------------- what exists here
POWERSHELL_FIXED = (
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe",
    "/mnt/c/Program Files/PowerShell/7/pwsh.exe",
)
INTEROP_FILES = ("/proc/sys/fs/binfmt_misc/WSLInterop", "/proc/sys/fs/binfmt_misc/WSLInterop-late")
WSL_CONF = "/etc/wsl.conf"


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _platform(platform: str | None = None, wsl: bool | None = None) -> str:
    """'windows' | 'wsl' | 'mac' | 'linux'."""
    if platform:
        return platform
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "wsl" if (chooser.in_wsl() if wsl is None else wsl) else "linux"


def parse_wsl_conf(text: str | None) -> dict:
    """{'interop_enabled': bool|None, 'append_windows_path': bool|None} from /etc/wsl.conf text (None = not set, so the default, which is on)."""
    out = {"interop_enabled": None, "append_windows_path": None}
    section = ""
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        key, eq, value = line.partition("=")
        if section != "interop" or not eq:
            continue
        flag = value.strip().lower() in ("true", "1", "yes", "on")
        if key.strip().lower() == "enabled":
            out["interop_enabled"] = flag
        elif key.strip().lower() == "appendwindowspath":
            out["append_windows_path"] = flag
    return out


def interop_state(env=None, read=_read) -> dict:
    """WSL interop (starting Windows programs from Linux): {'enabled': bool|None, 'detail': text, 'conf': parse_wsl_conf, 'wsl_interop_env': str}. None = could not tell."""
    env = os.environ if env is None else env
    conf = parse_wsl_conf(read(WSL_CONF))
    seen = []
    for f in INTEROP_FILES:
        text = read(f)
        if text is not None:
            seen.append((f, text.lstrip().lower().startswith("enabled")))
    sock = (env.get("WSL_INTEROP") or "").strip()
    if conf["interop_enabled"] is False:
        enabled, detail = False, "/etc/wsl.conf has [interop] enabled=false: Linux programs cannot start Windows programs"
    elif seen:
        enabled = any(ok for _, ok in seen)
        detail = "; ".join(f"{Path(f).name}: {'enabled' if ok else 'disabled'}" for f, ok in seen)
        if not enabled:
            detail += " (restart WSL with `wsl --shutdown` from Windows, or re-enable it: sudo sh -c 'echo 1 > /proc/sys/fs/binfmt_misc/WSLInterop')"
    elif sock:
        enabled, detail = True, f"WSL_INTEROP={sock}"
    else:
        enabled, detail = None, "could not read /proc/sys/fs/binfmt_misc/WSLInterop and WSL_INTEROP is not set"
    if conf["append_windows_path"] is False:
        detail += "; /etc/wsl.conf has appendWindowsPath=false, so Windows programs are not on PATH (PlasBench looks in /mnt/c/Windows instead)"
    return {"enabled": enabled, "detail": detail, "conf": conf, "wsl_interop_env": sock}


def powershell_candidates(env, which, exists=os.path.exists, run=subprocess.run, listdir=os.listdir) -> list:
    """Every place powershell.exe may be, in the order they are tried: the override, PATH, the usual /mnt/c locations, %SystemRoot% asked of cmd.exe, any /mnt/<drive>/Windows."""
    out = []
    override = (env.get(POWERSHELL_ENV) or "").strip()
    if override:
        out.append(override)
    for name in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
        found = which(name)
        if found:
            out.append(found)
    out += POWERSHELL_FIXED
    cmd = which("cmd.exe") or ("/mnt/c/Windows/System32/cmd.exe" if exists("/mnt/c/Windows/System32/cmd.exe") else None)
    if cmd and not override and not any(exists(c) for c in out):
        try:        # only asked when the usual places failed: it starts a Windows process
            got = run([cmd, "/c", "echo %SystemRoot%"], capture_output=True, timeout=8, cwd="/mnt/c" if exists("/mnt/c") else None)
            root = got.stdout.decode("utf-8", "replace").strip().splitlines()[-1].strip() if got.returncode == 0 and got.stdout.strip() else ""
            if root and chooser.DRIVE_RE.match(root):
                out.append(chooser.to_linux(root, wsl=True, run=run).rstrip("/") + "/System32/WindowsPowerShell/v1.0/powershell.exe")
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    try:
        for d in sorted(listdir("/mnt")):
            out.append(f"/mnt/{d}/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    except OSError:
        pass
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def find_powershell(env, which, exists=os.path.exists, run=subprocess.run, listdir=os.listdir, plat: str = "wsl") -> tuple:
    """(path or None, [what was tried]). On native Windows only the override, PATH and the System32 location are looked at."""
    override = (env.get(POWERSHELL_ENV) or "").strip()
    if override:
        ok = exists(override) or bool(which(override))
        return (override if ok else None), [override]
    if plat == "windows":
        root = env.get("SystemRoot") or env.get("SYSTEMROOT") or "C:\\Windows"
        cands = [c for c in [which(n) for n in ("powershell.exe", "pwsh.exe", "powershell", "pwsh")]
                 + [os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")] if c]
    else:
        cands = powershell_candidates(env, which, exists, run, listdir)
    found = {which(n) for n in ("powershell.exe", "pwsh.exe", "powershell", "pwsh")} - {None}      # what PATH lookup returned is trusted as it is
    for c in cands:
        if c in found or exists(c):
            return c, cands
    return None, cands


def _gateway_ips(read=_read) -> list:
    """The IPv4 addresses of this machine's default gateway(s), from /proc/net/route (under WSL2's NAT mode the Windows host is the gateway)."""
    out = []
    for line in (read("/proc/net/route") or "").splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000":
            try:
                out.append(".".join(str(b) for b in bytes.fromhex(f[2])[::-1]))
            except ValueError:
                pass
    return out


def is_local_client(addr: str, plat: str = "linux", gateways=None, local_ips=None) -> bool:
    """True when a request comes from this computer. Loopback always counts. Under WSL2 a Windows browser that reaches the window through localhost forwarding
    is seen as 127.0.0.1 or, on older or NAT builds, as the Windows host: the default gateway of the WSL virtual machine (or one of the VM's own addresses).
    Anywhere else only loopback counts: a Docker bridge gateway (172.17.0.1) may be another machine's browser."""
    a = str(addr or "").split("%")[0].strip().lower()
    if a.startswith("::ffff:"):
        a = a[7:]
    if a in ("::1", "localhost") or a.startswith("127."):
        return True
    if plat != "wsl":
        return False
    return a in (_gateway_ips() if gateways is None else gateways) or a in (local_ips or [])


def capabilities(platform: str | None = None, env=None, which=shutil.which, wsl: bool | None = None, *, exists=os.path.exists, run=subprocess.run,
                 read=_read, listdir=os.listdir) -> dict:
    """{'available': bool, 'via': program or None, 'kind': 'windows'|'wsl'|'mac'|'zenity'|'kdialog'|'yad'|None, 'platform', 'reason': why not, 'exe': path,
    'docker': bool, 'interop': {...} (WSL), 'tried': [paths looked at]}. Only looks for programs (and, for WSL, asks cmd.exe for %SystemRoot% when the usual places fail)."""
    env = os.environ if env is None else env
    plat = _platform(platform, wsl)
    out = {"available": False, "via": None, "kind": None, "platform": plat, "reason": "", "exe": None, "docker": False, "tried": []}
    if docker_helper.in_docker(env, exists, read):
        out["docker"] = True
        out["reason"] = docker_helper.DOCKER_REASON
        return out
    if env.get("SSH_CONNECTION") or env.get("SSH_TTY") or env.get("SSH_CLIENT"):
        out["reason"] = "this window runs over SSH: a folder window would open on the remote computer's desktop, not yours"
        return out
    if plat in ("windows", "wsl"):
        if plat == "wsl":
            out["interop"] = interop_state(env, read)
            if out["interop"]["enabled"] is False:
                out["reason"] = "WSL interop is off, so Linux programs cannot open Windows windows: " + out["interop"]["detail"]
                return out
        exe, tried = find_powershell(env, which, exists, run, listdir, plat)
        out["tried"] = tried
        if not exe:
            out["reason"] = ("powershell.exe was not found: PlasBench opens the Windows folder window through it"
                             + (" (WSL interop may be off: check `interop` and `appendWindowsPath` in /etc/wsl.conf; looked in " + ", ".join(tried[:6]) + ")" if plat == "wsl" else ""))
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
  [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("user32.dll")] static extern bool FlashWindow(IntPtr h, bool invert);
  [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
  static IShellItem Item(string path) {
    Guid g = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"); IShellItem it;
    try { SHCreateItemFromParsingName(path, IntPtr.Zero, ref g, out it); return it; } catch { return null; }
  }
  static readonly object gate = new object();
  static void Say(string tag, string text) {
    lock (gate) { Console.Out.WriteLine(tag + ":" + Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(text ?? ""))); Console.Out.Flush(); }
  }
  // Bring the dialog to the front. A process started from a background caller (WSL interop, a service) is not allowed to take the foreground; the Alt key press
  // and the thread-input attach are the documented ways round that. If it still fails the taskbar button flashes.
  static string Front(IntPtr h) {
    try {
      keybd_event(0x12, 0, 0, UIntPtr.Zero); keybd_event(0x12, 0, 2, UIntPtr.Zero);
      IntPtr fg = GetForegroundWindow(); uint me = GetCurrentThreadId(); uint other = fg == IntPtr.Zero ? 0 : GetWindowThreadProcessId(fg, IntPtr.Zero);
      if (other != 0 && other != me) AttachThreadInput(me, other, true);
      ShowWindow(h, 9); BringWindowToTop(h); bool ok = SetForegroundWindow(h);
      if (other != 0 && other != me) AttachThreadInput(me, other, false);
      if (ok && GetForegroundWindow() == h) return "foreground";
      FlashWindow(h, true); return "flashed";
    } catch (Exception e) { return "failed: " + e.Message; }
  }
  // Runs beside the modal dialog: says PB_OPENED as soon as the dialog window exists and is visible, raises it, and closes it after `selftest` seconds when asked.
  static void Watch(IntPtr owner, int selftest, int giveUp) {
    var t = new System.Threading.Thread(delegate() {
      DateTime end = DateTime.UtcNow.AddSeconds(giveUp);
      while (DateTime.UtcNow < end) {
        IntPtr d = GetWindow(owner, 6);
        if (d != IntPtr.Zero && IsWindowVisible(d)) {
          Say("PB_OPENED", "ifiledialog"); Say("PB_FOCUS", Front(d));
          if (selftest > 0) { System.Threading.Thread.Sleep(selftest * 1000); PostMessage(d, 0x0010, IntPtr.Zero, IntPtr.Zero); Say("PB_SELFTEST", "closed"); }
          return;
        }
        System.Threading.Thread.Sleep(80);
      }
    });
    t.IsBackground = true; t.Start();
  }
  static int Folder(IntPtr owner, string title, string initial, bool dry, int selftest, int timeout) {
    IFileDialog d;
    try {
      d = (IFileDialog)new FileOpenDialogCoClass();
      uint o; d.GetOptions(out o); d.SetOptions(o | 0x20 | 0x40 | 0x800);
      d.SetTitle(title);
      if (initial.Length > 0) { IShellItem s = Item(initial); if (s != null) { d.SetFolder(s); } }
      if (dry) { d.GetOptions(out o); Say("PB_RESULT", "dry-run options=0x" + o.ToString("x")); return 0; }
    } catch (Exception e) { Say("PB_NOTE", "the Explorer folder window could not be created: " + e.Message); return 5; }
    Watch(owner, selftest, timeout);
    int hr = d.Show(owner);
    if (unchecked((uint)hr) == 0x800704C7u) return 3;
    if (hr != 0) { Say("PB_NOTE", "the Explorer folder window failed (HRESULT 0x" + hr.ToString("x") + ")"); return 5; }
    IShellItem r; d.GetResult(out r); IntPtr p;
    try { r.GetDisplayName(0x80058000u, out p); } catch { Say("PB_ERROR", "that item is not a folder on a disk (choose a folder, not This PC)"); return 4; }
    string path = Marshal.PtrToStringUni(p); Marshal.FreeCoTaskMem(p);
    Say("PB_RESULT", path); return 0;
  }
  public static int Run(string kind, string title, string initial, string filter, int timeout, bool dry, int selftest) {
    Say("PB_PID", System.Diagnostics.Process.GetCurrentProcess().Id.ToString());
    new System.Threading.Timer(delegate { Environment.Exit(3); }, null, (timeout + 5) * 1000, -1);
    Application.EnableVisualStyles();
    Form owner = new Form();
    owner.TopMost = true; owner.ShowInTaskbar = false; owner.FormBorderStyle = FormBorderStyle.None; owner.StartPosition = FormStartPosition.CenterScreen;
    owner.Opacity = 0; owner.Size = new System.Drawing.Size(1, 1);
    owner.Show(); owner.Activate();
    try {
      if (kind == "folder") return Folder(owner.Handle, title, initial, dry, selftest, timeout);
      FileDialog fd; if (kind == "save") fd = new SaveFileDialog(); else fd = new OpenFileDialog();
      fd.Title = title; if (filter.Length > 0) fd.Filter = filter;
      if (initial.Length > 0) { if (System.IO.Directory.Exists(initial)) fd.InitialDirectory = initial; else { try { fd.InitialDirectory = System.IO.Path.GetDirectoryName(initial); fd.FileName = System.IO.Path.GetFileName(initial); } catch { } } }
      if (dry) { Say("PB_RESULT", "dry-run " + kind); return 0; }
      Watch(owner.Handle, selftest, timeout);
      DialogResult r = fd.ShowDialog(owner);
      if (r != DialogResult.OK) return 3;
      Say("PB_RESULT", fd.FileName); return 0;
    } catch (Exception e) { Say("PB_ERROR", e.Message); return 4; }
    finally { owner.Dispose(); }
  }
}
'''

# The pure-PowerShell fallbacks: used when Add-Type cannot compile C# (constrained language mode, a security product, a missing compiler) or the Explorer folder
# window cannot be created. FolderBrowserDialog is the older tree-style folder window; Shell.Application.BrowseForFolder is the COM one.
PS_FALLBACKS = r'''
function PBFallback($p) {
  $kind = [string]$p.kind
  if ([string]$p.strategy -ne 'shell') { try {
    Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing
    $o = New-Object System.Windows.Forms.Form
    $o.TopMost = $true; $o.ShowInTaskbar = $false; $o.FormBorderStyle = 'None'; $o.StartPosition = 'CenterScreen'; $o.Opacity = 0; $o.Size = New-Object System.Drawing.Size(1, 1)
    $o.Show(); [void]$o.Activate()
    if ($kind -eq 'folder') { $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = [string]$p.title; $d.ShowNewFolderButton = $true
      if ([string]$p.initial -ne '' -and (Test-Path -LiteralPath ([string]$p.initial))) { $d.SelectedPath = [string]$p.initial } }
    elseif ($kind -eq 'save') { $d = New-Object System.Windows.Forms.SaveFileDialog; $d.Title = [string]$p.title }
    else { $d = New-Object System.Windows.Forms.OpenFileDialog; $d.Title = [string]$p.title }
    if ($kind -ne 'folder' -and [string]$p.filter -ne '') { $d.Filter = [string]$p.filter }
    PBSay 'PB_STRATEGY' 'winforms'
    if ($p.dry) { PBSay 'PB_RESULT' 'dry-run winforms'; return 0 }
    PBSay 'PB_OPENED' 'winforms'
    if ($p.selftest -gt 0) { PBSay 'PB_NOTE' 'the self-test cannot close this older window by itself: close it'; }
    $r = $d.ShowDialog($o)
    if ($r -ne [System.Windows.Forms.DialogResult]::OK) { return 3 }
    if ($kind -eq 'folder') { PBSay 'PB_RESULT' $d.SelectedPath } else { PBSay 'PB_RESULT' $d.FileName }
    return 0
  } catch { PBSay 'PB_NOTE' ('the older Windows folder window failed: ' + $_.Exception.Message) } }
  if ($kind -eq 'folder') {
    try {
      $sh = New-Object -ComObject Shell.Application
      PBSay 'PB_STRATEGY' 'shell'
      if ($p.dry) { PBSay 'PB_RESULT' 'dry-run shell'; return 0 }
      PBSay 'PB_OPENED' 'shell'
      $f = $sh.BrowseForFolder(0, [string]$p.title, 0x51, [string]$p.initial)
      if ($f -eq $null) { return 3 }
      PBSay 'PB_RESULT' $f.Self.Path
      return 0
    } catch { PBSay 'PB_NOTE' ('Shell.Application failed: ' + $_.Exception.Message) }
  }
  PBSay 'PB_ERROR' 'no Windows folder window could be opened here (the C# window, the older window and Shell.Application all failed): use the built-in browser'
  return 6
}
'''

CHECK_SCRIPT = "'hello';$PSVersionTable.PSVersion.ToString();$ExecutionContext.SessionState.LanguageMode;[Threading.Thread]::CurrentThread.GetApartmentState();(Get-ExecutionPolicy);[IO.Path]::GetTempPath()"
COMPILE_TEST = ("Add-Type -TypeDefinition 'public static class PBProbe { public static int Answer() { return 42; } }'; [PBProbe]::Answer()")


def windows_script(kind: str, title: str, initial: str, filters: list, timeout: int, dry: bool = False, selftest: int = 0, strategy: str = "") -> str:
    """The PowerShell text that opens the dialog. The user's text is only ever the base64 payload; the rest is fixed. Tries the Explorer dialog (C#), then the older
    pure-PowerShell windows, and says which one it used (PB_STRATEGY) and when the window exists (PB_OPENED)."""
    flt = "|".join(f"{label} ({';'.join(p)})|{';'.join(p)}" for label, p in filters)
    payload = json.dumps({"kind": kind, "title": title, "initial": initial, "filter": flt, "timeout": int(timeout), "dry": bool(dry), "selftest": int(selftest), "strategy": strategy if strategy in ("winforms", "shell") else ""})
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return ("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'\n"
            "function PBSay($t,$x){[Console]::Out.WriteLine($t+':'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$x)));[Console]::Out.Flush()}\n"
            f"$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))|ConvertFrom-Json\n"
            "PBSay 'PB_ENV' ('ps='+$PSVersionTable.PSVersion+';language='+$ExecutionContext.SessionState.LanguageMode+';apartment='+[Threading.Thread]::CurrentThread.GetApartmentState())\n"
            + PS_FALLBACKS.strip() + "\n"
            "$code=5\n"
            "if ([string]$p.strategy -eq '') { try {\n"
            "Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'\n" + CSHARP.strip() + "\n'@\n"
            "PBSay 'PB_STRATEGY' 'ifiledialog'\n"
            "$code=[PBPick]::Run([string]$p.kind,[string]$p.title,[string]$p.initial,[string]$p.filter,[int]$p.timeout,[bool]$p.dry,[int]$p.selftest)\n"
            "} catch { PBSay 'PB_NOTE' ('the Explorer folder window could not be prepared: '+$_.Exception.Message); $code=5 } }\n"
            "if ($code -eq 5) { $code = [int](PBFallback $p | Select-Object -Last 1) }\n"
            "exit $code\n")


COMMAND_LINE_LIMIT = 7000     # characters of the -EncodedCommand argument; Windows allows 32767 but cmd.exe-style launchers stop at 8191 and WSL interop varies


def gzip_bootstrap(script: str) -> str:
    """A short script that unpacks `script` (gzip + base64) and runs it: the C# text compresses about threefold, which keeps the command line short."""
    import gzip
    packed = base64.b64encode(gzip.compress(script.encode("utf-8"), 9)).decode("ascii")
    return ("$b=[Convert]::FromBase64String('" + packed + "');$m=New-Object IO.MemoryStream(,$b);"
            "$g=New-Object IO.Compression.GZipStream($m,[IO.Compression.CompressionMode]::Decompress);"
            "$r=New-Object IO.StreamReader($g,[Text.Encoding]::UTF8);Invoke-Expression $r.ReadToEnd()")


def encoded_argv(exe: str, script: str) -> list:
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", enc]


def windows_routes(exe: str, script: str, limit: int = COMMAND_LINE_LIMIT, temp_dir: str | None = None, plat: str = "windows", win_temp: str | None = None,
                   write_file=None) -> list:
    """The ways to hand `script` to PowerShell, best first: [(route, argv, cleanup_path|None)]. 'encoded' (the script as -EncodedCommand) when it fits `limit`;
    'gzip' (a short ASCII unpacker passed as -Command) when that fits; 'file' (a .ps1 in the Windows temp folder, run with -File) when neither does; 'stdin' (the one-line unpacker on standard input; PowerShell cannot read a long multi-line script from stdin reliably) last."""
    routes = []
    plain = encoded_argv(exe, script)
    if len(plain[-1]) <= limit:
        routes.append(("encoded", plain, None))
    boot = gzip_bootstrap(script)      # plain ASCII (base64 and fixed text, no double quotes), so it travels as -Command without the doubling of UTF-16
    if len(boot) <= limit:
        routes.append(("gzip", [exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", boot], None))
    if win_temp and write_file:
        try:
            name = f"plasbench-pick-{uuid.uuid4().hex[:10]}.ps1"
            win_path = win_temp.rstrip("\\") + "\\" + name
            local = write_file(name, script)
            if local:
                routes.append(("file", [exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", win_path], local))
        except OSError:
            pass
    routes.append(("stdin", [exe, "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", "-"], None))
    if not any(r[0] in ("encoded", "gzip") for r in routes):
        routes.append(("encoded", plain, None))      # last resort: too long for the limit I chose, but the real limit is usually higher
    return routes


def windows_argv(exe: str, script: str) -> list:
    """The plain -EncodedCommand argv (short scripts, and the tests' fake powershell)."""
    return encoded_argv(exe, script)


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
        self.exe = None
        self.plat = "linux"
        self.cancel_event = threading.Event()
        self.started = time.time()
        self.thread = None
        self.opts: dict = {}
        self.opened = False            # the dialog window exists (the script said PB_OPENED); other platforms: the program was started
        self.opened_after = None       # seconds from the start to that signal
        self.strategy = ""             # ifiledialog | winforms | shell | zenity ...
        self.route = ""                # encoded | gzip | file | stdin
        self.focus = ""
        self.notes: list = []

    def note(self, text: str):
        text = clean_text(text, 400)
        if text and text not in self.notes and len(self.notes) < 20:
            self.notes.append(text)

    def view(self) -> dict:
        out = {"id": self.id, "state": self.state, "kind": self.kind, "elapsed": round(time.time() - self.started, 1), "opened": self.opened, "opened_after": self.opened_after,
               "strategy": self.strategy, "route": self.route, "focus": self.focus, "notes": list(self.notes)}
        out.update({k: v for k, v in self.result.items() if k != "available"})
        return out


_lock = threading.Lock()
_jobs: dict = {}
_active: Job | None = None
_last: Job | None = None


def _taskkill(exe, which=shutil.which):
    found = which("taskkill.exe")
    if found:
        return found
    try:
        cand = Path(exe).parents[2] / "taskkill.exe" if exe else None
    except IndexError:
        cand = None
    return str(cand) if cand and cand.exists() else None


def _kill(proc, win_pid=None, plat="linux", exe=None):
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
        tk = _taskkill(exe)
        if tk:
            try:
                subprocess.run([tk, "/F", "/T", "/PID", str(win_pid)], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _b64_text(raw: bytes) -> str:
    try:
        return base64.b64decode(raw.strip()).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return ""


def _run_argv(argv: list, timeout: float, job: Job, plat: str, popen=subprocess.Popen, stdin_text: str | None = None) -> tuple:
    """Run one dialog process: (returncode | None, stdout, stderr, reason in '' | 'timeout' | 'cancelled'). Reading never blocks the timeout.
    The script's PB_PID / PB_OPENED / PB_STRATEGY / PB_FOCUS / PB_NOTE lines are applied to `job` as they arrive."""
    kw = {"stdin": subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True
    proc = popen(argv, **kw)
    job.proc = proc
    bufs = {"out": [], "err": []}
    if stdin_text is not None:
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def pump(stream, key):
        try:
            for chunk in iter(lambda: stream.readline(), b""):
                bufs[key].append(chunk)
                if key != "out":
                    continue
                tag, _, rest = chunk.partition(b":")
                if tag == b"PB_PID":
                    try:
                        job.win_pid = int(rest.strip())
                    except ValueError:
                        pass
                elif tag == b"PB_OPENED":
                    job.opened = True
                    job.opened_after = round(time.time() - job.started, 1)
                elif tag == b"PB_STRATEGY":
                    job.strategy = _b64_text(rest)
                elif tag == b"PB_FOCUS":
                    job.focus = _b64_text(rest)
                elif tag in (b"PB_NOTE", b"PB_ENV"):
                    job.note(("" if tag == b"PB_NOTE" else "PowerShell: ") + _b64_text(rest))
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
            _kill(proc, job.win_pid, plat, job.exe)
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


_temp_cache: dict = {}


def windows_temp(exe: str, plat: str, run=subprocess.run) -> tuple:
    """(Windows temp folder as Windows writes it, the same folder as this process can write to it) or ('', ''). WSL asks PowerShell once (and caches the answer):
    a script file must be somewhere PowerShell can run it from, and \\\\wsl.localhost\\ paths are not reliably runnable under the default execution policy."""
    if plat == "windows":
        import tempfile
        return tempfile.gettempdir(), tempfile.gettempdir()
    if exe in _temp_cache:
        return _temp_cache[exe]
    pair = ("", "")
    try:
        got = run([exe, "-NoProfile", "-NonInteractive", "-Command", "[IO.Path]::GetTempPath()"], capture_output=True, timeout=20)
        win = got.stdout.decode("utf-8", "replace").strip().splitlines()[-1].strip() if got.returncode == 0 and got.stdout.strip() else ""
        if win and chooser.DRIVE_RE.match(win):
            pair = (win.rstrip("\\"), chooser.to_linux(win, wsl=True, run=run))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    _temp_cache[exe] = pair
    return pair


def _write_script_file(folder: str):
    def write(name: str, text: str):
        path = Path(folder) / name
        with open(path, "wb") as f:
            f.write(b"\xef\xbb\xbf" + text.encode("utf-8"))      # a BOM, so Windows PowerShell 5.1 reads it as UTF-8
        return str(path)
    return write


def _run_windows(job: Job, script: str, exe: str, plat: str, timeout: float, popen, run, limit: int = COMMAND_LINE_LIMIT) -> tuple:
    """Run the dialog script by the first route that works: (rc, out, err, reason). A route that did not start the script at all (no PB_ENV line) falls through to the next."""
    routes = windows_routes(exe, script, limit)
    if routes[0][0] not in ("encoded", "gzip"):
        win, local = windows_temp(exe, plat, run)
        if win and local:
            routes = windows_routes(exe, script, limit, win_temp=win, write_file=_write_script_file(local))
    last = (None, "", "", "")
    for route, argv, cleanup in routes:
        job.route = route
        try:
            last = _run_argv(argv, timeout, job, plat, popen, stdin_text=gzip_bootstrap(script) + "\n" if route == "stdin" else None)
        except OSError as exc:
            job.note(f"route {route}: could not start ({exc})")
            last = (None, "", str(exc), "")
            continue
        finally:
            if cleanup:
                try:
                    os.remove(cleanup)
                except OSError:
                    pass
        rc, out, err, reason = last
        if reason or "PB_ENV:" in out or "PB_RESULT:" in out or "PB_ERROR:" in out or rc == EXIT_CANCELLED:
            return last
        job.note(f"route {route}: PowerShell did not run the script (exit {rc}){': ' + clean_text(err.strip().splitlines()[-1], 200) if err.strip() else ''}")
    return last


def _execute(job: Job, kind: str, title: str, initial, filters, timeout: float, caps: dict, plat: str, popen, run) -> dict:
    title = clean_text(title, 120) or {"folder": "Choose a folder", "file": "Choose a file", "save": "Save as"}[kind]
    flt = clean_filters(filters)
    start = start_folder(initial, plat, run)
    exe = caps["exe"]
    job.exe, job.plat = exe, plat
    opts = job.opts
    if caps["kind"] in ("windows", "wsl"):
        script = windows_script(kind, title, start, flt, int(timeout), bool(opts.get("dry")), int(opts.get("selftest") or 0), str(opts.get("strategy") or ""))
        try:
            rc, out, err, reason = _run_windows(job, script, exe, plat, timeout, popen, run, opts.get("limit") or COMMAND_LINE_LIMIT)
        except OSError as exc:
            return {"ok": False, "cancelled": False, "error": f"could not start the folder window ({exc})"}
    else:
        if caps["kind"] == "mac":
            argv = mac_argv(exe, kind, title, start, flt)
        else:
            argv = linux_argv(caps["kind"], exe, kind, title, start, flt)
        job.strategy, job.route = caps["kind"], "argv"
        job.opened, job.opened_after = True, 0.0         # these programs give no signal: started means the window is (about to be) up
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
            if not _decode_tag(out, "PB_ERROR") and "language mode" in err.lower():
                msg = ("PowerShell is locked down on this computer (Constrained Language Mode, a security policy), so it cannot open a folder window: "
                       "use the built-in browser or ask your IT administrator")
            elif not _decode_tag(out, "PB_ERROR") and not err.strip():
                msg = f"PowerShell did not run the folder window (exit {rc}); " + ("; ".join(job.notes[-2:]) or "no output")
            return {"ok": False, "cancelled": False, "error": msg}
        if opts.get("dry") or opts.get("selftest"):
            return {"ok": True, "cancelled": False, "error": "", "path": raw, "display": raw, "windows_path": "", "mount_hint": "", "warning": ""}
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
                which=shutil.which, popen=subprocess.Popen, run=subprocess.run, wsl: bool | None = None, **opts) -> dict:
    """Open the computer's dialog and wait: {'ok', 'path', 'display', 'windows_path', 'cancelled', 'error', 'available'} (+ 'mount_hint', 'warning').
    Refuses while another dialog is open. `kind` is 'folder', 'file' or 'save'. opts: selftest=<seconds> (the window closes itself), dry=True, limit=<command-line chars>, strategy='winforms'|'shell' (skip the better windows)."""
    job = _begin(kind, title, platform, env, which, wsl)
    if isinstance(job, dict):
        return job
    job.opts = opts
    return _finish(job, kind, title, initial, filters, timeout, platform, env, which, popen, run, wsl)


def _begin(kind, title, platform, env, which, wsl):
    global _active, _last
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
        _last = job
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
    job.opts = {k: inject[k] for k in ("selftest", "dry", "limit", "strategy") if k in inject}
    job.thread = threading.Thread(target=_finish, args=(job, kind, title, initial, filters, timeout, platform, env, which, popen, run, wsl), daemon=True)
    job.thread.start()
    return {"id": job.id, "state": "open", "available": True}


def last_view() -> dict:
    """The most recently started dialog's view (what happened, even after it ended): {} when none was started."""
    return _last.view() if _last is not None else {}


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
    """Windows and WSL: ask Windows to bring the open dialog forward (found by its title, then by the process that owns it). Other platforms cannot be raised from here."""
    with _lock:
        job = _jobs.get(job_id) if job_id else _active
    if job is None or job.state != "open":
        return {"ok": False, "error": "no folder window is open"}
    caps = capabilities(platform, env, which, wsl)
    if caps["kind"] not in ("windows", "wsl"):
        return {"ok": False, "error": "this computer's folder window cannot be raised from here: look for it in the taskbar or the dock"}
    title = clean_text(job.title, 120) or {"folder": "Choose a folder", "file": "Choose a file", "save": "Save as"}[job.kind]
    b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
    pid = int(job.win_pid or 0)
    script = (f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'));$s=New-Object -ComObject WScript.Shell;"
              f"$ok=$s.AppActivate($t);if(-not $ok -and {pid} -gt 0){{$ok=$s.AppActivate({pid})}};if($ok){{'activated'}}else{{'not-found'}}")
    try:
        got = run(windows_argv(caps["exe"], script), capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    said = (getattr(got, "stdout", b"") or b"").decode("utf-8", "replace") if isinstance(getattr(got, "stdout", b""), (bytes, bytearray)) else str(getattr(got, "stdout", ""))
    if "not-found" in said:
        return {"ok": False, "error": "Windows could not find the folder window to raise it: look for the PowerShell or Explorer button in the taskbar"}
    return {"ok": True}


def cleanup():
    """Kill any open dialog (the server is exiting)."""
    with _lock:
        jobs = [j for j in _jobs.values() if j.state == "open"]
    for job in jobs:
        job.cancel_event.set()
        _kill(job.proc, job.win_pid, job.plat, job.exe)


atexit.register(cleanup)


def reset():
    """Forget every job (tests)."""
    global _active, _last
    cleanup()
    with _lock:
        _jobs.clear()
        _active = _last = None
    _temp_cache.clear()
