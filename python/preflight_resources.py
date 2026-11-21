#!/usr/bin/env python3
"""Check, before the heavy stages, that the computer has what they need: disk, memory, CPUs and writable folders.

  python3 -I python/preflight_resources.py check --stage 0|2|3 --results-dir D --data-dir D --tmp-dir D [--sheet S] --threads N --memory-gb N [--parallel N]
  python3 -I python/preflight_resources.py guard --stage 1|3 --sample S --sra R --results-dir D --data-dir D --tmp-dir D [--in-flight N]   (the rolling guard, exit 3 = stop)
  python3 -I python/preflight_resources.py vdisk                     (where Ubuntu's virtual disk is and how much room its Windows drive has, with the evidence)
  python3 -I python/preflight_resources.py retry-plan --threads N --memory-gb N [--own-limit]

A run used to find out that the disk was full or the memory short only when SPAdes died minutes into an isolate. This looks first, in milliseconds.

  disk     what the run will write, against the free space where it will be written, per drive. TWO figures, because a cohort is long and most of it is later:
             working set  what the first isolates need AT ONCE (peak per isolate x isolates in flight, MAX_PARALLEL_SAMPLES): if that does not fit, the run cannot
                          even start: FAIL (exit 6);
             whole run    what every isolate still to do will leave on disk (nothing is deleted after an isolate: reads, trimmed reads and the assembler folder stay):
                          if that does not fit, it is only a WARNING, with the number of isolates that will fit and a --max-isolates to use. A rolling guard
                          (`guard`, called before each isolate in stages 1 and 3) stops the run cleanly, exit 6, when the next isolate no longer fits plus a reserve
                          (PLASBENCH_DISK_RESERVE_GB, default 5); the finished isolates are kept and the same command resumes.
           Override: PLASBENCH_SKIP_DISK_CHECK=1 (the check and the guard).
  WSL      Ubuntu's own disk is a file (ext4.vhdx) on a Windows drive and cannot grow past that drive. The distribution THIS process runs in is found by its exact name
           (WSL_DISTRO_NAME, never another distribution such as docker-desktop) in the Windows registry and that drive's free BYTES are read; any problem gives
           'unknown', never a number, and the message shows the evidence. What matters depends on where the folders are: on a mounted Windows drive (/mnt/e, drvfs/9p) only
           small things go to Ubuntu's disk (conda environments, logs, caches), so only a hard floor (PLASBENCH_VDISK_MIN_GB, default 2) fails and under 10 GB warns; on
           Ubuntu's own disk, or in a /mnt/<x> folder that is NOT a mount (it lives on Ubuntu's disk), that drive's free space is the limit and is compared to the estimate.
  memory   the memory available now (cgroup and WSL aware, via plasbench/computer_info.py) against the assembler budget: a warning when the budget is the larger.
  threads  THREADS above the CPUs this process may really use (CPU count, affinity, cgroup quota, WSL processors=) is capped to them (CAP_THREADS_TO_CPUS=0 keeps it).
  folders  the study, data and temporary folders must accept a small write; a /mnt (Windows) folder or a cloud-synced folder gets a speed note.

Estimate (an estimate, and printed as one, with how it was got): reads per isolate are, in order, their size on disk, the base count in the cohort's verification lock x 0.615 bytes
per base, the mean of up to 20 sampled isolates whose size ENA reports (online, stage 0 only, cached in the study folder), else a typical 0.3 GB read set (low confidence).
Peak per isolate = trimmed reads (1x) + SPAdes working files (SPADES_WORK_FACTOR, 8x, an assumption in the 5 to 10 range) of that, plus 0.33 GB (reference, raw reads, results).
Kept per isolate = raw + trimmed reads + the assembler folder (ASM_KEPT_FACTOR, 3x of the reads, an assumption: the pipeline does not delete it) plus 0.33 GB.
Every check skips quietly when its information is unavailable. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GB = 10 ** 9                      # drive makers' and the download log's gigabyte
SPADES_WORK_FACTOR = 8            # assumption: SPAdes working files are 5-10x the compressed reads; the middle
ASM_KEPT_FACTOR = 3               # assumption: the assembler folder that stays after an isolate is about 3x the compressed reads
BYTES_PER_BASE = 0.615            # compressed FASTQ per base, measured on real downloads (python/estimate_download.py)
TYPICAL_READS_GB = 0.3            # a typical read set; used only when nothing is known
OTHER_GB = 0.33                   # reference bundle, raw reads and results per isolate (the project's 0.63 GB per isolate minus a typical 0.3 GB read set)
FALLBACK_GB_PER_ISOLATE = OTHER_GB + TYPICAL_READS_GB * (1 + SPADES_WORK_FACTOR)   # peak for a typical isolate, 3.03 GB
TMP_NEED_GB = 1.0                 # temporary folder: small helper files
HARD_FLOOR_GB = 0.5               # below this nothing can run, whatever the estimate
VDISK_FLOOR_GB = 2.0              # Ubuntu's disk, when only small things go to it: a failure below this
VDISK_COMFORT_GB = 10.0           # ... and a warning below this
RESERVE_GB = 5.0                  # kept free on top of what an isolate needs (PLASBENCH_DISK_RESERVE_GB)
SAMPLE_SIZE_N = 20                # isolates whose reads size ENA is asked for


def _env_gb(name, default):
    try:
        v = float(os.environ.get(name, ""))
        return v if v >= 0 else default
    except ValueError:
        return default


def _ci():
    sys.path.insert(0, str(ROOT))
    from plasbench import computer_info
    return computer_info


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


def isolate_bytes(reads):
    """(peak, kept) bytes for one isolate whose compressed read set is `reads` bytes (see the module docstring for the assumptions)."""
    return int(reads * (1 + SPADES_WORK_FACTOR) + OTHER_GB * GB), int(reads * (2 + ASM_KEPT_FACTOR) + OTHER_GB * GB)


def _reads_on_disk(d, sra):
    reads = 0
    for suffix in ("_1.fastq.gz", "_2.fastq.gz"):
        try:
            reads += os.path.getsize(d / f"{sra}{suffix}")
        except OSError:
            pass
    return reads


def _lock_bases(sheet):
    """{sample: bases} from the sheet's verification lock (python/estimate_download.py), or {}."""
    if not sheet:
        return {}
    try:
        sys.path.insert(0, str(ROOT / "python"))
        import estimate_download
        return estimate_download.lock_bases(Path(sheet))
    except Exception:  # noqa: BLE001 - advice only
        return {}


