#!/usr/bin/env python3
"""
simulate_validation.py -- does PlasBench's cluster-aware statistics do what it claims?

The leaderboard's intervals and the paired tests resample whole clusters (studies) with python/resampling.py. Those procedures were checked for exactness
(test_resampling_equivalence.py) but never for *calibration*: does a "95%" interval contain the truth about 95% of the time, and does a test at 0.05 reject a true null
about 5% of the time, when isolates within a study are correlated, studies differ, study sizes are unequal and some observations are missing?

This script answers that by simulation, with the real functions (resampling.bootstrap_ci and resampling.paired_permutation_pvalue):

  data       paired differences d = effect + study effect + isolate noise; study effects ~ N(0, tau), isolate noise ~ N(0, sigma); study sizes balanced or unbalanced;
             a share of observations dropped at random (missing); a study that loses every observation disappears
  measured   interval coverage of the true effect (nominal 0.95), the rate at which the test rejects at alpha 0.05 (the type-I error when effect = 0, the power when
             effect > 0), and the share of replicates in which a test or interval could be estimated at all (it needs MIN_CLUSTERS_TEST and MIN_CLUSTERS_CI independent units, 6 and 5)

  --mode smoke   a few scenarios, 100 replicates, light resampling: seconds; indicative, with its Monte Carlo standard error shown
  --mode full    more scenarios, 1,000 replicates, the production resampling counts: minutes; for a nightly run or before a release

Every number carries its standard error, a fixed seed makes a run repeatable, and the verdict says what the data can and cannot support (a smoke run cannot certify
calibration, only expose a gross failure, and its verdicts say "indicative"). A verdict tests the observed rate against the nominal one with the standard error EXPECTED UNDER
THE NOMINAL RATE (sqrt(0.95 x 0.05 / n) for coverage, sqrt(0.05 x 0.95 / n) for the type-I error), two of them either way: the observed rate's own standard error would let a
coverage of 0.90 pass in a 100-replicate run.
Interval methods (second review, issues 1 and 5A): every interval scenario measures all three of resampling.INTERVAL_METHODS on the same simulated data -- the percentile
cluster bootstrap, the cluster-robust t interval (CR1, t on G-1 degrees of freedom) and the studentized cluster bootstrap -- with coverage and mean width each, so the
method the leaderboard uses (resampling.INTERVAL_METHOD, PLASBENCH_CI_METHOD) is chosen on evidence, not assumed. The ci_* columns describe that method; the per-method
columns sit beside them. More bootstrap iterations would not fix an under-covering method: they only shrink Monte Carlo error.
Scope: unstratified scenarios (the pooled headline), STRATIFIED scenarios (a species macro-average over two strata: stratified percentile and stratified cluster t, the
stratified sign-flip test) and a HOLM scenario (all pairwise sign-flip tests among K tools that truly do not differ, Holm-adjusted: the family-wise error rate). The ratio
bootstrap (pooled CPRR) is covered by exactness tests only. Output: one TSV (benchmark.stats_validation.tsv) that the report shows under Sensitivity, power and reproducibility.
Advisory: it never changes a score or a rank. Standard library only.
"""
import argparse
import csv
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resampling  # noqa: E402

ALPHA = 0.05
NOMINAL = 0.95
METHODS = resampling.INTERVAL_METHODS
FIELDS = ("mode", "scenario", "n_clusters", "isolates_per_cluster", "tau", "sigma", "missing", "effect", "replicates", "ci_estimated", "ci_coverage", "ci_coverage_se",
          "ci_verdict", "test_estimated", "rejection_rate", "rejection_se", "test_method", "test_verdict", "kind", "ci_method",
          *(f"{m}_{k}" for m in METHODS for k in ("coverage", "width")))

# (name, clusters, isolates per cluster or None for unbalanced, tau, sigma, missing share)
SMOKE = (("balanced, few studies", 6, 3, 0.05, 0.10, 0.0), ("balanced, 12 studies", 12, 3, 0.05, 0.10, 0.0),
         ("unbalanced, 12 studies, 10% missing", 12, None, 0.08, 0.10, 0.10), ("balanced, 20 studies", 20, 3, 0.05, 0.10, 0.0))
