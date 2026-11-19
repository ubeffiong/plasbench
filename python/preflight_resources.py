#!/usr/bin/env python3
"""Check, before the heavy stages, that the computer has what they need: disk, memory, CPUs and writable folders.

  python3 -I python/preflight_resources.py check --stage 0|2|3 --results-dir D --data-dir D --tmp-dir D [--sheet S] --threads N --memory-gb N
  python3 -I python/preflight_resources.py retry-plan --threads N --memory-gb N [--own-limit]

A run used to find out that the disk was full or the memory short only when SPAdes died minutes into an isolate. This looks first, in milliseconds:

  disk     free space on the study, data and temporary folders against an ESTIMATE of what the isolates still to do will write (below), summed per
           drive. Warn under 2x the estimate, fail under 1x (override: PLASBENCH_SKIP_DISK_CHECK=1). Under WSL it also looks at the Windows drive that holds
           Ubuntu's virtual disk (found through the WSL registry entry, best effort) because that disk cannot grow when its drive is full.
  memory   the memory available now (cgroup and WSL aware, via plasbench/computer_info.py) against the assembler budget.
  threads  THREADS above the CPUs this process may really use (CPU count, affinity, cgroup quota, WSL processors=) is capped to them (CAP_THREADS_TO_CPUS=0 keeps it).
  folders  the study, data and temporary folders must accept a small write; a /mnt (Windows) folder or a cloud-synced folder gets a speed note.

Disk estimate (an estimate, and printed as one): per isolate still to assemble, trimmed reads about equal to the raw reads plus SPAdes working files at SPADES_WORK_FACTOR
times the raw compressed reads (an assumption in the 5 to 10 times range, the middle is used); with no reads on disk yet, FALLBACK_GB_PER_ISOLATE (the project's 0.63 GB of
downloads and results per isolate plus working space for a typical 0.3 GB read set). Every check skips quietly when its information is unavailable.
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GB = 10 ** 9                      # drive makers' and the download log's gigabyte
SPADES_WORK_FACTOR = 8            # assumption: SPAdes working files are 5-10x the compressed reads; the middle
FALLBACK_GB_PER_ISOLATE = 0.63 + 0.3 * SPADES_WORK_FACTOR
TMP_NEED_GB = 1.0                 # temporary folder: small helper files
HARD_FLOOR_GB = 0.5               # below this nothing can run, whatever the estimate


def gb(n):
    return f"{n / GB:.1f}"


def free_bytes(path, statvfs=None):
    """Free bytes for an unprivileged process where `path` is, or None."""
    p = str(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        if statvfs is not None or hasattr(os, "statvfs"):
            st = (statvfs or os.statvfs)(p)
            return st.f_bavail * st.f_frsize
        return shutil.disk_usage(p).free
    except (OSError, ValueError, AttributeError):
        return None


def device_of(path):
    p = str(path)
    while p and not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    try:
        return os.stat(p).st_dev
    except OSError:
        return None


def can_write(path):
    """(ok, why): a 4 KB write and removal in the folder (created when missing)."""
    try:
        os.makedirs(path, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".plasbench_write_test_", dir=str(path))
        try:
            os.write(fd, b"\0" * 4096)
            os.fsync(fd)
        finally:
            os.close(fd)
            os.unlink(name)
        return True, ""
    except OSError as exc:
        return False, (exc.strerror or str(exc))


def read_sheet(path):
    """[(sample, sra)] from the sample sheet (the same rules as lib.sh read_samples)."""
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [ln for ln in handle if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return rows
    for line in lines[1:]:
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) >= 3 and parts[0]:
            rows.append((parts[0], parts[2]))
    return rows


def pending_work(sheet_rows, data_dir, stage):
    """(isolates still to do, estimated bytes needed, how it was estimated)."""
    todo, total, measured = 0, 0, 0
    for sample, sra in sheet_rows:
        d = Path(data_dir) / sample
        if stage >= 3 and (d / "contigs.fasta").is_file() and os.path.getsize(d / "contigs.fasta") > 0:
            continue
        todo += 1
        reads = 0
        for suffix in ("_1.fastq.gz", "_2.fastq.gz"):
            try:
                reads += os.path.getsize(d / f"{sra}{suffix}")
            except OSError:
                pass
        if reads:
            total += reads * (1 + SPADES_WORK_FACTOR)
            measured += 1
        else:
            total += int(FALLBACK_GB_PER_ISOLATE * GB)
    basis = (f"from the size of the reads on disk for {measured} isolate(s)" if measured else "from a typical isolate (no reads on disk yet)")
    if measured and measured < todo:
        basis += f" and a typical isolate for the other {todo - measured}"
    return todo, total, basis


def usable_cpus(env):
    """(usable CPUs, the limit that sets it) from computer_info.environment()."""
    n = env.get("usable_cpus") or env.get("logical")
    why = ""
    for limit in env.get("limits", []):
        if limit.get("what") == "cpu":
            why = limit.get("text", "")
    wsl = env.get("wslconfig") or {}
    return n, why, wsl.get("processors")


def wsl_disk_holder(run=None, which=shutil.which):
    """The Windows drive letter holding this distribution's virtual disk, or ''. One PowerShell call (the Lxss registry key); best effort."""
    exe = which("powershell.exe")
    distro = os.environ.get("WSL_DISTRO_NAME", "")
    if not exe or not distro or not re.fullmatch(r"[A-Za-z0-9._ -]+", distro):
        return ""
    script = ("(Get-ChildItem HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss | Get-ItemProperty | "
              "Where-Object { $_.DistributionName -eq '%s' } | Select-Object -First 1).BasePath" % distro)
    out = (run or _run)([exe, "-NoProfile", "-NonInteractive", "-Command", script])
    m = re.search(r"([A-Za-z]):", out or "")
    return m.group(1).upper() if m else ""


