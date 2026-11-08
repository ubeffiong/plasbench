#!/usr/bin/env python3
"""
aggregate_results.py -- combine per-sample score rows into a per-tool
leaderboard, and emit a Markdown table for the final pitch.

Input : a scores TSV with the columns written by score_plasmids.py
        (sample, tool, ..., precision, recall, f1). Multiple rows per tool.
Output:
  * <out_prefix>.leaderboard.tsv   -- one row per tool with mean/median metrics
  * <out_prefix>.leaderboard.md    -- same, as a Markdown table (for README/pitch)

Standard library only.
"""

import argparse
import csv
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

# Depth-ladder ids are "<parent>__<depth>x"; used only when a sheet has lost its
# parent_sample_id column, so a copied ladder sheet still cannot be ranked.
LADDER_SUFFIX = re.compile(r"^(?P<parent>.+)__\d+(?:\.\d+)?x$")

# scripts/04_run_tools.sh appends "exit_code=<n>" to a failed run's reason.
# 124 is `timeout`, 137 is SIGKILL (what the kernel OOM killer sends). Both say
# the machine ran out of something, not that the tool produced a wrong answer.
EXIT_CODE = re.compile(r"exit_code=(\d+)")
RESOURCE_EXIT_CODES = {124, 137}


def sample_parents(sample_sheet):
    """Map sample_id -> parent_sample_id for correlated (derived) samples."""
    parents = {}
    if not sample_sheet:
        return parents
    path = Path(sample_sheet)
    if not path.is_file():
        return parents
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t")
        for row in reader:
            sample = (row.get("sample_id") or "").strip()
            if sample:
                parent = (row.get("parent_sample_id") or "").strip()
                if parent:
                    parents[sample] = parent
    return parents


CLUSTER_COLUMNS = ("bioproject", "source_study")


def sample_clusters(sample_sheet):
    """Map sample_id -> independence cluster label from the sample sheet.

    Isolates from one BioProject (one study, often one outbreak or clonal
    collection) are not independent observations. Resampling them one by one
    makes bootstrap intervals and permutation p-values look more certain than
    the data allow. The cluster is the row's bioproject, falling back to
    source_study; a sample with neither is its own cluster. Returns
    (mapping, column_used) -- column_used is "" when no cluster column was
    found, in which case every sample is its own cluster and the statistics
    are identical to plain per-sample resampling.
    """
    clusters = {}
    used = ""
    if not sample_sheet:
        return clusters, used
    path = Path(sample_sheet)
    if not path.is_file():
        return clusters, used
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t")
        for row in reader:
            sample = (row.get("sample_id") or "").strip()
            if not sample:
                continue
            for column in CLUSTER_COLUMNS:
                value = (row.get(column) or "").strip()
                if value:
                    clusters[sample] = f"{column}:{value}"
                    used = used or column
                    break
    return clusters, used


def cluster_labels(samples, clusters):
    """One cluster label per sample (the sample itself when unclustered)."""
    clusters = clusters or {}
    return [clusters.get(sample, f"sample:{sample}") for sample in samples]


def correlated_parents(rows, parents):
    """Return parent -> scored sample ids, for parents covering several samples."""
    groups = defaultdict(set)
    for row in rows:
        sample = row["sample"]
        parent = parents.get(sample)
        if not parent:
            match = LADDER_SUFFIX.match(sample)
            parent = match.group("parent") if match else None
        if parent:
            groups[parent].add(sample)
    return {parent: sorted(samples) for parent, samples in groups.items() if len(samples) > 1}


def read_scores(path):
    rows = []
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            rows.append({
                "sample": f[idx["sample"]],
                "tool": f[idx["tool"]],
                # Undefined on a zero-true-plasmid isolate (precision) or when
                # there was no true plasmid to recall (recall/f1) -- see
                # score_plasmids.py. Gracefully absent, never a misleading
                # 0.0, matching plasmid_recall/bin_f1/pr_auc's existing
                # pattern immediately below.
                "precision": float(f[idx["precision"]]) if "precision" in idx and f[idx["precision"]] else None,
                "recall": float(f[idx["recall"]]) if "recall" in idx and f[idx["recall"]] else None,
                "f1": float(f[idx["f1"]]) if "f1" in idx and f[idx["f1"]] else None,
                "analysis_track": f[idx["analysis_track"]] if "analysis_track" in idx and f[idx["analysis_track"]] else "short_read",
                # A missing plasmid-level value is not evidence of zero recovery.
                "plasmid_recall": (
                    float(f[idx["plasmid_recall"]])
                    if "plasmid_recall" in idx and f[idx["plasmid_recall"]]
                    else None
                ),
                "bin_f1": float(f[idx["bin_f1"]]) if "bin_f1" in idx and f[idx["bin_f1"]] else None,
                # Supplementary bin-quality metrics (score_bins.py's
                # clustering_agreement()); absent for binning_capable=no
                # tools and for a sample with an empty contingency table --
                # gracefully None, never 0, mirroring bin_f1 immediately above.
                "nmi": float(f[idx["nmi"]]) if "nmi" in idx and f[idx["nmi"]] else None,
                "variation_of_information": float(f[idx["variation_of_information"]]) if "variation_of_information" in idx and f[idx["variation_of_information"]] else None,
                # Only defined for tools whose adapter exposed a per-record
                # probability (adapters/SCORES.md); gracefully absent, never 0,
                # for every other tool -- see merge_pr_metrics.py.
                "pr_auc": float(f[idx["pr_auc"]]) if "pr_auc" in idx and f[idx["pr_auc"]] else None,
                "perfect_reference_recovery": f[idx["perfect_reference_recovery"]] if "perfect_reference_recovery" in idx else "",
                "strict_reference_reconstruction": f[idx["strict_reference_reconstruction"]] if "strict_reference_reconstruction" in idx else "",
                # Negative-control fields (score_plasmids.py): always defined
                # for a real isolate, most informative on a zero-true-plasmid
                # one, where they are the only signal of false-positive
                # behaviour since precision/recall/f1 above are undefined.
                "isolate_specificity": float(f[idx["isolate_specificity"]]) if "isolate_specificity" in idx and f[idx["isolate_specificity"]] else None,
                "chromosome_fp_bp": int(f[idx["chromosome_fp_bp"]]) if "chromosome_fp_bp" in idx and f[idx["chromosome_fp_bp"]] else None,
                "true_plasmid_count": int(f[idx["true_plasmid_count"]]) if "true_plasmid_count" in idx and f[idx["true_plasmid_count"]] else None,
                # Graded plasmid-recovery completeness bands (score_plasmids.py):
                # supplementary to plasmid_recall's single configured threshold
                # above, an intermediate view between "any recall" and perfect
                # recovery. Gracefully absent (never 0) when undefined, matching
                # plasmid_recall's own convention immediately above.
                "strict_precision": float(f[idx["strict_precision"]]) if "strict_precision" in idx and f[idx["strict_precision"]] else None,
                "recall_ceiling": float(f[idx["recall_ceiling"]]) if "recall_ceiling" in idx and f[idx["recall_ceiling"]] else None,
                "ceiling_adjusted_recall": float(f[idx["ceiling_adjusted_recall"]]) if "ceiling_adjusted_recall" in idx and f[idx["ceiling_adjusted_recall"]] else None,
                "redundant_pred_bp": int(f[idx["redundant_pred_bp"]]) if "redundant_pred_bp" in idx and f[idx["redundant_pred_bp"]] else None,
                "plasmid_recall_ge50": float(f[idx["plasmid_recall_ge50"]]) if "plasmid_recall_ge50" in idx and f[idx["plasmid_recall_ge50"]] else None,
                "plasmid_recall_ge90": float(f[idx["plasmid_recall_ge90"]]) if "plasmid_recall_ge90" in idx and f[idx["plasmid_recall_ge90"]] else None,
                "complete_circular_plasmid_recall": float(f[idx["complete_circular_plasmid_recall"]]) if "complete_circular_plasmid_recall" in idx and f[idx["complete_circular_plasmid_recall"]] else None,
            })
    return rows