def sampled_read_sizes(sras, results_dir, allow_lookup):
    """Compressed read-set sizes (bytes) of up to SAMPLE_SIZE_N isolates picked at random (fixed seed) from `sras`: from the cache in the study folder, and, when
    `allow_lookup`, asked of ENA for the rest within 10 seconds (python/estimate_download.ena_sizes) and cached. [] when none is known."""
    uniq = sorted(set(sras))
    pick = random.Random(0).sample(uniq, min(SAMPLE_SIZE_N, len(uniq))) if uniq else []
    cache_file = Path(results_dir) / ".ena_size_cache.json" if results_dir else None
    cache = {}
    try:
        if cache_file and cache_file.is_file():
            cache = {k: int(v) for k, v in json.loads(cache_file.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, TypeError):
        cache = {}
    missing = [r for r in pick if r not in cache]
    if missing and allow_lookup:
        try:
            sys.path.insert(0, str(ROOT / "python"))
            import estimate_download
            if estimate_download.lookup_enabled() and os.environ.get("PLASBENCH_OFFLINE") != "1" and not estimate_download.ena_unreachable():
                found, _ = estimate_download.ena_sizes({r: r for r in missing}, deadline=10.0)
                cache.update({k: int(v) for k, v in found.items()})
                if found and cache_file:
                    try:
                        cache_file.parent.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(json.dumps(cache), encoding="utf-8")
                    except OSError:
                        pass
        except Exception:  # noqa: BLE001 - a failed lookup only leaves the estimate typical
            pass
    return [cache[r] for r in pick if r in cache]


def pending_work(sheet_rows, data_dir, stage, sheet=None, in_flight=1, results_dir=None, sizes=None, lock=None, allow_lookup=False):
    """The estimate for the isolates still to do, as a dict:
      todo, whole (bytes the whole run leaves on disk), working (bytes the next `in_flight` isolates need at once), peak_mean, kept_mean, basis (how, in words),
      confidence ('measured' | 'sampled' | 'typical'), counts {disk, lock, sampled, typical}.
    `sizes` / `lock` let a test inject the sampled sizes and the lock's base counts."""
    pending = []
    for sample, sra in sheet_rows:
        d = Path(data_dir) / sample
        if stage >= 3 and (d / "contigs.fasta").is_file() and os.path.getsize(d / "contigs.fasta") > 0:
            continue
        pending.append((sample, sra, _reads_on_disk(d, sra)))
    lock = _lock_bases(sheet) if lock is None else lock
    unknown = [sra for sample, sra, r in pending if not r and not lock.get(sample)]
    if sizes is None:
        sizes = sampled_read_sizes(unknown, results_dir, allow_lookup) if unknown else []
    mean_reads = sum(sizes) / len(sizes) if sizes else None
    counts = {"disk": 0, "lock": 0, "sampled": 0, "typical": 0}
    peaks, kepts, remaining = [], [], []
    for sample, sra, on_disk in pending:
        if on_disk:
            reads, how = on_disk, "disk"
        elif lock.get(sample):
            reads, how = int(lock[sample] * BYTES_PER_BASE), "lock"
        elif mean_reads is not None:
            reads, how = mean_reads, "sampled"
        else:
            reads, how = TYPICAL_READS_GB * GB, "typical"
        counts[how] += 1
        peak, kept = isolate_bytes(reads)
        peaks.append(peak)
        kepts.append(kept)
        remaining.append(max(0, peak - (on_disk or 0)))
    todo = len(pending)
    top = sorted(remaining, reverse=True)[:max(1, int(in_flight))]
    parts = []
    if counts["disk"]:
        parts.append(f"the size of the reads on disk for {counts['disk']} isolate(s)")
    if counts["lock"]:
        parts.append(f"the verification lock's base counts for {counts['lock']}")
    if counts["sampled"]:
        parts.append(f"the mean read size of {len(sizes)} sampled isolate(s) ({mean_reads / GB:.2f} GB per read set, ENA) for {counts['sampled']}")
    if counts["typical"]:
        parts.append(f"a typical isolate ({TYPICAL_READS_GB} GB of reads, NOT measured) for {counts['typical']}")
    basis = ("from " + ", ".join(parts)) if parts else "nothing left to do"
    if counts["typical"] and not (counts["disk"] or counts["lock"] or counts["sampled"]):
        confidence = "typical"
    elif counts["typical"] or counts["sampled"]:
        confidence = "sampled"
    else:
        confidence = "measured"
    return {"todo": todo, "whole": sum(kepts), "working": sum(top), "peak_mean": int(sum(peaks) / todo) if todo else 0, "kept_mean": int(sum(kepts) / todo) if todo else 0,
            "basis": basis, "confidence": confidence, "counts": counts}


def usable_cpus(env):
    """(usable CPUs, the limit that sets it) from computer_info.environment()."""
    n = env.get("usable_cpus") or env.get("logical")
    why = ""
    for limit in env.get("limits", []):
        if limit.get("what") == "cpu":
            why = limit.get("text", "")
    wsl = env.get("wslconfig") or {}
    return n, why, wsl.get("processors")


def _run(argv, timeout=8):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)   # never read the caller's stdin (powershell.exe does)
        return done.stdout if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def wsl_vdisk(run=None, which=shutil.which, env=None, disks=None):
    """Where this Ubuntu's virtual disk is and how much room its Windows drive has (plasbench/computer_info.wsl_vdisk): a dict with the evidence, free None when unknown."""
    try:
        ci = _ci()
        runner = run or _run
        return ci.wsl_vdisk(run=lambda argv, timeout=8: runner(argv), which=which, env=env, disks=disks)
    except Exception as exc:  # noqa: BLE001 - best effort
        return {"distro": "", "base": "", "vhdx": "", "letter": "", "free": None, "total": None, "how": "", "error": f"the probe failed ({exc.__class__.__name__})", "command": "", "others": []}


