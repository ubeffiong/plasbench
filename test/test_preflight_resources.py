#!/usr/bin/env python3
"""python/preflight_resources.py: disk, memory, thread and folder checks with injected machine values (no real disk or WSL needed)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import preflight_resources as pr  # noqa: E402

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
    p = {"free": lambda path: int(free_gb * GB), "env": env, "wsl": wsl, "device": lambda path: 1,
         "writable": (lambda path: (True, "")) if writable else (lambda path: (False, "Read-only file system"))}
    p.update(extra)
    return p


def texts(result, level=None):
    return " | ".join(t for lv, t in result["items"] if level is None or lv == level)


def main():
    tmp = Path(tempfile.mkdtemp())
    for d in ("data/s1", "data/s2", "results", "tmp"):
        (tmp / d).mkdir(parents=True)
    # reads on disk: 0.5 GB compressed per isolate -> 4.5 GB each (trimmed copy + 8x working files)
    for s, sra in (("s1", "SRR1"), ("s2", "SRR2")):
        for suffix in ("_1.fastq.gz", "_2.fastq.gz"):
            with open(tmp / "data" / s / f"{sra}{suffix}", "wb") as handle:
                handle.truncate(250_000_000)
    todo, need, basis = pr.pending_work([("s1", "SRR1"), ("s2", "SRR2")], tmp / "data", 3)
    check("the estimate counts both isolates and is derived from the reads on disk", todo == 2 and need == 2 * 500_000_000 * 9 and "reads on disk" in basis, (todo, need, basis))
    (tmp / "data" / "s2" / "contigs.fasta").write_text(">c\nACGT\n", encoding="utf-8")
    todo2, need2, _ = pr.pending_work([("s1", "SRR1"), ("s2", "SRR2")], tmp / "data", 3)
    check("an isolate that already has contigs is not counted for stage 3", todo2 == 1 and need2 == need // 2, (todo2, need2))
    (tmp / "data" / "s2" / "contigs.fasta").unlink()
    t0, n0, b0 = pr.pending_work([("a", "X"), ("b", "Y")], tmp / "data", 0)
    check("with no reads on disk the typical-isolate figure is used and called an estimate", n0 == 2 * int(pr.FALLBACK_GB_PER_ISOLATE * GB) and "typical" in b0, (n0, b0))

    r = pr.run_checks(ctx(tmp), probes(free_gb=500))
    check("plenty of room: ok, nothing to report", r["level"] == "ok" and not r["items"] and r["threads"] is None, r)
    check("the rendered block starts with 'Resources check: ok'", pr.render(r, 3)[0].startswith("Resources check: ok"))
    r = pr.run_checks(ctx(tmp), probes(free_gb=15))
    check("under twice the estimate (9 GB): warn, not fail", r["level"] == "warn" and "estimated" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=5))
    check("under the estimate: fail, with the figures", r["level"] == "fail" and "only 5.0 GB" in texts(r, "fail") and "10.0 GB estimated for 2 isolate" in texts(r, "fail"), r)
    check("the failure names the override", "PLASBENCH_SKIP_DISK_CHECK=1" in texts(r, "fail"))
    r = pr.run_checks(ctx(tmp, skip_disk=True), probes(free_gb=0))
    check("PLASBENCH_SKIP_DISK_CHECK skips the disk figures", r["level"] == "ok", r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=0.1))
    check("under the hard floor it fails whatever the estimate", r["level"] == "fail")

    # --- WSL: the Windows drive that holds the virtual disk ------------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp), probes(free_gb=500, wsl=True, holder=lambda: "C", windows_free=lambda letter: 0))
    check("WSL with a full Windows drive: fail, naming the drive and the symptom", r["level"] == "fail" and "drive holding Ubuntu's virtual disk (C:) has only 0.0 GB free" in texts(r, "fail")
          and "No space left on device" in texts(r, "fail"), r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=500, wsl=True, holder=lambda: "C", windows_free=lambda letter: 12 * GB))
    check("WSL with 12 GB free on the drive (under twice the estimate): warn", r["level"] == "warn" and "C:" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=500, wsl=True, holder=lambda: "", windows_free=lambda letter: 0))
    check("WSL where the drive cannot be found: skipped quietly", r["level"] == "ok", r)
    r = pr.run_checks(ctx(tmp), probes(free_gb=500, wsl=False, holder=lambda: "C", windows_free=lambda letter: 0))
    check("not WSL: the Windows-drive check does not run", r["level"] == "ok", r)

    # --- memory and threads --------------------------------------------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp, memory_gb=5), probes(avail_gb=3))
    check("an assembler budget above the available memory is a warning", "budget is 5 GB but only 3.0 GB" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp, threads=20), probes(cpus=12))
    check("20 threads on 12 usable CPUs are capped to 12 and the decision is printed", r["threads"] == 12 and "using 12 threads" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp, threads=20, cap_threads=False), probes(cpus=12))
    check("CAP_THREADS_TO_CPUS=0 keeps the number and says so", r["threads"] is None and "keeps it as set" in texts(r, "warn"), r)
    env = {"memory_available": 16 * 2 ** 30, "usable_cpus": 6, "logical": 20, "limits": [{"what": "cpu", "text": "CPU time is limited to 6 CPUs by a cgroup v2 limit"}]}
    r = pr.run_checks(ctx(tmp, threads=20), probes(env=env))
    check("a cgroup CPU limit is the reason given for the cap", r["threads"] == 6 and "cgroup v2" in texts(r), r)
    r = pr.run_checks(ctx(tmp, threads=4), probes(cpus=12))
    check("threads within the CPUs are left alone", r["threads"] is None)
    r = pr.run_checks(ctx(tmp, threads=20), probes(env={}))
    check("unknown CPUs: nothing is capped, nothing is said", r["threads"] is None and r["level"] == "ok")

    # --- folders -------------------------------------------------------------------------------------------------------------------------
    r = pr.run_checks(ctx(tmp), probes(writable=False))
    check("a folder that cannot be written is a failure naming it", r["level"] == "fail" and "cannot be written to: Read-only file system" in texts(r, "fail"), r)
    ok, why = pr.can_write(str(tmp / "tmp"))
    check("can_write really writes and removes a test file", ok and not any(n.startswith(".plasbench_write_test_") for n in os.listdir(tmp / "tmp")), why)
    r = pr.run_checks(ctx(tmp, data_dir="/mnt/c/study/data"), probes(wsl=True, holder=lambda: ""))
    check("a /mnt folder under WSL gets a slow-drive note", "much slower" in texts(r, "warn"), r)
    r = pr.run_checks(ctx(tmp, data_dir="C:/Users/x/OneDrive/study/data"), probes())
    check("a cloud-synced folder gets a note", "cloud-synced" in texts(r, "warn"), r)

    # --- the retry plan ----------------------------------------------------------------------------------------------------------------
    check("retry plan: threads are halved, the budget never exceeds 80% of what is available",
          pr.memory_retry_plan(20, 5, 7) == (10, 5) and pr.memory_retry_plan(20, 12, 7) == (10, 5), (pr.memory_retry_plan(20, 5, 7), pr.memory_retry_plan(20, 12, 7)))
    check("retry plan: when SPAdes hit its own limit and more is free, the budget rises, up to the cap and never above the free memory",
          pr.memory_retry_plan(8, 4, 16, own_limit=True) == (4, 12) and pr.memory_retry_plan(8, 4, 5, own_limit=True) == (4, 4), (pr.memory_retry_plan(8, 4, 16, True), pr.memory_retry_plan(8, 4, 5, True)))
    check("retry plan: nothing smaller to try gives None", pr.memory_retry_plan(1, 2, 2) is None, pr.memory_retry_plan(1, 2, 2))
    check("retry plan never goes above the available memory", all(pr.memory_retry_plan(t, m, a)[1] <= max(2, int(a)) for t in (2, 8) for m in (3, 30) for a in (2.5, 7, 64) if pr.memory_retry_plan(t, m, a)))

    # --- the command line ----------------------------------------------------------------------------------------------------------------
    sheet = tmp / "sheet.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\n", encoding="utf-8")
    cmd = [sys.executable, "-I", str(ROOT / "python" / "preflight_resources.py"), "check", "--stage", "3", "--results-dir", str(tmp / "results"), "--data-dir", str(tmp / "data"),
           "--tmp-dir", str(tmp / "tmp"), "--sheet", str(sheet), "--threads", "4", "--memory-gb", "4"]
    out = subprocess.run(cmd + ["--quiet-ok"], capture_output=True, text=True, env={**os.environ, "PLASBENCH_SKIP_DISK_CHECK": "1"})
    check("the command line runs and exits 0 when the disk check is skipped", out.returncode == 0, out.stdout + out.stderr)
    out = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "preflight_resources.py"), "retry-plan", "--threads", "20", "--memory-gb", "5", "--available-gb", "7"], capture_output=True, text=True)
    check("retry-plan prints 'threads memory available'", out.stdout.split()[:2] == ["10", "5"], out.stdout + out.stderr)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all preflight-resource checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
