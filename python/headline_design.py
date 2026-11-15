#!/usr/bin/env python3
"""
headline_design.py -- the benchmark's pre-specified headline design.

Used by aggregate_results.py. docs/METHODS.md ("Endpoints", "Reference
standard", "Species balance") explains the rules; in short:

* Task tracks. Each tool's evaluation task is declared in
  config/tool_capabilities.tsv (evaluation_task), from its output contract,
  never inferred from binning_capable alone:
    binning_reconstruction  groups sequence into individual plasmids (bins or
                            one-plasmid-per-record output): RECONSTRUCTION,
                            ranked by length-weighted binning F1 (lw_bin_f1);
    sequence_reassembly     produces plasmid-enriched sequence without saying
                            which pieces form one plasmid (plasmidSPAdes):
                            REASSEMBLY, ranked by base-level sequence F1;
    classification          labels the input contigs: CLASSIFICATION, ranked
                            by base-level F1.
  No tool is scored zero on a task it does not attempt, and a reassembler is
  never ranked as if it were a contig classifier. On the long-read and hybrid
  input tracks, reconstruction tools are ranked instead by isolate-level CPRR
  (sample_cprr), because those tools aim to close whole plasmids
  (ranking_metric(); config/prereg.tsv). A row without evaluation_task (an
  older registry or a user tool) falls back to binning_capable and
  method_class.
* Reference standard. Only reference tiers <= HEADLINE_MAX_REFERENCE_TIER
  (default 2) enter the headline; tier 3 (short-read-first or unknown
  provenance) is a sensitivity analysis. Reference quality and reference
  independence are separate: with HEADLINE_REFERENCE_INDEPENDENCE=independent
  (the default) a tier 1-2 reference enters the primary analysis only if it
  was not polished with the benchmark's own reads; same-read-polished and
  not-shown-independent references form the dependent-reference sensitivity
  analysis (independence_table). If no sample qualifies, the primary analysis
  is unavailable and every ranking is labelled provisional.
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
import statistics
from collections import defaultdict, namedtuple
from pathlib import Path

from plasbench_common import UnionFind, CPRR_SWEEP_THRESHOLDS, cprr_sweep_auc  # noqa: E402
# Resampling primitives live in resampling.py (shared with aggregate_results.py,
# which used to be imported back from here, a circular dependency). Re-exported so
# existing `headline_design.exact_mean` / `hd.stratified_bootstrap` callers keep working.
from resampling import (  # noqa: E402,F401
    exact_mean, macro_mean, resampling_units, stratified_bootstrap, stratified_permutation, ratio_bootstrap,
)

TASK_RECONSTRUCTION = "reconstruction"
TASK_REASSEMBLY = "reassembly"
TASK_CLASSIFICATION = "classification"
TASKS = (TASK_RECONSTRUCTION, TASK_REASSEMBLY, TASK_CLASSIFICATION)
TASK_METRIC = {TASK_RECONSTRUCTION: "lw_bin_f1", TASK_REASSEMBLY: "f1", TASK_CLASSIFICATION: "f1"}
# config/tool_capabilities.tsv evaluation_task -> ranking task.
EVALUATION_TASKS = {"binning_reconstruction": TASK_RECONSTRUCTION, "sequence_reassembly": TASK_REASSEMBLY,
                    "classification": TASK_CLASSIFICATION}


def evaluation_task(row):
    """The ranking task of one capability-registry row.

    The declared evaluation_task wins. Without it (an older registry, a user tool
    manifest) binning_capable=yes means reconstruction, a reassembly method class
    that declares no bins means reassembly, and anything else classification.
    An unknown declared value is an error, never a silent default."""
    declared = (row.get("evaluation_task") or "").strip()
    if declared:
        if declared not in EVALUATION_TASKS:
            raise ValueError(f"{row.get('tool', '?')}: evaluation_task must be one of {sorted(EVALUATION_TASKS)}, got {declared!r}")
        return EVALUATION_TASKS[declared]
    if (row.get("binning_capable") or "").strip().lower() == "yes":
        return TASK_RECONSTRUCTION
    if (row.get("method_class") or "").strip() == "reassembly":
        return TASK_REASSEMBLY
    return TASK_CLASSIFICATION
# Track-specific primary endpoint (config/prereg.tsv, primary_endpoint_long_read):
# long-read and hybrid reconstruction tools are built to close whole plasmids, so
# they are ranked on isolate-level CPRR. Short-read reconstruction stays on
# lw_bin_f1, where complete recovery is rare enough that CPRR would floor out.
TRACK_TASK_METRIC = {("long_read", TASK_RECONSTRUCTION): "sample_cprr",
                     ("hybrid", TASK_RECONSTRUCTION): "sample_cprr"}
METRIC_LABEL = {"lw_bin_f1": "length-weighted binning F1", "f1": "base-level classification F1",
                "sample_cprr": "isolate-level CPRR"}
# A reassembler's base-level F1 measures recovered plasmid sequence, not contig labels.
TASK_METRIC_LABEL = {(TASK_REASSEMBLY, "f1"): "base-level sequence-recovery F1"}


def metric_label(task, metric):
    """Human label of a ranking metric within its task."""
    return TASK_METRIC_LABEL.get((task, metric)) or METRIC_LABEL.get(metric, metric)


def ranking_metric(track, task):
    """The pre-registered ranking metric for one (analysis track, task)."""
    return TRACK_TASK_METRIC.get((track, task), TASK_METRIC.get(task, "f1"))


def read_rows(path):
    if not path or not Path(path).is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        rows = list(csv.DictReader(lines, delimiter="\t"))
    from plasbench_common import with_user_tools
    return with_user_tools(path, rows)   # user tools join the built-in capability registry


def normalise_species(organism):
    """'Salmonella enterica subsp. enterica serovar X' -> 'Salmonella enterica'."""
    words = (organism or "").replace("[", "").replace("]", "").split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")


INDEPENDENT = "independent"
SAME_READ_POLISHED = "same_read_polished"
UNKNOWN_INDEPENDENCE = "unknown"
INDEPENDENCE_RULES = ("independent", "any")   # HEADLINE_REFERENCE_INDEPENDENCE


def record_independence(record):
    """independent | same_read_polished | unknown for one provenance row (older tables carry only truth_polish_reads)."""
    value = (record.get("reference_independence") or "").strip()
    if value in (INDEPENDENT, SAME_READ_POLISHED, UNKNOWN_INDEPENDENCE):
        return value
    polish = (record.get("truth_polish_reads") or "").strip()
    if polish in ("none", "independent"):
        return INDEPENDENT
    if polish == "same_as_benchmark":
        return SAME_READ_POLISHED
    if not polish and (record.get("base_level_metrics_valid") or "").strip() == "yes":
        return INDEPENDENT   # truth_provenance sets it yes exactly when the polishing reads were none or independent
    return UNKNOWN_INDEPENDENCE


PRIMARY_AVAILABLE = "available"
PRIMARY_UNAVAILABLE = "unavailable"
PRIMARY_FALLBACK = "fallback_allowed"
Selection = namedtuple("Selection", "rows basis status reason population")


class Design:
    """Everything the headline needs to know about samples and tools."""

    def __init__(self, sample_sheet=None, capabilities=None, provenance=None, clonal_groups=None,
                 max_tier=2, min_species_clusters=20, min_primary_clusters=1, reference_independence="any"):
        self.max_tier = int(max_tier)
        # "independent": the primary analysis accepts only references not polished with the benchmark's reads (the pipeline default,
        # HEADLINE_REFERENCE_INDEPENDENCE). "any": tier alone decides; the library default, so older callers are unchanged.
        if reference_independence not in INDEPENDENCE_RULES:
            raise ValueError(f"reference_independence must be one of {INDEPENDENCE_RULES}")
        self.reference_independence = reference_independence
        # independent clusters (BioProjects / clonal groups) the qualifying references must come from before the primary analysis counts as available; below it a headline would
        # carry no interval and no test. The pipeline passes HEADLINE_MIN_CLUSTERS (default 5, the interval minimum); the library default of 1 keeps old callers unchanged.
        self.min_primary_clusters = int(min_primary_clusters)
        self.min_species_clusters = int(min_species_clusters)
        sheet = read_rows(sample_sheet)
        self.species = {r["sample_id"]: normalise_species(r.get("organism")) for r in sheet if r.get("sample_id")}
        self.species = {k: v for k, v in self.species.items() if v}
        self.task_of = {}
        self.method_class = {}
        for row in read_rows(capabilities):
            if row.get("tool"):
                self.method_class[row["tool"]] = (row.get("method_class") or "").strip()
                self.task_of[row["tool"]] = evaluation_task(row)
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

    def independence(self, sample):
        record = self.provenance.get(sample)
        if not record:
            return UNKNOWN_INDEPENDENCE
        value = record_independence(record)
        # Tier 1 requires reads independent of the benchmark (truth_provenance.tier), so an older table that
        # records only the tier is still independent there.
        if value == UNKNOWN_INDEPENDENCE and not record.get("truth_polish_reads") and record.get("reference_tier") == "1":
            return INDEPENDENT
        return value

    def reference_group(self, sample):
        """tier1_independent | tier2_independent | tier2_same_read_polished | tier2_unknown_independence | tier3 | unrecorded."""
        tier = self.tier(sample)
        if not tier:
            return "unrecorded"
        if tier == "3":
            return "tier3"
        independence = self.independence(sample)
        return f"tier{tier}_{independence if independence != UNKNOWN_INDEPENDENCE else 'unknown_independence'}"

    def in_reference_standard(self, sample, require_independent=None):
        """True when the sample's reference is in tiers 1..max_tier and, when required, independent of the benchmark reads."""
        tier = self.tier(sample)
        if not tier or int(tier) > self.max_tier:
            return False
        if require_independent is None:
            require_independent = self.reference_independence == "independent"
        return not require_independent or self.independence(sample) == INDEPENDENT

    def composition(self, rows):
        """'tier1_independent 4; tier2_same_read_polished 2' over the distinct samples of rows."""
        counts = defaultdict(int)
        for sample in {r["sample"] for r in rows}:
            counts[self.reference_group(sample)] += 1
        return "; ".join(f"{group} {n}" for group, n in sorted(counts.items()))

    def headline_selection(self, rows, allow_fallback=False):
        """The headline population and whether the PRIMARY analysis is available: a Selection(rows, basis, status, reason, population).

        The primary analysis needs references the pre-specified criteria accept (reference tiers 1 to `max_tier`). When none exists the primary analysis is UNAVAILABLE:
        the same numbers are still computed on all samples, but they are labelled provisional everywhere (`primary_status`, `population`, the report banner) and are never
        the headline. This replaces a silent fallback to all samples. `allow_fallback` (ALLOW_PRIMARY_FALLBACK=1) keeps the numbers as the headline, with status
        'fallback_allowed' and the warning kept in every label."""
        if not self.provenance:
            reason = "no truth-provenance table, so no sample can be shown to meet the reference requirement"
        else:
            independent_only = self.reference_independence == "independent"
            in_tiers = [r for r in rows if self.in_reference_standard(r["sample"], require_independent=False)]
            kept = [r for r in in_tiers if self.in_reference_standard(r["sample"])]
            clusters = len({self.cluster(r["sample"]) for r in kept})
            scope = f"tiers 1-{self.max_tier}" + (", independent of the benchmark reads" if independent_only else "")
            if kept and clusters >= self.min_primary_clusters:
                label = f"reference {scope}"
                return Selection(kept, label, PRIMARY_AVAILABLE, "", f"primary: {label}")
            dependent = len({r["sample"] for r in in_tiers}) - len({r["sample"] for r in kept})
            if not in_tiers:
                reason = f"no sample has a reference in tiers 1-{self.max_tier}"
            elif not kept:
                reason = (f"no reference in tiers 1-{self.max_tier} is shown to be independent of the benchmark reads "
                          f"({dependent} sample(s) polished with them or not recorded; they are in the reference-independence sensitivity table)")
            else:
                reason = (f"only {clusters} independent cluster(s) have a reference in {scope}; at least {self.min_primary_clusters} are needed for the headline to carry an interval"
                          + (f" ({dependent} dependent-reference sample(s) left out)" if dependent else ""))
        if allow_fallback:
            return Selection(rows, f"all samples (FALLBACK ALLOWED: {reason})", PRIMARY_FALLBACK, reason,
                             f"fallback allowed: all samples ({reason})")
        return Selection(rows, f"provisional: all samples (primary analysis unavailable: {reason})", PRIMARY_UNAVAILABLE, reason,
                         f"provisional: all samples ({reason})")

    def headline_rows(self, rows):
        """(rows in the headline reference standard, basis label); see headline_selection for the primary-analysis state."""
        selection = self.headline_selection(rows)
        return selection.rows, selection.basis

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


