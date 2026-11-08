#!/usr/bin/env python3
"""
scorable_truth.py -- which true-plasmid bases CAN a prediction be scored on?

score_plasmids.py keeps only alignments that pass the length / identity /
MAPQ / query-coverage filters (MAPQ >= 20 by default). Plasmid sequence that
also occurs elsewhere in the same genome -- an IS element or transposon
shared with the chromosome or another plasmid, or a plasmid present in two
identical copies -- gets MAPQ ~0, so a prediction covering only that sequence
is dropped and those bases can never become TP. Recall then has a ceiling
below 1.0 that differs between isolates and is invisible in the score.

This script measures that ceiling directly, using the scorer's own mapper and
filters. Every truth plasmid is tiled into overlapping windows; the windows
are mapped back to the reference exactly the way predictions are (the caller
runs minimap2 with the same preset and --secondary=no); a window counts as
"scorable" only if its retained alignment lands on its own origin. The union
of scorable windows is written to truth_scorable.tsv, which score_plasmids.py
--scorable-truth turns into recall_ceiling and ceiling_adjusted_recall.

Approximation: a real contig that spans a repeat AND its unique flanks maps
uniquely and does cover the repeat, so this per-window view is a
conservative (pessimistic) ceiling for repeats longer than the window, and
blind to repeats much shorter than it. It is a diagnostic only.

Subcommands
  windows    --reference ref.fna --truth truth.tsv --out windows.fa
             [--window 1000] [--step 250]
  intervals  --paf windows_vs_ref.paf --truth truth.tsv --out truth_scorable.tsv
             [--min-alignment-length ...] [--min-alignment-identity ...]
             [--min-alignment-mapq ...] [--min-alignment-query-coverage ...]

Standard library only.
"""

import argparse
import gzip
import os
import sys

SEPARATOR = "__plasbench_window__"


def open_text(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def read_truth(path):
    """Read truth with exactly the scorer's validation.

    This used to be a looser copy that accepted duplicate ids, non-positive
    lengths and unknown molecule types, so the ceiling could be computed from a
    table the scorer itself would refuse. It now delegates to
    score_plasmids.read_truth.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from score_plasmids import read_truth as scorer_read_truth
    truth, _, _ = scorer_read_truth(path)
    clashes = [seq_id for seq_id in truth if SEPARATOR in seq_id]
    if clashes:
        sys.exit(f"ERROR: sequence id '{clashes[0]}' contains the reserved window "
                 f"separator '{SEPARATOR}'; rename it before computing scorable truth.")
    return truth


def read_fasta(path):
    name, chunks = None, []
    with open_text(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(chunks)
                name, chunks = line[1:].split()[0], []
            else:
                chunks.append(line)
    if name is not None:
        yield name, "".join(chunks)


def window_starts(length, window, step):
    """Start positions covering [0, length) with fixed-size windows."""
    if length <= window:
        return [0]
    starts = list(range(0, length - window + 1, step))
    if starts[-1] + window < length:
        starts.append(length - window)
    return starts


def cmd_windows(args):
    if args.window < 1 or args.step < 1:
        sys.exit("ERROR: --window and --step must be >= 1")
    truth = read_truth(args.truth)
    written = 0
    with open(args.out, "w") as out:
        for name, seq in read_fasta(args.reference):
            mol = truth.get(name, (None, 0))[0]
            if mol != "PLASMID":
                continue
            for start in window_starts(len(seq), args.window, args.step):
                end = min(len(seq), start + args.window)
                out.write(f">{name}{SEPARATOR}{start}_{end}\n{seq[start:end]}\n")
                written += 1
    sys.stderr.write(f"[scorable_truth] wrote {written} plasmid window(s) to {args.out}\n")


def merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def parse_window_name(name):
    if SEPARATOR not in name:
        return None
    seq_id, coords = name.rsplit(SEPARATOR, 1)
    start, end = coords.split("_")
    return seq_id, int(start), int(end)


def cmd_intervals(args):
    truth = read_truth(args.truth)
    scorable = {seq_id: [] for seq_id, (mol, _) in truth.items() if mol == "PLASMID"}
    with open(args.paf) as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 12:
                sys.exit(f"ERROR: PAF line {line_number} has fewer than 12 columns")
            origin = parse_window_name(f[0])
            if origin is None:
                continue
            seq_id, w_start, w_end = origin
            qlen, qstart, qend = int(f[1]), int(f[2]), int(f[3])
            target, tstart, tend = f[5], int(f[7]), int(f[8])
            matches, block, mapq = int(f[9]), int(f[10]), int(f[11])
            identity = matches / block if block else 0.0
            qcov = abs(qend - qstart) / qlen if qlen else 0.0
            if (block < args.min_alignment_length or identity < args.min_alignment_identity
                    or mapq < args.min_alignment_mapq or qcov < args.min_alignment_query_coverage):
                continue
            if target != seq_id or seq_id not in scorable:
                continue
            # Must land on its own origin, not a same-sequence copy elsewhere.
            if min(tend, w_end) - max(tstart, w_start) <= 0:
                continue
            scorable[seq_id].append((max(tstart, w_start), min(tend, w_end)))
    total_plasmid = sum(length for mol, length in truth.values() if mol == "PLASMID")
    total_scorable = 0
    with open(args.out, "w") as out:
        out.write("sequence_id\tstart\tend\n")
        for seq_id in sorted(scorable):
            for start, end in merge(scorable[seq_id]):
                out.write(f"{seq_id}\t{start}\t{end}\n")
                total_scorable += end - start
    fraction = total_scorable / total_plasmid if total_plasmid else 0.0
    sys.stderr.write(f"[scorable_truth] scorable plasmid bp: {total_scorable}/{total_plasmid} "
                     f"({fraction:.3f}) -> {args.out}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    w = sub.add_parser("windows", help="tile truth plasmids into windows FASTA")
    w.add_argument("--reference", required=True)
    w.add_argument("--truth", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--window", type=int, default=1000)
    w.add_argument("--step", type=int, default=250)
    w.set_defaults(func=cmd_windows)
    i = sub.add_parser("intervals", help="turn windows-vs-reference PAF into scorable intervals")
    i.add_argument("--paf", required=True)
    i.add_argument("--truth", required=True)
    i.add_argument("--out", required=True)
    i.add_argument("--min-alignment-length", type=int, default=1)
    i.add_argument("--min-alignment-identity", type=float, default=0.0)
    i.add_argument("--min-alignment-mapq", type=int, default=0)
    i.add_argument("--min-alignment-query-coverage", type=float, default=0.0)
    i.set_defaults(func=cmd_intervals)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
