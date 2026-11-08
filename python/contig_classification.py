#!/usr/bin/env python3
"""
contig_classification.py -- contig-level plasmid/chromosome classification
metrics, alongside PlasBench's reference-base scoring.

The base-level scorer projects predictions onto the reference. Most tools,
though, classify the contigs of a short-read assembly, and reviewers expect the
classification task scored on those contigs: each contig counts once
(count-based), and again weighted by its length (length-weighted). Both are
reported, with MCC because plasmid contigs are a small minority and accuracy is
misleading under that imbalance.

Contig labels (subcommand `label`), from an all-alignments PAF of the assembly
contigs against the truth reference (minimap2 -x asm5 -c --secondary=yes):

  SHORT      shorter than --min-length (default 1000 bp): excluded, counted.
  PLASMID    >= --min-coverage (0.80) of the contig aligns to PLASMID truth at
             >= --min-identity (0.95), and it does not also align that well to
             CHROMOSOME.
  CHROMOSOME the same, for CHROMOSOME truth.
  AMBIGUOUS  aligns that well to BOTH (IS elements, transposons, rRNA repeats):
             excluded from scoring -- not multi-membership -- and counted.
  UNPLACED   aligns well to neither (misassembly, contamination, truth gap):
             excluded, counted.

Truth is the file of the scored labelling scheme (stage 5 passes the same
TRUTH_LABEL_SCHEME truth it scores against; truth.tsv under the primary NCBI
scheme, truth.scored.tsv under the evidence scheme, where AMBIGUOUS replicons do
not label contigs either). `label` also writes, per truth
plasmid, how many of its bases the assembly's PLASMID contigs cover -- the
assembly-aware denominator for binning recall (score_bins.py
--assembly-coverage), so tools are not blamed for gaps in the assembly itself.

Per tool (subcommand `score`), a contig is called plasmid when its id appears in
the tool's predicted-plasmid FASTA. Tools that output reassembled sequences
rather than assembly contigs (no predicted id matches an assembly contig) are
marked not applicable rather than scored as calling nothing. Abstention: tools
in this pipeline do not report an explicit "unclassified" call, so abstention
is not measured; a contig a tool did not call plasmid counts as called
chromosome.

Standard library only.
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

LABEL_FIELDS = ["contig", "length", "label", "plasmid_fraction", "chromosome_fraction", "best_plasmid", "reason"]
SCORE_FIELDS = ["contig_min_length", "contigs_evaluable", "contigs_short", "contigs_ambiguous", "contigs_unplaced",
                "contig_tp", "contig_fp", "contig_fn", "contig_tn",
                "contig_precision_count", "contig_recall_count", "contig_f1_count", "contig_mcc_count",
                "contig_tp_bp", "contig_fp_bp", "contig_fn_bp", "contig_tn_bp",
                "contig_precision_bp", "contig_recall_bp", "contig_f1_bp", "contig_mcc_bp",
                "contig_classification_status",
                # Scoring specification (WP3): lengths of the excluded categories, and
                # contig-level binning (length-weighted, Hungarian one-to-one matching
                # over PLASMID contigs; |P| = summed PLASMID-contig length per plasmid,
                # a contig-layer-only denominator).
                "contigs_ambiguous_bp", "contigs_unplaced_bp",
                "contig_bin_precision_bp", "contig_bin_recall_bp", "contig_bin_f1_bp"]


def read_fasta_lengths(path):
    lengths, name = {}, None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                name = line[1:].split()[0]
                lengths[name] = 0
            elif name is not None:
                lengths[name] += len(line)
    return lengths


def read_truth(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sequence_id"]: (row["molecule_type"].strip().upper(), int(row["length"]))
                for row in csv.DictReader(handle, delimiter="\t")}


def merged_length(intervals):
    total, end = 0, -1
    for start, stop in sorted(intervals):
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


def merge(intervals):
    out = []
    for start, stop in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], stop)
        else:
            out.append([start, stop])
    return out


def cmd_label(args):
    lengths = read_fasta_lengths(args.contigs)
    truth = read_truth(args.truth)
    query_intervals = defaultdict(lambda: defaultdict(list))   # contig -> kind -> query intervals
    plasmid_bp = defaultdict(lambda: defaultdict(int))          # contig -> plasmid -> aligned bp
    target_intervals = defaultdict(list)                        # (contig, plasmid) -> target intervals
    with open(args.paf, encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 12 or f[0] not in lengths or f[5] not in truth:
                continue
            matches, block = int(f[9]), int(f[10])
            if not block or matches / block < args.min_identity:
                continue
            kind = truth[f[5]][0]
            q = (min(int(f[2]), int(f[3])), max(int(f[2]), int(f[3])))
            t = (min(int(f[7]), int(f[8])), max(int(f[7]), int(f[8])))
            query_intervals[f[0]][kind].append(q)
            if kind == "PLASMID":
                plasmid_bp[f[0]][f[5]] += q[1] - q[0]
                target_intervals[(f[0], f[5])].append(t)
    rows, covered = [], defaultdict(list)
    for contig, length in lengths.items():
        p_frac = merged_length(query_intervals[contig]["PLASMID"]) / length if length else 0.0
        c_frac = merged_length(query_intervals[contig]["CHROMOSOME"]) / length if length else 0.0
        best = max(plasmid_bp[contig], key=plasmid_bp[contig].get) if plasmid_bp[contig] else ""
        if length < args.min_length:
            label, reason = "SHORT", f"shorter than {args.min_length} bp"
        elif p_frac >= args.min_coverage and c_frac >= args.min_coverage:
            label, reason = "AMBIGUOUS", "aligns to both plasmid and chromosome truth"
        elif p_frac >= args.min_coverage:
            label, reason = "PLASMID", f"{p_frac:.0%} aligned to plasmid truth"
        elif c_frac >= args.min_coverage:
            label, reason = "CHROMOSOME", f"{c_frac:.0%} aligned to chromosome truth"
        else:
            label, reason = "UNPLACED", f"aligned fraction below {args.min_coverage:.0%} to either"
        if label == "PLASMID":
            for plasmid in plasmid_bp[contig]:
                covered[plasmid].extend(target_intervals[(contig, plasmid)])
        rows.append({"contig": contig, "length": length, "label": label, "plasmid_fraction": f"{p_frac:.4f}",
                     "chromosome_fraction": f"{c_frac:.4f}", "best_plasmid": best, "reason": reason})
    with open(args.labels_out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if args.coverage_out:
        with open(args.coverage_out, "w", newline="", encoding="utf-8") as handle:
            handle.write("sequence_id\tlength\tassembly_covered_bp\n")
            for seq_id, (kind, length) in sorted(truth.items()):
                if kind == "PLASMID":
                    bp = min(length, merged_length([tuple(i) for i in merge(covered[seq_id])]))
                    handle.write(f"{seq_id}\t{length}\t{bp}\n")
    counts = defaultdict(int)
    for row in rows:
        counts[row["label"]] += 1
    sys.stderr.write("[contig_classification] " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + "\n")


def ratios(tp, fp, fn, tn):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall else
          (0.0 if recall is not None else None))
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / denominator if denominator else None
    return precision, recall, f1, mcc


def fmt(value):
    return f"{value:.4f}" if value is not None else ""


def cmd_score(args):
    with open(args.labels, newline="", encoding="utf-8") as handle:
        labels = list(csv.DictReader(handle, delimiter="\t"))
    called = set(read_fasta_lengths(args.pred_fasta)) if os.path.getsize(args.pred_fasta) else set()
    contig_ids = {row["contig"] for row in labels}
    row = {field: "" for field in SCORE_FIELDS}
    row["contig_min_length"] = args.min_length
    if called and not (called & contig_ids):
        row["contig_classification_status"] = "not_applicable: predictions are not assembly contigs"
    else:
        tallies = {"n": [0, 0, 0, 0], "bp": [0, 0, 0, 0]}  # tp, fp, fn, tn
        excluded = defaultdict(int)
        for label in labels:
            kind, length = label["label"], int(label["length"])
            if kind not in ("PLASMID", "CHROMOSOME"):
                excluded[kind] += 1
                continue
            is_called = label["contig"] in called
            index = (0 if is_called else 2) if kind == "PLASMID" else (1 if is_called else 3)
            tallies["n"][index] += 1
            tallies["bp"][index] += length
        excluded_bp = defaultdict(int)
        for label in labels:
            if label["label"] in ("AMBIGUOUS", "UNPLACED"):
                excluded_bp[label["label"]] += int(label["length"])
        row.update({"contigs_ambiguous_bp": excluded_bp["AMBIGUOUS"], "contigs_unplaced_bp": excluded_bp["UNPLACED"]})
        if args.bins and os.path.isfile(args.bins) and os.path.getsize(args.bins):
            p, r, f1 = contig_binning(labels, args.bins)
            row.update({"contig_bin_precision_bp": fmt(p), "contig_bin_recall_bp": fmt(r), "contig_bin_f1_bp": fmt(f1)})
        row.update({"contigs_evaluable": sum(tallies["n"]), "contigs_short": excluded["SHORT"],
                    "contigs_ambiguous": excluded["AMBIGUOUS"], "contigs_unplaced": excluded["UNPLACED"]})
        for key, suffix, fields in (("n", "count", ("contig_tp", "contig_fp", "contig_fn", "contig_tn")),
                                    ("bp", "bp", ("contig_tp_bp", "contig_fp_bp", "contig_fn_bp", "contig_tn_bp"))):
            for field, value in zip(fields, tallies[key]):
                row[field] = value
            p, r, f1, mcc = ratios(*tallies[key])
            row.update({f"contig_precision_{suffix}": fmt(p), f"contig_recall_{suffix}": fmt(r),
                        f"contig_f1_{suffix}": fmt(f1), f"contig_mcc_{suffix}": fmt(mcc)})
        row["contig_classification_status"] = "scored"
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def contig_binning(labels, bins_path):
    """Length-weighted binning P/R/F1 at contig level (score_bins.length_weighted_binning).
    A PLASMID contig belongs to its best_plasmid; a CHROMOSOME contig placed in a
    bin is wrongly binned material; contigs in no bin are not predicted."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import score_bins
    membership = score_bins.read_bins(bins_path)
    overlaps, plasmids, total_mapped = defaultdict(int), defaultdict(int), defaultdict(int)
    for label in labels:
        kind, length, contig = label["label"], int(label["length"]), label["contig"]
        if kind == "PLASMID" and label.get("best_plasmid"):
            plasmids[label["best_plasmid"]] += length
        bin_id = membership.get(contig)
        if bin_id is None or kind not in ("PLASMID", "CHROMOSOME"):
            continue
        total_mapped[bin_id] += length
        if kind == "PLASMID" and label.get("best_plasmid"):
            overlaps[(bin_id, label["best_plasmid"])] += length
    if not plasmids:
        return None, None, None
    all_bins = set(membership.values())
    for bin_id in all_bins:
        total_mapped.setdefault(bin_id, 0)
    lw = score_bins.length_weighted_binning(dict(overlaps), dict(plasmids), dict(total_mapped), all_bins)
    return lw["precision"], lw["recall"], lw["f1"]


