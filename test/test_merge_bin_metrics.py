#!/usr/bin/env python3
"""Regression coverage for retaining all bin diagnostics in scores.tsv."""
import csv
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "merge_bin_metrics.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        scores = os.path.join(directory, "scores.tsv")
        results = os.path.join(directory, "results")
        os.makedirs(os.path.join(results, "sample1"))
        with open(scores, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample", "tool", "f1"], delimiter="\t")
            writer.writeheader()
            writer.writerow({"sample": "sample1", "tool": "tool_a", "f1": "0.5"})
        summary = os.path.join(results, "sample1", "tool_a.bin_summary.tsv")
        with open(summary, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins",
                "missed_plasmids", "split_events", "merge_events", "contaminated_bins",
            ], delimiter="\t")
            writer.writeheader()
            writer.writerow({"bin_precision": "0.5", "bin_recall": "0.5", "bin_f1": "0.5",
                             "matched_bins": "1", "unmatched_bins": "2", "missed_plasmids": "3",
                             "split_events": "4", "merge_events": "5", "contaminated_bins": "6"})
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--results-dir", results], check=True)
        row = next(csv.DictReader(open(scores), delimiter="\t"))
        assert row["split_events"] == "4"
        assert row["merge_events"] == "5"
        assert row["contaminated_bins"] == "6"
    print("ALL BIN-METRIC MERGE TESTS PASSED")


if __name__ == "__main__":
    main()