def read_status(path):
    counts = defaultdict(lambda: {"completed": 0, "reused": 0, "failed": 0, "skipped": 0})
    if not path:
        return counts
    try:
        fh = open(path)
    except FileNotFoundError:
        return counts
    with fh:
        header = fh.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        required = {"tool", "status"}
        if not required.issubset(idx):
            raise ValueError("status file must contain tool and status columns")
        for line in fh:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            status = f[idx["status"]]
            if status in counts[f[idx["tool"]]]:
                counts[f[idx["tool"]]][status] += 1
    return counts


def failure_class(reason):
    """'resource' when the recorded exit code is a timeout/SIGKILL, else 'tool'.

    A failure with no recorded exit code (a status file from before exit codes
    were captured) is 'tool', which is the conservative reading: it is scored as
    the tool's failure exactly as it always was.
    """
    match = EXIT_CODE.search(reason or "")
    if match and int(match.group(1)) in RESOURCE_EXIT_CODES:
        return "resource"
    return "tool"


def read_failures(path):
    """[(tool, sample, failure_class)] for every failed run in tool_status.tsv."""
    failures = []
    if not path:
        return failures
    try:
        handle = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        return failures
    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "sample" not in reader.fieldnames:
            return failures
        for row in reader:
            if row.get("status") == "failed" and row.get("sample") and row.get("tool"):
                failures.append((row["tool"], row["sample"], failure_class(row.get("reason"))))
    return failures


def read_failed_samples(path, resource_policy="score-zero"):
    """tool -> samples whose run failed and should score F1 = 0 for that tool.

    resource_policy 'score-zero' (default, the long-standing behaviour) treats
    every failure as the tool's result. 'exclude' leaves out failures whose exit
    code says the machine ran out of time or memory; the sample then has no F1
    for that tool and the shared-sample rule removes it from every tool's
    ranking, so a small machine cannot push a tool down the leaderboard.
    """
    failed = defaultdict(set)
    for tool, sample, kind in read_failures(path):
        if kind == "resource" and resource_policy == "exclude":
            continue
        failed[tool].add(sample)
    return failed


def read_resource_failure_counts(path):
    """tool -> number of failed runs classified as resource failures."""
    counts = defaultdict(int)
    for tool, _, kind in read_failures(path):
        if kind == "resource":
            counts[tool] += 1
    return counts


def read_database_overlap(path):
    """(sample, tool) -> overlap_status from flag_database_overlap.py output."""
    overlap = {}
    if not path or not Path(path).is_file():
        return overlap
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("sample") and row.get("tool"):
                overlap[(row["sample"], row["tool"])] = row.get("overlap_status", "")
    return overlap


