#!/usr/bin/env python3
"""Globally optimal predicted-bin versus true-plasmid matching from PAF.

Eligible edges require truth-plasmid completeness and predicted-bin purity. The
one-to-one assignment maximises total aligned plasmid bases with a Hungarian
maximum-weight bipartite match; it is not a greedy overlap heuristic.

Two further outputs implement the benchmark's headline and secondary
endpoints (docs/METHODS.md, "Endpoints"):

* Length-weighted binning precision / recall / F1 (lw_bin_*). A second,
  UNGATED Hungarian match pairs every predicted bin with at most one truth
  plasmid, maximising aligned plasmid bases. recall = bases placed in the
  correct (matched) bin / total truth-plasmid bases; precision = those same
  bases / all bases the tool's bins align to the reference (chromosome,
  other plasmids and unmatched bins all count against it). Unlike the
  count-based bin_f1, a tiny correct bin cannot outweigh a large plasmid.
* Correct Plasmid Reconstruction (CPRR, per truth plasmid, --cprr-out): a
  plasmid is correctly reconstructed only if it is identified (matched to a
  bin), covered to --cprr-min-coverage, dominates its bin to
  --cprr-min-share (no chromosome contamination or merged plasmids), is not
  split (no other bin holds >= --split-threshold of it), and -- only where
  base-level comparison is valid -- its matched alignments reach
  --cprr-min-identity. The identity criterion is reported separately so the
  aggregate can drop it for truth polished with the benchmark's own reads.
"""
import argparse
import csv
import math
import os
from collections import defaultdict
from plasbench_common import (  # noqa: E402
    merge_intervals, interval_overlap_bp as overlap, CPRR_SWEEP_THRESHOLDS, union_length, read_bin_membership,
    read_truth_split,
)
from matching import max_weight_matching  # noqa: E402


def read_truth(path):
    """(plasmid id -> length, chromosome id -> length), with the scorer's validation."""
    return read_truth_split(path)


def read_bins(path):
    return read_bin_membership(path)


def merge(intervals):
    """Covered length of the union of [start, stop) intervals; empty or reversed ones count 0."""
    return union_length(intervals)


def maximum_weight(edges, bins_list, plasmids_list):
    """Maximum-weight one-to-one bin <-> plasmid assignment: [(bin, plasmid, aligned bp)].

    The shared rectangular Hungarian (matching.py). It replaced a square O(max(B, P)^3)
    solver here; the optimum is the same, at a fraction of the cost when a tool emits
    many bins (docs/PERFORMANCE_AUDIT.md).
    """
    return max_weight_matching(edges, bins_list, plasmids_list)


def bin_ambiguity(path, membership, plasmids, chromosomes, min_length=1, min_identity=0.0,
                   min_mapq=0, min_query_coverage=0.0):
    """Return secondary-map plasmid/chromosome ambiguity bp per predicted bin."""
    if not path:
        return {}
    by_query = defaultdict(lambda: defaultdict(list))
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            fields = raw.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[0] not in membership: continue
            try:
                qlen = int(fields[1])
                start, stop = sorted((int(fields[2]), int(fields[3])))
                matches, block_length, mapq = int(fields[9]), int(fields[10]), int(fields[11])
            except ValueError: continue
            identity = matches / block_length if block_length else 0.0
            query_coverage = abs(stop - start) / qlen if qlen else 0.0
            if (block_length < min_length or identity < min_identity or mapq < min_mapq
                    or query_coverage < min_query_coverage): continue
            target = fields[5]
            if target in plasmids: by_query[fields[0]]["PLASMID"].append((start, stop))
            elif target in chromosomes: by_query[fields[0]]["CHROMOSOME"].append((start, stop))
    by_bin = defaultdict(int)
    for query, types in by_query.items():
        if types["PLASMID"] and types["CHROMOSOME"]:
            by_bin[membership[query]] += overlap(merge_intervals(types["PLASMID"]), merge_intervals(types["CHROMOSOME"]))
    return by_bin


def safe_div(a, b):
    return a / b if b else 0.0


