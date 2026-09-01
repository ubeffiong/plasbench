#!/usr/bin/env python3
"""Regression checks for aggregation when execution status is unavailable."""

import csv
import json
import os
import re
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AGGREGATE = os.path.join(HERE, "..", "python", "aggregate_results.py")


def write_tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="aggregate_test_") as tmp:
        scores = os.path.join(tmp, "scores.tsv")
        prefix = os.path.join(tmp, "benchmark")
        with open(scores, "w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow([
                "sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                "unmapped_pred_bp", "precision", "recall", "f1", "bin_precision",
                "bin_recall", "bin_f1", "matched_bins", "unmatched_bins", "missed_plasmids",
                "split_events", "merge_events", "contaminated_bins",
            ])
            writer.writerow(["sample1", "tool_a", 100, 80, 20, 20, 0, "0.8000", "0.8000", "0.8000",
                             "0.5", "0.5", "0.5", 1, 1, 1, 2, 3, 4])

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

        # The direct report builder must preserve optional cohort metadata and
        # manifest-recorded versions for filtering/export, without requiring a
        # fixed cohort vocabulary.
        sample_sheet = os.path.join(tmp, "cohort.tsv")
        with open(sample_sheet, "w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier", "biosample", "bioproject", "sample_origin", "read_depth_x"])
            writer.writerow(["sample1", "GCF_000000000.1", "SRR0000001", "Example species", "hybrid", "A", "SAMN00000001", "PRJNA000001", "wastewater", "72"])
        manifest = os.path.join(tmp, "run_manifest.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"tools": {"mob_recon": {"available": True, "version": "3.1.9"}}}, handle)
        rich_report = os.path.join(tmp, "rich.report.html")
        subprocess.run([
            sys.executable, os.path.join(ROOT, "python", "build_html_report.py"),
            "--project-root", ROOT, "--scores", scores,
            "--tool-status", os.path.join(tmp, "not-created.tsv"),
            "--leaderboard", prefix + ".leaderboard.tsv", "--sample-sheet", sample_sheet,
            "--manifest", manifest, "--out", rich_report,
        ], check=True)
        with open(rich_report, encoding="utf-8") as handle:
            page = handle.read()
        assert "wastewater" in page and "read_depth_x" not in page
        assert "Tool version" in page and "Plasmid size" in page and "Depth ≥" in page
        assert "Bin reconstruction diagnostics" in page and "Split events" in page and "Merge events" in page
        assert "Contaminated bins" in page
    # Depth-ladder points share a genome, so they must never be ranked as
    # independent samples -- detected from the rows, not from a sibling file.
    with tempfile.TemporaryDirectory() as tmp:
        correlated = os.path.join(tmp, "scores.tsv")
        write_tsv(correlated, ["sample", "tool", "precision", "recall", "f1", "plasmid_recall"],
                  [["s__20x", "tool_a", "0.9", "0.9", "0.9", "1.0"],
                   ["s__40x", "tool_a", "0.9", "0.9", "0.95", "1.0"]])
        sheet = os.path.join(tmp, "moved.tsv")
        write_tsv(sheet, ["sample_id", "sra_run", "parent_sample_id"],
                  [["s__20x", "SRR1", "s"], ["s__40x", "SRR1", "s"]])
        for label, argv in (("declared parent", ["--sample-sheet", sheet]), ("id convention only", [])):
            blocked = subprocess.run(
                [sys.executable, os.path.join(ROOT, "python", "aggregate_results.py"),
                 "--scores", correlated, "--out-prefix", os.path.join(tmp, "blocked"), *argv],
                text=True, capture_output=True)
            assert blocked.returncode != 0, label
            assert "correlated samples" in blocked.stderr, label
    # The manifest must record the checkout's version, not a stale installed one.
    sys.path.insert(0, os.path.join(ROOT, "python"))
    import write_manifest
    init = os.path.join(ROOT, "plasbench", "__init__.py")
    source = re.search(r"""__version__\s*=\s*["']([^"']+)["']""",
                       open(init, encoding="utf-8").read()).group(1)
    assert write_manifest.tool_version() == source,         f"manifest version {write_manifest.tool_version()} != checkout {source}"

    print("ALL AGGREGATION TESTS PASSED")


if __name__ == "__main__":
    main()
