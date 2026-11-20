#!/usr/bin/env python3
"""python/preflight_resources.py and computer_info.wsl_vdisk: disk (working set vs whole cohort), the Windows drive under Ubuntu's disk, memory, threads and folders, with
injected machine values (no real disk or WSL needed). The recorded outputs of the Windows probes are written from knowledge of their formats, not captured on a real machine."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import preflight_resources as pr  # noqa: E402
from plasbench import computer_info as ci  # noqa: E402

FAILED = []
GB = pr.GB


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def ctx(tmp, **kw):
    base = {"stage": 3, "results_dir": str(tmp / "results"), "data_dir": str(tmp / "data"), "tmp_dir": str(tmp / "tmp"),
            "sheet_rows": [("s1", "SRR1"), ("s2", "SRR2")], "threads": 4, "memory_gb": 4, "cap_threads": True, "skip_disk": False}
    base.update(kw)
    return base


def probes(free_gb=500, avail_gb=16, cpus=8, wsl=False, writable=True, **extra):
    env = {"memory_available": int(avail_gb * 2 ** 30), "usable_cpus": cpus, "logical": cpus, "limits": []}
    p = {"free": lambda path: int(free_gb * GB), "env": env, "wsl": wsl, "device": lambda path: 1, "lookup": False, "write_cache": False, "lock": {}, "sizes": [],
         "writable": (lambda path: (True, "")) if writable else (lambda path: (False, "Read-only file system"))}
    p.update(extra)
    return p


def texts(result, level=None):
    return " | ".join(t for lv, t in result["items"] if level is None or lv == level)


def vd(free_gb, letter="C", error=""):
    return {"distro": "Ubuntu", "base": letter + ":\\Users\\u\\AppData\\Local\\wsl\\{G}", "vhdx": letter + ":\\Users\\u\\AppData\\Local\\wsl\\{G}\\ext4.vhdx", "letter": letter,
            "free": None if free_gb is None else int(free_gb * GB), "total": 500 * GB, "how": "Win32_LogicalDisk FreeSpace in bytes", "error": error,
            "command": f'powershell.exe -NoProfile -Command "(Get-PSDrive {letter}).Free/1GB"', "others": ["docker-desktop"]}


MOUNTS_E = "E: /mnt/e 9p rw,noatime 0 0\n/dev/sdc / ext4 rw 0 0\n"
MOUNTS_NONE = "/dev/sdc / ext4 rw 0 0\n"


def main():
    tmp = Path(tempfile.mkdtemp())
    for d in ("data/s1", "data/s2", "results", "tmp"):
        (tmp / d).mkdir(parents=True)
    # reads on disk: 0.5 GB compressed per isolate
    for s, sra in (("s1", "SRR1"), ("s2", "SRR2")):
        for suffix in ("_1.fastq.gz", "_2.fastq.gz"):
            with open(tmp / "data" / s / f"{sra}{suffix}", "wb") as handle:
                handle.truncate(250_000_000)
    rows2 = [("s1", "SRR1"), ("s2", "SRR2")]
    other = int(pr.OTHER_GB * GB)

    # ---- the estimate ----------------------------------------------------------------------------------------------------------------
    e = pr.pending_work(rows2, tmp / "data", 3, lock={}, sizes=[])
    check("measured: peak per isolate = 9x the reads on disk + 0.33 GB; whole run = 5x + 0.33 GB (reads + trimmed + assembler folder)",
          e["todo"] == 2 and e["whole"] == 2 * (500_000_000 * 5 + other) and e["confidence"] == "measured" and "reads on disk" in e["basis"], e)
    check("working set = the peak of the isolates in flight, minus the reads already on disk", e["working"] == 500_000_000 * 9 + other - 500_000_000, e)
    e2 = pr.pending_work(rows2, tmp / "data", 3, in_flight=2, lock={}, sizes=[])
    check("two isolates in flight: the working set doubles", e2["working"] == 2 * e["working"], (e2["working"], e["working"]))
    (tmp / "data" / "s2" / "contigs.fasta").write_text(">c\nACGT\n", encoding="utf-8")
    e3 = pr.pending_work(rows2, tmp / "data", 3, lock={}, sizes=[])
    check("an isolate that already has contigs is not counted for stage 3", e3["todo"] == 1 and e3["whole"] == e["whole"] // 2, e3)
    (tmp / "data" / "s2" / "contigs.fasta").unlink()
    t = pr.pending_work([("a", "X"), ("b", "Y")], tmp / "data", 0, lock={}, sizes=[])
    check("nothing known: the typical isolate is used, called NOT measured, confidence typical",
          t["confidence"] == "typical" and "NOT measured" in t["basis"] and t["peak_mean"] == int(pr.FALLBACK_GB_PER_ISOLATE * GB), t)
    s = pr.pending_work([("a", "X"), ("b", "Y"), ("c", "Z")], tmp / "data", 0, lock={}, sizes=[200_000_000, 400_000_000])
    check("sampled ENA sizes: their mean (0.30 GB) applies to the isolates with nothing measured, and the basis says so",
          s["confidence"] == "sampled" and "sampled" in s["basis"] and "2 sampled" in s["basis"] and s["counts"]["sampled"] == 3 and s["peak_mean"] == pr.isolate_bytes(300_000_000)[0], s)
    k = pr.pending_work([("a", "X"), ("b", "Y")], tmp / "data", 0, lock={"a": 1_000_000_000}, sizes=[])
    check("the verification lock's base count gives the reads size (0.615 bytes per base); the other isolate is typical",
          k["counts"]["lock"] == 1 and k["counts"]["typical"] == 1 and "lock" in k["basis"], k)
    cache = tmp / "cachestudy"
    cache.mkdir()
    (cache / ".ena_size_cache.json").write_text(json.dumps({"X": 300_000_000, "Y": 500_000_000}), encoding="utf-8")
    check("sampled sizes come from the cache without a network call (lookup off)", sorted(pr.sampled_read_sizes(["X", "Y", "Z"], cache, False)) == [300_000_000, 500_000_000])
    big = pr.pending_work([(f"i{n}", f"R{n}") for n in range(7227)], tmp / "data", 0, lock={}, sizes=[])
    check("7,227 isolates without a measurement: ~1.83 GB kept each (not the 3 GB peak), a low-confidence estimate",
          big["todo"] == 7227 and abs(big["kept_mean"] / GB - 1.83) < 0.01 and big["confidence"] == "typical", big)

    # ---- policy: only what cannot start is a block ---------------------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp), probes(free_gb=500))
    check("plenty of room: ok, nothing to report", r["level"] == "ok" and not r["items"] and r["threads"] is None, r)
    check("the rendered block starts with 'Resources check: ok' and prints the rules applied", pr.render(r, 3)[0].startswith("Resources check: ok")
          and "memory: 4 GB assembler budget <= 16.0 GB available: ok" in pr.render(r, 3)[0] and "threads: 4 <= 8 usable CPU(s): no cap" in pr.render(r, 3)[0], pr.render(r, 3))
    r = pr.run_checks(ctx(tmp), probes(free_gb=9.5))
    check("working set fits (4.3 GB) but the whole run does not (5.7 GB + 5 GB reserve): a WARNING, the run can start", r["level"] == "warn" and "this run will fill" in texts(r, "warn")
          and "after about" in texts(r, "warn") and "--max-isolates" in " ".join(r["detail"]) and not texts(r, "fail"), r)
    check("the warning block says the run can start, with Measured / Needed / Next lines", pr.render(r, 3)[0].startswith("Resources check: 1 warning(s), the run can start")
          and any(x.strip().startswith("Measured:") for x in pr.render(r, 3)) and any(x.strip().startswith("Needed:") for x in pr.render(r, 3))
          and any(x.strip().startswith("Next:") for x in pr.render(r, 3)), pr.render(r, 3))
    r = pr.run_checks(ctx(tmp), probes(free_gb=3))
    check("the working set (4.3 GB) does not fit: 'cannot start', a block with the figures and the override", r["level"] == "fail" and "cannot start: 3.0 GB is free" in texts(r, "fail")
          and "4.3 GB at once" in texts(r, "fail") and "PLASBENCH_SKIP_DISK_CHECK=1" in " ".join(r["detail"]) and r["causes"] == ["disk space"], r)
    check("a block names its cause in the headline, never 'NOT ENOUGH RESOURCES' for memory", pr.render(r, 3)[0].startswith("Resources check: the run cannot start because of disk space"), pr.render(r, 3)[0])
    r = pr.run_checks(ctx(tmp, skip_disk=True), probes(free_gb=0))
    check("PLASBENCH_SKIP_DISK_CHECK skips the disk figures", r["level"] == "ok", r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=0.1))
    check("under the hard floor it fails whatever the estimate", r["level"] == "fail")
    r = pr.run_checks(ctx(tmp, reserve_gb=0), probes(free_gb=7))
    check("PLASBENCH_DISK_RESERVE_GB=0 removes the reserve from the whole-run warning (5.7 GB fits in 7)", r["level"] == "ok", r)
    r = pr.run_checks(ctx(tmp, reserve_gb=5), probes(free_gb=7))
    check("the default 5 GB reserve makes the same 7 GB a warning", r["level"] == "warn", r)

    # ---- the reported run: 7,227 isolates, the drive is big, Ubuntu's disk was nearly empty --------------------------------------------------
    rows_big = [(f"i{n}", f"R{n}") for n in range(7227)]
    c0 = ctx(tmp, stage=0, sheet_rows=rows_big, results_dir="/mnt/e/Plasbench/results", data_dir="/mnt/e/Plasbench/results", tmp_dir="/mnt/e/Plasbench/tmp", memory_gb=5, threads=20, write_cache=False)
    p0 = probes(free_gb=1519.6, avail_gb=7.0, cpus=20, wsl=True, mounts_text=MOUNTS_E, vdisk=lambda: vd(35.9), writable=True)
    p0["writable"] = lambda path: (True, "")
    r = pr.run_checks(c0, p0)
    out = "\n".join(pr.render(r, 0))
    check("reported run, C: with 35.9 GB: NOT a block; a warning that the whole cohort will not fit, with a --max-isolates", r["level"] == "warn" and "FAIL" not in out
          and "this run will fill Windows drive E:" in out and "add --max-isolates 500" in out and "7227" in out, out)
    check("the block shows what was measured (drive, bytes, how) and the vdisk evidence (distro, file, volume, bytes)", "1519600000000 bytes" in out and "distro 'Ubuntu'" in out
          and "ext4.vhdx" in out and "volume C:" in out and "35900000000 bytes" in out, out)
    check("memory 7.0 GB against a 5 GB budget and 20 of 20 CPUs: ok, the rules are printed", "memory: 5 GB assembler budget <= 7.0 GB available: ok" in out and "threads: 20 <= 20 usable CPU(s): no cap" in out, out)
    p1 = dict(p0, vdisk=lambda: vd(0.3))
    r = pr.run_checks(c0, p1)
    out = "\n".join(pr.render(r, 0))
    check("the same run with 0.3 GB on C: is a block (below the 2 GB floor), naming C:, the evidence and the one command to check it",
          r["level"] == "fail" and "Windows drive C: holding Ubuntu's virtual disk has only 0.3 GB" in texts(r, "fail") and "(Get-PSDrive C).Free/1GB" in out
          and "the run cannot start because of disk space" in out, out)

    # ---- severity by where the folders are ------------------------------------------------------------------------------------------------
    cw = ctx(tmp, results_dir="/mnt/e/s", data_dir="/mnt/e/s/data", tmp_dir="/mnt/e/tmp")
    r = pr.run_checks(cw, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_E, vdisk=lambda: vd(35.9)))
    check("study, data, temp on a mounted Windows drive and 35.9 GB on C: -> ok apart from the /mnt speed note", r["level"] == "warn" and "much slower" in texts(r, "warn") and not texts(r, "fail") and "virtual disk" not in texts(r), r)
    r = pr.run_checks(cw, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_E, vdisk=lambda: vd(5)))
    check("... 5 GB on C: only warns (small writes go to Ubuntu's disk), the run can start", "virtual disk" in texts(r, "warn") and not texts(r, "fail") and "keep at least 10 GB" in texts(r, "warn"), r)
    r = pr.run_checks(cw, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_E, vdisk=lambda: vd(1.5)))
    check("... 1.5 GB on C: fails at the 2 GB floor", "only 1.5 GB free (below the 2.0 GB floor)" in texts(r, "fail"), r)
    r = pr.run_checks(dict(cw, vdisk_min_gb=1), probes(free_gb=500, wsl=True, mounts_text=MOUNTS_E, vdisk=lambda: vd(1.5)))
    check("PLASBENCH_VDISK_MIN_GB lowers the floor", not texts(r, "fail"), r)
    ce = ctx(tmp, results_dir="/home/u/study", data_dir="/home/u/study/data", tmp_dir="/tmp")
    r = pr.run_checks(ce, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(35.9)))
    check("study and data on Ubuntu's own disk: df shows 500 GB but the Windows drive has 35.9, which is the limit; the whole run (5.7 GB) fits: ok", r["level"] == "ok", r)
    r = pr.run_checks(dict(ce, sheet_rows=rows_big), probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(35.9)))
    check("... with 7,227 isolates it warns and says the limit is the Windows drive C: under Ubuntu's disk (df inside shows 500.0)", "limited by Windows drive C:" in texts(r, "warn")
          and "df inside Ubuntu shows 500.0 GB" in texts(r, "warn") and "Ubuntu's own disk" in texts(r, "warn"), r)
    r = pr.run_checks(ce, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(3)))
    check("... and with only 3 GB on C: a block (the first isolate needs 4.3 GB at once)", r["level"] == "fail" and "cannot start" in texts(r, "fail"), r)
    cu = ctx(tmp, results_dir="/mnt/e/s", data_dir="/mnt/e/s/data", tmp_dir="/tmp")
    r = pr.run_checks(cu, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(35.9)))
    check("/mnt/e that is NOT a mount: 'E: is not mounted: /mnt/e is just a folder on Ubuntu's disk' with the mount command, never run for the user",
          "E: is not mounted: /mnt/e is just a folder on Ubuntu's disk" in texts(r, "warn") and "sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e" in texts(r, "warn")
          and "Windows drive E:" not in texts(r), r)
    r = pr.run_checks(dict(cu, sheet_rows=rows_big), probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(35.9)))
    check("... and it is measured as Ubuntu's disk, not called a Windows drive", "a folder on Ubuntu's own disk (/mnt/e is NOT a mounted drive)" in " ".join(r["detail"] + [texts(r)]), r)
    r = pr.run_checks(ce, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(None, error="the WSL registry list (HKCU Lxss) could not be read")))
    check("an unmeasurable vdisk is reported as unknown with the check command, never a number; only df is used",
          "could not measure the Windows drive" in texts(r) and r["level"] == "ok", r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=500, wsl=False, vdisk=lambda: vd(0)))
    check("not WSL: the Windows-drive probe does not run", r["level"] == "ok", r)

    # ---- the probe: recorded outputs ----------------------------------------------------------------------------------------------------
    lxss = json.dumps([{"DistributionName": "docker-desktop", "BasePath": "\\\\?\\D:\\docker\\wsl\\main"},
                       {"DistributionName": "Ubuntu", "BasePath": "\\\\?\\C:\\Users\\u\\AppData\\Local\\wsl\\{11111111-2222}"}])
    disks = json.dumps([{"DeviceID": "C:", "VolumeName": "OS", "DriveType": 3, "FileSystem": "NTFS", "Size": "999000000000", "FreeSpace": "35900000000"},
                        {"DeviceID": "D:", "VolumeName": "Data", "DriveType": 3, "FileSystem": "NTFS", "Size": "999000000000", "FreeSpace": "811000000000"}])

    def fake_run(lxss_out=lxss, disks_out=disks):
        def run(argv, timeout=8):
            return lxss_out if "Lxss" in argv[-1] else disks_out
        return run
    which = lambda name: "powershell.exe" if name.startswith("powershell") else None  # noqa: E731
    v = ci.wsl_vdisk(run=fake_run(), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("the probe picks the running distribution (Ubuntu), not docker-desktop, and reads THAT drive's free BYTES",
          v["letter"] == "C" and v["free"] == 35_900_000_000 and v["vhdx"].endswith("{11111111-2222}\\ext4.vhdx") and v["others"] == ["docker-desktop"] and not v["error"], v)
    v = ci.wsl_vdisk(run=fake_run(), which=which, env={"WSL_DISTRO_NAME": "docker-desktop"})
    check("if the process really runs in docker-desktop, that distribution's drive (D:) is measured", v["letter"] == "D" and v["free"] == 811_000_000_000, v)
    v = ci.wsl_vdisk(run=fake_run(), which=which, env={"WSL_DISTRO_NAME": "Debian"})
    check("a distribution Windows does not list: unknown, with the reason, no other distribution substituted", v["free"] is None and "no registry entry is named 'Debian'" in v["error"] and v["letter"] == "", v)
    v = ci.wsl_vdisk(run=fake_run(), which=which, env={})
    check("WSL_DISTRO_NAME unset: unknown, never a guess", v["free"] is None and "WSL_DISTRO_NAME is not set" in v["error"], v)
    v = ci.wsl_vdisk(run=lambda argv, timeout=8: None, which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("a failed PowerShell call: unknown", v["free"] is None and v["error"], v)
    v = ci.wsl_vdisk(run=fake_run(lxss_out="not json at all"), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("unparseable registry output: unknown", v["free"] is None and v["error"], v)
    v = ci.wsl_vdisk(run=fake_run(), which=lambda name: None, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("no powershell.exe: unknown", v["free"] is None and "powershell.exe is not reachable" in v["error"], v)
    unc = json.dumps({"DistributionName": "Ubuntu", "BasePath": "\\\\server\\share\\wsl"})
    v = ci.wsl_vdisk(run=fake_run(lxss_out=unc), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("a disk folder that is not on a drive letter: unknown", v["free"] is None and "not on a Windows drive letter" in v["error"], v)
    bad = json.dumps([{"DeviceID": "C:", "Size": "100", "FreeSpace": "900"}])
    v = ci.wsl_vdisk(run=fake_run(disks_out=bad), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("free larger than the volume (a wrong unit): unknown, not a number", v["free"] is None and "could not be read reliably" in v["error"], v)
    v = ci.wsl_vdisk(run=fake_run(disks_out=json.dumps([{"DeviceID": "D:", "Size": "1", "FreeSpace": "1"}])), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    check("Windows lists no drive C: -> unknown, says so", v["free"] is None and "listed no drive C:" in v["error"], v)
    v = ci.wsl_vdisk(run=fake_run(), which=which, env={"WSL_DISTRO_NAME": "Ubuntu"})
    ev = pr.vdisk_evidence(v)
    check("the evidence line names the distribution, the file, the volume and the bytes", "distro 'Ubuntu'" in ev and "ext4.vhdx" in ev and "volume C:" in ev and "35900000000 bytes" in ev, ev)
    check("the unknown line says UNKNOWN", "UNKNOWN" in pr.vdisk_evidence(dict(v, free=None, error="x")))
    check("classify_path: a drvfs/9p mount is a Windows drive, a plain /mnt folder is 'unmounted', ext4 is 'vdisk', outside WSL it is native",
          ci.classify_path("/mnt/e/study", True, MOUNTS_E) == ("windows", "E") and ci.classify_path("/mnt/e/study", True, MOUNTS_NONE) == ("unmounted", "E")
          and ci.classify_path("/home/u/x", True, MOUNTS_NONE) == ("vdisk", "") and ci.classify_path("/mnt/e/x", False, MOUNTS_E) == ("native", ""),
          (ci.classify_path("/mnt/e/study", True, MOUNTS_E), ci.classify_path("/mnt/e/study", True, MOUNTS_NONE)))
    check("suggest_max_isolates rounds down to 1, 2, 5, 10, 20, 50, ...", [pr.suggest_max_isolates(k) for k in (0, 1, 3, 7, 12, 99, 499, 827, 1500)] == [1, 1, 2, 5, 10, 50, 200, 500, 1000],
          [pr.suggest_max_isolates(k) for k in (0, 1, 3, 7, 12, 99, 499, 827, 1500)])

    # ---- the rolling guard ----------------------------------------------------------------------------------------------------------------
    gctx = {"stage": 3, "sample": "s1", "sra": "SRR1", "results_dir": str(tmp / "results"), "data_dir": str(tmp / "data"), "tmp_dir": str(tmp / "tmp"), "in_flight": 1, "reserve_gb": 5}
    ok, lines = pr.guard(gctx, probes(free_gb=500))
    check("guard: room for the isolate and the reserve: go on, silently", ok and not lines)
    ok, lines = pr.guard(gctx, probes(free_gb=7))
    check("guard: 7 GB free, 4.3 GB needed + 5 GB reserve: stop, with the isolate, the figures and the resume advice", not ok and "Stopping before s1" in lines[0] and "only 7.0 GB" in lines[0]
          and "plus a 5.0 GB reserve" in lines[0] and "finished are kept" in lines[1] or "already finished are kept" in lines[1] and "run the same command again" in lines[1], lines)
    ok, lines = pr.guard(dict(gctx, reserve_gb=0), probes(free_gb=7))
    check("guard: with no reserve the same space is enough", ok, lines)
    ok, lines = pr.guard(dict(gctx, skip_disk=True), probes(free_gb=0))
    check("guard: PLASBENCH_SKIP_DISK_CHECK skips it", ok)
    (tmp / "data" / "s1" / "contigs.fasta").write_text(">c\nA\n", encoding="utf-8")
    ok, lines = pr.guard(gctx, probes(free_gb=0))
    check("guard: an isolate that is already assembled needs nothing", ok)
    (tmp / "data" / "s1" / "contigs.fasta").unlink()
    ok, lines = pr.guard(dict(gctx, stage=1, sample="s9", sra="R9"), probes(free_gb=7))
    check("guard stage 1: an isolate with nothing on disk is estimated from the cache or the typical figure, and stops when it will not fit", not ok, lines)
    ok, lines = pr.guard(dict(gctx, in_flight=3), probes(free_gb=12))
    check("guard: isolates in flight multiply the need (3 x 4.3 GB + 5 > 12)", not ok, lines)
    ok, lines = pr.guard(gctx, probes(free_gb=500, wsl=True, mounts_text=MOUNTS_NONE, vdisk_free=lambda: 3 * GB))
    check("guard under WSL on Ubuntu's disk: the Windows drive's 3 GB is the limit even when df shows 500", not ok and "Ubuntu's own disk" in lines[0], lines)
    ok, lines = pr.guard(dict(gctx, data_dir="/mnt/e/d", results_dir="/mnt/e/r", tmp_dir="/mnt/e/t"), probes(free_gb=500, wsl=True, mounts_text=MOUNTS_E, vdisk_free=lambda: 3 * GB))
    check("guard with the data on a mounted Windows drive: the small vdisk figure does not stop an isolate", ok, lines)

    # ---- memory and threads (the wording is the rule that was applied) -------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp, memory_gb=5), probes(avail_gb=3))
    check("an assembler budget above the available memory is a warning that says so", "memory: the assembler budget (5 GB, MEMORY_GB) is above the 3.0 GB available" in texts(r, "warn")
          and "memory: 5 GB budget > 3.0 GB available: warn" in " ".join(r["rules"]), r)
    r = pr.run_checks(ctx(tmp, memory_gb=5, threads=20), probes(avail_gb=7, cpus=20))
    check("7 GB available and a 5 GB budget with 20 threads on 20 CPUs: no memory finding, the head says ok", r["level"] == "ok" and "NOT ENOUGH" not in pr.render(r, 3)[0], pr.render(r, 3))
    r = pr.run_checks(ctx(tmp, threads=20), probes(cpus=12))
    check("20 threads on 12 usable CPUs are capped to 12 and the decision is printed", r["threads"] == 12 and "using 12 threads" in texts(r, "warn") and "capped to 12" in " ".join(r["rules"]), r)
    r = pr.run_checks(ctx(tmp, threads=20, cap_threads=False), probes(cpus=12))
    check("CAP_THREADS_TO_CPUS=0 keeps the number and says so", r["threads"] is None and "keeps it as set" in texts(r, "warn"), r)
    env = {"memory_available": 16 * 2 ** 30, "usable_cpus": 6, "logical": 20, "limits": [{"what": "cpu", "text": "CPU time is limited to 6 CPUs by a cgroup v2 limit"}]}
    r = pr.run_checks(ctx(tmp, threads=20), probes(env=env))
    check("a cgroup CPU limit is the reason given for the cap", r["threads"] == 6 and "cgroup v2" in texts(r), r)
    r = pr.run_checks(ctx(tmp, threads=4), probes(cpus=12))
    check("threads within the CPUs are left alone", r["threads"] is None)
    r = pr.run_checks(ctx(tmp, threads=20), probes(env={}))
    check("unknown CPUs: nothing is capped, nothing is said", r["threads"] is None and r["level"] == "ok")

    # ---- folders -------------------------------------------------------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp), probes(writable=False))
    check("a folder that cannot be written is a failure naming it", r["level"] == "fail" and "cannot be written to: Read-only file system" in texts(r, "fail") and r["causes"] == ["an unwritable folder"], r)
    ok, why = pr.can_write(str(tmp / "tmp"))
    check("can_write really writes and removes a test file", ok and not any(n.startswith(".plasbench_write_test_") for n in os.listdir(tmp / "tmp")), why)
    r = pr.run_checks(ctx(tmp, data_dir="/mnt/c/study/data"), probes(wsl=True, mounts_text=MOUNTS_NONE, vdisk=lambda: vd(None, error="x")))
    check("a /mnt folder under WSL gets a slow-drive note", "much slower" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp, data_dir="C:/Users/x/OneDrive/study/data"), probes())
    check("a cloud-synced folder gets a note", "cloud-synced" in texts(r, "warn"), r)

    # ---- the retry plan ----------------------------------------------------------------------------------------------------------------
    check("retry plan: threads are halved, the budget never exceeds 80% of what is available",
          pr.memory_retry_plan(20, 5, 7) == (10, 5) and pr.memory_retry_plan(20, 12, 7) == (10, 5), (pr.memory_retry_plan(20, 5, 7), pr.memory_retry_plan(20, 12, 7)))
    check("retry plan: when SPAdes hit its own limit and more is free, the budget rises, up to the cap and never above the free memory",
          pr.memory_retry_plan(8, 4, 16, own_limit=True) == (4, 12) and pr.memory_retry_plan(8, 4, 5, own_limit=True) == (4, 4), (pr.memory_retry_plan(8, 4, 16, True), pr.memory_retry_plan(8, 4, 5, True)))
    check("retry plan: nothing smaller to try gives None", pr.memory_retry_plan(1, 2, 2) is None, pr.memory_retry_plan(1, 2, 2))
    check("retry plan never goes above the available memory", all(pr.memory_retry_plan(t, m, a)[1] <= max(2, int(a)) for t in (2, 8) for m in (3, 30) for a in (2.5, 7, 64) if pr.memory_retry_plan(t, m, a)))

    # ---- the command line ----------------------------------------------------------------------------------------------------------------
    sheet = tmp / "sheet.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\n", encoding="utf-8")
    base = [sys.executable, "-I", str(ROOT / "python" / "preflight_resources.py")]
    cmd = base + ["check", "--stage", "3", "--results-dir", str(tmp / "results"), "--data-dir", str(tmp / "data"), "--tmp-dir", str(tmp / "tmp"), "--sheet", str(sheet), "--threads", "4",
                  "--memory-gb", "4", "--parallel", "2"]
    out = subprocess.run(cmd + ["--quiet-ok"], capture_output=True, text=True, env={**os.environ, "PLASBENCH_SKIP_DISK_CHECK": "1"})
    check("the command line runs and exits 0 when the disk check is skipped", out.returncode == 0, out.stdout + out.stderr)
    out = subprocess.run(base + ["guard", "--stage", "3", "--sample", "s1", "--sra", "SRR1", "--results-dir", str(tmp / "results"), "--data-dir", str(tmp / "data"), "--tmp-dir", str(tmp / "tmp")],
                         capture_output=True, text=True, env={**os.environ, "PLASBENCH_DISK_RESERVE_GB": "99999999"})
    check("the command line guard exits 3 and prints the reason when the reserve cannot be met (PLASBENCH_DISK_RESERVE_GB honoured)", out.returncode == 3 and "Stopping before s1" in out.stdout, out.stdout + out.stderr)
    out = subprocess.run(base + ["guard", "--stage", "3", "--sample", "s1", "--sra", "SRR1", "--results-dir", str(tmp / "results"), "--data-dir", str(tmp / "data"), "--tmp-dir", str(tmp / "tmp")],
                         capture_output=True, text=True, env={**os.environ, "PLASBENCH_DISK_RESERVE_GB": "99999999", "PLASBENCH_SKIP_DISK_CHECK": "1"})
    check("... and PLASBENCH_SKIP_DISK_CHECK=1 lets it through", out.returncode == 0, out.stdout + out.stderr)
    out = subprocess.run(base + ["retry-plan", "--threads", "20", "--memory-gb", "5", "--available-gb", "7"], capture_output=True, text=True)
    check("retry-plan prints 'threads memory available'", out.stdout.split()[:2] == ["10", "5"], out.stdout + out.stderr)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all preflight-resource checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
