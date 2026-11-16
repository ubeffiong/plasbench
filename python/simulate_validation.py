#!/usr/bin/env python3
"""
simulate_validation.py -- does PlasBench's cluster-aware statistics do what it claims?

The leaderboard's intervals and the paired tests resample whole clusters (studies) with python/resampling.py. Those procedures were checked for exactness
(test_resampling_equivalence.py) but never for *calibration*: does a "95%" interval contain the truth about 95% of the time, and does a test at 0.05 reject a true null
about 5% of the time, when isolates within a study are correlated, studies differ, study sizes are unequal, one study or species dominates, tools fail or produce nothing,
and many tools are compared at once?

This script answers that by simulation, with the real functions (resampling.bootstrap_ci, paired_permutation_pvalue, stratified_bootstrap, stratified_permutation and
aggregate_results.holm_adjust). The results are reported BY THE NUMBER OF INDEPENDENT STUDIES, because that, not the number of isolates, limits what the statistics can show.

  data       paired differences d = effect + study effect + isolate noise; study effects ~ N(0, tau), isolate noise ~ N(0, sigma) (so the within-study correlation is
             tau^2 / (tau^2 + sigma^2), reported as `icc`); study sizes balanced, unbalanced (1, 2 or 6 isolates), one DOMINANT study (60% of the isolates) or TWO HEAVY
             studies (80%); a share of observations dropped at random (a missing output: excluded); resource FAILURES (a tool that produced nothing and is scored 0, so the
             paired difference is +-0.7 with the sign random, symmetric so the null stays true), either per isolate or CLUSTERED (a whole study fails, for example one
             database or one node); several SPECIES with one dominant (70% of the studies) analysed with the species-stratified functions the species-balanced headline uses;
             a study that loses every observation disappears
  measured   interval coverage of the true effect (nominal 0.95); the rate at which the test rejects at alpha 0.05 (the type-I error when effect = 0, the power when
             effect > 0); the share of replicates in which an interval or a test could be estimated at all (MIN_CLUSTERS_CI 5, MIN_CLUSTERS_TEST 6); and, for the Holm family,
             the family-wise error rate (any false rejection among m comparisons of which none, or a third, are real) with and without the Holm adjustment, and the power

  --mode smoke   a few scenarios, 100 replicates, light resampling: seconds; indicative, with its Monte Carlo standard error shown
  --mode full    every scenario, 1,000 replicates, the production resampling counts: minutes with --workers; for a nightly run or before a release

Every number carries its standard error, a fixed seed makes a run repeatable, and the verdict says what the data can and cannot support (a smoke run cannot certify
calibration, only expose a gross failure, and its verdicts say "indicative"). A verdict tests the observed rate against the nominal one with the standard error EXPECTED UNDER
THE NOMINAL RATE (sqrt(0.95 x 0.05 / n) for coverage, sqrt(0.05 x 0.95 / n) for the type-I error), two of them either way.

INTERVAL METHODS. Every interval scenario measures all three of resampling.INTERVAL_METHODS on the same simulated data -- the percentile cluster bootstrap, the cluster-robust t
interval (CR1, t on G-1 degrees of freedom) and the studentized cluster bootstrap -- with coverage and mean width each. They are all kept: the leaderboard uses resampling.INTERVAL_METHOD
(PLASBENCH_CI_METHOD, default cluster_t), the others stay selectable and are reported beside it. The ci_* columns describe the method in use; the per-method columns sit beside them.
Further scopes: STRATIFIED scenarios (a species macro-average over two strata with different means) and a HOLM_PAIRS scenario (all pairwise sign-flip tests among K tools that truly
do not differ, Holm-adjusted: the family-wise error rate).

STATUS. The statistical procedures stay PROVISIONAL until a full-mode run supports them for the number of independent studies and the cohort structure they are used on:
by_studies() groups the rows by the number of studies and says, per number, "supported", "shortfall" (with the scenario that fails) or "indicative only (smoke run)", and
overall_status() is the one-line state the report and the leaderboard notes quote. A shortfall is a limit, not a failure to hide: read the interval as optimistic there.

Scope: the Holm scenarios draw independent comparisons (real tool pairs share tools, so their p-values are positively dependent, which makes Holm conservative; independence is
the case that tests the adjustment itself). Output: benchmark.stats_validation.tsv (one row per scenario and effect) and, with --by-studies-out, the summary by number of
studies. Advisory: it never changes a score or a rank. Standard library only.
"""
import argparse
import csv
import math
import os
import random
import sys
from collections import namedtuple
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resampling  # noqa: E402

