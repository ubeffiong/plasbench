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
                "precision": float(f[idx["precision"]]),
                "recall": float(f[idx["recall"]]),
                "f1": float(f[idx["f1"]]),
                # A missing plasmid-level value is not evidence of zero recovery.
                "plasmid_recall": (
                    float(f[idx["plasmid_recall"]])
                    if "plasmid_recall" in idx and f[idx["plasmid_recall"]]
                    else None
                ),
                "bin_f1": float(f[idx["bin_f1"]]) if "bin_f1" in idx and f[idx["bin_f1"]] else None,
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
    by_tool = defaultdict(lambda: {"precision": [], "recall": [], "f1": [], "plasmid_recall": [], "bin_f1": [], "n": 0})
    for r in rows:
        t = by_tool[r["tool"]]
        t["precision"].append(r["precision"])
        t["recall"].append(r["recall"])
        t["f1"].append(r["f1"])
        if r["plasmid_recall"] is not None:
            t["plasmid_recall"].append(r["plasmid_recall"])
        if r["bin_f1"] is not None: t["bin_f1"].append(r["bin_f1"])
        t["n"] += 1

    summary = []
    for tool, d in by_tool.items():
        f1_ci_low, f1_ci_high = bootstrap_ci(d["f1"])
        summary.append({
            "tool": tool,
            "n_samples": d["n"],
            "mean_precision": statistics.mean(d["precision"]),
            "mean_recall": statistics.mean(d["recall"]),
            "mean_f1": statistics.mean(d["f1"]),
            "f1_ci_low": f1_ci_low,
            "f1_ci_high": f1_ci_high,
            "median_f1": statistics.median(d["f1"]),
            "mean_plasmid_recall": statistics.mean(d["plasmid_recall"]) if d["plasmid_recall"] else None,
            "mean_bin_f1": statistics.mean(d["bin_f1"]) if d["bin_f1"] else None,
            "n_bin_scored": len(d["bin_f1"]),
            "n_completed": status_counts[tool]["completed"] + status_counts[tool]["reused"],
            "n_failed": status_counts[tool]["failed"],
            "n_skipped": status_counts[tool]["skipped"],
        })
    # Rank by mean F1 (descending).
    summary.sort(key=lambda x: x["mean_f1"], reverse=True)
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


def write_comparisons(rows, path):
    by_tool = defaultdict(dict)
    for row in rows:
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
            "mean_recall", "mean_plasmid_recall", "n_bin_scored", "mean_bin_f1", "mean_f1", "f1_ci_low", "f1_ci_high", "median_f1"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                i, s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
                f"{s['mean_precision']:.4f}", f"{s['mean_recall']:.4f}",
                f"{s['mean_plasmid_recall']:.4f}" if s["mean_plasmid_recall"] is not None else "",
                s['n_bin_scored'], f"{s['mean_bin_f1']:.4f}" if s['mean_bin_f1'] is not None else "",
                f"{s['mean_f1']:.4f}", f"{s['f1_ci_low']:.4f}" if s["f1_ci_low"] is not None else "",
                f"{s['f1_ci_high']:.4f}" if s["f1_ci_high"] is not None else "", f"{s['median_f1']:.4f}",
            ]) + "\n")


def write_md(summary, path):
    with open(path, "w") as fh:
        fh.write("# Plasmid reconstruction leaderboard\n\n")
        fh.write("Ranked by mean base-level F1 across samples "
                 "(positive class = plasmid).\n\n")
        fh.write("| Rank | Tool | Scored | Completed | Failed | Skipped | Mean precision | "
                 "Mean base recall | Mean plasmid recall | **Mean F1** | 95% F1 CI | Median F1 |\n")
        fh.write("|" + "|".join(["---:", ":---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]) + "|\n")
        for i, s in enumerate(summary, start=1):
            plasmid_recall = f"{s['mean_plasmid_recall']:.3f}" if s["mean_plasmid_recall"] is not None else "not annotated"
            ci = (f"{s['f1_ci_low']:.3f}–{s['f1_ci_high']:.3f}"
                  if s["f1_ci_low"] is not None else "n < 5")
            fh.write(
                f"| {i} | {s['tool']} | {s['n_samples']} | {s['n_completed']} | {s['n_failed']} | {s['n_skipped']} | "
                f"{s['mean_precision']:.3f} | {s['mean_recall']:.3f} | "
                f"{plasmid_recall} | **{s['mean_f1']:.3f}** | {ci} | {s['median_f1']:.3f} |\n"
            )
        fh.write("\n_Recall = completeness (fraction of true plasmid bases "
                 "recovered). Plasmid recall = fraction of truth plasmids meeting the configured "
                 "recovery threshold; it is not available for legacy score rows. Precision = 1 - "
                 "chromosomal contamination._\n")


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
    write_tsv(summary, args.out_prefix + ".leaderboard.tsv")
    write_md(summary, args.out_prefix + ".leaderboard.md")
    write_comparisons(rows, args.out_prefix + ".paired_comparisons.tsv")

    # Print the leaderboard to stdout so it appears in the run log.
    print("\n=== LEADERBOARD (mean F1, descending) ===")
    for i, s in enumerate(summary, start=1):
        print(f"{i:>2}. {s['tool']:<16} "
              f"F1={s['mean_f1']:.3f}  "
              f"P={s['mean_precision']:.3f}  R={s['mean_recall']:.3f}  "
              f"(scored={s['n_samples']}, completed={s['n_completed']}, failed={s['n_failed']}, skipped={s['n_skipped']})")


if __name__ == "__main__":
    main()