def _run(argv, timeout=8):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return done.stdout if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def windows_free(letter, disks=None):
    """Free bytes of Windows drive `letter` (from computer_info.windows_disks), or None."""
    if disks is None:
        try:
            sys.path.insert(0, str(ROOT))
            from plasbench import computer_info
            disks = computer_info.windows_disks(run=lambda argv, timeout=8: _run(argv, timeout))
        except Exception:  # noqa: BLE001 - best effort
            return None
    for disk in disks or []:
        if str(disk.get("letter", "")).upper()[:1] == letter and disk.get("free") is not None:
            return disk["free"]
    return None


def run_checks(ctx, probes=None):
    """The verdict as {level, items:[(level, text)], threads (capped value or None), summary}. `probes` lets tests inject the machine."""
    probes = probes or {}
    free = probes.get("free", free_bytes)
    writable = probes.get("writable", can_write)
    device = probes.get("device", device_of)
    env = probes.get("env")
    if env is None:
        try:
            sys.path.insert(0, str(ROOT))
            from plasbench import computer_info
            wsl = probes.get("wsl", False)
            env = computer_info.environment(in_wsl=wsl)
        except Exception:  # noqa: BLE001
            env = {}
    wsl = probes.get("wsl", False)
    items = []
    skip_disk = ctx.get("skip_disk")
    stage = int(ctx.get("stage", 0))
    folders = [("study folder", ctx.get("results_dir")), ("data folder", ctx.get("data_dir")), ("temporary folder", ctx.get("tmp_dir"))]
    folders = [(label, p) for label, p in folders if p]

    # --- folders must be writable ----------------------------------------------------------------------------------------------
    for label, p in folders:
        ok, why = writable(p)
        if not ok:
            items.append(("fail", f"the {label} ({p}) cannot be written to: {why}. Choose a writable folder (TMPDIR for the temporary one)."))

    # --- disk ------------------------------------------------------------------------------------------------------------------
    todo, need, basis = pending_work(ctx.get("sheet_rows") or [], ctx.get("data_dir") or ".", stage)
    per_drive = {}
    for label, p in folders:
        key = device(p)
        entry = per_drive.setdefault(key if key is not None else p, {"labels": [], "path": p, "need": 0})
        entry["labels"].append(label)
        entry["need"] += TMP_NEED_GB * GB if label == "temporary folder" else (need if label == "data folder" else 0)
    if not skip_disk:
        for key, entry in per_drive.items():
            f = free(entry["path"])
            if f is None:
                continue
            nd = entry["need"]
            where = ", ".join(entry["labels"])
            est = f"{gb(nd)} GB estimated for {todo} isolate(s), {basis}" if nd and todo else "estimated need unknown"
            if f < HARD_FLOOR_GB * GB or (nd and f < nd):
                items.append(("fail", f"only {gb(f)} GB is free where the {where} is ({entry['path']}); {est}. Free space (df -h) or move the study; "
                                      "set PLASBENCH_SKIP_DISK_CHECK=1 to try anyway."))
            elif nd and f < 2 * nd:
                items.append(("warn", f"{gb(f)} GB is free where the {where} is; {est}: it may run short (under twice the estimate)."))
        if wsl:
            letter = probes["holder"]() if "holder" in probes else wsl_disk_holder()
            if letter:
                wf = probes["windows_free"](letter) if "windows_free" in probes else windows_free(letter)
                if wf is not None:
                    wneed = need if todo else 0
                    if wf < HARD_FLOOR_GB * GB or (wneed and wf < wneed):
                        items.append(("fail", f"the drive holding Ubuntu's virtual disk ({letter}:) has only {gb(wf)} GB free. Ubuntu's disk cannot grow past it, so assemblies fail "
                                              f"with 'No space left on device' even when df inside Ubuntu shows room. Free space on {letter}: (empty the Recycle Bin, move files off it), "
                                              "then run the same command again."))
                    elif wneed and wf < 2 * wneed:
                        items.append(("warn", f"the drive holding Ubuntu's virtual disk ({letter}:) has {gb(wf)} GB free; about {gb(wneed)} GB is estimated for this run."))

    # --- memory ----------------------------------------------------------------------------------------------------------------
    avail = env.get("memory_available")
    budget = ctx.get("memory_gb")
    if avail is not None and budget:
        avail_gb = avail / 2 ** 30
        if budget > avail_gb:
            items.append(("warn", f"the assembler budget is {budget} GB but only {avail_gb:.1f} GB of memory is available now: SPAdes may be killed or swap. "
                                  "Lower it (--memory-gb) or free memory."))
        for limit in env.get("limits", []):
            if limit.get("what") in ("memory", "wsl") and stage == 0:
                items.append(("note", limit["text"]))
                break

    # --- threads ---------------------------------------------------------------------------------------------------------------
    capped = None
    threads = ctx.get("threads")
    cpus, why, wsl_cpus = usable_cpus(env)
    if threads and cpus and threads > cpus:
        if ctx.get("cap_threads", True):
            capped = int(cpus)
            items.append(("warn", f"THREADS is {threads} but this process may use only {cpus} CPU(s){' (' + why + ')' if why else ''}: using {capped} threads "
                                  "(CAP_THREADS_TO_CPUS=0 keeps your number)."))
        else:
            items.append(("warn", f"THREADS is {threads} but only {cpus} CPU(s) are usable{' (' + why + ')' if why else ''}; CAP_THREADS_TO_CPUS=0 keeps it as set."))

    # --- speed notes -----------------------------------------------------------------------------------------------------------
    for label, p in folders[:2]:
        low = str(p).lower()
        if any(m in low for m in ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "nextcloud", "box sync")):
            items.append(("warn", f"the {label} ({p}) is inside a cloud-synced folder: syncing slows large reads and writes and can lock files. Use a folder that is not synced."))
        elif wsl and re.match(r"^/mnt/[a-z]/", str(p)):
            items.append(("warn", f"the {label} ({p}) is on a Windows drive seen from Ubuntu (/mnt): file access is much slower than inside Ubuntu's own disk."))

    level = "fail" if any(i[0] == "fail" for i in items) else "warn" if any(i[0] == "warn" for i in items) else "ok"
    cpu_text = f"{cpus} CPU(s)" if cpus else "CPUs unknown"
    mem_text = f"{avail / 2 ** 30:.1f} GB memory available" if avail else "memory unknown"
    return {"level": level, "items": items, "threads": capped, "summary": f"{cpu_text}, {mem_text}"}


