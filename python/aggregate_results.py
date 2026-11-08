#!/usr/bin/env python3
"""
aggregate_results.py -- combine per-sample score rows into a per-tool
leaderboard, and emit a Markdown table for the final pitch.

Input : a scores TSV with the columns written by score_plasmids.py
        (sample, tool, ..., precision, recall, f1). Multiple rows per tool.
Output:
  * <out_prefix>.leaderboard.tsv   -- one row per tool with mean/median metrics
  * <out_prefix>.leaderboard.md    -- same, as a Markdown table (for README/pitch)
  * <out_prefix>.species.tsv       -- per tool x species (species balance)
  * <out_prefix>.reference_tiers.tsv -- per tool x reference tier (sensitivity)
  * <out_prefix>.headline_design.tsv -- which samples/species formed each headline

Headline design (python/headline_design.py, docs/METHODS.md "Endpoints"):
tools are ranked within (input track, task). Binning-capable tools are ranked
on the RECONSTRUCTION task by length-weighted binning F1; classifier-only
tools on the CLASSIFICATION task by base-level F1. The ranking score is a
species-balanced mean over reference tiers 1-2, with cluster-aware CIs.

Standard library only.
"""

import argparse
import math
import os
import csv
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

import headline_design as hd

fast_mean = hd.exact_mean  # bit-identical to statistics.mean, faster (see headline_design.exact_mean)

# Depth-ladder ids are "<parent>__<depth>x"; used only when a sheet has lost its
# parent_sample_id column, so a copied ladder sheet still cannot be ranked.
LADDER_SUFFIX = re.compile(r"^(?P<parent>.+)__\d+(?:\.\d+)?x$")

# scripts/04_run_tools.sh appends "exit_code=<n>" to a failed run's reason.
# 124 is `timeout`, 137 is SIGKILL (what the kernel OOM killer sends). Both say
# the machine ran out of something, not that the tool produced a wrong answer.
EXIT_CODE = re.compile(r"exit_code=(\d+)")
RESOURCE_EXIT_CODES = {124, 137}
# The container or command could not start (125/126/127): says nothing about the
# tool, so the run is never scored (scoring specification WP4).
INFRASTRUCTURE_EXIT_CODES = {125, 126, 127}
OUTCOME_STATE_FIELDS = ["analysis_track", "tool", "n_runs", "completed", "reused", "failed_tool", "failed_resource",
                        "infrastructure_failure", "not_applicable", "retried"]


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


def parse_sweep(text):
    """Comma-separated CPRR sweep counts -> list of ints; None when absent or malformed.

    A list whose length does not match the shared grid is treated as absent rather
    than being aligned to the wrong thresholds.
    """
    if not text:
        return None
    try:
        values = [int(v) for v in text.split(",")]
    except ValueError:
        return None
    return values if len(values) == len(hd.CPRR_SWEEP_THRESHOLDS) else None


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
                # Metric-rubric additions: contig-level classification (count-based and
                # length-weighted F1/MCC), bp-weighted ARI, assembly-aware binning F1, and
                # raw base counts for micro (pooled) averaging.
                "contig_f1_count": float(f[idx["contig_f1_count"]]) if "contig_f1_count" in idx and f[idx["contig_f1_count"]] else None,
                "contig_mcc_count": float(f[idx["contig_mcc_count"]]) if "contig_mcc_count" in idx and f[idx["contig_mcc_count"]] else None,
                "contig_f1_bp": float(f[idx["contig_f1_bp"]]) if "contig_f1_bp" in idx and f[idx["contig_f1_bp"]] else None,
                "contig_mcc_bp": float(f[idx["contig_mcc_bp"]]) if "contig_mcc_bp" in idx and f[idx["contig_mcc_bp"]] else None,
                "bin_ari": float(f[idx["bin_ari"]]) if "bin_ari" in idx and f[idx["bin_ari"]] else None,
                "lw_bin_f1_assembly_aware": float(f[idx["lw_bin_f1_assembly_aware"]]) if "lw_bin_f1_assembly_aware" in idx and f[idx["lw_bin_f1_assembly_aware"]] else None,
                "TP_bp": int(f[idx["TP_bp"]]) if "TP_bp" in idx and f[idx["TP_bp"]] else None,
                "FP_bp": int(f[idx["FP_bp"]]) if "FP_bp" in idx and f[idx["FP_bp"]] else None,
                "FN_bp": int(f[idx["FN_bp"]]) if "FN_bp" in idx and f[idx["FN_bp"]] else None,
                # Probability calibration (score_plasmids.py; probability-exposing tools only).
                "brier_score": float(f[idx["brier_score"]]) if "brier_score" in idx and f[idx["brier_score"]] else None,
                "expected_calibration_error": (float(f[idx["expected_calibration_error"]])
                                               if "expected_calibration_error" in idx and f[idx["expected_calibration_error"]] else None),
                # Headline/secondary endpoints from score_bins.py (via merge_bin_metrics.py).
                "lw_bin_f1": float(f[idx["lw_bin_f1"]]) if "lw_bin_f1" in idx and f[idx["lw_bin_f1"]] else None,
                "cprr_plasmids": int(f[idx["cprr_plasmids"]]) if "cprr_plasmids" in idx and f[idx["cprr_plasmids"]] else None,
                "cprr_correct": int(f[idx["cprr_correct"]]) if "cprr_correct" in idx and f[idx["cprr_correct"]] else None,
                "cprr_correct_without_identity": (int(f[idx["cprr_correct_without_identity"]])
                                                  if "cprr_correct_without_identity" in idx and f[idx["cprr_correct_without_identity"]] else None),
                "recall_ceiling": float(f[idx["recall_ceiling"]]) if "recall_ceiling" in idx and f[idx["recall_ceiling"]] else None,
                "ceiling_adjusted_recall": float(f[idx["ceiling_adjusted_recall"]]) if "ceiling_adjusted_recall" in idx and f[idx["ceiling_adjusted_recall"]] else None,
                "redundant_pred_bp": int(f[idx["redundant_pred_bp"]]) if "redundant_pred_bp" in idx and f[idx["redundant_pred_bp"]] else None,
                "plasmid_recall_ge50": float(f[idx["plasmid_recall_ge50"]]) if "plasmid_recall_ge50" in idx and f[idx["plasmid_recall_ge50"]] else None,
                "plasmid_recall_ge90": float(f[idx["plasmid_recall_ge90"]]) if "plasmid_recall_ge90" in idx and f[idx["plasmid_recall_ge90"]] else None,
                "complete_circular_plasmid_recall": float(f[idx["complete_circular_plasmid_recall"]]) if "complete_circular_plasmid_recall" in idx and f[idx["complete_circular_plasmid_recall"]] else None,
                # Scoring-specification additions (score_plasmids.py / score_bins.py).
                "mcc": float(f[idx["mcc"]]) if "mcc" in idx and f[idx["mcc"]] else None,
                "f2": float(f[idx["f2"]]) if "f2" in idx and f[idx["f2"]] else None,
                "f0_5": float(f[idx["f0_5"]]) if "f0_5" in idx and f[idx["f0_5"]] else None,
                "contig_bin_f1_bp": float(f[idx["contig_bin_f1_bp"]]) if "contig_bin_f1_bp" in idx and f[idx["contig_bin_f1_bp"]] else None,
                "abstention_rate": float(f[idx["abstention_rate"]]) if "abstention_rate" in idx and f[idx["abstention_rate"]] else None,
                "outcome_perfect": int(f[idx["outcome_perfect"]]) if "outcome_perfect" in idx and f[idx["outcome_perfect"]] else None,
                "outcome_fragmented": int(f[idx["outcome_fragmented"]]) if "outcome_fragmented" in idx and f[idx["outcome_fragmented"]] else None,
                "outcome_merged": int(f[idx["outcome_merged"]]) if "outcome_merged" in idx and f[idx["outcome_merged"]] else None,
                "outcome_fragmented_and_merged": int(f[idx["outcome_fragmented_and_merged"]]) if "outcome_fragmented_and_merged" in idx and f[idx["outcome_fragmented_and_merged"]] else None,
                "outcome_partial": int(f[idx["outcome_partial"]]) if "outcome_partial" in idx and f[idx["outcome_partial"]] else None,
                "outcome_missed": int(f[idx["outcome_missed"]]) if "outcome_missed" in idx and f[idx["outcome_missed"]] else None,
                # CPRR threshold sweep: one correct count per CPRR_SWEEP_THRESHOLDS value.
                "cprr_sweep_correct": parse_sweep(f[idx["cprr_sweep_correct"]]) if "cprr_sweep_correct" in idx else None,
                "cprr_sweep_correct_without_identity": (parse_sweep(f[idx["cprr_sweep_correct_without_identity"]])
                                                        if "cprr_sweep_correct_without_identity" in idx else None),
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


