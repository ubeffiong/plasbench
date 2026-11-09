#!/usr/bin/env python3
"""resampling.py -- exact means, cluster bootstrap and sign-flip permutation tests.

The single home of PlasBench's resampling primitives. aggregate_results.py and
headline_design.py both import from here (they used to import from each other).

Exactness
---------
Every mean here is bit-identical to statistics.mean: the exact rational sum of the
values, rounded once to the nearest double. Earlier versions built that sum from
fractions.Fraction objects, which dominated stage 6 (78% of aggregation time in
the performance audit). The same value is now computed from integers:

* every finite double is n / 2**k exactly (float.as_integer_ratio);
* scaled to the largest power-of-two denominator D in the data, a set of values
  sums exactly to an integer N over D;
* N / (D * count) is Python int / int true division, which is correctly rounded.

A resampled mean is a sum over whole clusters, so each cluster's integer sum is
computed once and every bootstrap draw or sign flip only adds integers. The random
stream is consumed in exactly the order the earlier code used, so every interval
and p-value is unchanged (test/test_resampling_equivalence.py checks this against
the earlier implementations).

Standard library only.
"""

import math
import random
import statistics
from collections import defaultdict


# -- exact means ---------------------------------------------------------------------

def _finite(values):
    return all(math.isfinite(v) for v in values)


def _common_denominator(values):
    """Largest power-of-two denominator among the values (a common multiple of all)."""
    return max((v.as_integer_ratio()[1] for v in values), default=1)