def bp_entropy(weights_by_label):
    """Shannon entropy (natural log) of a discrete bp-weighted distribution."""
    total = sum(weights_by_label.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for weight in weights_by_label.values():
        if weight <= 0:
            continue
        p = weight / total
        entropy -= p * math.log(p)
    return entropy


def clustering_agreement(overlaps, plasmids, chromosome_bp, all_bins):
    """NMI and Variation of Information over a deliberately scoped bp-weighted
    contingency table -- NOT just the matched-pair bins the Hungarian
    assignment above picked, so a tool that over-merges everything into one
    bin, or leaves plasmid sequence completely unassigned, is actually
    penalized here rather than invisible to it (both would score well under
    a "matched pairs only" metric).

    Rows (predicted clusters): every real bin_id, plus a virtual
    "__unassigned__" row for true-plasmid bp that NO bin covers at all
    (a missed plasmid, or a partially-recovered one).
    Columns (truth clusters): every true plasmid, plus a virtual
    "CHROMOSOME" column for chromosome bp a bin wrongly claims.

    Deliberately excluded: chromosome bp that no bin ever claims. That is
    the correct, desired outcome for the vast majority of a bacterial
    genome, not a clustering decision -- including it would swamp the
    contingency table with an enormous, uninteresting "true negative" mass
    and trivially inflate agreement, since neither NMI nor VI is being asked
    to cluster the whole genome, only the fraction of it a tool actually made
    a plasmid-related decision about (matches score_bins.py's precision/
    recall/f1 above, which are also computed only over bins/plasmids, never
    over unclaimed chromosome).

    Returns (nmi, vi), or (None, None) if the table is empty (no true
    plasmid bp and no wrongly-claimed chromosome bp at all).
    """
    row_weights = defaultdict(lambda: defaultdict(int))  # row -> {col: bp}
    claimed_by_plasmid = defaultdict(int)
    for (bin_id, plasmid), bp in overlaps.items():
        if bp > 0:
            row_weights[bin_id][plasmid] += bp
            claimed_by_plasmid[plasmid] += bp
    for bin_id, bp in chromosome_bp.items():
        if bp > 0:
            row_weights[bin_id]["CHROMOSOME"] += bp
    for plasmid, length in plasmids.items():
        missed = length - claimed_by_plasmid.get(plasmid, 0)
        if missed > 0:
            row_weights["__unassigned__"][plasmid] += missed

    total = sum(sum(cols.values()) for cols in row_weights.values())
    if total <= 0:
        return None, None

    row_totals = {row: sum(cols.values()) for row, cols in row_weights.items()}
    col_totals = defaultdict(int)
    for cols in row_weights.values():
        for col, bp in cols.items():
            col_totals[col] += bp

    h_row = bp_entropy(row_totals)
    h_col = bp_entropy(dict(col_totals))
    mutual_information = 0.0
    for row, cols in row_weights.items():
        for col, bp in cols.items():
            if bp <= 0:
                continue
            p_joint = bp / total
            p_row = row_totals[row] / total
            p_col = col_totals[col] / total
            mutual_information += p_joint * math.log(p_joint / (p_row * p_col))

    # Normalization convention: arithmetic mean of the two entropies (the
    # same convention scikit-learn's normalized_mutual_info_score defaults
    # to), so a reader can cross-check this against a familiar reference
    # implementation. If both sides are a single point mass (H=0 for both --
    # one bin, one plasmid, no chromosome contamination, nothing missed),
    # agreement is perfect by construction. If only one side has zero
    # entropy, no information could possibly be shared with the other side's
    # real variability, so NMI is 0 by convention (matches scikit-learn).
    if h_row == 0.0 and h_col == 0.0:
        nmi = 1.0
    elif h_row == 0.0 or h_col == 0.0:
        nmi = 0.0
    else:
        nmi = 2 * mutual_information / (h_row + h_col)
    vi = h_row + h_col - 2 * mutual_information
    return nmi, vi


def adjusted_rand(overlaps, plasmids, chromosome_bp):
    """Base-pair-weighted Adjusted Rand Index over the same contingency table
    clustering_agreement() uses (bins + unassigned plasmid bp as rows; truth
    plasmids + wrongly claimed chromosome as columns). Each base is an item, so
    pair counts are C(n, 2) of base counts. None when undefined (fewer than two
    bases, or a degenerate table where expected == maximum)."""
    rows = defaultdict(lambda: defaultdict(int))
    claimed = defaultdict(int)
    for (bin_id, plasmid), bp in overlaps.items():
        if bp > 0:
            rows[bin_id][plasmid] += bp
            claimed[plasmid] += bp
    for bin_id, bp in chromosome_bp.items():
        if bp > 0:
            rows[bin_id]["CHROMOSOME"] += bp
    for plasmid, length in plasmids.items():
        if length - claimed.get(plasmid, 0) > 0:
            rows["__unassigned__"][plasmid] += length - claimed.get(plasmid, 0)

    def pairs(n):
        return n * (n - 1) / 2

    total = sum(sum(c.values()) for c in rows.values())
    if total < 2:
        return None
    col_totals = defaultdict(int)
    for cols in rows.values():
        for col, bp in cols.items():
            col_totals[col] += bp
    index = sum(pairs(bp) for cols in rows.values() for bp in cols.values())
    row_sum = sum(pairs(sum(cols.values())) for cols in rows.values())
    col_sum = sum(pairs(bp) for bp in col_totals.values())
    expected = row_sum * col_sum / pairs(total)
    maximum = (row_sum + col_sum) / 2
    if maximum == expected:
        return None
    return (index - expected) / (maximum - expected)


def read_assembly_coverage(path, plasmids):
    """sequence_id -> bases of the plasmid covered by the assembly's plasmid contigs."""
    covered = {}
    if not path:
        return covered
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("sequence_id") in plasmids:
                covered[row["sequence_id"]] = min(plasmids[row["sequence_id"]], int(row["assembly_covered_bp"]))
    return covered


OUTCOME_FIELDS = ["true_plasmid", "length", "best_bin", "best_bin_recall", "best_bin_precision",
                  "bins_holding_share", "merged_with", "contamination_fraction", "outcome"]
OUTCOMES = ("perfect", "fragmented", "merged", "fragmented_and_merged", "partial", "missed")


def plasmid_outcomes(overlaps, plasmids, total_mapped, chromosome_bp, perfect=0.95, fragment_share=0.20,
                     missed_recall=0.50):
    """One outcome per truth plasmid (scoring specification, WP1).

    best bin   the bin holding most of the plasmid's bases
    missed     best-bin recall < missed_recall (or no bin at all)
    fragmented another bin also holds >= fragment_share of the plasmid
    merged     the best bin also holds >= fragment_share of another truth plasmid
    perfect    best-bin recall and precision >= perfect, neither fragmented nor merged
    partial    anything else
    contamination_fraction = chromosome bases / all mapped bases of the best bin.
    """
    by_plasmid, by_bin = {}, {}
    for (bin_id, plasmid), bp in overlaps.items():
        by_plasmid.setdefault(plasmid, {})[bin_id] = bp
        by_bin.setdefault(bin_id, {})[plasmid] = bp
    rows = []
    for plasmid in sorted(plasmids):
        length = plasmids[plasmid]
        bins = by_plasmid.get(plasmid, {})
        if not bins:
            rows.append({"true_plasmid": plasmid, "length": length, "best_bin": "", "best_bin_recall": "0.0000",
                         "best_bin_precision": "", "bins_holding_share": 0, "merged_with": "",
                         "contamination_fraction": "", "outcome": "missed"})
            continue
        best = max(bins, key=lambda b: (bins[b], b))
        recall = safe_div(bins[best], length)
        precision = safe_div(bins[best], total_mapped.get(best, 0))
        holding = sorted(b for b, bp in bins.items() if safe_div(bp, length) >= fragment_share)
        others = sorted(p for p, bp in by_bin.get(best, {}).items()
                        if p != plasmid and safe_div(bp, plasmids[p]) >= fragment_share)
        fragmented, merged = len(holding) > 1, bool(others)
        if recall < missed_recall:
            outcome = "missed"
        elif fragmented and merged:
            outcome = "fragmented_and_merged"
        elif fragmented:
            outcome = "fragmented"
        elif merged:
            outcome = "merged"
        elif recall >= perfect and precision >= perfect:
            outcome = "perfect"
        else:
            outcome = "partial"
        rows.append({"true_plasmid": plasmid, "length": length, "best_bin": best,
                     "best_bin_recall": f"{recall:.4f}", "best_bin_precision": f"{precision:.4f}",
                     "bins_holding_share": len(holding), "merged_with": ",".join(others),
                     "contamination_fraction": f"{safe_div(chromosome_bp.get(best, 0), total_mapped.get(best, 0)):.4f}",
                     "outcome": outcome})
    return rows


CPRR_FIELDS = ["true_plasmid", "length", "matched_bin", "coverage", "bin_share", "identity",
               "split", "identified", "coverage_ok", "share_ok", "not_split", "identity_ok",
               "correct_without_identity", "correct"]


def length_weighted_binning(overlaps, plasmids, total_mapped, all_bins):
    """Length-weighted binning precision/recall/F1 from an ungated Hungarian match."""
    matched = maximum_weight(dict(overlaps), sorted(all_bins), sorted(plasmids))
    correct_bp = sum(bp for _, _, bp in matched)
    truth_bp = sum(plasmids.values())
    mapped_bp = sum(total_mapped.values())
    precision = safe_div(correct_bp, mapped_bp)
    recall = safe_div(correct_bp, truth_bp)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"matched": matched, "precision": precision, "recall": recall, "f1": f1}