def render(result, stage):
    n_warn = sum(1 for i in result["items"] if i[0] in ("warn", "fail"))
    head = "Resources check: ok" if result["level"] == "ok" else (f"Resources check: {n_warn} warning(s)" if result["level"] == "warn" else "Resources check: NOT ENOUGH RESOURCES")
    lines = [f"{head} ({result['summary']})"]
    for level, text in result["items"]:
        lines.append(("  FAIL: " if level == "fail" else "  - ") + text)
    return lines


def memory_retry_plan(threads, memory_gb, available_gb, own_limit=False):
    """New (threads, memory_gb) for ONE retry after an out-of-memory failure, or None when there is nothing smaller to try.
    Threads are halved (never below 1). The budget never goes above 80% of the memory available now; when SPAdes stopped at its OWN limit and more is
    available, the budget rises to that cap, otherwise it only falls."""
    threads, memory_gb = int(threads), int(memory_gb)
    cap = int(available_gb * 0.8) if available_gb is not None else memory_gb
    cap = max(2, cap)
    new_mem = max(cap, memory_gb) if (own_limit and cap > memory_gb) else min(memory_gb, cap)
    new_threads = max(1, threads // 2)
    if available_gb is not None:
        new_mem = min(new_mem, max(2, int(available_gb)))
    if new_threads == threads and new_mem >= memory_gb:
        return None
    return new_threads, new_mem


def _available_gb():
    try:
        sys.path.insert(0, str(ROOT))
        from plasbench import computer_info
        avail = computer_info.environment(in_wsl=False).get("memory_available")
        return avail / 2 ** 30 if avail else None
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--stage", type=int, default=0)
    c.add_argument("--results-dir")
    c.add_argument("--data-dir")
    c.add_argument("--tmp-dir")
    c.add_argument("--sheet")
    c.add_argument("--threads", type=int)
    c.add_argument("--memory-gb", type=int)
    c.add_argument("--no-cap", action="store_true")
    c.add_argument("--quiet-ok", action="store_true", help="print nothing when everything is fine")
    r = sub.add_parser("retry-plan")
    r.add_argument("--threads", type=int, required=True)
    r.add_argument("--memory-gb", type=int, required=True)
    r.add_argument("--own-limit", action="store_true")
    r.add_argument("--available-gb", type=float)
    args = ap.parse_args(argv)
    if args.cmd == "retry-plan":
        avail = args.available_gb if args.available_gb is not None else _available_gb()
        plan = memory_retry_plan(args.threads, args.memory_gb, avail, args.own_limit)
        print("none" if plan is None else f"{plan[0]} {plan[1]} {'-' if avail is None else '%.1f' % avail}")
        return 0
    wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or ("microsoft" in (Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower() if Path("/proc/sys/kernel/osrelease").exists() else ""))
    ctx = {"stage": args.stage, "results_dir": args.results_dir, "data_dir": args.data_dir, "tmp_dir": args.tmp_dir,
           "sheet_rows": read_sheet(args.sheet) if args.sheet else [], "threads": args.threads, "memory_gb": args.memory_gb,
           "cap_threads": not args.no_cap, "skip_disk": os.environ.get("PLASBENCH_SKIP_DISK_CHECK") == "1"}
    result = run_checks(ctx, {"wsl": wsl})
    if not (args.quiet_ok and result["level"] == "ok"):
        print("\n".join(render(result, args.stage)))
    if result["threads"]:
        print(f"@threads={result['threads']}")
    return 3 if result["level"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
