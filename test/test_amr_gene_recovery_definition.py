#!/usr/bin/env python3
"""AMR gene recovery means the same in both scorers (audit AU-047): the union of alignments, as score_plasmids.py counts it.

A gene split 0-48 + 52-100 (96% covered) was recovered for the base scorer and not_recovered for the placement scorer, which looked at one interval only."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "score_amr_placement.py"


def run(paf_lines, fasta_records, bins=None):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\npA\tPLASMID\t5000\n")
        (tmp / "amr.tsv").write_text("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\npA\t1000\t1100\tblaKPC-2\tg1\tc1\tcard\t1\n")
        (tmp / "pred.fasta").write_text("".join(f">{n}\n{'A' * l}\n" for n, l in fasta_records))
        (tmp / "pred.paf").write_text("".join(paf_lines))
        (tmp / "labels.tsv").write_text("contig\tlength\tlabel\tplasmid_fraction\tchromosome_fraction\tbest_plasmid\treason\n" + "".join(f"{n}\t{l}\tPLASMID\t1\t0\tpA\t\n" for n, l in fasta_records))
        cmd = [sys.executable, str(SCRIPT), "score", "--sample", "S", "--tool", "t", "--truth", str(tmp / "truth.tsv"), "--amr-truth", str(tmp / "amr.tsv"), "--paf", str(tmp / "pred.paf"),
               "--pred-fasta", str(tmp / "pred.fasta"), "--contig-labels", str(tmp / "labels.tsv"), "--out", str(tmp / "o.tsv")]
        if bins:
            (tmp / "bins.tsv").write_text("sequence_id\tbin_id\n" + "".join(f"{n}\t{b}\n" for n, b in bins))
            cmd += ["--bins", str(tmp / "bins.tsv")]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(tmp / "o.tsv", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))[0]


def paf(q, ql, qs, qe, ts, te):
    return f"{q}\t{ql}\t{qs}\t{qe}\t+\tpA\t5000\t{ts}\t{te}\t{qe - qs}\t{qe - qs}\t60\n"


# one record aligned in two blocks around a 4 bp gap in the gene (96% union): recovered and placed on its record
one = run([paf("r1", 5000, 1000, 1048, 1000, 1048), paf("r1", 5000, 1052, 1100, 1052, 1100)], [("r1", 5000)], bins=[("r1", "b1")])
assert one["placement"] == "correct_plasmid", one
# two different records each covering one half: the base scorer counts it recovered; it cannot be placed on one record, so it is unassigned (not not_recovered)
two = run([paf("r1", 48, 0, 48, 1000, 1048), paf("r2", 48, 0, 48, 1052, 1100)], [("r1", 48), ("r2", 48)], bins=[("r1", "b1"), ("r2", "b2")])
assert two["placement"] == "unassigned_contig" and two["assigned_bin"] == "" and two["matched_plasmid"] == "", two
# a gene only half covered is still not recovered
half = run([paf("r1", 50, 0, 50, 1000, 1050)], [("r1", 50)], bins=[("r1", "b1")])
assert half["placement"] == "not_recovered", half
print("  PASS: split gene recovered by union (one record: placed; two records: unassigned_contig); half-covered gene still not_recovered")
print("ALL AMR GENE RECOVERY DEFINITION TESTS PASSED")
