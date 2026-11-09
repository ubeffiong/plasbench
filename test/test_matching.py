#!/usr/bin/env python3
"""python/matching.py against the earlier square Hungarian (score_bins.maximum_weight, v0.2.8).

* The total matched weight is always identical (both are optimal).
* Where the optimum is unique (checked by brute force on small instances), the
  matched pairs are identical too.
* Bin-heavy instances finish in well under a second (the square solver took
  seconds at 200 x 20; see docs/PERFORMANCE_AUDIT.md).
"""

import itertools
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from matching import max_weight_matching  # noqa: E402


def ref_maximum_weight(edges, bins_list, plasmids_list):
    """Verbatim logic of the pre-optimisation score_bins.maximum_weight."""
    n = max(len(bins_list), len(plasmids_list))
    if not n:
        return []
    high = max(edges.values(), default=0)
    cost = [[high] * n for _ in range(n)]
    for i, bin_id in enumerate(bins_list):
        for j, plasmid in enumerate(plasmids_list):
            cost[i][j] = high - edges.get((bin_id, plasmid), 0)
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0, minv, used = i, 0, [float("inf")] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, n + 1):
                if not used[j]:
                    current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minv[j]: minv[j], way[j] = current, j0
                    if minv[j] < delta: delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if not p[j0]: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if not j0: break
    matched = []
    for j in range(1, n + 1):
        i = p[j]
        if i and i <= len(bins_list) and j <= len(plasmids_list):
            key = (bins_list[i - 1], plasmids_list[j - 1])
            if edges.get(key, 0) > 0: matched.append((key[0], key[1], edges[key]))
    return matched


def optimum_is_unique(edges, bins, plasmids):
    """Brute force: exactly one set of positive pairs reaches the maximum weight."""
    best, count = -1, 0
    seen = set()
    small, large, flip = (bins, plasmids, False) if len(bins) <= len(plasmids) else (plasmids, bins, True)
    for perm in itertools.permutations(range(len(large)), len(small)):
        pairs = frozenset((large[j], a) if flip else (a, large[j]) for a, j in zip(small, perm)
                          if edges.get((large[j], a) if flip else (a, large[j]), 0) > 0)
        if pairs in seen:
            continue
        seen.add(pairs)
        total = sum(edges[k] for k in pairs)
        if total > best:
            best, count = total, 1
        elif total == best:
            count += 1
    return count == 1


def instance(rng, n_bins, n_plasmids, tie_prone):
    bins = [f"b{i:03d}" for i in range(n_bins)]
    plasmids = [f"p{j:03d}" for j in range(n_plasmids)]
    edges = {}
    for b in bins:
        for p in rng.sample(plasmids, min(len(plasmids), rng.choice([0, 1, 1, 2, 3]))):
            edges[(b, p)] = rng.choice([100, 200, 300]) if tie_prone else rng.randint(1, 10 ** 6)
    return edges, bins, plasmids


def main():
    rng = random.Random(42)
    unique_checked = ties = 0
    for trial in range(1500):
        edges, bins, plasmids = instance(rng, rng.randint(0, 6), rng.randint(0, 6), trial % 3 == 0)
        old = ref_maximum_weight(edges, bins, plasmids)
        new = max_weight_matching(edges, bins, plasmids)
        assert sum(w for *_, w in old) == sum(w for *_, w in new), (edges, old, new)
        if optimum_is_unique(edges, bins, plasmids):
            assert old == new, (edges, old, new)          # same pairs, same order
            unique_checked += 1
        elif sorted(old) != sorted(new):
            ties += 1
    # Larger instances: weights still equal (pairs compared only for weight).
    for trial in range(30):
        edges, bins, plasmids = instance(rng, rng.randint(20, 60), rng.randint(3, 15), False)
        old, new = ref_maximum_weight(edges, bins, plasmids), max_weight_matching(edges, bins, plasmids)
        assert sum(w for *_, w in old) == sum(w for *_, w in new)
    # Bin-heavy: one bin per contig against a few plasmids.
    edges, bins, plasmids = instance(random.Random(7), 400, 20, False)
    start = time.perf_counter()
    max_weight_matching(edges, bins, plasmids)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"400 x 20 matching took {elapsed:.2f}s"
    print(f"test_matching: {unique_checked} unique-optimum instances identical; "
          f"{ties} tied instances with equal weight; 400x20 in {elapsed:.3f}s")


if __name__ == "__main__":
    main()
