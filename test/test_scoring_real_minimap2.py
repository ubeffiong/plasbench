#!/usr/bin/env python3
"""Golden test with the REAL aligner: minimap2 + score_plasmids.py on seeded sequences.

Every other scoring test feeds the scorer a hand-written PAF, so none of them checks
the minimap2 invocation the pipeline actually uses (scripts/05_score.sh). This one
builds a reference, makes a prediction whose answer is known by construction, aligns
it with the same flags and scores it with the pipeline's filter defaults.

Skipped (exit 0, with a message) when minimap2 is not on PATH; CI installs it.
"""
import csv
import os
import random
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER = os.path.join(ROOT, "python", "score_plasmids.py")


def seq(rng, n):
    return "".join(rng.choice("ACGT") for _ in range(n))


def main():
    if not shutil.which("minimap2"):
        print("SKIP: minimap2 not on PATH (CI installs it); real-aligner golden test not run")
        return 0
    rng = random.Random(20240607)
    chrom, plasmid = seq(rng, 20000), seq(rng, 6000)
    foreign = seq(rng, 2000)                      # in no reference: must stay unmapped
    with tempfile.TemporaryDirectory() as d:
        ref, pred, truth = (os.path.join(d, n) for n in ("ref.fa", "pred.fa", "truth.tsv"))
        open(ref, "w").write(f">chr\n{chrom}\n>p1\n{plasmid}\n")
        open(pred, "w").write(f">hit\n{plasmid[:4000]}\n>junk\n{foreign}\n")
        open(truth, "w").write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\np1\tPLASMID\t6000\n")
        paf = os.path.join(d, "pred.paf")
        with open(paf, "w") as fh:
            subprocess.run(["minimap2", "--secondary=no", "-c", "-x", "asm5", ref, pred],
                           check=True, stdout=fh, stderr=subprocess.DEVNULL)
        out = os.path.join(d, "scores.tsv")
        subprocess.run([sys.executable, SCORER, "--truth", truth, "--paf", paf, "--pred-fasta", pred,
                        "--sample", "golden", "--tool", "ctl", "--out", out,
                        "--min-alignment-length", "200", "--min-alignment-identity", "0.90",
                        "--min-alignment-mapq", "20", "--min-alignment-query-coverage", "0.20"],
                       check=True, capture_output=True)
        with open(out, newline="") as fh:
            row = next(csv.DictReader(fh, delimiter="\t"))
    tp, fp = int(row["TP_bp"]), int(row["FP_bp"])
    # Exact copy of 4000 bp of the plasmid: minimap2 may trim a few bp at chain ends.
    checks = {
        "TP within 1% of 4000 bp": 3960 <= tp <= 4000,
        "no chromosome FP from an exact plasmid copy": fp == 0,
        "foreign 2000 bp stays unmapped (not FP)": int(row["unmapped_pred_bp"]) >= 1900,
        "precision == 1": float(row["precision"]) == 1.0,
        "recall ~ 4000/6000": abs(float(row["recall"]) - 4000 / 6000) < 0.01,
    }
    ok = True
    for name, good in checks.items():
        print(f"  {name}: {'PASS' if good else 'FAIL'}")
        ok &= good
    print("ALL REAL MINIMAP2 GOLDEN TESTS PASSED" if ok else f"GOLDEN TEST FAILED: row={row}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
