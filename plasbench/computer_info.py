"""What this computer really is: CPU, memory, the limits in force for this process, the host behind WSL, and every drive.

The window's "This computer" card shows `report()`. Three things were wrong before: under WSL the numbers were the WSL virtual
machine's with no word that a Windows host stands behind it; the memory was the installed total, not what is free (the figure a
benchmark can actually use); and nothing said which limits (a cgroup, `.wslconfig`, CPU affinity) apply to this process.

Every probe takes its source as an argument (`meminfo`, `mounts_text`, `df_text`, `lsblk_text`, `host_json`, `run`, `usage`), so tests
feed sample /proc/meminfo, /proc/mounts, df, lsblk, powershell, wmic, sysctl, vm_stat and `mount` output for Linux, WSL, macOS and
Windows. Every probe is defensive: a probe that fails gives `None` (the window shows "unknown"), never an exception. Nothing here
mounts, writes or changes anything; the drvfs mount command for an unmounted Windows drive is only shown, as chooser.mount_help words it.
Standard library only. Units are binary: 1 GB here is 2**30 bytes (GiB), matching free/df -h, and the labels say so.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

GB = 2 ** 30
SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync", "sync.com", "nextcloud")
NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3", "smbfs", "afpfs", "webdav", "fuse.sshfs", "fuse.rclone", "ceph", "glusterfs", "lustre")
PSEUDO_FS = ("proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "overlay", "squashfs", "autofs", "mqueue", "debugfs",
             "tracefs", "securityfs", "pstore", "bpf", "configfs", "fusectl", "hugetlbfs", "binfmt_misc", "ramfs", "nsfs", "efivarfs",
             "rpc_pipefs", "devfs", "fdescfs", "lxcfs")
WSL_FS = ("drvfs", "9p", "virtiofs")
WIN_DRIVE_TYPES = {0: "unknown", 1: "no root", 2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "ram disk"}


# ---------------------------------------------------------------- small helpers
def _read(path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _run(argv, timeout=20) -> str | None:
    """stdout of a command, or None when it is missing, fails or times out. Never raises."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return p.stdout if p.returncode == 0 else None


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _gb(n):
    return None if n is None else round(n / GB, 1)


