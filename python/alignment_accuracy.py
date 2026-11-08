#!/usr/bin/env python3
"""Nucleotide-level accuracy and missing-region counts for one (sample, tool).

Coverage says how much of a plasmid was recovered; it says nothing about whether the
recovered bases are right. A tool can reconstruct 99% of a plasmid with 90% identity, or
60% of it at 99.9% identity. This script reports the second dimension separately, so the
two are never confused.

It reads the same PAF the scorer reads and keeps the same alignments (length, identity,
MAPQ and query-coverage filters; secondary rows dropped), then, for blocks that land on a
truth PLASMID, decodes the CIGAR (`cg:Z:` tag, written by `minimap2 -c`) and the edit
distance (`NM:i:`):

    alignment columns = aligned (M) + inserted (I) + deleted (D)
    mismatches        = X operations when present, else NM - I - D
    identity          = (aligned - mismatches) / columns
    mismatch / insertion / deletion rate = each over the same columns

so identity + mismatch + insertion + deletion = 1 for the pooled blocks. Insertions are
bases in the prediction that the reference lacks; deletions are reference bases the
prediction lacks inside an aligned block.

A block with no `cg` tag cannot be decoded and is counted in `n_blocks_without_cigar`,
never guessed. If no block can be decoded the accuracy fields are blank, which means "not
evaluated", never zero.

Missing regions are reference intervals no retained alignment covers, per truth plasmid:
their count, total length and longest. A plasmid is treated as linear here, so a gap that
spans the origin of a circular plasmid is counted as two.

SNP concordance is not computed: it needs known variant positions, and a single
same-isolate reference has none. This is a limit of the design, not an omission.

Descriptive only. It never changes scores.tsv or any ranking. Standard library only.
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict

CIGAR_OP = re.compile(r"(\d+)([MIDNSHP=X])")
SUMMARY_FIELDS = ("sample", "tool", "analysis_track", "n_blocks", "n_blocks_without_cigar",
                  "aligned_columns", "identity", "mismatch_rate", "insertion_rate", "deletion_rate",
                  "mismatch_bp", "inserted_bp", "deleted_bp")
REGION_FIELDS = ("sample", "tool", "sequence_id", "length", "covered_bp", "missing_regions",
                 "missing_bp", "longest_missing_bp")


def read_truth(path):
    plasmids = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["molecule_type"].upper() == "PLASMID":
                plasmids[row["sequence_id"]] = int(row["length"])
    return plasmids


def decode_cigar(cigar, edit_distance):
    """(aligned, inserted, deleted, mismatches) from a CIGAR; mismatches None if unknowable."""
    aligned = inserted = deleted = x_ops = 0
    has_eqx = False
    for length, op in CIGAR_OP.findall(cigar):
        n = int(length)
        if op == "M":
            aligned += n
        elif op == "=":
            aligned += n
            has_eqx = True
        elif op == "X":
            aligned += n
            x_ops += n
            has_eqx = True
        elif op == "I":
            inserted += n
        elif op == "D":
            deleted += n
    if has_eqx:
        mismatches = x_ops
    elif edit_distance is not None:
        mismatches = max(0, edit_distance - inserted - deleted)
    else:
        mismatches = None
    return aligned, inserted, deleted, mismatches


def merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def analyse(truth, paf, min_length, min_identity, min_mapq, min_qcov):
    plasmids = read_truth(truth)
    covered = defaultdict(list)
    n_blocks = n_nocigar = 0
    aligned = inserted = deleted = mismatches = 0
    with open(paf, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 12 or "tp:A:S" in f[12:]:
                continue
            try:
                qlen, qstart, qend = int(f[1]), int(f[2]), int(f[3])
                tname, tlen, tstart, tend = f[5], int(f[6]), int(f[7]), int(f[8])
                matches, block, mapq = int(f[9]), int(f[10]), int(f[11])
            except ValueError:
                continue
            identity = matches / block if block else 0.0
            qcov = abs(qend - qstart) / qlen if qlen else 0.0
            if block < min_length or identity < min_identity or mapq < min_mapq or qcov < min_qcov:
                continue
            if tname not in plasmids:
                continue
            tstart, tend = max(0, min(tstart, tend)), min(tlen, max(tstart, tend))
            covered[tname].append((tstart, tend))
            n_blocks += 1
            tags = {t[:2]: t[5:] for t in f[12:] if len(t) > 5 and t[2] == ":"}
            cigar = tags.get("cg")
            if not cigar:
                n_nocigar += 1
                continue
            nm = int(tags["NM"]) if tags.get("NM", "").isdigit() else None
            a, i, d, mm = decode_cigar(cigar, nm)
            if mm is None:
                n_nocigar += 1
                continue
            aligned += a
            inserted += i
            deleted += d
            mismatches += mm
    columns = aligned + inserted + deleted
    summary = {"n_blocks": n_blocks, "n_blocks_without_cigar": n_nocigar, "aligned_columns": columns,
               "mismatch_bp": mismatches, "inserted_bp": inserted, "deleted_bp": deleted}
    if columns:
        summary.update(identity=(aligned - mismatches) / columns, mismatch_rate=mismatches / columns,
                       insertion_rate=inserted / columns, deletion_rate=deleted / columns)
    regions = []
    for seq_id, length in plasmids.items():
        merged = merge(covered.get(seq_id, []))
        gaps, cursor = [], 0
        for start, end in merged:
            if start > cursor:
                gaps.append(start - cursor)
            cursor = max(cursor, end)
        if cursor < length:
            gaps.append(length - cursor)
        regions.append({"sequence_id": seq_id, "length": length,
                        "covered_bp": sum(e - s for s, e in merged), "missing_regions": len(gaps),
                        "missing_bp": sum(gaps), "longest_missing_bp": max(gaps) if gaps else 0})
    return summary, regions


def fmt(value):
    return "" if value is None else (f"{value:.6f}" if isinstance(value, float) else str(value))


def append_rows(path, fields, rows):
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        if new:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in fields})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--analysis-track", default="short_read")
    ap.add_argument("--out", required=True, help="append one summary row (accuracy.tsv)")
    ap.add_argument("--regions-out", help="append one row per truth plasmid (missing_regions.tsv)")
    ap.add_argument("--min-alignment-length", type=int, default=int(os.environ.get("MIN_ALIGNMENT_LENGTH", 200)))
    ap.add_argument("--min-alignment-identity", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_IDENTITY", 0.90)))
    ap.add_argument("--min-alignment-mapq", type=int, default=int(os.environ.get("MIN_ALIGNMENT_MAPQ", 20)))
    ap.add_argument("--min-alignment-query-coverage", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_QUERY_COVERAGE", 0.20)))
    args = ap.parse_args()
    summary, regions = analyse(args.truth, args.paf, args.min_alignment_length, args.min_alignment_identity,
                               args.min_alignment_mapq, args.min_alignment_query_coverage)
    meta = {"sample": args.sample, "tool": args.tool, "analysis_track": args.analysis_track}
    append_rows(args.out, SUMMARY_FIELDS, [{**meta, **summary}])
    if args.regions_out:
        append_rows(args.regions_out, REGION_FIELDS, [{**meta, **r} for r in regions])
    return 0


if __name__ == "__main__":
    sys.exit(main())
