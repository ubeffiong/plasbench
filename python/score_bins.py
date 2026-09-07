#!/usr/bin/env python3
"""Globally optimal predicted-bin versus true-plasmid matching from PAF.

Eligible edges require truth-plasmid completeness and predicted-bin purity. The
one-to-one assignment maximises total aligned plasmid bases with a Hungarian
maximum-weight bipartite match; it is not a greedy overlap heuristic.
"""
import argparse
import csv
import math
from collections import defaultdict


def merge(intervals):
    total, end = 0, -1
    for start, stop in sorted((start, stop) for start, stop in intervals if stop > start):
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


def read_truth(path):
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    plasmids = {row["sequence_id"]: int(row["length"]) for row in rows if row["molecule_type"].upper() == "PLASMID"}
    chromosomes = {row["sequence_id"]: int(row["length"]) for row in rows if row["molecule_type"].upper() == "CHROMOSOME"}
    return plasmids, chromosomes


def read_bins(path):
    membership = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if not row.get("bin_id") or not row.get("sequence_id") or row["sequence_id"] in membership:
                raise ValueError("bins TSV requires unique sequence_id and nonempty bin_id")
            membership[row["sequence_id"]] = row["bin_id"]
    return membership


def overlap(left, right):
    """Return shared bases between two merged query-coordinate interval lists."""
    i = j = total = 0
    while i < len(left) and j < len(right):
        total += max(0, min(left[i][1], right[j][1]) - max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]: i += 1
        else: j += 1
    return total


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


def merge_intervals(intervals):
    ordered = sorted(intervals)
    merged = []
    for start, stop in ordered:
        if merged and start <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], stop)
        else: merged.append([start, stop])
    return merged


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


def maximum_weight(edges, bins_list, plasmids_list):
    """Return a maximum-weight one-to-one assignment using Hungarian O(n^3)."""
    n = max(len(bins_list), len(plasmids_list))
    if not n:
        return []
    high = max(edges.values(), default=0)
    cost = [[high] * n for _ in range(n)]
    for i, bin_id in enumerate(bins_list):
        for j, plasmid in enumerate(plasmids_list):
            cost[i][j] = high - edges.get((bin_id, plasmid), 0)
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0, minv, used = i, 0, [float("inf")] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, n + 1):
                if not used[j]:
                    current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minv[j]: minv[j], way[j] = current, j0
                    if minv[j] < delta: delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if not p[j0]: break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if not j0: break
    matched = []
    for j in range(1, n + 1):
        i = p[j]
        if i and i <= len(bins_list) and j <= len(plasmids_list):
            key = (bins_list[i - 1], plasmids_list[j - 1])
            if edges.get(key, 0) > 0: matched.append((key[0], key[1], edges[key]))
    return matched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("truth", "paf", "bins", "out", "summary"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--threshold", type=float, default=.9, help="minimum truth-plasmid completeness")
    parser.add_argument("--min-bin-purity", type=float, default=.9, help="minimum plasmid bp / mapped bin bp")
    parser.add_argument("--split-threshold", type=float, default=.1)
    parser.add_argument("--ambiguity-paf", help="Optional all-mapping PAF for repeat-associated bin ambiguity.")
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
    with open(args.summary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events", "contaminated_bins", "chromosome_aligned_bp", "repeat_ambiguity_bp", "bin_total_mapped_bp", "contamination_fraction", "nmi", "variation_of_information"])
        writer.writerow([f"{precision:.4f}", f"{recall:.4f}", f"{f1:.4f}", len(matched), len(all_bins - used_bins), len(set(plasmids) - used_plasmids), splits, merges, sum(chromosome_bp.get(bin_id, 0) > 0 for bin_id in all_bins), chromosome_total, sum(ambiguity_bp.values()), total_bp, f"{chromosome_total / total_bp if total_bp else 0.0:.4f}", f"{nmi:.4f}" if nmi is not None else "", f"{vi:.4f}" if vi is not None else ""])
    print(f"bin precision={precision:.4f} bin recall={recall:.4f} bin f1={f1:.4f} matches={len(matched)}")


if __name__ == "__main__": main()