def summarise(rows, status_counts, failed_samples=None, clusters=None, overlap=None,
              plasmid_samples=None, resource_failures=None):
    by_tool = defaultdict(lambda: {"precision": [], "recall": [], "f1": [], "plasmid_recall": [], "bin_f1": [], "pr_auc": [], "perfect": [], "strict": [], "n": 0,
                                   "zero_plasmid_specificity": [], "zero_plasmid_fp_bp": [], "n_zero_plasmid": 0,
                                   "nmi": [], "vi": [],
                                   "plasmid_recall_ge50": [], "plasmid_recall_ge90": [], "complete_circular_plasmid_recall": [],
                                   "strict_precision": [], "redundant_pred_bp": [],
                                   "recall_ceiling": [], "ceiling_adjusted_recall": []})
    for r in rows:
        t = by_tool[r["tool"]]
        # Undefined (score_plasmids.py) on a zero-true-plasmid isolate or one
        # with no true plasmid to recall -- excluded from the mean here
        # exactly like plasmid_recall/bin_f1/pr_auc below, never coerced to 0.
        if r["precision"] is not None: t["precision"].append(r["precision"])
        if r["recall"] is not None: t["recall"].append(r["recall"])
        if r["f1"] is not None: t["f1"].append(r["f1"])
        if r["plasmid_recall"] is not None:
            t["plasmid_recall"].append(r["plasmid_recall"])
        if r.get("strict_precision") is not None:
            t["strict_precision"].append(r["strict_precision"])
        if r.get("recall_ceiling") is not None:
            t["recall_ceiling"].append(r["recall_ceiling"])
        if r.get("ceiling_adjusted_recall") is not None:
            t["ceiling_adjusted_recall"].append(r["ceiling_adjusted_recall"])
        if r.get("redundant_pred_bp") is not None:
            t["redundant_pred_bp"].append(r["redundant_pred_bp"])
        if r["plasmid_recall_ge50"] is not None:
            t["plasmid_recall_ge50"].append(r["plasmid_recall_ge50"])
        if r["plasmid_recall_ge90"] is not None:
            t["plasmid_recall_ge90"].append(r["plasmid_recall_ge90"])
        if r["complete_circular_plasmid_recall"] is not None:
            t["complete_circular_plasmid_recall"].append(r["complete_circular_plasmid_recall"])
        if r["bin_f1"] is not None: t["bin_f1"].append(r["bin_f1"])
        if r["nmi"] is not None: t["nmi"].append(r["nmi"])
        if r["variation_of_information"] is not None: t["vi"].append(r["variation_of_information"])
        if r["pr_auc"] is not None: t["pr_auc"].append(r["pr_auc"])
        if r["perfect_reference_recovery"] in ("yes", "no"):
            t["perfect"].append(r["perfect_reference_recovery"] == "yes")
        if r["strict_reference_reconstruction"] in ("yes", "no"):
            t["strict"].append(r["strict_reference_reconstruction"] == "yes")
        # Negative-control summary: isolates with zero true plasmids are the
        # only ones that can measure false-positive plasmid calls directly
        # (precision/recall/f1 are undefined there) -- kept as its own
        # separate tally, never blended into the main ranking metrics above.
        if r["true_plasmid_count"] == 0:
            t["n_zero_plasmid"] += 1
            if r["isolate_specificity"] is not None:
                t["zero_plasmid_specificity"].append(r["isolate_specificity"])
            if r["chromosome_fp_bp"] is not None:
                t["zero_plasmid_fp_bp"].append(r["chromosome_fp_bp"])
        t["n"] += 1

    # Rank every tool on the SAME samples. A sample a tool crashed, timed out
    # or was not scored on has no row for that tool; averaging each tool over
    # its own surviving samples would let a tool that fails on hard isolates
    # outrank one that attempted them. The ranking F1 (mean_f1, its CI and
    # median) is therefore computed over the samples every F1-bearing tool in
    # this leaderboard was scored on. The per-tool own-sample mean is kept as
    # mean_f1_all_scored for transparency, never for ranking.
    #
    # A sample on which a tool's own run FAILED (tool_status.tsv) is not an
    # infrastructure gap but the tool's result: on a plasmid-bearing sample
    # it counts as F1 = 0 for that tool's ranking, so one crashing tool
    # cannot shrink every other tool's ranking set. Samples merely missing
    # (no status, skipped, or a scoring failure) are handled by the
    # shared-sample rule instead.
    f1_by_tool = defaultdict(dict)
    # Which samples carry true plasmid is a property of the sample, not of the
    # track, so the caller may pass the set found across every track. Without it
    # a track whose tools all crashed would have no plasmid-bearing sample here.
    plasmid_samples = set(plasmid_samples or ())
    for r in rows:
        if r["f1"] is not None:
            f1_by_tool[r["tool"]][r["sample"]] = r["f1"]
            plasmid_samples.add(r["sample"])
    failure_zero = defaultdict(int)
    for tool, samples in (failed_samples or {}).items():
        for sample in samples:
            if sample in plasmid_samples and sample not in f1_by_tool[tool]:
                # A tool that failed on EVERY sample has no score rows and so is
                # not in by_tool yet. Touch it so it still gets a leaderboard row
                # (F1 = 0 on every plasmid-bearing sample) instead of vanishing,
                # which would let total failure look better than partial failure.
                _ = by_tool[tool]
                f1_by_tool[tool][sample] = 0.0
                failure_zero[tool] += 1
    ranked_tools = [tool for tool, values in f1_by_tool.items() if values]
    shared = (set.intersection(*(set(f1_by_tool[tool]) for tool in ranked_tools))
              if ranked_tools else set())
    ranking_basis = "shared_samples" if shared else "own_samples_no_overlap"

    summary = []
    for tool, d in by_tool.items():
        if shared and tool in f1_by_tool:
            ranking_samples = sorted(shared)
            ranking_f1 = [f1_by_tool[tool][sample] for sample in ranking_samples]
        else:
            ranking_samples = [r["sample"] for r in rows if r["tool"] == tool and r["f1"] is not None]
            ranking_f1 = list(d["f1"])
        groups = cluster_labels(ranking_samples, clusters)
        f1_ci_low, f1_ci_high = bootstrap_ci(ranking_f1, groups=groups)
        summary.append({
            "tool": tool,
            "n_samples": d["n"],
            "mean_precision": statistics.mean(d["precision"]) if d["precision"] else None,
            "mean_recall": statistics.mean(d["recall"]) if d["recall"] else None,
            "mean_f1": statistics.mean(ranking_f1) if ranking_f1 else None,
            "n_ranking_samples": len(ranking_f1),
            "ranking_basis": ranking_basis if ranking_f1 else "",
            "mean_f1_all_scored": statistics.mean(d["f1"]) if d["f1"] else None,
            "n_f1_scored": len(d["f1"]),
            "n_failures_scored_zero": failure_zero.get(tool, 0),
            "n_failed_resource": (resource_failures or {}).get(tool, 0),
            "f1_ci_low": f1_ci_low,
            "f1_ci_high": f1_ci_high,
            "n_independent_clusters": len(set(groups)),
            "median_f1": statistics.median(ranking_f1) if ranking_f1 else None,
            "mean_plasmid_recall": statistics.mean(d["plasmid_recall"]) if d["plasmid_recall"] else None,
            # Supplementary robustness diagnostics (never ranking metrics).
            "mean_strict_precision": statistics.mean(d["strict_precision"]) if d["strict_precision"] else None,
            "total_redundant_pred_bp": sum(d["redundant_pred_bp"]) if d["redundant_pred_bp"] else None,
            "mean_recall_ceiling": statistics.mean(d["recall_ceiling"]) if d["recall_ceiling"] else None,
            # Reference-database overlap screen (flag_database_overlap.py):
            # how many of this tool's samples may already be inside its own
            # database, and its mean F1 on samples that cannot be.
            **overlap_summary(tool, rows, overlap),
            "mean_ceiling_adjusted_recall": statistics.mean(d["ceiling_adjusted_recall"]) if d["ceiling_adjusted_recall"] else None,
            # Graded plasmid-recovery completeness bands (score_plasmids.py):
            # supplementary breakdowns between "any recall" (mean_plasmid_recall
            # above, at its own configured threshold) and perfect recovery
            # (reference_perfect_recovery_rate below) -- never a ranking
            # replacement for mean_f1.
            "mean_plasmid_recall_ge50": statistics.mean(d["plasmid_recall_ge50"]) if d["plasmid_recall_ge50"] else None,
            "mean_plasmid_recall_ge90": statistics.mean(d["plasmid_recall_ge90"]) if d["plasmid_recall_ge90"] else None,
            "mean_complete_circular_plasmid_recall": statistics.mean(d["complete_circular_plasmid_recall"]) if d["complete_circular_plasmid_recall"] else None,
            "n_complete_circular_assessed": len(d["complete_circular_plasmid_recall"]),
            "n_zero_plasmid_isolates": d["n_zero_plasmid"],
            "mean_zero_plasmid_specificity": statistics.mean(d["zero_plasmid_specificity"]) if d["zero_plasmid_specificity"] else None,
            "total_zero_plasmid_chromosome_fp_bp": sum(d["zero_plasmid_fp_bp"]) if d["zero_plasmid_fp_bp"] else None,
            "mean_bin_f1": statistics.mean(d["bin_f1"]) if d["bin_f1"] else None,
            "n_bin_scored": len(d["bin_f1"]),
            # Supplementary, never a ranking replacement -- see
            # score_bins.py's clustering_agreement().
            "mean_nmi": statistics.mean(d["nmi"]) if d["nmi"] else None,
            "mean_variation_of_information": statistics.mean(d["vi"]) if d["vi"] else None,
            # Supplementary, never a ranking replacement: only defined for
            # tools that expose a probability (adapters/SCORES.md); ranking
            # below stays on mean_f1 so every tool remains comparable.
            "mean_pr_auc": statistics.mean(d["pr_auc"]) if d["pr_auc"] else None,
            "n_pr_scored": len(d["pr_auc"]),
            "n_reference_perfect_assessed": len(d["perfect"]),
            "reference_perfect_recovery_rate": statistics.mean(d["perfect"]) if d["perfect"] else None,
            "n_strict_reconstruction_assessed": len(d["strict"]),
            "strict_reference_reconstruction_rate": statistics.mean(d["strict"]) if d["strict"] else None,
            "n_completed": status_counts[tool]["completed"] + status_counts[tool]["reused"],
            "n_failed": status_counts[tool]["failed"],
            "n_skipped": status_counts[tool]["skipped"],
        })
    # Rank by shared-sample mean F1 (descending). A tool scored only on
    # zero-true-plasmid isolates has no defined mean_f1 at all -- sort it last
    # rather than crashing the comparison against a real float.
    # Tie-break on the tool name so equal scores always rank the same way. Without
    # it the order followed scores.tsv, which made the "runner-up" in the
    # significance test depend on file order.
    summary.sort(key=lambda x: (x["mean_f1"] is None, -(x["mean_f1"] or 0.0), x["tool"]))
    for rank, row in enumerate(summary, start=1):
        row["rank"] = rank
    return summary


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


