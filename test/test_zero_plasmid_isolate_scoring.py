#!/usr/bin/env python3
"""
test_zero_plasmid_isolate_scoring.py -- a genuinely zero-true-plasmid isolate
(an all-chromosome truth table) is a negative control: it is the only kind of
sample that can directly measure a tool's false-positive plasmid-calling
behaviour, since precision/recall/f1 are all undefined when there is no true
plasmid to recall (see score_plasmids.py). Confirms:

  1. A tool that correctly predicts nothing gets undefined precision/recall/f1
     ("", never a misleading 0.0), perfect isolate_specificity (1.0), and zero
     false-positive counters -- distinguishing it from real failure.
  2. A tool that wrongly calls chromosome sequence "plasmid" on this same
     isolate gets a real, defined precision (0.0 -- something was predicted,
     none of it correct) while recall/f1 stay undefined (no true plasmid
     exists to recall at all); isolate_specificity dropping below 1.0 and
     the chromosome_fp_bp/fp_predicted_record_count counters confirm and
     quantify exactly what went wrong, beyond what precision alone shows.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCORER = os.path.join(HERE, "..", "python", "score_plasmids.py")


def approx(a, b, tol=1e-4):
    return abs(a - b) <= tol


def write_fasta(path, records):
    with open(path, "w") as fh:
        for name, length in records.items():
            fh.write(f">{name}\n")
            fh.write("A" * length + "\n")


def run_scorer(truth, paf, pred_fasta, tool, out):
    subprocess.run(
        [sys.executable, SCORER, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
         "--sample", "NEG_CONTROL", "--tool", tool, "--out", out],
        check=True,
    )
    # .splitlines() alone, never .strip() first: score_plasmids.py can
    # legitimately write an empty final column (e.g. no --circular-plasmids
    # given), and str.strip() on the whole file would silently swallow that
    # trailing tab-delimited empty field along with the newline, corrupting
    # the last column's parse -- see test_scoring.py's own fix for the same bug.
    with open(out) as fh:
        lines = fh.read().splitlines()
    return dict(zip(lines[0].split("\t"), lines[1].split("\t")))


def main():
    tmp = tempfile.mkdtemp(prefix="zero_plasmid_test_")
    truth = os.path.join(tmp, "truth.tsv")
    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\n")
        fh.write("chromosome\tCHROMOSOME\t100000\n")
    ok = True

    # --- Scenario 1: tool correctly predicts nothing on an all-chromosome isolate. ---
    empty_paf = os.path.join(tmp, "empty.paf")
    empty_pred = os.path.join(tmp, "empty.fasta")
    open(empty_paf, "w").close()
    write_fasta(empty_pred, {})
    good = run_scorer(truth, empty_paf, empty_pred, "good", os.path.join(tmp, "good.tsv"))

    ok &= (good["precision"] == "" and good["recall"] == "" and good["f1"] == "")
    print(f"  correct abstention -> precision/recall/f1 undefined ? "
          f"{good['precision']!r},{good['recall']!r},{good['f1']!r} -> "
          f"{good['precision']=='' and good['recall']=='' and good['f1']==''}")

    ok &= approx(float(good["isolate_specificity"]), 1.0)
    print(f"  correct abstention -> isolate_specificity == 1.0 ? "
          f"{good['isolate_specificity']} -> {approx(float(good['isolate_specificity']), 1.0)}")

    ok &= (int(good["chromosome_fp_bp"]) == 0 and int(good["fp_predicted_record_count"]) == 0)
    print(f"  correct abstention -> zero FP bp and zero FP records ? "
          f"{good['chromosome_fp_bp']},{good['fp_predicted_record_count']} -> "
          f"{int(good['chromosome_fp_bp'])==0 and int(good['fp_predicted_record_count'])==0}")

    # --- Scenario 2: tool wrongly calls 5000bp of the chromosome "plasmid". ---
    bad_paf = os.path.join(tmp, "bad.paf")
    bad_pred = os.path.join(tmp, "bad.fasta")
    with open(bad_paf, "w") as fh:
        fh.write("badcontig\t5000\t0\t5000\t+\tchromosome\t100000\t0\t5000\t5000\t5000\t60\n")
    write_fasta(bad_pred, {"badcontig": 5000})
    bad = run_scorer(truth, bad_paf, bad_pred, "leaky", os.path.join(tmp, "bad.tsv"))

    # Unlike scenario 1, precision IS now defined here: something was
    # predicted (tp+fp > 0), so "of what was predicted, how much was
    # correct" is a real question with a real answer -- 0.0, since every
    # predicted base landed on chromosome. recall/f1 remain undefined: there
    # is still no true plasmid on this isolate to recall at all. This means
    # precision alone already distinguishes "correctly abstained" (undefined)
    # from "wrongly predicted" (a real 0.0) -- the negative-control fields
    # below make that distinction even more directly, with real counts.
    ok &= (bad["precision"] == "0.0000" and bad["recall"] == "" and bad["f1"] == "")
    print(f"  wrong prediction -> precision=0.0000 (defined), recall/f1 still undefined ? "
          f"{bad['precision']!r},{bad['recall']!r},{bad['f1']!r} -> "
          f"{bad['precision']=='0.0000' and bad['recall']=='' and bad['f1']==''}")

    expected_specificity = (100000 - 5000) / 100000
    ok &= approx(float(bad["isolate_specificity"]), expected_specificity)
    print(f"  wrong prediction -> isolate_specificity == {expected_specificity} ? "
          f"{bad['isolate_specificity']} -> {approx(float(bad['isolate_specificity']), expected_specificity)}")

    ok &= (int(bad["chromosome_fp_bp"]) == 5000 and int(bad["fp_predicted_record_count"]) == 1)
    print(f"  wrong prediction -> chromosome_fp_bp=5000, fp_predicted_record_count=1 ? "
          f"{bad['chromosome_fp_bp']},{bad['fp_predicted_record_count']} -> "
          f"{int(bad['chromosome_fp_bp'])==5000 and int(bad['fp_predicted_record_count'])==1}")

    # Both scenarios share undefined recall/f1 (no true plasmid on this
    # isolate at all) -- specificity and the FP counters are what
    # additionally confirm scenario 2 was worse than scenario 1, beyond what
    # precision's 0.0 already implies.
    ok &= (good["recall"] == bad["recall"] == "" and
           float(good["isolate_specificity"]) > float(bad["isolate_specificity"]))
    print("  specificity confirms scenario 2 is worse than scenario 1 -> "
          f"{float(good['isolate_specificity'])} > {float(bad['isolate_specificity'])} -> "
          f"{float(good['isolate_specificity']) > float(bad['isolate_specificity'])}")

    print("\nALL ZERO-PLASMID ISOLATE SCORING TESTS PASSED" if ok else "\nTESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
