#!/usr/bin/env python3
"""A fast work folder for assemblies when the data folder is on a slow file system.

SPAdes writes tens of thousands of small files. On a Windows drive seen from WSL (9p/drvfs), on an NTFS/exFAT volume, a network share or a cloud-synced folder
every small file costs milliseconds: measured on the machine this was written on, 2000 tiny files took 0.06 s on Ubuntu's own disk and 16.4 s on /mnt/f (9p), about 280 times
longer to create. So when the data folder is on such a mount the assembler works in a folder on a fast local disk and only the finished results are moved back.

  python3 -I python/work_dir.py resolve --data-dir D --study NAME [--mode auto|data|PATH] [--need-gb N]   -> prints  <dir>\\t<reason>\\t<fstype>
  python3 -I python/work_dir.py clean   --root DIR                                           remove scratch folders of runs that are gone (their pid is dead)
  python3 -I python/work_dir.py finish  --src DIR --dst DIR                                  move the finished results back, atomically

WORK_DIR (config/config.sh): `auto` (default) = a scratch folder under ~/.plasbench/scratch/<study> when the data folder is on a slow mount, else the data folder itself;
`data` = always the data folder (the old behaviour); any other value = that folder. Inputs are never moved or deleted; only the scratch folder is removed, after the
results are safely in the isolate's folder. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

SLOW_TYPES = {"9p", "v9fs", "drvfs", "ntfs", "ntfs3", "fuseblk", "vfat", "msdos", "exfat", "cifs", "smb3", "smbfs", "nfs", "nfs4", "virtiofs", "vboxsf", "afpfs",
              "fuse", "sshfs", "rclone", "osxfuse", "macfuse", "9pfs"}
# Directories SPAdes fills with intermediate files: not results, not moved back.
SKIP_DIRS = {"corrected", "misc", "tmp", "split_input", "mismatch_corrector", "dataset.info"}
SKIP_PREFIXES = ("K",)          # K21, K33, ... K127


def mount_table(text=None):
    """[(mountpoint, fstype)] from /proc/self/mounts (octal escapes in paths decoded); [] when it cannot be read."""
    if text is None:
        try:
            text = Path("/proc/self/mounts").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[1])
            rows.append((point, parts[2]))
    return rows


def fs_type(path, mounts=None):
    """The file system type holding `path` (longest matching mount point), '' when unknown. PLASBENCH_FORCE_FS_TYPE overrides it (tests)."""
    forced = os.environ.get("PLASBENCH_FORCE_FS_TYPE")
    if forced:
        return forced
    rows = mount_table() if mounts is None else mounts
    real = os.path.realpath(str(path)) if os.name == "posix" else str(path).replace(chr(92), "/")
    best = ("", "")
    for point, kind in rows:
        prefix = point.rstrip("/") + "/"
        if (real == point or real.startswith(prefix) or point == "/") and len(point) >= len(best[0]):
            best = (point, kind)
    return best[1]


def is_slow(kind):
    kind = (kind or "").lower()
    return kind in SLOW_TYPES or kind.startswith("fuse.")


def free_bytes(path):
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(str(probe)).free
    except OSError:
        return None


def resolve(mode, data_dir, study, home=None, need_bytes=0, mounts=None):
    """{'dir', 'reason', 'fs', 'slow', 'scratch'}: where assemblies run. `dir` is the data folder itself unless a scratch folder is chosen."""
    home = Path(home or os.environ.get("HOME") or os.path.expanduser("~"))
    kind = fs_type(data_dir, mounts)
    out = {"dir": str(data_dir), "fs": kind, "slow": is_slow(kind), "scratch": False, "reason": ""}
    mode = (mode or "auto").strip()
    if mode.lower() == "data":
        out["reason"] = "WORK_DIR=data: working in the data folder"
        return out
    if mode.lower() == "auto":
        if not out["slow"]:
            out["reason"] = "the data folder is on %s, a fast disk" % (kind or "an unknown file system")
            return out
        target = home / ".plasbench" / "scratch" / (re.sub(r"[^A-Za-z0-9._-]", "_", study or "default") or "default")
        why = "the data folder is on %s (slow for many small files); using a scratch folder on the local disk" % kind
    else:
        target = Path(mode)
        why = "WORK_DIR=%s" % mode
    free = free_bytes(target)
    if free is not None and need_bytes and free < need_bytes:
        out["reason"] = "not enough free space in %s (%.1f GB free, about %.1f GB needed): working in the data folder instead" % (target, free / 1e9, need_bytes / 1e9)
        return out
    out.update(dir=str(target), scratch=True, reason=why)
    return out


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, OverflowError, OSError):
        return True
    return True


def clean(root):
    """Remove scratch folders named '<sample>.<pid>' whose process is gone (left by a crash or a kill). Returns the removed names."""
    removed = []
    root = Path(root)
    if not root.is_dir():
        return removed
    for child in sorted(root.iterdir()):
        m = re.match(r"^.+\.(\d+)$", child.name)
        if child.is_dir() and m and not pid_alive(m.group(1)):
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child.name)
    return removed


def _is_result(path):
    name = path.name
    if path.is_dir():
        return not (name in SKIP_DIRS or (name.startswith(SKIP_PREFIXES) and name[1:].isdigit()))
    return True


def finish(src, dst):
    """Move the results of an assembly from `src` (scratch) to `dst` (the isolate's assembly folder), atomically: everything is copied into a sibling folder of `dst`
    first (same file system as `dst`), checked by size, and renamed into place, so `dst` is either absent or complete. Returns (files, bytes)."""
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        return 0, 0
    part = dst.parent / (dst.name + ".partial.%d" % os.getpid())
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    files = total = 0
    for item in sorted(src.iterdir()):
        if not _is_result(item):
            continue
        target = part / item.name
        if item.is_dir():
            shutil.copytree(item, target)
            for f in target.rglob("*"):
                if f.is_file():
                    files += 1
                    total += f.stat().st_size
        else:
            shutil.copyfile(item, target)
            if target.stat().st_size != item.stat().st_size:
                shutil.rmtree(part, ignore_errors=True)
                raise OSError("copy of %s is incomplete (the destination may be full)" % item.name)
            files += 1
            total += item.stat().st_size
    shutil.rmtree(dst, ignore_errors=True)
    os.replace(part, dst)
    return files, total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--data-dir", required=True)
    r.add_argument("--study", default="")
    r.add_argument("--mode", default=os.environ.get("WORK_DIR", "auto"))
    r.add_argument("--need-gb", type=float, default=0)
    r.add_argument("--home")
    c = sub.add_parser("clean")
    c.add_argument("--root", required=True)
    f = sub.add_parser("finish")
    f.add_argument("--src", required=True)
    f.add_argument("--dst", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "resolve":
        res = resolve(args.mode, args.data_dir, args.study, args.home, int(args.need_gb * 1e9))
        print("\t".join((res["dir"], res["reason"], res["fs"] or "-", "scratch" if res["scratch"] else "data")))
        return 0
    if args.cmd == "clean":
        for name in clean(args.root):
            print(name)
        return 0
    try:
        files, total = finish(args.src, args.dst)
    except OSError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    print("%d file(s), %.1f MB" % (files, total / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
