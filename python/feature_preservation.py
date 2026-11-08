#!/usr/bin/env python3
"""Biological feature preservation and gene-order conservation (NGOC) for one (sample, tool).

Two reconstructions can have the same coverage and identity yet differ in whether they keep
the genes and features that matter, and in whether those features are still in the right
order. This script measures both by projecting each TRUTH feature through the same
alignments the scorer uses, so the predicted sequence never needs its own annotation (no
extra caller, no annotation disagreement to explain away).

Feature preservation, per feature kind (replicon, mobility, amr, is_element, gene, ...):
    full length  covered fraction >= --min-feature-coverage (default 0.95) by retained
                 alignment blocks on that truth plasmid
    truncated    covered, but below that threshold
    missed       not covered at all
  full_length_rate = full / expected. mean_covered_fraction is the "functional element
  completeness". Presence alone is not recovery: a truncated element is reported as
  truncated, never as recovered.

NGOC (normalised gene order conservation): the share of adjacent feature pairs in the
reference (per truth plasmid, in coordinate order; the last-first pair too when the plasmid
is circular) that are still adjacent in the reconstruction:
    both features project onto the same predicted record,
    on the same orientation, in the order that orientation implies, and
    no other projected feature sits between them.
  Bidirectional: a record reconstructed on the opposite strand conserves the same order.
  A feature that does not project (missed, or covered below --ngoc-min-coverage, default
  0.5) breaks its pairs, so the denominator is every reference pair. With a gene table the
  value is gene-order conservation; with only landmark features (replicon, AMR, IS) it is
  landmark-order conservation, and `ngoc_features` says how many features it rests on.

Inputs: feature tables with sequence_id, start, end, and either `feature_type` and `label`
(annotate_reference.py's truth_features.tsv) or `category` and `gene` (a protein table). An
optional `strand` column is used when present. Only features on truth PLASMIDS are scored.
Blank means not evaluated, never zero. Descriptive only; never changes scores.tsv.
Standard library only.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

KIND_ALIASES = {"mob": "mobility", "is": "is_element", "isescan": "is_element"}
SUMMARY_FIELDS = ("sample", "tool", "analysis_track", "feature_kind", "n_expected", "n_full_length",
                  "n_truncated", "n_missed", "full_length_rate", "mean_covered_fraction")
NGOC_FIELDS = ("sample", "tool", "analysis_track", "ngoc_features", "n_pairs", "n_conserved", "ngoc")


def read_truth(path):
    plasmids = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["molecule_type"].upper() == "PLASMID":
                plasmids[row["sequence_id"]] = int(row["length"])
    return plasmids


def read_features(paths, plasmids):
    features, seen = [], set()
    for path in paths:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                seq = row.get("sequence_id")
                if seq not in plasmids:
                    continue
                try:
                    start, end = int(row["start"]), int(row["end"])
                except (KeyError, ValueError):
                    continue
                if end < start:
                    start, end = end, start
                if end <= start:
                    continue
                kind = (row.get("feature_type") or row.get("category") or "gene").strip().lower()
                kind = KIND_ALIASES.get(kind, kind)
                label = (row.get("label") or row.get("gene") or row.get("feature_id") or "").strip()
                key = (seq, start, end, kind)
                if key in seen:           # the same landmark listed by two callers
                    continue
                seen.add(key)
                features.append({"seq": seq, "start": start, "end": end, "kind": kind, "label": label})
    features.sort(key=lambda f: (f["seq"], f["start"], f["end"]))
    return features


def read_circular(path):
    if not path or not os.path.isfile(path):
        return set()
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sequence_id"] for row in csv.DictReader(handle, delimiter="\t") if row.get("sequence_id")}


def read_blocks(paf, plasmids, min_length, min_identity, min_mapq, min_qcov):
    blocks = defaultdict(list)
    with open(paf, encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 12 or "tp:A:S" in f[12:]:
                continue
            try:
                qname, qlen, qs, qe, strand = f[0], int(f[1]), int(f[2]), int(f[3]), f[4]
                tname, ts, te = f[5], int(f[7]), int(f[8])
                matches, block, mapq = int(f[9]), int(f[10]), int(f[11])
            except ValueError:
                continue
            if tname not in plasmids or block < min_length or mapq < min_mapq:
                continue
            if (matches / block if block else 0.0) < min_identity:
                continue
            if (abs(qe - qs) / qlen if qlen else 0.0) < min_qcov:
                continue
            ts, te = min(ts, te), max(ts, te)
            qs, qe = min(qs, qe), max(qs, qe)
            blocks[tname].append({"q": qname, "qs": qs, "qe": qe, "strand": strand, "ts": ts, "te": te})
    return blocks


def covered_fraction(feature, blocks):
    spans = sorted((max(b["ts"], feature["start"]), min(b["te"], feature["end"]))
                   for b in blocks if b["te"] > feature["start"] and b["ts"] < feature["end"])
    total, cursor = 0, feature["start"]
    for start, end in spans:
        start = max(start, cursor)
        if end > start:
            total += end - start
            cursor = end
    return total / (feature["end"] - feature["start"])


def project(feature, blocks, min_cov):
    """(record, position, orientation) of the feature on the prediction, or None."""
    length = feature["end"] - feature["start"]
    best, best_overlap = None, 0
    for b in blocks:
        overlap = min(b["te"], feature["end"]) - max(b["ts"], feature["start"])
        if overlap > best_overlap:
            best, best_overlap = b, overlap
    if best is None or best_overlap / length < min_cov:
        return None
    mid = min(max((feature["start"] + feature["end"]) / 2, best["ts"]), best["te"])
    span_t = max(best["te"] - best["ts"], 1)
    span_q = best["qe"] - best["qs"]
    frac = (mid - best["ts"]) / span_t
    position = best["qs"] + frac * span_q if best["strand"] == "+" else best["qe"] - frac * span_q
    return best["q"], position, best["strand"]


def ngoc(features, blocks_by_seq, circular, min_cov):
    projections = {}
    for index, feature in enumerate(features):
        projections[index] = project(feature, blocks_by_seq.get(feature["seq"], []), min_cov)
    by_record = defaultdict(list)
    for index, proj in projections.items():
        if proj:
            by_record[proj[0]].append((proj[1], index))
    for record in by_record:
        by_record[record].sort()
    rank = {index: (record, order) for record, items in by_record.items() for order, (_, index) in enumerate(items)}

    pairs = []
    per_seq = defaultdict(list)
    for index, feature in enumerate(features):
        per_seq[feature["seq"]].append(index)
    for seq, indexes in per_seq.items():
        if len(indexes) < 2:
            continue
        pairs.extend(zip(indexes, indexes[1:]))
        if seq in circular and len(indexes) > 2:
            pairs.append((indexes[-1], indexes[0]))
    conserved = 0
    for i, j in pairs:
        if not projections[i] or not projections[j]:
            continue
        (rec_i, _, strand_i), (rec_j, _, strand_j) = projections[i], projections[j]
        if rec_i != rec_j or strand_i != strand_j:
            continue
        order_i, order_j = rank[i][1], rank[j][1]
        size = len(by_record[rec_i])
        step = order_j - order_i
        # Reference order i -> j is "forward"; on a '-' record the prediction order reverses.
        expected = 1 if strand_i == "+" else -1
        adjacent = step == expected
        if not adjacent and size > 2:      # wrap-around of a circular record
            adjacent = (order_i == size - 1 and order_j == 0 and expected == 1) or \
                       (order_i == 0 and order_j == size - 1 and expected == -1)
        if adjacent:
            conserved += 1
    return len(pairs), conserved, sum(1 for p in projections.values() if p)


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
    ap.add_argument("--features", action="append", required=True, help="feature table; repeatable")
    ap.add_argument("--circular-plasmids", help="truth_circular.tsv; adds the last-first pair for those plasmids")
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--analysis-track", default="short_read")
    ap.add_argument("--out", required=True, help="append feature-preservation rows")
    ap.add_argument("--ngoc-out", help="append one NGOC row")
    ap.add_argument("--min-feature-coverage", type=float, default=0.95)
    ap.add_argument("--ngoc-min-coverage", type=float, default=0.5)
    ap.add_argument("--min-alignment-length", type=int, default=int(os.environ.get("MIN_ALIGNMENT_LENGTH", 200)))
    ap.add_argument("--min-alignment-identity", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_IDENTITY", 0.90)))
    ap.add_argument("--min-alignment-mapq", type=int, default=int(os.environ.get("MIN_ALIGNMENT_MAPQ", 20)))
    ap.add_argument("--min-alignment-query-coverage", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_QUERY_COVERAGE", 0.20)))
    args = ap.parse_args()

    plasmids = read_truth(args.truth)
    features = read_features([p for p in args.features if os.path.isfile(p)], plasmids)
    meta = {"sample": args.sample, "tool": args.tool, "analysis_track": args.analysis_track}
    if not features:
        sys.stderr.write("[feature_preservation] no features on truth plasmids; nothing evaluated\n")
        return 0
    blocks = read_blocks(args.paf, plasmids, args.min_alignment_length, args.min_alignment_identity,
                         args.min_alignment_mapq, args.min_alignment_query_coverage)
    tally = defaultdict(lambda: {"full": 0, "part": 0, "miss": 0, "cov": 0.0, "n": 0})
    for feature in features:
        fraction = covered_fraction(feature, blocks.get(feature["seq"], []))
        for kind in (feature["kind"], "all"):
            t = tally[kind]
            t["n"] += 1
            t["cov"] += fraction
            if fraction >= args.min_feature_coverage:
                t["full"] += 1
            elif fraction > 0:
                t["part"] += 1
            else:
                t["miss"] += 1
    rows = [{**meta, "feature_kind": kind, "n_expected": t["n"], "n_full_length": t["full"],
             "n_truncated": t["part"], "n_missed": t["miss"], "full_length_rate": t["full"] / t["n"],
             "mean_covered_fraction": t["cov"] / t["n"]} for kind, t in sorted(tally.items())]
    append_rows(args.out, SUMMARY_FIELDS, rows)
    if args.ngoc_out:
        pairs, conserved, projected = ngoc(features, blocks, read_circular(args.circular_plasmids),
                                           args.ngoc_min_coverage)
        append_rows(args.ngoc_out, NGOC_FIELDS, [{**meta, "ngoc_features": len(features), "n_pairs": pairs,
                                                  "n_conserved": conserved,
                                                  "ngoc": (conserved / pairs) if pairs else None}])
    return 0


if __name__ == "__main__":
    sys.exit(main())
