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
separately as `unmapped_pred_bp` (likely mis-assembly / contamination); bases
that DO map, but only to a reference sequence absent from --truth (e.g. a
contig the sequence report never classified), are reported separately again
as `off_truth_pred_bp`. Neither is counted as FP, to keep the core metric
defensible.

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


def parse_paf_intervals(path, truth, pred_lengths, min_length=1, min_identity=0.0, min_mapq=0,
                        min_query_coverage=0.0):
    """
    Parse PAF, keep one row per (query, target alignment), and collect covered
    intervals ON THE TARGET (reference) as 0-based half-open [start, end).

    Returns:
      covered: dict target_id -> list of (start, end)
      unmapped_pred_bp: predicted query bases with NO retained alignment at all
      off_truth_pred_bp: predicted query bases whose only retained alignment(s)
          land on a reference sequence absent from --truth. These are not
          scorable either way (not FP: never in truth; not TP/FN: not
          plasmid) and are reported separately from unmapped_pred_bp, since a
          record aligning outside the truth set is a different failure mode
          from one that does not align at all (e.g. a reference contig the
          sequence report never classified).
      mapped_pred_bp: predicted query bases aligned to a truth-labelled target
      covered_by_query: dict target_id -> list of (query_id, start, end), the
          same retained truth-labelled alignments as `covered` but additionally
          tagged with which predicted record each interval came from. Unused by
          the point-estimate score() below; it exists so a PR-curve sweep (see
          filter_covered_by_qname/sweep_thresholds) can recompute coverage for
          an arbitrary subset of records without re-parsing the PAF or
          duplicating this function's alignment-filtering logic.
    """
    covered = defaultdict(list)
    covered_by_query = defaultdict(list)
    query_covered = defaultdict(list)
    query_off_truth = defaultdict(list)

    counters = {"alignment_total": 0, "alignment_retained": 0, "filtered_alignment_count": 0}
    if os.path.getsize(path) == 0:
        return covered, sum(pred_lengths.values()), 0, 0, counters, covered_by_query

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
                matches = int(f[9])
                block_length = int(f[10])
                mapq = int(f[11])
            except ValueError as exc:
                raise ValueError(f"PAF line {line_number} has invalid integer coordinates") from exc
            if qname not in pred_lengths:
                raise ValueError(f"PAF query '{qname}' is absent from --pred-fasta")
            if qlen != pred_lengths[qname]:
                raise ValueError(
                    f"PAF query length for '{qname}' ({qlen}) disagrees with FASTA "
                    f"({pred_lengths[qname]})"
                )
            counters["alignment_total"] += 1
            identity = matches / block_length if block_length else 0.0
            query_coverage = abs(qend - qstart) / qlen if qlen else 0.0
            if (block_length < min_length or identity < min_identity or mapq < min_mapq
                    or query_coverage < min_query_coverage):
                counters["filtered_alignment_count"] += 1
                continue
            counters["alignment_retained"] += 1
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
                covered_by_query[tname].append((qname, tstart, tend))
                if qend < qstart:
                    qstart, qend = qend, qstart
                qstart = max(0, min(qstart, qlen))
                qend = max(0, min(qend, qlen))
                query_covered[qname].append((qstart, qend))
            else:
                if qend < qstart:
                    qstart, qend = qend, qstart
                qstart = max(0, min(qstart, qlen))
                qend = max(0, min(qend, qlen))
                query_off_truth[qname].append((qstart, qend))

    unmapped_pred_bp = mapped_pred_bp = off_truth_pred_bp = 0
    for qname, length in pred_lengths.items():
        _, mapped_bp = merge_intervals(query_covered.get(qname, []))
        mapped_bp = min(mapped_bp, length)
        mapped_pred_bp += mapped_bp
        _, any_bp = merge_intervals(query_covered.get(qname, []) + query_off_truth.get(qname, []))
        any_bp = min(any_bp, length)
        off_truth_pred_bp += max(0, any_bp - mapped_bp)
        unmapped_pred_bp += max(0, length - any_bp)
    return covered, unmapped_pred_bp, off_truth_pred_bp, mapped_pred_bp, counters, covered_by_query


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


