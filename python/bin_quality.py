#!/usr/bin/env python3
"""Quality-tier bin yield and homogeneity / completeness for one (sample, tool).

A surveillance laboratory asks "would I trust this bin?", not "what is the F1?". This script
translates a tool's bins into the usual quality tiers and reports the share of truth plasmids
that end up in a trustworthy bin.

For each bin the best-overlapping truth plasmid p* is found on the reference. Then:
    completeness  = reference bases of p* covered by the bin / length of p*
    contamination = 1 - (bin bases that align to p*) / (bin bases that align anywhere)
Tiers (thresholds are options; defaults follow the genome-bin convention):
    high    completeness >= 0.90 and contamination <= 0.05
    medium  completeness >= 0.50 and contamination <= 0.10
    low     any other bin that aligns to a truth plasmid
    spurious  a bin that aligns to no truth plasmid at all (chromosome, foreign or unmapped)
A plasmid split over several bins is judged by its best bin.
  high_quality_yield          = truth plasmids with a high bin / truth plasmids
  medium_or_better_yield      = truth plasmids with a high or medium bin / truth plasmids

Homogeneity and completeness (clustering sense) use the same base-pair weighted contingency
table as the NMI in score_bins.py: rows are the real bins plus an `unassigned` row for truth
plasmid bases no bin covers, columns are the truth plasmids plus `CHROMOSOME` for chromosome
bases a bin wrongly claims, and unclaimed chromosome is left out (it is the correct outcome
for most of a genome, not a clustering decision). Homogeneity = 1 - H(truth|bin)/H(truth);
completeness = 1 - H(bin|truth)/H(bin); V-measure is their harmonic mean. They are descriptive
secondary statistics: base-pair weighted, so contig length is not ignored, but not repeat-aware.

These are secondary diagnostics. The binning endpoint is the length-weighted binning F1 (ungated one-to-one
match) and CPRR from score_bins.py; nothing here is a competing headline, and this script does not re-match
bins to plasmids, it only reads which truth plasmid each bin overlaps most.

Blank means not evaluated (for example, no plasmid or no bin), never zero. Descriptive only;
never changes scores.tsv. Standard library only.
"""
import argparse
import csv
import math
import os
import sys
from collections import defaultdict

FIELDS = ("sample", "tool", "analysis_track", "n_truth_plasmids", "n_bins", "n_high", "n_medium", "n_low",
          "n_spurious", "plasmids_with_high_bin", "plasmids_with_medium_or_better_bin", "high_quality_yield",
          "medium_or_better_yield", "homogeneity", "completeness", "v_measure")