def overlap_summary(tool, rows, overlap):
    if not overlap:
        return {"n_possible_db_overlap": None, "n_after_database": None, "mean_f1_after_database": None,
                "n_unknown_overlap": None}
    statuses = [overlap.get((r["sample"], tool), "") for r in rows if r["tool"] == tool]
    after = [r["f1"] for r in rows if r["tool"] == tool and r["f1"] is not None
             and overlap.get((r["sample"], tool)) == "after_database"]
    return {
        "n_possible_db_overlap": statuses.count("possible_overlap"),
        "n_after_database": statuses.count("after_database"),
        "mean_f1_after_database": statistics.mean(after) if after else None,
        # Pairs the screen could not judge (database release date not filled in,
        # or truth release date unavailable). "0 possible, 0 after" is otherwise
        # indistinguishable from "checked and clean".
        "n_unknown_overlap": statuses.count("unknown"),
    }


def leakage_unassessed(overlap):
    """True when the overlap screen ran but could not judge a single pair.

    Every status is then 'unknown' (or 'no_reference_database'): the usual cause
    is config/tool_database_releases.tsv still having blank release dates. In
    that state the leaderboard's overlap columns read 0 / 0 / blank, which looks
    like a clean result and is not one.
    """
    if not overlap:
        return False
    statuses = set(overlap.values())
    return "unknown" in statuses and not (statuses & {"possible_overlap", "after_database"})


LEAKAGE_UNASSESSED_NOTE = (
    "Database leakage was NOT assessed. Every database-using tool/sample pair is 'unknown' because "
    "no database release date has been filled in (config/tool_database_releases.tsv). Tools that "
    "score contigs against a plasmid database or a model trained on one may have seen the truth "
    "genomes, so their F1 can be inflated relative to new isolates. Treat their ranking as "
    "provisional until the dates are filled in and the screen is re-run.")


