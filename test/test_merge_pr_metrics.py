#!/usr/bin/env python3
"""Regression coverage for merging PR-curve summaries into scores.tsv
(structural clone of test_merge_bin_metrics.py). Also covers a tool with no
pr_summary.tsv at all (never scored a probability) getting an empty, not
missing, pr_auc/pr_n_thresholds column -- the "gracefully absent" contract
aggregate_results.py's summarise() relies on.
"""
import csv
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "merge_pr_metrics.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        scores = os.path.join(directory, "scores.tsv")
        results = os.path.join(directory, "results")
        os.makedirs(os.path.join(results, "sample1"))
        with open(scores, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample", "tool", "f1"], delimiter="\t")
            writer.writeheader()
            writer.writerow({"sample": "sample1", "tool": "mltool", "f1": "0.5"})
            writer.writerow({"sample": "sample1", "tool": "mob_recon", "f1": "0.9"})
        summary = os.path.join(results, "sample1", "mltool.pr_summary.tsv")
        with open(summary, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["pr_auc", "pr_n_thresholds"], delimiter="\t")
            writer.writeheader()
            writer.writerow({"pr_auc": "0.791667", "pr_n_thresholds": "3"})
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--results-dir", results], check=True)
        rows = {row["tool"]: row for row in csv.DictReader(open(scores), delimiter="\t")}
        assert rows["mltool"]["pr_auc"] == "0.791667"
        assert rows["mltool"]["pr_n_thresholds"] == "3"
        # mob_recon never produced a pr_summary.tsv (it has no probabilities) --
        # its columns must be present but empty, not simply missing/KeyError.
        assert rows["mob_recon"]["pr_auc"] == ""
        assert rows["mob_recon"]["pr_n_thresholds"] == ""
    print("ALL PR-METRIC MERGE TESTS PASSED")


if __name__ == "__main__":
    main()
