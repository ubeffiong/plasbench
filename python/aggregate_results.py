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


def summarise(rows, status_counts):
    by_tool = defaultdict(lambda: {"precision": [], "recall": [], "f1": [], "plasmid_recall": [], "bin_f1": [], "pr_auc": [], "perfect": [], "strict": [], "n": 0,
                                   "zero_plasmid_specificity": [], "zero_plasmid_fp_bp": [], "n_zero_plasmid": 0,
                                   "nmi": [], "vi": []})
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

    summary = []
    for tool, d in by_tool.items():
        f1_ci_low, f1_ci_high = bootstrap_ci(d["f1"])
        summary.append({
            "tool": tool,
            "n_samples": d["n"],
            "mean_precision": statistics.mean(d["precision"]) if d["precision"] else None,
            "mean_recall": statistics.mean(d["recall"]) if d["recall"] else None,
            "mean_f1": statistics.mean(d["f1"]) if d["f1"] else None,
            "f1_ci_low": f1_ci_low,
            "f1_ci_high": f1_ci_high,
            "median_f1": statistics.median(d["f1"]) if d["f1"] else None,
            "mean_plasmid_recall": statistics.mean(d["plasmid_recall"]) if d["plasmid_recall"] else None,
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
    # Rank by mean F1 (descending). A tool scored only on zero-true-plasmid
    # isolates has no defined mean_f1 at all -- sort it last rather than
    # crashing the comparison against a real float.
    summary.sort(key=lambda x: (x["mean_f1"] is None, -(x["mean_f1"] or 0.0)))
    return summary


def bootstrap_ci(values, iterations=1000):
    """Deterministic percentile CI for the mean F1; descriptive, not a p-value."""
    # Intervals from very small cohorts imply a precision the data do not have.
    if len(values) < 5:
        return None, None
    rng = random.Random(20260831)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def paired_permutation_pvalue(differences, iterations=10000):
    """Two-sided sign-flip permutation p-value for paired mean differences."""
    if len(differences) < 5:
        return None
    observed = abs(statistics.mean(differences))
    rng = random.Random(20260901)
    extreme = 0
    for _ in range(iterations):
        value = abs(statistics.mean(item if rng.randrange(2) else -item for item in differences))
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


def compute_comparisons(rows):
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
    tools = sorted(by_tool)
    comparisons = []
    for i, a in enumerate(tools):
        for b in tools[i + 1:]:
            shared = sorted(set(by_tool[a]) & set(by_tool[b]))
            diffs = [by_tool[a][sample] - by_tool[b][sample] for sample in shared]
            if not diffs:
                continue
            low, high = bootstrap_ci(diffs)
            comparisons.append({
                "tool_a": a, "tool_b": b, "paired_samples": len(shared),
                "mean_f1_difference": statistics.mean(diffs), "difference_ci_low": low,
                "difference_ci_high": high, "permutation_p_value": paired_permutation_pvalue(diffs),
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
        handle.write("tool_a\ttool_b\tpaired_samples\tmean_f1_difference\tdifference_ci_low\tdifference_ci_high\tpermutation_p_value\tpermutation_p_value_holm\twins_a\tties\twins_b\n")
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
                f"{adjusted_text}\t{row['wins_a']}\t{row['ties']}\t{row['wins_b']}\n"
            )


def write_tsv(summary, path):
    cols = ["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision",
            "mean_recall", "mean_plasmid_recall", "n_bin_scored", "mean_bin_f1", "mean_nmi", "mean_variation_of_information", "n_pr_scored", "mean_pr_auc",
            "n_reference_perfect_assessed", "reference_perfect_recovery_rate", "n_strict_reconstruction_assessed", "strict_reference_reconstruction_rate",
            "mean_f1", "f1_ci_low", "f1_ci_high", "median_f1", "significant_vs_runner_up",
            "n_zero_plasmid_isolates", "mean_zero_plasmid_specificity", "total_zero_plasmid_chromosome_fp_bp"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                i, s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
                f"{s['mean_precision']:.4f}" if s["mean_precision"] is not None else "",
                f"{s['mean_recall']:.4f}" if s["mean_recall"] is not None else "",
                f"{s['mean_plasmid_recall']:.4f}" if s["mean_plasmid_recall"] is not None else "",
                s['n_bin_scored'], f"{s['mean_bin_f1']:.4f}" if s['mean_bin_f1'] is not None else "",
                f"{s['mean_nmi']:.4f}" if s['mean_nmi'] is not None else "",
                f"{s['mean_variation_of_information']:.4f}" if s['mean_variation_of_information'] is not None else "",
                s['n_pr_scored'], f"{s['mean_pr_auc']:.4f}" if s['mean_pr_auc'] is not None else "",
                s['n_reference_perfect_assessed'], f"{s['reference_perfect_recovery_rate']:.4f}" if s['reference_perfect_recovery_rate'] is not None else "",
                s['n_strict_reconstruction_assessed'], f"{s['strict_reference_reconstruction_rate']:.4f}" if s['strict_reference_reconstruction_rate'] is not None else "",
                f"{s['mean_f1']:.4f}" if s["mean_f1"] is not None else "",
                f"{s['f1_ci_low']:.4f}" if s["f1_ci_low"] is not None else "",
                f"{s['f1_ci_high']:.4f}" if s["f1_ci_high"] is not None else "",
                f"{s['median_f1']:.4f}" if s["median_f1"] is not None else "",
                # Derived from the SAME paired, shared-sample, sign-flip
                # permutation test (Holm-adjusted) as
                # benchmark.paired_comparisons.tsv -- see attach_significance().
                # Never a bootstrap-CI-overlap heuristic.
                s.get("significant_vs_runner_up", "not_assessed"),
                # Negative-control summary: only meaningful for isolates with
                # zero true plasmids (score_plasmids.py's isolate_specificity/
                # chromosome_fp_bp), never blended into the ranking metrics above.
                s["n_zero_plasmid_isolates"],
                f"{s['mean_zero_plasmid_specificity']:.4f}" if s["mean_zero_plasmid_specificity"] is not None else "",
                s["total_zero_plasmid_chromosome_fp_bp"] if s["total_zero_plasmid_chromosome_fp_bp"] is not None else "",
            ]) + "\n")


def format_rate(rate, assessed):
    """Display an availability-aware rate without turning missing evidence into zero."""
    return f"{rate:.1%} (n={assessed})" if rate is not None else "not assessed"


def write_md(summary, path):
    with open(path, "w") as fh:
        fh.write("# Plasmid reconstruction leaderboard\n\n")
        fh.write("Ranked by mean base-level F1 across samples "
                 "(positive class = plasmid).\n\n")
        fh.write("| Rank | Tool | Scored | Completed | Failed | Skipped | Mean precision | "
                 "Mean base recall | Mean plasmid recall | Perfect reference recovery | Strict reconstruction | **Mean F1** | 95% F1 CI | Median F1 | Significant vs runner-up |\n")
        fh.write("|" + "|".join(["---:", ":---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", ":---"]) + "|\n")
        for i, s in enumerate(summary, start=1):
            plasmid_recall = f"{s['mean_plasmid_recall']:.3f}" if s["mean_plasmid_recall"] is not None else "not annotated"
            ci = (f"{s['f1_ci_low']:.3f}–{s['f1_ci_high']:.3f}"
                  if s["f1_ci_low"] is not None else "n < 5")
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
            significance = s.get("significant_vs_runner_up", "not_assessed")
            significance_text = {True: "yes (paired permutation, Holm-adjusted)",
                                 False: "no (paired permutation, Holm-adjusted)"}.get(significance, "not assessed")
            fh.write(
                f"| {i} | {s['tool']} | {s['n_samples']} | {s['n_completed']} | {s['n_failed']} | {s['n_skipped']} | "
                f"{mean_precision} | {mean_recall} | "
                f"{plasmid_recall} | {format_rate(s['reference_perfect_recovery_rate'], s['n_reference_perfect_assessed'])} | "
                f"{format_rate(s['strict_reference_reconstruction_rate'], s['n_strict_reconstruction_assessed'])} | "
                f"**{mean_f1}** | {ci} | {median_f1} | {significance_text} |\n"
            )
        fh.write("\n_Recall = completeness (fraction of true plasmid bases "
                 "recovered). Plasmid recall = fraction of truth plasmids meeting the configured "
                 "recovery threshold; it is not available for legacy score rows. Precision = 1 - "
                 "chromosomal contamination. Perfect reference recovery requires F1/plasmid recall of 1 "
                 "and zero ambiguous, unmapped, and off-truth predicted bases. Strict reconstruction also "
                 "requires perfect available bin diagnostics; neither measure proves nucleotide identity or closure._\n")


def write_track_leaderboards(rows, status_counts, prefix):
    """Emit one leaderboard per declared input track; never mix track claims."""
    tracks = defaultdict(list)
    for row in rows:
        tracks[row["analysis_track"]].append(row)
    for track, track_rows in tracks.items():
        summary = summarise(track_rows, status_counts)
        # Significance is computed against this track's OWN shared samples,
        # not the global comparison -- a tool's runner-up, and how many
        # samples they actually share, can differ per track.
        attach_significance(summary, compute_comparisons(track_rows))
        track_prefix = f"{prefix}.{track}"
        write_tsv(summary, track_prefix + ".leaderboard.tsv")
        write_md(summary, track_prefix + ".leaderboard.md")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True, help="combined scores TSV")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--tool-status", help="optional status TSV from stage 4")
    ap.add_argument("--sample-sheet", help="sample sheet used for the run; read for parent_sample_id.")
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
    summary = summarise(rows, status_counts)
    comparisons = compute_comparisons(rows)
    attach_significance(summary, comparisons)
    write_tsv(summary, args.out_prefix + ".leaderboard.tsv")
    write_md(summary, args.out_prefix + ".leaderboard.md")
    write_track_leaderboards(rows, status_counts, args.out_prefix)
    write_comparisons(rows, args.out_prefix + ".paired_comparisons.tsv", comparisons=comparisons)

    # Print the leaderboard to stdout so it appears in the run log.
    print("\n=== LEADERBOARD (mean F1, descending) ===")
    def fmt3(value):
        return f"{value:.3f}" if value is not None else "n/a"
    for i, s in enumerate(summary, start=1):
        print(f"{i:>2}. {s['tool']:<16} "
              f"F1={fmt3(s['mean_f1'])}  "
              f"P={fmt3(s['mean_precision'])}  R={fmt3(s['mean_recall'])}  "
              f"(scored={s['n_samples']}, completed={s['n_completed']}, failed={s['n_failed']}, skipped={s['n_skipped']})")


if __name__ == "__main__":
    main()