FULL = SMOKE + (("balanced, 8 studies", 8, 3, 0.05, 0.10, 0.0), ("balanced, 30 studies", 30, 3, 0.05, 0.10, 0.0),
                ("strong study effect, 12 studies", 12, 4, 0.20, 0.10, 0.0), ("unbalanced, 20 studies, 20% missing", 20, None, 0.08, 0.10, 0.20),
                ("one isolate per study, 12 studies", 12, 1, 0.00, 0.10, 0.0))
# Stratified: (name, clusters per stratum, isolates per cluster or None, tau, sigma, missing); two strata whose means differ by 0.2.
STRATIFIED_SMOKE = (("stratified, 2 x 4 studies", 4, 3, 0.05, 0.10, 0.0), ("stratified, 2 x 8 studies", 8, 3, 0.05, 0.10, 0.0))
STRATIFIED_FULL = STRATIFIED_SMOKE + (("stratified, 2 x 12 studies, unbalanced", 12, None, 0.08, 0.10, 0.10),)
# Holm: (name, tools, clusters, isolates per cluster, tau, sigma); every tool has the same true performance.
HOLM_SMOKE = (("Holm family, 4 tools, 12 studies", 4, 12, 3, 0.05, 0.10),)
HOLM_FULL = HOLM_SMOKE + (("Holm family, 8 tools, 20 studies", 8, 20, 3, 0.05, 0.10),)
SETTINGS = {"smoke": {"scenarios": SMOKE, "stratified": STRATIFIED_SMOKE, "holm": HOLM_SMOKE, "replicates": 100, "bootstrap": 200, "permutations": 1000,
                      "effects": (0.0, 0.10)},
            "full": {"scenarios": FULL, "stratified": STRATIFIED_FULL, "holm": HOLM_FULL, "replicates": 1000, "bootstrap": 1000, "permutations": 10000,
                     "effects": (0.0, 0.05, 0.10)}}


def simulate(rng, clusters, per_cluster, tau, sigma, missing, effect):
    """(values, groups) of one simulated paired-difference data set."""
    values, groups = [], []
    for k in range(clusters):
        size = per_cluster if per_cluster else rng.choice((1, 2, 6))
        study = rng.gauss(0.0, tau) if tau else 0.0
        for _ in range(size):
            if missing and rng.random() < missing:
                continue
            values.append(effect + study + rng.gauss(0.0, sigma))
            groups.append(f"study{k}")
    return values, groups


def binomial_se(rate, n):
    return math.sqrt(rate * (1 - rate) / n) if n else float("nan")


def run_scenario(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, bootstrap, permutations, seed, mode):
    rng = random.Random(seed)
    rejected = test_n = 0
    sizes = []
    methods = set()
    per_method = {m: [0, 0, 0.0] for m in METHODS}   # covered, estimated, summed width
    for _ in range(replicates):
        values, groups = simulate(rng, clusters, per_cluster, tau, sigma, missing, effect)
        if not values:
            continue
        sizes.append(len(values) / max(1, len(set(groups))))
        for method in METHODS:
            low, high = resampling.interval(values, groups, None, method=method, iterations=bootstrap)
            if low is not None:
                per_method[method][1] += 1
                per_method[method][0] += low <= effect <= high
                per_method[method][2] += high - low
        units = len(set(groups))
        p = resampling.paired_permutation_pvalue(values, iterations=permutations, groups=groups)
        if p is not None:
            test_n += 1
            rejected += p <= ALPHA
            methods.add(resampling.permutation_method(units))
    return _row(mode, name, "unstratified", clusters, sizes, tau, sigma, missing, effect, replicates, per_method, rejected, test_n, methods)