METHODS = resampling.INTERVAL_METHODS
LEADERBOARD = "leaderboard"   # the interval the leaderboard actually uses: resampling.INTERVAL_METHOD, or the percentile bootstrap when one study dominates
COLUMN_METHODS = METHODS + (LEADERBOARD,)
from aggregate_results import holm_adjust  # noqa: E402

ALPHA = 0.05
NOMINAL = 0.95
FAILURE_MAGNITUDE = 0.7     # a failed tool scores 0 where the other scores about 0.7 (a typical F1): the paired difference is +-0.7
FIELDS = ("mode", "scenario", "n_clusters", "isolates_per_cluster", "tau", "sigma", "missing", "effect", "replicates", "ci_estimated", "ci_coverage", "ci_coverage_se",
          "ci_verdict", "test_estimated", "rejection_rate", "rejection_se", "test_method", "test_verdict",
          "family", "sizes", "icc", "failure", "species", "comparisons", "fwer_unadjusted", "fwer_holm", "power_unadjusted", "power_holm", "kind", "ci_method",
          *(f"{m}_{k}" for m in COLUMN_METHODS for k in ("coverage", "width")))

Scenario = namedtuple("Scenario", "name family clusters per_cluster tau sigma missing sizes failure clustered species comparisons")


def S(name, clusters, per=3, tau=0.05, sigma=0.10, missing=0.0, sizes="balanced", failure=0.0, clustered=False, species=0, comparisons=1, family="studies"):
    if per is None and sizes == "balanced":
        sizes = "unbalanced"
    return Scenario(name, family, clusters, per, tau, sigma, missing, sizes, failure, clustered, species, comparisons)


SMOKE = (S("balanced, few studies", 6), S("balanced, 12 studies", 12), S("unbalanced, 12 studies, 10% missing", 12, None, 0.08, 0.10, 0.10, family="sizes and missing"),
         S("balanced, 20 studies", 20),
         S("one dominant study, 12 studies", 12, None, family="sizes and missing", sizes="dominant"),
         S("10% resource failures, 12 studies", 12, family="failures", failure=0.10),
         S("Holm over 6 comparisons, 12 studies", 12, family="holm", comparisons=6))
FULL = SMOKE + (
    S("balanced, 5 studies", 5), S("balanced, 8 studies", 8), S("balanced, 30 studies", 30),
    S("one isolate per study, 12 studies", 12, 1, 0.00, family="studies"),
    S("unbalanced, 20 studies, 20% missing", 20, None, 0.08, 0.10, 0.20, family="sizes and missing"),
    S("one dominant study, 20 studies", 20, None, family="sizes and missing", sizes="dominant"),
    S("two heavy studies (80% of isolates), 12 studies", 12, None, family="sizes and missing", sizes="heavy2"),
    S("two heavy studies (80% of isolates), 20 studies", 20, None, family="sizes and missing", sizes="heavy2"),
    S("no within-study correlation, 12 studies", 12, 4, 0.0, family="within-study correlation"),
    S("moderate correlation (icc 0.5), 12 studies", 12, 4, 0.10, family="within-study correlation"),
    S("strong correlation (icc 0.8), 12 studies", 12, 4, 0.20, family="within-study correlation"),
    S("30% missing outputs, 12 studies", 12, family="sizes and missing", missing=0.30),
    S("10% resource failures, 20 studies", 20, family="failures", failure=0.10),
    S("a study fails entirely (10% of studies), 12 studies", 12, family="failures", failure=0.10, clustered=True),
    S("a study fails entirely (10% of studies), 20 studies", 20, family="failures", failure=0.10, clustered=True),
    S("one dominant species of 3, 12 studies", 12, 3, family="dominant species", species=3),
    S("one dominant species of 3, 24 studies", 24, 3, family="dominant species", species=3),
    S("Holm over 15 comparisons, 12 studies", 12, family="holm", comparisons=15),
    S("Holm over 6 comparisons, 20 studies", 20, family="holm", comparisons=6))
SETTINGS = {"smoke": {"scenarios": SMOKE, "replicates": 100, "bootstrap": 200, "permutations": 1000, "effects": (0.0, 0.10)},
            "full": {"scenarios": FULL, "replicates": 1000, "bootstrap": 1000, "permutations": 10000, "effects": (0.0, 0.05, 0.10)}}


