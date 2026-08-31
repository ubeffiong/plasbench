#!/usr/bin/env python3
"""
score_plasmids.py  --  base-level scoring of plasmid-reconstruction predictions.

Idea (one metric that works for every tool):
  * The COMPLETE (long-read) assembly is ground truth. Every base of every
    reference sequence is labelled PLASMID or CHROMOSOME (from the NCBI
    sequence report -> truth.tsv).
  * A tool under test emits a FASTA of the sequence it *thinks* is plasmid.
  * We map that predicted-plasmid FASTA back onto the reference with minimap2
    (PAF). Every reference base covered by a predicted-plasmid alignment is a
    base the tool "claimed" as plasmid.
  * Confusion matrix over reference bases (positive class = PLASMID):
        TP = reference PLASMID bases covered by prediction
        FP = reference CHROMOSOME bases covered by prediction
        FN = reference PLASMID bases NOT covered by prediction
    precision = TP / (TP + FP)
    recall    = TP / (TP + FN)   (a.k.a. completeness)
    f1        = harmonic mean

This reduces classification tools (Platon, mob_recon) and re-assembly tools
(plasmidSPAdes, gplas) to the SAME comparable metric, because everything is
projected onto the reference.

Predicted-plasmid bases that do not map to the reference at all are reported
separately as `unmapped_pred_bp` (likely mis-assembly / contamination) and are
NOT counted as FP, to keep the core metric defensible.

Inputs
------
--truth   TSV with header: sequence_id  molecule_type  length
          molecule_type must be PLASMID or CHROMOSOME (case-insensitive).
--paf     minimap2 PAF: predicted-plasmid FASTA (query) vs reference (target).
          If the tool predicted nothing, pass an empty file (0 bytes).
--sample  sample id string (for the output row)
--tool    tool name string (for the output row)
--pred-fasta  predicted-plasmid FASTA, used to measure unaligned query bases.
--out     output TSV path (one row appended; header written if new)

Only the Python standard library is used. No third-party dependencies.
"""

import argparse
import os
import sys
from collections import defaultdict


def read_truth(path):
    """Return dict sequence_id -> (molecule_type, length) and total plasmid bp."""
    truth = {}
    total_plasmid = 0
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        # Be tolerant of column order as long as names are present.
        try:
            i_id = header.index("sequence_id")
            i_type = header.index("molecule_type")
            i_len = header.index("length")
        except ValueError:
            sys.exit(
                "ERROR: truth file must have a header row with columns "
                "'sequence_id', 'molecule_type', 'length'."
            )
        for line in fh:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            seq_id = f[i_id]
            mol = f[i_type].strip().upper()
            length = int(f[i_len])
            if mol not in ("PLASMID", "CHROMOSOME"):
                sys.exit(f"ERROR: molecule_type must be PLASMID/CHROMOSOME, got '{mol}'")
            truth[seq_id] = (mol, length)
            if mol == "PLASMID":
                total_plasmid += length
    return truth, total_plasmid


def read_fasta_lengths(path):
    """Return FASTA record id -> length, rejecting ambiguous duplicate ids."""
    lengths = {}
    name = None
    length = 0
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    if name in lengths:
                        raise ValueError(f"duplicate FASTA record id: {name}")
                    lengths[name] = length
                fields = line[1:].split()
                if not fields:
                    raise ValueError("FASTA header without a record id")
                name = fields[0]
                length = 0
            elif name is None:
                raise ValueError("FASTA sequence encountered before a header")
            else:
                length += len(line)
    if name is not None:
        if name in lengths:
            raise ValueError(f"duplicate FASTA record id: {name}")
        lengths[name] = length
    return lengths