def _row(mode, name, kind, clusters, sizes, tau, sigma, missing, effect, replicates, per_method, rejected, test_n, methods):
    covered, ci_n, _ = per_method.get(resampling.INTERVAL_METHOD, [0, 0, 0.0]) if per_method else (0, 0, 0.0)
    coverage = covered / ci_n if ci_n else None
    rate = rejected / test_n if test_n else None
    coverage_se = binomial_se(coverage, ci_n) if ci_n else None
    rate_se = binomial_se(rate, test_n) if test_n else None
    # The verdict compares the observed rate with the nominal one using the standard error expected UNDER the nominal rate (a coverage of 0.90 over 100 replicates is below
    # 0.95 - 2 x 0.0218 = 0.906, so it is flagged; using the observed rate's own standard error would let it pass), and never rounds a shortfall up: a percentile cluster
    # bootstrap with few studies is known to under-cover, and the table must say so rather than call 0.86 "adequate". 'not estimable' when too few replicates had an interval.
    # A smoke run is labelled indicative: its verdicts can expose a gross failure but cannot certify calibration.
    tag = " (indicative: smoke run)" if mode == "smoke" else ""
    if coverage is None or ci_n < replicates * 0.5:
        ci_verdict = "not estimable (too few independent units)"
    elif coverage >= NOMINAL - 2 * math.sqrt(NOMINAL * (1 - NOMINAL) / ci_n):
        ci_verdict = "consistent with 95%" + tag
    else:
        ci_verdict = f"below nominal ({coverage:.0%}): the interval is too narrow" + tag
    if rate is None or test_n < replicates * 0.5:
        test_verdict = f"not estimable (needs {resampling.MIN_CLUSTERS_TEST} independent units)"
    elif effect == 0:
        test_verdict = ("valid (type-I error within tolerance)" + tag if rate <= ALPHA + 2 * math.sqrt(ALPHA * (1 - ALPHA) / test_n)
                        else "anti-conservative (type-I error too high)" + tag)
    else:
        test_verdict = f"power {rate:.2f}"
    extra = {"kind": kind, "ci_method": resampling.INTERVAL_METHOD if per_method else ""}
    for method in METHODS:
        hit, n, width = (per_method or {}).get(method, (0, 0, 0.0))
        extra[f"{method}_coverage"] = f"{hit / n:.3f}" if n else ""
        extra[f"{method}_width"] = f"{width / n:.4f}" if n else ""
    if not per_method:
        ci_verdict = "not applicable (a test-only scenario)"
    return {**extra, "mode": mode, "scenario": name, "n_clusters": clusters,
            "isolates_per_cluster": (f"{sum(sizes) / len(sizes):.1f}" if sizes else ""), "tau": tau, "sigma": sigma, "missing": missing, "effect": effect,
            "replicates": replicates, "ci_estimated": f"{ci_n / replicates:.2f}", "ci_coverage": "" if coverage is None else f"{coverage:.3f}",
            "ci_coverage_se": "" if coverage_se is None else f"{coverage_se:.3f}", "ci_verdict": ci_verdict, "test_estimated": f"{test_n / replicates:.2f}",
            "rejection_rate": "" if rate is None else f"{rate:.3f}", "rejection_se": "" if rate_se is None else f"{rate_se:.3f}",
            "test_method": "/".join(sorted(methods)) or "not_estimated", "test_verdict": test_verdict}


def run(mode="smoke", replicates=None, seed=20261114):
    config = SETTINGS[mode]
    replicates = replicates or config["replicates"]
    rows = []
    for index, (name, clusters, per_cluster, tau, sigma, missing) in enumerate(config["scenarios"]):
        for effect in config["effects"]:
            rows.append(run_scenario(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, config["bootstrap"], config["permutations"],
                                     seed + 1000 * index + int(round(effect * 1000)), mode))
    for index, (name, clusters, per_cluster, tau, sigma, missing) in enumerate(config["stratified"]):
        for effect in config["effects"]:
            rows.append(run_stratified(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, config["bootstrap"], config["permutations"],
                                       seed + 50000 + 1000 * index + int(round(effect * 1000)), mode))
    for index, (name, tools, clusters, per_cluster, tau, sigma) in enumerate(config["holm"]):
        rows.append(run_holm(name, tools, clusters, per_cluster, tau, sigma, replicates, config["permutations"], seed + 90000 + index, mode))
    return rows