def _sizes(rng, clusters, per_cluster, sizes):
    if sizes == "dominant":                       # one study holds 60% of the isolates, the others 2 each
        rest = 2 * (clusters - 1)
        return [math.ceil(1.5 * rest)] + [2] * (clusters - 1)
    if sizes == "heavy2":                         # two studies hold 80% of the isolates, the others 1 each
        return [2 * (clusters - 2)] * 2 + [1] * (clusters - 2)
    if per_cluster:
        return [per_cluster] * clusters
    return [rng.choice((1, 2, 6)) for _ in range(clusters)]


def draw(rng, clusters, per_cluster, tau, sigma, missing, effect, sizes="balanced", failure=0.0, clustered=False, species=0):
    """(values, groups, strata) of one simulated paired-difference data set; strata is None unless `species` > 0."""
    values, groups, strata = [], [], []
    study_sizes = _sizes(rng, clusters, per_cluster, sizes)
    if species:
        dominant = max(1, round(0.7 * clusters))
        labels = ["species0"] * dominant + [f"species{1 + i % (species - 1)}" for i in range(clusters - dominant)]
    for k in range(clusters):
        study = rng.gauss(0.0, tau) if tau else 0.0
        study_failed = clustered and failure and rng.random() < failure
        study_sign = rng.choice((-1, 1))
        for _ in range(study_sizes[k]):
            if missing and rng.random() < missing:
                continue
            if study_failed:
                value = study_sign * FAILURE_MAGNITUDE
            elif failure and not clustered and rng.random() < failure:
                value = rng.choice((-1, 1)) * FAILURE_MAGNITUDE
            else:
                value = effect + study + rng.gauss(0.0, sigma)
            values.append(value)
            groups.append(f"study{k}")
            if species:
                strata.append(labels[k])
    return values, groups, (strata if species else None)


def simulate(rng, clusters, per_cluster, tau, sigma, missing, effect, **options):
    """(values, groups) of one simulated data set (see draw for the options)."""
    values, groups, _strata = draw(rng, clusters, per_cluster, tau, sigma, missing, effect, **options)
    return values, groups


def binomial_se(rate, n):
    return math.sqrt(rate * (1 - rate) / n) if n else float("nan")


def _verdicts(coverage, ci_n, rate, test_n, effect, replicates, mode):
    # The verdict compares the observed rate with the nominal one using the standard error expected UNDER the nominal rate (a coverage of 0.90 over 100 replicates is below
    # 0.95 - 2 x 0.0218 = 0.906, so it is flagged), and never rounds a shortfall up: a percentile cluster bootstrap with few studies is known to under-cover, and the table must
    # say so rather than call 0.86 "adequate". 'not estimable' when too few replicates had an interval. A smoke run is labelled indicative.
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
    return ci_verdict, test_verdict


def _method_columns(per_method):
    """The per-method coverage and width columns, and the ci_* triple of the method the leaderboard uses: ({column: text}, (covered, estimated))."""
    columns = {"ci_method": f"{resampling.INTERVAL_METHOD}, percentile when one study holds more than {resampling.DOMINANT_STUDY_SHARE:.0%}" if per_method else ""}
    for method in COLUMN_METHODS:
        hit, n, width = (per_method or {}).get(method, (0, 0, 0.0))
        columns[f"{method}_coverage"] = f"{hit / n:.3f}" if n else ""
        columns[f"{method}_width"] = f"{width / n:.4f}" if n else ""
    return columns


def _row(scn, mode, effect, replicates, **values):
    icc = (scn.tau ** 2 / (scn.tau ** 2 + scn.sigma ** 2)) if (scn.tau or scn.sigma) else 0.0
    base = {"mode": mode, "scenario": scn.name, "n_clusters": scn.clusters, "tau": scn.tau, "sigma": scn.sigma, "missing": scn.missing, "effect": effect, "replicates": replicates,
            "family": scn.family, "sizes": scn.sizes, "icc": f"{icc:.2f}",
            "failure": ("" if not scn.failure else f"{scn.failure:g}" + (" (whole studies)" if scn.clustered else "")), "species": scn.species or "",
            "comparisons": scn.comparisons if scn.family == "holm" else ""}
    base.update({name: "" for name in FIELDS if name not in base})
    base["kind"] = "holm" if scn.family == "holm" else "stratified" if scn.species else "unstratified"
    base.update(values)
    return base


