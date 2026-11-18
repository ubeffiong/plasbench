#!/usr/bin/env python3
"""A gene on a record that no bin contains is unassigned, not correctly placed (audit AU-004).

The old code turned an unbinned record into a one-record bin of its own, so a binner that left the plasmid contig out of every bin was credited with
`correct_plasmid` for its genes."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "score_amr_placement.py"

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\npA\tPLASMID\t5000\npB\tPLASMID\t5000\n")
    (tmp / "amr.tsv").write_text("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\n"
                                 "pA\t100\t900\tblaKPC-2\tg1\tc1\tcard\t1\npB\t100\t900\tblaCTX-M-15\tg2\tc2\tcard\t1\n")
    (tmp / "pred.fasta").write_text(">r1\n" + "A" * 5000 + "\n>r2\n" + "A" * 5000 + "\n")
    (tmp / "pred.paf").write_text("r1\t5000\t0\t5000\t+\tpA\t5000\t0\t5000\t5000\t5000\t60\nr2\t5000\t0\t5000\t+\tpB\t5000\t0\t5000\t5000\t5000\t60\n")
    (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nr1\tb1\n")        # r2 is in no bin
    (tmp / "labels.tsv").write_text("contig\tlength\tlabel\tplasmid_fraction\tchromosome_fraction\tbest_plasmid\treason\nr1\t5000\tPLASMID\t1\t0\tpA\t\nr2\t5000\tPLASMID\t1\t0\tpB\t\n")
    results = tmp / "results" / "S1"
    results.mkdir(parents=True)
    subprocess.run([sys.executable, str(SCRIPT), "score", "--sample", "S1", "--tool", "t", "--truth", str(tmp / "truth.tsv"), "--amr-truth", str(tmp / "amr.tsv"),
                    "--paf", str(tmp / "pred.paf"), "--pred-fasta", str(tmp / "pred.fasta"), "--bins", str(tmp / "bins.tsv"), "--contig-labels", str(tmp / "labels.tsv"),
                    "--out", str(results / "t.amr_placement.tsv")], check=True, capture_output=True)
    with open(results / "t.amr_placement.tsv", newline="") as handle:
        genes = {r["gene_name"]: r for r in csv.DictReader(handle, delimiter="\t")}
    assert genes["blaKPC-2"]["placement"] == "correct_plasmid", genes
    assert genes["blaCTX-M-15"]["placement"] == "unassigned_contig", genes
    assert genes["blaCTX-M-15"]["assigned_bin"] == "" and genes["blaCTX-M-15"]["matched_plasmid"] == "", genes
    print("  PASS: a gene on a record in no bin is unassigned_contig, not correct_plasmid; the binned gene is unaffected")
print("ALL AMR UNBINNED TESTS PASSED")
