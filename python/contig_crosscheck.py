#!/usr/bin/env python3
"""
contig_crosscheck.py -- an independent second scorer for the contig layer.

contig_classification.py labels assembly contigs from minimap2 alignments and
scores each tool per contig. This script reaches the same quantities by a
different route, sharing no code with it, so an error in either shows up as a
disagreement:

  labelling   alignment-free. Every canonical k-mer (--k, 21) of the truth
              replicons is sampled by hash (FracMinHash, keep hash % --scaled
              == 0) into a plasmid set and a chromosome set. A contig's
              containment in each set is the share of its own sampled k-mers
              found there. The decision rule mirrors the primary scorer's on
              purpose (>= --min-length bp; containment >= --min-containment in
              one kind only; in both -> AMBIGUOUS; in neither -> UNPLACED), so
              the two differ only in how "the contig matches that truth" is
              measured: shared k-mers here, alignment coverage there.
  scoring     written separately: TP/FP/FN/TN over evaluable contigs, by count
              and by length, precision/recall/F1/MCC.

Subcommands:
  label    one sample: <sample>/contig_labels.kmer.tsv
  compare  every sample and tool: per (sample, tool) the label agreement
           (share of contigs given the same label, and Cohen's kappa) and both
           scorers' length-weighted F1 and MCC with their difference, plus the
           primary scorer's recorded values. Status "agree" when |delta F1| and
           |delta MCC| are both <= --tolerance (0.02); otherwise "disagree",
           listed with the contigs labelled differently.

Assembly contigs are near-identical to their own isolate's reference, so exact
k-mer containment is a fair independent test; a divergent truth (another
isolate's reference) would not be, and is not what the contig layer scores.

Standard library only.
"""

import argparse
import csv
import gzip
import hashlib
import math
import os
import sys
from collections import Counter
from pathlib import Path

LABEL_FIELDS = ["contig", "length", "label", "plasmid_containment", "chromosome_containment", "sampled_kmers"]
COMPARE_FIELDS = ["sample", "tool", "n_contigs", "n_label_agree", "label_agreement", "label_kappa",
                  "primary_f1_bp", "independent_f1_bp", "delta_f1_bp", "primary_mcc_bp", "independent_mcc_bp",
                  "delta_mcc_bp", "recorded_f1_bp", "status", "differing_contigs"]
COMPLEMENT = str.maketrans("ACGTacgt", "TGCAtgca")


def fasta(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    name, parts = None, []
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line[0] == ">":
                if name is not None:
                    yield name, "".join(parts).upper()
                name, parts = line[1:].split()[0], []
            else:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts).upper()


def sampled_kmers(sequence, k, scaled):
    """Canonical k-mers whose hash is 0 modulo `scaled` (deterministic: blake2b)."""
    out = set()
    reverse = sequence.translate(COMPLEMENT)[::-1]
    n = len(sequence)
    for i in range(n - k + 1):
        forward = sequence[i:i + k]
        if "N" in forward:
            continue
        rc = reverse[n - i - k:n - i]
        kmer = forward if forward <= rc else rc
        value = int.from_bytes(hashlib.blake2b(kmer.encode(), digest_size=8).digest(), "little")
        if value % scaled == 0:
            out.add(value)
    return out


