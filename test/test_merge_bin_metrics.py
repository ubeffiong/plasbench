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
            writer = csv.DictWriter(handle, fieldnames=["sample", "tool", "f1", "plasmid_recall", "unmapped_pred_bp", "off_truth_pred_bp", "ambiguously_mapped_pred_bp"], delimiter="\t")
            writer.writeheader()
            writer.writerow({"sample": "sample1", "tool": "tool_a", "f1": "1", "plasmid_recall": "1", "unmapped_pred_bp": "0", "off_truth_pred_bp": "0", "ambiguously_mapped_pred_bp": "0"})
        summary = os.path.join(results, "sample1", "tool_a.bin_summary.tsv")
        with open(summary, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins",
                "missed_plasmids", "split_events", "merge_events", "contaminated_bins",
                "chromosome_aligned_bp", "repeat_ambiguity_bp", "bin_total_mapped_bp", "contamination_fraction",
            ], delimiter="\t")
            writer.writeheader()
            writer.writerow({"bin_precision": "1", "bin_recall": "1", "bin_f1": "1",
                             "matched_bins": "1", "unmatched_bins": "0", "missed_plasmids": "0",
                             "split_events": "0", "merge_events": "0", "contaminated_bins": "0",
                             "chromosome_aligned_bp": "0", "repeat_ambiguity_bp": "0",
                             "bin_total_mapped_bp": "100", "contamination_fraction": "0"})
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--results-dir", results], check=True)
        row = next(csv.DictReader(open(scores), delimiter="\t"))
        assert row["split_events"] == "0"
        assert row["merge_events"] == "0"
        assert row["contaminated_bins"] == "0"
        assert row["perfect_reference_recovery"] == "yes"
        assert row["strict_reference_reconstruction"] == "yes"
    print("ALL BIN-METRIC MERGE TESTS PASSED")


if __name__ == "__main__":
    main()
