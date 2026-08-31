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
            })
    return rows


def read_status(path):
    counts = defaultdict(lambda: {"completed": 0, "reused": 0, "failed": 0, "skipped": 0})
    if not path:
        return counts
    with open(path) as fh:
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
    by_tool = defaultdict(lambda: {"precision": [], "recall": [], "f1": [], "n": 0})
    for r in rows:
        t = by_tool[r["tool"]]
        t["precision"].append(r["precision"])
        t["recall"].append(r["recall"])
        t["f1"].append(r["f1"])
        t["n"] += 1

    summary = []
    for tool, d in by_tool.items():
        summary.append({
            "tool": tool,
            "n_samples": d["n"],
            "mean_precision": statistics.mean(d["precision"]),
            "mean_recall": statistics.mean(d["recall"]),
            "mean_f1": statistics.mean(d["f1"]),
            "median_f1": statistics.median(d["f1"]),
            "n_completed": status_counts[tool]["completed"] + status_counts[tool]["reused"],
            "n_failed": status_counts[tool]["failed"],
            "n_skipped": status_counts[tool]["skipped"],
        })
    # Rank by mean F1 (descending).
    summary.sort(key=lambda x: x["mean_f1"], reverse=True)
    return summary


def write_tsv(summary, path):
    cols = ["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision",
            "mean_recall", "mean_f1", "median_f1"]
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for i, s in enumerate(summary, start=1):
            fh.write("\t".join(str(x) for x in [
                i, s["tool"], s["n_samples"], s["n_completed"], s["n_failed"], s["n_skipped"],
                f"{s['mean_precision']:.4f}", f"{s['mean_recall']:.4f}",
                f"{s['mean_f1']:.4f}", f"{s['median_f1']:.4f}",
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

    # Print the leaderboard to stdout so it appears in the run log.
    print("\n=== LEADERBOARD (mean F1, descending) ===")
    for i, s in enumerate(summary, start=1):
        print(f"{i:>2}. {s['tool']:<16} "
              f"F1={s['mean_f1']:.3f}  "
              f"P={s['mean_precision']:.3f}  R={s['mean_recall']:.3f}  "
              f"(scored={s['n_samples']}, completed={s['n_completed']}, failed={s['n_failed']}, skipped={s['n_skipped']})")


if __name__ == "__main__":
    main()
