#!/usr/bin/env python3
"""Base-level MCC, F2, F0.5 and abstention (python/score_plasmids.py).

Hand calculation for the fixture (reference: 1000 bp chromosome, 200 bp plasmid;
prediction covers plasmid 0-150 and chromosome 0-50):
  TP=150, FP=50, FN=50, TN=950
  precision = 0.75, recall = 0.75
  MCC = (150*950 - 50*50) / sqrt(200*200*1000*1000) = 140000/200000 = 0.70
  F2  = 5*0.75*0.75 / (4*0.75 + 0.75) = 0.75 ; F0.5 = 0.75 (P = R)
A tool that predicts nothing: F1 = 0, MCC undefined (blank), abstention_rate 1.
A plasmid-free isolate: MCC blank, never 0. --min-contig-length drops short records.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "score_plasmids.py"
sys.path.insert(0, str(ROOT / "python"))
import score_plasmids as sp  # noqa: E402


def run(tmp, truth, paf, fasta, extra=()):
    out = Path(tmp) / "scores.tsv"
    if out.exists():
        out.unlink()
    subprocess.run([sys.executable, str(SCRIPT), "--truth", str(truth), "--paf", str(paf), "--pred-fasta", str(fasta),
                    "--sample", "S", "--tool", "t", "--out", str(out), *extra], check=True, capture_output=True)
    with open(out, newline="") as handle:
        return next(csv.DictReader(handle, delimiter="\t"))


def main():
    assert abs(sp.mcc_from_counts(150, 50, 50, 950) - 0.70) < 1e-12
    assert sp.mcc_from_counts(0, 0, 10, 0) is None
    assert abs(sp.f_beta(0.5, 1.0, 2.0) - (5 * 0.5 / (4 * 0.5 + 1.0))) < 1e-12
    assert sp.f_beta(None, 0.0, 2.0) == 0.0 and sp.f_beta(0.5, None, 2.0) is None
    print("  PASS: mcc_from_counts / f_beta match hand values and undefined rules")
    with tempfile.TemporaryDirectory() as tmp:
        truth = Path(tmp) / "truth.tsv"
        truth.write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t1000\np\tPLASMID\t200\n")
        fasta = Path(tmp) / "pred.fasta"
        fasta.write_text(">a\n" + "A" * 150 + "\n>b\n" + "C" * 50 + "\n")
        paf = Path(tmp) / "pred.paf"
        paf.write_text("a\t150\t0\t150\t+\tp\t200\t0\t150\t150\t150\t60\n"
                       "b\t50\t0\t50\t+\tchr\t1000\t0\t50\t50\t50\t60\n")
        row = run(tmp, truth, paf, fasta)
        assert row["TN_bp"] == "950" and row["mcc"] == "0.7000", row
        assert row["f2"] == "0.7500" and row["f0_5"] == "0.7500" and row["abstention_rate"] == "0.0"
        print("  PASS: MCC 0.70, F2 = F0.5 = 0.75, abstention 0 on the hand-computed fixture")

        row = run(tmp, truth, paf, fasta, ("--min-contig-length", "100"))
        assert row["FP_bp"] == "0" and row["precision"] == "1.0000", row
        print("  PASS: --min-contig-length 100 drops the 50 bp record (no chromosome false positive)")

        empty = Path(tmp) / "empty.fasta"
        empty.write_text("")
        empty_paf = Path(tmp) / "empty.paf"
        empty_paf.write_text("")
        row = run(tmp, truth, empty_paf, empty)
        assert row["f1"] == "0.0000" and row["mcc"] == "" and row["abstention_rate"] == "1.0", row
        print("  PASS: no prediction -> F1 0, MCC blank (undefined), abstention 1")

        free = Path(tmp) / "free.tsv"
        free.write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t1000\n")
        chr_paf = Path(tmp) / "chr.paf"
        chr_paf.write_text("b\t50\t0\t50\t+\tchr\t1000\t0\t50\t50\t50\t60\n")
        only_b = Path(tmp) / "b.fasta"
        only_b.write_text(">b\n" + "C" * 50 + "\n")
        row = run(tmp, free, chr_paf, only_b)
        assert row["mcc"] == "" and row["f2"] == "" and row["f1"] == "", row
        print("  PASS: plasmid-free isolate -> MCC/F2/F1 blank, never 0")
    print("ALL MCC/ABSTENTION TESTS PASSED")


if __name__ == "__main__":
    main()
