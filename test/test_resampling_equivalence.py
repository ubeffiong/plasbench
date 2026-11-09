#!/usr/bin/env python3
"""python/resampling.py must reproduce the earlier Fraction-based statistics exactly.

The reference functions below are verbatim copies of the implementations that
resampling.py replaced (headline_design.exact_mean / macro_mean /
stratified_bootstrap / stratified_permutation and aggregate_results.bootstrap_ci /
paired_permutation_pvalue as of v0.2.8). Every interval and p-value must be
bit-identical, including on tie-heavy and cancellation-heavy inputs.
"""

import math
import os
import random
import statistics
import sys
from collections import defaultdict
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
import resampling  # noqa: E402


# -- reference implementations (pre-optimisation, verbatim logic) ---------------------

def ref_exact_mean(values):
    values = list(values)
    if not values:
        return statistics.mean(values)
    total = math.fsum(values)
    if not math.isfinite(total):
        return statistics.mean(values)
    terms = [total]
    while True:
        remainder = math.fsum(values + [-term for term in terms])
        if remainder == 0.0:
            break
        terms.append(remainder)
        if len(terms) > 8:
            return statistics.mean(values)
    return float(sum(map(Fraction, terms)) / len(values))


def ref_macro_mean(values, strata):
    if strata is None:
        return ref_exact_mean(values)
    by = defaultdict(list)
    for value, stratum in zip(values, strata):
        by[stratum].append(value)
    return ref_exact_mean([ref_exact_mean(v) for v in by.values()])


def ref_bootstrap_ci(values, iterations=1000, groups=None):
    units = resampling.resampling_units(values, groups)
    if len(values) < 5 or len(units) < 5:
        return None, None
    rng = random.Random(20260831)
    means = sorted(ref_exact_mean([value for unit in rng.choices(units, k=len(units)) for value in unit])
                   for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def ref_paired_permutation_pvalue(differences, iterations=10000, groups=None):
    units = resampling.resampling_units(differences, groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(ref_exact_mean(differences))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    pairs = list(zip(units, [[-item for item in unit] for unit in units]))
    extreme = 0
    for _ in range(iterations):
        signed = []
        for unit, flipped in pairs:
            bits = getrandbits(2)
            while bits >= 2:
                bits = getrandbits(2)
            signed.extend(unit if bits else flipped)
        extreme += abs(ref_exact_mean(signed)) >= observed
    return (extreme + 1) / (iterations + 1)


def ref_stratified_bootstrap(values, groups, strata, iterations=1000):
    if strata is None:
        return ref_bootstrap_ci(values, iterations=iterations, groups=groups)
    by_stratum = defaultdict(lambda: ([], []))
    for value, group, stratum in zip(values, groups, strata):
        by_stratum[stratum][0].append(value)
        by_stratum[stratum][1].append(group)
    units = {s: resampling.resampling_units(v, g) for s, (v, g) in by_stratum.items()}
    if len(values) < 5 or sum(len(u) for u in units.values()) < 5:
        return None, None
    rng = random.Random(20260831)
    order = sorted(units)
    means = []
    for _ in range(iterations):
        stratum_means = []
        for stratum in order:
            drawn = rng.choices(units[stratum], k=len(units[stratum]))
            stratum_means.append(ref_exact_mean([v for unit in drawn for v in unit]))
        means.append(ref_exact_mean(stratum_means))
    means.sort()
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def ref_stratified_permutation(differences, groups, strata, iterations=10000):
    if strata is None:
        return ref_paired_permutation_pvalue(differences, iterations=iterations, groups=groups)
    units = resampling.resampling_units(list(zip(differences, strata)), groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(ref_macro_mean(differences, strata))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    labelled = [([v for v, _ in unit], [-v for v, _ in unit], [s for _, s in unit]) for unit in units]
    extreme = 0
    for _ in range(iterations):
        values, labels = [], []
        for positive, negative, unit_strata in labelled:
            bits = getrandbits(2)
            while bits >= 2:
                bits = getrandbits(2)
            values.extend(positive if bits else negative)
            labels.extend(unit_strata)
        extreme += abs(ref_macro_mean(values, labels)) >= observed
    return (extreme + 1) / (iterations + 1)


# -- generators -----------------------------------------------------------------------

def sample_values(rng, n):
    kind = rng.random()
    if kind < 0.3:
        return [rng.random() for _ in range(n)]                                  # F1-like
    if kind < 0.55:
        return [rng.choice([0.0, 0.1, -0.1, 0.25, -0.25, 1 / 3, -1 / 3]) for _ in range(n)]  # ties
    if kind < 0.7:
        return [rng.choice([1e16, -1e16, 1.0, 1e-8, -3.0]) * rng.random() for _ in range(n)]  # cancellation
    return [round(rng.uniform(-1, 1), 4) for _ in range(n)]                       # read back from TSV


def main():
    rng = random.Random(2026)
    checked = 0
    for _ in range(20000):
        values = sample_values(rng, rng.randint(1, 40))
        assert resampling.exact_mean(values) == ref_exact_mean(values), values
        checked += 1
    assert math.isnan(resampling.exact_mean([1.0, float("nan")]))
    assert resampling.exact_mean([1.0, float("inf")]) == float("inf")
    try:
        resampling.exact_mean([])
        raise AssertionError("empty input must raise")
    except statistics.StatisticsError:
        pass

    for case in range(16):
        n = rng.choice([5, 12, 30, 60])
        values = sample_values(rng, n)
        groups = [f"g{i // rng.choice([1, 2, 3])}" for i in range(n)] if case % 2 else None
        strata = [("E", "K", "A")[i % 3] for i in range(n)] if case % 4 >= 2 else None
        g = groups or [f"s{i}" for i in range(n)]
        iters = 400
        assert resampling.bootstrap_ci(values, iterations=iters, groups=groups) == \
            ref_bootstrap_ci(values, iterations=iters, groups=groups), case
        assert resampling.paired_permutation_pvalue(values, iterations=iters, groups=groups) == \
            ref_paired_permutation_pvalue(values, iterations=iters, groups=groups), case
        assert resampling.stratified_bootstrap(values, g, strata, iterations=iters) == \
            ref_stratified_bootstrap(values, g, strata, iterations=iters), case
        assert resampling.stratified_permutation(values, g, strata, iterations=iters) == \
            ref_stratified_permutation(values, g, strata, iterations=iters), case
        assert resampling.macro_mean(values, strata) == ref_macro_mean(values, strata), case
    # Full-size runs: the production iteration counts cross many block refills of the
    # bulk word stream, so stream boundaries are exercised, not just the first block.
    values = [round(rng.gauss(0.02, 0.1), 4) for _ in range(150)]
    groups = [f"g{i // 2}" for i in range(150)]
    strata = [("E", "K", "A")[i % 3] for i in range(150)]
    assert resampling.paired_permutation_pvalue(values, groups=groups) == \
        ref_paired_permutation_pvalue(values, groups=groups)
    assert resampling.stratified_permutation(values, groups, strata) == \
        ref_stratified_permutation(values, groups, strata)
    assert resampling.stratified_bootstrap(values, groups, strata) == \
        ref_stratified_bootstrap(values, groups, strata)
    assert resampling.bootstrap_ci(values, groups=groups) == ref_bootstrap_ci(values, groups=groups)
    print(f"test_resampling_equivalence: {checked} means, 16 resampling designs and 4 full-size runs identical")


if __name__ == "__main__":
    main()