def bootstrap_ci(values, iterations=1000, groups=None):
    """Deterministic percentile CI for the mean F1; descriptive, not a p-value.

    With groups, whole clusters are resampled (cluster bootstrap), so
    correlated isolates from one study widen the interval instead of
    narrowing it. At least 5 independent units are required.
    """
    units = resampling_units(values, groups)
    # Intervals from very small cohorts imply a precision the data do not have.
    if len(values) < 5 or len(units) < 5:
        return None, None
    rng = random.Random(20260831)
    means = sorted(statistics.mean([value for unit in rng.choices(units, k=len(units)) for value in unit])
                   for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def paired_permutation_pvalue(differences, iterations=10000, groups=None):
    """Two-sided sign-flip permutation p-value for paired mean differences.

    With groups, every difference in a cluster is flipped together, which is
    the valid null when isolates within a study are correlated. At least 5
    independent units are required.
    """
    units = resampling_units(differences, groups)
    if len(differences) < 5 or len(units) < 5:
        return None
    observed = abs(statistics.mean(differences))
    rng = random.Random(20260901)
    extreme = 0
    for _ in range(iterations):
        signed = []
        for unit in units:
            sign = 1 if rng.randrange(2) else -1
            signed.extend(sign * item for item in unit)
        value = abs(statistics.mean(signed))
        extreme += value >= observed
    return (extreme + 1) / (iterations + 1)


def holm_adjust(pvalues):
    """Return Holm-adjusted p-values keyed by comparison index."""
    ordered = sorted(((pvalue, index) for index, pvalue in enumerate(pvalues)
                      if pvalue is not None), key=lambda item: item[0])
    adjusted = [None] * len(pvalues)
    previous = 0.0
    total = len(ordered)
    for rank, (pvalue, index) in enumerate(ordered):
        value = min(1.0, max(previous, pvalue * (total - rank)))
        adjusted[index] = value
        previous = value
    return adjusted


def compute_comparisons(rows, failed_samples=None, clusters=None, plasmid_samples=None):
    """Paired, shared-sample, sign-flip permutation comparisons for every
    pair of tools, Holm-adjusted across all pairs computed here. Shared by
    write_comparisons() (writes benchmark.paired_comparisons.tsv) and
    attach_significance() (derives the leaderboard's significant_vs_runner_up
    flag), so both always agree on the same underlying test."""
    by_tool = defaultdict(dict)
    for row in rows:
        # f1 is undefined (None) for a zero-true-plasmid isolate -- excluded
        # from the paired comparison entirely for that sample/tool, same as
        # it is excluded from summarise()'s mean_f1 above, rather than
        # letting a None reach the subtraction below.
        if row["f1"] is not None:
            by_tool[row["tool"]][row["sample"]] = row["f1"]
    # Same rule as summarise(): a failed tool run on a plasmid-bearing sample
    # is that tool's F1 = 0, so the test and the ranking judge the same data.
    plasmid_samples = set(plasmid_samples or ()) | {
        sample for values in by_tool.values() for sample in values}
    for tool, samples in (failed_samples or {}).items():
        for sample in samples:
            if sample in plasmid_samples and sample not in by_tool[tool]:
                by_tool[tool][sample] = 0.0   # also adds a tool that failed everywhere
    tools = sorted(by_tool)
    comparisons = []
    for i, a in enumerate(tools):
        for b in tools[i + 1:]:
            shared = sorted(set(by_tool[a]) & set(by_tool[b]))
            diffs = [by_tool[a][sample] - by_tool[b][sample] for sample in shared]
            if not diffs:
                continue
            groups = cluster_labels(shared, clusters)
            low, high = bootstrap_ci(diffs, groups=groups)
            comparisons.append({
                "tool_a": a, "tool_b": b, "paired_samples": len(shared),
                "paired_clusters": len(set(groups)),
                "mean_f1_difference": statistics.mean(diffs), "difference_ci_low": low,
                "difference_ci_high": high,
                "permutation_p_value": paired_permutation_pvalue(diffs, groups=groups),
                "wins_a": sum(x > 0 for x in diffs), "ties": sum(x == 0 for x in diffs),
                "wins_b": sum(x < 0 for x in diffs),
            })
    for row, adjusted in zip(comparisons, holm_adjust([x["permutation_p_value"] for x in comparisons])):
        row["permutation_p_value_holm"] = adjusted
    return comparisons


def attach_significance(summary, comparisons, alpha=0.05):
    """Mark the top-ranked tool as significantly better than the runner-up
    using the SAME paired, shared-sample, sign-flip permutation test (Holm-
    adjusted) already computed by compute_comparisons() -- never a bootstrap-
    CI-overlap heuristic, which is a weaker and different claim for a paired
    comparison. Every row gets a value: "not_assessed" when there is no
    runner-up, or the pair was never tested (fewer than 5 shared samples,
    paired_permutation_pvalue's own existing gate); True/False otherwise.
    Mutates summary in place; also returns it."""
    for row in summary:
        row["significant_vs_runner_up"] = "not_assessed"
    if len(summary) < 2:
        return summary
    top, runner_up = summary[0]["tool"], summary[1]["tool"]
    pair = next(
        (c for c in comparisons
         if {c["tool_a"], c["tool_b"]} == {top, runner_up}),
        None,
    )
    if pair is None or pair["permutation_p_value_holm"] is None:
        return summary
    summary[0]["significant_vs_runner_up"] = pair["permutation_p_value_holm"] < alpha
    return summary


def write_comparisons(rows, path, comparisons=None):
    if comparisons is None:
        comparisons = compute_comparisons(rows)
    with open(path, "w") as handle:
        handle.write("tool_a\ttool_b\tpaired_samples\tmean_f1_difference\tdifference_ci_low\tdifference_ci_high\tpermutation_p_value\tpermutation_p_value_holm\twins_a\tties\twins_b\tanalysis_track\tpaired_clusters\n")
        for row in comparisons:
            low = f"{row['difference_ci_low']:.4f}" if row["difference_ci_low"] is not None else ""
            high = f"{row['difference_ci_high']:.4f}" if row["difference_ci_high"] is not None else ""
            pvalue = row["permutation_p_value"]
            adjusted = row["permutation_p_value_holm"]
            pvalue_text = f"{pvalue:.6f}" if pvalue is not None else ""
            adjusted_text = f"{adjusted:.6f}" if adjusted is not None else ""
            handle.write(
                f"{row['tool_a']}\t{row['tool_b']}\t{row['paired_samples']}\t"
                f"{row['mean_f1_difference']:.4f}\t{low}\t{high}\t{pvalue_text}\t"
                f"{adjusted_text}\t{row['wins_a']}\t{row['ties']}\t{row['wins_b']}\t"
                f"{row.get('analysis_track', '')}\t{row.get('paired_clusters', '')}\n"
            )


def write_tsv(summary, path):
    cols = ["rank", "analysis_track", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision",
            "mean_recall", "mean_plasmid_recall",
            "mean_plasmid_recall_ge50", "mean_plasmid_recall_ge90",
            "n_complete_circular_assessed", "mean_complete_circular_plasmid_recall",
            "n_bin_scored", "mean_bin_f1", "mean_nmi", "mean_variation_of_information", "n_pr_scored", "mean_pr_auc",
            "n_reference_perfect_assessed", "reference_perfect_recovery_rate", "n_strict_reconstruction_assessed", "strict_reference_reconstruction_rate",
            "mean_f1", "n_ranking_samples", "ranking_basis", "f1_ci_low", "f1_ci_high", "n_independent_clusters", "median_f1",
            "mean_f1_all_scored", "n_f1_scored", "n_failures_scored_zero", "significant_vs_runner_up",
            "mean_strict_precision", "total_redundant_pred_bp", "mean_recall_ceiling", "mean_ceiling_adjusted_recall",
            "n_possible_db_overlap", "n_after_database", "mean_f1_after_database",
            "n_zero_plasmid_isolates", "mean_zero_plasmid_specificity", "total_zero_plasmid_chromosome_fp_bp",
            "n_failed_resource", "n_unknown_overlap"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                s.get("rank", i), s.get("analysis_track", ""), s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
                f"{s['mean_precision']:.4f}" if s["mean_precision"] is not None else "",
                f"{s['mean_recall']:.4f}" if s["mean_recall"] is not None else "",
                f"{s['mean_plasmid_recall']:.4f}" if s["mean_plasmid_recall"] is not None else "",
                f"{s['mean_plasmid_recall_ge50']:.4f}" if s["mean_plasmid_recall_ge50"] is not None else "",
                f"{s['mean_plasmid_recall_ge90']:.4f}" if s["mean_plasmid_recall_ge90"] is not None else "",
                s['n_complete_circular_assessed'],
                f"{s['mean_complete_circular_plasmid_recall']:.4f}" if s["mean_complete_circular_plasmid_recall"] is not None else "",
                s['n_bin_scored'], f"{s['mean_bin_f1']:.4f}" if s['mean_bin_f1'] is not None else "",
                f"{s['mean_nmi']:.4f}" if s['mean_nmi'] is not None else "",
                f"{s['mean_variation_of_information']:.4f}" if s['mean_variation_of_information'] is not None else "",
                s['n_pr_scored'], f"{s['mean_pr_auc']:.4f}" if s['mean_pr_auc'] is not None else "",
                s['n_reference_perfect_assessed'], f"{s['reference_perfect_recovery_rate']:.4f}" if s['reference_perfect_recovery_rate'] is not None else "",
                s['n_strict_reconstruction_assessed'], f"{s['strict_reference_reconstruction_rate']:.4f}" if s['strict_reference_reconstruction_rate'] is not None else "",
                f"{s['mean_f1']:.4f}" if s["mean_f1"] is not None else "",
                s.get("n_ranking_samples", ""), s.get("ranking_basis", ""),
                f"{s['f1_ci_low']:.4f}" if s["f1_ci_low"] is not None else "",
                f"{s['f1_ci_high']:.4f}" if s["f1_ci_high"] is not None else "",
                s.get("n_independent_clusters", ""),
                f"{s['median_f1']:.4f}" if s["median_f1"] is not None else "",
                f"{s['mean_f1_all_scored']:.4f}" if s.get("mean_f1_all_scored") is not None else "",
                s.get("n_f1_scored", ""), s.get("n_failures_scored_zero", 0),
                # Derived from the SAME paired, shared-sample, sign-flip
                # permutation test (Holm-adjusted) as
                # benchmark.paired_comparisons.tsv -- see attach_significance().
                # Never a bootstrap-CI-overlap heuristic.
                s.get("significant_vs_runner_up", "not_assessed"),
                f"{s['mean_strict_precision']:.4f}" if s.get("mean_strict_precision") is not None else "",
                s["total_redundant_pred_bp"] if s.get("total_redundant_pred_bp") is not None else "",
                f"{s['mean_recall_ceiling']:.4f}" if s.get("mean_recall_ceiling") is not None else "",
                f"{s['mean_ceiling_adjusted_recall']:.4f}" if s.get("mean_ceiling_adjusted_recall") is not None else "",
                s["n_possible_db_overlap"] if s.get("n_possible_db_overlap") is not None else "",
                s["n_after_database"] if s.get("n_after_database") is not None else "",
                f"{s['mean_f1_after_database']:.4f}" if s.get("mean_f1_after_database") is not None else "",
                # Negative-control summary: only meaningful for isolates with
                # zero true plasmids (score_plasmids.py's isolate_specificity/
                # chromosome_fp_bp), never blended into the ranking metrics above.
                s["n_zero_plasmid_isolates"],
                f"{s['mean_zero_plasmid_specificity']:.4f}" if s["mean_zero_plasmid_specificity"] is not None else "",
                s["total_zero_plasmid_chromosome_fp_bp"] if s["total_zero_plasmid_chromosome_fp_bp"] is not None else "",
                s.get("n_failed_resource", 0),
                s["n_unknown_overlap"] if s.get("n_unknown_overlap") is not None else "",
            ]) + "\n")


