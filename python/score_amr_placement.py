#!/usr/bin/env python3
"""
score_amr_placement.py -- does a tool put each AMR gene copy on the right plasmid?
(scoring specification, AMR placement)

Input is the curated AMR truth (truth_amr.tsv: one row per gene copy with its
plasmid and coordinates, validate_amr_truth.py), the tool's PAF against the
reference, its predicted FASTA and, when it bins, its bins TSV. Per gene copy:

  copy matching   a predicted record covers >= --min-gene-coverage (0.90) of the
                  copy AT ITS POSITION on its plasmid; a second copy elsewhere
                  does not stand in for it.
  placement       not_recovered | shared_contig | unassigned_contig |
                  wrong_plasmid | correct_plasmid
                  The covering record's bin (or the record itself when the tool
                  does not bin) is matched one-to-one to a truth plasmid with
                  score_bins.maximum_weight over aligned bases. correct_plasmid
                  when that plasmid is the gene's (level 2). A record that the
                  contig layer labelled AMBIGUOUS (shared with the chromosome or
                  another plasmid) or UNPLACED is its own category, never
                  counted right or wrong.
  replicon level  level 1: the matched plasmid carries a replicon type the gene's
                  plasmid also carries (truth_features.tsv); not_evaluated when
                  replicon typing did not run.

Gene class comes from config/amr_gene_classes.tsv (prefix match on gene_name;
unmatched genes are "other").

Subcommands: `score` (one sample and tool) and `collect` (every
<sample>/<tool>.amr_placement.tsv -> one row per tool and gene class).
Standard library only.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_bins  # noqa: E402
import score_plasmids as sp  # noqa: E402

GENE_FIELDS = ["sample", "tool", "copy_id", "gene_name", "gene_class", "sequence_id", "start", "end",
               "covering_record", "assigned_bin", "matched_plasmid", "placement", "replicon_type_correct"]
SUMMARY_FIELDS = ["tool", "gene_class", "n_gene_copies", "n_recovered", "n_correct_plasmid", "n_wrong_plasmid",
                  "n_shared_contig", "n_unassigned_contig", "correct_plasmid_rate", "replicon_type_correct_rate",
                  "n_samples"]
DEFAULT_CLASSES = Path(__file__).resolve().parents[1] / "config" / "amr_gene_classes.tsv"


def read_tsv(path):
    if not path or not os.path.isfile(path) or not os.path.getsize(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def gene_class(name, classes):
    lowered = (name or "").lower()
    for prefix, cls in sorted(classes, key=lambda item: -len(item[0])):
        if lowered.startswith(prefix.lower()):
            return cls
    return "other"


def replicon_types(features):
    types = defaultdict(set)
    for row in features:
        # annotate_reference.py columns: feature_type (replicon/mob/amr/...), label.
        if (row.get("feature_type") or "") == "replicon" and row.get("label"):
            types[row.get("sequence_id", "")].add(row["label"])
    return types


def cmd_score(args):
    truth, _, _ = sp.read_truth(args.truth)
    amr = read_tsv(args.amr_truth)
    pred_lengths = sp.read_fasta_lengths(args.pred_fasta) if os.path.getsize(args.pred_fasta) else {}
    covered_by_query = sp.parse_paf_intervals(args.paf, truth, pred_lengths, args.min_alignment_length,
                                              args.min_alignment_identity, args.min_alignment_mapq,
                                              args.min_alignment_query_coverage)[5] if pred_lengths else {}
    membership = score_bins.read_bins(args.bins) if args.bins and os.path.isfile(args.bins) else {}
    labels = {r["contig"]: r["label"] for r in read_tsv(args.contig_labels)}
    classes = [(r["gene_prefix"], r["gene_class"]) for r in read_tsv(args.gene_classes) if r.get("gene_prefix")]
    rtypes = replicon_types(read_tsv(args.features))
    plasmids = {sid: length for sid, (mol, length) in truth.items() if mol == "PLASMID"}

    # Bin -> plasmid by maximum-weight one-to-one matching over aligned bases.
    overlaps = defaultdict(int)
    for target, intervals in covered_by_query.items():
        if target not in plasmids:
            continue
        for query, start, end in intervals:
            overlaps[(membership.get(query, query), target)] += max(0, end - start)
    bins = sorted({b for b, _ in overlaps})
    matched = {b: p for b, p, _ in score_bins.maximum_weight(dict(overlaps), bins, sorted(plasmids))}

    out = []
    for row in amr:
        sid, start, end = row["sequence_id"], int(row["start"]), int(row["end"])
        length = max(1, end - start)
        best, best_bp = "", 0
        for query, qs, qe in covered_by_query.get(sid, []):
            bp = max(0, min(end, qe) - max(start, qs))
            if bp > best_bp:
                best, best_bp = query, bp
        record = {"sample": args.sample, "tool": args.tool, "copy_id": row.get("copy_id", ""),
                  "gene_name": row.get("gene_name", ""), "gene_class": gene_class(row.get("gene_name"), classes),
                  "sequence_id": sid, "start": start, "end": end, "covering_record": "", "assigned_bin": "",
                  "matched_plasmid": "", "placement": "not_recovered", "replicon_type_correct": ""}
        if best and best_bp / length >= args.min_gene_coverage:
            bin_id = membership.get(best, best)
            target = matched.get(bin_id, "")
            label = labels.get(best, "")
            if label == "AMBIGUOUS":
                placement = "shared_contig"
            elif label == "UNPLACED":
                placement = "unassigned_contig"
            else:
                placement = "correct_plasmid" if target == sid else "wrong_plasmid"
            replicon = "not_evaluated"
            if rtypes and target:
                replicon = "yes" if (rtypes.get(target, set()) & rtypes.get(sid, set())) else "no"
            record.update(covering_record=best, assigned_bin=bin_id, matched_plasmid=target, placement=placement,
                          replicon_type_correct=replicon)
        out.append(record)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GENE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    sys.stderr.write(f"[score_amr_placement] {args.sample}/{args.tool}: "
                     f"{sum(r['placement'] == 'correct_plasmid' for r in out)}/{len(out)} gene copies on the right plasmid\n")


def summarise(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["tool"], row["gene_class"])].append(row)
        groups[(row["tool"], "all")].append(row)
    out = []
    for (tool, cls), items in sorted(groups.items()):
        recovered = [r for r in items if r["placement"] != "not_recovered"]
        decided = [r for r in recovered if r["placement"] in ("correct_plasmid", "wrong_plasmid")]
        typed = [r for r in recovered if r["replicon_type_correct"] in ("yes", "no")]
        fmt = lambda n, d: f"{n / d:.4f}" if d else ""  # noqa: E731
        out.append({"tool": tool, "gene_class": cls, "n_gene_copies": len(items), "n_recovered": len(recovered),
                    "n_correct_plasmid": sum(r["placement"] == "correct_plasmid" for r in items),
                    "n_wrong_plasmid": sum(r["placement"] == "wrong_plasmid" for r in items),
                    "n_shared_contig": sum(r["placement"] == "shared_contig" for r in items),
                    "n_unassigned_contig": sum(r["placement"] == "unassigned_contig" for r in items),
                    "correct_plasmid_rate": fmt(sum(r["placement"] == "correct_plasmid" for r in decided), len(items)),
                    "replicon_type_correct_rate": fmt(sum(r["replicon_type_correct"] == "yes" for r in typed), len(typed)),
                    "n_samples": len({r["sample"] for r in items})})
    return out


def cmd_collect(args):
    rows = []
    for path in sorted(Path(args.results_dir).glob("*/*.amr_placement.tsv")):
        rows.extend(read_tsv(str(path)))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(summarise(rows))
    sys.stderr.write(f"[score_amr_placement] {len(rows)} gene-copy row(s) -> {args.out}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("score")
    for name in ("--sample", "--tool", "--truth", "--amr-truth", "--paf", "--pred-fasta", "--out"):
        s.add_argument(name, required=True)
    s.add_argument("--bins")
    s.add_argument("--contig-labels", help="contig_classification.py labels (AMBIGUOUS/UNPLACED categories)")
    s.add_argument("--features", help="truth_features.tsv (replicon types, level 1)")
    s.add_argument("--gene-classes", default=str(DEFAULT_CLASSES))
    s.add_argument("--min-gene-coverage", type=float, default=0.90)
    s.add_argument("--min-alignment-length", type=int, default=1)
    s.add_argument("--min-alignment-identity", type=float, default=0.0)
    s.add_argument("--min-alignment-mapq", type=int, default=0)
    s.add_argument("--min-alignment-query-coverage", type=float, default=0.0)
    c = sub.add_parser("collect")
    c.add_argument("--results-dir", required=True)
    c.add_argument("--out", required=True)
    args = ap.parse_args()
    cmd_score(args) if args.command == "score" else cmd_collect(args)


if __name__ == "__main__":
    main()