def failure_class(reason, exit_code=None):
    """'resource' when the recorded exit code is a timeout/SIGKILL,
    'infrastructure' for 125/126/127 (the command or container never started),
    else 'tool'.

    A failure with no recorded exit code (a status file from before exit codes
    were captured) is 'tool', which is the conservative reading: it is scored as
    the tool's failure exactly as it always was.
    """
    code = None
    if exit_code not in (None, ""):
        try:
            code = int(exit_code)
        except ValueError:
            code = None
    if code is None:
        match = EXIT_CODE.search(reason or "")
        code = int(match.group(1)) if match else None
    if code in RESOURCE_EXIT_CODES:
        return "resource"
    if code in INFRASTRUCTURE_EXIT_CODES:
        return "infrastructure"
    return "tool"


def read_outcome_side_table(status_path):
    """(sample, tool) -> row of tool_outcomes.tsv (04_run_tools.sh), next to
    tool_status.tsv. Absent for results from before the side table existed;
    callers then fall back to the exit code in the reason text."""
    if not status_path:
        return {}
    path = Path(status_path).with_name("tool_outcomes.tsv")
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {(r.get("sample"), r.get("tool")): r for r in csv.DictReader(handle, delimiter="\t")}


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
        side = read_outcome_side_table(path)
        for row in reader:
            if not (row.get("sample") and row.get("tool")):
                continue
            if row.get("status") == "infrastructure_failure":
                failures.append((row["tool"], row["sample"], "infrastructure"))
            elif row.get("status") == "failed":
                extra = side.get((row["sample"], row["tool"]), {})
                kind = extra.get("failure_class") or failure_class(row.get("reason"), extra.get("exit_code"))
                failures.append((row["tool"], row["sample"], kind))
    return failures


def outcome_states(path, tool_tracks=None):
    """One row per tool: how every run ended (scoring specification WP4).
    not_applicable is a skipped run (input the tool cannot use, tool absent)."""
    counts = {}
    if not path or not Path(path).is_file():
        return []
    side = read_outcome_side_table(path)
    kinds = {(sample, tool): kind for tool, sample, kind in read_failures(path)}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            tool, sample, status = row.get("tool"), row.get("sample"), row.get("status")
            if not tool:
                continue
            c = counts.setdefault(tool, {k: 0 for k in OUTCOME_STATE_FIELDS[2:]})
            c["n_runs"] += 1
            if status in ("completed", "reused"):
                c[status] += 1
            elif status == "skipped":
                c["not_applicable"] += 1
            elif status in ("failed", "infrastructure_failure"):
                kind = kinds.get((sample, tool), "tool")
                c["infrastructure_failure" if kind == "infrastructure" else f"failed_{kind}"] += 1
            try:
                c["retried"] += int((side.get((sample, tool)) or {}).get("attempts") or 1) > 1
            except ValueError:
                pass
    return [{"analysis_track": (tool_tracks or {}).get(tool, ""), "tool": tool, **c} for tool, c in sorted(counts.items())]


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
        if kind == "infrastructure":
            continue  # never scored: rerun instead
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


