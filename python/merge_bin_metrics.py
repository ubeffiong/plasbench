#!/usr/bin/env python3
"""Join per-sample bin summaries into the canonical PlasBench score table."""

import argparse
import csv
from pathlib import Path

FIELDS = [
    "bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins",
    "missed_plasmids", "split_events", "merge_events", "contaminated_bins",
    "chromosome_aligned_bp", "bin_total_mapped_bp", "contamination_fraction",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", required=True)
    parser.add_argument("--results-dir", required=True)
    args = parser.parse_args()
    summaries = {}
    for path in Path(args.results_dir).glob("*/*.bin_summary.tsv"):
        tool = path.name.removesuffix(".bin_summary.tsv")
        sample = path.parent.name
        with open(path) as handle:
            summaries[(sample, tool)] = next(csv.DictReader(handle, delimiter="\t"))
    with open(args.scores) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
        fieldnames = list(rows[0]) if rows else []
    for field in FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)
    for row in rows:
        summary = summaries.get((row["sample"], row["tool"]), {})
        for field in FIELDS:
            row[field] = summary.get(field, "")
    with open(args.scores, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
