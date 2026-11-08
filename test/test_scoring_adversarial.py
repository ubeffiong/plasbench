#!/usr/bin/env python3
"""
test_scoring_adversarial.py -- hand-computed scoring behaviour on the inputs a
benchmark is most likely to get wrong. No minimap2 or downloaded data needed.

Reference (truth):
    chromosome 10,000 bp CHROMOSOME
    plasmidA    2,000 bp PLASMID
    plasmidB    1,000 bp PLASMID        (3,000 bp of true plasmid)

These tests pin down what the scorer DOES today, including the documented
optimism of precision (bases with no retained alignment are never false
positives), so a later change to that behaviour is a visible, deliberate one.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCORER = os.path.join(HERE, "..", "python", "score_plasmids.py")

TRUTH = [("chromosome", "CHROMOSOME", 10000), ("plasmidA", "PLASMID", 2000), ("plasmidB", "PLASMID", 1000)]


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def paf(qname, qlen, qs, qe, tname, tlen, ts, te, mapq=60, tag=""):
    ident = min(qe - qs, te - ts)
    row = f"{qname}\t{qlen}\t{qs}\t{qe}\t+\t{tname}\t{tlen}\t{ts}\t{te}\t{ident}\t{ident}\t{mapq}"
    return row + (f"\t{tag}" if tag else "") + "\n"


def score(tmp, name, pred_records, paf_text, *extra):
    truth = os.path.join(tmp, f"{name}.truth.tsv")
    paf_path = os.path.join(tmp, f"{name}.paf")
    pred = os.path.join(tmp, f"{name}.fasta")
    out = os.path.join(tmp, f"{name}.scores.tsv")
    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\n")
        for sid, mol, length in TRUTH:
            fh.write(f"{sid}\t{mol}\t{length}\n")
    with open(paf_path, "w") as fh:
        fh.write(paf_text)
    with open(pred, "w") as fh:
        for rid, length in pred_records.items():
            fh.write(f">{rid}\n{'A' * length}\n")
    result = subprocess.run(
        [sys.executable, SCORER, "--truth", truth, "--paf", paf_path, "--pred-fasta", pred,
         "--sample", "SYNTH", "--tool", name, "--out", out, *extra],
        check=True, capture_output=True, text=True)
    with open(out) as fh:
        lines = fh.read().splitlines()
    return dict(zip(lines[0].split("\t"), lines[1].split("\t"))), result.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="score_adv_")
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    # 1. Chimeric contig: first 2000 bp is plasmidA, last 500 bp is chromosome.
    #    Both pieces are primary placements and both must be counted.
    row, _ = score(tmp, "chimeric", {"chim": 2500},
                   paf("chim", 2500, 0, 2000, "plasmidA", 2000, 0, 2000)
                   + paf("chim", 2500, 2000, 2500, "chromosome", 10000, 4000, 4500))
    print("chimeric contig (plasmid + chromosome in one record)")
    check("TP == 2000", int(row["TP_bp"]) == 2000)
    check("FP == 500 (chromosome part is charged)", int(row["FP_bp"]) == 500)
    check("FN == 1000 (plasmidB never covered)", int(row["FN_bp"]) == 1000)
    check("precision == 0.8", approx(float(row["precision"]), 0.8))
    check("recall == 0.6667", approx(float(row["recall"]), 2000 / 3000))

    # 2. Repeat shared by plasmidA and the chromosome, placed at MAPQ 0, plus one
    #    clean contig. With the pipeline's MAPQ >= 20 filter the repeat contig is
    #    dropped, so precision is NOT reduced; strict_precision exposes it.
    repeat_paf = (paf("good", 2000, 0, 2000, "plasmidA", 2000, 0, 2000, mapq=60)
                  + paf("rep", 800, 0, 800, "plasmidA", 2000, 0, 800, mapq=0)
                  + paf("rep", 800, 0, 800, "chromosome", 10000, 100, 900, mapq=0))
    row, _ = score(tmp, "repeat_filtered", {"good": 2000, "rep": 800}, repeat_paf,
                   "--min-alignment-mapq", "20")
    print("repeat shared with chromosome, MAPQ filter 20 (pipeline default)")
    check("FP == 0 (filtered repeat is not a false positive)", int(row["FP_bp"]) == 0)
    check("unmapped_pred_bp == 800 (it is reported here instead)", int(row["unmapped_pred_bp"]) == 800)
    check("precision == 1.0 (optimistic by design)", approx(float(row["precision"]), 1.0))
    check("strict_precision == 2000/2800", approx(float(row["strict_precision"]), 2000 / 2800))
    row, _ = score(tmp, "repeat_unfiltered", {"good": 2000, "rep": 800}, repeat_paf,
                   "--min-alignment-mapq", "0")
    print("same repeat with MAPQ filter 0")
    check("FP == 800 (the chromosome placement is now charged)", int(row["FP_bp"]) == 800)
    check("precision == 2000/2800", approx(float(row["precision"]), 2000 / 2800))

    # 3. Multimer: two tandem copies of plasmidA in one 4000 bp record. Coverage is
    #    merged, so the second copy earns no TP and costs nothing, but is reported.
    row, _ = score(tmp, "multimer", {"dimer": 4000},
                   paf("dimer", 4000, 0, 2000, "plasmidA", 2000, 0, 2000)
                   + paf("dimer", 4000, 2000, 4000, "plasmidA", 2000, 0, 2000))
    print("multimer (two tandem copies of plasmidA)")
    check("TP == 2000 (no double credit)", int(row["TP_bp"]) == 2000)
    check("FP == 0 (no penalty either)", int(row["FP_bp"]) == 0)
    check("redundant_pred_bp == 2000 (the only trace)", int(row["redundant_pred_bp"]) == 2000)

    # 4. Truncated plasmids: plasmidA 85% covered, plasmidB 100% covered.
    row, _ = score(tmp, "truncated", {"a": 1700, "b": 1000},
                   paf("a", 1700, 0, 1700, "plasmidA", 2000, 0, 1700)
                   + paf("b", 1000, 0, 1000, "plasmidB", 1000, 0, 1000))
    print("truncated plasmid (85% of plasmidA)")
    check("recovered at the 0.90 threshold == 1 of 2", int(row["recovered_plasmid_count"]) == 1)
    check(">=50% band counts both", int(row["recovered_plasmid_count_ge50"]) == 2)
    check(">=90% band counts only plasmidB", int(row["recovered_plasmid_count_ge90"]) == 1)
    check("base recall still high (2700/3000)", approx(float(row["recall"]), 0.9))

    # 5. A secondary row handed to the scorer must not claim chromosome bases.
    row, err = score(tmp, "secondary", {"s": 2000},
                     paf("s", 2000, 0, 2000, "plasmidA", 2000, 0, 2000, tag="tp:A:P")
                     + paf("s", 2000, 0, 500, "chromosome", 10000, 0, 500, mapq=60, tag="tp:A:S"))
    print("secondary alignment row (tp:A:S) in the PAF")
    check("FP == 0 (secondary row ignored)", int(row["FP_bp"]) == 0)
    check("TP == 2000", int(row["TP_bp"]) == 2000)
    check("a warning names the ignored row", "secondary" in err and "tp:A:S" in err)

    # 6. Primary rows with tags still count (guards against over-filtering).
    row, _ = score(tmp, "tagged_primary", {"p": 2000},
                   paf("p", 2000, 0, 2000, "plasmidA", 2000, 0, 2000, tag="tp:A:P"))
    print("primary row with a tp:A:P tag")
    check("TP == 2000", int(row["TP_bp"]) == 2000)

    print()
    if not ok:
        print("SCORING ADVERSARIAL TESTS FAILED")
        sys.exit(1)
    print("ALL SCORING ADVERSARIAL TESTS PASSED")


if __name__ == "__main__":
    main()