def parse_size(text) -> int | None:
    """'8GB', '512MB', '4294967296' -> bytes (the units .wslconfig uses; 1 GB = 2**30)."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*", str(text or ""), re.I)
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "K": 2 ** 10, "M": 2 ** 20, "G": GB, "T": 2 ** 40}[m.group(2).upper()])


# ---------------------------------------------------------------- Linux / WSL: /proc
def parse_meminfo(text) -> dict:
    """/proc/meminfo -> bytes. The kernel writes 'kB' but means KiB (1024). available falls back to free + buffers + cached on old kernels."""
    kib = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            kib[m.group(1)] = int(m.group(2))
    def b(key):
        return kib[key] * 1024 if key in kib else None
    available = b("MemAvailable")
    if available is None and "MemFree" in kib:
        available = (kib["MemFree"] + kib.get("Buffers", 0) + kib.get("Cached", 0)) * 1024
    return {"total": b("MemTotal"), "available": available, "free": b("MemFree"), "swap_total": b("SwapTotal"), "swap_free": b("SwapFree")}


def parse_cpuinfo(text) -> dict:
    """/proc/cpuinfo -> model, logical (processor entries), physical (distinct physical id + core id; None when the file does not say, e.g. ARM)."""
    model, logical, cores = "", 0, set()
    phys, core = None, None
    for line in (text or "").splitlines() + [""]:
        if not line.strip():
            if phys is not None and core is not None:
                cores.add((phys, core))
            phys, core = None, None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "processor" and value.isdigit():
            logical += 1
        elif key in ("model name", "hardware", "model") and not model and not value.isdigit():
            model = value
        elif key == "physical id":
            phys = value
        elif key == "core id":
            core = value
    return {"model": model or None, "logical": logical or None, "physical": len(cores) or None}


def cgroup_limits(read=_read) -> dict:
    """The memory and CPU limits a container runtime or systemd puts on this process: {'memory': bytes|None, 'cpus': float|None, 'source': 'cgroup v2'|'cgroup v1'|None}.
    'max' / -1 / absurdly large values mean no limit."""
    out = {"memory": None, "cpus": None, "source": None}
    def lim(text):
        v = _int(text)
        return v if v is not None and 0 < v < 2 ** 60 else None
    mem2, cpu2 = read("/sys/fs/cgroup/memory.max"), read("/sys/fs/cgroup/cpu.max")
    if mem2 is not None or cpu2 is not None:
        out["source"] = "cgroup v2"
        out["memory"] = lim(mem2)
        parts = (cpu2 or "").split()
        if len(parts) == 2 and _int(parts[0]) and _int(parts[1]):
            out["cpus"] = round(_int(parts[0]) / _int(parts[1]), 2)
        return out
    mem1, quota, period = read("/sys/fs/cgroup/memory/memory.limit_in_bytes"), read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if mem1 is not None or quota is not None:
        out["source"] = "cgroup v1"
        out["memory"] = lim(mem1)
        if _int(quota) and _int(quota) > 0 and _int(period):
            out["cpus"] = round(_int(quota) / _int(period), 2)
    return out


def parse_wslconfig(text) -> dict:
    """.wslconfig [wsl2] section -> {'memory': bytes, 'processors': int, 'swap': bytes} for the keys that are set."""
    out, section = {}, ""
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        elif section == "wsl2" and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key in ("memory", "swap"):
                out[key] = parse_size(value)
            elif key == "processors" and value.isdigit():
                out["processors"] = int(value)
    return {k: v for k, v in out.items() if v is not None}


# ---------------------------------------------------------------- Windows host (also read from WSL)
HOST_PS = ("$c=@(Get-CimInstance Win32_Processor);$o=Get-CimInstance Win32_OperatingSystem;"
           "$pf=(Get-CimInstance Win32_PageFileUsage|Measure-Object AllocatedBaseSize -Sum).Sum;"
           "[pscustomobject]@{Name=$c[0].Name;Cores=($c|Measure-Object NumberOfCores -Sum).Sum;Logical=($c|Measure-Object NumberOfLogicalProcessors -Sum).Sum;"
           "TotalKiB=$o.TotalVisibleMemorySize;FreeKiB=$o.FreePhysicalMemory;PageFileMiB=$pf;Caption=$o.Caption;UserProfile=$env:USERPROFILE}|ConvertTo-Json -Compress")
DISKS_PS = ("$bus=@{};try{Get-Partition|Where-Object DriveLetter|ForEach-Object{$bus[[string]$_.DriveLetter]=[string](Get-Disk -Number $_.DiskNumber).BusType}}catch{};"
            "@(Get-CimInstance Win32_LogicalDisk|ForEach-Object{[pscustomobject]@{DeviceID=$_.DeviceID;VolumeName=$_.VolumeName;DriveType=$_.DriveType;FileSystem=$_.FileSystem;"
            "Size=$_.Size;FreeSpace=$_.FreeSpace;ProviderName=$_.ProviderName;Access=$_.Access;Bus=$bus[$_.DeviceID.Substring(0,1)]}})|ConvertTo-Json -Compress")


def _json(text):
    try:
        return json.loads((text or "").strip().lstrip("\ufeff"))
    except ValueError:
        return None


def parse_host_json(text) -> dict | None:
    """The HOST_PS output -> {'cpu_model', 'cores', 'logical', 'total', 'free', 'pagefile', 'os', 'userprofile'} (bytes), or None."""
    d = _json(text)
    if not isinstance(d, dict):
        return None
    return {"cpu_model": (d.get("Name") or "").strip() or None, "cores": _int(d.get("Cores")), "logical": _int(d.get("Logical")),
            "total": (_int(d.get("TotalKiB")) or 0) * 1024 or None, "free": (_int(d.get("FreeKiB")) or 0) * 1024 or None,
            "pagefile": (_int(d.get("PageFileMiB")) or 0) * 2 ** 20 or None, "os": d.get("Caption"), "userprofile": d.get("UserProfile")}


def parse_windows_disks(text) -> list:
    """The DISKS_PS output (one object, or a list) -> one dict per Windows drive."""
    d = _json(text)
    if isinstance(d, dict):
        d = [d]
    out = []
    for row in d if isinstance(d, list) else []:
        if not isinstance(row, dict) or not row.get("DeviceID"):
            continue
        out.append({"letter": str(row["DeviceID"])[:1].upper(), "label": (row.get("VolumeName") or "").strip(), "drive_type": _int(row.get("DriveType")) or 0,
                    "fs": row.get("FileSystem") or None, "total": _int(row.get("Size")), "free": _int(row.get("FreeSpace")),
                    "provider": row.get("ProviderName") or "", "bus": (row.get("Bus") or "").strip() or None,
                    "read_only": {1: True, 2: False, 3: False}.get(_int(row.get("Access")))})
    return out


def parse_wmic_csv(text) -> list:
    """`wmic ... /format:csv` -> list of dict (header row names the columns; the Node column is dropped). wmic is deprecated but still the only tool on old Windows."""
    lines = [ln for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return []
    head = [h.strip() for h in lines[0].split(",")]
    rows = []
    for ln in lines[1:]:
        cells = ln.split(",")
        if len(cells) < len(head):
            continue
        row = dict(zip(head, cells[:len(head)]))
        row.pop("Node", None)
        rows.append({k: v.strip() for k, v in row.items()})
    return rows


def host_info(run=_run, in_wsl=False) -> dict | None:
    """CPU, memory and disks of the Windows host (native Windows, or the machine behind WSL), or None when PowerShell cannot be reached."""
    exe = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    base = [exe, "-NoProfile", "-NonInteractive", "-Command"] if exe else None
    host = disks = None
    if base:
        host = parse_host_json(run(base + [HOST_PS]))
        disks = parse_windows_disks(run(base + [DISKS_PS]))
    if host is None:     # the old tool: wmic
        wmic = shutil.which("wmic.exe") or shutil.which("wmic")
        if wmic:
            cpu = parse_wmic_csv(run([wmic, "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors", "/format:csv"]))
            osr = parse_wmic_csv(run([wmic, "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory,Caption", "/format:csv"]))
            if cpu or osr:
                host = {"cpu_model": cpu[0].get("Name") if cpu else None, "cores": sum(_int(r.get("NumberOfCores")) or 0 for r in cpu) or None,
                        "logical": sum(_int(r.get("NumberOfLogicalProcessors")) or 0 for r in cpu) or None,
                        "total": (_int(osr[0].get("TotalVisibleMemorySize")) or 0) * 1024 or None if osr else None,
                        "free": (_int(osr[0].get("FreePhysicalMemory")) or 0) * 1024 or None if osr else None,
                        "pagefile": None, "os": osr[0].get("Caption") if osr else None, "userprofile": None}
    if not disks:
        wmic = shutil.which("wmic.exe") or shutil.which("wmic")
        if wmic:
            rows = parse_wmic_csv(run([wmic, "logicaldisk", "get", "DeviceID,VolumeName,DriveType,FileSystem,Size,FreeSpace,ProviderName,Access", "/format:csv"]))
            disks = [{"letter": r["DeviceID"][:1].upper(), "label": r.get("VolumeName", ""), "drive_type": _int(r.get("DriveType")) or 0, "fs": r.get("FileSystem") or None,
                      "total": _int(r.get("Size")), "free": _int(r.get("FreeSpace")), "provider": r.get("ProviderName", ""), "bus": None,
                      "read_only": {1: True, 2: False, 3: False}.get(_int(r.get("Access")))} for r in rows if r.get("DeviceID")]
    if host is None and not disks:
        return None
    host = dict(host or {})
    host["disks"] = disks or []
    return host


# ---------------------------------------------------------------- macOS
def parse_vm_stat(text) -> int | None:
    """`vm_stat` -> bytes that can be used without swapping: (free + inactive + speculative) pages x page size."""
    m = re.search(r"page size of (\d+) bytes", text or "")
    if not m:
        return None
    size = int(m.group(1))
    pages = 0
    for key in ("free", "inactive", "speculative"):
        p = re.search(rf"^Pages {key}:\s+(\d+)", text, re.M)
        pages += int(p.group(1)) if p else 0
    return pages * size or None


def parse_swapusage(text) -> tuple:
    """`sysctl vm.swapusage` -> (total, free) bytes; macOS prints 'total = 2048.00M  used = 1024.00M  free = 1024.00M'."""
    def val(key):
        m = re.search(rf"{key} = ([\d.]+)([MGK])", text or "")
        return int(float(m.group(1)) * {"K": 2 ** 10, "M": 2 ** 20, "G": GB}[m.group(2)]) if m else None
    return val("total"), val("free")


def parse_mac_mount(text) -> list:
    """macOS `mount` -> [{'device', 'mount', 'fs', 'flags'}] from lines like '/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled)'."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^(.+?) on (.+?) \(([^)]*)\)\s*$", line)
        if m:
            flags = [f.strip() for f in m.group(3).split(",")]
            out.append({"device": m.group(1), "mount": m.group(2), "fs": flags[0], "flags": flags[1:]})
    return out


