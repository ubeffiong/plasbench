#!/usr/bin/env python3
"""python/work_dir.py: when an assembly gets a fast scratch folder, how leftovers are cleaned, and the atomic move back of the results (no file system needed besides tmp)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import work_dir as wd  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


WSL_MOUNTS = "/dev/sdd / ext4 rw 0 0\nF:\\134 /mnt/f 9p rw,noatime,aname=drvfs 0 0\nC:\\134 /mnt/c 9p rw 0 0\ntmpfs /run tmpfs rw 0 0\n/dev/sde /data/fast ext4 rw 0 0\nrclone: /home/u/cloud fuse.rclone rw 0 0\n"
mounts = wd.mount_table(WSL_MOUNTS)
os.environ.pop("PLASBENCH_FORCE_FS_TYPE", None)

check("a folder on /mnt/f is on 9p (longest mount point wins over /)", wd.fs_type("/mnt/f/BioRun/Cohort", mounts) == "9p", wd.fs_type("/mnt/f/BioRun/Cohort", mounts))
check("a folder on Ubuntu's own disk is ext4", wd.fs_type("/home/effiong/PlasBench", mounts) == "ext4")
check("9p, drvfs, ntfs, exfat, cifs, nfs and fuse.* are slow; ext4, xfs, apfs, tmpfs are not", all(wd.is_slow(k) for k in ("9p", "drvfs", "ntfs3", "exfat", "cifs", "nfs4", "fuse.rclone", "fuseblk"))
      and not any(wd.is_slow(k) for k in ("ext4", "xfs", "apfs", "tmpfs", "btrfs", "")))

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    home = tmp / "home"
    home.mkdir()
    r = wd.resolve("auto", "/mnt/f/BioRun/Cohort", "negative-controls-v1", home, mounts=mounts)
    check("auto + slow data folder: a scratch folder under ~/.plasbench/scratch/<study>", r["scratch"] and r["dir"] == str(home / ".plasbench" / "scratch" / "negative-controls-v1"), r)
    check("the reason names the file system", "9p" in r["reason"], r["reason"])
    r = wd.resolve("auto", "/home/effiong/data", "s", home, mounts=mounts)
    check("auto + fast data folder: the data folder itself", not r["scratch"] and r["dir"] == "/home/effiong/data", r)
    r = wd.resolve("data", "/mnt/f/x", "s", home, mounts=mounts)
    check("WORK_DIR=data disables it even on a slow mount", not r["scratch"] and r["dir"] == "/mnt/f/x", r)
    r = wd.resolve(str(tmp / "mine"), "/mnt/f/x", "s", home, mounts=mounts)
    check("an explicit folder is used", r["scratch"] and r["dir"] == str(tmp / "mine"), r)
    r = wd.resolve("auto", "/mnt/f/x", "s", "/home/u", mounts=wd.mount_table("/dev/sdc /mnt/f 9p rw 0 0" + chr(10) + "tmpfs /home/u tmpfs rw,size=1048576k 0 0" + chr(10) + "overlay / overlay rw 0 0" + chr(10)))
    check("a tmpfs home (Docker mode) is never used as the scratch folder: the data folder is used and the reason says why", not r["scratch"] and "memory-backed" in r["reason"], r)
    r = wd.resolve("auto", "/mnt/f/x", "s", home, need_bytes=10 ** 18, mounts=mounts)
    check("not enough free space on the scratch file system: fall back to the data folder and say so", not r["scratch"] and "not enough free space" in r["reason"], r)
    r = wd.resolve("auto", "/mnt/f/x", "a b/c", home, mounts=mounts)
    check("the study name is made safe for a folder name", "/" not in Path(r["dir"]).name and " " not in Path(r["dir"]).name, r["dir"])

    # leftovers of a crashed run are removed, a live one's are kept
    root = tmp / "scratch"
    (root / "s1.99999999").mkdir(parents=True)
    (root / "s1.99999999" / "big").write_text("x")
    (root / ("s2.%d" % os.getpid())).mkdir()
    (root / "notes").mkdir()
    removed = wd.clean(root)
    check("a scratch folder whose pid is dead is removed", os.name != "posix" or removed == ["s1.99999999"] and not (root / "s1.99999999").exists() or os.name != "posix", removed)
    check("one owned by a live pid, and unrelated folders, are kept", (root / ("s2.%d" % os.getpid())).exists() and (root / "notes").exists())

    # the move back: results only, atomic, byte-identical
    src = tmp / "scratch_asm"
    (src / "K21").mkdir(parents=True)
    (src / "K21" / "big.bin").write_text("intermediate")
    (src / "corrected").mkdir()
    (src / "corrected" / "r.fastq").write_text("reads")
    (src / "misc").mkdir()
    (src / "contigs.fasta").write_bytes(b">c1\nACGT\n")
    (src / "assembly_graph_with_scaffolds.gfa").write_bytes(b"S\t1\tACGT\n")
    (src / "spades.log").write_text("log")
    dst = tmp / "data" / "s1" / "assembly"
    dst.parent.mkdir(parents=True)
    dst.mkdir()
    (dst / "stale.txt").write_text("an earlier attempt")
    files, total = wd.finish(src, dst)
    check("the result files arrive byte-identical", (dst / "contigs.fasta").read_bytes() == b">c1\nACGT\n" and (dst / "assembly_graph_with_scaffolds.gfa").read_bytes() == b"S\t1\tACGT\n", sorted(p.name for p in dst.iterdir()))
    check("intermediate folders (K21, corrected, misc) are not moved", not (dst / "K21").exists() and not (dst / "corrected").exists() and not (dst / "misc").exists())
    check("the destination is replaced as a whole (no stale file of an earlier attempt), no .partial left", not (dst / "stale.txt").exists() and not list(dst.parent.glob("*.partial*")))
    check("the source is untouched (the caller removes the scratch folder)", (src / "contigs.fasta").exists())
    check("the count is reported", files == 3 and total > 0, (files, total))
    check("finish on a missing source moves nothing", wd.finish(tmp / "nope", tmp / "d2") == (0, 0))

print("ALL WORK DIRECTORY TESTS PASSED" if ok else "WORK DIRECTORY TESTS FAILED")
sys.exit(0 if ok else 1)
