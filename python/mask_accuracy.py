#!/usr/bin/env python3
"""Blank nucleotide-accuracy rates where the truth cannot support them.

Identity, mismatch, insertion and deletion rates compare a prediction with the reference at the
base level. That is only meaningful if the reference was not polished with the same Illumina
reads the tools are benchmarked on: otherwise the truth carries the very errors the reads
carry, and a tool can look accurate for sharing them. truth_provenance.py records this per
sample as `base_level_metrics_valid` (yes or no), and the CPRR identity criterion already uses
it. This script applies the same rule to the accuracy table:

  * a sample whose provenance says `no` has its rates blanked and `accuracy_status` set to
    `not_assessable_truth_polished_with_benchmark_reads`
  * a sample with a `yes`, or with no provenance record, keeps its rates (`evaluated`)
  * a row with no decodable CIGAR stays blank (`no_cigar`)

Coverage-based metrics are unaffected; they do not depend on base-level truth accuracy. The
table is rewritten in place (or to --out) with one extra column. Blank means not assessable,
never zero. Standard library only.
"""
import argparse
import csv
import sys

STATUS = "accuracy_status"
RATE_COLUMNS = ("identity", "mismatch_rate", "insertion_rate", "deletion_rate")


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return reader.fieldnames or [], list(reader)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accuracy", required=True, help="merged accuracy.tsv")
    ap.add_argument("--truth-provenance", help="benchmark.truth_provenance.tsv (sample, base_level_metrics_valid)")
    ap.add_argument("--out", help="default: rewrite --accuracy in place")
    args = ap.parse_args()
    fields, rows = read(args.accuracy)
    valid = {}
    if args.truth_provenance:
        try:
            _, prov = read(args.truth_provenance)
            valid = {r["sample"]: r.get("base_level_metrics_valid") for r in prov}
        except (OSError, KeyError):
            sys.stderr.write("[mask_accuracy] truth provenance unreadable; rates are left as computed\n")
    if STATUS not in fields:
        fields = list(fields) + [STATUS]
    masked = 0
    for row in rows:
        if valid.get(row["sample"]) == "no":
            for column in RATE_COLUMNS:
                if column in row:
                    row[column] = ""
            row[STATUS] = "not_assessable_truth_polished_with_benchmark_reads"
            masked += 1
        elif not row.get("identity"):
            row[STATUS] = "no_cigar"
        else:
            row[STATUS] = "evaluated"
    with open(args.out or args.accuracy, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    sys.stderr.write(f"[mask_accuracy] {masked} row(s) not assessable (truth polished with the benchmark's reads)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