def summarise(rows, status_counts, failed_samples=None, clusters=None, overlap=None, design=None, metric="f1",
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
    # Headline endpoint (headline_design.py): the task's ranking metric over
    # the shared samples (failure-as-zero), species-balanced when enough
    # independent clusters exist, with a cluster-aware CI; plus CPRR.
    # known_tools / eligible_samples: a tool that failed on EVERY sample has no rows,
    # so without them the headline path would drop it exactly as the legacy path once did.
    by_metric, shared_metric, _ = hd.shared_values(
        rows, metric, failed_samples, known_tools=set(failed_samples or ()), eligible_samples=plasmid_samples)
    for row in summary:
        row.update(hd.ranking_fields(row["tool"], by_metric, shared_metric, design, metric))
        row.update(hd.cprr_fields(row["tool"], rows, design))
        lw = [r["lw_bin_f1"] for r in rows if r["tool"] == row["tool"] and r.get("lw_bin_f1") is not None]
        row["mean_lw_bin_f1"] = statistics.mean(lw) if lw else None
        brier = [r["brier_score"] for r in rows if r["tool"] == row["tool"] and r.get("brier_score") is not None]
        ece = [r["expected_calibration_error"] for r in rows
               if r["tool"] == row["tool"] and r.get("expected_calibration_error") is not None]
        row["mean_brier_score"] = statistics.mean(brier) if brier else None
        row["mean_expected_calibration_error"] = statistics.mean(ece) if ece else None
        row["n_calibrated"] = len(ece)
        row["is_baseline"] = "yes" if (design.is_baseline(row["tool"]) if design else row["tool"].startswith("baseline_")) else "no"
        tool_rows = [r for r in rows if r["tool"] == row["tool"]]
        for key in ("contig_f1_count", "contig_mcc_count", "contig_f1_bp", "contig_mcc_bp",
                    "bin_ari", "lw_bin_f1_assembly_aware", "mcc", "f2", "f0_5", "abstention_rate",
                    "contig_bin_f1_bp"):
            values = [r[key] for r in tool_rows if r.get(key) is not None]
            row[f"mean_{key}"] = statistics.mean(values) if values else None
        for key in ("outcome_perfect", "outcome_fragmented", "outcome_merged", "outcome_fragmented_and_merged",
                    "outcome_partial", "outcome_missed"):
            values = [r[key] for r in tool_rows if r.get(key) is not None]
            row[f"total_{key}"] = sum(values) if values else None
        # Micro average: TP/FP/FN bases pooled over every sample the tool was
        # scored on (large isolates weigh more). mean_precision/recall/f1 are the
        # macro average: per isolate, then averaged.
        pooled = [r for r in tool_rows if r.get("TP_bp") is not None]
        tp = sum(r["TP_bp"] for r in pooled)
        fp = sum(r.get("FP_bp") or 0 for r in pooled)
        fn = sum(r.get("FN_bp") or 0 for r in pooled)
        row["micro_precision"] = tp / (tp + fp) if tp + fp else None
        row["micro_recall"] = tp / (tp + fn) if tp + fn else None
        row["micro_f1"] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    # Rank by the ranking score (descending). A tool with no defined score
    # (e.g. scored only on zero-true-plasmid isolates) sorts last. Equal scores
    # rank by tool name, so the order never depends on row order in scores.tsv
    # (which made the "runner-up" in the significance test arbitrary).
    summary.sort(key=lambda x: (x["ranking_score"] is None, -(x["ranking_score"] or 0.0), x["tool"]))
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
    means = sorted(fast_mean([value for unit in rng.choices(units, k=len(units)) for value in unit])
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
    observed = abs(fast_mean(differences))
    rng = random.Random(20260901)
    getrandbits = rng.getrandbits
    negated = [[-item for item in unit] for unit in units]
    pairs = list(zip(units, negated))
    extreme = 0
    for _ in range(iterations):
        signed = []
        for unit, flipped in pairs:
            # Same bit stream as rng.randrange(2) (2 bits, reject >= 2), minus the call overhead.
            bits = getrandbits(2)
            while bits >= 2:
                bits = getrandbits(2)
            signed.extend(unit if bits else flipped)
        value = abs(fast_mean(signed))
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


def wilcoxon_signed_rank(differences, exact_max_n=25):
    """Two-sided paired Wilcoxon signed-rank p-value, pure Python.

    Zero differences are dropped (Wilcoxon's method). Tied |d| get average
    ranks. For n <= exact_max_n the p-value is exact: the null distribution of
    W+ is enumerated over doubled ranks (integers even with half-rank ties, so
    the exact test is conditional on the observed ties). Above that, the normal
    approximation with tie-corrected variance and a 0.5 continuity correction.
    Reported beside the primary sign-flip permutation test, never replacing it.
    Returns None when every difference is zero or there are none.
    """
    nonzero = [d for d in differences if d != 0]
    n = len(nonzero)
    if n == 0:
        return None
    order = sorted(range(n), key=lambda i: abs(nonzero[i]))
    ranks = [0.0] * n
    i = 0
    tie_term = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nonzero[order[j + 1]]) == abs(nonzero[order[i]]):
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, nonzero) if d > 0)
    if n <= exact_max_n:
        doubled = [int(round(2 * r)) for r in ranks]
        total = sum(doubled)
        counts = [0] * (total + 1)
        counts[0] = 1
        for r in doubled:
            for s in range(total, r - 1, -1):
                counts[s] += counts[s - r]
        observed = int(round(2 * w_plus))
        all_ways = 2 ** n
        lower = sum(counts[: observed + 1]) / all_ways
        upper = sum(counts[observed:]) / all_ways
        return min(1.0, 2 * min(lower, upper))
    mean = n * (n + 1) / 4
    variance = n * (n + 1) * (2 * n + 1) / 24 - tie_term / 48
    if variance <= 0:
        return None
    z = max(0.0, abs(w_plus - mean) - 0.5) / math.sqrt(variance)
    return min(1.0, math.erfc(z / math.sqrt(2)))


