#!/usr/bin/env python3
"""Regression checks for conservative candidate selection and file retention."""
import csv
import json
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "select_operational_method.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        samples = os.path.join(directory, "samples.tsv")
        scores = os.path.join(directory, "scores.tsv")
        results = os.path.join(directory, "results")
        os.makedirs(os.path.join(results, "s1"))
        with open(samples, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample_id", "organism", "truth_technology", "sample_origin", "read_depth_x"], delimiter="\t")
            writer.writeheader(); writer.writerow({"sample_id": "s1", "organism": "Example bacterium", "truth_technology": "hybrid", "sample_origin": "clinical", "read_depth_x": "100"})
        fields = ["sample", "tool", "true_plasmid_bp", "unmapped_pred_bp", "plasmid_recall", "bin_f1", "precision", "recall", "f1", "split_events", "merge_events", "contamination_fraction"]
        with open(scores, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader()
            writer.writerow({"sample": "s1", "tool": "tool_a", "true_plasmid_bp": "10000", "unmapped_pred_bp": "0", "plasmid_recall": "1", "bin_f1": "1", "precision": "1", "recall": "1", "f1": "1", "split_events": "0", "merge_events": "0", "contamination_fraction": "0"})
            writer.writerow({"sample": "s1", "tool": "tool_b", "true_plasmid_bp": "10000", "unmapped_pred_bp": "2000", "plasmid_recall": "0.7", "bin_f1": "", "precision": "0.7", "recall": "0.7", "f1": "0.7", "split_events": "1", "merge_events": "0", "contamination_fraction": "0.2"})
        open(os.path.join(results, "s1", "pred_tool_a.plasmid.fasta"), "w").write(">candidate\nACGT\n")
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--sample-sheet", samples,
                        "--results-dir", results, "--out-prefix", os.path.join(results, "benchmark"),
                        "--min-samples", "1", "--min-coverage", "1"], check=True)
        report_path = os.path.join(results, "s1", "selected_candidate", "selection_report.json")
        report = json.load(open(report_path))
        assert report["selected_tool"] == "tool_a"
        assert report["selection_type"] == "truth_set_best_candidate"
        assert report["copied_files"] == ["candidate.plasmid.fasta"]
        assert os.path.isfile(os.path.join(results, "s1", "selected_candidate", "candidate.plasmid.fasta"))
        recommendation = list(csv.DictReader(open(os.path.join(results, "benchmark.recommendations.tsv")), delimiter="\t"))
        assert any(row["scope"] == "overall" and row["tool"] == "tool_a" and row["recommendation"] == "primary" for row in recommendation)
        assert os.path.isfile(os.path.join(results, "benchmark.stratified.tsv"))
    print("ALL SELECTION TESTS PASSED")


if __name__ == "__main__": main()