def cmd_merge(args):
    """Append each <sample>/<tool>.contig_classification.tsv row to scores.tsv."""
    from pathlib import Path
    summaries = {}
    for path in Path(args.results_dir).glob("*/*.contig_classification.tsv"):
        tool = path.name.removesuffix(".contig_classification.tsv")
        with open(path, newline="", encoding="utf-8") as handle:
            summaries[(path.parent.name, tool)] = next(csv.DictReader(handle, delimiter="\t"), {})
    with open(args.scores, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    fields = list(rows[0]) if rows else []
    fields += [f for f in SCORE_FIELDS if f not in fields]
    for row in rows:
        summary = summaries.get((row["sample"], row["tool"]), {})
        for field in SCORE_FIELDS:
            row[field] = summary.get(field, "")
    with open(args.scores, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    lab = sub.add_parser("label", help="label assembly contigs against truth")
    lab.add_argument("--contigs", required=True)
    lab.add_argument("--paf", required=True, help="contigs vs truth reference, all alignments")
    lab.add_argument("--truth", required=True)
    lab.add_argument("--labels-out", required=True)
    lab.add_argument("--coverage-out", help="per truth plasmid: bases covered by the assembly's plasmid contigs")
    lab.add_argument("--min-length", type=int, default=1000)
    lab.add_argument("--min-identity", type=float, default=0.95)
    lab.add_argument("--min-coverage", type=float, default=0.80)
    lab.set_defaults(func=cmd_label)
    sco = sub.add_parser("score", help="count-based and length-weighted metrics for one tool")
    sco.add_argument("--labels", required=True)
    sco.add_argument("--pred-fasta", required=True)
    sco.add_argument("--out", required=True)
    sco.add_argument("--min-length", type=int, default=1000)
    sco.add_argument("--bins", help="the tool's bins TSV (sequence_id, bin_id): adds contig-level binning F1")
    sco.set_defaults(func=cmd_score)
    mer = sub.add_parser("merge", help="join per-tool rows into scores.tsv")
    mer.add_argument("--scores", required=True)
    mer.add_argument("--results-dir", required=True)
    mer.set_defaults(func=cmd_merge)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