def correct_reconstruction(matched, overlaps, plasmids, total_mapped, identity_counts, fragments,
                           min_coverage, min_share, min_identity):
    """Per truth plasmid: does it meet every pre-specified CPRR criterion?"""
    by_plasmid = {plasmid: (bin_id, bp) for bin_id, plasmid, bp in matched}
    rows = []
    for plasmid in sorted(plasmids):
        length = plasmids[plasmid]
        bin_id, bp = by_plasmid.get(plasmid, ("", 0))
        coverage = safe_div(bp, length)
        share = safe_div(bp, total_mapped.get(bin_id, 0)) if bin_id else 0.0
        matches, block = identity_counts.get((bin_id, plasmid), (0, 0)) if bin_id else (0, 0)
        identity = safe_div(matches, block)
        split = len(fragments.get(plasmid, set()) - {bin_id}) > 0
        checks = {"identified": bool(bin_id), "coverage_ok": coverage >= min_coverage,
                  "share_ok": share >= min_share, "not_split": not split,
                  "identity_ok": identity >= min_identity}
        structural = all(checks[key] for key in ("identified", "coverage_ok", "share_ok", "not_split"))
        rows.append({
            "true_plasmid": plasmid, "length": length, "matched_bin": bin_id,
            "coverage": f"{coverage:.4f}", "bin_share": f"{share:.4f}", "identity": f"{identity:.4f}",
            "split": "yes" if split else "no",
            **{key: "yes" if value else "no" for key, value in checks.items()},
            "correct_without_identity": "yes" if structural else "no",
            "correct": "yes" if structural and checks["identity_ok"] else "no",
            # Unrounded values for the threshold sweep; not written to the TSV.
            "_coverage": coverage, "_share": share, "_identity_ok": checks["identity_ok"],
        })
    return rows