def _scaled(value, denominator):
    numerator, own = value.as_integer_ratio()
    return numerator * (denominator // own)


def exact_mean(values):
    """Bit-identical to statistics.mean(values) for finite floats, without Fraction objects.

    Non-finite input keeps statistics.mean's own behaviour (inf/nan propagation);
    an empty input raises statistics.StatisticsError exactly as before.
    """
    values = list(values)
    if not values or not _finite(values):
        return statistics.mean(values)
    total = math.fsum(values)
    if math.fsum(values + [-total]) == 0.0:
        return total / len(values)          # the sum is an exact double: one rounding
    denominator = _common_denominator(values)
    return sum(_scaled(v, denominator) for v in values) / (denominator * len(values))


def macro_mean(values, strata):
    """Mean of per-stratum means (plain mean when strata is None)."""
    if strata is None:
        return exact_mean(values)
    by = defaultdict(list)
    for value, stratum in zip(values, strata):
        by[stratum].append(value)
    return exact_mean([exact_mean(v) for v in by.values()])


# -- resampling units ----------------------------------------------------------------

def resampling_units(values, groups=None):
    """Group values into independent resampling units (clusters).

    Without groups every value is its own unit, which reproduces plain
    per-sample resampling exactly (same RNG draws, same results).
    """
    if groups is None:
        return [[value] for value in values]
    if len(groups) != len(values):
        raise ValueError("groups must align one-to-one with values")
    units = {}
    for value, group in zip(values, groups):
        units.setdefault(group, []).append(value)
    return list(units.values())


def _unit_sums(units, denominator):
    """[(exact integer sum over `denominator`, count)] per unit."""
    return [(sum(_scaled(v, denominator) for v in unit), len(unit)) for unit in units]


def _flip_bit(getrandbits):
    """One fair bit, drawn exactly as rng.randrange(2) draws it (2 bits, reject >= 2)."""
    bits = getrandbits(2)
    while bits >= 2:
        bits = getrandbits(2)
    return bits


# -- bootstrap -----------------------------------------------------------------------

def bootstrap_ci(values, iterations=1000, groups=None):
    """Deterministic percentile CI for the mean; descriptive, not a p-value.

    With groups, whole clusters are resampled (cluster bootstrap), so
    correlated isolates from one study widen the interval instead of
    narrowing it. At least 5 independent units are required.
    """
    units = resampling_units(values, groups)
    # Intervals from very small cohorts imply a precision the data do not have.
    if len(values) < 5 or len(units) < 5:
        return None, None
    rng = random.Random(20260831)
    if not _finite(values):
        means = sorted(exact_mean([value for unit in rng.choices(units, k=len(units)) for value in unit])
                       for _ in range(iterations))
    else:
        denominator = _common_denominator(values)
        sums = _unit_sums(units, denominator)
        means = []
        for _ in range(iterations):
            drawn = rng.choices(sums, k=len(sums))
            means.append(sum(s for s, _ in drawn) / (denominator * sum(n for _, n in drawn)))
        means.sort()
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def stratified_bootstrap(values, groups, strata, iterations=1000):
    """Percentile CI of macro_mean, resampling clusters within each stratum.

    With strata None this is exactly bootstrap_ci(values, groups=groups) -- same
    units, same RNG draws.
    """
    if strata is None:
        return bootstrap_ci(values, iterations=iterations, groups=groups)
    by_stratum = defaultdict(lambda: ([], []))
    for value, group, stratum in zip(values, groups, strata):
        by_stratum[stratum][0].append(value)
        by_stratum[stratum][1].append(group)
    units = {s: resampling_units(v, g) for s, (v, g) in by_stratum.items()}
    if len(values) < 5 or sum(len(u) for u in units.values()) < 5:
        return None, None
    rng = random.Random(20260831)
    order = sorted(units)
    if not _finite(values):
        means = []
        for _ in range(iterations):
            stratum_means = []
            for stratum in order:
                drawn = rng.choices(units[stratum], k=len(units[stratum]))
                stratum_means.append(exact_mean([v for unit in drawn for v in unit]))
            means.append(exact_mean(stratum_means))
    else:
        denominator = _common_denominator(values)
        sums = {s: _unit_sums(units[s], denominator) for s in order}
        means = []
        for _ in range(iterations):
            stratum_means = []
            for stratum in order:
                drawn = rng.choices(sums[stratum], k=len(sums[stratum]))
                stratum_means.append(sum(s for s, _ in drawn) / (denominator * sum(n for _, n in drawn)))
            means.append(exact_mean(stratum_means))
    means.sort()
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def ratio_bootstrap(pairs, groups, iterations=1000):
    """Percentile CI of sum(correct)/sum(total), resampling clusters."""
    units = resampling_units(pairs, groups)
    if len(pairs) < 5 or len(units) < 5:
        return None, None
    rng = random.Random(20260902)
    ratios = []
    for _ in range(iterations):
        drawn = [p for unit in rng.choices(units, k=len(units)) for p in unit]
        total = sum(t for _, t in drawn)
        ratios.append(sum(c for c, _ in drawn) / total if total else 0.0)
    ratios.sort()
    return ratios[int(0.025 * iterations)], ratios[int(0.975 * iterations) - 1]


# -- sign-flip permutation tests -------------------------------------------------------

def paired_permutation_pvalue(differences, iterations=10000, groups=None):
    """Two-sided sign-flip permutation p-value for paired mean differences.

    With groups, every difference in a cluster is flipped together, which is
    the valid null when isolates within a study are correlated. At least 5
    independent units are required.
    """
    units = resampling_units(differences, groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(exact_mean(differences))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    extreme = 0
    if not _finite(differences):
        pairs = [(unit, [-item for item in unit]) for unit in units]
        for _ in range(iterations):
            signed = []
            for unit, flipped in pairs:
                signed.extend(unit if _flip_bit(getrandbits) else flipped)
            extreme += abs(exact_mean(signed)) >= observed
        return (extreme + 1) / (iterations + 1)
    denominator = _common_denominator(differences)
    sums = [s for s, _ in _unit_sums(units, denominator)]
    scale = denominator * len(differences)
    for _ in range(iterations):
        total = 0
        for s in sums:
            # One fair bit, drawn exactly as rng.randrange(2) draws it (2 bits, reject >= 2);
            # inline, because a function call per draw costs more than the draw itself.
            bits = getrandbits(2)
            while bits >= 2:
                bits = getrandbits(2)
            total += s if bits else -s
        extreme += abs(total / scale) >= observed
    return (extreme + 1) / (iterations + 1)


def stratified_permutation(differences, groups, strata, iterations=10000):
    """Sign-flip p-value for macro_mean(differences), flipping whole clusters."""
    if strata is None:
        return paired_permutation_pvalue(differences, iterations=iterations, groups=groups)
    units = resampling_units(list(zip(differences, strata)), groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(macro_mean(differences, strata))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    extreme = 0
    if not _finite(differences):
        labelled = [([value for value, _ in unit], [-value for value, _ in unit], [stratum for _, stratum in unit])
                    for unit in units]
        for _ in range(iterations):
            values, labels = [], []
            for positive, negative, unit_strata in labelled:
                values.extend(positive if _flip_bit(getrandbits) else negative)
                labels.extend(unit_strata)
            extreme += abs(macro_mean(values, labels)) >= observed
        return (extreme + 1) / (iterations + 1)
    denominator = _common_denominator(differences)
    # Strata in first-appearance order over the units, as macro_mean groups them.
    index = {}
    for unit in units:
        for _, stratum in unit:
            index.setdefault(stratum, len(index))
    counts = [0] * len(index)
    parts = []                                   # per unit: [(stratum index, exact integer sum)]
    for unit in units:
        by = {}
        for value, stratum in unit:
            k = index[stratum]
            by[k] = by.get(k, 0) + _scaled(value, denominator)
            counts[k] += 1
        parts.append(list(by.items()))
    scales = [denominator * n for n in counts]
    for _ in range(iterations):
        totals = [0] * len(index)
        for unit_parts in parts:
            bits = getrandbits(2)                # inline fair bit, as in paired_permutation_pvalue
            while bits >= 2:
                bits = getrandbits(2)
            if bits:
                for k, s in unit_parts:
                    totals[k] += s
            else:
                for k, s in unit_parts:
                    totals[k] -= s
        extreme += abs(exact_mean([totals[k] / scales[k] for k in range(len(totals))])) >= observed
    return (extreme + 1) / (iterations + 1)
