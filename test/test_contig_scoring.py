#!/usr/bin/env python3
"""Contig layer additions (contig_classification.py score --bins): excluded-category
lengths and contig-level length-weighted binning F1.

Hand calculation. Labels: c1 PLASMID pA 4 kb, c2 PLASMID pA 2 kb, c3 PLASMID pB 3 kb,
c4 CHROMOSOME 10 kb, c5 AMBIGUOUS 1.5 kb, c6 UNPLACED 1.2 kb.
Prediction calls c1, c2, c3 and c4 plasmid; bins: b1 = {c1, c3}, b2 = {c2, c4}.
  overlaps: (b1,pA)=4000, (b1,pB)=3000, (b2,pA)=2000; mapped b1=7000, b2=12000
  one-to-one best: b1-pA 4000 + b2 none for pB... Hungarian maximises 4000 + 0
  vs (b1-pB 3000 + b2-pA 2000 = 5000) -> 5000 correct bp
  precision = 5000 / 19000 = 0.2632, recall = 5000 / 9000 = 0.5556
  F1 = 2PR/(P+R) = 0.3571
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "contig_classification.py"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "labels.tsv").write_text(
            "contig\tlength\tlabel\tplasmid_fraction\tchromosome_fraction\tbest_plasmid\treason\n"
            "c1\t4000\tPLASMID\t1\t0\tpA\t\nc2\t2000\tPLASMID\t1\t0\tpA\t\nc3\t3000\tPLASMID\t1\t0\tpB\t\n"
            "c4\t10000\tCHROMOSOME\t0\t1\t\t\nc5\t1500\tAMBIGUOUS\t1\t1\t\t\nc6\t1200\tUNPLACED\t0\t0\t\t\n")
        (tmp / "pred.fasta").write_text(">c1\nA\n>c2\nA\n>c3\nA\n>c4\nA\n")
        (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nc1\tb1\nc3\tb1\nc2\tb2\nc4\tb2\n")
        subprocess.run([sys.executable, str(SCRIPT), "score", "--labels", str(tmp / "labels.tsv"),
                        "--pred-fasta", str(tmp / "pred.fasta"), "--bins", str(tmp / "bins.tsv"),
                        "--out", str(tmp / "out.tsv")], check=True)
        with open(tmp / "out.tsv", newline="") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["contigs_ambiguous_bp"] == "1500" and row["contigs_unplaced_bp"] == "1200", row
        assert row["contig_bin_precision_bp"] == "0.2632" and row["contig_bin_recall_bp"] == "0.5556", row
        assert row["contig_bin_f1_bp"] == "0.3571", row
        assert row["contig_tp_bp"] == "9000" and row["contig_fp_bp"] == "10000", row
        print("  PASS: shared/unassigned lengths reported; contig-level binning P/R/F1 match the hand values")

        subprocess.run([sys.executable, str(SCRIPT), "score", "--labels", str(tmp / "labels.tsv"),
                        "--pred-fasta", str(tmp / "pred.fasta"), "--out", str(tmp / "nobins.tsv")], check=True)
        with open(tmp / "nobins.tsv", newline="") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["contig_bin_f1_bp"] == "" and row["contig_f1_bp"] != ""
        print("  PASS: without --bins the binning columns are blank, classification still scored")
    print("ALL CONTIG SCORING TESTS PASSED")


if __name__ == "__main__":
    main()
