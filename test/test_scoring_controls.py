#!/usr/bin/env python3
"""Control predictions with analytically known answers.

A benchmark is a measuring instrument; before trusting it on tools, show it returns
the right number for predictions whose score can be computed by hand. Uses a
hand-written PAF, so no minimap2 is needed.

Reference: chromosome 8000 bp; plasmid P1 1500 bp; plasmid P2 500 bp (2000 plasmid bp).

  oracle            predicts exactly P1 + P2          -> precision 1, recall 1, F1 1
  empty             predicts nothing                  -> recall 0, F1 0, precision blank
  whole genome      predicts everything               -> recall 1, precision 2000/10000
  chromosome only   predicts only chromosome          -> TP 0, precision 0, F1 0
  half oracle       predicts P1 only                  -> precision 1, recall 0.75
  plasmid-free      isolate with no plasmid, predicts
                    a chromosome chunk                -> recall/F1 blank, FP counted
"""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER = os.path.join(ROOT, "python", "score_plasmids.py")


def score(tmp, name, truth_rows, paf_rows, fasta):
    truth, paf, pred, out = (os.path.join(tmp, f"{name}.{x}") for x in ("truth", "paf", "fa", "out"))
    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\n")
        for seq, kind, length in truth_rows:
            fh.write(f"{seq}\t{kind}\t{length}\n")
    with open(paf, "w") as fh:
        for q, qlen, t, tlen, start, end in paf_rows:
            fh.write(f"{q}\t{qlen}\t0\t{qlen}\t+\t{t}\t{tlen}\t{start}\t{end}\t{qlen}\t{qlen}\t60\n")
    with open(pred, "w") as fh:
        for rec, length in fasta.items():
            fh.write(f">{rec}\n{'A' * length}\n")
    subprocess.run([sys.executable, SCORER, "--truth", truth, "--paf", paf, "--pred-fasta", pred,
                    "--sample", name, "--tool", "ctl", "--out", out], check=True,
                   capture_output=True)
    with open(out, newline="") as fh:
        return next(csv.DictReader(fh, delimiter="\t"))


def num(row, key):
    value = row[key]
    return None if value == "" else float(value)


def main():
    ok = True
    ref = [("chr", "CHROMOSOME", 8000), ("P1", "PLASMID", 1500), ("P2", "PLASMID", 500)]
    with tempfile.TemporaryDirectory() as tmp:
        cases = {
            "oracle": (ref, [("q1", 1500, "P1", 1500, 0, 1500), ("q2", 500, "P2", 500, 0, 500)],
                       {"q1": 1500, "q2": 500}, dict(precision=1.0, recall=1.0, f1=1.0)),
            "empty": (ref, [], {}, dict(precision=None, recall=0.0, f1=0.0)),
            "whole_genome": (ref, [("g1", 8000, "chr", 8000, 0, 8000),
                                   ("g2", 1500, "P1", 1500, 0, 1500),
                                   ("g3", 500, "P2", 500, 0, 500)],
                             {"g1": 8000, "g2": 1500, "g3": 500},
                             dict(precision=0.2, recall=1.0, f1=2 * 0.2 / 1.2)),
            "chromosome_only": (ref, [("c1", 3000, "chr", 8000, 0, 3000)], {"c1": 3000},
                                dict(precision=0.0, recall=0.0, f1=0.0)),
            "half_oracle": (ref, [("q1", 1500, "P1", 1500, 0, 1500)], {"q1": 1500},
                            dict(precision=1.0, recall=0.75, f1=2 * 0.75 / 1.75)),
            "plasmid_free": ([("chr", "CHROMOSOME", 8000)],
                             [("c1", 1000, "chr", 8000, 0, 1000)], {"c1": 1000},
                             dict(precision=0.0, recall=None, f1=None)),
        }
        for name, (truth_rows, paf_rows, fasta, want) in cases.items():
            row = score(tmp, name, truth_rows, paf_rows, fasta)
            for key, expected in want.items():
                got = num(row, key)
                good = (got is None and expected is None) or (
                    got is not None and expected is not None and abs(got - expected) < 1e-3)
                print(f"  {name:16s} {key:9s} got={got} expected={expected} {'PASS' if good else 'FAIL'}")
                ok &= good
            if name == "plasmid_free":
                fp = int(row["FP_bp"])
                print(f"  {name:16s} FP_bp     got={fp} expected=1000 {'PASS' if fp == 1000 else 'FAIL'}")
                ok &= fp == 1000
    print("ALL SCORING CONTROL TESTS PASSED" if ok else "SCORING CONTROL TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