def compute_comparisons(rows, failed_samples=None, clusters=None, metric="f1", design=None, plasmid_samples=None):
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
        if row.get(metric) is not None:
            by_tool[row["tool"]][row["sample"]] = row[metric]
    # Same rule as summarise(): a failed tool run on a plasmid-bearing sample
    # is that tool's F1 = 0, so the test and the ranking judge the same data.
    plasmid_samples = set(plasmid_samples or ()) | {
        sample for values in by_tool.values() for sample in values}
    for tool, samples in (failed_samples or {}).items():
        for sample in samples:
            if sample in plasmid_samples and sample not in by_tool[tool]:
                by_tool[tool][sample] = 0.0   # also adds a tool that failed everywhere
    tools = sorted(by_tool)
    comparisons, jobs = [], []
    for i, a in enumerate(tools):
        for b in tools[i + 1:]:
            shared = sorted(set(by_tool[a]) & set(by_tool[b]))
            diffs = [by_tool[a][sample] - by_tool[b][sample] for sample in shared]
            if not diffs:
                continue
            strata_map = design.strata_for(shared) if design else None
            if strata_map is not None:
                shared = [sample for sample in shared if sample in strata_map]
                diffs = [by_tool[a][sample] - by_tool[b][sample] for sample in shared]
                strata = [strata_map[sample] for sample in shared]
                groups = [design.cluster(sample) for sample in shared]
            else:
                strata = None
                groups = ([design.cluster(sample) for sample in shared] if design and design.clusters
                          else cluster_labels(shared, clusters))
            jobs.append((diffs, groups, strata))
            comparisons.append({
                "tool_a": a, "tool_b": b, "paired_samples": len(shared),
                "paired_clusters": len(set(groups)), "metric": metric,
                "mean_f1_difference": hd.macro_mean(diffs, strata),
                "wins_a": sum(x > 0 for x in diffs), "ties": sum(x == 0 for x in diffs),
                "wins_b": sum(x < 0 for x in diffs),
                "wilcoxon_p_value": wilcoxon_signed_rank(diffs),
            })
    # The bootstrap CI and permutation test dominate runtime and are independent
    # per pair (each seeds its own RNG), so they run in parallel; order is kept.
    for row, (low, high, pvalue) in zip(comparisons, hd.map_pair_statistics(jobs)):
        row["difference_ci_low"] = low
        row["difference_ci_high"] = high
        row["permutation_p_value"] = pvalue
    for row, adjusted in zip(comparisons, holm_adjust([x["permutation_p_value"] for x in comparisons])):
        row["permutation_p_value_holm"] = adjusted
    for row, adjusted in zip(comparisons, holm_adjust([x["wilcoxon_p_value"] for x in comparisons])):
        row["wilcoxon_p_value_holm"] = adjusted
    smallest = float(os.environ.get("SMALLEST_DIFFERENCE", 0.05))
    for row in comparisons:
        # Equivalence flag: the mean difference AND its interval lie inside
        # +/- SMALLEST_DIFFERENCE, the pre-registered smallest difference of interest.
        low, high = row.get("difference_ci_low"), row.get("difference_ci_high")
        inside = abs(row["mean_f1_difference"]) < smallest
        if low is not None and high is not None:
            inside = inside and -smallest < low and high < smallest
        row["equivalent"] = "yes" if inside else "no"
        row["smallest_difference"] = smallest
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
        handle.write("tool_a\ttool_b\tpaired_samples\tmean_f1_difference\tdifference_ci_low\tdifference_ci_high\tpermutation_p_value\tpermutation_p_value_holm\twins_a\tties\twins_b\tanalysis_track\tpaired_clusters\ttask\tmetric"
                     "\twilcoxon_p_value\twilcoxon_p_value_holm\tequivalent\tsmallest_difference\n")
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
                f"{row.get('analysis_track', '')}\t{row.get('paired_clusters', '')}\t"
                f"{row.get('task', '')}\t{row.get('metric', 'f1')}\t"
                f"{fmt6(row.get('wilcoxon_p_value'))}\t{fmt6(row.get('wilcoxon_p_value_holm'))}\t"
                f"{row.get('equivalent', '')}\t{row.get('smallest_difference', '')}\n"
            )


def fmt6(value):
    return f"{value:.6f}" if value is not None else ""


def fmt4(value):
    return f"{value:.4f}" if value is not None else ""


