#!/usr/bin/env python3
"""Regression checks for aggregation when execution status is unavailable."""

import csv
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGGREGATE = os.path.join(HERE, "..", "python", "aggregate_results.py")


def main():
    with tempfile.TemporaryDirectory(prefix="aggregate_test_") as tmp:
        scores = os.path.join(tmp, "scores.tsv")
        prefix = os.path.join(tmp, "benchmark")
        with open(scores, "w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow([
                "sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                "unmapped_pred_bp", "precision", "recall", "f1",
            ])
            writer.writerow(["sample1", "tool_a", 100, 80, 20, 20, 0, "0.8000", "0.8000", "0.8000"])

        subprocess.run([
            sys.executable, AGGREGATE, "--scores", scores,
            "--tool-status", os.path.join(tmp, "not-created.tsv"),
            "--out-prefix", prefix,
        ], check=True)

        with open(prefix + ".leaderboard.tsv", newline="") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["tool"] == "tool_a"
        assert row["n_completed"] == "0"
        assert row["n_failed"] == "0"
        assert row["n_skipped"] == "0"

        # A report can be rebuilt from a shared results directory even when
        # the original sample sheet and stage-4 status file are unavailable.
        subprocess.run([
            sys.executable, "-m", "plasbench", "--project-root", ROOT,
            "report", "--results-dir", tmp,
        ], cwd=ROOT, check=True)
        report = os.path.join(tmp, "benchmark.report.html")
        assert os.path.isfile(report)
        with open(report, encoding="utf-8") as handle:
            assert "tool_a" in handle.read()
    print("ALL AGGREGATION TESTS PASSED")


if __name__ == "__main__":
    main()
