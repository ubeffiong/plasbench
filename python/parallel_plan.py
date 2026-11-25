#!/usr/bin/env python3
"""AUTO_PARALLEL: how many isolates a stage runs at the same time, sized to this computer.

With MAX_PARALLEL_SAMPLES=1 (the default) a stage runs one isolate at a time, and in the single-threaded steps most of a 6-CPU laptop sits idle (a real run: about 3 to 4
of 6 cores busy during reference annotation). With AUTO_PARALLEL=1 (the default) the stages whose isolates are independent and light run several isolates at once, and the
THREAD BUDGET IS DIVIDED between them, so the machine is never asked for more threads than it has:

  stage 2 (truth + reference annotation)  at least 3 threads and about 1.5 GB per isolate (estimated: ISEScan/HMMER, the k-mer table of repeat_content on a 9 Mbp genome)
  stage 5 (scoring)                       at least 2 threads and about 1 GB per isolate (estimated: minimap2 against one isolate's reference, the scorers)
  stage 3 (assembly)                      ONE isolate at a time unless the free memory holds two assemblies or more: each needs the largest need this run has learned
                                          (results/resource_profile.tsv) or ASSEMBLY_SLOT_GB (default 8), plus 15% and 0.5 GB, inside 85% of the free memory (the same
                                          rule as python/resource_adapt.py memory_plan); the memory budget is then divided between them
  stage 4 (the tools) is not changed: the tools differ too much in memory to share a machine safely by default (MAX_PARALLEL_TOOLS is the opt-in).

Explicit settings win: MAX_PARALLEL_SAMPLES (or --parallel-samples) set by you is used as is, and THREADS set by you is not divided. Results never depend on the plan: every
isolate writes its own files and every table is merged in the sample-sheet order (test/test_auto_parallel.sh proves a parallel run equals a sequential one byte for byte).

  python3 -I python/parallel_plan.py plan --stage 2 --cpus 6 --available-mb 7065 --isolates 5 [--slot-gb 8] [--profile results/resource_profile.tsv]
        -> slots<TAB>threads<TAB>memory_gb_per_slot<TAB>sentence
  python3 -I python/parallel_plan.py summary --cpus 6 --available-mb 7065 --isolates 5      the lines `plasbench run` prints at the start

Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import math
import sys

# per stage: (minimum threads per isolate, memory per isolate in GB, what the stage is called)
STAGES = {
    2: (3, 1.5, "truth and reference annotation"),
    3: (4, None, "assembly"),
    5: (2, 1.0, "scoring"),
}
DEFAULT_SLOT_GB = 8.0          # a bacterial SPAdes assembly on a typical read set; learned needs replace it


def learned_assembly_need(profile_path):
    """The largest needed_gb this run has learned for SPAdes (results/resource_profile.tsv), or None."""
    if not profile_path:
        return None
    try:
        with open(profile_path, encoding="utf-8") as handle:
            rows = [ln.rstrip("\n").split("\t") for ln in handle if ln.strip()]
    except OSError:
        return None
    if not rows:
        return None
    header, best = rows[0], None
    for row in rows[1:]:
        d = dict(zip(header, row))
        try:
            need = float(d.get("needed_gb") or 0)
        except ValueError:
            continue
        if need > 0 and (best is None or need > best):
            best = need
    return best


def plan(stage, cpus, available_mb, isolates, slot_gb=None, profile=None):
    """{'slots', 'threads', 'memory_gb', 'reason'} for one stage. Never more slots than isolates, CPUs allow or memory allows; never below 1."""
    cpus = max(1, int(cpus))
    isolates = max(1, int(isolates))
    avail_gb = max(0.0, float(available_mb) / 1024.0)
    if stage not in STAGES:
        return {"slots": 1, "threads": cpus, "memory_gb": None, "reason": "stage %s runs one isolate at a time" % stage}
    min_threads, per_gb, name = STAGES[stage]
    by_cpu = max(1, cpus // min_threads)
    if stage == 3:
        need = learned_assembly_need(profile) or float(slot_gb or DEFAULT_SLOT_GB)
        per_gb = math.ceil(need * 1.15 + 0.5)
    by_mem = max(1, int((avail_gb * 0.85) // per_gb)) if per_gb else isolates
    slots = max(1, min(isolates, by_cpu, by_mem))
    threads = max(1, cpus // slots)
    memory = None
    if stage == 3:
        memory = int(per_gb) if slots > 1 else None
    limits = []
    if slots == by_cpu and by_cpu < isolates:
        limits.append("%d CPUs at %d threads or more each" % (cpus, min_threads))
    if slots == by_mem and by_mem < isolates:
        limits.append("%.1f GB free at about %s GB each" % (avail_gb, ("%g" % per_gb)))
    if slots == isolates and isolates > 1:
        limits.append("every isolate at once")
    if slots == 1:
        why = ("one isolate at a time (%s)" % "; ".join(limits)) if limits else "one isolate at a time"
    else:
        why = "%d isolates at a time, %d threads each (%s)" % (slots, threads, "; ".join(limits) or "machine size")
    return {"slots": slots, "threads": threads, "memory_gb": memory, "reason": why, "name": name}


def summary(cpus, available_mb, isolates, slot_gb=None, profile=None):
    avail_gb = float(available_mb) / 1024.0
    lines = []
    for stage in (2, 3, 5):
        p = plan(stage, cpus, available_mb, isolates, slot_gb, profile)
        if p["slots"] > 1:
            lines.append("stage %d (%s): running %d isolates at a time: %d CPUs, %.1f GB free (%d threads each)" % (stage, p["name"], p["slots"], cpus, avail_gb, p["threads"]))
        else:
            lines.append("stage %d (%s): one isolate at a time, all %d CPUs" % (stage, p["name"], cpus)
                         + (" (one assembly needs most of the %.1f GB free)" % avail_gb if stage == 3 and isolates > 1 else ""))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "summary"):
        p = sub.add_parser(name)
        if name == "plan":
            p.add_argument("--stage", type=int, required=True)
        p.add_argument("--cpus", type=int, required=True)
        p.add_argument("--available-mb", type=float, required=True)
        p.add_argument("--isolates", type=int, required=True)
        p.add_argument("--slot-gb", type=float, default=None)
        p.add_argument("--profile", default="")
    args = ap.parse_args(argv)
    if args.cmd == "plan":
        p = plan(args.stage, args.cpus, args.available_mb, args.isolates, args.slot_gb, args.profile)
        print("\t".join((str(p["slots"]), str(p["threads"]), str(p["memory_gb"] or ""), p["reason"])))
        return 0
    for line in summary(args.cpus, args.available_mb, args.isolates, args.slot_gb, args.profile):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
