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
                  Two attribution modes (attribution_mode), by what the tool's
                  output can claim (second review, section 7):
                    bin_matching        a tool that bins (--bins): the covering
                                        record's bin is matched one-to-one to a
                                        truth plasmid with score_bins.maximum_weight
                                        over aligned bases. correct_plasmid when that
                                        plasmid is the gene's (level 2).
                    contig_attribution  a tool that does not bin (a classifier, a
                                        reassembler): there is no plasmid-level
                                        grouping to match, and one truth plasmid may
                                        rightly be spread over several records, so a
                                        one-to-one matching would wrongly leave all but
                                        one of them unmatched. Each gene-bearing record
                                        is attributed to the truth sequence it aligns
                                        to most (many records may share one plasmid).
                                        correct_plasmid then means plasmid-associated
                                        sequence attribution, NOT a reconstructed
                                        plasmid: AMR-PRR and co-localisation are not
                                        applicable and stay blank. A record that the
                  contig layer labelled AMBIGUOUS (shared with the chromosome or
                  another plasmid) or UNPLACED is its own category, never
                  counted right or wrong.
  replicon level  level 1: the matched plasmid carries a replicon type the gene's
                  plasmid also carries (truth_features.tsv); not_evaluated when
                  replicon typing did not run.

Gene class comes from config/amr_gene_classes.tsv (prefix match on gene_name;
unmatched genes are "other").