def run_scenario(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, bootstrap, permutations, seed, mode, **options):
    scn = S(name, clusters, per_cluster, tau, sigma, missing, **{k: v for k, v in options.items() if k in ("sizes", "failure", "clustered", "species", "family", "comparisons")})
    rng = random.Random(seed)
    rejected = test_n = 0
    sizes = []
    methods = set()
    per_method = {m: [0, 0, 0.0] for m in COLUMN_METHODS}   # covered, estimated, summed width
    for _ in range(replicates):
        values, groups, strata = draw(rng, clusters, per_cluster, tau, sigma, missing, effect, scn.sizes, scn.failure, scn.clustered, scn.species)
        if not values:
            continue
        sizes.append(len(values) / max(1, len(set(groups))))
        for method in COLUMN_METHODS:
            low, high = resampling.interval(values, groups, strata, method=None if method == LEADERBOARD else method, iterations=bootstrap)
            if low is not None:
                per_method[method][1] += 1
                per_method[method][0] += low <= effect <= high
                per_method[method][2] += high - low
        units = len(set(groups))
        p = resampling.stratified_permutation(values, groups, strata, iterations=permutations)
        if p is not None:
            test_n += 1
            rejected += p <= ALPHA
            methods.add(resampling.permutation_method(units))
    covered, ci_n, _width = per_method[LEADERBOARD]
    coverage = covered / ci_n if ci_n else None
    rate = rejected / test_n if test_n else None
    ci_verdict, test_verdict = _verdicts(coverage, ci_n, rate, test_n, effect, replicates, mode)
    row = _row(scn, mode, effect, replicates, **_method_columns(per_method), isolates_per_cluster=(f"{sum(sizes) / len(sizes):.1f}" if sizes else ""), ci_estimated=f"{ci_n / replicates:.2f}",
               ci_coverage="" if coverage is None else f"{coverage:.3f}", ci_coverage_se="" if coverage is None else f"{binomial_se(coverage, ci_n):.3f}", ci_verdict=ci_verdict,
               test_estimated=f"{test_n / replicates:.2f}", rejection_rate="" if rate is None else f"{rate:.3f}", rejection_se="" if rate is None else f"{binomial_se(rate, test_n):.3f}",
               test_method="/".join(sorted(methods)) or "not_estimated", test_verdict=test_verdict)
    return row