def vdisk_evidence(v):
    """One line of evidence for a vdisk probe result."""
    if not v:
        return "Ubuntu's virtual disk: not looked at"
    where = f"distro '{v.get('distro') or '?'}'" + (f", file {v['vhdx']}" if v.get("vhdx") else "") + (f", volume {v['letter']}:" if v.get("letter") else "")
    if v.get("free") is None:
        return f"Ubuntu's virtual disk: free space UNKNOWN ({v.get('error') or 'not measured'}); {where}"
    return f"Ubuntu's virtual disk: {where}: {gb(v['free'])} GB free ({v['free']} bytes, from {v.get('how') or 'Windows'})"


def classify(path, wsl, mounts_text=None):
    try:
        return _ci().classify_path(path, wsl, mounts_text)
    except Exception:  # noqa: BLE001
        return ("vdisk", "") if wsl else ("native", "")


def describe(kind, letter):
    if kind == "windows":
        return f"Windows drive {letter + ':' if letter else '(a mounted drive)'} (a real mount, /mnt{'/' + letter.lower() if letter else ''})"
    if kind == "unmounted":
        return f"a folder on Ubuntu's own disk (/mnt/{letter.lower()} is NOT a mounted drive)"
    if kind == "vdisk":
        return "Ubuntu's own disk"
    return "the drive"