# ---------------------------------------------------------------- the environment this process runs in
def environment(platform_name=None, meminfo=None, cpuinfo=None, cgroups=None, affinity=None, run=_run, in_wsl=False, wslconfig=None) -> dict:
    """What this process sees. Memory in bytes; every field may be None (unknown)."""
    platform_name = platform_name or ("windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux")
    env = {"cpu_model": None, "logical": None, "physical": None, "usable_cpus": None, "memory_total": None, "memory_available": None,
           "swap_total": None, "swap_free": None, "limits": [], "source": ""}
    try:
        if platform_name == "linux":
            mem = parse_meminfo(meminfo if meminfo is not None else _read("/proc/meminfo"))
            cpu = parse_cpuinfo(cpuinfo if cpuinfo is not None else _read("/proc/cpuinfo"))
            env.update(cpu_model=cpu["model"], logical=cpu["logical"] or os.cpu_count(), physical=cpu["physical"], memory_total=mem["total"],
                       memory_available=mem["available"], swap_total=mem["swap_total"], swap_free=mem["swap_free"], source="/proc/meminfo, /proc/cpuinfo")
            if affinity is None:
                try:
                    affinity = len(os.sched_getaffinity(0))
                except (AttributeError, OSError):
                    affinity = None
            usable = affinity or env["logical"]
            cg = cgroup_limits() if cgroups is None else cgroups
            if cg.get("memory") and (env["memory_total"] is None or cg["memory"] < env["memory_total"]):
                env["limits"].append({"what": "memory", "value": cg["memory"], "by": cg["source"],
                                      "text": f"memory is limited to {_gb(cg['memory'])} GB by a {cg['source']} limit (a container or service), below the {_gb(env['memory_total'])} GB installed"})
                env["memory_available"] = min(env["memory_available"] or cg["memory"], cg["memory"])
            if cg.get("cpus") and (usable is None or cg["cpus"] < usable):
                env["limits"].append({"what": "cpu", "value": cg["cpus"], "by": cg["source"], "text": f"CPU time is limited to {cg['cpus']:g} CPUs by a {cg['source']} limit"})
                usable = max(1, int(cg["cpus"]))
            if affinity and env["logical"] and affinity < env["logical"]:
                env["limits"].append({"what": "cpu", "value": affinity, "by": "CPU affinity", "text": f"this process may use only {affinity} of the {env['logical']} CPUs (CPU affinity)"})
            env["usable_cpus"] = usable
            if in_wsl:
                env["limits"].append({"what": "wsl", "value": None, "by": ".wslconfig",
                                      "text": "inside WSL2 these numbers are the WSL virtual machine's, not the whole computer's: its memory, CPUs and swap are set by "
                                              "C:\\Users\\<you>\\.wslconfig (memory=, processors=, swap=) and change only after `wsl --shutdown`"})
                if wslconfig:
                    env["wslconfig"] = wslconfig
        elif platform_name == "macos":
            def sysctl(name):
                out = run(["sysctl", "-n", name])
                return out.strip() if out else None
            env.update(cpu_model=sysctl("machdep.cpu.brand_string"), logical=_int(sysctl("hw.logicalcpu")) or os.cpu_count(), physical=_int(sysctl("hw.physicalcpu")),
                       memory_total=_int(sysctl("hw.memsize")), memory_available=parse_vm_stat(run(["vm_stat"])), source="sysctl, vm_stat")
            env["swap_total"], env["swap_free"] = parse_swapusage(run(["sysctl", "vm.swapusage"]))
            env["usable_cpus"] = env["logical"]
        else:
            env.update(logical=os.cpu_count(), usable_cpus=os.cpu_count(), cpu_model=platform.processor() or None, source="Windows API")
            try:
                import ctypes

                class MS(ctypes.Structure):
                    _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                                ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong),
                                ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
                ms = MS()
                ms.l = ctypes.sizeof(MS)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                    env.update(memory_total=ms.total, memory_available=ms.avail, swap_total=max(0, ms.tpage - ms.total), swap_free=max(0, ms.apage - ms.avail))
            except (OSError, AttributeError, ValueError):
                pass
    except Exception:  # noqa: BLE001 - a failing probe is "unknown", never a crash
        pass
    return env