def run_holm(scn, effect, replicates, permutations, seed, mode):
    """Family-wise error and power over scn.comparisons paired comparisons, with and without Holm. Under the global null (effect 0) none is real; otherwise a third are,
    each with the effect given. Comparisons are independent (see the module doc)."""
    rng = random.Random(seed)
    m = scn.comparisons
    real = 0 if effect == 0 else max(1, m // 3)
    false_unadjusted = false_holm = n = 0
    hit_unadjusted = hit_holm = 0.0
    for _ in range(replicates):
        pvalues = []
        for j in range(m):
            values, groups, _s = draw(rng, scn.clusters, scn.per_cluster, scn.tau, scn.sigma, scn.missing, effect if j < real else 0.0, scn.sizes, scn.failure, scn.clustered, 0)
            pvalues.append(resampling.paired_permutation_pvalue(values, iterations=permutations, groups=groups) if values else None)
        if any(p is None for p in pvalues):
            continue
        n += 1
        adjusted = holm_adjust(pvalues)
        null = range(real, m)
        false_unadjusted += any(pvalues[j] <= ALPHA for j in null)
        false_holm += any(adjusted[j] <= ALPHA for j in null)
        if real:
            hit_unadjusted += sum(pvalues[j] <= ALPHA for j in range(real)) / real
            hit_holm += sum(adjusted[j] <= ALPHA for j in range(real)) / real
    tag = " (indicative: smoke run)" if mode == "smoke" else ""
    if n < replicates * 0.5:
        verdict = f"not estimable (needs {resampling.MIN_CLUSTERS_TEST} independent units)"
    elif effect == 0:
        limit = ALPHA + 2 * math.sqrt(ALPHA * (1 - ALPHA) / n)
        verdict = (f"Holm controls the family-wise error ({false_holm / n:.3f}; unadjusted {false_unadjusted / n:.2f})" + tag if false_holm / n <= limit
                   else f"Holm does NOT control the family-wise error ({false_holm / n:.3f})" + tag)
    else:
        verdict = f"Holm power {hit_holm / n:.2f} (unadjusted {hit_unadjusted / n:.2f}); false-rejection rate {false_holm / n:.3f}"
    return _row(scn, mode, effect, replicates, ci_estimated="", test_estimated=f"{n / replicates:.2f}", test_method=resampling.permutation_method(scn.clusters), test_verdict=verdict,
                fwer_unadjusted="" if not n else f"{false_unadjusted / n:.3f}", fwer_holm="" if not n else f"{false_holm / n:.3f}",
                power_unadjusted="" if not (n and real) else f"{hit_unadjusted / n:.3f}", power_holm="" if not (n and real) else f"{hit_holm / n:.3f}",
                rejection_rate="" if not n else f"{false_holm / n:.3f}", rejection_se="" if not n else f"{binomial_se(false_holm / n, n):.3f}")


STRATIFIED_SMOKE = (("stratified, 2 x 4 studies", 4, 3, 0.05, 0.10, 0.0), ("stratified, 2 x 8 studies", 8, 3, 0.05, 0.10, 0.0))
STRATIFIED_FULL = STRATIFIED_SMOKE + (("stratified, 2 x 12 studies, unbalanced", 12, None, 0.08, 0.10, 0.10),)
HOLM_PAIRS_SMOKE = (("Holm family, 4 tools, 12 studies", 4, 12, 3, 0.05, 0.10),)
HOLM_PAIRS_FULL = HOLM_PAIRS_SMOKE + (("Holm family, 8 tools, 20 studies", 8, 20, 3, 0.05, 0.10),)
SETTINGS["smoke"].update(stratified=STRATIFIED_SMOKE, holm_pairs=HOLM_PAIRS_SMOKE)
SETTINGS["full"].update(stratified=STRATIFIED_FULL, holm_pairs=HOLM_PAIRS_FULL)


def _plain_row(mode, name, kind, clusters, sizes, tau, sigma, missing, effect, replicates, per_method, rejected, test_n, methods, family):
    """A row for the stratified and Holm-pairs scenarios (they have no isolate-structure options)."""
    scn = S(name, clusters, 3, tau, sigma, missing, family=family)
    covered, ci_n, _ = per_method.get(LEADERBOARD, [0, 0, 0.0]) if per_method else (0, 0, 0.0)
    coverage = covered / ci_n if ci_n else None
    rate = rejected / test_n if test_n else None
    ci_verdict, test_verdict = _verdicts(coverage, ci_n, rate, test_n, effect, replicates, mode)
    if not per_method:
        ci_verdict = "not applicable (a test-only scenario)"
    row = _row(scn, mode, effect, replicates, **_method_columns(per_method), isolates_per_cluster=(f"{sum(sizes) / len(sizes):.1f}" if sizes else ""),
               ci_estimated=f"{ci_n / replicates:.2f}", ci_coverage="" if coverage is None else f"{coverage:.3f}", ci_coverage_se="" if coverage is None else f"{binomial_se(coverage, ci_n):.3f}",
               ci_verdict=ci_verdict, test_estimated=f"{test_n / replicates:.2f}", rejection_rate="" if rate is None else f"{rate:.3f}",
               rejection_se="" if rate is None else f"{binomial_se(rate, test_n):.3f}", test_method="/".join(sorted(methods)) or "not_estimated", test_verdict=test_verdict)
    row["kind"] = kind
    return row


def run_stratified(name, clusters, per_cluster, tau, sigma, missing, effect, replicates, bootstrap, permutations, seed, mode):
    """Two strata (species) with different means; the target is the macro mean of the stratum means (= effect)."""
    rng = random.Random(seed)
    rejected = test_n = 0
    sizes, methods = [], set()
    per_method = {m: [0, 0, 0.0] for m in ("percentile", "cluster_t", LEADERBOARD)}
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
            low, high = resampling.interval(values, groups, strata, method=None if method == LEADERBOARD else method, iterations=bootstrap)
            if low is not None:
                per_method[method][1] += 1
                per_method[method][0] += low <= effect <= high
                per_method[method][2] += high - low
        p = resampling.stratified_permutation(values, groups, strata, iterations=permutations)
        if p is not None:
            test_n += 1
            rejected += p <= ALPHA
            methods.add(resampling.permutation_method(len(set(groups))))
    per_method["bootstrap_t"] = list(per_method["cluster_t"])   # bootstrap_t has no stratified form (resampling.interval falls back to cluster_t)
    return _plain_row(mode, name, "stratified", 2 * clusters, sizes, tau, sigma, missing, effect, replicates, per_method, rejected, test_n, methods, "stratified species")


def run_holm_pairs(name, tools, clusters, per_cluster, tau, sigma, replicates, permutations, seed, mode):
    """Family-wise error: all pairwise sign-flip tests among tools with equal true performance, Holm-adjusted."""
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
                pvalues.append(resampling.paired_permutation_pvalue([x - y for x, y in zip(scores[a], scores[b])], iterations=permutations, groups=groups))
        if any(p is None for p in pvalues):
            continue
        families += 1
        methods.add(resampling.permutation_method(clusters))
        any_rejected += any(p <= ALPHA for p in holm_adjust(pvalues))
    row = _plain_row(mode, name, "holm", clusters, [per_cluster], tau, sigma, 0.0, 0.0, replicates, None, any_rejected, families, methods, "holm all pairs")
    if families:
        rate = any_rejected / families
        tag = " (indicative: smoke run)" if mode == "smoke" else ""
        row["test_verdict"] = ((f"Holm controls the family-wise error ({rate:.3f})" if rate <= ALPHA + 2 * math.sqrt(ALPHA * (1 - ALPHA) / families)
                                else f"Holm does NOT control the family-wise error ({rate:.3f})") + tag + f" over {tools * (tools - 1) // 2} pairwise comparisons")
        row["fwer_holm"] = f"{rate:.3f}"
    return row


def _job(args):
    scn, effect, config, replicates, seed, mode = args
    if isinstance(scn, tuple) and scn and scn[0] in ("stratified", "holm_pairs"):
        kind, spec = scn
        if kind == "stratified":
            return run_stratified(*spec, effect, replicates, config["bootstrap"], config["permutations"], seed, mode)
        return run_holm_pairs(*spec, replicates, config["permutations"], seed, mode)
    if scn.family == "holm":
        return run_holm(scn, effect, replicates, config["permutations"], seed, mode)
    return run_scenario(scn.name, scn.clusters, scn.per_cluster, scn.tau, scn.sigma, scn.missing, effect, replicates, config["bootstrap"], config["permutations"], seed, mode,
                        sizes=scn.sizes, failure=scn.failure, clustered=scn.clustered, species=scn.species, family=scn.family)


def run(mode="smoke", replicates=None, seed=20261114, workers=1):
    config = SETTINGS[mode]
    replicates = replicates or config["replicates"]
    jobs = []
    for index, scn in enumerate(config["scenarios"]):
        # a Holm scenario is one family: the global null and one real-effect setting, not every effect
        effects = (0.0, config["effects"][-1]) if scn.family == "holm" else config["effects"]
        for effect in effects:
            jobs.append((scn, effect, config, replicates, seed + 1000 * index + int(round(effect * 1000)), mode))
    for index, spec in enumerate(config["stratified"]):
        for effect in config["effects"]:
            jobs.append((("stratified", spec), effect, config, replicates, seed + 50000 + 1000 * index + int(round(effect * 1000)), mode))
    for index, spec in enumerate(config["holm_pairs"]):
        jobs.append((("holm_pairs", spec), 0.0, config, replicates, seed + 90000 + index, mode))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_job, jobs))
    return [_job(job) for job in jobs]