def write_tsv(summary, path):
    cols = ["rank", "analysis_track", "task", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision",
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
            "ranking_metric", "ranking_score", "ranking_ci_low", "ranking_ci_high", "ranking_species_basis",
            "n_headline_species", "n_ranking_clusters", "mean_lw_bin_f1",
            "cprr", "cprr_ci_low", "cprr_ci_high", "cprr_correct", "cprr_plasmids",
            "mean_brier_score", "mean_expected_calibration_error", "n_calibrated", "is_baseline", "beats_best_baseline",
            "n_failed_resource", "n_unknown_overlap",
            "micro_precision", "micro_recall", "micro_f1",
            "mean_contig_f1_count", "mean_contig_mcc_count", "mean_contig_f1_bp", "mean_contig_mcc_bp",
            "mean_bin_ari", "mean_lw_bin_f1_assembly_aware",
            "n_plasmids_in_tool_database", "mean_recovery_in_tool_database", "mean_recovery_not_in_tool_database",
            "mean_mcc", "mean_f2", "mean_f0_5", "mean_abstention_rate",
            "total_outcome_perfect", "total_outcome_fragmented", "total_outcome_merged",
            "total_outcome_fragmented_and_merged", "total_outcome_partial", "total_outcome_missed",
            "n_failed_tool", "n_infrastructure_failure", "n_not_applicable", "mean_contig_bin_f1_bp",
            "cprr_isolate_mean", "cprr_isolates", "cprr_auc"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                s.get("rank", i), s.get("analysis_track", ""), s.get("task", ""), s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
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
                s.get("ranking_metric", ""), fmt4(s.get("ranking_score")), fmt4(s.get("ranking_ci_low")),
                fmt4(s.get("ranking_ci_high")), s.get("ranking_species_basis", ""),
                s.get("n_headline_species", ""), s.get("n_ranking_clusters", ""), fmt4(s.get("mean_lw_bin_f1")),
                fmt4(s.get("cprr")), fmt4(s.get("cprr_ci_low")), fmt4(s.get("cprr_ci_high")),
                s.get("cprr_correct", ""), s.get("cprr_plasmids", ""),
                fmt4(s.get("mean_brier_score")), fmt4(s.get("mean_expected_calibration_error")),
                s.get("n_calibrated", ""), s.get("is_baseline", "no"), s.get("beats_best_baseline", ""),
                s.get("n_failed_resource", 0),
                s["n_unknown_overlap"] if s.get("n_unknown_overlap") is not None else "",
                fmt4(s.get("micro_precision")), fmt4(s.get("micro_recall")), fmt4(s.get("micro_f1")),
                fmt4(s.get("mean_contig_f1_count")), fmt4(s.get("mean_contig_mcc_count")),
                fmt4(s.get("mean_contig_f1_bp")), fmt4(s.get("mean_contig_mcc_bp")),
                fmt4(s.get("mean_bin_ari")), fmt4(s.get("mean_lw_bin_f1_assembly_aware")),
                s.get("n_plasmids_in_tool_database", ""), fmt4(s.get("mean_recovery_in_tool_database")),
                fmt4(s.get("mean_recovery_not_in_tool_database")),
                fmt4(s.get("mean_mcc")), fmt4(s.get("mean_f2")), fmt4(s.get("mean_f0_5")),
                fmt4(s.get("mean_abstention_rate")),
                *("" if s.get(k) is None else s[k] for k in (
                    "total_outcome_perfect", "total_outcome_fragmented", "total_outcome_merged",
                    "total_outcome_fragmented_and_merged", "total_outcome_partial", "total_outcome_missed")),
                s.get("n_failed_tool", ""), s.get("n_infrastructure_failure", ""), s.get("n_not_applicable", ""),
                fmt4(s.get("mean_contig_bin_f1_bp")),
                # Isolate-weighted CPRR (each isolate counts once) and the normalised
                # area under the CPRR threshold-sweep curve (0.80-0.99).
                fmt4(s.get("cprr_isolate_mean")), s.get("cprr_isolates", ""), fmt4(s.get("cprr_auc")),
            ]) + "\n")


def format_rate(rate, assessed):
    """Display an availability-aware rate without turning missing evidence into zero."""
    return f"{rate:.1%} (n={assessed})" if rate is not None else "not assessed"


def write_md(summary, path, notes=()):
    # Deliberately narrower than write_tsv(): the compact, at-a-glance ranking
    # view. Every other column lives in the TSV and the HTML report.
    with open(path, "w") as fh:
        fh.write("# Plasmid reconstruction leaderboard\n\n")
        fh.write("Tools are ranked only within their own input track and task, never across them. "
                 "**Reconstruction** (binning-capable tools) is ranked by length-weighted binning F1 on the "
                 "short-read track and by isolate-level CPRR on the long-read and hybrid tracks; "
                 "**classification** (classifier-only tools) by base-level F1. "
                 "The ranking score averages per-species means when enough independent isolates exist, "
                 "over reference tiers 1-2 only, using the samples every ranked tool shares.\n\n")
        groups = []
        for row in summary:
            key = (row.get("analysis_track", ""), row.get("task", ""))
            if key not in groups:
                groups.append(key)
        for track, task in groups:
            group_rows = [r for r in summary if (r.get("analysis_track", ""), r.get("task", "")) == (track, task)]
            write_md_table(fh, group_rows, track if len({g[0] for g in groups}) > 1 else None, task)
        for note in notes:
            fh.write(f"\n> **Warning:** {note}\n")
        fh.write("\n_Length-weighted binning F1: bases placed in the correct (one-to-one matched) bin, over all "
                 "truth-plasmid bases (recall) and over all bases the bins align to (precision). CPRR = share of "
                 "truth plasmids reconstructed correctly (matched, covered, uncontaminated, not split, and -- "
                 "where truth was not polished with the benchmark's own reads -- high identity). A tool that "
                 "predicts nothing, or whose run failed, on a plasmid-bearing sample scores 0 there; a sample "
                 "missing for any other reason is removed from every tool's ranking. CIs resample independent "
                 "clusters (shared BioProject or clonal group) within each species._\n")


