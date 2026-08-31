#!/usr/bin/env python3
"""
test_scoring.py -- prove score_plasmids.py computes the right numbers on a
hand-built example, WITHOUT needing minimap2 or any downloaded data.

We invent a tiny reference genome:
    chromosome  : 10,000 bp   (CHROMOSOME)
    plasmidA    :  2,000 bp   (PLASMID)
    plasmidB    :  1,000 bp   (PLASMID)
  => total plasmid bp = 3,000

We then hand-write a PAF describing what a hypothetical tool "predicted as
plasmid", and check the metrics match values we computed by hand.

Scenario:
  * The tool fully covers plasmidA  (2000/2000 plasmid bp recovered)  -> TP += 2000
  * It covers only half of plasmidB (bases 0..500)                    -> TP +=  500
  * It wrongly claims a 300 bp chunk of the chromosome (bases 0..300) -> FP  =  300
  Expected:
    TP = 2500, FP = 300, FN = 3000 - 2500 = 500
    precision = 2500 / 2800 = 0.8929
    recall    = 2500 / 3000 = 0.8333
    f1        = 2*0.8929*0.8333/(0.8929+0.8333) = 0.8621
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCORER = os.path.join(HERE, "..", "python", "score_plasmids.py")


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def write_fasta(path, records):
    with open(path, "w") as fh:
        for name, length in records.items():
            fh.write(f">{name}\n")
            fh.write("A" * length + "\n")


def main():
    tmp = tempfile.mkdtemp(prefix="score_test_")
    truth = os.path.join(tmp, "truth.tsv")
    paf = os.path.join(tmp, "pred.paf")
    pred = os.path.join(tmp, "pred.fasta")
    out = os.path.join(tmp, "scores.tsv")

    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\n")
        fh.write("chromosome\tCHROMOSOME\t10000\n")
        fh.write("plasmidA\tPLASMID\t2000\n")
        fh.write("plasmidB\tPLASMID\t1000\n")

    # PAF columns: qname qlen qstart qend strand tname tlen tstart tend matches blocklen mapq
    # We only need targets/coords to be right for scoring.
    with open(paf, "w") as fh:
        # predicted contig 1 covers all of plasmidA
        fh.write("pred1\t2000\t0\t2000\t+\tplasmidA\t2000\t0\t2000\t2000\t2000\t60\n")
        # predicted contig 2 covers first 500 bp of plasmidB
        fh.write("pred2\t500\t0\t500\t+\tplasmidB\t1000\t0\t500\t500\t500\t60\n")
        # predicted contig 3 wrongly covers 300 bp of the chromosome
        fh.write("pred3\t300\t0\t300\t+\tchromosome\t10000\t0\t300\t300\t300\t60\n")
    write_fasta(pred, {"pred1": 2000, "pred2": 500, "pred3": 300, "unmapped": 100})

    subprocess.run(
        [sys.executable, SCORER,
         "--truth", truth, "--paf", paf, "--pred-fasta", pred,
         "--sample", "SYNTH", "--tool", "demo", "--out", out],
        check=True,
    )

    with open(out) as fh:
        lines = fh.read().strip().splitlines()
    header = lines[0].split("\t")
    row = dict(zip(header, lines[1].split("\t")))

    tp = int(row["TP_bp"]); fp = int(row["FP_bp"]); fn = int(row["FN_bp"])
    prec = float(row["precision"]); rec = float(row["recall"]); f1 = float(row["f1"])

    print("Parsed result row:", row)

    ok = True
    ok &= (tp == 2500);  print(f"  TP  == 2500 ? {tp}  -> {tp==2500}")
    ok &= (fp == 300);   print(f"  FP  == 300  ? {fp}   -> {fp==300}")
    ok &= (fn == 500);   print(f"  FN  == 500  ? {fn}   -> {fn==500}")
    ok &= approx(prec, 0.8929); print(f"  prec ~ 0.8929 ? {prec} -> {approx(prec,0.8929)}")
    ok &= approx(rec, 0.8333);  print(f"  rec  ~ 0.8333 ? {rec} -> {approx(rec,0.8333)}")
    ok &= approx(f1, 0.8621);   print(f"  f1   ~ 0.8621 ? {f1} -> {approx(f1,0.8621)}")
    ok &= (int(row["unmapped_pred_bp"]) == 100)
    print(f"  unmapped prediction == 100 ? {row['unmapped_pred_bp']} -> {int(row['unmapped_pred_bp'])==100}")

    # Second scenario: overlapping predictions must not double-count.
    paf2 = os.path.join(tmp, "pred2.paf")
    pred2 = os.path.join(tmp, "pred2.fasta")
    out2 = os.path.join(tmp, "scores2.tsv")
    with open(paf2, "w") as fh:
        # Two contigs both cover plasmidA 0..2000 and 1000..2000 (overlap).
        fh.write("a\t2000\t0\t2000\t+\tplasmidA\t2000\t0\t2000\t2000\t2000\t60\n")
        fh.write("b\t1000\t0\t1000\t+\tplasmidA\t2000\t1000\t2000\t1000\t1000\t60\n")
    write_fasta(pred2, {"a": 2000, "b": 1000})
    subprocess.run(
        [sys.executable, SCORER, "--truth", truth, "--paf", paf2, "--pred-fasta", pred2,
         "--sample", "SYNTH", "--tool", "overlap", "--out", out2],
        check=True,
    )
    with open(out2) as fh:
        r2 = dict(zip(header, fh.read().strip().splitlines()[1].split("\t")))
    tp2 = int(r2["TP_bp"])
    ok &= (tp2 == 2000)
    print(f"  overlap TP == 2000 (no double count) ? {tp2} -> {tp2==2000}")

    # Third scenario: empty prediction file -> all FN, zero precision/recall.
    empty = os.path.join(tmp, "empty.paf")
    empty_pred = os.path.join(tmp, "empty.fasta")
    open(empty, "w").close()
    write_fasta(empty_pred, {})
    out3 = os.path.join(tmp, "scores3.tsv")
    subprocess.run(
        [sys.executable, SCORER, "--truth", truth, "--paf", empty, "--pred-fasta", empty_pred,
         "--sample", "SYNTH", "--tool", "nullpred", "--out", out3],
        check=True,
    )
    with open(out3) as fh:
        r3 = dict(zip(header, fh.read().strip().splitlines()[1].split("\t")))
    ok &= (int(r3["TP_bp"]) == 0 and int(r3["FN_bp"]) == 3000 and float(r3["f1"]) == 0.0)
    print(f"  empty pred -> TP=0 FN=3000 f1=0 ? "
          f"{r3['TP_bp']},{r3['FN_bp']},{r3['f1']} -> "
          f"{int(r3['TP_bp'])==0 and int(r3['FN_bp'])==3000 and float(r3['f1'])==0.0}")

    print("\nALL TESTS PASSED" if ok else "\nTESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