def mount_help(letter):
    try:
        sys.path.insert(0, str(ROOT))
        from plasbench import chooser
        return chooser.mount_command(letter)
    except Exception:  # noqa: BLE001
        return f"sudo mkdir -p /mnt/{letter.lower()} && sudo mount -t drvfs {letter}: /mnt/{letter.lower()}"


def suggest_max_isolates(k):
    """A round number of isolates at or below k (1, 2, 5, 10, 20, 50, 100, ...), at least 1."""
    if k < 1:
        return 1
    mag = 10 ** (len(str(int(k))) - 1)
    for step in (5, 2, 1):
        if mag * step <= k:
            return mag * step
    return int(k)


def run_checks(ctx, probes=None):
    """The verdict as {level, items:[(level, text)], detail:[lines], rules, causes, threads (capped value or None), summary}. `probes` lets tests inject the machine."""
    probes = probes or {}
    free = probes.get("free", free_bytes)
    writable = probes.get("writable", can_write)
    device = probes.get("device", device_of)
    env = probes.get("env")
    if env is None:
        try:
            env = _ci().environment(in_wsl=probes.get("wsl", False))
        except Exception:  # noqa: BLE001
            env = {}
    wsl = probes.get("wsl", False)
    items, detail, causes = [], [], []
    skip_disk = ctx.get("skip_disk")
    stage = int(ctx.get("stage", 0))
    parallel = max(1, int(ctx.get("parallel", 1)))
    reserve = ctx.get("reserve_gb", RESERVE_GB) * GB
    vfloor = ctx.get("vdisk_min_gb", VDISK_FLOOR_GB) * GB
    folders = [("study folder", ctx.get("results_dir")), ("data folder", ctx.get("data_dir")), ("temporary folder", ctx.get("tmp_dir"))]
    folders = [(label, p) for label, p in folders if p]

    # --- folders must be writable ----------------------------------------------------------------------------------------------
    for label, p in folders:
        ok, why = writable(p)
        if not ok:
            items.append(("fail", f"the {label} ({p}) cannot be written to: {why}. Choose a writable folder (TMPDIR for the temporary one)."))
            causes.append("an unwritable folder")

    # --- disk ------------------------------------------------------------------------------------------------------------------
    est = pending_work(ctx.get("sheet_rows") or [], ctx.get("data_dir") or ".", stage, sheet=ctx.get("sheet"), in_flight=parallel, results_dir=ctx.get("results_dir"),
                       sizes=probes.get("sizes"), lock=probes.get("lock"), allow_lookup=(stage == 0 and not skip_disk and probes.get("lookup", True)))
    todo = est["todo"]
    mounts_text = probes.get("mounts_text")
    per_drive = {}
    for label, p in folders:
        key = device(p)
        kind, letter = classify(p, wsl, mounts_text)
        entry = per_drive.setdefault(key if key is not None else p, {"labels": [], "path": p, "work": 0, "whole": 0, "kind": kind, "letter": letter})
        entry["labels"].append(label)
        if label == "temporary folder":
            entry["work"] += TMP_NEED_GB * GB
            entry["whole"] += TMP_NEED_GB * GB
        elif label == "data folder":
            entry["work"] += est["working"]
            entry["whole"] += est["whole"]
    if not skip_disk:
        vd = None
        if wsl and per_drive:
            vd = probes["vdisk"]() if "vdisk" in probes else wsl_vdisk()
        host_free = vd.get("free") if vd else None
        on_vdisk_need = sum(e["whole"] for e in per_drive.values() if e["kind"] in ("vdisk", "unmounted"))
        measured_lines, advice, block_advice = [], [], []
        needed_line = ""
        blocked = False
        for key, entry in per_drive.items():
            f = free(entry["path"])
            if f is None:
                continue
            kind = entry["kind"]
            where = ", ".join(entry["labels"])
            desc = describe(kind, entry["letter"])
            eff, limit_by = f, ""
            if kind in ("vdisk", "unmounted") and host_free is not None and host_free < f:
                eff = host_free
                limit_by = f" (limited by Windows drive {vd['letter']}: under Ubuntu's disk, which has {gb(host_free)} GB free; df inside Ubuntu shows {gb(f)} GB)"
            measured_lines.append(f"the {where} ({entry['path']}): {gb(f)} GB free on {desc} (statvfs, {f} bytes){limit_by}")
            w, whole = entry["work"], entry["whole"]
            if kind == "unmounted":
                items.append(("warn", f"{entry['letter']}: is not mounted: /mnt/{entry['letter'].lower()} is just a folder on Ubuntu's disk, so the {where} is written to Ubuntu's virtual disk, "
                                      f"not to the {entry['letter']}: drive. Mount it first (PlasBench never runs this for you): {mount_help(entry['letter'])}"))
            if eff < HARD_FLOOR_GB * GB or (w and eff < w):
                blocked = True
                items.append(("fail", f"cannot start: {gb(eff)} GB is free for the {where} on {desc}{limit_by}; the first {parallel} isolate(s) need about "
                                      f"{gb(est['working'])} GB at once (working set, {est['confidence']} estimate)."))
                causes.append("disk space")
                block_advice += ["free space there or choose a folder on a bigger drive (df -h)", "set PLASBENCH_SKIP_DISK_CHECK=1 to try anyway (it may fail partway)"]
            elif whole and todo and eff < whole + reserve:
                fits = max(0, int((eff - reserve - (TMP_NEED_GB * GB if "temporary folder" in entry["labels"] else 0)) / max(1, est["kept_mean"])))
                sug = suggest_max_isolates(fits)
                items.append(("warn", f"this run will fill {desc} after about {fits} of {todo} isolate(s) (estimate, {est['confidence']}): {gb(eff)} GB free{limit_by}, "
                                      f"about {gb(whole)} GB for all {todo}. The run stops cleanly when space runs out (finished isolates are kept)."))
                advice += [f"add --max-isolates {sug}", f"or free space / use a drive with about {gb(whole + reserve)} GB free", "or continue as is: it stops cleanly and the same command resumes"]
        if todo:
            needed_line = (f"the first {parallel} isolate(s) need about {gb(est['working'])} GB at once; all {todo} isolate(s) leave about {gb(est['whole'])} GB "
                           f"({gb(est['kept_mean'])} GB each); {est['basis']}; {est['confidence']} estimate. Peak per isolate = trimmed reads + {SPADES_WORK_FACTOR}x SPAdes working files; "
                           f"kept = raw + trimmed reads + assembler folder ({ASM_KEPT_FACTOR}x, assumed); nothing is deleted after an isolate.")
        # Ubuntu's virtual disk: the Windows drive under it
        if vd is not None:
            measured_lines.append(vdisk_evidence(vd))
            if host_free is not None:
                if host_free < vfloor:
                    blocked = True
                    items.append(("fail", f"the Windows drive {vd['letter']}: holding Ubuntu's virtual disk has only {gb(host_free)} GB free (below the {gb(vfloor)} GB floor). Ubuntu's disk cannot grow past it: "
                                          f"conda environments, logs and caches fail with 'No space left on device' even when df inside Ubuntu shows room. Free space on {vd['letter']}: "
                                          "(empty the Recycle Bin, move files off it), then run the same command again."))
                    causes.append("disk space")
                    block_advice += [f"free space on {vd['letter']}: (it holds Ubuntu's disk); check it yourself: {vd['command']}", "then run the same command again"]
                elif not on_vdisk_need and host_free < VDISK_COMFORT_GB * GB:
                    items.append(("warn", f"the Windows drive {vd['letter']}: holding Ubuntu's virtual disk has {gb(host_free)} GB free: enough to start (the study, data and temporary folders are not on it), "
                                          "but conda environments and logs are written there; keep at least 10 GB free."))
            elif on_vdisk_need:
                items.append(("note", f"could not measure the Windows drive under Ubuntu's disk ({vd.get('error') or 'unknown'}); only Ubuntu's own df figure was used."
                                      + (f" Check it yourself: {vd['command']}" if vd.get("command") else "")))
        if blocked or any(i[0] == "warn" and ("isolate(s)" in i[1] or "virtual disk" in i[1] or "not mounted" in i[1]) for i in items):
            detail.append("Measured: " + "; ".join(measured_lines))
            if needed_line:
                detail.append("Needed: " + needed_line)
            seen = []
            for a in (block_advice if blocked else advice):
                if a not in seen:
                    seen.append(a)
            if seen:
                detail.append("Next: " + " ".join(f"({i + 1}) {a};" for i, a in enumerate(seen[:3])).rstrip(";") + ".")
        if todo and ctx.get("results_dir") and probes.get("write_cache", True):
            try:
                Path(ctx["results_dir"]).mkdir(parents=True, exist_ok=True)
                (Path(ctx["results_dir"]) / ".disk_estimate.json").write_text(json.dumps({"peak_mean": est["peak_mean"], "kept_mean": est["kept_mean"],
                                                                                           "confidence": est["confidence"]}), encoding="utf-8")
            except OSError:
                pass

    # --- memory ----------------------------------------------------------------------------------------------------------------
    avail = env.get("memory_available")
    budget = ctx.get("memory_gb")
    rules = []
    if avail is not None and budget:
        avail_gb = avail / 2 ** 30
        if budget > avail_gb:
            items.append(("warn", f"memory: the assembler budget ({budget} GB, MEMORY_GB) is above the {avail_gb:.1f} GB available now: SPAdes may be killed or swap. "
                                  "Lower it (--memory-gb) or free memory."))
            rules.append(f"memory: {budget} GB budget > {avail_gb:.1f} GB available: warn")
        else:
            rules.append(f"memory: {budget} GB assembler budget <= {avail_gb:.1f} GB available: ok")
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
            items.append(("warn", f"threads: THREADS is {threads} but this process may use only {cpus} CPU(s){' (' + why + ')' if why else ''}: using {capped} threads "
                                  "(CAP_THREADS_TO_CPUS=0 keeps your number)."))
            rules.append(f"threads: {threads} > {cpus} usable CPU(s): capped to {capped}")
        else:
            items.append(("warn", f"threads: THREADS is {threads} but only {cpus} CPU(s) are usable{' (' + why + ')' if why else ''}; CAP_THREADS_TO_CPUS=0 keeps it as set."))
            rules.append(f"threads: {threads} > {cpus} usable CPU(s): kept as set")
    elif threads and cpus:
        rules.append(f"threads: {threads} <= {cpus} usable CPU(s): no cap")

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
    return {"level": level, "items": items, "detail": detail, "rules": rules, "causes": sorted(set(causes)), "threads": capped, "summary": f"{cpu_text}, {mem_text}"}


