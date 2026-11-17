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

Independent units and exact tests
---------------------------------
The number of independent units (clusters: isolates from one study count once) limits what can be claimed, so the thresholds are named, not buried:

  MIN_CLUSTERS_CI    5   a bootstrap interval needs at least this many independent units
  MIN_CLUSTERS_TEST  6   a sign-flip permutation test needs at least this many: with n units there are 2**n sign patterns, so the smallest two-sided p-value
                         is 2 / 2**n; with 5 units that is 0.0625, which can never reach 0.05, so no test is reported for 5 or fewer
  EXACT_MAX_UNITS    12  up to this many units the test enumerates every sign pattern (an exact p-value, no random numbers); above it, the Monte Carlo estimate
                         is used, drawn exactly as before (the random stream is unchanged)

permutation_method(n_units) says which applies and permutation_floor(n_units) gives the smallest attainable p-value, so a report can say "exact" or "Monte Carlo"
and flag a comparison as underpowered when that floor is above 0.05.

Standard library only.
"""

import math
import random
import statistics
from collections import defaultdict


MIN_CLUSTERS_CI = 5
MIN_CLUSTERS_TEST = 6
EXACT_MAX_UNITS = 12
PERMUTATION_ITERATIONS = 10000


def permutation_method(n_units):
    """'not_estimated' below MIN_CLUSTERS_TEST units, 'exact' up to EXACT_MAX_UNITS, else 'monte_carlo'."""
    if n_units < MIN_CLUSTERS_TEST:
        return "not_estimated"
    return "exact" if n_units <= EXACT_MAX_UNITS else "monte_carlo"


def permutation_floor(n_units, iterations=PERMUTATION_ITERATIONS):
    """The smallest two-sided p-value a sign-flip test on n_units independent units can report (None for no units)."""
    if n_units < 1:
        return None
    exact = min(1.0, 2.0 / (2 ** n_units))
    if n_units <= EXACT_MAX_UNITS:
        return exact
    return max(exact, 1.0 / (iterations + 1))


def _exact_paired_pvalue(units, differences):
    """Exact two-sided sign-flip p-value: every sign pattern of the whole units, integer arithmetic, no random numbers."""
    denominator = _common_denominator(differences)
    sums = [s for s, _ in _unit_sums(units, denominator)]
    observed = abs(sum(sums))
    n = len(sums)
    extreme = 0
    for mask in range(1 << n):
        total = 0
        for i in range(n):
            total += sums[i] if (mask >> i) & 1 else -sums[i]
        extreme += abs(total) >= observed
    return extreme / (1 << n)


# -- exact means ---------------------------------------------------------------------

def _has_nan(values):
    """True when any value is NaN. A NaN is 'not measured': no interval or p-value can be made from it (an unguarded NaN made `abs(x) >= nan` false for every
    permutation, which reported a p-value of about 1e-4 for data that has no result). An infinite value keeps its documented behaviour."""
    return any(v != v for v in values)


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
    narrowing it. At least MIN_CLUSTERS_CI (5) independent units are required.
    """
    units = resampling_units(values, groups)
    # Intervals from very small cohorts imply a precision the data do not have.
    if len(values) < MIN_CLUSTERS_CI or len(units) < MIN_CLUSTERS_CI or _has_nan(values):
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
    if len(values) < MIN_CLUSTERS_CI or sum(len(u) for u in units.values()) < MIN_CLUSTERS_CI or _has_nan(values):
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
    if len(pairs) < MIN_CLUSTERS_CI or len(units) < MIN_CLUSTERS_CI or _has_nan([v for pair in pairs for v in pair]):
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
    the valid null when isolates within a study are correlated. At least
    MIN_CLUSTERS_TEST (6) independent units are required (with 5 the smallest
    attainable two-sided p is 0.0625). Up to EXACT_MAX_UNITS units every sign
    pattern is enumerated (an exact p-value); above it the Monte Carlo estimate
    below is used, with its random stream unchanged.
    """
    units = resampling_units(differences, groups)
    if len(differences) < MIN_CLUSTERS_TEST or len(units) < MIN_CLUSTERS_TEST or _has_nan(differences):
        return None
    if len(units) <= EXACT_MAX_UNITS and _finite(differences):
        return _exact_paired_pvalue(units, differences)
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
    if len(differences) < MIN_CLUSTERS_TEST or len(units) < MIN_CLUSTERS_TEST or _has_nan(differences):
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
    if len(units) <= EXACT_MAX_UNITS:            # every sign pattern of the whole units: an exact p-value
        n_units = len(parts)
        for mask in range(1 << n_units):
            totals = [0] * len(index)
            for i, unit_parts in enumerate(parts):
                sign = 1 if (mask >> i) & 1 else -1
                for k, s_ in unit_parts:
                    totals[k] += sign * s_
            extreme += abs(exact_mean([totals[k] / scales[k] for k in range(len(totals))])) >= observed
        return extreme / (1 << n_units)
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


# -- small-cluster interval methods (second review, issues 1 and 5A) ----------------------------------
#
# The percentile cluster bootstrap above under-covers with few independent clusters (python/simulate_validation.py measured
# roughly 0.85-0.94 for a nominal 95%). More iterations do not fix that: they only shrink Monte Carlo error. Two alternatives
# are implemented here and compared with it by simulation; the leaderboard's interval method is the one the simulation supports
# (INTERVAL_METHOD, set by PLASBENCH_CI_METHOD):
#
#   percentile    the cluster percentile bootstrap above (bootstrap_ci / stratified_bootstrap), kept for comparison and old runs
#   cluster_t     a cluster-robust (CR1) standard error of the mean with the small-sample factor G/(G-1) and a Student t critical
#                 value on G-1 degrees of freedom (stratified: the macro mean's variance is the sum of the strata variances over
#                 S**2, on sum(G_s - 1) degrees of freedom). Deterministic, no random numbers.
#   bootstrap_t   the studentized cluster bootstrap: resample clusters, studentize each replicate with its own CR1 standard error,
#                 and invert the quantiles of t*. Second-order accurate in principle; can be unstable with very few clusters.
#
# The sign-flip permutation test is already the wild cluster (Rademacher) bootstrap test under the null, with the exact
# enumeration below EXACT_MAX_UNITS, so the testing side needs no separate wild-bootstrap implementation.

INTERVAL_METHODS = ("percentile", "cluster_t", "bootstrap_t")


def _betacf(a, b, x):
    """Continued fraction for the regularized incomplete beta function (Lentz's method)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    """Student t cumulative distribution function."""
    x = df / (df + t * t)
    tail = 0.5 * _betai(df / 2.0, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p, df):
    """Student t quantile by bisection on t_cdf (accurate to ~1e-10)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    low, high = -1e3, 1e3
    for _ in range(200):
        mid = (low + high) / 2.0
        if t_cdf(mid, df) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _cr1(units):
    """(mean, CR1 standard error, clusters) of the pooled mean over cluster units (lists of values)."""
    n = sum(len(u) for u in units)
    g = len(units)
    mean = sum(sum(u) for u in units) / n
    residuals = [sum(v - mean for v in u) for u in units]
    variance = (g / (g - 1)) * sum(r * r for r in residuals) / (n * n)
    return mean, math.sqrt(variance), g


def _stratified_cr1(values, groups, strata):
    """(macro mean, standard error, degrees of freedom) with CR1 within each stratum."""
    by_stratum = defaultdict(lambda: ([], []))
    for value, group, stratum in zip(values, groups, strata):
        by_stratum[stratum][0].append(value)
        by_stratum[stratum][1].append(group)
    means, variance, df = [], 0.0, 0
    for stratum in sorted(by_stratum):
        units = resampling_units(*by_stratum[stratum])
        if len(units) < 2:
            return None
        mean, se, g = _cr1(units)
        means.append(mean)
        variance += se * se
        df += g - 1
    s = len(means)
    return sum(means) / s, math.sqrt(variance) / s, df


def cluster_t_ci(values, groups=None, strata=None, level=0.95):
    """Cluster-robust t interval for the (macro) mean; (None, None) below MIN_CLUSTERS_CI units."""
    units = resampling_units(values, groups)
    if len(values) < MIN_CLUSTERS_CI or len(units) < MIN_CLUSTERS_CI or _has_nan(values) or not _finite(values):
        return None, None
    if strata is None:
        mean, se, g = _cr1(units)
        df = g - 1
    else:
        result = _stratified_cr1(values, groups if groups is not None else list(range(len(values))), strata)
        if result is None:
            return None, None
        mean, se, df = result
    q = t_quantile(0.5 + level / 2.0, max(1, df))
    return mean - q * se, mean + q * se


def bootstrap_t_ci(values, groups=None, iterations=1000, level=0.95):
    """Studentized cluster bootstrap interval for the pooled mean; (None, None) below MIN_CLUSTERS_CI units."""
    units = resampling_units(values, groups)
    if len(values) < MIN_CLUSTERS_CI or len(units) < MIN_CLUSTERS_CI or _has_nan(values) or not _finite(values):
        return None, None
    mean, se, _ = _cr1(units)
    if se == 0:
        return mean, mean
    rng = random.Random(20261115)
    stats = []
    for _ in range(iterations):
        drawn = rng.choices(units, k=len(units))
        m, s, _ = _cr1(drawn)
        if s > 0:
            stats.append((m - mean) / s)
    if len(stats) < iterations // 2:
        return None, None
    stats.sort()
    alpha = (1.0 - level) / 2.0
    low_q = stats[int(alpha * len(stats))]
    high_q = stats[int((1.0 - alpha) * len(stats)) - 1]
    return mean - high_q * se, mean - low_q * se


def stratified_bootstrap_t_ci(values, groups, strata, iterations=1000, level=0.95):
    """Studentized cluster bootstrap interval for the macro mean (the mean of per-stratum means); (None, None) when a stratum has fewer than two clusters.

    Clusters are resampled within each stratum, the macro mean and its CR1 standard error are recomputed on every draw, and the interval is built from the
    distribution of (draw mean - mean) / draw standard error, as bootstrap_t_ci does for one stratum. Until this existed, bootstrap_t fell back to cluster_t
    whenever the ranking was species-balanced, which is the headline's usual form.
    """
    if _has_nan(values) or not _finite(values):
        return None, None
    by_stratum = defaultdict(lambda: ([], []))
    for value, group, stratum in zip(values, groups if groups is not None else list(range(len(values))), strata):
        by_stratum[stratum][0].append(value)
        by_stratum[stratum][1].append(group)
    sets = [resampling_units(*by_stratum[s]) for s in sorted(by_stratum)]
    if not sets or any(len(units) < 2 for units in sets) or sum(len(units) for units in sets) < MIN_CLUSTERS_CI:
        return None, None

    def macro(unit_sets):
        means, variance = [], 0.0
        for units in unit_sets:
            mean, se, _ = _cr1(units)
            means.append(mean)
            variance += se * se
        s = len(means)
        return sum(means) / s, math.sqrt(variance) / s

    mean, se = macro(sets)
    if se == 0:
        return mean, mean
    rng = random.Random(20261117)
    stats = []
    for _ in range(iterations):
        m, s = macro([rng.choices(units, k=len(units)) for units in sets])
        if s > 0:
            stats.append((m - mean) / s)
    if len(stats) < iterations // 2:
        return None, None
    stats.sort()
    alpha = (1.0 - level) / 2.0
    low_q = stats[int(alpha * len(stats))]
    high_q = stats[int((1.0 - alpha) * len(stats)) - 1]
    return mean - high_q * se, mean - low_q * se


def dominant_share(values, groups=None):
    """The largest share of the observations held by one independent cluster (0 with no cluster labels). One study that holds most of the isolates is what the
    full simulation found the cluster-t interval cannot handle (python/simulate_validation.py: 64-79% coverage of a nominal 95%)."""
    if not groups or not len(values):
        return 0.0
    counts = {}
    for group in groups:
        counts[group] = counts.get(group, 0) + 1
    return max(counts.values()) / len(groups)


def interval_method_used(values, groups=None, strata=None, method=None):
    """The method interval() will use. An explicit `method` is honoured. With none given the leaderboard's INTERVAL_METHOD applies, EXCEPT that a study holding more than
    DOMINANT_STUDY_SHARE of the observations switches a studentised interval to the percentile cluster bootstrap, which the simulation found the least bad there."""
    if method:
        return method
    if DOMINANT_FALLBACK and INTERVAL_METHOD != "percentile" and dominant_share(values, groups) > DOMINANT_STUDY_SHARE:
        return "percentile"
    return INTERVAL_METHOD


def interval(values, groups=None, strata=None, method=None, iterations=1000):
    """The leaderboard's interval for the (macro) mean, by INTERVAL_METHOD unless method is given (or a dominant study triggers the percentile fallback: interval_method_used).

    bootstrap_t has a stratified form (stratified_bootstrap_t_ci)."""
    method = interval_method_used(values, groups, strata, method)
    if method == "percentile":
        return stratified_bootstrap(values, groups, strata, iterations=iterations)
    if method == "bootstrap_t":
        if strata is None:
            return bootstrap_t_ci(values, groups, iterations=iterations)
        return stratified_bootstrap_t_ci(values, groups, strata, iterations=iterations)
    return cluster_t_ci(values, groups, strata)


INTERVAL_METHOD = __import__("os").environ.get("PLASBENCH_CI_METHOD", "cluster_t")
# A study that holds more than this share of the observations makes the default interval fall back to the percentile bootstrap (PLASBENCH_DOMINANT_SHARE, pre-registration row
# dominant_study_share; PLASBENCH_DOMINANT_FALLBACK=0 turns the fallback off). 0.30 is above what unbalanced designs of 1-6 isolates per study reach and far below the 40-60% of
# the structures the simulation showed cluster-t cannot cover.
DOMINANT_STUDY_SHARE = float(__import__("os").environ.get("PLASBENCH_DOMINANT_SHARE", "0.30"))
DOMINANT_FALLBACK = __import__("os").environ.get("PLASBENCH_DOMINANT_FALLBACK", "1") != "0"
if INTERVAL_METHOD not in INTERVAL_METHODS:
    raise SystemExit(f"PLASBENCH_CI_METHOD must be one of {INTERVAL_METHODS}, got {INTERVAL_METHOD!r}")