How a predicted unit is attributed to a plasmid depends on what the tool outputs (the registry's evaluation_task; --task):
  binning_reconstruction   ONE-TO-ONE: each bin is matched to at most one plasmid and each plasmid to at most one bin (maximum weight over aligned bases). Two bins that both hold
                           pieces of one plasmid cannot both be that plasmid: the plasmid is fragmented, and the bin that lost the matching is wrong for its genes.
  classification,          MANY-TO-ONE: each predicted record is attributed to the plasmid it overlaps most, so two contigs that each carry one resistance gene of the same plasmid
  sequence_reassembly      are both correctly attributed. That says which plasmid the evidence points at for each gene; it is NOT evidence that the tool linked the genes or reconstructed
                           the plasmid. Forcing one record per plasmid on these tools (as one-to-one matching does) would call the second correct contig wrong and understate their gene recovery.
AMR-PRR and the co-localisation of genes are only defined for tools whose output supports plasmid-level reconstruction (binning and reassembly); a classifier gets neither.

Context (plan B4), per gene copy and per plasmid, reported beside the placement and never ranking a tool:
  flank context   share of the +-AMR_FLANK_BP (1000) flanks of the copy that the SAME covering record also covers (clipped at the plasmid ends):
                  was the gene recovered with its surroundings, or as a fragment? Blank when the copy was not recovered.
  co-localisation for two recovered copies on one truth plasmid, whether the tool put them in the same bin (same record for a tool that does not bin);
                  the share of such pairs kept together.
  AMR-PRR         of the plasmids that carry a curated AMR copy, the share whose copies ALL sit on the right plasmid AND that the tool reconstructed correctly
                  (CPRR criteria, `--cprr` the tool's per-plasmid table); blank without that table. `amr_complete_rate` is the same without the CPRR condition.
Each is alignment-derived from curated truth and as unvalidated as that truth: a draft from derive_amr_truth.py is not curated until promote_amr_truth.py.
A truth row whose `evidence_tier` is `auto_derived` is a draft that someone copied to truth_amr.tsv without promoting it: it is scored (the file is the file the scorer reads) but
every gene copy carries its `truth_evidence_tier`, a warning is printed, and the summary counts `draft_truth_copies`, so the report can say the result rests on uncurated truth.
AMR-PRR follows CPRR's identity rule: on an isolate whose truth cannot judge identity (polished with the benchmark's own reads) the tool's CPRR verdict without the identity
criterion is used (`collect --truth-provenance`).

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
import tool_capabilities as tc  # noqa: E402

GENE_FIELDS = ["sample", "tool", "copy_id", "gene_name", "gene_class", "sequence_id", "start", "end",
               "covering_record", "assigned_bin", "matched_plasmid", "placement", "replicon_type_correct", "flank_covered", "plasmid_cprr_correct",
               "plasmid_cprr_correct_no_identity", "truth_evidence_tier", "evaluation_task", "attribution", "attribution_mode"]
SUMMARY_FIELDS = ["tool", "gene_class", "n_gene_copies", "n_recovered", "n_correct_plasmid", "n_wrong_plasmid",
                  "n_shared_contig", "n_unassigned_contig", "correct_plasmid_rate", "replicon_type_correct_rate",
                  "n_samples", "n_amr_plasmids", "amr_complete_rate", "amr_prr", "n_pairs", "n_colocalised_pairs", "colocalisation_rate", "flank_context_rate", "draft_truth_copies", "evaluation_task", "attribution_mode"]
DEFAULT_CLASSES = Path(__file__).resolve().parents[1] / "config" / "amr_gene_classes.tsv"


def read_tsv(path):
    if not path or not os.path.isfile(path) or not os.path.getsize(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


FLANK_BP = int(os.environ.get("AMR_FLANK_BP", 1000))


def covered_bp(intervals, start, end):
    """Bases of [start, end) covered by the union of `intervals` ((s, e) pairs)."""
    total, cursor = 0, start
    for s, e in sorted(intervals):
        s, e = max(s, cursor), min(e, end)
        if e > s:
            total += e - s
            cursor = e
    return total


def flank_share(record_intervals, start, end, plasmid_length, flank):
    """Share of the two flanks of [start, end) (each `flank` bases, clipped to 0 and the plasmid length) that the intervals cover; None when there is no flank."""
    flanks = [(max(0, start - flank), start), (end, min(plasmid_length, end + flank))]
    total = sum(b - a for a, b in flanks if b > a)
    if total <= 0:
        return None
    return sum(covered_bp(record_intervals, a, b) for a, b in flanks if b > a) / total


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


ONE_TO_ONE_TASKS = ("binning_reconstruction",)


def attribute_units(overlaps, plasmids, task):
    """{unit: plasmid}: which plasmid each predicted unit (a bin, or a record for a tool that does not bin) is attributed to, by the rule of the tool's task (see the module docstring).

    overlaps: {(unit, plasmid): aligned bases}. One-to-one for binning (a plasmid goes to one bin); many-to-one for the others (a unit goes to the plasmid it overlaps most, ties by name)."""
    units = sorted({u for u, _ in overlaps})
    if task in ONE_TO_ONE_TASKS:
        return {b: p for b, p, _ in score_bins.maximum_weight(dict(overlaps), units, sorted(plasmids))}
    best = {}
    for (unit, plasmid), bp in sorted(overlaps.items()):
        if bp > 0 and (unit not in best or bp > best[unit][1]):
            best[unit] = (plasmid, bp)
    return {unit: plasmid for unit, (plasmid, _bp) in best.items()}


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
    cprr_rows = read_tsv(args.cprr) if getattr(args, "cprr", None) else []
    cprr = {r.get("true_plasmid"): r.get("correct") for r in cprr_rows}
    cprr_no_identity = {r.get("true_plasmid"): r.get("correct_without_identity") for r in cprr_rows}
    if any((r.get("evidence_tier") or "") == "auto_derived" for r in amr):
        sys.stderr.write(f"[score_amr_placement] WARNING: {args.sample}: the AMR truth contains auto-derived DRAFT rows (evidence_tier=auto_derived), not curated truth: review the draft and "
                         "promote it (plasbench promote-amr-truth) instead of copying it to truth_amr.tsv.\n")

    # Unit (bin, or record) -> plasmid, by the rule of the tool's task: one-to-one for a binner, best plasmid per record for a classifier or a reassembler.
    task = tc.LEGACY_TASKS.get(getattr(args, "task", "binning_reconstruction"), getattr(args, "task", "binning_reconstruction"))
    overlaps = defaultdict(int)
    for target, intervals in covered_by_query.items():
        if target not in plasmids:
            continue
        for query, start, end in intervals:
            overlaps[(membership.get(query, query), target)] += max(0, end - start)
    # bin_matching: a binner with bins, matched one-to-one. contig_attribution: a classifier or reassembler (or a binner that wrote no bins): each record is attributed to the truth sequence
    # (plasmid or chromosome) it aligns to most, many records may share one plasmid, and a record that is mostly chromosome is wrong for a plasmid gene.
    mode = "bin_matching" if task in ONE_TO_ONE_TASKS and membership else "contig_attribution"
    if mode == "bin_matching":
        matched = attribute_units(overlaps, plasmids, task)
    else:
        matched = dominant_targets(covered_by_query)
    attribution = "one_to_one_bin" if mode == "bin_matching" else "best_plasmid_per_record"
    if mode == "contig_attribution" and task != "sequence_reassembly":
        cprr, cprr_no_identity = {}, {}   # no plasmid-level reconstruction to judge (a classifier, or a binner that wrote no bins): AMR-PRR is not applicable

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
                  "matched_plasmid": "", "placement": "not_recovered", "replicon_type_correct": "", "flank_covered": "",
                  "plasmid_cprr_correct": cprr.get(sid, ""), "plasmid_cprr_correct_no_identity": cprr_no_identity.get(sid, ""),
                  "truth_evidence_tier": (row.get("evidence_tier") or "").strip(), "evaluation_task": task, "attribution": attribution, "attribution_mode": mode}
        if best and best_bp / length >= args.min_gene_coverage:
            # contig_attribution: the record is attributed on its own; there is no bin, so no co-localisation claim
            bin_id = membership.get(best, best) if mode == "bin_matching" else ""
            target = matched.get(bin_id if mode == "bin_matching" else best, "")
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
            share = flank_share([(qs, qe) for q, qs, qe in covered_by_query.get(sid, []) if q == best], start, end, plasmids.get(sid, end), args.flank_bp)
            record.update(covering_record=best, assigned_bin=bin_id, matched_plasmid=target, placement=placement,
                          replicon_type_correct=replicon, flank_covered="" if share is None else f"{share:.4f}")
        out.append(record)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GENE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    sys.stderr.write(f"[score_amr_placement] {args.sample}/{args.tool} ({mode}): "
                     f"{sum(r['placement'] == 'correct_plasmid' for r in out)}/{len(out)} gene copies on the right plasmid"
                     + (" sequence (not a reconstructed plasmid)" if mode == "contig_attribution" else "") + "\n")


def dominant_targets(covered_by_query):
    """record -> the truth sequence (plasmid or chromosome) it has the most aligned bases on; ties go to the lower id."""
    totals = defaultdict(lambda: defaultdict(int))
    for target, intervals in covered_by_query.items():
        for query, start, end in intervals:
            totals[query][target] += max(0, end - start)
    return {query: sorted(by_target.items(), key=lambda item: (-item[1], item[0]))[0][0] for query, by_target in totals.items() if by_target}


def context(items, invalid_identity=frozenset()):
    """(plasmids with AMR, complete rate, AMR-PRR, pairs, co-localised pairs, co-localisation rate, mean flank context) for one group of gene-copy rows.

    `invalid_identity` is the set of samples whose truth cannot judge identity: for them the CPRR verdict without the identity criterion decides AMR-PRR, as for CPRR itself."""
    fmt = lambda n, d: f"{n / d:.4f}" if d else ""  # noqa: E731
    by_plasmid = defaultdict(list)
    for r in items:
        by_plasmid[(r["sample"], r["sequence_id"])].append(r)
    complete = {k: all(r["placement"] == "correct_plasmid" for r in v) for k, v in by_plasmid.items()}
    def verdict(key):
        record = by_plasmid[key][0]
        return record.get("plasmid_cprr_correct_no_identity") if key[0] in invalid_identity else record.get("plasmid_cprr_correct")
    known = {k: verdict(k) in ("yes", "no") for k in by_plasmid}
    prr_den = sum(1 for k in by_plasmid if known[k])
    prr_num = sum(1 for k in by_plasmid if known[k] and complete[k] and verdict(k) == "yes")
    pairs = together = 0
    for v in by_plasmid.values():
        got = [r["assigned_bin"] for r in v if r["placement"] != "not_recovered" and r.get("assigned_bin")]
        for i in range(len(got)):
            for j in range(i + 1, len(got)):
                pairs += 1
                together += got[i] == got[j]
    flanks = [float(r["flank_covered"]) for r in items if r.get("flank_covered") not in ("", None)]
    return (len(by_plasmid), fmt(sum(complete.values()), len(by_plasmid)), fmt(prr_num, prr_den), pairs, together, fmt(together, pairs),
            f"{sum(flanks) / len(flanks):.4f}" if flanks else "")


def summary_context(items, invalid_identity=frozenset()):
    """The context columns of one summary row. AMR-PRR and the pair co-localisation are blank for a classifier: its records are not plasmid reconstructions, so
    'these genes were kept together' and 'the plasmid was reconstructed' are not claims it makes. Its gene attribution and flank context are still reported."""
    values = dict(zip(("n_amr_plasmids", "amr_complete_rate", "amr_prr", "n_pairs", "n_colocalised_pairs", "colocalisation_rate", "flank_context_rate"), context(items, invalid_identity)))
    if (items[0].get("evaluation_task") or "binning_reconstruction") == "classification":
        values.update(amr_prr="", n_pairs="", n_colocalised_pairs="", colocalisation_rate="")
    return values


def summarise(rows, invalid_identity=frozenset()):
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
                    "n_samples": len({r["sample"] for r in items}),
                    **summary_context(items, invalid_identity),
                    "draft_truth_copies": sum(1 for r in items if (r.get("truth_evidence_tier") or "") == "auto_derived"),
                    "evaluation_task": items[0].get("evaluation_task") or "binning_reconstruction",
                    "attribution_mode": "/".join(sorted({r.get("attribution_mode") or "bin_matching" for r in items}))})
    return out