def write_md_table(fh, summary, track=None, task=None):
    """One ranked Markdown table for one (track, task)."""
    title = []
    if track:
        title.append(f"Track: {track}")
    if task:
        metric = summary[0].get("ranking_metric", "") if summary else ""
        title.append(f"{task} (ranked by {hd.METRIC_LABEL.get(metric, metric)})")
    if title:
        fh.write("## " + " · ".join(title) + "\n\n")
    fh.write("| Rank | Tool | Scored | Completed | Failed | Skipped | **Ranking score** | 95% CI | Basis | "
             "CPRR | Mean base F1 | Mean precision | Mean base recall | Significant vs runner-up |\n")
    fh.write("|" + "|".join(["---:", ":---", "---:", "---:", "---:", "---:", "---:", "---:", ":---",
                             "---:", "---:", "---:", "---:", ":---"]) + "|\n")

    def f3(value):
        return f"{value:.3f}" if value is not None else "n/a"

    for i, s in enumerate(summary, start=1):
        ci = (f"{s['ranking_ci_low']:.3f}–{s['ranking_ci_high']:.3f}"
              if s.get("ranking_ci_low") is not None else "< 5 independent units")
        cprr = (f"{s['cprr']:.1%} ({s['cprr_correct']}/{s['cprr_plasmids']})"
                if s.get("cprr") is not None else "not bin-scored")
        if s.get("cprr_isolate_mean") is not None:
            cprr += f"; per isolate {s['cprr_isolate_mean']:.1%}"
        if s.get("cprr_auc") is not None:
            cprr += f"; AUC 0.80–0.99 {s['cprr_auc']:.3f}"
        basis = s.get("ranking_species_basis") or "pooled"
        if s.get("n_ranking_samples"):
            basis += f"; {s['n_ranking_samples']} shared sample(s), {s.get('n_ranking_clusters', '?')} cluster(s)"
        significance = s.get("significant_vs_runner_up", "not_assessed")
        significance_text = {True: "yes (paired permutation, Holm-adjusted)",
                             False: "no (paired permutation, Holm-adjusted)"}.get(significance, "not assessed")
        fh.write(
            f"| {s.get('rank', i)} | {s['tool']} | {s['n_samples']} | {s['n_completed']} | {s['n_failed']} | "
            f"{s['n_skipped']} | **{f3(s.get('ranking_score'))}** | {ci} | {basis} | {cprr} | "
            f"{f3(s['mean_f1'])} | {f3(s['mean_precision'])} | {f3(s['mean_recall'])} | {significance_text} |\n"
        )
    fh.write("\n")


TRACK_ORDER = ("short_read", "long_read", "hybrid")


TASK_ORDER = (hd.TASK_RECONSTRUCTION, hd.TASK_CLASSIFICATION)


def ranked_tracks(rows, status_counts, failed_samples=None, clusters=None, overlap=None, design=None,
                  tool_tracks=None, resource_failures=None):
    """Summarise, rank and test each (input track, task) on its own.

    Returns [(track, task, rows, summary, comparisons)] in a stable order.
    A long-read tool is never ranked against a short-read one, and a
    classifier-only tool never against a binning tool.

    tool_tracks maps tool -> declared track (the capability registry). It is only
    consulted for a tool with no score rows at all, which is exactly the tool that
    failed on every sample: its rows cannot say which track it is in. Such a tool
    still gets a leaderboard row (score 0 on every plasmid-bearing sample), in the
    (track, task) it belongs to, instead of vanishing. A failure only ever counts
    in the group its tool belongs to.
    """
    design = design or hd.Design()
    hd.attach_sample_cprr(rows, design)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["analysis_track"], design.task(row["tool"], rows))].append(row)

    row_groups = defaultdict(set)
    for key, group_rows in groups.items():
        for row in group_rows:
            row_groups[row["tool"]].add(key)

    def groups_of(tool):
        if row_groups.get(tool):
            return row_groups[tool]
        # Same default read_scores() applies to a row with no analysis_track.
        track = (tool_tracks or {}).get(tool) or "short_read"
        return {(track, design.task(tool, rows))}

    # Which samples carry true plasmid is a property of the sample, not of a group,
    # so it is found across every group. Without it a group whose tools all crashed
    # would have no plasmid-bearing sample to score the crashes against.
    plasmid_samples = {row["sample"] for row in rows if row["f1"] is not None}
    # A group in which every tool failed everywhere has no score rows, so it would
    # not appear at all. Create it so those failures still produce a leaderboard.
    for tool, samples in (failed_samples or {}).items():
        if samples & plasmid_samples:
            for key in groups_of(tool):
                groups.setdefault(key, [])
    ordered = sorted(groups, key=lambda key: (
        TRACK_ORDER.index(key[0]) if key[0] in TRACK_ORDER else len(TRACK_ORDER), key[0],
        TASK_ORDER.index(key[1]) if key[1] in TASK_ORDER else len(TASK_ORDER)))
    result = []
    for track, task in ordered:
        group_rows = groups[(track, task)]
        metric = hd.ranking_metric(track, task)
        group_failed = {tool: samples for tool, samples in (failed_samples or {}).items()
                        if (track, task) in groups_of(tool)}
        group_resource = {tool: n for tool, n in (resource_failures or {}).items()
                          if (track, task) in groups_of(tool)}
        summary = summarise(group_rows, status_counts, group_failed, clusters, overlap, design, metric,
                            plasmid_samples=plasmid_samples, resource_failures=group_resource)
        comparisons = compute_comparisons(group_rows, group_failed, clusters, metric, design,
                                          plasmid_samples=plasmid_samples)
        for row in summary:
            row["analysis_track"], row["task"] = track, task
        for row in comparisons:
            row["analysis_track"], row["task"] = track, task
        attach_significance(summary, comparisons)
        attach_baseline_comparison(summary)
        result.append((track, task, group_rows, summary, comparisons))
    return result


def attach_baseline_comparison(summary):
    """Does each tool beat the best trivial baseline ranked alongside it?

    'yes'/'no' compare ranking scores within one (track, task); 'no baseline'
    when no baseline was scored there. A tool that cannot beat a trivial rule
    adds nothing the rule does not already give (question bank Q62/Q108).
    """
    baselines = [row.get("ranking_score") for row in summary
                 if row.get("is_baseline") == "yes" and row.get("ranking_score") is not None]
    best = max(baselines) if baselines else None
    for row in summary:
        if row.get("is_baseline") == "yes":
            row["beats_best_baseline"] = "baseline"
        elif best is None or row.get("ranking_score") is None:
            row["beats_best_baseline"] = "no baseline"
        else:
            row["beats_best_baseline"] = "yes" if row["ranking_score"] > best else "no"
    return summary