def cprr_sweep(rows, thresholds=CPRR_SWEEP_THRESHOLDS):
    """Correct-plasmid counts at each sweep threshold: (with identity, without identity).

    At threshold t a plasmid passes when it is identified, not split, and both its
    coverage and its bin share are >= t; the identity criterion is unchanged.
    """
    with_identity, without_identity = [], []
    for t in thresholds:
        passing = [r for r in rows if r["identified"] == "yes" and r["not_split"] == "yes"
                   and r["_coverage"] >= t and r["_share"] >= t]
        without_identity.append(len(passing))
        with_identity.append(sum(1 for r in passing if r["_identity_ok"]))
    return with_identity, without_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("truth", "paf", "bins", "out", "summary"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--threshold", type=float, default=.9, help="minimum truth-plasmid completeness")
    parser.add_argument("--min-bin-purity", type=float, default=.9, help="minimum plasmid bp / mapped bin bp")
    parser.add_argument("--split-threshold", type=float, default=.1)
    parser.add_argument("--ambiguity-paf", help="Optional all-mapping PAF for repeat-associated bin ambiguity.")
    parser.add_argument("--cprr-out", help="Per-truth-plasmid correct-reconstruction table (CPRR).")
    parser.add_argument("--outcomes-out", help="Per-truth-plasmid outcome table (perfect/fragmented/merged/missed).")
    parser.add_argument("--perfect-threshold", type=float, default=float(os.environ.get("PERFECT_THRESHOLD", 0.95)))
    parser.add_argument("--fragment-share", type=float, default=float(os.environ.get("FRAGMENT_SHARE", 0.20)))
    parser.add_argument("--missed-recall", type=float, default=float(os.environ.get("MISSED_RECALL", 0.50)))
    parser.add_argument("--assembly-coverage", help="contig_classification.py coverage table: per truth plasmid, bases "
                                                    "the assembly covers (assembly-aware binning recall).")
    parser.add_argument("--cprr-min-coverage", type=float, default=0.95,
                        help="CPRR: minimum fraction of the plasmid covered by its matched bin.")
    parser.add_argument("--cprr-min-share", type=float, default=0.95,
                        help="CPRR: minimum fraction of the matched bin's aligned bases that belong to this plasmid.")
    parser.add_argument("--cprr-min-identity", type=float, default=0.99,
                        help="CPRR: minimum alignment identity of the matched bin on the plasmid.")
    parser.add_argument("--min-alignment-length", type=int, default=1,
                        help="Minimum PAF block length retained for bin scoring (default: 1).")
    parser.add_argument("--min-alignment-identity", type=float, default=0.0,
                        help="Minimum PAF matches/block-length retained for bin scoring (default: 0).")
    parser.add_argument("--min-alignment-mapq", type=int, default=0,
                        help="Minimum PAF mapping quality retained for bin scoring (default: 0).")
    parser.add_argument("--min-alignment-query-coverage", type=float, default=0.0,
                        help="Minimum fraction of a predicted record covered by an individual PAF alignment (default: 0).")
    args = parser.parse_args()
    if not 0 < args.threshold <= 1 or not 0 < args.min_bin_purity <= 1:
        raise SystemExit("ERROR: matching thresholds must be in (0, 1].")
    if (args.min_alignment_length < 1 or not 0 <= args.min_alignment_identity <= 1
            or args.min_alignment_mapq < 0 or not 0 <= args.min_alignment_query_coverage <= 1):
        raise SystemExit("ERROR: alignment thresholds must be min-length >= 1, "
                          "identity/query coverage in [0, 1], and MAPQ >= 0")
    plasmids, chromosomes = read_truth(args.truth)
    membership = read_bins(args.bins)
    plasmid_intervals, chromosome_intervals = defaultdict(list), defaultdict(list)
    identity_counts = defaultdict(lambda: [0, 0])  # (bin, plasmid) -> [matches, block length]
    # Applies the same alignment-quality gate as score_plasmids.py (base-level
    # scoring), so a short, low-identity, or low-MAPQ placement that the base
    # score discards cannot still count toward bin completeness/purity.
    with open(args.paf, encoding="utf-8") as handle:
        for raw in handle:
            fields = raw.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[0] not in membership: continue
            try:
                qlen, qstart, qend = int(fields[1]), int(fields[2]), int(fields[3])
                start, stop = int(fields[7]), int(fields[8])
                matches, block_length, mapq = int(fields[9]), int(fields[10]), int(fields[11])
            except ValueError: continue
            identity = matches / block_length if block_length else 0.0
            query_coverage = abs(qend - qstart) / qlen if qlen else 0.0
            if (block_length < args.min_alignment_length or identity < args.min_alignment_identity
                    or mapq < args.min_alignment_mapq or query_coverage < args.min_alignment_query_coverage):
                continue
            target, bin_id = fields[5], membership[fields[0]]
            if target in plasmids:
                identity_counts[(bin_id, target)][0] += matches
                identity_counts[(bin_id, target)][1] += block_length
            if target in plasmids: plasmid_intervals[(bin_id, target)].append((max(0, start), min(plasmids[target], stop)))
            elif target in chromosomes: chromosome_intervals[bin_id].append((max(0, start), min(chromosomes[target], stop)))
    overlaps = {key: merge(value) for key, value in plasmid_intervals.items()}
    plasmid_bp = defaultdict(int)
    for (bin_id, _), bp in overlaps.items(): plasmid_bp[bin_id] += bp
    chromosome_bp = {bin_id: merge(value) for bin_id, value in chromosome_intervals.items()}
    all_bins = set(membership.values())
    ambiguity_bp = bin_ambiguity(args.ambiguity_paf, membership, plasmids, chromosomes,
                                 args.min_alignment_length, args.min_alignment_identity,
                                 args.min_alignment_mapq, args.min_alignment_query_coverage)
    total_mapped = {bin_id: plasmid_bp[bin_id] + chromosome_bp.get(bin_id, 0) for bin_id in all_bins}
    purity = {bin_id: plasmid_bp[bin_id] / total_mapped[bin_id] if total_mapped[bin_id] else 0.0 for bin_id in all_bins}
    edges = {(bin_id, plasmid): bp for (bin_id, plasmid), bp in overlaps.items() if safe_div(bp, plasmids[plasmid]) >= args.threshold and purity[bin_id] >= args.min_bin_purity}
    matched = maximum_weight(edges, sorted(all_bins), sorted(plasmids))
    used_bins, used_plasmids = {item[0] for item in matched}, {item[1] for item in matched}
    fragments, merged = defaultdict(set), defaultdict(set)
    for (bin_id, plasmid), bp in overlaps.items():
        if safe_div(bp, plasmids[plasmid]) >= args.split_threshold:
            fragments[plasmid].add(bin_id); merged[bin_id].add(plasmid)
    splits = sum(len(value) - 1 for value in fragments.values() if len(value) > 1)
    merges = sum(len(value) - 1 for value in merged.values() if len(value) > 1)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["bin_id", "true_plasmid", "aligned_bp", "truth_completeness", "bin_purity", "chromosome_aligned_bp", "repeat_ambiguity_bp", "contamination_fraction", "match_status"])
        for bin_id, plasmid, bp in matched:
            writer.writerow([bin_id, plasmid, bp, f"{safe_div(bp, plasmids[plasmid]):.4f}", f"{purity[bin_id]:.4f}", chromosome_bp.get(bin_id, 0), ambiguity_bp.get(bin_id, 0), f"{1 - purity[bin_id]:.4f}", "matched"])
        for bin_id in sorted(all_bins - used_bins): writer.writerow([bin_id, "", 0, "", f"{purity[bin_id]:.4f}", chromosome_bp.get(bin_id, 0), ambiguity_bp.get(bin_id, 0), f"{1 - purity[bin_id]:.4f}", "unmatched_bin"])
        for plasmid in sorted(set(plasmids) - used_plasmids): writer.writerow(["", plasmid, 0, "", "", "", "", "", "missed_plasmid"])
    precision = len(matched) / len(all_bins) if all_bins else 0.0; recall = len(matched) / len(plasmids) if plasmids else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total_bp, chromosome_total = sum(total_mapped.values()), sum(chromosome_bp.values())
    # Supplementary to bin_f1/split_events/merge_events/contamination_fraction
    # above -- never a replacement for them. "" (not 0) when the contingency
    # table is empty (no true plasmid bp and nothing wrongly claimed as
    # plasmid), matching this file's existing availability-aware convention.
    nmi, vi = clustering_agreement(overlaps, plasmids, chromosome_bp, all_bins)
    lw = length_weighted_binning(overlaps, plasmids, total_mapped, all_bins)
    ari = adjusted_rand(overlaps, plasmids, chromosome_bp)
    # Assembly-aware recall: the denominator is the plasmid length the assembly
    # actually covers, so a tool is not blamed for bases no contig contains.
    assembly_covered = read_assembly_coverage(args.assembly_coverage, plasmids)
    lw_recall_assembly = lw_f1_assembly = None
    if assembly_covered:
        reachable = sum(assembly_covered.values())
        correct_bp = sum(bp for _, _, bp in lw["matched"])
        lw_recall_assembly = min(1.0, safe_div(correct_bp, reachable)) if reachable else None
        if lw_recall_assembly is not None:
            p = lw["precision"]
            lw_f1_assembly = 2 * p * lw_recall_assembly / (p + lw_recall_assembly) if p + lw_recall_assembly else 0.0
    cprr_rows = correct_reconstruction(lw["matched"], overlaps, plasmids, total_mapped, identity_counts,
                                       fragments, args.cprr_min_coverage, args.cprr_min_share,
                                       args.cprr_min_identity)
    if args.cprr_out:
        with open(args.cprr_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(CPRR_FIELDS)
            for row in cprr_rows:
                writer.writerow([row[field] for field in CPRR_FIELDS])
    outcomes = plasmid_outcomes(overlaps, plasmids, total_mapped, chromosome_bp, args.perfect_threshold,
                                args.fragment_share, args.missed_recall)
    if args.outcomes_out:
        with open(args.outcomes_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTCOME_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(outcomes)
    outcome_counts = {name: sum(row["outcome"] == name for row in outcomes) for name in OUTCOMES}
    cprr_total = len(cprr_rows)
    cprr_correct = sum(row["correct"] == "yes" for row in cprr_rows)
    cprr_correct_no_identity = sum(row["correct_without_identity"] == "yes" for row in cprr_rows)
    sweep_with, sweep_without = cprr_sweep(cprr_rows)
    with open(args.summary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events", "contaminated_bins", "chromosome_aligned_bp", "repeat_ambiguity_bp", "bin_total_mapped_bp", "contamination_fraction", "nmi", "variation_of_information",
                         "lw_bin_precision", "lw_bin_recall", "lw_bin_f1",
                         "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity",
                         "bin_ari", "lw_bin_recall_assembly_aware", "lw_bin_f1_assembly_aware"]
                        + [f"outcome_{name}" for name in OUTCOMES]
                        + ["cprr_sweep_correct", "cprr_sweep_correct_without_identity"])
        writer.writerow([f"{precision:.4f}", f"{recall:.4f}", f"{f1:.4f}", len(matched), len(all_bins - used_bins), len(set(plasmids) - used_plasmids), splits, merges, sum(chromosome_bp.get(bin_id, 0) > 0 for bin_id in all_bins), chromosome_total, sum(ambiguity_bp.values()), total_bp, f"{chromosome_total / total_bp if total_bp else 0.0:.4f}", f"{nmi:.4f}" if nmi is not None else "", f"{vi:.4f}" if vi is not None else "",
                         f"{lw['precision']:.4f}", f"{lw['recall']:.4f}", f"{lw['f1']:.4f}",
                         cprr_total, cprr_correct, cprr_correct_no_identity,
                         f"{ari:.4f}" if ari is not None else "",
                         f"{lw_recall_assembly:.4f}" if lw_recall_assembly is not None else "",
                         f"{lw_f1_assembly:.4f}" if lw_f1_assembly is not None else ""]
                        + [outcome_counts[name] for name in OUTCOMES]
                        # Comma-separated counts, one per CPRR_SWEEP_THRESHOLDS value (0.80..0.99).
                        + [",".join(map(str, sweep_with)), ",".join(map(str, sweep_without))])
    print(f"bin precision={precision:.4f} bin recall={recall:.4f} bin f1={f1:.4f} matches={len(matched)} "
          f"lw_bin_f1={lw['f1']:.4f} cprr={cprr_correct}/{cprr_total}")


if __name__ == "__main__": main()
