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
Scope: it exercises the UNSTRATIFIED paths of bootstrap_ci and paired_permutation_pvalue, which the headline uses when no species stratification applies. The stratified, ratio
and Holm steps are covered by exactness tests (test_resampling_equivalence.py), not by this calibration. Output: one TSV (benchmark.stats_validation.tsv) that the report shows under Sensitivity, power and reproducibility.
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
FIELDS = ("mode", "scenario", "n_clusters", "isolates_per_cluster", "tau", "sigma", "missing", "effect", "replicates", "ci_estimated", "ci_coverage", "ci_coverage_se",
          "ci_verdict", "test_estimated", "rejection_rate", "rejection_se", "test_method", "test_verdict")

# (name, clusters, isolates per cluster or None for unbalanced, tau, sigma, missing share)
SMOKE = (("balanced, few studies", 6, 3, 0.05, 0.10, 0.0), ("balanced, 12 studies", 12, 3, 0.05, 0.10, 0.0),
         ("unbalanced, 12 studies, 10% missing", 12, None, 0.08, 0.10, 0.10), ("balanced, 20 studies", 20, 3, 0.05, 0.10, 0.0))
FULL = SMOKE + (("balanced, 8 studies", 8, 3, 0.05, 0.10, 0.0), ("balanced, 30 studies", 30, 3, 0.05, 0.10, 0.0),
                ("strong study effect, 12 studies", 12, 4, 0.20, 0.10, 0.0), ("unbalanced, 20 studies, 20% missing", 20, None, 0.08, 0.10, 0.20),
                ("one isolate per study, 12 studies", 12, 1, 0.00, 0.10, 0.0))
SETTINGS = {"smoke": {"scenarios": SMOKE, "replicates": 100, "bootstrap": 200, "permutations": 1000, "effects": (0.0, 0.10)},
            "full": {"scenarios": FULL, "replicates": 1000, "bootstrap": 1000, "permutations": 10000, "effects": (0.0, 0.05, 0.10)}}


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
    covered = ci_n = rejected = test_n = 0
    sizes = []
    methods = set()
    for _ in range(replicates):
        values, groups = simulate(rng, clusters, per_cluster, tau, sigma, missing, effect)
        if not values:
            continue
        sizes.append(len(values) / max(1, len(set(groups))))
        low, high = resampling.bootstrap_ci(values, iterations=bootstrap, groups=groups)
        if low is not None:
            ci_n += 1
            covered += low <= effect <= high
        units = len(set(groups))
        p = resampling.paired_permutation_pvalue(values, iterations=permutations, groups=groups)
        if p is not None:
            test_n += 1
            rejected += p <= ALPHA
            methods.add(resampling.permutation_method(units))
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
    return {"mode": mode, "scenario": name, "n_clusters": clusters,
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
    return rows


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