def invalid_identity_samples(path):
    """The samples whose truth cannot judge identity (truth_provenance base_level_metrics_valid is not 'yes'): the rule of headline_design.Design.identity_valid."""
    return {r["sample"] for r in read_tsv(path) if r.get("sample") and r.get("base_level_metrics_valid") != "yes"} if path else set()


def cmd_collect(args):
    rows = []
    for path in sorted(Path(args.results_dir).glob("*/*.amr_placement.tsv")):
        rows.extend(read_tsv(str(path)))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(summarise(rows, invalid_identity_samples(getattr(args, "truth_provenance", None))))
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
    s.add_argument("--task", choices=tc.EVALUATION_TASKS + tuple(tc.LEGACY_TASKS), default="binning_reconstruction",
                   help="the tool's evaluation task (registry evaluation_task): binning is matched one-to-one, classification and reassembly attribute each record to the plasmid it overlaps most")
    s.add_argument("--cprr", help="the tool's <tool>.cprr.tsv (score_bins.py --cprr-out): which truth plasmids it reconstructed correctly (for AMR-PRR)")
    s.add_argument("--flank-bp", type=int, default=FLANK_BP, help="bases either side of a gene copy whose coverage is the flank context (env AMR_FLANK_BP, default 1000)")
    s.add_argument("--min-gene-coverage", type=float, default=0.90)
    s.add_argument("--min-alignment-length", type=int, default=1)
    s.add_argument("--min-alignment-identity", type=float, default=0.0)
    s.add_argument("--min-alignment-mapq", type=int, default=0)
    s.add_argument("--min-alignment-query-coverage", type=float, default=0.0)
    c = sub.add_parser("collect")
    c.add_argument("--results-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--truth-provenance", help="benchmark.truth_provenance.tsv: AMR-PRR then follows CPRR's identity rule for isolates whose truth cannot judge identity")
    args = ap.parse_args()
    cmd_score(args) if args.command == "score" else cmd_collect(args)


if __name__ == "__main__":
    main()
