#!/usr/bin/env python3
"""Independent second scorer for the contig layer (python/contig_crosscheck.py).

Synthetic isolate: chromosome 60 kb, plasmid pA 12 kb. A shared 3 kb IS-like
segment sits in both. Contigs (cut from the reference, so exact):
  c_chr1, c_chr2   chromosome pieces (8 kb, 6 kb)        -> CHROMOSOME
  c_pA1, c_pA2     plasmid pieces (5 kb, 4 kb)           -> PLASMID
  c_is             the shared segment (3 kb)             -> AMBIGUOUS
  c_short          500 bp of plasmid                     -> SHORT
  c_junk           random 2 kb                           -> UNPLACED
The minimap2-based labeller (contig_classification.py label, fed an exact PAF of
those cut positions) and the k-mer labeller must agree on every contig, and both
scorers must give the same length-weighted F1/MCC for a tool calling c_pA1, c_pA2
and c_chr2 (TP 9000, FP 6000, FN 0, TN 8000: F1 = 0.75, MCC = 72e6 / sqrt(15000*9000*14000*8000) = 0.5855). A planted
labelling error in the primary labels must show up as "disagree".
"""
import csv
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XC = ROOT / "python" / "contig_crosscheck.py"
CC = ROOT / "python" / "contig_classification.py"


def rand(n, rng):
    return "".join(rng.choice("ACGT") for _ in range(n))


def rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    rng = random.Random(11)
    shared = rand(3000, rng)
    chrom = rand(20000, rng) + shared + rand(37000, rng)
    plasmid = rand(5000, rng) + rand(4000, rng) + shared
    contigs = {"c_chr1": (chrom, 0, 8000), "c_chr2": (chrom, 30000, 36000), "c_pA1": (plasmid, 0, 5000),
               "c_pA2": (plasmid, 5000, 9000), "c_is": (plasmid, 9000, 12000), "c_short": (plasmid, 1000, 1500)}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        data, results = tmp / "data" / "S1", tmp / "results" / "S1"
        data.mkdir(parents=True)
        results.mkdir(parents=True)
        (data / "reference.fna").write_text(f">chr\n{chrom}\n>pA\n{plasmid}\n")
        (data / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t60000\npA\tPLASMID\t12000\n")
        fasta = "".join(f">{name}\n{seq[a:b]}\n" for name, (seq, a, b) in contigs.items())
        fasta += f">c_junk\n{rand(2000, rng)}\n"
        (data / "contigs.fasta").write_text(fasta)
        paf = []
        for name, (seq, a, b) in contigs.items():
            target, tlen = ("chr", 60000) if seq is chrom else ("pA", 12000)
            n = b - a
            paf.append(f"{name}\t{n}\t0\t{n}\t+\t{target}\t{tlen}\t{a}\t{b}\t{n}\t{n}\t60")
        paf.append("c_is\t3000\t0\t3000\t+\tchr\t60000\t20000\t23000\t3000\t3000\t0")
        (data / "contigs_vs_ref.paf").write_text("\n".join(paf) + "\n")
        subprocess.run([sys.executable, str(CC), "label", "--contigs", str(data / "contigs.fasta"), "--paf",
                        str(data / "contigs_vs_ref.paf"), "--truth", str(data / "truth.tsv"), "--labels-out",
                        str(data / "contig_labels.tsv"), "--coverage-out", str(data / "cov.tsv")],
                       check=True, capture_output=True)
        subprocess.run([sys.executable, str(XC), "label", "--contigs", str(data / "contigs.fasta"), "--reference",
                        str(data / "reference.fna"), "--truth", str(data / "truth.tsv"), "--out",
                        str(data / "contig_labels.kmer.tsv"), "--scaled", "4"], check=True, capture_output=True)
        primary = {r["contig"]: r["label"] for r in rows(data / "contig_labels.tsv")}
        independent = {r["contig"]: r["label"] for r in rows(data / "contig_labels.kmer.tsv")}
        expected = {"c_chr1": "CHROMOSOME", "c_chr2": "CHROMOSOME", "c_pA1": "PLASMID", "c_pA2": "PLASMID",
                    "c_is": "AMBIGUOUS", "c_short": "SHORT", "c_junk": "UNPLACED"}
        assert independent == expected, independent
        assert primary == expected, primary
        print("  PASS: alignment-free labels match the minimap2 labels on every category")

        (results / "pred_toolA.plasmid.fasta").write_text(">c_pA1\nA\n>c_pA2\nA\n>c_chr2\nA\n")
        out = tmp / "xc.tsv"
        subprocess.run([sys.executable, str(XC), "compare", "--results-dir", str(tmp / "results"), "--data-dir",
                        str(tmp / "data"), "--out", str(out)], check=True, capture_output=True)
        row = rows(out)[0]
        assert row["status"] == "agree" and row["label_agreement"] == "1.0000" and row["label_kappa"] == "1.0000", row
        assert row["primary_f1_bp"] == row["independent_f1_bp"] == "0.7500", row
        assert row["primary_mcc_bp"] == "0.5855", row
        print("  PASS: both scorers give F1 0.75 and MCC 0.5855 for the same calls (status agree)")

        labels = rows(data / "contig_labels.tsv")
        for r in labels:
            if r["contig"] == "c_chr2":
                r["label"] = "PLASMID"  # planted error in the primary scorer
        with open(data / "contig_labels.tsv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(labels[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(labels)
        subprocess.run([sys.executable, str(XC), "compare", "--results-dir", str(tmp / "results"), "--data-dir",
                        str(tmp / "data"), "--out", str(out)], check=True, capture_output=True)
        row = rows(out)[0]
        assert row["status"] == "disagree" and "c_chr2" in row["differing_contigs"], row
        print("  PASS: a planted labelling error in the primary scorer is caught as a disagreement")

        (data / "contigs.fasta").write_text(fasta + ">c_repeat\n" + "ACGT" * 1000 + "\n")
        subprocess.run([sys.executable, str(XC), "label", "--contigs", str(data / "contigs.fasta"), "--reference",
                        str(data / "reference.fna"), "--truth", str(data / "truth.tsv"), "--out",
                        str(data / "contig_labels.kmer.tsv"), "--scaled", "4"], check=True, capture_output=True)
        low = {r["contig"]: r["label"] for r in rows(data / "contig_labels.kmer.tsv")}["c_repeat"]
        assert low == "LOW_INFORMATION", low
        print("  PASS: a 4 kb tandem repeat has too few distinct k-mers -> LOW_INFORMATION, not UNPLACED")
    print("ALL CONTIG CROSS-CHECK TESTS PASSED")


if __name__ == "__main__":
    main()
