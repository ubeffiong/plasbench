#!/usr/bin/env python3
"""AMR placement follows the tool's output type (python/score_amr_placement.py --task).

One truth plasmid pA (6 kb) carries two resistance genes, blaKPC-2 (pA:100-900) and mcr-1 (pA:4000-4800). A tool reports it as two separate predicted records,
r1 (pA 0-2000) and r2 (pA 3500-5000), so each gene sits on its own record.

  classification       many-to-one: both records are attributed to pA, so BOTH genes are correct_plasmid (gene-recovery credit), but a classifier makes no
                       reconstruction claim, so it has no AMR-PRR and no pairs-kept-together figure.
  binning (two bins)   one-to-one: only one bin can be pA; the other is wrong for its gene (the plasmid is fragmented), exactly as before.
  binning (one bin)    both records in one bin: both genes correct.
  sequence_reassembly  many-to-one attribution, like the classifier (its contigs are not bins); reconstruction is still judged by the CPRR.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
SCRIPT = ROOT / "python" / "score_amr_placement.py"
import score_amr_placement as sap  # noqa: E402


def run(tmp, task, bins=None, cprr=None, tag="t"):
    results = tmp / "results" / "S1"
    results.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(SCRIPT), "score", "--sample", "S1", "--tool", tag, "--task", task, "--truth", str(tmp / "truth.tsv"),
           "--amr-truth", str(tmp / "amr.tsv"), "--paf", str(tmp / "pred.paf"), "--pred-fasta", str(tmp / "pred.fasta"),
           "--out", str(results / f"{tag}.amr_placement.tsv")]
    if bins:
        cmd += ["--bins", str(bins)]
    if cprr:
        cmd += ["--cprr", str(cprr)]
    subprocess.run(cmd, check=True, capture_output=True)
    with open(results / f"{tag}.amr_placement.tsv", newline="") as handle:
        return {r["gene_name"]: r for r in csv.DictReader(handle, delimiter="\t")}


def summary(tmp):
    subprocess.run([sys.executable, str(SCRIPT), "collect", "--results-dir", str(tmp / "results"), "--out", str(tmp / "summary.tsv")], check=True, capture_output=True)
    with open(tmp / "summary.tsv", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    # the attribution rule itself, without files
    overlaps = {("r1", "pA"): 1900, ("r2", "pA"): 1500}
    assert sap.attribute_units(overlaps, ["pA"], "classification") == {"r1": "pA", "r2": "pA"}
    assert sap.attribute_units(overlaps, ["pA"], "sequence_reassembly") == {"r1": "pA", "r2": "pA"}
    one = sap.attribute_units(overlaps, ["pA"], "binning_reconstruction")
    assert list(one.values()) == ["pA"] and len(one) == 1, one      # one plasmid goes to one bin
    print("  PASS: attribution rule (classifier and reassembler many-to-one; binner one-to-one)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\npA\tPLASMID\t6000\n")
        (tmp / "amr.tsv").write_text("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\n"
                                     "pA\t100\t900\tblaKPC-2\tg1\tc1\tcard\t1\npA\t4000\t4800\tmcr-1\tg2\tc2\tcard\t1\n")
        (tmp / "pred.fasta").write_text(">r1\n" + "A" * 2000 + "\n>r2\n" + "A" * 1500 + "\n")
        (tmp / "pred.paf").write_text("r1\t2000\t0\t2000\t+\tpA\t6000\t0\t2000\t2000\t2000\t60\n"
                                      "r2\t1500\t0\t1500\t+\tpA\t6000\t3500\t5000\t1500\t1500\t60\n")
        (tmp / "bins_two.tsv").write_text("sequence_id\tbin_id\nr1\tb1\nr2\tb2\n")
        (tmp / "bins_one.tsv").write_text("sequence_id\tbin_id\nr1\tb1\nr2\tb1\n")
        (tmp / "cprr.tsv").write_text("plasmid\tcorrect\nplasmid_correct\tno\n")   # an unrelated stub: the placement does not need it to attribute genes

        cls = run(tmp, "classification", tag="clf")
        assert {g: r["placement"] for g, r in cls.items()} == {"blaKPC-2": "correct_plasmid", "mcr-1": "correct_plasmid"}, cls
        assert {r["attribution"] for r in cls.values()} == {"best_plasmid_per_record"} and {r["evaluation_task"] for r in cls.values()} == {"classification"}
        print("  PASS: a classifier with two contigs of one plasmid gets BOTH resistance genes attributed (gene-recovery credit)")

        two = run(tmp, "binning_reconstruction", bins=tmp / "bins_two.tsv", tag="bin2")
        assert sorted(r["placement"] for r in two.values()) == ["correct_plasmid", "wrong_plasmid"], two
        assert {r["attribution"] for r in two.values()} == {"one_to_one_bin"}
        one_bin = run(tmp, "binning_reconstruction", bins=tmp / "bins_one.tsv", tag="bin1")
        assert {r["placement"] for r in one_bin.values()} == {"correct_plasmid"}, one_bin
        print("  PASS: a binner keeps the one-to-one rule (fragmented plasmid: one bin wrong; one bin: both right)")

        rea = run(tmp, "sequence_reassembly", tag="rea")
        assert {r["placement"] for r in rea.values()} == {"correct_plasmid"} and {r["attribution"] for r in rea.values()} == {"best_plasmid_per_record"}
        print("  PASS: a reassembler's contigs are attributed per record")

        rows = {r["tool"]: r for r in summary(tmp) if r["gene_class"] == "all"}
        assert rows["clf"]["amr_prr"] == "" and rows["clf"]["n_pairs"] == "" and rows["clf"]["colocalisation_rate"] == "", rows["clf"]
        assert rows["clf"]["correct_plasmid_rate"] == "1.0000" and rows["clf"]["evaluation_task"] == "classification", rows["clf"]
        assert rows["bin2"]["evaluation_task"] == "binning_reconstruction" and rows["bin2"]["correct_plasmid_rate"] == "0.5000", rows["bin2"]
        print("  PASS: summary: the classifier has gene recovery 1.0 but no AMR-PRR and no pairs-kept-together; the fragmented binner has 0.5")

    # A shared replicon type is supporting evidence, not proof of the right plasmid (third review): two plasmids carry the same replicon type, the gene is on pA, but its record is
    # in a bin that the matching assigns to pB. The placement is wrong_plasmid although the replicon type agrees.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\npA\tPLASMID\t6000\npB\tPLASMID\t6000\n")
        (tmp / "amr.tsv").write_text("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\npA\t100\t900\tblaKPC-2\tg1\tc1\tcard\t1\n")
        (tmp / "pred.fasta").write_text(">r1\n" + "A" * 1500 + "\n>r2\n" + "A" * 5000 + "\n")
        (tmp / "pred.paf").write_text("r1\t1500\t0\t1500\t+\tpA\t6000\t0\t1500\t1500\t1500\t60\nr2\t5000\t0\t5000\t+\tpB\t6000\t0\t5000\t5000\t5000\t60\n")
        (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nr1\tb1\nr2\tb1\n")
        (tmp / "features.tsv").write_text("sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\npA\t0\t6000\treplicon\tIncX3\tmob\t1\npB\t0\t6000\treplicon\tIncX3\tmob\t1\n")
        results = tmp / "results" / "S1"
        results.mkdir(parents=True)
        subprocess.run([sys.executable, str(SCRIPT), "score", "--sample", "S1", "--tool", "t", "--task", "binning_reconstruction", "--truth", str(tmp / "truth.tsv"), "--amr-truth", str(tmp / "amr.tsv"),
                        "--paf", str(tmp / "pred.paf"), "--pred-fasta", str(tmp / "pred.fasta"), "--bins", str(tmp / "bins.tsv"), "--features", str(tmp / "features.tsv"),
                        "--out", str(results / "t.amr_placement.tsv")], check=True, capture_output=True)
        with open(results / "t.amr_placement.tsv", newline="") as handle:
            gene = next(csv.DictReader(handle, delimiter="\t"))
        assert gene["placement"] == "wrong_plasmid" and gene["matched_plasmid"] == "pB", gene
        assert gene["replicon_type_correct"] == "yes", gene     # the replicon type agrees; the plasmid is still wrong
        print("  PASS: two plasmids with the same replicon type: the gene is on the wrong plasmid although the replicon type matches (replicon agreement is not identity)")
    print("ALL AMR PLACEMENT BY TASK TESTS PASSED")


if __name__ == "__main__":
    main()
