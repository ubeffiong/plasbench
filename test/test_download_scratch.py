#!/usr/bin/env python3
"""Where a read download is written and checked (python/download_scratch.py, DOWNLOAD_TMP_DIR), and how the verified file reaches its final name.

A slow file system (9p/drvfs/NTFS/exFAT/FUSE/network, simulated with PLASBENCH_FORCE_FS_TYPE and with a mount table) gets a local scratch folder; a fast one does not; DOWNLOAD_TMP_DIR=data
turns the step off; a memory-backed folder is refused; too little free space is explained; the move works on one file system (a rename) and across file systems (copy, fsync, size check,
atomic rename); the final file is 0644 whatever it was; a failed move keeps the verified file. The whole path is also run through python/fetch_ena_reads.py against the fake ENA.
"""
import errno
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import download_scratch as ds  # noqa: E402
from ena_range_server import FakeENA  # noqa: E402

ok = True
MIB = 1 << 20


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        data = os.path.join(tmp, "data")
        os.makedirs(data)
        env = dict(os.environ)
        os.environ.pop("PLASBENCH_FORCE_FS_TYPE", None)
        mounts = [("/", "ext4"), ("/mnt/f", "9p")]
        r = ds.resolve("auto", "/mnt/f/study/data", "my study", 5 * MIB, home=home, mounts=mounts)
        check("a data folder on 9p gets a scratch folder under ~/.plasbench/downloads/<study>", r["scratch"] and r["dir"] == os.path.join(home, ".plasbench", "downloads", "my_study") and "9p" in r["reason"], r)
        for kind in ("drvfs", "ntfs", "exfat", "fuseblk", "cifs", "nfs", "fuse.sshfs"):
            check(f"{kind} counts as slow", ds.resolve("auto", "/m/x", "s", 0, home=home, mounts=[("/", "ext4"), ("/m", kind)])["scratch"])
        r = ds.resolve("auto", "/home/u/data", "s", 5 * MIB, home=home, mounts=mounts)
        check("a fast disk (ext4) needs no scratch step", not r["scratch"] and r["dir"] == "/home/u/data", r)
        r = ds.resolve("data", "/mnt/f/data", "s", 5 * MIB, home=home, mounts=mounts)
        check("DOWNLOAD_TMP_DIR=data disables the scratch step even on 9p", not r["scratch"] and "DOWNLOAD_TMP_DIR=data" in r["reason"], r)
        custom = os.path.join(tmp, "elsewhere")
        r = ds.resolve(custom, "/home/u/data", "s", 5 * MIB, home=home, mounts=[("/", "ext4")])
        check("DOWNLOAD_TMP_DIR=PATH uses that folder", r["scratch"] and r["dir"] == custom, r)
        r = ds.resolve("/dev/shm/dl", "/mnt/f/data", "s", 5 * MIB, home=home, mounts=[("/", "ext4"), ("/dev/shm", "tmpfs"), ("/mnt/f", "9p")])
        check("a memory-backed folder (tmpfs) is refused, with the reason, and the data folder is used", not r["scratch"] and "memory-backed" in r["reason"], r)
        with mock.patch.object(ds.work_dir, "free_bytes", return_value=2 * (1 << 30)):
            r = ds.resolve("auto", "/mnt/f/data", "s", 9_500_000_000, home=home, mounts=mounts)
        check("too little free space in the scratch folder is explained in GB, and the data folder is used", not r["scratch"] and "not enough free space" in r["reason"] and "GB free" in r["reason"] and "GB needed" in r["reason"], r)
        check("the margin is at least 1 GiB and 5% of a big file", ds.margin(1000) == 1 << 30 and ds.margin(100 << 30) == int((100 << 30) * 0.05))
        os.environ["PLASBENCH_FORCE_FS_TYPE"] = "9p"
        check("PLASBENCH_FORCE_FS_TYPE (the same override as WORK_DIR) simulates a slow file system", ds.resolve("auto", data, "s", 0, home=home)["scratch"])
        os.environ.pop("PLASBENCH_FORCE_FS_TYPE")

        # the move
        src = os.path.join(tmp, "scratch", "x.fastq.gz.part")
        os.makedirs(os.path.dirname(src))
        Path(src).write_bytes(b"abc" * 1000)
        Path(src + ".state").write_text("{}")
        os.chmod(src, 0o755)
        dst = os.path.join(data, "x.fastq.gz")
        how = ds.move_into_place(src, dst, 3000)
        check("a move on one file system is a rename and removes the state file", how == "renamed" and Path(dst).read_bytes() == b"abc" * 1000 and not os.path.exists(src) and not os.path.exists(src + ".state"), how)
        if os.name == "posix":
            check("the final file is 0644 (not executable, not read-only), whatever mode the part file had", stat.S_IMODE(os.stat(dst).st_mode) == 0o644, oct(os.stat(dst).st_mode))
        src = os.path.join(tmp, "scratch", "y.fastq.gz.part")
        Path(src).write_bytes(b"xyz" * 5000)
        real_replace = os.replace
        calls = []

        def cross_device(a, b):
            if not calls and str(a) == src:
                calls.append(1)
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(a, b)
        dst = os.path.join(data, "y.fastq.gz")
        with mock.patch.object(os, "replace", cross_device):
            how = ds.move_into_place(src, dst, 15000)
        check("across file systems: copy, fsync, size check, atomic rename, then the scratch copy is removed", how == "copied" and Path(dst).read_bytes() == b"xyz" * 5000 and not os.path.exists(src)
              and not os.path.exists(dst + ".moving"), how)
        src = os.path.join(tmp, "scratch", "z.fastq.gz.part")
        Path(src).write_bytes(b"q" * 4000)
        dst = os.path.join(data, "z.fastq.gz")
        calls.clear()

        def cross_then_full(a, b):
            if str(a) == src:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(a, b)
        with mock.patch.object(os, "replace", cross_then_full), mock.patch.object(ds.work_dir, "free_bytes", return_value=10):
            try:
                ds.move_into_place(src, dst, 4000)
                good = False
            except OSError as exc:
                good = "not enough free space" in str(exc) and "stays in" in str(exc)
        check("a full destination is explained, and the verified file stays in the scratch folder", good and os.path.exists(src) and not os.path.exists(dst))
        try:
            ds.move_into_place(src, dst, 9999)
            good = False
        except OSError as exc:
            good = "expected 9999" in str(exc)
        check("a size that is not the verified size is refused", good)

        # the whole path through fetch_ena_reads.py with a slow data folder
        s = FakeENA()
        s.add_run("SRRS", size=3 * MIB)
        s.start()
        data2 = os.path.join(tmp, "data2")
        env = dict(os.environ, ENA_PORTAL_URL=s.portal(), PLASBENCH_FORCE_FS_TYPE="9p", HOME=home, ENA_CHUNK_MIB="1", ENA_SEGMENT_MIN_BYTES=str(MIB), ENA_CHUNK_BACKOFF_SECONDS="0",
                   ENA_USE_ARIA2="0", DOWNLOAD_TMP_DIR="auto")
        r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", "SRRS", "--out-dir", data2, "--study", "demo"], env=env, capture_output=True, text=True)
        files_ok = all(os.path.getsize(os.path.join(data2, f"SRRS_{m}.fastq.gz")) == 3 * MIB for m in (1, 2)) if r.returncode == 0 else False
        scratch = os.path.join(home, ".plasbench", "downloads", "demo")
        check("on a (simulated) 9p data folder the run completes and says it used the scratch folder", files_ok and "downloading and checking in" in r.stderr and scratch in r.stderr, r.stderr[-500:])
        check("nothing is left in the scratch folder afterwards, and no .part file in the data folder", not [f for f in os.listdir(scratch)] and not [f for f in os.listdir(data2) if ".part" in f], os.listdir(scratch))
        if os.name == "posix":
            check("the final files are 0644", all(stat.S_IMODE(os.stat(os.path.join(data2, f"SRRS_{m}.fastq.gz")).st_mode) == 0o644 for m in (1, 2)))
        # a failed run leaves its chunks in the scratch folder, and the next run resumes from them
        s.faults.append({"kind": "reset", "start": 2 * MIB, "after": 0, "times": 10 ** 6, "path": "/f/SRRS_1.fastq.gz"})
        shutil_dir = os.path.join(tmp, "data3")
        env2 = dict(env, ENA_CHUNK_RETRIES="1", ENA_RETRY_DELAY_SECONDS="0")
        r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", "SRRS", "--out-dir", shutil_dir, "--study", "demo"], env=env2, capture_output=True, text=True)
        kept = sorted(os.listdir(scratch))
        check("a failed download keeps its partial file and state in the scratch folder and leaves nothing under the final name",
              r.returncode != 0 and any(f.endswith(".part.state") for f in kept) and not os.path.exists(os.path.join(shutil_dir, "SRRS_1.fastq.gz")), (r.returncode, kept))
        s.faults.clear()
        s.reset_stats()
        r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", "SRRS", "--out-dir", shutil_dir, "--study", "demo"], env=env, capture_output=True, text=True)
        check("the next run resumes: the chunks that were safe are not requested again", r.returncode == 0 and "were already on disk from an earlier attempt" in r.stderr and s.stats()["ranged_bytes"] < 6 * MIB, (r.stderr[-400:], s.stats()["ranged_bytes"]))
        s.stop()
    print("ALL DOWNLOAD SCRATCH TESTS PASSED" if ok else "SOME DOWNLOAD SCRATCH TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
