#!/usr/bin/env python3
"""Where a read download is written and checked: a fast local scratch folder when the data folder is on a slow mount, then moved into place.

A Windows drive seen from WSL (9p/drvfs), an NTFS/exFAT volume, a network share or a FUSE/cloud-synced folder is slow for the things a download does a lot of: many small random
writes (one per chunk) and reading the whole file back for the MD5 check (a 9.5 GB check took about five minutes from /mnt/f). So when the data folder is on such a mount the
`.part` files, their state files and the MD5 check live in a folder on a local disk, and only the verified file is moved to its final name.

  DOWNLOAD_TMP_DIR   auto (default)  a folder under ~/.plasbench/downloads/<study> when the data folder is on a slow mount, else the data folder itself
                     data            always the data folder (no scratch step)
                     PATH            that folder (never a memory-backed one: tmpfs/ramfs would take RAM from the assemblers and count against a container's limit)

  python3 -I python/download_scratch.py resolve --data-dir D --study NAME [--mode auto|data|PATH] [--need-bytes N]   -> prints  <dir>\\t<reason>\\t<fstype>\\t<scratch|data>

`resolve` falls back to the data folder, and says why, when the scratch folder is memory-backed or has too little free space (the file's size plus a margin).
`move_into_place` moves a VERIFIED file to its final name: a rename on the same file system; otherwise copy to a temporary name next to the destination, fsync, compare sizes,
then an atomic rename; the scratch copy is removed only afterwards. Final files get ordinary permissions (0644). Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import errno
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import work_dir  # noqa: E402

MARGIN_FLOOR = 1 << 30            # 1 GiB
MARGIN_FRACTION = 0.05
FINAL_MODE = 0o644


def margin(need_bytes):
    return max(MARGIN_FLOOR, int(need_bytes * MARGIN_FRACTION))


def resolve(mode, data_dir, study, need_bytes=0, home=None, mounts=None):
    """{'dir', 'reason', 'fs', 'slow', 'scratch'}: where the .part files and the MD5 check go."""
    home = Path(home or os.environ.get("HOME") or os.path.expanduser("~"))
    kind = work_dir.fs_type(data_dir, mounts)
    out = {"dir": str(data_dir), "fs": kind, "slow": work_dir.is_slow(kind), "scratch": False, "reason": ""}
    mode = (mode or "auto").strip() or "auto"
    if mode.lower() == "data":
        out["reason"] = "DOWNLOAD_TMP_DIR=data: downloading straight into the data folder"
        return out
    if mode.lower() == "auto":
        if not out["slow"]:
            out["reason"] = "the data folder is on %s, a fast disk" % (kind or "an unknown file system")
            return out
        target = home / ".plasbench" / "downloads" / (re.sub(r"[^A-Za-z0-9._-]", "_", study or "default") or "default")
        why = "the data folder is on %s (slow for random writes and for reading a big file back); downloading and checking in %s on the local disk, then moving the file" % (kind, target)
    else:
        target = Path(mode)
        why = "DOWNLOAD_TMP_DIR=%s" % mode
    target_fs = work_dir.fs_type(target, mounts).lower()
    if target_fs in ("tmpfs", "ramfs"):
        out["reason"] = "%s is on %s (memory-backed, it would take RAM and a container's memory limit): downloading into the data folder instead" % (target, target_fs)
        return out
    free = work_dir.free_bytes(target)
    needed = need_bytes + margin(need_bytes) if need_bytes else 0
    if free is not None and needed and free < needed:
        out["reason"] = ("not enough free space in %s: %.1f GB free, about %.1f GB needed (the files %.1f GB plus a margin): downloading into the data folder instead"
                         % (target, free / 1e9, needed / 1e9, need_bytes / 1e9))
        return out
    out.update(dir=str(target), scratch=True, reason=why)
    return out


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def move_into_place(src, dst, expected_bytes=None):
    """Move the verified file `src` to `dst`. Same file system: one rename. Otherwise copy + fsync + size check + atomic rename, and only then remove `src`.
    Returns 'renamed' or 'copied'. On any failure `src` is left where it is (and so is its state) and OSError is raised with a plain message."""
    src, dst = str(src), str(dst)
    size = os.path.getsize(src)
    if expected_bytes and size != int(expected_bytes):
        raise OSError("the verified file %s is %d bytes, expected %d" % (src, size, int(expected_bytes)))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    try:
        os.replace(src, dst)
        how = "renamed"
    except OSError as exc:
        if exc.errno != errno.EXDEV and not isinstance(exc, PermissionError) and exc.errno not in (errno.EPERM, errno.EACCES):
            raise
        free = work_dir.free_bytes(os.path.dirname(os.path.abspath(dst)))
        if free is not None and free < size + (64 << 20):
            raise OSError("not enough free space to move %s into %s: %.1f GB free, %.1f GB needed. The verified file stays in %s; free space and run the same command again, "
                          "it will only move it." % (os.path.basename(src), os.path.dirname(dst), free / 1e9, size / 1e9, os.path.dirname(src)))
        part = dst + ".moving"
        try:
            with open(src, "rb") as reader, open(part, "wb") as writer:
                shutil.copyfileobj(reader, writer, 8 << 20)
                writer.flush()
                os.fsync(writer.fileno())
            if os.path.getsize(part) != size:
                raise OSError("the copy of %s is %d bytes, expected %d (the destination may be full)" % (os.path.basename(src), os.path.getsize(part), size))
            os.replace(part, dst)
        except OSError:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        os.remove(src)
        how = "copied"
    _fsync_dir(os.path.dirname(os.path.abspath(dst)))
    try:
        os.chmod(dst, FINAL_MODE)
    except OSError:
        pass
    for extra in (src + ".state", src + ".aria2"):
        try:
            os.remove(extra)
        except OSError:
            pass
    return how


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--data-dir", required=True)
    r.add_argument("--study", default="")
    r.add_argument("--mode", default=os.environ.get("DOWNLOAD_TMP_DIR", "auto"))
    r.add_argument("--need-bytes", type=int, default=0)
    args = ap.parse_args(argv)
    res = resolve(args.mode, args.data_dir, args.study, args.need_bytes)
    print("\t".join((res["dir"], res["reason"], res["fs"] or "-", "scratch" if res["scratch"] else "data")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
