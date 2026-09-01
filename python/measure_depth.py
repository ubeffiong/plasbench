#!/usr/bin/env python3
"""Measure paired-read coverage against the labelled reference length."""
import argparse, csv, gzip

def reference_bp(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return sum(int(row["length"]) for row in csv.DictReader(handle, delimiter="\t"))

def fastq_bp(path):
    total = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle):
            if number % 4 == 1:
                total += len(line.rstrip("\r\n"))
    return total

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True); parser.add_argument("--r1", required=True); parser.add_argument("--r2", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args()
    reference = reference_bp(args.truth)
    if reference <= 0: raise SystemExit("ERROR: truth table has no reference bases")
    bases = fastq_bp(args.r1) + fastq_bp(args.r2)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("reference_bp", "read_bases", "observed_depth_x"), delimiter="\t")
        writer.writeheader(); writer.writerow({"reference_bp": reference, "read_bases": bases, "observed_depth_x": f"{bases / reference:.6f}"})

if __name__ == "__main__": main()