BY_STUDIES_FIELDS = ("n_studies", "mode", "scenarios", "intervals_checked", "lowest_coverage", "lowest_coverage_percentile", "lowest_coverage_cluster_t", "lowest_coverage_bootstrap_t", "lowest_coverage_leaderboard", "interval_status", "tests_checked", "highest_type_i_error", "test_status",
                     "holm_status", "status", "limiting_scenarios")


def by_studies(rows):
    """One row per number of independent studies: what the simulation supports there. A number is 'supported' only for a FULL run with no interval below nominal, no
    anti-conservative test and no Holm failure over every scenario at that number; 'indicative only' for a smoke run; 'shortfall' names the scenarios that fail."""
    out = []
    for n in sorted({int(r["n_clusters"]) for r in rows}):
        group = [r for r in rows if int(r["n_clusters"]) == n]
        for r in group:
            r.setdefault("kind", "holm" if r.get("family") == "holm" else "unstratified")
        mode = group[0]["mode"]
        coverages = [float(r["ci_coverage"]) for r in group if r["ci_coverage"] != "" and r["kind"] != "holm"]
        per_method_low = {m: [float(r[f"{m}_coverage"]) for r in group if r.get(f"{m}_coverage") not in ("", None) and r["kind"] != "holm"] for m in COLUMN_METHODS}
        type_one = [float(r["rejection_rate"]) for r in group if r["kind"] != "holm" and r["effect"] in (0, 0.0, "0", "0.0") and r["rejection_rate"] != ""]
        low = [r for r in group if r["ci_verdict"].startswith("below nominal")]
        high = [r for r in group if r["test_verdict"].startswith("anti-conservative")]
        holm = [r for r in group if r["kind"] == "holm"]
        holm_bad = [r for r in holm if "does NOT control" in r["test_verdict"]]
        estimable = [r for r in group if r["kind"] != "holm" and not r["ci_verdict"].startswith("not estimable")]
        interval = ("not estimable" if not estimable else "shortfall" if low else "consistent with 95%")
        test = ("not estimable" if not any(r["test_verdict"][0] in "vap" for r in group if r["kind"] != "holm") else "shortfall" if high else "valid")
        holm_status = ("not run at this number" if not holm else "shortfall" if holm_bad else "controls the family-wise error")
        limiting = sorted({r["scenario"] for r in low + high + holm_bad})
        if interval == "not estimable":
            status = "not estimable at this number of studies"
        elif limiting:
            status = "shortfall"
        elif mode == "smoke":
            status = "indicative only (smoke run)"
        else:
            status = "supported"
        out.append({"n_studies": n, "mode": mode, "scenarios": len({r["scenario"] for r in group}), "intervals_checked": len(coverages),
                    "lowest_coverage": f"{min(coverages):.3f}" if coverages else "",
                    **{f"lowest_coverage_{m}": (f"{min(v):.3f}" if v else "") for m, v in per_method_low.items()}, "interval_status": interval, "tests_checked": len(type_one),
                    "highest_type_i_error": f"{max(type_one):.3f}" if type_one else "", "test_status": test, "holm_status": holm_status, "status": status,
                    "limiting_scenarios": "; ".join(limiting)})
    return out


