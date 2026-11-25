#!/usr/bin/env python3
"""python/parallel_plan.py: the AUTO_PARALLEL plan never oversubscribes, respects memory, keeps assembly at one isolate unless memory allows more, and reads a learned need."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import parallel_plan as pp  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


laptop = dict(cpus=6, available_mb=6.9 * 1024, isolates=5)
p2, p3, p5 = (pp.plan(s, **laptop) for s in (2, 3, 5))
check("the owner's laptop (6 CPUs, 6.9 GB): stage 2 runs 2 isolates x 3 threads", (p2["slots"], p2["threads"]) == (2, 3), p2)
check("... stage 5 runs 3 isolates x 2 threads", (p5["slots"], p5["threads"]) == (3, 2), p5)
check("... assembly stays at one isolate with all 6 CPUs (8 GB per assembly does not fit twice)", (p3["slots"], p3["threads"]) == (1, 6), p3)
for cpus in range(1, 33):
    for mb in (1024, 4096, 8192, 32768, 131072):
        for n in (1, 2, 5, 100):
            for stage in (2, 3, 4, 5):
                p = pp.plan(stage, cpus, mb, n)
                if p["slots"] * p["threads"] > max(cpus, p["threads"]) or p["slots"] < 1 or p["slots"] > n or p["threads"] < 1:
                    check("no oversubscription, never more slots than isolates (cpus=%d mb=%d n=%d stage=%d)" % (cpus, mb, n, stage), False, p)
check("no plan asks for more threads than CPUs, or more slots than isolates (6,400 cases)", ok)
check("one isolate: one slot, every CPU", pp.plan(2, 8, 16384, 1)["slots"] == 1 and pp.plan(2, 8, 16384, 1)["threads"] == 8)
check("memory limits stage 2 (2 GB free: one isolate at 1.5 GB each)", pp.plan(2, 16, 2048, 5)["slots"] == 1)
big = pp.plan(3, 16, 64 * 1024, 5)
check("a 16-CPU, 64 GB machine runs 4 assemblies x 4 threads with a 10 GB budget each", (big["slots"], big["threads"], big["memory_gb"]) == (4, 4, 10), big)
check("stage 4 is never changed by the plan", pp.plan(4, 16, 65536, 10)["slots"] == 1)
with tempfile.TemporaryDirectory() as tmp:
    prof = Path(tmp) / "resource_profile.tsv"
    with open(str(prof), "w") as handle:
        handle.write("tool\tsample\tneeded_gb\tbudget_gb\nspades\ta\t5.2\t7\nspades\tb\t20.0\t24\n")
    learned = pp.plan(3, 16, 64 * 1024, 5, profile=str(prof))
    check("a learned need of 20 GB (the largest of the run) allows 2 assemblies on 64 GB", learned["slots"] == 2 and learned["memory_gb"] == 24, learned)
    check("a missing profile falls back to ASSEMBLY_SLOT_GB", pp.learned_assembly_need(os.path.join(tmp, "none.tsv")) is None)
lines = pp.summary(6, 6.9 * 1024, 5)
check("the run start says 'running 2 isolates at a time: 6 CPUs, 6.9 GB free'", any("running 2 isolates at a time: 6 CPUs, 6.9 GB free" in ln for ln in lines), lines)
print("ALL PARALLEL PLAN TESTS PASSED" if ok else "PARALLEL PLAN TESTS FAILED")
sys.exit(0 if ok else 1)