def benchmark_defaults(env: dict, overrides: dict | None = None) -> dict:
    """What a benchmark will use here, mirroring config/config.sh: THREADS = the usable CPUs (nproc; one job slot) and MEMORY_GB = 80% of the memory
    available now, never below 2. An explicit THREADS / MEMORY_GB setting always wins. config.sh's nproc does not see a cgroup CPU or memory limit; this
    estimate does, so it can be lower than what a run on a limited container would actually try (it says so in `notes`)."""
    overrides = overrides or {}
    notes = []
    threads = _int(overrides.get("THREADS")) or env.get("usable_cpus")
    avail = env.get("memory_available")
    mem = _int(overrides.get("MEMORY_GB")) or (max(2, int(avail * 0.8 / GB)) if avail else None)
    if any(limit["by"].startswith("cgroup") for limit in env.get("limits", [])):
        notes.append("a cgroup limit is in force; config.sh sizes threads and assembler memory from nproc and /proc/meminfo, which do not see it, "
                     "so set THREADS and MEMORY_GB yourself if runs are killed (exit 137)")
    return {"threads": threads, "memory_gb": mem, "threads_set": bool(_int(overrides.get("THREADS"))), "memory_set": bool(_int(overrides.get("MEMORY_GB"))), "notes": notes}