def run_stratified(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, bootstrap, permutations, seed, mode):
    """Two strata (species) with different means; the target is the macro mean of the stratum means (= effect)."""
    rng = random.Random(seed)
    rejected = test_n = 0
    sizes, methods = [], set()
    per_method = {m: [0, 0, 0.0] for m in ("percentile", "cluster_t")}
    for _ in range(replicates):
        values, groups, strata = [], [], []
        for stratum, shift in (("A", -0.1), ("B", 0.1)):
            v, g = simulate(rng, clusters, per_cluster, tau, sigma, missing, effect + shift)
            values += v
            groups += [f"{stratum}:{x}" for x in g]
            strata += [stratum] * len(v)
        if len(set(strata)) < 2:
            continue
        sizes.append(len(values) / max(1, len(set(groups))))
        for method in per_method:
            low, high = resampling.interval(values, groups, strata, method=method, iterations=bootstrap)
            if low is not None:
                per_method[method][1] += 1
                per_method[method][0] += low <= effect <= high
                per_method[method][2] += high - low
        p = resampling.stratified_permutation(values, groups, strata, iterations=permutations)
        if p is not None:
            test_n += 1
            rejected += p <= ALPHA
            methods.add(resampling.permutation_method(len(set(groups))))
    # bootstrap_t has no stratified form (resampling.interval falls back to cluster_t), so it is reported as cluster_t's figure.
    per_method["bootstrap_t"] = list(per_method["cluster_t"])
    return _row(mode, name, "stratified", 2 * clusters, sizes, tau, sigma, missing, effect, replicates, per_method, rejected, test_n, methods)


def run_holm(name, tools, clusters, per_cluster, tau, sigma, replicates, permutations, seed, mode):
    """Family-wise error: all pairwise sign-flip tests among tools with equal true performance, Holm-adjusted."""
    from aggregate_results import holm_adjust
    rng = random.Random(seed)
    any_rejected = families = 0
    methods = set()
    for _ in range(replicates):
        study = [rng.gauss(0.0, tau) for _ in range(clusters)]
        scores = {t: [] for t in range(tools)}
        groups = []
        for k in range(clusters):
            for _ in range(per_cluster):
                shared = study[k] + rng.gauss(0.0, sigma)   # the isolate's difficulty, common to every tool
                for t in range(tools):
                    scores[t].append(shared + rng.gauss(0.0, sigma))
                groups.append(f"study{k}")
        pvalues = []
        for a in range(tools):
            for b in range(a + 1, tools):
                diffs = [x - y for x, y in zip(scores[a], scores[b])]
                pvalues.append(resampling.paired_permutation_pvalue(diffs, iterations=permutations, groups=groups))
        if any(p is None for p in pvalues):
            continue
        families += 1
        methods.add(resampling.permutation_method(clusters))
        any_rejected += any(p <= ALPHA for p in holm_adjust(pvalues))
    row = _row(mode, name, "holm", clusters, [per_cluster], tau, sigma, 0.0, 0.0, replicates, None, any_rejected, families, methods)
    if families:
        rate = any_rejected / families
        tag = " (indicative: smoke run)" if mode == "smoke" else ""
        row["test_verdict"] = ("family-wise error within tolerance" + tag if rate <= ALPHA + 2 * math.sqrt(ALPHA * (1 - ALPHA) / families)
                               else "family-wise error too high" + tag) + f" over {tools * (tools - 1) // 2} comparisons"
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(SETTINGS), default="smoke")
    ap.add_argument("--replicates", type=int, help="override the replicates per scenario (default 100 smoke, 1000 full)")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--out", required=True, help="benchmark.stats_validation.tsv")
    args = ap.parse_args()
    rows = run(args.mode, args.replicates, args.seed)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    bad = [r for r in rows if r["ci_verdict"].startswith("below nominal") or r["test_verdict"].startswith("anti-conservative")]
    sys.stderr.write(f"[simulate_validation] {args.mode}: {len(rows)} scenario(s); "
                     + (f"{len(bad)} show a calibration shortfall (see the table)" if bad else "no calibration shortfall detected") + f" -> {args.out}\n")


if __name__ == "__main__":
    main()
