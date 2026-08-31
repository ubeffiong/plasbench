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
import random
import statistics
from collections import defaultdict


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
                "plasmid_recall": float(f[idx["plasmid_recall"]]) if "plasmid_recall" in idx else 0.0,
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
    by_tool = defaultdict(lambda: {"precision": [], "recall": [], "f1": [], "plasmid_recall": [], "n": 0})
    for r in rows:
        t = by_tool[r["tool"]]
        t["precision"].append(r["precision"])
        t["recall"].append(r["recall"])
        t["f1"].append(r["f1"])
        t["plasmid_recall"].append(r["plasmid_recall"])
        t["n"] += 1

    summary = []
    for tool, d in by_tool.items():
        summary.append({
            "tool": tool,
            "n_samples": d["n"],
            "mean_precision": statistics.mean(d["precision"]),
            "mean_recall": statistics.mean(d["recall"]),
            "mean_f1": statistics.mean(d["f1"]),
            "f1_ci_low": bootstrap_ci(d["f1"])[0],
            "f1_ci_high": bootstrap_ci(d["f1"])[1],
            "median_f1": statistics.median(d["f1"]),
            "mean_plasmid_recall": statistics.mean(d["plasmid_recall"]),
            "n_completed": status_counts[tool]["completed"] + status_counts[tool]["reused"],
            "n_failed": status_counts[tool]["failed"],
            "n_skipped": status_counts[tool]["skipped"],
        })
    # Rank by mean F1 (descending).
    summary.sort(key=lambda x: x["mean_f1"], reverse=True)
    return summary


def bootstrap_ci(values, iterations=1000):
    """Deterministic percentile CI for the mean F1; descriptive, not a p-value."""
    if len(values) < 2:
        return statistics.mean(values), statistics.mean(values)
    rng = random.Random(20260831)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def write_comparisons(rows, path):
    by_tool = defaultdict(dict)
    for row in rows:
        by_tool[row["tool"]][row["sample"]] = row["f1"]
    tools = sorted(by_tool)
    with open(path, "w") as handle:
        handle.write("tool_a\ttool_b\tpaired_samples\tmean_f1_difference\twins_a\tties\twins_b\n")
        for i, a in enumerate(tools):
            for b in tools[i + 1:]:
                shared = sorted(set(by_tool[a]) & set(by_tool[b]))
                diffs = [by_tool[a][sample] - by_tool[b][sample] for sample in shared]
                if not diffs:
                    continue
                handle.write(f"{a}\t{b}\t{len(shared)}\t{statistics.mean(diffs):.4f}\t"
                             f"{sum(x > 0 for x in diffs)}\t{sum(x == 0 for x in diffs)}\t{sum(x < 0 for x in diffs)}\n")


def write_tsv(summary, path):
    cols = ["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision",
            "mean_recall", "mean_plasmid_recall", "mean_f1", "f1_ci_low", "f1_ci_high", "median_f1"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                i, s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
                f"{s['mean_precision']:.4f}", f"{s['mean_recall']:.4f}",
                f"{s['mean_plasmid_recall']:.4f}", f"{s['mean_f1']:.4f}", f"{s['f1_ci_low']:.4f}", f"{s['f1_ci_high']:.4f}", f"{s['median_f1']:.4f}",
            ]) + "\n")


def write_md(summary, path):
    with open(path, "w") as fh:
        fh.write("# Plasmid reconstruction leaderboard\n\n")
        fh.write("Ranked by mean base-level F1 across samples "
                 "(positive class = plasmid).\n\n")
        fh.write("| Rank | Tool | Scored | Completed | Failed | Skipped | Mean precision | "
                 "Mean recall | **Mean F1** | Median F1 |\n")
        fh.write("|---:|:---|---:|---:|---:|---:|---:|---:|---:|\n")
        for i, s in enumerate(summary, start=1):
            fh.write(
                f"| {i} | {s['tool']} | {s['n_samples']} | {s['n_completed']} | {s['n_failed']} | {s['n_skipped']} | "
                f"{s['mean_precision']:.3f} | {s['mean_recall']:.3f} | "
                f"**{s['mean_f1']:.3f}** | {s['median_f1']:.3f} |\n"
            )
        fh.write("\n_Recall = completeness (fraction of true plasmid bases "
                 "recovered). Precision = 1 - chromosomal contamination._\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True, help="combined scores TSV")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--tool-status", help="optional status TSV from stage 4")
    args = ap.parse_args()

    rows = read_scores(args.scores)
    if not rows:
        raise SystemExit("No score rows found in " + args.scores)
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