def format_rate(rate, assessed):
    """Display an availability-aware rate without turning missing evidence into zero."""
    return f"{rate:.1%} (n={assessed})" if rate is not None else "not assessed"


def write_md(summary, path, notes=()):
    # Deliberately narrower than write_tsv()'s own `cols` list: the graded
    # plasmid-recovery completeness tiers (mean_plasmid_recall_ge50/ge90,
    # mean_complete_circular_plasmid_recall) and NMI/VI/PR-AUC are
    # programmatic/supplementary columns already carried in full by the TSV
    # and the HTML report's own dedicated sections -- this Markdown table is
    # kept to the compact, at-a-glance ranking view it has always been,
    # never meant to duplicate every column the TSV carries. Not an
    # oversight; add a column here only if it belongs in the headline view,
    # not just because write_tsv()/build_html_report.py gained one.
    with open(path, "w") as fh:
        fh.write("# Plasmid reconstruction leaderboard\n\n")
        fh.write("Ranked by mean base-level F1 over the samples every ranked tool was "
                 "scored on (positive class = plasmid). Tools are ranked only within "
                 "their own input track, never across tracks.\n\n")
        tracks = []
        for row in summary:
            track = row.get("analysis_track", "")
            if track not in tracks:
                tracks.append(track)
        for track in tracks:
            track_rows = [row for row in summary if row.get("analysis_track", "") == track]
            write_md_table(fh, track_rows, track if len(tracks) > 1 else None)
        for note in notes:
            fh.write(f"\n> **Warning:** {note}\n")
        fh.write("\n_Recall = completeness (fraction of true plasmid bases "
                 "recovered). Plasmid recall = fraction of truth plasmids meeting the configured "
                 "recovery threshold; it is not available for legacy score rows. Precision = 1 - "
                 "chromosomal contamination. A tool that predicts nothing on a plasmid-bearing "
                 "sample scores F1 = 0 there. Mean F1, its CI and median use only the samples shared by "
                 "every ranked tool in the track (\"Ranked on\"). A tool run that failed on a "
                 "plasmid-bearing sample counts as F1 = 0 for that tool; a sample missing for any "
                 "other reason is removed from every tool's ranking. Perfect reference recovery requires F1/plasmid recall of 1 "
                 "and zero ambiguous, unmapped, and off-truth predicted bases. Strict reconstruction also "
                 "requires perfect available bin diagnostics; neither measure proves nucleotide identity or closure._\n")


