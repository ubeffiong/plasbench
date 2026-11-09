#!/usr/bin/env python3
"""
headline_design.py -- the benchmark's pre-specified headline design.

Used by aggregate_results.py. docs/METHODS.md ("Endpoints", "Reference
standard", "Species balance") explains the rules; in short:

* Task tracks. Tools that group contigs into plasmids (binning_capable=yes
  in config/tool_capabilities.tsv) are ranked on the RECONSTRUCTION track by
  length-weighted binning F1 (lw_bin_f1, the primary endpoint). Tools that
  only classify contigs are ranked on a separate CLASSIFICATION track by
  base-level F1 -- they are never scored zero on a binning task they do not
  attempt. On the long-read and hybrid input tracks, reconstruction tools are
  ranked instead by isolate-level CPRR (sample_cprr), because those tools aim
  to close whole plasmids (ranking_metric(); config/prereg.tsv).
* Reference standard. Only reference tiers <= HEADLINE_MAX_REFERENCE_TIER
  (default 2) enter the headline; tier 3 (short-read-first or unknown
  provenance) is a sensitivity analysis. If no sample qualifies, the
  headline falls back to all samples and says so.
* Species balance. The ranking score is the mean of per-species means over
  species with >= MIN_SPECIES_CLUSTERS independent clusters, so one
  over-represented species cannot dominate. Smaller species are described
  only. With no qualifying species the pooled mean is used, and says so.
* Independence. A cluster joins isolates sharing a BioProject/study OR a
  clonal group (union-find). Bootstrap CIs resample clusters within each
  species; permutation tests flip whole clusters. With no species/cluster
  information all of this reduces exactly to plain per-sample statistics.

Standard library only.
"""

import csv
import math
import random
import statistics
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from plasbench_common import UnionFind, CPRR_SWEEP_THRESHOLDS, cprr_sweep_auc  # noqa: E402

TASK_RECONSTRUCTION = "reconstruction"
TASK_CLASSIFICATION = "classification"
TASK_METRIC = {TASK_RECONSTRUCTION: "lw_bin_f1", TASK_CLASSIFICATION: "f1"}
# Track-specific primary endpoint (config/prereg.tsv, primary_endpoint_long_read):
# long-read and hybrid reconstruction tools are built to close whole plasmids, so
# they are ranked on isolate-level CPRR. Short-read reconstruction stays on
# lw_bin_f1, where complete recovery is rare enough that CPRR would floor out.
TRACK_TASK_METRIC = {("long_read", TASK_RECONSTRUCTION): "sample_cprr",
                     ("hybrid", TASK_RECONSTRUCTION): "sample_cprr"}
METRIC_LABEL = {"lw_bin_f1": "length-weighted binning F1", "f1": "base-level classification F1",
                "sample_cprr": "isolate-level CPRR"}


def ranking_metric(track, task):
    """The pre-registered ranking metric for one (analysis track, task)."""
    return TRACK_TASK_METRIC.get((track, task), TASK_METRIC.get(task, "f1"))


def read_rows(path):
    if not path or not Path(path).is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def normalise_species(organism):
    """'Salmonella enterica subsp. enterica serovar X' -> 'Salmonella enterica'."""
    words = (organism or "").replace("[", "").replace("]", "").split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")


