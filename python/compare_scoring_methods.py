#!/usr/bin/env python3
"""One-off BLASTN-vs-minimap2 scoring cross-check (Phase E, Part 15 of the
sibling-repo cross-pollination plan) -- NOT part of the ongoing pipeline,
never wired into any stage script, matching parse_teixeira2025_supplement.py's
own "one-time migration/investigation script" precedent. Run it by hand
against a handful of already-scored samples to get independent evidence for
or against PlasBench's own minimap2-based scoring approach.

PlasBench scores every tool by projecting its predicted-plasmid FASTA onto
the reference with minimap2 and merging aligned intervals per reference
sequence (score_plasmids.py) -- an EXACT base-level accounting. A sibling
plasmid-tool benchmarking pipeline, C-Connor/PlasmidToolBenchMarking, scores
predictions with BLASTN instead. This script reproduces its VERIFIED,
real command from that repo's own `modules/BlastContigs/main.nf`
(confirmed by direct fetch, not assumed from a generic BLASTN invocation):

    blastn -num_threads 1 -dust no -perc_identity 80 -evalue 1E-20 \\
        -culling_limit 1 -max_target_seqs 10000 \\
        -outfmt '6 qseqid qlen sseqid slen length pident qcovhsp' \\
        -subject <reference.fna> -query <pred_<tool>.plasmid.fasta>

IMPORTANT CAVEAT, stated plainly rather than papered over: that repo's own
chosen `-outfmt` has NO sstart/send (alignment coordinates on the
reference), so it cannot do the same exact interval-merge PlasBench's own
minimap2+PAF approach does -- a real limitation of the outfmt they picked,
confirmed by direct fetch, not this script's own shortcut. Their own
downstream scoring interpretation (whatever R/Python step consumes the raw
`.blastresults` file this command produces) lives elsewhere in their
pipeline and was not part of this verification. This script therefore
computes a GOOD-FAITH PROXY using only the confirmed columns: each hit's
own `length` (alignment length, not merged/deduplicated) is attributed to
whichever molecule_type its `sseqid` maps to in truth.tsv, capped per truth
sequence at that sequence's own total length to bound the double-counting
redundant/overlapping HSPs would otherwise cause -- clearly a coarser
accounting than PlasBench's own exact interval merge, not a claim of
methodological equivalence.

Reports, per sample/tool: PlasBench's own minimap2-based F1 (read directly
from the real scores.tsv row already produced by a normal PlasBench run --
never re-derived, so this is the actual number the leaderboard shows) next
to this script's own BLASTN-derived F1 proxy, and their absolute
difference, as evidence for how much scoring-method choice alone can move
the reported number.

Usage:
  compare_scoring_methods.py --sample s1 --tool platon \\
      --reference data/s1/reference.fna --truth data/s1/truth.tsv \\
      --pred-fasta results/s1/pred_platon.plasmid.fasta \\
      --scores results/scores.tsv --out s1.platon.scoring_comparison.tsv
"""

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path


def read_truth(path):
    """sequence_id -> (molecule_type, length)."""
    truth = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            truth[row["sequence_id"]] = (row["molecule_type"].upper(), int(row["length"]))
    return truth


def read_minimap2_f1(scores_path, sample, tool):
    """The REAL, already-computed minimap2-based F1 for this sample/tool
    from a normal PlasBench run -- never re-derived here, so this is
    exactly the number the leaderboard shows."""
    with open(scores_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["sample"] == sample and row["tool"] == tool:
                value = row.get("f1", "")
                return float(value) if value else None
    return None


def run_blastn(blastn_path, query, subject, threads=1):
    command = [blastn_path, "-num_threads", str(threads), "-dust", "no",
               "-perc_identity", "80", "-evalue", "1E-20", "-culling_limit", "1",
               "-max_target_seqs", "10000",
               "-outfmt", "6 qseqid qlen sseqid slen length pident qcovhsp",
               "-subject", str(subject), "-query", str(query)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"[compare_scoring_methods] blastn failed (exit {result.returncode}):\n{result.stderr[-2000:]}\n")
        return None
    return result.stdout


def blastn_f1(hits_text, truth):
    """Good-faith proxy F1 from BLASTN hit lengths -- see module docstring
    for exactly why this is coarser than PlasBench's own minimap2+PAF exact
    interval merge, and in what specific way."""
    tp_by_seq = {}
    fp = 0
    for line in hits_text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 5:
            continue
        sseqid, length = fields[2], int(fields[4])
        molecule_type, seq_len = truth.get(sseqid, (None, 0))
        if molecule_type == "PLASMID":
            tp_by_seq[sseqid] = min(seq_len, tp_by_seq.get(sseqid, 0) + length)
        elif molecule_type == "CHROMOSOME":
            fp += length
        # A hit to a sequence absent from truth.tsv is neither TP nor FP --
        # matching score_plasmids.py's own off_truth_pred_bp treatment.
    tp = sum(tp_by_seq.values())
    total_plasmid = sum(length for molecule_type, length in truth.values() if molecule_type == "PLASMID")
    fn = max(0, total_plasmid - tp)
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--pred-fasta", required=True)
    ap.add_argument("--scores", required=True, help="An existing scores.tsv from a real PlasBench run.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    header = ["sample", "tool", "minimap2_f1", "blastn_f1_proxy", "absolute_difference"]
    minimap2_f1 = read_minimap2_f1(args.scores, args.sample, args.tool)

    blastn_path = shutil.which("blastn")
    blastn_proxy = None
    if not blastn_path:
        sys.stderr.write("[compare_scoring_methods] blastn is not installed (or not on PATH)\n")
    elif not Path(args.pred_fasta).is_file() or Path(args.pred_fasta).stat().st_size == 0:
        sys.stderr.write(f"[compare_scoring_methods] {args.pred_fasta} is empty (tool predicted nothing); no BLASTN comparison\n")
    else:
        hits_text = run_blastn(blastn_path, args.pred_fasta, args.reference)
        if hits_text is not None:
            truth = read_truth(args.truth)
            blastn_proxy = blastn_f1(hits_text, truth)

    difference = (abs(minimap2_f1 - blastn_proxy)
                  if minimap2_f1 is not None and blastn_proxy is not None else None)
    row = [args.sample, args.tool,
           f"{minimap2_f1:.4f}" if minimap2_f1 is not None else "",
           f"{blastn_proxy:.4f}" if blastn_proxy is not None else "",
           f"{difference:.4f}" if difference is not None else ""]

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerow(row)

    sys.stderr.write(f"[compare_scoring_methods] {args.sample}/{args.tool}: "
                      f"minimap2_f1={row[2] or 'n/a'} blastn_f1_proxy={row[3] or 'n/a'}\n")


if __name__ == "__main__":
    main()