def write_md_table(fh, summary, track=None):
    """One ranked Markdown table; a heading names the track when several exist."""
    if track:
        fh.write(f"## Track: {track}\n\n")
    fh.write("| Rank | Tool | Scored | Completed | Failed | Skipped | Mean precision | "
             "Mean base recall | Mean plasmid recall | Perfect reference recovery | Strict reconstruction | **Mean F1** | Ranked on | 95% F1 CI | Median F1 | Significant vs runner-up |\n")
    fh.write("|" + "|".join(["---:", ":---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", ":---"]) + "|\n")
    for i, s in enumerate(summary, start=1):
        plasmid_recall = f"{s['mean_plasmid_recall']:.3f}" if s["mean_plasmid_recall"] is not None else "not annotated"
        clusters_n = s.get("n_independent_clusters")
        ci = (f"{s['f1_ci_low']:.3f}–{s['f1_ci_high']:.3f}"
              + (f" ({clusters_n} clusters)" if clusters_n and clusters_n < s.get("n_ranking_samples", 0) else "")
              if s["f1_ci_low"] is not None else "< 5 independent units")
        # A tool scored only on zero-true-plasmid isolates has no defined
        # mean precision/recall/f1 at all (score_plasmids.py) -- "not
        # applicable" rather than crashing on a None float format.
        mean_precision = f"{s['mean_precision']:.3f}" if s["mean_precision"] is not None else "n/a"
        mean_recall = f"{s['mean_recall']:.3f}" if s["mean_recall"] is not None else "n/a"
        mean_f1 = f"{s['mean_f1']:.3f}" if s["mean_f1"] is not None else "n/a"
        median_f1 = f"{s['median_f1']:.3f}" if s["median_f1"] is not None else "n/a"
        # Only the winner (rank 1) ever carries a real value here -- see
        # attach_significance(). Paired sign-flip permutation test on
        # shared samples, Holm-adjusted across every pairwise comparison.
        if s.get("ranking_basis") == "shared_samples":
            ranked_on = f"{s.get('n_ranking_samples', '')} shared"
        elif s.get("n_ranking_samples"):
            ranked_on = f"{s.get('n_ranking_samples')} own (no shared samples)"
        else:
            ranked_on = "n/a"
        significance = s.get("significant_vs_runner_up", "not_assessed")
        significance_text = {True: "yes (paired permutation, Holm-adjusted)",
                             False: "no (paired permutation, Holm-adjusted)"}.get(significance, "not assessed")
        fh.write(
            f"| {s.get('rank', i)} | {s['tool']} | {s['n_samples']} | {s['n_completed']} | {s['n_failed']} | {s['n_skipped']} | "
            f"{mean_precision} | {mean_recall} | "
            f"{plasmid_recall} | {format_rate(s['reference_perfect_recovery_rate'], s['n_reference_perfect_assessed'])} | "
            f"{format_rate(s['strict_reference_reconstruction_rate'], s['n_strict_reconstruction_assessed'])} | "
            f"**{mean_f1}** | {ranked_on} | {ci} | {median_f1} | {significance_text} |\n"
        )
    fh.write("\n")


TRACK_ORDER = ("short_read", "long_read", "hybrid")