METADATA_FIELDS = (
    ("organism", "species unrecorded: left out of the species-balanced headline"),
    ("bioproject", "no study recorded: treated as its own independent cluster"),
    ("collection_country", "origin unrecorded: cannot be stratified by geography"),
    ("sample_origin", "isolation source unrecorded: cannot be stratified by clinical/environmental origin"),
    ("truth_assembly_strategy", "truth construction not recorded: tier derived from NCBI metadata or unknown"),
    ("truth_polish_reads", "polishing reads not recorded: identity criteria may be unassessable"),
)


def database_recovery(summary, containment_path, results_dir):
    """Per tool: mean per-plasmid completeness for truth plasmids inside vs
    outside that tool's own database (database_containment.py). A large gap
    means the tool recognises known plasmids better than it infers new ones."""
    contained = defaultdict(dict)  # tool -> (sample, plasmid) -> in_database
    for row in hd.read_rows(containment_path):
        for tool in (row.get("tools") or "").split(","):
            if tool:
                key = (row["sample"], row["sequence_id"])
                # A truth plasmid is "in" a tool's database if ANY of that tool's databases holds it.
                contained[tool][key] = bool(contained[tool].get(key)) or row.get("in_database") == "yes"
    for row in summary:
        membership = contained.get(row["tool"])
        if not membership:
            row["n_plasmids_in_tool_database"] = ""
            continue
        inside, outside = [], []
        for path in Path(results_dir).glob(f"*/{row['tool']}.per_plasmid.tsv"):
            for record in hd.read_rows(path):
                key = (path.parent.name, record.get("sequence_id"))
                if key in membership and record.get("completeness") not in (None, ""):
                    (inside if membership[key] else outside).append(float(record["completeness"]))
        row["n_plasmids_in_tool_database"] = len(inside)
        row["mean_recovery_in_tool_database"] = statistics.mean(inside) if inside else None
        row["mean_recovery_not_in_tool_database"] = statistics.mean(outside) if outside else None
    return summary


def metadata_completeness(sample_sheet, samples):
    """Which consequential sample-sheet fields are missing, per scored sample."""
    rows = hd.read_rows(sample_sheet)
    by_sample = {row.get("sample_id"): row for row in rows if row.get("sample_id")}
    out = []
    for sample in sorted(samples):
        row = by_sample.get(sample)
        if row is None:
            out.append({"sample": sample, "n_missing": len(METADATA_FIELDS),
                        "missing_fields": "not in sample sheet",
                        "consequences": "sample absent from the sheet: no species, study or provenance"})
            continue
        missing = [(field, why) for field, why in METADATA_FIELDS if not (row.get(field) or "").strip()]
        out.append({"sample": sample, "n_missing": len(missing),
                    "missing_fields": ",".join(field for field, _ in missing),
                    "consequences": "; ".join(why for _, why in missing)})
    return out