# ---------------------------------------------------------------- drives
def parse_mounts(text) -> list:
    """/proc/mounts -> [{'device', 'mount', 'fs', 'read_only'}] (mount points decode \\040 and friends)."""
    out = []
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) >= 4:
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), p[1])
            out.append({"device": p[0], "mount": mount, "fs": p[2], "read_only": "ro" in p[3].split(",")})
    return out


def parse_df(text) -> dict:
    """`df -kP` (or macOS `df -k`) -> {mount: (total, used, free)} in bytes."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+(?:\d+\s+\d+\s+\d+%\s+)?(/.*|[A-Za-z]:.*)$", line)
        if m:
            out[m.group(6).strip()] = (int(m.group(2)) * 1024, int(m.group(3)) * 1024, int(m.group(4)) * 1024)
    return out


def parse_lsblk(text) -> dict:
    """`lsblk -J -o NAME,LABEL,MOUNTPOINT,RM,HOTPLUG,TRAN,FSTYPE,TYPE` -> {mountpoint: {'label', 'removable', 'transport'}}. A device is removable when lsblk says RM or
    HOTPLUG, or its transport is usb; a partition inherits that from its disk."""
    out = {}
    data = _json(text)
    def walk(node, parent_removable, parent_tran):
        rm = bool(node.get("rm") in (True, 1, "1")) or bool(node.get("hotplug") in (True, 1, "1")) or parent_removable
        tran = node.get("tran") or parent_tran
        mounts = [node.get("mountpoint")] + list(node.get("mountpoints") or [])
        for mount in filter(None, mounts):
            out[mount] = {"label": node.get("label") or "", "removable": rm or tran == "usb", "transport": tran}
        for child in node.get("children") or []:
            walk(child, rm, tran)
    for dev in (data or {}).get("blockdevices", []) if isinstance(data, dict) else []:
        walk(dev, False, None)
    return out


def _holder(path, mounts):
    """The mount point (longest prefix) that holds `path`."""
    best = ""
    p = str(path)
    for mount in mounts:
        if not mount:
            continue
        m = mount.rstrip("/\\")
        hit = (m == "" or p == m or p.startswith(m + "/")) if mount.startswith("/") else (p.lower() == m.lower() or p.lower().startswith(m.lower() + "\\") or p.lower().startswith(m.lower() + "/"))
        if hit and len(m) >= len(best.rstrip("/\\")):
            best = mount
    return best


def _is_cloud(*texts) -> bool:
    return any(marker in t.lower() for t in texts if t for marker in SYNC_MARKERS)


def _usage(path, usage=None):
    try:
        u = (usage or shutil.disk_usage)(path)
        return u.total, u.used, u.free
    except (OSError, ValueError, TypeError):
        return None


def list_drives(platform_name: str, wsl: bool = False, mounts_text=None, df_text=None, lsblk_text=None, mac_mount_text=None, host=None,
                usage=None, wsl_drives_dir: str = "/mnt", where: dict | None = None) -> list:
    """Every mounted drive or volume, with what is known about it. `where` names folders to mark: {'data folder': path, 'workspace': path, 'study': path}.
    Each dict: id, label, mount, device, windows (letter 'E:' or ''), fs, total, used, free (bytes or None), type (internal | removable | network | optical | cloud-synced |
    virtual | unknown), type_certain (False when the type is a guess from the mount point), read_only (True/False/None), plugged_in, mounted, holds, warnings, hint."""
    drives = _list_drives(platform_name, wsl, mounts_text, df_text, lsblk_text, mac_mount_text, host, usage, wsl_drives_dir, where)
    mounts = [d["mount"] for d in drives]
    for name, path in {k: v for k, v in (where or {}).items() if v}.items():
        holder = _holder(path, mounts)
        for d in drives:
            if holder and d["mount"] == holder:
                d["holds"].append(name)
                if d["free"] is not None and d["free"] < 50 * GB and name == "data folder":
                    d["warnings"].append(f"only {_gb(d['free'])} GB free where the data folder is; a public cohort needs hundreds of GB")
    return drives


def _list_drives(platform_name, wsl, mounts_text, df_text, lsblk_text, mac_mount_text, host, usage, wsl_drives_dir, where) -> list:
    from . import chooser
    disks = (host or {}).get("disks") or []
    win = {d["letter"]: d for d in disks}
    df = parse_df(df_text)
    lsblk = parse_lsblk(lsblk_text)
    drives = []

    def usage_for(mount):
        u = _usage(mount, usage)
        if u is None and mount in df:
            u = df[mount]
        return u

    def finish(d):
        total, used, free = (d.pop("_u", None) or (None, None, None))
        d.update(total=total, used=used, free=free)
        if d["type"] != "cloud-synced" and _is_cloud(d["label"], d["mount"]):
            d["type"], d["type_certain"] = "cloud-synced", True
        warn = d["warnings"]
        if d["read_only"]:
            warn.append("read-only: PlasBench cannot write results here")
        if d["type"] == "network":
            warn.append("network location: slower, and a dropped connection stops a run")
        if d["type"] == "removable":
            warn.append("removable drive: keep it connected while benchmarks run; a disconnected drive stops the run")
        if d["type"] == "cloud-synced":
            warn.append("cloud-synced folder or drive: syncing large read and assembly files is slow and can lock files mid-run; a plain local disk is safer")
        if d["windows"] and wsl and d["mounted"]:
            warn.append(f"Windows drive seen from Ubuntu ({d['mount']}): slower than Ubuntu's own disk for many small files and for git")
        d["id"] = d["mount"] or d["device"]
        drives.append(d)

    def base(**kw):
        d = {"label": "", "mount": "", "device": "", "windows": "", "fs": None, "type": "unknown", "type_certain": False, "read_only": None, "plugged_in": True,
             "mounted": True, "holds": [], "warnings": [], "hint": ""}
        d.update(kw)
        return d

    if platform_name == "windows":
        for dk in disks:
            kind = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "virtual"}.get(dk["drive_type"], "unknown")
            certain = dk["drive_type"] in (2, 4, 5, 6) or dk["bus"] is not None
            if dk["drive_type"] == 3 and dk["bus"] and dk["bus"].upper() in ("USB", "1394", "SD", "MMC"):
                kind, certain = "removable", True
            mount = f"{dk['letter']}:\\"
            total, free = dk["total"], dk["free"]
            u = (total, total - free, free) if total is not None and free is not None else usage_for(mount)
            finish(base(label=dk["label"] or dk["provider"], mount=mount, device=f"{dk['letter']}:", windows=f"{dk['letter']}:", fs=dk["fs"], type=kind,
                        type_certain=certain, read_only=dk["read_only"], _u=u))
        return drives

    if platform_name == "macos":
        for m in parse_mac_mount(mac_mount_text):
            fs, flags = m["fs"], m["flags"]
            if not m["device"].startswith(("/dev/", "//")) and fs not in NETWORK_FS:
                continue
            if m["mount"].startswith(("/System/Volumes/VM", "/System/Volumes/Preboot", "/System/Volumes/Update", "/System/Volumes/xarts", "/System/Volumes/iSCPreboot",
                                      "/System/Volumes/Hardware", "/private/var/vm", "/Library/Developer")):
                continue
            net = fs in NETWORK_FS or m["device"].startswith("//")
            ext = m["mount"].startswith("/Volumes/") and "local" in flags and not net
            kind = "network" if net else "removable" if ext else "internal"
            label = PurePosixPath(m["mount"]).name if m["mount"] != "/" else "Macintosh HD"
            finish(base(label=label, mount=m["mount"], device=m["device"], fs=fs, type=kind, type_certain=net,
                        read_only="read-only" in flags, _u=usage_for(m["mount"])))
        return drives

    # linux and WSL
    seen = set()
    for m in parse_mounts(mounts_text):
        fs, mount, dev = m["fs"], m["mount"], m["device"]
        if mount in seen:
            continue
        if wsl and fs in WSL_FS:
            parent = PurePosixPath(mount).parent
            if str(parent) != wsl_drives_dir or len(PurePosixPath(mount).name) != 1 or not PurePosixPath(mount).name.isalpha():
                continue
        elif fs in PSEUDO_FS and mount != "/":
            continue
        elif dev.startswith("/dev/loop") or mount.startswith(("/mnt/wsl", "/usr/lib/wsl", "/snap/", "/boot/efi", "/sys", "/proc", "/dev", "/run/user", "/run/lock", "/var/lib/docker")):
            continue
        elif not (dev.startswith("/dev/") or fs in NETWORK_FS or fs.startswith("fuse.") or ":" in dev or dev.startswith("//")):
            continue
        seen.add(mount)
        info = lsblk.get(mount, {})
        letter = PurePosixPath(mount).name.upper() if wsl and fs in WSL_FS else ""
        kind, certain, label = "internal", False, info.get("label") or ""
        if not letter and (fs in NETWORK_FS or dev.startswith("//") or (":" in dev and not dev.startswith("/dev/"))):
            kind, certain = "network", True
        elif letter and letter in win:
            d = win[letter]
            kind = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "virtual"}.get(d["drive_type"], "unknown")
            certain = True
            if d["drive_type"] == 3 and d["bus"] and d["bus"].upper() in ("USB", "1394", "SD", "MMC"):
                kind = "removable"
            label = d["label"] or label
        elif letter:
            kind = "unknown"      # a Windows drive, and the host could not say whether it is internal or removable
        elif info:
            kind, certain = ("removable" if info.get("removable") else "internal"), True
        elif mount.startswith(("/media", "/run/media")) or mount.startswith("/mnt/") and not letter:
            kind = "removable"    # a guess from the mount point
        if not label:
            label = PurePosixPath(mount).name if mount != "/" else "root filesystem"
        finish(base(label=label, mount=mount, device=dev, windows=f"{letter}:" if letter else "", fs=fs, type=kind, type_certain=certain,
                    read_only=m["read_only"], _u=usage_for(mount)))
    if wsl:     # Windows drives the host has but Ubuntu has not mounted: plugged in, not usable until the user mounts them
        mounted = {d["windows"][:1] for d in drives if d["windows"]}
        for letter, dk in sorted(win.items()):
            if letter in mounted:
                continue
            kind = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "virtual"}.get(dk["drive_type"], "unknown")
            if dk["drive_type"] == 3 and dk["bus"] and dk["bus"].upper() in ("USB", "1394", "SD", "MMC"):
                kind = "removable"
            total, free = dk["total"], dk["free"]
            finish(base(label=dk["label"] or dk["provider"], mount="", device=f"{letter}:", windows=f"{letter}:", fs=dk["fs"], type=kind, type_certain=True,
                        read_only=dk["read_only"], mounted=False, hint=chooser.mount_help(letter),
                        _u=(total, total - free, free) if total is not None and free is not None else None))
            drives[-1]["id"] = f"{letter}:"
    return drives


def diff_drives(previous: list | None, current: list) -> dict:
    """Which drives appeared or went away since the last listing: {'new': [id], 'removed': [{'id', 'label'}]}. The first listing (previous is None) reports nothing as new."""
    if previous is None:
        return {"new": [], "removed": []}
    before = {d["id"]: d for d in previous}
    now = {d["id"] for d in current}
    return {"new": sorted(i for i in now if i not in before),
            "removed": [{"id": i, "label": before[i].get("label") or i} for i in sorted(before) if i not in now]}


# ---------------------------------------------------------------- everything the card shows
_LAST: dict = {"ids": None, "drives": None}


def report(where: dict | None = None, overrides: dict | None = None, remember: bool = True) -> dict:
    """The whole card: environment, host (Windows, or the Windows machine behind WSL), what a benchmark will use, and the drives with the change since the last call."""
    from . import platform_info
    o = platform_info.os_kind()
    wsl = platform_info.in_wsl()
    name = {"windows": "windows", "macos": "macos"}.get(o, "linux")
    host = None
    try:
        if o == "windows" or wsl:
            host = host_info(in_wsl=wsl)
    except Exception:  # noqa: BLE001
        host = None
    wslconfig = None
    if wsl and host and host.get("userprofile"):
        try:
            from . import chooser
            wslconfig = parse_wslconfig(_read(Path(chooser.to_linux(host["userprofile"], wsl=True)) / ".wslconfig"))
        except Exception:  # noqa: BLE001
            wslconfig = None
    env = environment(name, in_wsl=wsl, wslconfig=wslconfig)
    if o == "windows" and host:     # the Windows API gives only logical CPUs; the host query adds the model and physical cores
        env["physical"] = env["physical"] or host.get("cores")
        env["cpu_model"] = host.get("cpu_model") or env["cpu_model"]
    mounts = _read("/proc/mounts") if name == "linux" else None
    df_text = lsblk_text = mac_mount = None
    if name == "linux":
        df_text = _run(["df", "-kP"])
        lsblk_text = _run(["lsblk", "-J", "-o", "NAME,LABEL,MOUNTPOINT,MOUNTPOINTS,RM,HOTPLUG,TRAN,FSTYPE,TYPE"]) or _run(["lsblk", "-J", "-o", "NAME,LABEL,MOUNTPOINT,RM,TRAN,FSTYPE,TYPE"])
    elif name == "macos":
        df_text, mac_mount = _run(["df", "-k"]), _run(["mount"])
    try:
        drives = list_drives(name, wsl, mounts, df_text, lsblk_text, mac_mount, host, where=where)
    except Exception:  # noqa: BLE001
        drives = []
    previous = _LAST["drives"]
    change = diff_drives(previous, drives)
    for d in drives:
        d["new"] = d["id"] in change["new"]
    if remember:
        _LAST["drives"] = drives
    return {"environment": env, "host": host, "wsl": wsl, "os": name, "benchmark": benchmark_defaults(env, overrides), "drives": drives, "change": change,
            "units": "GB = 2^30 bytes (GiB), as free and df -h report"}
