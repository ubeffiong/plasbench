#!/usr/bin/env python3
"""resampling.stratified_bootstrap_t_ci: the studentised cluster bootstrap for a species-balanced (stratified) macro mean."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
import resampling as rs  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def draw(rng, per_stratum, means=(0.3, 0.7)):
    values, groups, strata = [], [], []
    for s, base in enumerate(means):
        for c in range(per_stratum):
            eff = min(1, max(0, rng.gauss(base, 0.1)))
            for _ in range(rng.choice([1, 2, 3])):
                values.append(min(1, max(0, rng.gauss(eff, 0.05))))
                groups.append(f"s{s}c{c}")
                strata.append(f"sp{s}")
    return values, groups, strata


rng = random.Random(5)
v, g, s = draw(rng, 8)
lo, hi = rs.stratified_bootstrap_t_ci(v, g, s, iterations=500)
mean, _, _ = rs._stratified_cr1(v, g, s)
check("an interval is returned and contains the macro mean", lo is not None and lo < mean < hi, (lo, hi, mean))
check("it is deterministic", rs.stratified_bootstrap_t_ci(v, g, s, iterations=500) == (lo, hi))
check("a stratum with a single cluster gives no interval, not a wrong one", rs.stratified_bootstrap_t_ci([0.1, 0.2, 0.3], ["a", "b", "c"], ["x", "y", "y"]) == (None, None))
check("fewer than the minimum clusters gives no interval", rs.stratified_bootstrap_t_ci([0.1, 0.2, 0.3, 0.4], ["a", "b", "c", "d"], ["x", "x", "y", "y"]) == (None, None))
check("a NaN gives no interval", rs.stratified_bootstrap_t_ci([float("nan")] + v[1:], g, s)[0] is None)
check("interval(method='bootstrap_t') with strata uses it instead of falling back to cluster_t", rs.interval(v, g, s, method="bootstrap_t", iterations=500) == (lo, hi))
check("it differs from the cluster-t interval (a real second method)", rs.interval(v, g, s, method="cluster_t") != (lo, hi))

# a small coverage check on data with a known macro mean (0.5): smoke only, wide tolerance
hits = total = 0
for _ in range(120):
    vv, gg, ss = draw(rng, 6)
    low, high = rs.stratified_bootstrap_t_ci(vv, gg, ss, iterations=200)
    if low is not None:
        total += 1
        hits += low <= 0.5 <= high
coverage = hits / total
check(f"coverage of the true macro mean is near nominal on well-behaved data ({coverage:.2f} over {total}; smoke check, not the validation)", coverage >= 0.85, coverage)

print("ALL STRATIFIED BOOTSTRAP-T TESTS PASSED" if ok else "STRATIFIED BOOTSTRAP-T TESTS FAILED")
sys.exit(0 if ok else 1)