def ranked_tracks(rows, status_counts, failed_samples=None, clusters=None, overlap=None,
                  tool_tracks=None, resource_failures=None):
    """Summarise, rank and test each declared input track on its own.

    Returns [(track, rows, summary, comparisons)] in a stable order. Tools are
    ranked, and significance is tested, only against tools in the same track
    -- a long-read tool is never ranked against a short-read one.

    tool_tracks maps tool -> declared track (the capability registry). It is
    only consulted for a tool with no score rows at all, which is exactly the
    tool that failed on every sample: its rows cannot say which track it is in.
    """
    tracks = defaultdict(list)
    for row in rows:
        tracks[row["analysis_track"]].append(row)

    row_tracks = defaultdict(set)
    for row in rows:
        row_tracks[row["tool"]].add(row["analysis_track"])

    def tracks_of(tool):
        if row_tracks.get(tool):
            return row_tracks[tool]
        # Same default read_scores() applies to a row with no analysis_track.
        return {(tool_tracks or {}).get(tool) or "short_read"}

    plasmid_samples = {row["sample"] for row in rows if row["f1"] is not None}
    # A track in which every tool failed everywhere has no score rows, so it would
    # not appear at all. Create it so those failures still produce a leaderboard.
    for tool, samples in (failed_samples or {}).items():
        if samples & plasmid_samples:
            for track in tracks_of(tool):
                tracks.setdefault(track, [])
    ordered = sorted(tracks, key=lambda t: (TRACK_ORDER.index(t) if t in TRACK_ORDER else len(TRACK_ORDER), t))
    result = []
    for track in ordered:
        track_rows = tracks[track]
        # Failures only count in the track their tool belongs to.
        track_failed = {tool: samples for tool, samples in (failed_samples or {}).items()
                        if track in tracks_of(tool)}
        track_resource = {tool: n for tool, n in (resource_failures or {}).items()
                          if track in tracks_of(tool)}
        summary = summarise(track_rows, status_counts, track_failed, clusters, overlap,
                            plasmid_samples=plasmid_samples, resource_failures=track_resource)
        comparisons = compute_comparisons(track_rows, track_failed, clusters,
                                          plasmid_samples=plasmid_samples)
        for row in summary:
            row["analysis_track"] = track
        for row in comparisons:
            row["analysis_track"] = track
        attach_significance(summary, comparisons)
        result.append((track, track_rows, summary, comparisons))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True, help="combined scores TSV")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--tool-status", help="optional status TSV from stage 4")
    ap.add_argument("--sample-sheet", help="sample sheet used for the run; read for parent_sample_id.")
    ap.add_argument("--database-overlap", help="flag_database_overlap.py output; adds per-tool overlap counts "
                                               "and mean_f1_after_database.")
    ap.add_argument("--exclude-database-overlap", action="store_true",
                    help="drop sample x tool rows flagged possible_overlap before ranking.")
    ap.add_argument("--resource-failures", choices=("score-zero", "exclude"), default="score-zero",
                    help="how a run killed by a timeout or out-of-memory (exit code 124/137) is ranked. "
                         "score-zero (default): F1 = 0 for that tool, like any failure. exclude: the "
                         "sample drops out of every tool's ranking, so a small machine cannot penalise a tool. "
                         "Either way the count is reported as n_failed_resource.")
    ap.add_argument("--tool-capabilities",
                    help="capability registry (config/tool_capabilities.tsv); used to place a tool that "
                         "failed on every sample, and so has no score rows, in its declared track.")
    args = ap.parse_args()

    rows = read_scores(args.scores)
    if not rows:
        raise SystemExit("No score rows found in " + args.scores)

    # A headline leaderboard treats samples as independent. Depth-ladder points
    # share a genome, so ranking them would narrow the bootstrap CI and inflate
    # the effective n behind every paired permutation test.
    correlated = correlated_parents(rows, sample_parents(args.sample_sheet))
    if correlated:
        detail = "; ".join(f"{parent} -> {', '.join(samples)}"
                           for parent, samples in sorted(correlated.items())[:5])
        raise SystemExit(
            "ERROR: scores contain correlated samples derived from the same genome, "
            "which cannot produce a headline leaderboard: " + detail
            + (" ..." if len(correlated) > 5 else "")
            + "\nUse 'plasbench depth-report' to summarise a depth-ladder run."
        )
    try:
        status_counts = read_status(args.tool_status)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    clusters, cluster_column = sample_clusters(args.sample_sheet)
    if cluster_column:
        print(f"[aggregate] CIs and permutation tests resample by {cluster_column} "
              f"cluster ({len(set(clusters.values()))} cluster(s) in the sample sheet).")
    overlap = read_database_overlap(args.database_overlap)
    if args.exclude_database_overlap:
        if not overlap:
            raise SystemExit("ERROR: --exclude-database-overlap needs a non-empty --database-overlap file")
        before = len(rows)
        rows = [r for r in rows if overlap.get((r["sample"], r["tool"])) != "possible_overlap"]
        print(f"[aggregate] excluded {before - len(rows)} sample x tool row(s) flagged possible_overlap "
              f"with the tool's own reference database.")
        if not rows:
            raise SystemExit("ERROR: every score row was excluded as a possible database overlap")
    tool_tracks = {}
    registry_path = Path(args.tool_capabilities) if args.tool_capabilities else \
        Path(__file__).resolve().parent.parent / "config" / "tool_capabilities.tsv"
    if registry_path.is_file():
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tool_capabilities import read_capabilities
            tool_tracks = {tool: row["analysis_track"] for tool, row in read_capabilities(registry_path).items()}
        except (ValueError, ImportError) as exc:
            print(f"[aggregate] WARNING: could not read {registry_path}: {exc}. A tool that failed on "
                  f"every sample will be placed in the short_read track.")
    resource_failures = read_resource_failure_counts(args.tool_status)
    if resource_failures:
        verb = "scored as F1 = 0" if args.resource_failures == "score-zero" else "excluded from ranking"
        print(f"[aggregate] {sum(resource_failures.values())} run(s) ended in a timeout or out-of-memory kill "
              f"(exit code 124/137); {verb} (--resource-failures {args.resource_failures}).")
    per_track = ranked_tracks(rows, status_counts,
                              read_failed_samples(args.tool_status, args.resource_failures),
                              clusters, overlap, tool_tracks=tool_tracks,
                              resource_failures=resource_failures)
    # The combined files hold every track's leaderboard, each ranked within
    # its own track (rank restarts per track; analysis_track says which).
    # They never rank tools across tracks.
    summary = [row for _, _, track_summary, _ in per_track for row in track_summary]
    comparisons = [row for _, _, _, track_comparisons in per_track for row in track_comparisons]
    notes = []
    if leakage_unassessed(overlap):
        notes.append(LEAKAGE_UNASSESSED_NOTE)
        print(f"\n[aggregate] WARNING: {LEAKAGE_UNASSESSED_NOTE}\n")
    write_tsv(summary, args.out_prefix + ".leaderboard.tsv")
    write_md(summary, args.out_prefix + ".leaderboard.md", notes=notes)
    for track, _, track_summary, _ in per_track:
        write_tsv(track_summary, f"{args.out_prefix}.{track}.leaderboard.tsv")
        write_md(track_summary, f"{args.out_prefix}.{track}.leaderboard.md", notes=notes)
    write_comparisons(rows, args.out_prefix + ".paired_comparisons.tsv", comparisons=comparisons)

    # Print the leaderboard to stdout so it appears in the run log.
    def fmt3(value):
        return f"{value:.3f}" if value is not None else "n/a"
    for track, _, track_summary, _ in per_track:
        print(f"\n=== LEADERBOARD [{track}] (shared-sample mean F1, descending) ===")
        for s in track_summary:
            print(f"{s['rank']:>2}. {s['tool']:<16} "
                  f"F1={fmt3(s['mean_f1'])} on {s['n_ranking_samples']} sample(s)  "
                  f"P={fmt3(s['mean_precision'])}  R={fmt3(s['mean_recall'])}  "
                  f"(scored={s['n_samples']}, completed={s['n_completed']}, failed={s['n_failed']}, skipped={s['n_skipped']})")
            if s["n_f1_scored"] > s["n_ranking_samples"]:
                print(f"    note: {s['tool']} has F1 on {s['n_f1_scored']} sample(s); only the "
                      f"{s['n_ranking_samples']} shared by every ranked tool count toward rank "
                      f"(own-sample mean F1={fmt3(s['mean_f1_all_scored'])}).")

if __name__ == "__main__":
    main()
