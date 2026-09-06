#!/usr/bin/env python3
"""Regression for python/measure_read_quality.py: exact mean Phred quality
against a hand-computed synthetic FASTQ (analytic fixture, not approximate)."""

import gzip
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "python", "measure_read_quality.py")


def phred_char(score):
    return chr(score + 33)


def main():
    with tempfile.TemporaryDirectory(prefix="read_quality_") as tmp:
        # Two reads: read1 has 4 bases all at Phred 20; read2 has 2 bases at
        # Phred 10. Mean = (4*20 + 2*10) / 6 = 100/6 = 16.6667.
        fastq = os.path.join(tmp, "long_reads.fastq")
        with open(fastq, "w", encoding="utf-8") as handle:
            handle.write("@read1\nACGT\n+\n" + phred_char(20) * 4 + "\n")
            handle.write("@read2\nAC\n+\n" + phred_char(10) * 2 + "\n")
        out = os.path.join(tmp, "observed_read_quality.tsv")
        subprocess.run([sys.executable, SCRIPT, "--fastq", fastq, "--out", out], check=True, capture_output=True, text=True)
        with open(out, encoding="utf-8") as handle:
            header = handle.readline().strip().split("\t")
            row = dict(zip(header, handle.readline().strip().split("\t")))
        assert row["total_bases"] == "6", row
        assert abs(float(row["mean_phred_quality"]) - (100 / 6)) < 1e-4, row
        print("exact mean Phred quality against a hand-computed fixture -> PASS")

        # gzip input must work identically.
        fastq_gz = os.path.join(tmp, "long_reads.fastq.gz")
        with open(fastq, "rb") as src, gzip.open(fastq_gz, "wb") as dst:
            dst.write(src.read())
        out_gz = os.path.join(tmp, "observed_read_quality_gz.tsv")
        subprocess.run([sys.executable, SCRIPT, "--fastq", fastq_gz, "--out", out_gz], check=True, capture_output=True, text=True)
        with open(out_gz, encoding="utf-8") as handle:
            handle.readline()
            row_gz = handle.readline().strip()
        with open(out, encoding="utf-8") as handle:
            handle.readline()
            row_plain = handle.readline().strip()
        assert row_gz == row_plain, "gzip and plain input must produce identical results"
        print("gzip-compressed FASTQ produces the identical result -> PASS")

        # Empty FASTQ (no reads) is a genuine error, not a silent zero.
        empty = os.path.join(tmp, "empty.fastq")
        open(empty, "w", encoding="utf-8").close()
        result = subprocess.run([sys.executable, SCRIPT, "--fastq", empty, "--out", os.path.join(tmp, "x.tsv")],
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert "no reads found" in result.stderr
        print("an empty FASTQ is a genuine error, not a silent zero-quality result -> PASS")

    print("ALL MEASURE READ QUALITY TESTS PASSED")


if __name__ == "__main__":
    main()
