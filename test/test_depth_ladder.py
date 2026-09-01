#!/usr/bin/env python3
"""Regression tests for depth-ladder result summarization."""

import csv
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "summarize_depth_ladder.py")


def write_tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="depth_ladder_test_") as tmp:
        manifest = os.path.join(tmp, "manifest.tsv")
        scores = os.path.join(tmp, "scores.tsv")
        prefix = os.path.join(tmp, "depth")
        write_tsv(manifest, ["sample_id", "parent_sample_id", "target_depth_x", "source_depth_x", "fraction", "seed"], [
            ["isolate_a__20x", "isolate_a", "20", "80", "0.25", "1"],
            ["isolate_a__80x", "isolate_a", "80", "80", "1", "1"],
            ["isolate_b__20x", "isolate_b", "20", "80", "0.25", "1"],
            ["isolate_b__80x", "isolate_b", "80", "80", "1", "1"],
        ])
        write_tsv(scores, ["sample", "tool", "precision", "recall", "f1", "plasmid_recall"], [
            ["isolate_a__20x", "tool_a", "0.8", "0.4", "0.5", "0.2"],
            ["isolate_b__20x", "tool_a", "0.8", "0.6", "0.7", "0.4"],
            ["isolate_a__80x", "tool_a", "0.9", "0.8", "0.85", "0.8"],
            ["isolate_b__80x", "tool_a", "0.9", "1.0", "0.95", "1.0"],
            ["unrelated", "tool_a", "0", "0", "0", "0"],
        ])
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--manifest", manifest,
                        "--out-prefix", prefix], check=True)
        with open(prefix + ".summary.tsv", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert [(row["target_depth_x"], row["n_scored"], row["f1"]) for row in rows] == [
            ("20", "2", "0.600000"), ("80", "2", "0.900000")]
        with open(prefix + ".recovery.svg", encoding="utf-8") as handle:
            svg = handle.read()
        assert "Recovery versus read depth" in svg and "tool_a" in svg and "80x" in svg
    print("ALL DEPTH LADDER TESTS PASSED")


if __name__ == "__main__":
    main()
