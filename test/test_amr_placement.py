#!/usr/bin/env python3
"""AMR placement (python/score_amr_placement.py).

Truth: pA (5 kb, IncX3) and pB (5 kb, IncFII). Gene copies: blaKPC-2 pA:100-900,
blaCTX-M-15 pB:100-900, mcr-1 pA:2000-2800, blaTEM-1 pB:3000-3800, blaNDM-1 pA:4500-4600
(4500-4600 is covered, so it is recovered; a sixth copy on pB:4500-4900 is not covered).
Records: r1 = pA 0-5000 (bin b1), r2 = pB 0-2000 (bin b2, contig label AMBIGUOUS),
r3 = pB 2900-4000 (bin b1, misbinned).
Matching (max weight): b1-pA (5000 bp), b2-pB (2000 bp).
  blaKPC-2   r1 -> b1 -> pA   correct_plasmid     carbapenemase
  blaCTX-M   r2 AMBIGUOUS     shared_contig       ESBL
  mcr-1      r1 -> pA         correct_plasmid     colistin
  blaTEM-1   r3 -> b1 -> pA   wrong_plasmid       beta_lactamase, replicon no
  blaNDM-1   r1 -> pA         correct_plasmid     carbapenemase
  blaOXA-48  pB:4500-4900     not_recovered       carbapenemase
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "score_amr_placement.py"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\n"
                                       "pA\tPLASMID\t5000\npB\tPLASMID\t5000\n")
        (tmp / "amr.tsv").write_text(
            "sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\n"
            "pA\t100\t900\tblaKPC-2\tg1\tc1\tcard\t1\npB\t100\t900\tblaCTX-M-15\tg2\tc2\tcard\t1\n"
            "pA\t2000\t2800\tmcr-1\tg3\tc3\tcard\t1\npB\t3000\t3800\tblaTEM-1\tg4\tc4\tcard\t1\n"
            "pA\t4500\t4600\tblaNDM-1\tg5\tc5\tcard\t1\npB\t4500\t4900\tblaOXA-48\tg6\tc6\tcard\t1\n")
        (tmp / "pred.fasta").write_text(">r1\n" + "A" * 5000 + "\n>r2\n" + "A" * 2000 + "\n>r3\n" + "A" * 1100 + "\n")
        (tmp / "pred.paf").write_text("r1\t5000\t0\t5000\t+\tpA\t5000\t0\t5000\t5000\t5000\t60\n"
                                      "r2\t2000\t0\t2000\t+\tpB\t5000\t0\t2000\t2000\t2000\t60\n"
                                      "r3\t1100\t0\t1100\t+\tpB\t5000\t2900\t4000\t1100\t1100\t60\n")
        (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nr1\tb1\nr2\tb2\nr3\tb1\n")
        (tmp / "labels.tsv").write_text("contig\tlength\tlabel\tplasmid_fraction\tchromosome_fraction\tbest_plasmid\treason\n"
                                        "r1\t5000\tPLASMID\t1\t0\tpA\t\nr2\t2000\tAMBIGUOUS\t1\t1\tpB\t\n"
                                        "r3\t1100\tPLASMID\t1\t0\tpB\t\n")
        (tmp / "features.tsv").write_text("sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
                                          "pA\t0\t5000\treplicon\tIncX3\tmob\t1\npB\t0\t5000\treplicon\tIncFII\tmob\t1\n")
        results = tmp / "results" / "S1"
        results.mkdir(parents=True)
        subprocess.run([sys.executable, str(SCRIPT), "score", "--sample", "S1", "--tool", "t", "--truth",
                        str(tmp / "truth.tsv"), "--amr-truth", str(tmp / "amr.tsv"), "--paf", str(tmp / "pred.paf"),
                        "--pred-fasta", str(tmp / "pred.fasta"), "--bins", str(tmp / "bins.tsv"),
                        "--contig-labels", str(tmp / "labels.tsv"), "--features", str(tmp / "features.tsv"),
                        "--out", str(results / "t.amr_placement.tsv")], check=True, capture_output=True)
        with open(results / "t.amr_placement.tsv", newline="") as handle:
            genes = {r["gene_name"]: r for r in csv.DictReader(handle, delimiter="\t")}
        expected = {"blaKPC-2": "correct_plasmid", "blaCTX-M-15": "shared_contig", "mcr-1": "correct_plasmid",
                    "blaTEM-1": "wrong_plasmid", "blaNDM-1": "correct_plasmid", "blaOXA-48": "not_recovered"}
        assert {g: r["placement"] for g, r in genes.items()} == expected, genes
        assert genes["blaTEM-1"]["replicon_type_correct"] == "no" and genes["blaKPC-2"]["replicon_type_correct"] == "yes"
        assert genes["blaKPC-2"]["gene_class"] == "carbapenemase" and genes["blaCTX-M-15"]["gene_class"] == "ESBL"
        assert genes["mcr-1"]["gene_class"] == "colistin" and genes["blaOXA-48"]["gene_class"] == "carbapenemase"
        print("  PASS: per-copy placement (correct / wrong / shared / not recovered), replicon level and gene class")

        subprocess.run([sys.executable, str(SCRIPT), "collect", "--results-dir", str(tmp / "results"),
                        "--out", str(tmp / "summary.tsv")], check=True, capture_output=True)
        with open(tmp / "summary.tsv", newline="") as handle:
            summary = {r["gene_class"]: r for r in csv.DictReader(handle, delimiter="\t")}
        assert summary["all"]["n_gene_copies"] == "6" and summary["all"]["n_correct_plasmid"] == "3"
        assert summary["all"]["correct_plasmid_rate"] == "0.5000" and summary["all"]["n_shared_contig"] == "1"
        assert summary["carbapenemase"]["n_gene_copies"] == "3" and summary["carbapenemase"]["correct_plasmid_rate"] == "0.6667"
        print("  PASS: collect -> per gene class (carbapenemase 2/3 placed correctly, overall 3/6)")

    # Second review, section 7: a tool that does not bin may rightly spread one plasmid over several contigs. One plasmid, two AMR genes
    # far apart, two contigs each carrying one gene and both aligning to that plasmid, plus a mostly-chromosomal contig carrying a third copy.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\npA\tPLASMID\t10000\n")
        (tmp / "amr.tsv").write_text(
            "sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\n"
            "pA\t1000\t1800\tblaKPC-2\tg1\tc1\tcard\t1\npA\t7000\t7800\tblaCTX-M-15\tg2\tc2\tcard\t1\n"
            "pA\t8500\t8900\tmcr-1\tg3\tc3\tcard\t1\n")
        (tmp / "pred.fasta").write_text(">k1\n" + "A" * 3000 + "\n>k2\n" + "A" * 2000 + "\n>k3\n" + "A" * 6000 + "\n")
        # k3 covers mcr-1 on pA (400 bp) but aligns mostly to the chromosome (5600 bp): attributed to the chromosome
        (tmp / "pred.paf").write_text("k1\t3000\t0\t3000\t+\tpA\t10000\t0\t3000\t3000\t3000\t60\n"
                                      "k2\t2000\t0\t2000\t+\tpA\t10000\t6000\t8000\t2000\t2000\t60\n"
                                      "k3\t6000\t0\t400\t+\tpA\t10000\t8500\t8900\t400\t400\t60\n"
                                      "k3\t6000\t400\t6000\t+\tchr\t20000\t0\t5600\t5600\t5600\t60\n")
        (tmp / "cprr.tsv").write_text("true_plasmid\tcorrect\tcorrect_without_identity\npA\tyes\tyes\n")
        results = tmp / "results" / "S1"
        results.mkdir(parents=True)

        def score(tool, *extra):
            done = subprocess.run([sys.executable, str(SCRIPT), "score", "--sample", "S1", "--tool", tool, "--truth", str(tmp / "truth.tsv"),
                                   "--amr-truth", str(tmp / "amr.tsv"), "--paf", str(tmp / "pred.paf"), "--pred-fasta", str(tmp / "pred.fasta"),
                                   "--cprr", str(tmp / "cprr.tsv"), *extra, "--out", str(results / f"{tool}.amr_placement.tsv")],
                                  check=True, capture_output=True, text=True)
            with open(results / f"{tool}.amr_placement.tsv", newline="") as handle:
                return {r["gene_name"]: r for r in csv.DictReader(handle, delimiter="\t")}, done.stderr

        genes, log = score("classifier")
        assert genes["blaKPC-2"]["placement"] == "correct_plasmid" and genes["blaCTX-M-15"]["placement"] == "correct_plasmid", genes
        assert {r["attribution_mode"] for r in genes.values()} == {"contig_attribution"}
        assert genes["mcr-1"]["placement"] == "wrong_plasmid" and genes["mcr-1"]["matched_plasmid"] == "chr", genes["mcr-1"]
        assert all(r["assigned_bin"] == "" and r["plasmid_cprr_correct"] == "" for r in genes.values()), genes
        assert "not a reconstructed plasmid" in log, log
        print("  PASS: no bins: both contigs of one plasmid get correct plasmid-sequence attribution (no one-to-one penalty); a mostly-chromosomal contig does not")
        # The same output forced through one-to-one matching (each contig its own bin) loses one of the two: the failure the review found.
        (tmp / "own_bins.tsv").write_text("sequence_id\tbin_id\nk1\tk1\nk2\tk2\nk3\tk3\n")
        forced, _ = score("forced", "--bins", str(tmp / "own_bins.tsv"))
        assert sorted(forced[g]["placement"] for g in ("blaKPC-2", "blaCTX-M-15")) == ["correct_plasmid", "wrong_plasmid"], forced
        print("  PASS: the same contigs as one-to-one bins lose one copy (the old penalty), so a non-binning tool is no longer scored that way")
        (results / "forced.amr_placement.tsv").unlink()
        subprocess.run([sys.executable, str(SCRIPT), "collect", "--results-dir", str(tmp / "results"), "--out", str(tmp / "summary.tsv")],
                       check=True, capture_output=True)
        with open(tmp / "summary.tsv", newline="") as handle:
            overall = next(r for r in csv.DictReader(handle, delimiter="\t") if r["gene_class"] == "all")
        assert overall["attribution_mode"] == "contig_attribution" and overall["amr_prr"] == "" and overall["n_pairs"] == "0", overall
        print("  PASS: AMR-PRR and pairs kept together stay unavailable for a tool that cannot establish a plasmid-level reconstruction")
    print("ALL AMR PLACEMENT TESTS PASSED")


if __name__ == "__main__":
    main()