def read_truth(path):
    plasmids, chromosomes = {}, {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            target = plasmids if row["molecule_type"].upper() == "PLASMID" else chromosomes
            target[row["sequence_id"]] = int(row["length"])
    return plasmids, chromosomes


def read_bins(path):
    membership = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("bin_id") and row.get("sequence_id"):
                membership[row["sequence_id"]] = row["bin_id"]
    return membership


def union_bp(intervals):
    total, cursor = 0, -1
    for start, end in sorted(intervals):
        start = max(start, cursor)
        if end > start:
            total += end - start
            cursor = end
    return total


def read_alignments(paf, membership, plasmids, chromosomes, min_length, min_identity, min_mapq, min_qcov):
    """bin -> target -> [(tstart, tend)] and bin -> mapped query bases (any truth target)."""
    ref = defaultdict(lambda: defaultdict(list))
    query = defaultdict(list)
    with open(paf, encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 12 or "tp:A:S" in f[12:] or f[0] not in membership:
                continue
            try:
                qlen, qs, qe, tname = int(f[1]), int(f[2]), int(f[3]), f[5]
                ts, te, matches, block, mapq = int(f[7]), int(f[8]), int(f[9]), int(f[10]), int(f[11])
            except ValueError:
                continue
            if block < min_length or mapq < min_mapq or (matches / block if block else 0) < min_identity:
                continue
            if (abs(qe - qs) / qlen if qlen else 0) < min_qcov:
                continue
            if tname not in plasmids and tname not in chromosomes:
                continue
            bin_id = membership[f[0]]
            ref[bin_id][tname].append((min(ts, te), max(ts, te)))
            query[(bin_id, f[0])].append((min(qs, qe), max(qs, qe)))
    mapped = defaultdict(int)
    for (bin_id, _), intervals in query.items():
        mapped[bin_id] += union_bp(intervals)
    return ref, mapped


def entropy(weights):
    total = sum(weights)
    return -sum((w / total) * math.log(w / total) for w in weights if w > 0) if total > 0 else 0.0


def homogeneity_completeness(table):
    """table: {row: {column: bp}} -> (homogeneity, completeness, v) or Nones when undefined."""
    total = sum(sum(cols.values()) for cols in table.values())
    if total <= 0:
        return None, None, None
    col_weights = defaultdict(float)
    for cols in table.values():
        for col, bp in cols.items():
            col_weights[col] += bp
    h_truth = entropy(list(col_weights.values()))
    h_bins = entropy([sum(cols.values()) for cols in table.values()])
    h_truth_given_bin = sum(sum(cols.values()) / total * entropy(list(cols.values())) for cols in table.values())
    h_bin_given_truth = 0.0
    for col, weight in col_weights.items():
        h_bin_given_truth += weight / total * entropy([table[row].get(col, 0) for row in table])
    homogeneity = 1.0 if h_truth == 0 else 1 - h_truth_given_bin / h_truth
    completeness = 1.0 if h_bins == 0 else 1 - h_bin_given_truth / h_bins
    v = 0.0 if homogeneity + completeness == 0 else 2 * homogeneity * completeness / (homogeneity + completeness)
    return homogeneity, completeness, v


def analyse(plasmids, chromosomes, ref, mapped, bins, thresholds):
    high_c, high_k, med_c, med_k = thresholds
    tiers = {"high": 0, "medium": 0, "low": 0, "spurious": 0}
    best_tier_for = {}                     # plasmid -> best tier rank among bins whose best match it is
    rank = {"high": 3, "medium": 2, "low": 1}
    table = {}
    covered_plasmid = defaultdict(list)
    for bin_id in bins:
        by_target = ref.get(bin_id, {})
        overlaps = {t: union_bp(iv) for t, iv in by_target.items() if t in plasmids}
        chromosome_bp = sum(union_bp(iv) for t, iv in by_target.items() if t in chromosomes)
        row = {t: bp for t, bp in overlaps.items() if bp > 0}
        if chromosome_bp:
            row["CHROMOSOME"] = chromosome_bp
        for t, iv in by_target.items():
            if t in plasmids:
                covered_plasmid[t].extend(iv)
        if row:
            table[bin_id] = row
        best = max(overlaps, key=overlaps.get) if overlaps and max(overlaps.values()) > 0 else None
        if best is None:
            tiers["spurious"] += 1
            continue
        completeness = overlaps[best] / plasmids[best]
        total_mapped = mapped.get(bin_id, 0)
        contamination = 1 - overlaps[best] / total_mapped if total_mapped else 1.0
        if completeness >= high_c and contamination <= high_k:
            tier = "high"
        elif completeness >= med_c and contamination <= med_k:
            tier = "medium"
        else:
            tier = "low"
        tiers[tier] += 1
        best_tier_for[best] = max(best_tier_for.get(best, 0), rank[tier])
    unassigned = {t: plasmids[t] - union_bp(covered_plasmid.get(t, [])) for t in plasmids}
    unassigned = {t: bp for t, bp in unassigned.items() if bp > 0}
    if unassigned:
        table["__unassigned__"] = unassigned
    n = len(plasmids)
    with_high = sum(1 for v in best_tier_for.values() if v == 3)
    with_med = sum(1 for v in best_tier_for.values() if v >= 2)
    hom, comp, v = homogeneity_completeness(table) if bins else (None, None, None)
    return {"n_truth_plasmids": n, "n_bins": len(bins), "n_high": tiers["high"], "n_medium": tiers["medium"],
            "n_low": tiers["low"], "n_spurious": tiers["spurious"], "plasmids_with_high_bin": with_high,
            "plasmids_with_medium_or_better_bin": with_med,
            "high_quality_yield": with_high / n if n else None,
            "medium_or_better_yield": with_med / n if n else None,
            "homogeneity": hom, "completeness": comp, "v_measure": v}


def fmt(value):
    return "" if value is None else (f"{value:.6f}" if isinstance(value, float) else str(value))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--bins", required=True, help="TSV with sequence_id and bin_id")
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--analysis-track", default="short_read")
    ap.add_argument("--out", required=True, help="append one row")
    ap.add_argument("--high-completeness", type=float, default=0.90)
    ap.add_argument("--high-contamination", type=float, default=0.05)
    ap.add_argument("--medium-completeness", type=float, default=0.50)
    ap.add_argument("--medium-contamination", type=float, default=0.10)
    ap.add_argument("--min-alignment-length", type=int, default=int(os.environ.get("MIN_ALIGNMENT_LENGTH", 200)))
    ap.add_argument("--min-alignment-identity", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_IDENTITY", 0.90)))
    ap.add_argument("--min-alignment-mapq", type=int, default=int(os.environ.get("MIN_ALIGNMENT_MAPQ", 20)))
    ap.add_argument("--min-alignment-query-coverage", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_QUERY_COVERAGE", 0.20)))
    args = ap.parse_args()
    plasmids, chromosomes = read_truth(args.truth)
    membership = read_bins(args.bins)
    ref, mapped = read_alignments(args.paf, membership, plasmids, chromosomes, args.min_alignment_length,
                                  args.min_alignment_identity, args.min_alignment_mapq,
                                  args.min_alignment_query_coverage)
    bins = sorted(set(membership.values()))
    result = analyse(plasmids, chromosomes, ref, mapped, bins,
                     (args.high_completeness, args.high_contamination,
                      args.medium_completeness, args.medium_contamination))
    row = {"sample": args.sample, "tool": args.tool, "analysis_track": args.analysis_track, **result}
    new = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    with open(args.out, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerow({k: fmt(row.get(k)) for k in FIELDS})
    return 0


if __name__ == "__main__":
    sys.exit(main())