class Design:
    """Everything the headline needs to know about samples and tools."""

    def __init__(self, sample_sheet=None, capabilities=None, provenance=None, clonal_groups=None,
                 max_tier=2, min_species_clusters=20):
        self.max_tier = int(max_tier)
        self.min_species_clusters = int(min_species_clusters)
        sheet = read_rows(sample_sheet)
        self.species = {r["sample_id"]: normalise_species(r.get("organism")) for r in sheet if r.get("sample_id")}
        self.species = {k: v for k, v in self.species.items() if v}
        self.task_of = {}
        self.method_class = {}
        for row in read_rows(capabilities):
            if row.get("tool"):
                self.method_class[row["tool"]] = (row.get("method_class") or "").strip()
                capable = (row.get("binning_capable") or "").strip().lower() == "yes"
                self.task_of[row["tool"]] = TASK_RECONSTRUCTION if capable else TASK_CLASSIFICATION
        self.provenance = {r["sample"]: r for r in read_rows(provenance) if r.get("sample")}
        clonal = {r["sample"]: r.get("clonal_group", "") for r in read_rows(clonal_groups) if r.get("sample")}
        self.clusters = self._join_clusters(sheet, clonal)

    @staticmethod
    def _join_clusters(sheet, clonal):
        """Union-find over shared BioProject/study and shared clonal group."""
        clusters = UnionFind()
        find, union = clusters.find, clusters.union

        samples = [r["sample_id"] for r in sheet if r.get("sample_id")]
        for row in sheet:
            sample = row.get("sample_id")
            if not sample:
                continue
            find(f"s:{sample}")
            for column in ("bioproject", "source_study"):
                value = (row.get(column) or "").strip()
                if value:
                    union(f"s:{sample}", f"{column}:{value}")
                    break
            group = (clonal.get(sample) or "").strip()
            if group and not group.startswith("isolate:"):
                union(f"s:{sample}", f"clonal:{group}")
        return {sample: find(f"s:{sample}") for sample in samples}

    def is_baseline(self, tool):
        """Built-in trivial baselines (python/baseline_predictors.py)."""
        return self.method_class.get(tool) == "baseline" or tool.startswith("baseline_")

    # -- tasks -----------------------------------------------------------------
    def task(self, tool, rows):
        if tool in self.task_of:
            return self.task_of[tool]
        has_bins = any(r.get("lw_bin_f1") is not None for r in rows if r["tool"] == tool)
        return TASK_RECONSTRUCTION if has_bins else TASK_CLASSIFICATION

    # -- reference standard ----------------------------------------------------
    def tier(self, sample):
        return (self.provenance.get(sample) or {}).get("reference_tier", "")

    def headline_rows(self, rows):
        """(rows in the headline reference standard, basis label)."""
        if not self.provenance:
            return rows, "all samples (no provenance table)"
        kept = [r for r in rows if self.tier(r["sample"]) and int(self.tier(r["sample"])) <= self.max_tier]
        if kept:
            return kept, f"reference tiers 1-{self.max_tier}"
        return rows, f"all samples (FALLBACK: no sample in reference tiers 1-{self.max_tier})"

    def identity_valid(self, sample):
        record = self.provenance.get(sample)
        return record is None or record.get("base_level_metrics_valid") == "yes"

    def ambiguous_plasmids(self, sample):
        record = self.provenance.get(sample) or {}
        try:
            return int(record.get("ambiguous_plasmids") or 0)
        except ValueError:
            return 0

    # -- species / clusters ------------------------------------------------------
    def cluster(self, sample):
        return self.clusters.get(sample, f"sample:{sample}")

    def qualifying_species(self, samples):
        """Species with >= min_species_clusters independent clusters among samples."""
        clusters = defaultdict(set)
        for sample in samples:
            species = self.species.get(sample)
            if species:
                clusters[species].add(self.cluster(sample))
        return sorted(s for s, c in clusters.items() if len(c) >= self.min_species_clusters)

    def strata_for(self, samples):
        """sample -> species for qualifying species only, or None (pooled)."""
        qualifying = set(self.qualifying_species(samples))
        if not qualifying:
            return None
        return {s: self.species[s] for s in samples if self.species.get(s) in qualifying}


# -- statistics -------------------------------------------------------------------

def exact_mean(values):
    """Bit-identical to statistics.mean(values) for floats, ~10x faster.

    statistics.mean sums every element as an exact Fraction. Here math.fsum gives
    the correctly rounded sum, further fsum passes collect the exact remainder as
    a few doubles, and a single Fraction division rounds once -- the same single
    rounding statistics.mean performs, so bootstrap/permutation results (and
    permutation ties) do not change. Plain fsum/len rounds twice and was seen to
    shift a tie-heavy stratified p-value, so it is deliberately not used.
    """
    values = list(values)
    if not values:
        return statistics.mean(values)  # raises StatisticsError like before
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


def macro_mean(values, strata):
    """Mean of per-stratum means (plain mean when strata is None)."""
    if strata is None:
        return exact_mean(values)
    by = defaultdict(list)
    for value, stratum in zip(values, strata):
        by[stratum].append(value)
    return exact_mean([exact_mean(v) for v in by.values()])


