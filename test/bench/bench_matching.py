"""Time python/matching.py against the earlier square Hungarian at increasing bin counts.

usage: python test/bench/bench_matching.py
"""
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "python"))
sys.path.insert(0, os.path.join(HERE, ".."))
from matching import max_weight_matching  # noqa: E402
from test_matching import ref_maximum_weight  # noqa: E402


def workload(n_bins, n_plasmids, seed=1):
    rng = random.Random(seed)
    bins = [f"b{i}" for i in range(n_bins)]
    plasmids = [f"p{j}" for j in range(n_plasmids)]
    edges = {}
    for b in bins:
        for p in rng.sample(plasmids, 1 if rng.random() < 0.85 else 2):
            edges[(b, p)] = rng.randint(100, 100000)
    return edges, bins, plasmids


print("n_bins\tn_plasmids\tsquare_s\trectangular_s\tspeedup\tsame_weight")
for n_bins, n_pl in [(10, 5), (50, 10), (100, 10), (200, 20), (300, 30)]:
    edges, bins, plasmids = workload(n_bins, n_pl)
    t0 = time.perf_counter(); a = ref_maximum_weight(edges, bins, plasmids)
    t1 = time.perf_counter(); b = max_weight_matching(edges, bins, plasmids)
    t2 = time.perf_counter()
    same = sum(x[2] for x in a) == sum(x[2] for x in b)
    print(f"{n_bins}\t{n_pl}\t{t1 - t0:.3f}\t{t2 - t1:.4f}\t{(t1 - t0) / max(t2 - t1, 1e-9):.0f}x\t{same}", flush=True)