def overall_status(rows):
    """The one-line state of the statistical procedures (the report and the notes quote it): provisional unless a FULL run supports every number of studies it covered."""
    if not rows:
        return "provisional: no simulation has been run"
    table = by_studies(rows)
    if any(r["mode"] == "smoke" for r in table):
        return "provisional: only a smoke run (indicative, 100 replicates); run STATS_VALIDATION_MODE=full to support or reject the procedures"
    short = [r for r in table if r["status"] == "shortfall"]
    if short:
        return ("provisional: the full simulation shows a shortfall at " + ", ".join(str(r["n_studies"]) for r in short) + " independent studies ("
                + "; ".join(sorted({s for r in short for s in r["limiting_scenarios"].split("; ") if s})) + "); read the intervals there as optimistic")
    supported = [r["n_studies"] for r in table if r["status"] == "supported"]
    return (f"supported by the full simulation at {', '.join(map(str, supported))} independent studies under the simulated structures; below {min(supported) if supported else 'the smallest number'} "
            "studies, or for another cohort structure, the procedures remain provisional")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=sorted(SETTINGS), default="smoke")
    ap.add_argument("--replicates", type=int, help="override the replicates per scenario (default 100 smoke, 1000 full)")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--workers", type=int, default=1, help="processes to run scenarios on (default 1; the full mode takes minutes with 8 or more)")
    ap.add_argument("--out", required=True, help="benchmark.stats_validation.tsv")
    ap.add_argument("--by-studies-out", help="write the summary by number of independent studies (benchmark.stats_validation_by_studies.tsv)")
    args = ap.parse_args()
    rows = run(args.mode, args.replicates, args.seed, args.workers)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    table = by_studies(rows)
    if args.by_studies_out:
        with open(args.by_studies_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=BY_STUDIES_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
    bad = [r for r in rows if r["ci_verdict"].startswith("below nominal") or r["test_verdict"].startswith("anti-conservative") or "does NOT control" in r["test_verdict"]]
    sys.stderr.write(f"[simulate_validation] {args.mode}: {len(rows)} scenario row(s); "
                     + (f"{len(bad)} show a calibration shortfall (see the table)" if bad else "no calibration shortfall detected") + f" -> {args.out}\n"
                     f"[simulate_validation] status: {overall_status(rows)}\n")


if __name__ == "__main__":
    main()