def overlap_bp(left, right):
    """Return the number of bases shared by two merged interval lists."""
    i = j = total = 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        total += max(0, end - start)
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


def ambiguous_query_bp(path, truth, pred_lengths, min_length, min_identity, min_mapq, min_query_coverage):
    """Measure query bases with retained plasmid and chromosome alternatives.

    Primary-only mapping is retained for the core score so repetitive sequence
    cannot inflate claims across multiple replicons. This companion diagnostic
    uses secondary mappings only to expose bases with conflicting molecular
    assignments; it never changes TP, FP, or F1.
    """
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return 0
    by_query = defaultdict(lambda: defaultdict(list))
    with open(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 12:
                raise ValueError(f"ambiguity PAF line {line_number} has fewer than 12 columns")
            qname, target = fields[0], fields[5]
            try:
                qlen, qstart, qend = int(fields[1]), int(fields[2]), int(fields[3])
                matches, block_length, mapq = int(fields[9]), int(fields[10]), int(fields[11])
            except ValueError as exc:
                raise ValueError(f"ambiguity PAF line {line_number} has invalid coordinates") from exc
            if qname not in pred_lengths or qlen != pred_lengths[qname] or target not in truth:
                continue
            query_coverage = abs(qend - qstart) / qlen if qlen else 0.0
            if (block_length < min_length or (matches / block_length if block_length else 0.0) < min_identity
                    or mapq < min_mapq or query_coverage < min_query_coverage):
                continue
            qstart, qend = sorted((max(0, min(qstart, qlen)), max(0, min(qend, qlen))))
            by_query[qname][truth[target][0]].append((qstart, qend))
    return sum(
        overlap_bp(merge_intervals(types["PLASMID"])[0], merge_intervals(types["CHROMOSOME"])[0])
        for types in by_query.values() if types["PLASMID"] and types["CHROMOSOME"]
    )


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


def read_pred_scores(path, candidate_ids):
    """Read the SCORES.md contract: a TSV of record_id, probability (extra
    columns tolerated). record_id must exactly match candidate_ids (the
    record ids in --pred-candidates-fasta) -- not --pred-fasta's, since the
    whole point of this file is to cover the wider candidate universe the
    tool's hard call is a subset of (see adapters/SCORES.md)."""
    probabilities = {}
    with open(path) as handle:
        header = handle.readline().rstrip("\n").split("\t")
        required = {"record_id", "probability"}
        if not required.issubset(header):
            raise ValueError("pred-scores TSV must contain record_id, probability")
        indices = {name: header.index(name) for name in required}
        for line_number, line in enumerate(handle, start=2):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            record_id = fields[indices["record_id"]]
            if record_id in probabilities:
                raise ValueError(f"pred-scores line {line_number}: duplicate record_id {record_id!r}")
            try:
                probability = float(fields[indices["probability"]])
            except ValueError as exc:
                raise ValueError(f"pred-scores line {line_number}: probability must be numeric") from exc
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"pred-scores line {line_number}: probability must be in [0, 1], got {probability}")
            probabilities[record_id] = probability
    missing = candidate_ids - probabilities.keys()
    extra = probabilities.keys() - candidate_ids
    if missing or extra:
        raise ValueError(
            "pred-scores record_id set does not match --pred-candidates-fasta: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    return probabilities


def filter_covered_by_qname(covered_by_query, included_qnames):
    """Reshape covered_by_query (target -> [(qname, start, end)]) into a plain
    covered dict (target -> [(start, end)]) restricted to included_qnames, so
    the existing score() can be reused unchanged for an arbitrary subset of
    predicted records."""
    covered = defaultdict(list)
    for tname, entries in covered_by_query.items():
        for qname, start, end in entries:
            if qname in included_qnames:
                covered[tname].append((start, end))
    return covered


def sweep_thresholds(covered_by_query, probabilities, truth, total_plasmid):
    """Compute one (precision, recall) point per distinct probability value,
    high-to-low, plus the empty-inclusion endpoint every threshold above the
    maximum probability shares. That endpoint is defined as precision=1.0,
    recall=0.0 -- the standard precision_recall_curve convention -- rather
    than safe_div's 0/0 -> 0.0 fallback, which would spuriously depress the
    trapezoidal AUC by inserting a low-precision point at zero recall.

    Recall is guaranteed non-decreasing across the sweep (the included set
    only grows as the threshold falls, and merge_intervals-based coverage
    cannot shrink as more intervals are added), so the returned points are
    already ordered by recall ascending -- trapezoidal_auc still re-sorts
    defensively rather than relying on that.
    """
    thresholds = sorted(set(probabilities.values()), reverse=True)
    points = [{"threshold": "inf", "precision": 1.0, "recall": 0.0,
               "tp_bp": 0, "fp_bp": 0, "fn_bp": total_plasmid}]
    for threshold in thresholds:
        included = {qname for qname, probability in probabilities.items() if probability >= threshold}
        covered_subset = filter_covered_by_qname(covered_by_query, included)
        tp, fp, fn = score(truth, total_plasmid, covered_subset)
        points.append({"threshold": threshold, "precision": safe_div(tp, tp + fp),
                       "recall": safe_div(tp, tp + fn), "tp_bp": tp, "fp_bp": fp, "fn_bp": fn})
    return points


def trapezoidal_auc(points):
    ordered = sorted(points, key=lambda point: point["recall"])
    auc = 0.0
    for previous, current in zip(ordered, ordered[1:]):
        auc += (current["recall"] - previous["recall"]) * (previous["precision"] + current["precision"]) / 2
    return auc


def read_amr_genes(path, truth):
    """Read curated 0-based half-open AMR intervals: sequence_id, start, end."""
    if not path:
        return []
    genes = []
    with open(path) as handle:
        header = handle.readline().rstrip("\n").split("\t")
        required = {"sequence_id", "start", "end"}
        if not required.issubset(header):
            raise ValueError("AMR truth TSV must contain sequence_id, start, end")
        indices = {name: header.index(name) for name in required}
        for line_number, line in enumerate(handle, start=2):
            if not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            seq_id = fields[indices["sequence_id"]]
            if seq_id not in truth or truth[seq_id][0] != "PLASMID":
                raise ValueError(f"AMR truth line {line_number} is not on a labelled plasmid: {seq_id}")
            start, end = int(fields[indices["start"]]), int(fields[indices["end"]])
            genes.append((seq_id, max(0, start), min(truth[seq_id][1], end)))
    return genes


def read_circular_plasmids(path, truth):
    if not path:
        return []
    circular = []
    with open(path) as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if "sequence_id" not in header:
            raise ValueError("circular truth TSV must contain sequence_id")
        index = header.index("sequence_id")
        for line_number, line in enumerate(handle, start=2):
            if not line.strip():
                continue
            seq_id = line.rstrip("\n").split("\t")[index]
            if seq_id not in truth or truth[seq_id][0] != "PLASMID":
                raise ValueError(f"circular truth line {line_number} is not a labelled plasmid: {seq_id}")
            circular.append(seq_id)
    return circular


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--ambiguity-paf", help="Optional all-mapping PAF used only for ambiguous molecular-assignment diagnostics.")
    ap.add_argument("--pred-fasta", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plasmid-recovery-threshold", type=float, default=0.90,
                    help="Fraction of a true plasmid that counts as recovered (default: 0.90).")
    ap.add_argument("--amr-genes", help="Optional curated AMR truth TSV (sequence_id, start, end).")
    ap.add_argument("--amr-gene-recovery-threshold", type=float, default=0.90)
    ap.add_argument("--circular-plasmids", help="Optional curated circular-plasmid TSV (sequence_id).")
    ap.add_argument("--min-alignment-length", type=int, default=1,
                    help="Minimum PAF block length retained for scoring (default: 1).")
    ap.add_argument("--min-alignment-identity", type=float, default=0.0,
                    help="Minimum PAF matches/block-length retained for scoring (default: 0).")
    ap.add_argument("--min-alignment-mapq", type=int, default=0,
                    help="Minimum PAF mapping quality retained for scoring (default: 0).")
    ap.add_argument("--min-alignment-query-coverage", type=float, default=0.0,
                    help="Minimum fraction of a predicted record covered by an individual PAF alignment (default: 0).")
    ap.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    ap.add_argument("--pred-scores", help="Optional adapters/SCORES.md-format TSV (record_id, probability) "
                                          "covering every record in --pred-candidates-fasta; enables a PR-curve "
                                          "sweep alongside the point-estimate score above. Omitting this (and "
                                          "the two options below) reproduces today's exact single-point behavior.")
    ap.add_argument("--pred-candidates-fasta", help="Every contig/node the tool scored (superset of --pred-fasta's "
                                                     "records); required together with --pred-scores.")
    ap.add_argument("--pred-candidates-paf", help="minimap2 PAF of --pred-candidates-fasta against the reference "
                                                   "(mapped the same way as --paf); required together with --pred-scores.")
    ap.add_argument("--pr-curve-out", help="Write the swept (threshold, precision, recall) points here.")
    ap.add_argument("--pr-summary-out", help="Write a one-row (pr_auc, pr_n_thresholds) summary here.")
    args = ap.parse_args()

    truth, total_plasmid = read_truth(args.truth)
    try:
        pred_lengths = read_fasta_lengths(args.pred_fasta)
        if (args.min_alignment_length < 1 or not 0 <= args.min_alignment_identity <= 1
                or args.min_alignment_mapq < 0 or not 0 <= args.min_alignment_query_coverage <= 1):
            raise ValueError("alignment thresholds must be min-length >= 1, identity/query coverage in [0, 1], and MAPQ >= 0")
        covered, unmapped_pred_bp, off_truth_pred_bp, mapped_pred_bp, alignment, _ = parse_paf_intervals(
            args.paf, truth, pred_lengths, args.min_alignment_length,
            args.min_alignment_identity, args.min_alignment_mapq, args.min_alignment_query_coverage)
        ambiguous_bp = ambiguous_query_bp(args.ambiguity_paf, truth, pred_lengths,
                                          args.min_alignment_length, args.min_alignment_identity,
                                          args.min_alignment_mapq, args.min_alignment_query_coverage)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    tp, fp, fn = score(truth, total_plasmid, covered)

    # Optional PR-curve sweep. Entirely additive: omitting --pred-scores (and
    # the two options it requires) touches none of the point-estimate code
    # above or the header/row below, reproducing today's exact output. A
    # missing companion flag is a caller-contract bug (05_score.sh always
    # passes all three or none), so that stays a hard failure; a malformed
    # scores/candidates FILE is instead treated as an adapter data-quality
    # problem -- warn and skip the curve rather than losing this tool's
    # otherwise-valid point-estimate score below over an optional extra.
    if args.pred_scores:
        if not (args.pred_candidates_fasta and args.pred_candidates_paf):
            raise SystemExit("ERROR: --pred-scores requires --pred-candidates-fasta and --pred-candidates-paf")
        try:
            candidate_lengths = read_fasta_lengths(args.pred_candidates_fasta)
            probabilities = read_pred_scores(args.pred_scores, set(candidate_lengths))
            _, _, _, _, _, candidates_covered_by_query = parse_paf_intervals(
                args.pred_candidates_paf, truth, candidate_lengths, args.min_alignment_length,
                args.min_alignment_identity, args.min_alignment_mapq, args.min_alignment_query_coverage)
        except ValueError as exc:
            sys.stderr.write(f"WARNING: PR-curve sweep skipped for {args.sample}/{args.tool}: {exc}\n")
        else:
            points = sweep_thresholds(candidates_covered_by_query, probabilities, truth, total_plasmid)
            pr_auc = trapezoidal_auc(points)
            if args.pr_curve_out:
                with open(args.pr_curve_out, "w") as handle:
                    handle.write("threshold\tprecision\trecall\ttp_bp\tfp_bp\tfn_bp\n")
                    for point in sorted(points, key=lambda p: p["recall"]):
                        handle.write(
                            f"{point['threshold']}\t{point['precision']:.4f}\t{point['recall']:.4f}\t"
                            f"{point['tp_bp']}\t{point['fp_bp']}\t{point['fn_bp']}\n"
                        )
            if args.pr_summary_out:
                with open(args.pr_summary_out, "w") as handle:
                    handle.write("pr_auc\tpr_n_thresholds\n")
                    handle.write(f"{pr_auc:.6f}\t{len(points) - 1}\n")

    if not 0 < args.plasmid_recovery_threshold <= 1:
        raise SystemExit("ERROR: --plasmid-recovery-threshold must be in (0, 1].")
    true_plasmids = [seq_id for seq_id, (mol, _) in truth.items() if mol == "PLASMID"]
    recovered_plasmids = 0
    for seq_id in true_plasmids:
        _, covered_bp = merge_intervals(covered.get(seq_id, []))
        if safe_div(covered_bp, truth[seq_id][1]) >= args.plasmid_recovery_threshold:
            recovered_plasmids += 1
    predicted_records = len(pred_lengths)
    try:
        amr_genes = read_amr_genes(args.amr_genes, truth)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    recovered_amr = 0
    for seq_id, start, end in amr_genes:
        merged, _ = merge_intervals(covered.get(seq_id, []))
        overlap = sum(max(0, min(end, e) - max(start, s)) for s, e in merged)
        if end > start and overlap / (end - start) >= args.amr_gene_recovery_threshold:
            recovered_amr += 1
    try:
        circular_plasmids = read_circular_plasmids(args.circular_plasmids, truth)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    recovered_circular = sum(
        1 for seq_id in circular_plasmids
        if safe_div(merge_intervals(covered.get(seq_id, []))[1], truth[seq_id][1]) >= args.plasmid_recovery_threshold
    )

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)          # completeness
    f1 = safe_div(2 * precision * recall, precision + recall)

    header = [
        "sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
        "mapped_pred_bp", "unambiguously_mapped_pred_bp", "unmapped_pred_bp", "off_truth_pred_bp", "ambiguously_mapped_pred_bp", "true_plasmid_count", "recovered_plasmid_count",
        "plasmid_recall", "predicted_record_count", "true_amr_gene_count",
        "recovered_amr_gene_count", "amr_gene_recall", "true_circular_plasmid_count",
        "recovered_circular_plasmid_count", "circular_truth_plasmid_recovery", "circular_plasmid_recall", "alignment_total",
        "alignment_retained", "filtered_alignment_count", "precision", "recall", "f1",
    ]
    row = [
        args.sample, args.tool, args.analysis_track, total_plasmid, tp, fp, fn,
        mapped_pred_bp, max(0, mapped_pred_bp - ambiguous_bp), unmapped_pred_bp, off_truth_pred_bp, ambiguous_bp, len(true_plasmids), recovered_plasmids,
        f"{safe_div(recovered_plasmids, len(true_plasmids)):.4f}", predicted_records,
        len(amr_genes) if args.amr_genes else "", recovered_amr if args.amr_genes else "",
        f"{safe_div(recovered_amr, len(amr_genes)):.4f}" if args.amr_genes else "",
        len(circular_plasmids) if args.circular_plasmids else "", recovered_circular if args.circular_plasmids else "",
        f"{safe_div(recovered_circular, len(circular_plasmids)):.4f}" if args.circular_plasmids else "",
        # Compatibility alias. New consumers should use the explicitly scoped
        # circular_truth_plasmid_recovery field, which does not claim closure.
        f"{safe_div(recovered_circular, len(circular_plasmids)):.4f}" if args.circular_plasmids else "",
        alignment["alignment_total"], alignment["alignment_retained"], alignment["filtered_alignment_count"],
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