def render(result, stage):
    items = result["items"]
    n_warn = sum(1 for i in items if i[0] in ("warn", "fail"))
    causes = result.get("causes") or []
    if result["level"] == "ok":
        head = "Resources check: ok"
    elif result["level"] == "warn":
        head = f"Resources check: {n_warn} warning(s), the run can start"
    else:
        head = "Resources check: the run cannot start because of " + " and ".join(causes or ["a resource problem"])
    rules = result.get("rules") or []
    lines = [f"{head} ({result['summary']}{'; ' + '; '.join(rules) if rules else ''})"]
    for level, text in items:
        lines.append(("  FAIL: " if level == "fail" else "  - ") + text)
    for d in result.get("detail") or []:
        lines.append("  " + d)
    return lines


def guard(ctx, probes=None):
    """The rolling check before one isolate's download (stage 1) or assembly (stage 3): (ok, [lines]). It stops when the free space on a drive the isolate writes to is
    below what that isolate needs (for `in_flight` isolates) plus the reserve. An isolate whose output is already there needs nothing."""
    probes = probes or {}
    free = probes.get("free", free_bytes)
    device = probes.get("device", device_of)
    if ctx.get("skip_disk"):
        return True, []
    stage, sample, sra = int(ctx.get("stage", 3)), ctx.get("sample", ""), ctx.get("sra", "")
    d = Path(ctx.get("data_dir") or ".") / sample
    if stage >= 3 and (d / "contigs.fasta").is_file() and os.path.getsize(d / "contigs.fasta") > 0:
        return True, []
    on_disk = _reads_on_disk(d, sra)
    if stage <= 1 and on_disk and (d / "reference.fna").is_file():
        return True, []
    try:
        cache = json.loads((Path(ctx.get("results_dir") or ".") / ".disk_estimate.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    peak = isolate_bytes(on_disk)[0] if on_disk else int(cache.get("peak_mean") or FALLBACK_GB_PER_ISOLATE * GB)
    need = max(0, peak - on_disk) * max(1, int(ctx.get("in_flight", 1)))
    reserve = ctx.get("reserve_gb", RESERVE_GB) * GB
    wsl = probes.get("wsl", False)
    groups = {}
    for label, p, n in (("data folder", ctx.get("data_dir"), need), ("study folder", ctx.get("results_dir"), 0), ("temporary folder", ctx.get("tmp_dir"), TMP_NEED_GB * GB)):
        if not p:
            continue
        key = device(p)
        g = groups.setdefault(key if key is not None else p, {"labels": [], "path": p, "need": 0, "kind": classify(p, wsl, probes.get("mounts_text"))})
        g["labels"].append(label)
        g["need"] += n
    host_free = None
    if wsl and any(g["kind"][0] in ("vdisk", "unmounted") for g in groups.values()):
        host_free = probes["vdisk_free"]() if "vdisk_free" in probes else _cached_vdisk_free(ctx)
    for g in groups.values():
        f = free(g["path"])
        if f is None:
            continue
        eff = f
        if g["kind"][0] in ("vdisk", "unmounted") and host_free is not None:
            eff = min(f, host_free)
        if eff < g["need"] + reserve:
            where = ", ".join(g["labels"])
            return False, [f"Stopping before {sample}: only {gb(eff)} GB is free for the {where} on {describe(g['kind'][0], g['kind'][1])} ({g['path']}); "
                           f"this isolate needs about {gb(g['need'])} GB (estimate) plus a {gb(reserve)} GB reserve (PLASBENCH_DISK_RESERVE_GB).",
                           "The isolates already finished are kept. Free space (or choose a bigger drive), then run the same command again: it continues with the isolates not finished yet. "
                           "PLASBENCH_SKIP_DISK_CHECK=1 turns this guard off."]
    return True, []


def _cached_vdisk_free(ctx, max_age=300):
    """Free bytes of the Windows drive under Ubuntu's disk, re-read at most every `max_age` seconds (the probe takes a second); None when unknown."""
    f = Path(ctx.get("results_dir") or ".") / ".vdisk_free.json"
    try:
        c = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - float(c["at"]) < max_age:
            return c["free"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    free = wsl_vdisk().get("free")
    try:
        f.write_text(json.dumps({"free": free, "at": time.time()}), encoding="utf-8")
    except OSError:
        pass
    return free


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
    forced = os.environ.get("PLASBENCH_TEST_AVAILABLE_MB")      # lets a test pretend to be a smaller or larger machine
    if forced and forced.isdigit():
        return int(forced) / 1024.0
    try:
        sys.path.insert(0, str(ROOT))
        from plasbench import computer_info
        avail = computer_info.environment(in_wsl=False).get("memory_available")
        return avail / 2 ** 30 if avail else None
    except Exception:  # noqa: BLE001
        return None


def _in_container():
    """True inside a container: it shares WSL2's kernel under Docker Desktop but is not a WSL distribution, so the WSL / Windows-drive checks do not apply."""
    flag = os.environ.get("PLASBENCH_IN_DOCKER", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _is_wsl():
    if _in_container():
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


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
    c.add_argument("--parallel", type=int, default=1, help="isolates in flight at once (MAX_PARALLEL_SAMPLES)")
    c.add_argument("--no-cap", action="store_true")
    c.add_argument("--quiet-ok", action="store_true", help="print nothing when everything is fine")
    g = sub.add_parser("guard")
    g.add_argument("--stage", type=int, required=True)
    g.add_argument("--sample", required=True)
    g.add_argument("--sra", default="")
    g.add_argument("--results-dir")
    g.add_argument("--data-dir")
    g.add_argument("--tmp-dir")
    g.add_argument("--in-flight", type=int, default=1)
    sub.add_parser("vdisk")
    sub.add_parser("available", help="memory available now in GB (cgroup and WSL aware), one decimal; empty when unknown")
    r = sub.add_parser("retry-plan")
    r.add_argument("--threads", type=int, required=True)
    r.add_argument("--memory-gb", type=int, required=True)
    r.add_argument("--own-limit", action="store_true")
    r.add_argument("--available-gb", type=float)
    args = ap.parse_args(argv)
    if args.cmd == "available":
        avail = _available_gb()
        print("" if avail is None else "%.1f" % avail)
        return 0
    if args.cmd == "retry-plan":
        avail = args.available_gb if args.available_gb is not None else _available_gb()
        plan = memory_retry_plan(args.threads, args.memory_gb, avail, args.own_limit)
        print("none" if plan is None else f"{plan[0]} {plan[1]} {'-' if avail is None else '%.1f' % avail}")
        return 0
    wsl = _is_wsl()
    skip = os.environ.get("PLASBENCH_SKIP_DISK_CHECK") == "1"
    reserve = _env_gb("PLASBENCH_DISK_RESERVE_GB", RESERVE_GB)
    vmin = _env_gb("PLASBENCH_VDISK_MIN_GB", VDISK_FLOOR_GB)
    if args.cmd == "vdisk":
        if not wsl:
            print("Not running under WSL: there is no Ubuntu virtual disk to look at.")
            return 0
        v = wsl_vdisk()
        print(vdisk_evidence(v))
        for other in v.get("others") or []:
            print(f"  (another distribution, not measured: {other})")
        if v.get("command"):
            print(f"Check it yourself in Windows: {v['command']}")
        return 0 if v.get("free") is not None else 1
    if args.cmd == "guard":
        ok, lines = guard({"stage": args.stage, "sample": args.sample, "sra": args.sra, "results_dir": args.results_dir, "data_dir": args.data_dir,
                           "tmp_dir": args.tmp_dir, "in_flight": args.in_flight, "skip_disk": skip, "reserve_gb": reserve}, {"wsl": wsl})
        print("\n".join(lines))
        return 0 if ok else 3
    ctx = {"stage": args.stage, "results_dir": args.results_dir, "data_dir": args.data_dir, "tmp_dir": args.tmp_dir, "sheet": args.sheet,
           "sheet_rows": read_sheet(args.sheet) if args.sheet else [], "threads": args.threads, "memory_gb": args.memory_gb, "parallel": args.parallel,
           "cap_threads": not args.no_cap, "skip_disk": skip, "reserve_gb": reserve, "vdisk_min_gb": vmin}
    result = run_checks(ctx, {"wsl": wsl})
    if not (args.quiet_ok and result["level"] == "ok"):
        print("\n".join(render(result, args.stage)))
    if result["threads"]:
        print(f"@threads={result['threads']}")
    return 3 if result["level"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
