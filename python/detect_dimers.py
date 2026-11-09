#!/usr/bin/env python3
"""
detect_dimers.py -- find truth plasmids that are tandem dimers of themselves and,
optionally, collapse them to the monomer before anything is scored.

A reference assembler sometimes closes a plasmid as two head-to-tail copies
(panel edge case D2). Scoring against the dimer halves every tool's recall on
it: a perfect monomer reconstruction covers only half the "true" sequence.

Detection: split the replicon into halves [0, L/2) and [L/2, L). For a circular
dimer M+M every linearisation gives two halves that are copies of M, so the
halves are compared directly:

  * minimap2 (when on PATH): align half 1 to half 2 (asm5); identity = matches /
    block length of the best alignment, coverage = aligned fraction of half 2.
  * otherwise: Hamming identity of the two equal-length halves (exact or
    substitution-only copies; an indel between the copies lowers it).

A dimer has identity >= --min-identity (0.95) over >= --min-half-coverage (0.90)
of the half length. Only PLASMID-labelled replicons are tested.

With --collapse, each dimer is replaced in the reference FASTA by its first half
and its truth.tsv length is updated; AMR and circular-truth rows on the second
copy are dropped (the first copy's rows still score). The original reference is
kept as reference.precollapse.fna. Every change is written to
truth.corrections.tsv, which the report and label_schemes.py read. Without
--collapse the dimer is only flagged: the evidence scheme then excludes it
(AMBIGUOUS, python/label_truth_evidence.py --multimers).

Standard library only (minimap2 optional).
"""

import argparse
import csv
import gzip
import os
import shutil
import subprocess
import sys
import tempfile

FIELDS = ["sequence_id", "original_length", "corrected_length", "identity", "half_coverage", "method",
          "multimer", "action"]


from plasbench_common import iter_fasta  # noqa: E402


def read_fasta(path):
    """[(full header, sequence)]: dimer records are keyed by the whole header line."""
    return [(header, seq) for _, header, seq in iter_fasta(path)]


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader), list(reader.fieldnames or [])


def hamming_identity(a, b):
    n = min(len(a), len(b))
    if n == 0:
        return 0.0, 0.0
    same = sum(1 for x, y in zip(a[:n].upper(), b[:n].upper()) if x == y)
    return same / n, n / max(len(a), len(b))


def minimap2_identity(a, b, threads=1):
    """(identity, coverage of b) of the best alignment of a against b, or None."""
    with tempfile.TemporaryDirectory() as tmp:
        qa, tb = os.path.join(tmp, "a.fa"), os.path.join(tmp, "b.fa")
        with open(qa, "w") as handle:
            handle.write(f">a\n{a}\n")
        with open(tb, "w") as handle:
            handle.write(f">b\n{b}\n")
        try:
            out = subprocess.run(["minimap2", "-x", "asm5", "--secondary=no", "-t", str(threads), tb, qa],
                                 check=True, capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None
    best = None
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) < 12:
            continue
        matches, block, tlen, tstart, tend = int(f[9]), int(f[10]), int(f[6]), int(f[7]), int(f[8])
        candidate = (matches / block if block else 0.0, (tend - tstart) / tlen if tlen else 0.0)
        if best is None or candidate[1] > best[1]:
            best = candidate
    return best or (0.0, 0.0)


def test_dimer(sequence, min_identity, min_coverage, use_minimap2=True):
    """(is_dimer, identity, coverage, method)."""
    half = len(sequence) // 2
    if half < 100:
        return False, 0.0, 0.0, "too_short"
    a, b = sequence[:half], sequence[half:half * 2]
    result = minimap2_identity(a, b) if use_minimap2 and shutil.which("minimap2") else None
    method = "minimap2"
    if result is None:
        result, method = hamming_identity(a, b), "hamming"
    identity, coverage = result
    return identity >= min_identity and coverage >= min_coverage, identity, coverage, method


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--truth", required=True, help="truth.tsv (updated in place with --collapse)")
    ap.add_argument("--amr-truth", help="truth_amr.tsv (second-copy rows dropped with --collapse)")
    ap.add_argument("--circular-truth", help="truth_circular.tsv (kept; ids are unchanged)")
    ap.add_argument("--out", required=True, help="truth.corrections.tsv")
    ap.add_argument("--min-identity", type=float, default=0.95)
    ap.add_argument("--min-half-coverage", type=float, default=0.90)
    ap.add_argument("--collapse", action="store_true")
    ap.add_argument("--no-minimap2", action="store_true", help="always use the Hamming comparison")
    args = ap.parse_args()

    truth, truth_fields = read_tsv(args.truth)
    plasmids = {r["sequence_id"] for r in truth if (r.get("molecule_type") or "").upper() == "PLASMID"}
    records = read_fasta(args.reference)
    corrections, new_records = [], []
    for header, sequence in records:
        sid = header.split()[0]
        if sid not in plasmids:
            new_records.append((header, sequence))
            continue
        dimer, identity, coverage, method = test_dimer(sequence, args.min_identity, args.min_half_coverage,
                                                       not args.no_minimap2)
        if not dimer:
            new_records.append((header, sequence))
            continue
        monomer = sequence[:len(sequence) // 2]
        action = "collapsed" if args.collapse else "flagged"
        corrections.append({"sequence_id": sid, "original_length": len(sequence),
                            "corrected_length": len(monomer) if args.collapse else len(sequence),
                            "identity": f"{identity:.4f}", "half_coverage": f"{coverage:.4f}", "method": method,
                            "multimer": "yes", "action": action})
        new_records.append((header, monomer) if args.collapse else (header, sequence))

    collapsed = {c["sequence_id"]: int(c["corrected_length"]) for c in corrections if c["action"] == "collapsed"}
    if collapsed:
        backup = os.path.join(os.path.dirname(os.path.abspath(args.reference)), "reference.precollapse.fna")
        if not os.path.exists(backup):
            shutil.copyfile(args.reference, backup)
        tmp = args.reference + ".tmp"
        with open(tmp, "w") as handle:
            for header, sequence in new_records:
                handle.write(f">{header}\n")
                for i in range(0, len(sequence), 80):
                    handle.write(sequence[i:i + 80] + "\n")
        os.replace(tmp, args.reference)
        for row in truth:
            if row["sequence_id"] in collapsed:
                row["length"] = str(collapsed[row["sequence_id"]])
        with open(args.truth, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=truth_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(truth)
        amr, amr_fields = read_tsv(args.amr_truth)
        if amr:
            kept = [r for r in amr if r.get("sequence_id") not in collapsed
                    or int(r.get("end") or 0) <= collapsed[r["sequence_id"]]]
            if len(kept) != len(amr):
                with open(args.amr_truth, "w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=amr_fields, delimiter="\t", lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(kept)
                sys.stderr.write(f"[detect_dimers] dropped {len(amr) - len(kept)} AMR row(s) on second copies\n")
    # Written last, so it is newer than the rewritten reference and truth and
    # stage 2 can skip a re-run (a collapsed monomer is no longer a dimer).
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(corrections)
    sys.stderr.write(f"[detect_dimers] {len(corrections)} dimer(s) among {len(plasmids)} plasmid(s); "
                     f"{len(collapsed)} collapsed\n")


if __name__ == "__main__":
    main()