def stratified_bootstrap(values, groups, strata, iterations=1000):
    """Percentile CI of macro_mean, resampling clusters within each stratum.

    With strata None this is exactly aggregate_results.bootstrap_ci(values,
    groups=groups) -- same units, same RNG draws.
    """
    from aggregate_results import bootstrap_ci, resampling_units
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
    means = []
    for _ in range(iterations):
        stratum_means = []
        for stratum in order:
            drawn = rng.choices(units[stratum], k=len(units[stratum]))
            stratum_means.append(exact_mean([v for unit in drawn for v in unit]))
        means.append(exact_mean(stratum_means))
    means.sort()
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def stratified_permutation(differences, groups, strata, iterations=10000):
    """Sign-flip p-value for macro_mean(differences), flipping whole clusters."""
    from aggregate_results import paired_permutation_pvalue, resampling_units
    if strata is None:
        return paired_permutation_pvalue(differences, iterations=iterations, groups=groups)
    units = resampling_units(list(zip(differences, strata)), groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(macro_mean(differences, strata))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    labelled = [([value for value, _ in unit], [-value for value, _ in unit], [stratum for _, stratum in unit])
                for unit in units]
    extreme = 0
    for _ in range(iterations):
        values, labels = [], []
        for positive, negative, unit_strata in labelled:
            # Same bit stream as rng.randrange(2); see aggregate_results.paired_permutation_pvalue.
            bits = getrandbits(2)
            while bits >= 2:
                bits = getrandbits(2)
            values.extend(positive if bits else negative)
            labels.extend(unit_strata)
        extreme += abs(macro_mean(values, labels)) >= observed
    return (extreme + 1) / (iterations + 1)


PARALLEL_MIN_PAIRED_SAMPLES = 2000


def pair_statistics(diffs, groups, strata):
    """(ci_low, ci_high, permutation_p) for one tool pair.

    Module-level and argument-pure so compute_comparisons can fan pairs out to
    worker processes; every resampling call seeds its own RNG, so the result
    does not depend on which process runs it or in what order.
    """
    low, high = stratified_bootstrap(diffs, groups, strata)
    return low, high, stratified_permutation(diffs, groups, strata)


def map_pair_statistics(jobs, workers=None):
    """pair_statistics over jobs [(diffs, groups, strata)], order preserved.

    Runs serially unless there is enough work to repay process start-up:
    at least 4 jobs and 2000 paired samples in total. PLASBENCH_STATS_WORKERS
    overrides the worker count (1 forces serial).
    """
    import os
    if workers is None:
        workers = int(os.environ.get("PLASBENCH_STATS_WORKERS", "0") or 0) or (os.cpu_count() or 1)
    work = sum(len(job[0]) for job in jobs)
    if workers <= 1 or len(jobs) < 4 or work < PARALLEL_MIN_PAIRED_SAMPLES:
        return [pair_statistics(*job) for job in jobs]
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        return list(pool.map(pair_statistics, *zip(*jobs), chunksize=1))


def ratio_bootstrap(pairs, groups, iterations=1000):
    """Percentile CI of sum(correct)/sum(total), resampling clusters."""
    from aggregate_results import resampling_units
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


# -- per-tool headline fields --------------------------------------------------------

def shared_values(rows, key, failed_samples=None, known_tools=None, eligible_samples=None):
    """tool -> {sample: value} with failure-as-zero, the shared sample set, zero counts.

    known_tools: tools to count even though they have no score rows. A tool that
    failed on every sample has none, and would otherwise be dropped here, which
    would let total failure rank above partial failure. The caller must pass only
    failures belonging to this group's tools.
    eligible_samples: plasmid-bearing samples to treat as eligible for a
    failure-as-zero entry in addition to those this group's rows define; needed
    when no row in the group defines the metric at all.
    """
    by_tool = defaultdict(dict)
    eligible = set(eligible_samples or ())
    for r in rows:
        if r.get(key) is not None:
            by_tool[r["tool"]][r["sample"]] = r[key]
            eligible.add(r["sample"])
    tools = {r["tool"] for r in rows} | set(known_tools or ())
    zeros = defaultdict(int)
    for tool, samples in (failed_samples or {}).items():
        if tool not in tools:
            continue
        for sample in samples:
            if sample in eligible and sample not in by_tool[tool]:
                by_tool[tool][sample] = 0.0
                zeros[tool] += 1
    ranked = [t for t, v in by_tool.items() if v]
    shared = set.intersection(*(set(by_tool[t]) for t in ranked)) if ranked else set()
    return by_tool, shared, zeros


def ranking_fields(tool, by_tool, shared, design, metric):
    """ranking_score, its CI and basis for one tool."""
    values_by_sample = by_tool.get(tool, {})
    samples = sorted(shared) if shared else sorted(values_by_sample)
    samples = [s for s in samples if s in values_by_sample]
    empty = {"ranking_metric": metric, "ranking_score": None, "ranking_ci_low": None, "ranking_ci_high": None,
             "ranking_species_basis": "", "n_headline_species": 0, "n_ranking_clusters": 0}
    if not samples:
        return empty
    strata_map = design.strata_for(samples) if design else None
    if strata_map is not None:
        samples = [s for s in samples if s in strata_map]
        strata = [strata_map[s] for s in samples]
        basis = f"species macro-average ({len(set(strata))} species)"
    else:
        strata = None
        basis = "pooled (no species with enough independent clusters)" if design and design.species else "pooled"
    values = [values_by_sample[s] for s in samples]
    groups = [design.cluster(s) if design else f"sample:{s}" for s in samples]
    low, high = stratified_bootstrap(values, groups, strata)
    return {"ranking_metric": metric, "ranking_score": macro_mean(values, strata),
            "ranking_ci_low": low, "ranking_ci_high": high, "ranking_species_basis": basis,
            "n_headline_species": len(set(strata)) if strata else 0, "n_ranking_clusters": len(set(groups))}


def cprr_counts(row, design):
    """(correct, total) for one score row under the identity rule; None when not bin-scored.

    Where identity is not valid for the sample (truth polished with the benchmark's
    own reads) the identity criterion is dropped, as for the pooled CPRR.
    """
    if row.get("cprr_plasmids") in (None, 0):
        return None
    valid = design.identity_valid(row["sample"]) if design else True
    correct = row.get("cprr_correct") if valid else row.get("cprr_correct_without_identity")
    return None if correct is None else (correct, row["cprr_plasmids"])


def cprr_sweep_counts(row, design):
    """Per-threshold correct counts for one row under the identity rule, or None."""
    if row.get("cprr_plasmids") in (None, 0):
        return None
    valid = design.identity_valid(row["sample"]) if design else True
    return row.get("cprr_sweep_correct") if valid else row.get("cprr_sweep_correct_without_identity")


def attach_sample_cprr(rows, design):
    """Set row['sample_cprr'] = correct / truth plasmids for that isolate (None if undefined).

    This is the isolate-weighted CPRR unit: every isolate counts once, however many
    plasmids it carries. It is also the ranking metric on the long-read and hybrid
    reconstruction tracks, so it reuses the per-isolate bootstrap and paired tests.
    """
    for row in rows:
        counts = cprr_counts(row, design)
        row["sample_cprr"] = counts[0] / counts[1] if counts else None
    return rows


def cprr_fields(tool, rows, design):
    """Pooled and isolate-weighted CPRR, cluster bootstrap CI, and threshold-sweep AUC."""
    pairs, samples, sweeps = [], [], []
    for r in rows:
        if r["tool"] != tool:
            continue
        counts = cprr_counts(r, design)
        if counts is None:
            continue
        pairs.append(counts)
        samples.append(r["sample"])
        sweeps.append((cprr_sweep_counts(r, design), counts[1]))
    total = sum(t for _, t in pairs)
    if not total:
        return {"cprr": None, "cprr_ci_low": None, "cprr_ci_high": None, "cprr_plasmids": 0, "cprr_correct": 0,
                "cprr_isolate_mean": None, "cprr_isolates": 0, "cprr_auc": None}
    groups = [design.cluster(s) if design else f"sample:{s}" for s in samples]
    low, high = ratio_bootstrap(pairs, groups)
    correct = sum(c for c, _ in pairs)
    return {"cprr": correct / total, "cprr_ci_low": low, "cprr_ci_high": high,
            "cprr_plasmids": total, "cprr_correct": correct,
            "cprr_isolate_mean": statistics.mean(c / t for c, t in pairs), "cprr_isolates": len(pairs),
            "cprr_auc": cprr_sweep_auc(pooled_sweep(sweeps)["pooled"])}


def pooled_sweep(sweeps):
    """[(per-threshold counts or None, truth plasmids)] -> pooled and isolate-mean rates per threshold.

    Rows without sweep counts (older score tables) are left out of both curves; a
    curve with no rows at all is a list of None, so its AUC is None, never 0.
    """
    usable = [(counts, total) for counts, total in sweeps if counts is not None and total]
    n = len(CPRR_SWEEP_THRESHOLDS)
    if not usable:
        return {"pooled": [None] * n, "isolate_mean": [None] * n, "n_isolates": 0, "n_plasmids": 0}
    plasmids = sum(t for _, t in usable)
    return {"pooled": [sum(c[i] for c, _ in usable) / plasmids for i in range(n)],
            "isolate_mean": [statistics.mean(c[i] / t for c, t in usable) for i in range(n)],
            "n_isolates": len(usable), "n_plasmids": plasmids}


def cprr_sweep_table(track, task, rows, design):
    """Per tool x sweep threshold: pooled and isolate-weighted CPRR (benchmark.cprr_threshold_sweep.tsv)."""
    by_tool = defaultdict(list)
    for r in rows:
        counts = cprr_counts(r, design)
        if counts is not None:
            by_tool[r["tool"]].append((cprr_sweep_counts(r, design), counts[1]))
    out = []
    for tool, sweeps in sorted(by_tool.items()):
        curve = pooled_sweep(sweeps)
        if not curve["n_isolates"]:
            continue
        for i, threshold in enumerate(CPRR_SWEEP_THRESHOLDS):
            out.append({"analysis_track": track, "task": task, "tool": tool, "threshold": f"{threshold:.2f}",
                        "cprr": curve["pooled"][i], "cprr_isolate_mean": curve["isolate_mean"][i],
                        "n_isolates": curve["n_isolates"], "n_plasmids": curve["n_plasmids"]})
    return out


def species_table(track, task, rows, metric, design, failed_samples, known_tools=None, eligible_samples=None):
    """Per tool x species: n, clusters, mean ranking metric, headline membership.

    known_tools and eligible_samples are passed to shared_values: without them a tool
    that failed on every sample (no score rows) is missing from this table although the
    ranking scores it 0 on every plasmid-bearing sample. The caller passes only the
    tools of this (track, task), so failures of other groups' tools are not counted.
    """
    by_tool, shared, _ = shared_values(rows, metric, failed_samples, known_tools, eligible_samples)
    samples = sorted(shared) if shared else sorted({s for v in by_tool.values() for s in v})
    qualifying = set(design.qualifying_species(samples)) if design else set()
    out = []
    for tool in sorted(by_tool):
        by_species = defaultdict(list)
        for sample in samples:
            if sample in by_tool[tool]:
                by_species[design.species.get(sample, "unrecorded") if design else "unrecorded"].append(sample)
        for species, members in sorted(by_species.items()):
            out.append({"analysis_track": track, "task": task, "tool": tool, "species": species,
                        "n_samples": len(members),
                        "n_clusters": len({design.cluster(s) for s in members}) if design else len(members),
                        "mean_metric": statistics.mean(by_tool[tool][s] for s in members),
                        "metric": metric, "in_headline": "yes" if species in qualifying else "no"})
    return out


def tier_table(track, task, rows, metric, design):
    """Per tool x reference tier: n, mean ranking metric and pooled CPRR (sensitivity)."""
    by, cprr = defaultdict(list), defaultdict(list)
    for r in rows:
        key = (r["tool"], design.tier(r["sample"]) or "unrecorded")
        if r.get(metric) is not None:
            by[key].append(r[metric])
        counts = cprr_counts(r, design)
        if counts is not None:
            cprr[key].append(counts)

    def pooled(pairs):
        total = sum(t for _, t in pairs)
        return sum(c for c, _ in pairs) / total if total else None
    return [{"analysis_track": track, "task": task, "tool": tool, "reference_tier": tier, "n_samples": len(v),
             "mean_metric": statistics.mean(v), "metric": metric,
             "cprr": pooled(cprr.get((tool, tier), [])),
             "cprr_plasmids": sum(t for _, t in cprr.get((tool, tier), []))}
            for (tool, tier), v in sorted(by.items())]
