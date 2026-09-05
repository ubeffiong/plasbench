#!/usr/bin/env python3
"""Regression tests for read-quality-ladder result summarization and input
generation (structural clone of test_depth_ladder.py)."""

import csv
import gzip
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "summarize_read_quality_ladder.py")


def write_tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="read_quality_ladder_test_") as tmp:
        manifest = os.path.join(tmp, "manifest.tsv")
        scores = os.path.join(tmp, "scores.tsv")
        prefix = os.path.join(tmp, "rq")
        write_tsv(manifest, ["sample_id", "parent_sample_id", "rung_label", "min_length", "min_mean_q", "retained_reads"], [
            ["isolate_a__len1000_q8", "isolate_a", "len1000_q8", "1000", "8", "500"],
            ["isolate_a__len20000_q15", "isolate_a", "len20000_q15", "20000", "15", "100"],
            ["isolate_b__len1000_q8", "isolate_b", "len1000_q8", "1000", "8", "500"],
            ["isolate_b__len20000_q15", "isolate_b", "len20000_q15", "20000", "15", "100"],
        ])
        write_tsv(scores, ["sample", "tool", "precision", "recall", "f1", "plasmid_recall"], [
            ["isolate_a__len1000_q8", "tool_a", "0.8", "0.4", "0.5", "0.2"],
            ["isolate_b__len1000_q8", "tool_a", "0.8", "0.6", "0.7", "0.4"],
            ["isolate_a__len20000_q15", "tool_a", "0.9", "0.8", "0.85", "0.8"],
            ["isolate_b__len20000_q15", "tool_a", "0.9", "1.0", "0.95", "1.0"],
            ["unrelated", "tool_a", "0", "0", "0", "0"],
        ])
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--manifest", manifest,
                        "--out-prefix", prefix], check=True)
        with open(prefix + ".summary.tsv", newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert [(row["min_length"], row["n_scored"], row["f1"]) for row in rows] == [
            ("1000", "2", "0.600000"), ("20000", "2", "0.900000")]
        with open(prefix + ".recovery.svg", encoding="utf-8") as handle:
            svg = handle.read()
        assert "Recovery versus read-length rung" in svg and "tool_a" in svg and "20000bp" in svg
    check_make_ladder()
    print("ALL READ QUALITY LADDER TESTS PASSED")


def check_make_ladder():
    """Exercise make_read_quality_ladder.py's own input-generation logic
    offline, stubbing filtlong/gzip the same way test_depth_ladder.py stubs
    seqtk/gzip -- this is a length/quality FILTER, not a random subsample, so
    there is deliberately no --seed to thread through."""
    sys.path.insert(0, os.path.join(HERE, "..", "python"))
    import types
    import make_read_quality_ladder as ladder

    with tempfile.TemporaryDirectory(prefix="rq_ladder_local_") as tmp:
        sample = os.path.join(tmp, "data", "local")
        os.makedirs(sample)
        write_tsv(os.path.join(sample, "truth.tsv"),
                  ["sequence_id", "molecule_type", "length"], [["chr", "CHROMOSOME", "1000"]])
        with open(os.path.join(sample, "reference.fna"), "w", encoding="utf-8") as handle:
            handle.write(">chr\nACGT\n")
        with gzip.open(os.path.join(sample, "long_reads.fastq.gz"), "wt", encoding="utf-8") as handle:
            handle.write("@r\n" + "A" * 30000 + "\n+\n" + "I" * 30000 + "\n")
        samples = os.path.join(tmp, "samples.tsv")
        write_tsv(samples, ["sample_id"], [["local"]])

        original = (ladder.shutil.which, ladder.subprocess.Popen, ladder.subprocess.run)
        ladder.shutil.which = lambda name: "/stub/" + name
        ladder.subprocess.Popen = lambda cmd, stdout=None: types.SimpleNamespace(
            stdout=types.SimpleNamespace(close=lambda: None), wait=lambda: 0)
        ladder.subprocess.run = lambda cmd, stdin=None, stdout=None, check=False: (
            stdout.write(gzip.compress(b"@r\nACGTACGTACGT\n+\nIIIIIIIIIIII\n")), types.SimpleNamespace(returncode=0))[1]
        out = os.path.join(tmp, "out")
        argv = sys.argv
        try:
            sys.argv = ["make_read_quality_ladder.py", "--samples", samples, "--data-dir",
                        os.path.join(tmp, "data"), "--out-dir", out, "--rungs", "1000:8,20000:15"]
            ladder.main()
        finally:
            sys.argv = argv
            ladder.shutil.which, ladder.subprocess.Popen, ladder.subprocess.run = original

        derived = os.path.join(out, "data", "local__len1000_q8")
        assert os.path.isfile(os.path.join(derived, "truth.tsv"))
        assert os.path.isfile(os.path.join(derived, "long_reads.fastq.gz"))
        with open(os.path.join(out, "read_quality_ladder.samples.tsv"), newline="", encoding="utf-8") as handle:
            first = next(csv.DictReader(handle, delimiter="\t"))
        assert first["parent_sample_id"] == "local"
        with open(os.path.join(out, "read_quality_ladder.manifest.tsv"), newline="", encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert len(manifest_rows) == 2
        assert manifest_rows[0]["retained_reads"] == "1"  # one @r record in the stubbed output


if __name__ == "__main__":
    main()
