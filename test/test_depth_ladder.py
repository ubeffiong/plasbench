#!/usr/bin/env python3
"""Regression tests for depth-ladder result summarization."""

import csv
import gzip
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "summarize_depth_ladder.py")
MEASURE = os.path.join(HERE, "..", "python", "measure_depth.py")


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
        truth = os.path.join(tmp, "truth.tsv")
        write_tsv(truth, ["sequence_id", "molecule_type", "length"], [["chr", "CHROMOSOME", "10"]])
        for mate in ("r1", "r2"):
            with gzip.open(os.path.join(tmp, mate + ".fastq.gz"), "wt", encoding="utf-8") as handle:
                handle.write("@read\nACGT\n+\n!!!!\n")
        depth = os.path.join(tmp, "observed_depth.tsv")
        subprocess.run([sys.executable, MEASURE, "--truth", truth, "--r1", os.path.join(tmp, "r1.fastq.gz"),
                        "--r2", os.path.join(tmp, "r2.fastq.gz"), "--out", depth], check=True)
        with open(depth, newline="", encoding="utf-8") as handle:
            assert next(csv.DictReader(handle, delimiter="\t"))["observed_depth_x"] == "0.800000"
    check_local_truth_inputs()
    print("ALL DEPTH LADDER TESTS PASSED")


def check_local_truth_inputs():
    """A local cohort supplies truth.tsv instead of an NCBI sequence report."""
    sys.path.insert(0, os.path.join(HERE, "..", "python"))
    import types
    import make_depth_ladder as ladder

    with tempfile.TemporaryDirectory(prefix="ladder_local_") as tmp:
        sample = os.path.join(tmp, "data", "local")
        os.makedirs(sample)
        write_tsv(os.path.join(sample, "truth.tsv"),
                  ["sequence_id", "molecule_type", "length"], [["chr", "CHROMOSOME", "1000"]])
        write_tsv(os.path.join(sample, "observed_depth.tsv"),
                  ["reference_bp", "read_bases", "observed_depth_x"], [["1000", "80000", "80.000000"]])
        with open(os.path.join(sample, "reference.fna"), "w", encoding="utf-8") as handle:
            handle.write(">chr\nACGT\n")
        for mate in (1, 2):
            with gzip.open(os.path.join(sample, f"SRRL_{mate}.fastq.gz"), "wt", encoding="utf-8") as handle:
                handle.write("@r\nACGT\n+\n!!!!\n")
        samples = os.path.join(tmp, "samples.tsv")
        write_tsv(samples, ["sample_id", "sra_run", "read_depth_x"], [["local", "SRRL", "80"]])

        # Stub the external binaries so the input contract itself is exercised.
        original = (ladder.shutil.which, ladder.subprocess.Popen, ladder.subprocess.run)
        ladder.shutil.which = lambda name: "/stub/" + name
        ladder.subprocess.Popen = lambda cmd, stdout=None: types.SimpleNamespace(
            stdout=types.SimpleNamespace(close=lambda: None), wait=lambda: 0)
        ladder.subprocess.run = lambda cmd, stdin=None, stdout=None, check=False: (
            stdout.write(gzip.compress(b"@r\nACGT\n+\n!!!!\n")), types.SimpleNamespace(returncode=0))[1]
        out = os.path.join(tmp, "out")
        argv = sys.argv
        try:
            sys.argv = ["make_depth_ladder.py", "--samples", samples, "--data-dir",
                        os.path.join(tmp, "data"), "--out-dir", out, "--depths", "20"]
            ladder.main()
        finally:
            sys.argv = argv
            ladder.shutil.which, ladder.subprocess.Popen, ladder.subprocess.run = original

        derived = os.path.join(out, "data", "local__20x")
        assert os.path.isfile(os.path.join(derived, "truth.tsv"))
        # Stage 2 recomputes coverage for the subsample; the parent's value is wrong.
        assert not os.path.exists(os.path.join(derived, "observed_depth.tsv"))
        with open(os.path.join(out, "depth_ladder.samples.tsv"), newline="", encoding="utf-8") as handle:
            assert next(csv.DictReader(handle, delimiter="\t"))["parent_sample_id"] == "local"


if __name__ == "__main__":
    main()