INDEPENDENCE_GROUPS = (
    ("eligible_any_independence", "tiers 1-max, any independence (the reference-tier rule alone)"),
    ("independent", "tiers 1-max, independent of the benchmark reads"),
    ("same_read_polished", "tiers 1-max, polished with the benchmark's own reads (dependent reference)"),
    ("unknown_independence", "tiers 1-max, independence not recorded"),
    ("tier3", "tier 3: provisional, exploratory"),
)


def independence_table(track, task, rows, metric, design):
    """Reference-independence sensitivity (second review, section 4), per tool x reference group.

    For each group: samples, independent clusters, mean ranking metric, the tool's rank within
    the group, and the difference in mean and in rank from the independent-reference group. It
    answers how much a tool's apparent performance depends on how its references were built.
    Descriptive: means are over each tool's own scored samples in the group, it never changes
    the leaderboard, and a group with few clusters says little.
    """
    def member(sample, group):
        tier = design.tier(sample)
        if group == "tier3":
            return tier == "3"
        if not design.in_reference_standard(sample, require_independent=False):
            return False
        return group == "eligible_any_independence" or design.independence(sample) == {
            "independent": INDEPENDENT, "same_read_polished": SAME_READ_POLISHED,
            "unknown_independence": UNKNOWN_INDEPENDENCE}[group]

    values = defaultdict(lambda: defaultdict(dict))   # group -> tool -> sample -> value
    for r in rows:
        if r.get(metric) is None:
            continue
        for group, _ in INDEPENDENCE_GROUPS:
            if member(r["sample"], group):
                values[group][r["tool"]][r["sample"]] = r[metric]
    means, ranks = {}, {}
    for group, by_tool in values.items():
        means[group] = {tool: statistics.mean(v.values()) for tool, v in by_tool.items()}
        order = sorted(means[group], key=lambda tool: (-means[group][tool], tool))
        ranks[group] = {tool: i + 1 for i, tool in enumerate(order)}
    out = []
    labels = dict(INDEPENDENCE_GROUPS)
    for group, _ in INDEPENDENCE_GROUPS:
        for tool in sorted(values.get(group, {})):
            samples = values[group][tool]
            ref_mean = means.get("independent", {}).get(tool)
            ref_rank = ranks.get("independent", {}).get(tool)
            out.append({"analysis_track": track, "task": task, "tool": tool, "reference_group": group,
                        "description": labels[group], "n_samples": len(samples),
                        "n_clusters": len({design.cluster(s) for s in samples}), "metric": metric,
                        "mean_metric": means[group][tool], "rank_in_group": ranks[group][tool],
                        "difference_vs_independent": None if ref_mean is None or group == "independent" else means[group][tool] - ref_mean,
                        "rank_change_vs_independent": None if ref_rank is None or group == "independent" else ranks[group][tool] - ref_rank})
    return out
