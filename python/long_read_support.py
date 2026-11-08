#!/usr/bin/env python3
"""
long_read_support.py -- mean long-read depth per truth replicon.

Small plasmids are often lost in long-read size selection, so a hybrid truth
assembly can contain a small plasmid that only the short reads support. Such
a plasmid is reported, but label_truth_evidence.py treats it as lower
confidence (AMBIGUOUS, excluded from the headline) when its long-read depth
is below a threshold.

Input: a minimap2 PAF of the isolate's long reads against the truth
reference (-x map-ont / map-pb / map-hifi, --secondary=no). Output TSV:
sequence_id, length, mean_depth, reads.

Standard library only.
"""

import argparse
import csv
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--min-mapq", type=int, default=20)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.truth, newline="", encoding="utf-8") as handle:
        lengths = {row["sequence_id"]: int(row["length"]) for row in csv.DictReader(handle, delimiter="\t")}
    aligned, reads = defaultdict(int), defaultdict(set)
    with open(args.paf, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[5] not in lengths or int(fields[11]) < args.min_mapq:
                continue
            aligned[fields[5]] += abs(int(fields[8]) - int(fields[7]))
            reads[fields[5]].add(fields[0])
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "length", "mean_depth", "reads"])
        for seq, length in lengths.items():
            depth = aligned[seq] / length if length else 0.0
            writer.writerow([seq, length, f"{depth:.2f}", len(reads[seq])])


if __name__ == "__main__":
    main()