def parse_paf_intervals(path, truth, pred_lengths):
    """
    Parse PAF, keep one row per (query, target alignment), and collect covered
    intervals ON THE TARGET (reference) as 0-based half-open [start, end).

    Returns:
      covered: dict target_id -> list of (start, end)
      unmapped_pred_bp: predicted query bases not aligned to a truth reference
    """
    covered = defaultdict(list)
    query_covered = defaultdict(list)

    if os.path.getsize(path) == 0:
        return covered, sum(pred_lengths.values())

    with open(path) as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 12:
                raise ValueError(
                    f"PAF line {line_number} has {len(f)} columns; expected at least 12"
                )
            # PAF mandatory columns (0-based indices):
            # 0 qname 1 qlen 2 qstart 3 qend 4 strand
            # 5 tname 6 tlen 7 tstart 8 tend 9 matches 10 blocklen 11 mapq
            qname = f[0]
            try:
                qlen = int(f[1])
                qstart = int(f[2])
                qend = int(f[3])
                tname = f[5]
                tlen = int(f[6])
                tstart = int(f[7])
                tend = int(f[8])
            except ValueError as exc:
                raise ValueError(f"PAF line {line_number} has invalid integer coordinates") from exc
            if qname not in pred_lengths:
                raise ValueError(f"PAF query '{qname}' is absent from --pred-fasta")
            if qlen != pred_lengths[qname]:
                raise ValueError(
                    f"PAF query length for '{qname}' ({qlen}) disagrees with FASTA "
                    f"({pred_lengths[qname]})"
                )
            # Only keep alignments to sequences we actually have truth for.
            if tname in truth:
                truth_length = truth[tname][1]
                if tlen != truth_length:
                    raise ValueError(
                        f"PAF target length for '{tname}' ({tlen}) disagrees with truth "
                        f"({truth_length})"
                    )
                if tend < tstart:
                    tstart, tend = tend, tstart
                tstart = max(0, min(tstart, truth_length))
                tend = max(0, min(tend, truth_length))
                covered[tname].append((tstart, tend))
                if qend < qstart:
                    qstart, qend = qend, qstart
                qstart = max(0, min(qstart, qlen))
                qend = max(0, min(qend, qlen))
                query_covered[qname].append((qstart, qend))

    unmapped_pred_bp = 0
    for qname, length in pred_lengths.items():
        _, mapped_bp = merge_intervals(query_covered.get(qname, []))
        unmapped_pred_bp += max(0, length - min(mapped_bp, length))
    return covered, unmapped_pred_bp


def merge_intervals(intervals):
    """Merge overlapping [start, end) intervals; return list + total length."""
    if not intervals:
        return [], 0
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    total = sum(e - s for s, e in merged)
    return merged, total


def score(truth, total_plasmid, covered):
    """Compute TP, FP, FN over reference bases."""
    tp = 0  # plasmid ref bases covered by prediction
    fp = 0  # chromosome ref bases covered by prediction
    for seq_id, (mol, length) in truth.items():
        _, cov_bp = merge_intervals(covered.get(seq_id, []))
        # Guard against over-count if alignments run slightly past tlen.
        cov_bp = min(cov_bp, length)
        if mol == "PLASMID":
            tp += cov_bp
        else:
            fp += cov_bp
    fn = total_plasmid - tp
    if fn < 0:
        fn = 0
    return tp, fp, fn


def safe_div(a, b):
    return a / b if b else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--pred-fasta", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plasmid-recovery-threshold", type=float, default=0.90,
                    help="Fraction of a true plasmid that counts as recovered (default: 0.90).")
    args = ap.parse_args()

    truth, total_plasmid = read_truth(args.truth)
    try:
        pred_lengths = read_fasta_lengths(args.pred_fasta)
        covered, unmapped_pred_bp = parse_paf_intervals(args.paf, truth, pred_lengths)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    tp, fp, fn = score(truth, total_plasmid, covered)

    if not 0 < args.plasmid_recovery_threshold <= 1:
        raise SystemExit("ERROR: --plasmid-recovery-threshold must be in (0, 1].")
    true_plasmids = [seq_id for seq_id, (mol, _) in truth.items() if mol == "PLASMID"]
    recovered_plasmids = 0
    for seq_id in true_plasmids:
        _, covered_bp = merge_intervals(covered.get(seq_id, []))
        if covered_bp / truth[seq_id][1] >= args.plasmid_recovery_threshold:
            recovered_plasmids += 1
    predicted_records = len(pred_lengths)

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)          # completeness
    f1 = safe_div(2 * precision * recall, precision + recall)

    header = [
        "sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
        "unmapped_pred_bp", "true_plasmid_count", "recovered_plasmid_count",
        "plasmid_recall", "predicted_record_count", "precision", "recall", "f1",
    ]
    row = [
        args.sample, args.tool, total_plasmid, tp, fp, fn,
        unmapped_pred_bp, len(true_plasmids), recovered_plasmids,
        f"{safe_div(recovered_plasmids, len(true_plasmids)):.4f}", predicted_records,
        f"{precision:.4f}", f"{recall:.4f}", f"{f1:.4f}",
    ]

    new_file = not os.path.exists(args.out) or os.path.getsize(args.out) == 0
    with open(args.out, "a") as fh:
        if new_file:
            fh.write("\t".join(header) + "\n")
        fh.write("\t".join(str(x) for x in row) + "\n")

    # Also echo a human-readable line to stderr for the logs.
    sys.stderr.write(
        f"[score] {args.sample} / {args.tool}: "
        f"precision={precision:.3f} recall={recall:.3f} f1={f1:.3f} "
        f"(TP={tp} FP={fp} FN={fn})\n"
    )


if __name__ == "__main__":
    main()