def write_rows(rows, path, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([fmt4(row[f]) if isinstance(row.get(f), float) else row.get(f, "") for f in fields])


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
    ap.add_argument("--capabilities", help="config/tool_capabilities.tsv; binning_capable decides the task track.")
    ap.add_argument("--truth-provenance", help="truth_provenance.py output (reference tiers).")
    ap.add_argument("--clonal-groups", help="clonal_groups.py output.")
    ap.add_argument("--database-containment", help="database_containment.py output (truth plasmids in tool databases).")
    ap.add_argument("--headline-max-tier", type=int, default=2,
                    help="highest reference tier included in the headline (default 2).")
    ap.add_argument("--min-species-clusters", type=int, default=20,
                    help="independent clusters a species needs to enter the species-balanced headline.")
    ap.add_argument("--resource-failures", choices=("score-zero", "exclude"), default="score-zero",
                    help="how a run killed by a timeout or out-of-memory (exit code 124/137) is ranked. "
                         "score-zero (default): scored 0 for that tool, like any failure. exclude: the "
                         "sample drops out of every tool's ranking, so a small machine cannot penalise a tool. "
                         "Either way the count is reported as n_failed_resource.")
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
    design = hd.Design(args.sample_sheet, args.capabilities, args.truth_provenance, args.clonal_groups,
                       args.headline_max_tier, args.min_species_clusters)
    all_rows = rows
    rows, reference_basis = design.headline_rows(rows)
    print(f"[aggregate] headline reference standard: {reference_basis} "
          f"({len({r['sample'] for r in rows})} of {len({r['sample'] for r in all_rows})} sample(s)).")
    # A sample whose only plasmids were evidence-labelled AMBIGUOUS is not a
    # plasmid-free negative control.
    for row in rows:
        if row.get("true_plasmid_count") == 0 and design.ambiguous_plasmids(row["sample"]) > 0:
            row["true_plasmid_count"] = None
    failed = read_failed_samples(args.tool_status, args.resource_failures)
    # A tool that failed on every sample has no score rows, so its track cannot be
    # read from them; take it from the capability registry.
    tool_tracks = {}
    registry_path = (Path(args.capabilities) if args.capabilities
                     else Path(__file__).resolve().parent.parent / "config" / "tool_capabilities.tsv")
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
        verb = "scored as 0" if args.resource_failures == "score-zero" else "excluded from ranking"
        print(f"[aggregate] {sum(resource_failures.values())} run(s) ended in a timeout or out-of-memory kill "
              f"(exit code 124/137); {verb} (--resource-failures {args.resource_failures}).")
    per_track = ranked_tracks(rows, status_counts, failed, clusters, overlap, design,
                              tool_tracks=tool_tracks, resource_failures=resource_failures)
    notes = []
    if leakage_unassessed(overlap):
        notes.append(LEAKAGE_UNASSESSED_NOTE)
        print(f"{chr(10)}[aggregate] WARNING: {LEAKAGE_UNASSESSED_NOTE}{chr(10)}")
    # The combined files hold every (track, task) leaderboard, each ranked on
    # its own (rank restarts per group). They never rank across groups.
    summary = [row for *_, track_summary, _ in per_track for row in track_summary]
    # Outcome states per tool (completed / failed: tool, resource / infrastructure /
    # not applicable / retried), beside accuracy in the leaderboard and the report.
    states = outcome_states(args.tool_status, tool_tracks)
    if states:
        write_rows(states, args.out_prefix + ".outcome_states.tsv", OUTCOME_STATE_FIELDS)
        by_tool = {r["tool"]: r for r in states}
        for row in summary:
            state = by_tool.get(row["tool"])
            if state:
                row.update(n_failed_tool=state["failed_tool"], n_infrastructure_failure=state["infrastructure_failure"],
                           n_not_applicable=state["not_applicable"])
        infra = sum(r["infrastructure_failure"] for r in states)
        if infra:
            print(f"[aggregate] {infra} run(s) were infrastructure failures (exit 125/126/127 or disk full): "
                  "not scored; rerun them.")
    if args.database_containment:
        database_recovery(summary, args.database_containment, os.path.dirname(os.path.abspath(args.out_prefix)))
    comparisons = [row for *_, track_comparisons in per_track for row in track_comparisons]
    write_tsv(summary, args.out_prefix + ".leaderboard.tsv")
    write_md(summary, args.out_prefix + ".leaderboard.md", notes=notes)
    by_track = defaultdict(list)
    for track, _, _, track_summary, _ in per_track:
        by_track[track].extend(track_summary)
    for track, track_summary in by_track.items():
        write_tsv(track_summary, f"{args.out_prefix}.{track}.leaderboard.tsv")
        write_md(track_summary, f"{args.out_prefix}.{track}.leaderboard.md", notes=notes)
    write_comparisons(rows, args.out_prefix + ".paired_comparisons.tsv", comparisons=comparisons)

    # Species balance and reference-tier sensitivity tables.
    species_rows, tier_rows, design_rows, sweep_rows = [], [], [], []
    hd.attach_sample_cprr(all_rows, design)
    for track, task, group_rows, track_summary, _ in per_track:
        metric = hd.ranking_metric(track, task)
        sweep_rows.extend(hd.cprr_sweep_table(track, task, group_rows, design))
        species_rows.extend(hd.species_table(
            track, task, group_rows, metric, design, failed,
            known_tools={row["tool"] for row in track_summary},
            eligible_samples={r["sample"] for r in rows if r["f1"] is not None}))
        all_group = [r for r in all_rows if r["analysis_track"] == track and design.task(r["tool"], all_rows) == task]
        tier_rows.extend(hd.tier_table(track, task, all_group, metric, design))
        design_rows.append({"analysis_track": track, "task": task, "ranking_metric": metric,
                            "reference_basis": reference_basis,
                            "species_basis": track_summary[0].get("ranking_species_basis", "") if track_summary else "",
                            "min_species_clusters": design.min_species_clusters})
    write_rows(species_rows, args.out_prefix + ".species.tsv",
               ["analysis_track", "task", "tool", "species", "n_samples", "n_clusters", "metric", "mean_metric",
                "in_headline"])
    write_rows(tier_rows, args.out_prefix + ".reference_tiers.tsv",
               ["analysis_track", "task", "tool", "reference_tier", "n_samples", "metric", "mean_metric",
                "cprr", "cprr_plasmids"])
    # CPRR threshold robustness: pooled and isolate-weighted CPRR with the coverage
    # and bin-share criteria swept over 0.80-0.99; the leaderboard's cprr_auc
    # summarises the pooled curve. Descriptive; it never changes a rank.
    write_rows(sweep_rows, args.out_prefix + ".cprr_threshold_sweep.tsv",
               ["analysis_track", "task", "tool", "threshold", "cprr", "cprr_isolate_mean",
                "n_isolates", "n_plasmids"])
    write_rows(design_rows, args.out_prefix + ".headline_design.tsv",
               ["analysis_track", "task", "ranking_metric", "reference_basis", "species_basis",
                "min_species_clusters"])
    if args.sample_sheet:
        completeness = metadata_completeness(args.sample_sheet, {r["sample"] for r in all_rows})
        write_rows(completeness, args.out_prefix + ".metadata_completeness.tsv",
                   ["sample", "n_missing", "missing_fields", "consequences"])
        incomplete = sum(1 for row in completeness if row["n_missing"])
        if incomplete:
            print(f"[aggregate] {incomplete} of {len(completeness)} scored sample(s) lack consequential metadata; "
                  f"see {args.out_prefix}.metadata_completeness.tsv")

    # Print the leaderboard to stdout so it appears in the run log.
    def fmt3(value):
        return f"{value:.3f}" if value is not None else "n/a"
    for track, task, _, track_summary, _ in per_track:
        metric = hd.METRIC_LABEL.get(hd.ranking_metric(track, task), "")
        print(f"\n=== LEADERBOARD [{track} / {task}] ranked by {metric} ===")
        for s in track_summary:
            print(f"{s['rank']:>2}. {s['tool']:<16} "
                  f"score={fmt3(s.get('ranking_score'))} ({s.get('ranking_species_basis') or 'pooled'})  "
                  f"F1={fmt3(s['mean_f1'])} on {s['n_ranking_samples']} sample(s)  "
                  f"P={fmt3(s['mean_precision'])}  R={fmt3(s['mean_recall'])}  "
                  f"(scored={s['n_samples']}, completed={s['n_completed']}, failed={s['n_failed']}, skipped={s['n_skipped']})")
            if s["n_f1_scored"] > s["n_ranking_samples"]:
                print(f"    note: {s['tool']} has F1 on {s['n_f1_scored']} sample(s); only the "
                      f"{s['n_ranking_samples']} shared by every ranked tool count toward rank "
                      f"(own-sample mean F1={fmt3(s['mean_f1_all_scored'])}).")


if __name__ == "__main__":
    main()