def read_truth_kinds(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return {r["sequence_id"]: r["molecule_type"].strip().upper() for r in csv.DictReader(handle, delimiter="\t")}


def cmd_label(args):
    kinds = read_truth_kinds(args.truth)
    plasmid, chromosome = set(), set()
    for name, seq in fasta(args.reference):
        kind = kinds.get(name)
        if kind == "PLASMID":
            plasmid |= sampled_kmers(seq, args.k, args.scaled)
        elif kind == "CHROMOSOME":
            chromosome |= sampled_kmers(seq, args.k, args.scaled)
    rows = []
    for name, seq in fasta(args.contigs):
        kmers = sampled_kmers(seq, args.k, args.scaled)
        p = len(kmers & plasmid) / len(kmers) if kmers else 0.0
        c = len(kmers & chromosome) / len(kmers) if kmers else 0.0
        if len(seq) < args.min_length:
            label = "SHORT"
        elif p >= args.min_containment and c >= args.min_containment:
            label = "AMBIGUOUS"
        elif p >= args.min_containment:
            label = "PLASMID"
        elif c >= args.min_containment:
            label = "CHROMOSOME"
        else:
            label = "UNPLACED"
        rows.append({"contig": name, "length": len(seq), "label": label, "plasmid_containment": f"{p:.4f}",
                     "chromosome_containment": f"{c:.4f}", "sampled_kmers": len(kmers)})
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(r["label"] for r in rows)
    sys.stderr.write("[contig_crosscheck] " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + "\n")


def read_labels(path):
    if not path.is_file():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {r["contig"]: (r["label"], int(r["length"])) for r in csv.DictReader(handle, delimiter="\t")}


def fasta_ids(path):
    if not path.is_file() or not path.stat().st_size:
        return set()
    with open(path, encoding="utf-8") as handle:
        return {line[1:].split()[0] for line in handle if line.startswith(">")}


def length_weighted(labels, called):
    """(F1, MCC) by contig length over PLASMID/CHROMOSOME contigs; None when undefined."""
    tp = fp = fn = tn = 0
    for contig, (label, length) in labels.items():
        if label == "PLASMID":
            tp, fn = (tp + length, fn) if contig in called else (tp, fn + length)
        elif label == "CHROMOSOME":
            fp, tn = (fp + length, tn) if contig in called else (fp, tn + length)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if recall is None:
        f1 = None
    elif not precision:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    denominator = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    mcc = (tp * tn - fp * fn) / math.sqrt(denominator) if denominator else None
    return f1, mcc


def kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right.get(k, 0) for k in left) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def cmd_compare(args):
    results, data = Path(args.results_dir), Path(args.data_dir)
    fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
    rows = []
    for primary_path in sorted(data.glob("*/contig_labels.tsv")):
        sample = primary_path.parent.name
        primary = read_labels(primary_path)
        independent = read_labels(primary_path.with_name("contig_labels.kmer.tsv"))
        if not independent:
            continue
        shared = sorted(set(primary) & set(independent))
        pairs = [(primary[c][0], independent[c][0]) for c in shared]
        differing = [c for c in shared if primary[c][0] != independent[c][0]]
        for pred in sorted((results / sample).glob("pred_*.plasmid.fasta")):
            tool = pred.name[len("pred_"):-len(".plasmid.fasta")]
            called = fasta_ids(pred)
            if called and not (called & set(primary)):
                continue  # reassembled sequences: the contig layer does not apply
            f1_a, mcc_a = length_weighted({c: primary[c] for c in shared}, called)
            f1_b, mcc_b = length_weighted({c: independent[c] for c in shared}, called)
            recorded = ""
            summary = results / sample / f"{tool}.contig_classification.tsv"
            if summary.is_file():
                with open(summary, newline="", encoding="utf-8") as handle:
                    recorded = (next(csv.DictReader(handle, delimiter="\t"), {}) or {}).get("contig_f1_bp", "")
            d_f1 = None if f1_a is None or f1_b is None else abs(f1_a - f1_b)
            d_mcc = None if mcc_a is None or mcc_b is None else abs(mcc_a - mcc_b)
            agree = all(d is None or d <= args.tolerance for d in (d_f1, d_mcc)) and (f1_a is None) == (f1_b is None)
            rows.append({"sample": sample, "tool": tool, "n_contigs": len(shared),
                         "n_label_agree": len(shared) - len(differing),
                         "label_agreement": fmt((len(shared) - len(differing)) / len(shared) if shared else None),
                         "label_kappa": fmt(kappa(pairs)), "primary_f1_bp": fmt(f1_a), "independent_f1_bp": fmt(f1_b),
                         "delta_f1_bp": fmt(d_f1), "primary_mcc_bp": fmt(mcc_a), "independent_mcc_bp": fmt(mcc_b),
                         "delta_mcc_bp": fmt(d_mcc), "recorded_f1_bp": recorded,
                         "status": "agree" if agree else "disagree", "differing_contigs": ",".join(differing[:20])})
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPARE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    disagree = sum(r["status"] == "disagree" for r in rows)
    sys.stderr.write(f"[contig_crosscheck] {len(rows)} (sample, tool) pair(s) compared, {disagree} disagree "
                     f"beyond {args.tolerance} -> {args.out}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    lab = sub.add_parser("label")
    lab.add_argument("--contigs", required=True)
    lab.add_argument("--reference", required=True)
    lab.add_argument("--truth", required=True)
    lab.add_argument("--out", required=True)
    lab.add_argument("--k", type=int, default=21)
    lab.add_argument("--scaled", type=int, default=int(os.environ.get("CONTIG_CROSSCHECK_SCALED", 10)))
    lab.add_argument("--min-length", type=int, default=int(os.environ.get("CONTIG_MIN_LENGTH", 1000)))
    lab.add_argument("--min-containment", type=float, default=float(os.environ.get("CONTIG_MIN_COVERAGE", 0.80)))
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--results-dir", required=True)
    cmp_.add_argument("--data-dir", required=True)
    cmp_.add_argument("--out", required=True)
    cmp_.add_argument("--tolerance", type=float, default=0.02)
    args = ap.parse_args()
    cmd_label(args) if args.command == "label" else cmd_compare(args)


if __name__ == "__main__":
    main()
