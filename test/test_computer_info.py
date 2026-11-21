#!/usr/bin/env python3
"""The window's "This computer" card (plasbench/computer_info.py): resources, limits, the Windows host behind WSL, and every drive.

All sources are injected samples (/proc/meminfo, /proc/cpuinfo, cgroup files, .wslconfig, /proc/mounts, df, lsblk, PowerShell JSON, wmic CSV, sysctl, vm_stat, mount),
so the Linux, WSL, macOS and Windows formats are all tested on any machine. A failing probe must give unknown (None), never an exception.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from plasbench import chooser, computer_info as ci  # noqa: E402

fails = []
GB = 2 ** 30


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"-> {detail}")
    if not ok:
        fails.append(name)


MEMINFO = "MemTotal:        8133980 kB\nMemFree:          412000 kB\nMemAvailable:    7342000 kB\nBuffers:          1000 kB\nCached:           2000 kB\nSwapTotal:       4194304 kB\nSwapFree:        4088000 kB\n"
m = ci.parse_meminfo(MEMINFO)
check("meminfo: kB is KiB (x1024), total/available/swap", m["total"] == 8133980 * 1024 and m["available"] == 7342000 * 1024 and m["swap_total"] == 4 * GB, m)
check("meminfo: available is MemAvailable, not MemFree", m["available"] != m["free"])
old = ci.parse_meminfo("MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 150 kB\n")
check("meminfo on an old kernel: available = free + buffers + cached", old["available"] == 300 * 1024, old)
check("meminfo garbage gives unknown", ci.parse_meminfo("nonsense")["total"] is None and ci.parse_meminfo(None)["total"] is None)

CPU_X86 = "".join(f"processor\t: {i}\nmodel name\t: 13th Gen Intel(R) Core(TM) i7-1365U\nphysical id\t: 0\ncore id\t\t: {i // 2}\n\n" for i in range(6))
c = ci.parse_cpuinfo(CPU_X86)
check("cpuinfo x86: 6 logical, 3 physical, model", c == {"model": "13th Gen Intel(R) Core(TM) i7-1365U", "logical": 6, "physical": 3}, c)
c = ci.parse_cpuinfo("processor : 0\nBogoMIPS : 108\nprocessor : 1\nmodel name : ARMv8 Processor rev 1\n\n")
check("cpuinfo ARM: logical counted, physical unknown", c["logical"] == 2 and c["physical"] is None and "ARMv8" in c["model"], c)
check("cpuinfo garbage gives unknown", ci.parse_cpuinfo("")["logical"] is None)

files = {"/sys/fs/cgroup/memory.max": "2147483648\n", "/sys/fs/cgroup/cpu.max": "200000 100000\n"}
cg = ci.cgroup_limits(read=lambda p: files.get(p))
check("cgroup v2: 2 GB and 2 CPUs", cg == {"memory": 2 * GB, "cpus": 2.0, "source": "cgroup v2"}, cg)
cg = ci.cgroup_limits(read=lambda p: {"/sys/fs/cgroup/memory.max": "max\n", "/sys/fs/cgroup/cpu.max": "max 100000\n"}.get(p))
check("cgroup v2 'max' means no limit", cg["memory"] is None and cg["cpus"] is None and cg["source"] == "cgroup v2", cg)
v1 = {"/sys/fs/cgroup/memory/memory.limit_in_bytes": "1073741824", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "150000", "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}
cg = ci.cgroup_limits(read=lambda p: v1.get(p))
check("cgroup v1: 1 GB and 1.5 CPUs", cg["memory"] == GB and cg["cpus"] == 1.5 and cg["source"] == "cgroup v1", cg)
cg = ci.cgroup_limits(read=lambda p: {"/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1", "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}.get(p))
check("cgroup v1 huge / -1 values mean no limit", cg["memory"] is None and cg["cpus"] is None, cg)
check("no cgroup files: unknown source, no limit", ci.cgroup_limits(read=lambda p: None)["source"] is None)

wc = ci.parse_wslconfig("# comment\n[wsl2]\nmemory=8GB ; trailing\nprocessors=6\nswap=4GB\n[experimental]\nmemory=1GB\n")
check(".wslconfig: memory 8 GB, 6 processors, 4 GB swap; other sections ignored", wc == {"memory": 8 * GB, "processors": 6, "swap": 4 * GB}, wc)
check(".wslconfig empty or missing", ci.parse_wslconfig("") == {} and ci.parse_wslconfig(None) == {})

env = ci.environment("linux", meminfo=MEMINFO, cpuinfo=CPU_X86, cgroups={"memory": 2 * GB, "cpus": 2.0, "source": "cgroup v2"}, affinity=4, in_wsl=True, wslconfig=wc)
whats = [lim["by"] for lim in env["limits"]]
check("environment (WSL, cgroup, affinity): limits listed, usable CPUs and memory reduced",
      env["usable_cpus"] == 2 and env["memory_available"] == 2 * GB and "cgroup v2" in whats and "CPU affinity" in whats and ".wslconfig" in whats
      and env["physical"] == 3 and env["logical"] == 6, env)
check("environment under WSL says these are the VM's numbers", any("virtual machine" in lim["text"] for lim in env["limits"]))
env = ci.environment("linux", meminfo=MEMINFO, cpuinfo=CPU_X86, cgroups={"memory": None, "cpus": None, "source": None}, affinity=6)
check("environment, nothing limited: all 6 CPUs, 7.0 GB available, no limits", env["usable_cpus"] == 6 and not env["limits"] and abs(env["memory_available"] - 7342000 * 1024) < 1, env)
b = ci.benchmark_defaults(env)
check("a benchmark uses the usable CPUs and 85% of the available memory minus 512 MB, 2 to 64 GB (config.sh)", b["threads"] == 6 and b["memory_gb"] == min(64, max(2, (7342000 * 1024 * 85 // 100 - 512 * 1024 * 1024) // GB)), b)
b = ci.benchmark_defaults(env, {"THREADS": "3", "MEMORY_GB": "20"})
check("explicit THREADS / MEMORY_GB win and are marked as yours", b["threads"] == 3 and b["memory_gb"] == 20 and b["threads_set"] and b["memory_set"], b)
env_cg = ci.environment("linux", meminfo=MEMINFO, cpuinfo=CPU_X86, cgroups={"memory": GB, "cpus": None, "source": "cgroup v1"}, affinity=6)
check("a cgroup MEMORY limit needs no warning: config.sh sees it and the budget follows it", not ci.benchmark_defaults(env_cg)["notes"] and ci.benchmark_defaults(env_cg)["memory_gb"] == 2, ci.benchmark_defaults(env_cg))
env_cpu = ci.environment("linux", meminfo=MEMINFO, cpuinfo=CPU_X86, cgroups={"memory": None, "cpus": 2.0, "source": "cgroup v2"}, affinity=6)
check("a cgroup CPU limit warns that config.sh (nproc) does not see it", ci.benchmark_defaults(env_cpu)["notes"], ci.benchmark_defaults(env_cpu))
check("environment never raises on garbage", ci.environment("linux", meminfo="\x00junk", cpuinfo="", cgroups={}, affinity=None)["memory_total"] is None)

# macOS
VM = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:                               10000.\nPages active:                            300000.\nPages inactive:                           50000.\nPages speculative:                         2000.\n"
check("vm_stat: (free + inactive + speculative) x page size", ci.parse_vm_stat(VM) == 62000 * 16384, ci.parse_vm_stat(VM))
check("swapusage parsed", ci.parse_swapusage("vm.swapusage: total = 2048.00M  used = 1024.00M  free = 1024.00M  (encrypted)") == (2048 * 2 ** 20, 1024 * 2 ** 20))
outs = {("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M2 Pro\n", ("sysctl", "-n", "hw.logicalcpu"): "12\n", ("sysctl", "-n", "hw.physicalcpu"): "10\n",
        ("sysctl", "-n", "hw.memsize"): "17179869184\n", ("vm_stat",): VM, ("sysctl", "vm.swapusage"): "vm.swapusage: total = 2048.00M  used = 1024.00M  free = 1024.00M  (encrypted)"}
env = ci.environment("macos", run=lambda argv, timeout=20: outs.get(tuple(argv)))
check("environment macOS: Apple M2 Pro, 10 physical / 12 logical, 16 GB, available from vm_stat",
      env["cpu_model"] == "Apple M2 Pro" and env["physical"] == 10 and env["logical"] == 12 and env["memory_total"] == 16 * GB and env["memory_available"] == 62000 * 16384, env)
check("environment macOS with every probe failing is unknown, not an error", ci.environment("macos", run=lambda argv, timeout=20: None)["memory_total"] is None)

# Windows host (PowerShell JSON and wmic CSV)
HOST = json.dumps({"Name": "13th Gen Intel(R) Core(TM) i7-1365U", "Cores": 10, "Logical": 12, "TotalKiB": 16125592, "FreeKiB": 830000, "PageFileMiB": 46090, "Caption": "Microsoft Windows 11 Pro", "UserProfile": "C:\\Users\\Effiong"})
h = ci.parse_host_json(HOST)
check("host JSON: 10 cores, 12 threads, 15.4 GB (KiB x1024), user profile", h["cores"] == 10 and h["logical"] == 12 and h["total"] == 16125592 * 1024 and h["userprofile"] == "C:\\Users\\Effiong", h)
check("host JSON garbage is None", ci.parse_host_json("not json") is None and ci.parse_host_json("") is None)
DISKS = json.dumps([{"DeviceID": "C:", "VolumeName": "", "DriveType": 3, "FileSystem": "NTFS", "Size": 1048035979264, "FreeSpace": 3705098240, "ProviderName": "", "Access": 0, "Bus": "NVMe"},
                    {"DeviceID": "E:", "VolumeName": "BACKUP", "DriveType": 3, "FileSystem": "exFAT", "Size": 2000000000000, "FreeSpace": 1500000000000, "ProviderName": "", "Access": 0, "Bus": "USB"},
                    {"DeviceID": "Z:", "VolumeName": "", "DriveType": 4, "FileSystem": "NTFS", "Size": 500000000000, "FreeSpace": 100000000000, "ProviderName": "\\\\nas\\share", "Access": 0, "Bus": None},
                    {"DeviceID": "D:", "VolumeName": "DVD", "DriveType": 5, "FileSystem": None, "Size": None, "FreeSpace": None, "ProviderName": "", "Access": 1, "Bus": None}])
disks = ci.parse_windows_disks(DISKS)
check("Windows disks JSON: four drives parsed", [d["letter"] for d in disks] == ["C", "E", "Z", "D"] and disks[1]["bus"] == "USB" and disks[3]["read_only"] is True, disks)
check("a single Windows drive (PowerShell prints an object, not a list) parses", len(ci.parse_windows_disks(json.dumps({"DeviceID": "C:", "DriveType": 3}))) == 1)
WMIC = "\r\r\nNode,Caption,FreePhysicalMemory,TotalVisibleMemorySize\r\r\nPC,Microsoft Windows 10 Pro,830000,16125592\r\r\n"
rows = ci.parse_wmic_csv(WMIC)
check("wmic CSV (\\r\\r\\n line ends) parsed", rows == [{"Caption": "Microsoft Windows 10 Pro", "FreePhysicalMemory": "830000", "TotalVisibleMemorySize": "16125592"}], rows)
host = {"disks": disks}
drv = ci.list_drives("windows", host=host, where={"data folder": "E:\\plasbench\\data"})
by = {d["windows"]: d for d in drv}
check("Windows drives: C internal, E removable (USB bus), Z network, D optical read-only",
      by["C:"]["type"] == "internal" and by["E:"]["type"] == "removable" and by["Z:"]["type"] == "network" and by["D:"]["type"] == "optical" and by["D:"]["read_only"] is True, by)
check("Windows: the drive holding the data folder is marked, with its space and a removable warning",
      by["E:"]["holds"] == ["data folder"] and by["E:"]["free"] == 1500000000000 and by["E:"]["used"] == 500000000000 and any("removable" in w for w in by["E:"]["warnings"]) and not by["C:"]["holds"], by["E:"])
check("Windows: a read-only drive carries the warning", any("read-only" in w for w in by["D:"]["warnings"]))

# Linux: /proc/mounts, df, lsblk
MOUNTS = ("/dev/sda2 / ext4 rw,relatime 0 0\nproc /proc proc rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sda1 /boot/efi vfat rw 0 0\n/dev/loop3 /snap/core20/1 squashfs ro 0 0\n"
          "/dev/sdb1 /media/ada/MY\\040USB exfat rw,nosuid 0 0\nnas:/export /mnt/nas nfs4 rw 0 0\n/dev/sdc1 /data ext4 ro,relatime 0 0\noverlay /var/lib/docker/overlay2/x overlay rw 0 0\n")
DF = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda2 500000000 100000000 400000000 21% /\n/dev/sdb1 31000000 1000000 30000000 4% /media/ada/MY USB\n"
      "nas:/export 1000000000 500000000 500000000 50% /mnt/nas\n/dev/sdc1 100000 50000 50000 50% /data\n")
LSBLK = json.dumps({"blockdevices": [{"name": "sda", "rm": False, "tran": "sata", "children": [{"name": "sda2", "mountpoint": "/", "label": None}]},
                                      {"name": "sdb", "rm": True, "hotplug": True, "tran": "usb", "children": [{"name": "sdb1", "mountpoint": "/media/ada/MY USB", "label": "MY USB"}]}]})
none_usage = lambda path: (_ for _ in ()).throw(OSError("no such file"))  # noqa: E731 - force the df fallback
drv = ci.list_drives("linux", mounts_text=MOUNTS, df_text=DF, lsblk_text=LSBLK, usage=none_usage, where={"data folder": "/media/ada/MY USB/plasbench/data", "workspace": "/home/ada/studies"})
by = {d["mount"]: d for d in drv}
check("Linux: pseudo filesystems, loop devices, the EFI partition and docker overlays are not listed", set(by) == {"/", "/media/ada/MY USB", "/mnt/nas", "/data"}, sorted(by))
check("Linux: usage falls back to df output (KiB blocks x1024)", by["/"]["total"] == 500000000 * 1024 and by["/"]["free"] == 400000000 * 1024 and by["/"]["used"] == 100000000 * 1024, by["/"])
check("Linux: lsblk makes the USB stick removable with its label; the data folder and workspace are marked on the right drives",
      by["/media/ada/MY USB"]["type"] == "removable" and by["/media/ada/MY USB"]["label"] == "MY USB" and by["/media/ada/MY USB"]["type_certain"]
      and by["/media/ada/MY USB"]["holds"] == ["data folder"] and by["/"]["holds"] == ["workspace"], by)
check("Linux: NFS is network, a ro mount is read-only (with a warning), ext4 root is internal",
      by["/mnt/nas"]["type"] == "network" and by["/data"]["read_only"] is True and any("read-only" in w for w in by["/data"]["warnings"]) and by["/"]["type"] == "internal")
drv = ci.list_drives("linux", mounts_text="/dev/sdb1 /media/ada/OneDrive-sync vfat rw 0 0\n", usage=none_usage)
check("Linux: a cloud-sync folder name is flagged as cloud-synced with the speed warning", drv[0]["type"] == "cloud-synced" and any("cloud" in w for w in drv[0]["warnings"]), drv)
drv = ci.list_drives("linux", mounts_text="/dev/sdb1 /media/ada/STICK vfat rw 0 0\n", usage=none_usage)
check("Linux: without lsblk a /media mount is a removable GUESS, marked uncertain", drv[0]["type"] == "removable" and not drv[0]["type_certain"], drv)

# WSL: Windows drives through drvfs/9p, and an unmounted E:
WSL_MOUNTS = ("/dev/sdd / ext4 rw 0 0\nC:\\134 /mnt/c 9p rw,noatime,aname=drvfs 0 0\nF:\\134 /mnt/f 9p rw,noatime,aname=drvfs 0 0\n"
              "none /mnt/wsl tmpfs rw 0 0\n/dev/sdd /mnt/wslg/distro ext4 ro 0 0\n/dev/sdd /mnt/wsl/docker-desktop-bind-mounts/Ubuntu/abc ext4 rw 0 0\n")
host = {"disks": ci.parse_windows_disks(json.dumps([{"DeviceID": "C:", "VolumeName": "OS", "DriveType": 3, "FileSystem": "NTFS", "Size": 1048035979264, "FreeSpace": 3705098240, "Bus": "NVMe", "Access": 0},
                                                    {"DeviceID": "F:", "VolumeName": "Research", "DriveType": 3, "FileSystem": "NTFS", "Size": 999291875328, "FreeSpace": 362318516224, "Bus": "NVMe", "Access": 0},
                                                    {"DeviceID": "E:", "VolumeName": "BACKUP", "DriveType": 3, "FileSystem": "exFAT", "Size": 2000000000000, "FreeSpace": 1500000000000, "Bus": "USB", "Access": 0}]))}
drv = ci.list_drives("linux", wsl=True, mounts_text=WSL_MOUNTS, host=host, usage=none_usage, where={"data folder": "/home/ada/data", "workspace": "/mnt/f/studies"})
by = {d["id"]: d for d in drv}
check("WSL: root, /mnt/c and /mnt/f listed; WSL's own /mnt/wsl, /mnt/wslg mounts and bind mounts are not", set(by) == {"/", "/mnt/c", "/mnt/f", "E:"}, sorted(by))
check("WSL: /mnt/c is Windows drive C: with its label and type from the host, and the slow-drive warning",
      by["/mnt/c"]["windows"] == "C:" and by["/mnt/c"]["label"] == "OS" and by["/mnt/c"]["type"] == "internal" and by["/mnt/c"]["type_certain"]
      and any("slower than Ubuntu's own disk" in w for w in by["/mnt/c"]["warnings"]), by["/mnt/c"])
check("WSL: the plugged-in but unmounted USB drive E: is listed as removable, not mounted, with the exact chooser hint",
      by["E:"]["type"] == "removable" and by["E:"]["mounted"] is False and by["E:"]["plugged_in"] and by["E:"]["hint"] == chooser.mount_help("E")
      and "sudo mount -t drvfs E: /mnt/e" in by["E:"]["hint"] and by["E:"]["free"] == 1500000000000, by["E:"])
check("WSL: the workspace on /mnt/f is marked on F:, the data folder on the WSL root", by["/mnt/f"]["holds"] == ["workspace"] and by["/"]["holds"] == ["data folder"], (by["/mnt/f"]["holds"], by["/"]["holds"]))
drv = ci.list_drives("linux", wsl=True, mounts_text=WSL_MOUNTS, host=None, usage=none_usage)
check("WSL without a host probe: Windows drives show an unknown type (not guessed internal)", {d["id"]: d for d in drv}["/mnt/c"]["type"] == "unknown")
src = open(os.path.join(ROOT, "plasbench", "computer_info.py"), encoding="utf-8").read()
check("nothing here mounts anything or uses sudo (the hint is only shown)", "sudo" not in src and "mount -t" not in src and "chooser.mount_help" in src)

# macOS drives
MAC_MOUNT = ("/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\ndevfs on /dev (devfs, local, nobrowse)\n/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled)\n"
             "/dev/disk3s6 on /System/Volumes/VM (apfs, local, noexec, journaled, nobrowse)\n/dev/disk5s1 on /Volumes/BACKUP (exfat, local, nodev, nosuid, noowners)\n//ada@nas/share on /Volumes/share (smbfs, nodev, nosuid, mounted by ada)\n")
MAC_DF = ("Filesystem 1024-blocks Used Available Capacity iused ifree %iused Mounted on\n/dev/disk3s5 488245288 300000000 150000000 67% 1000 1500000000 0% /System/Volumes/Data\n"
          "/dev/disk5s1 976490576 100000000 876490576 11% 0 0 100% /Volumes/BACKUP\n")
drv = ci.list_drives("macos", mac_mount_text=MAC_MOUNT, df_text=MAC_DF, usage=none_usage)
by = {d["mount"]: d for d in drv}
check("macOS: pseudo, VM and devfs mounts skipped; root, Data, BACKUP and the SMB share listed", set(by) == {"/", "/System/Volumes/Data", "/Volumes/BACKUP", "/Volumes/share"}, sorted(by))
check("macOS: /Volumes/BACKUP removable (guess), the SMB share network, root read-only; df extra columns parsed",
      by["/Volumes/BACKUP"]["type"] == "removable" and not by["/Volumes/BACKUP"]["type_certain"] and by["/Volumes/share"]["type"] == "network" and by["/"]["read_only"] is True
      and by["/Volumes/BACKUP"]["free"] == 876490576 * 1024 and by["/System/Volumes/Data"]["total"] == 488245288 * 1024, by)

# plugged and unplugged
first = [{"id": "/", "label": "root"}, {"id": "/media/a", "label": "USB A"}]
second = [{"id": "/", "label": "root"}, {"id": "/media/b", "label": "USB B"}]
check("first listing reports nothing as new", ci.diff_drives(None, first) == {"new": [], "removed": []})
d = ci.diff_drives(first, second)
check("a drive plugged in is new, one removed is reported by its label", d["new"] == ["/media/b"] and d["removed"] == [{"id": "/media/a", "label": "USB A"}], d)
check("an unchanged listing changes nothing", ci.diff_drives(second, second) == {"new": [], "removed": []})

# defensive
check("garbage in every drive source gives an empty or partial list, not an exception",
      isinstance(ci.list_drives("linux", mounts_text="\x00 garbage\n\n", df_text="???", lsblk_text="{bad", usage=none_usage), list)
      and ci.list_drives("macos", mac_mount_text="nonsense") == [] and ci.list_drives("windows", host={"disks": []}) == [])
check("unknown usage is None (shown as unknown)", ci.list_drives("linux", mounts_text="/dev/sda1 / ext4 rw 0 0\n", usage=none_usage)[0]["free"] is None)
ci._LAST.update(ids=None, drives=None)
r = ci.report({"data folder": ROOT}, remember=False)
check("report() on this machine has the card's parts and does not raise", all(k in r for k in ("environment", "host", "benchmark", "drives", "change")) and isinstance(r["drives"], list), list(r))

print("\nFAILED:" if fails else "\nAll computer-info checks passed.", *fails)
sys.exit(1 if fails else 0)
