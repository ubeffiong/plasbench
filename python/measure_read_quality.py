#!/usr/bin/env python3
"""Measure mean per-base Phred quality for a long-read FASTQ.

Standard library only, modeled directly on measure_depth.py. Powers
read_quality_band, the long-read/hybrid analog of read_depth_band -- an
isolate's own long-read quality characteristic, not a synthetic
read-quality-ladder rung (make_read_quality_ladder.py's filtlong rungs are a
derived experiment applied on top of real reads, not a property of the reads
themselves).

Usage:
  measure_read_quality.py --fastq long_reads.fastq.gz --out observed_read_quality.tsv
"""
import argparse
import gzip

PHRED_OFFSET = 33  # Phred+33: standard for ONT/PacBio and Illumina 1.8+


def open_maybe_gz(path, mode="rt"):
    return gzip.open(path, mode) if path.endswith(".gz") else open(path, mode)


def mean_phred_quality(path):
    total_score = 0
    total_bases = 0
    with open_maybe_gz(path) as handle:
        for number, line in enumerate(handle):
            if number % 4 == 3:  # FASTQ quality line
                stripped = line.rstrip("\r\n")
                total_score += sum(ord(char) - PHRED_OFFSET for char in stripped)
                total_bases += len(stripped)
    return total_score, total_bases


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fastq", required=True, help="long-read FASTQ (.fastq/.fastq.gz)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    total_score, total_bases = mean_phred_quality(args.fastq)
    if total_bases == 0:
        raise SystemExit(f"ERROR: no reads found in {args.fastq}")
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        handle.write("total_bases\tmean_phred_quality\n")
        handle.write(f"{total_bases}\t{total_score / total_bases:.4f}\n")


if __name__ == "__main__":
    main()
