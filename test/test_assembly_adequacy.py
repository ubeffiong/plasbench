#!/usr/bin/env python3
"""python/assembly_adequacy.py.

Fixture: truth plasmid p1 1000 bp, assembly covers 800 -> adequacy 0.8 < 0.90 -> adequate no
(0.8 >= 0.75 -> yes). Labels: c1 PLASMID 800, c2 CHROMOSOME 5000, c3 CHIMERIC 300, c4 UNPLACED 100,
c5 AMBIGUOUS 200, c6 FUTURE_LABEL 100 (unknown counts 0). contig_bp = 6500, chimeric_fraction
300/6500 = 0.0462, unplaced_fraction 100/6500 = 0.0154.
N50: FASTA lengths 100,80,60,40,20 (total 300, half 150; 100+80 = 180 >= 150) -> 80.
GC: G in the 100 bp and 40 bp contigs = 140 of 300 bases -> 46.6667%.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "assembly_adequacy.py"
FAILED = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def rows(path):
    with open(path, newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h, delimiter="\t"))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        d = tmp / "data" / "s1"
        d.mkdir(parents=True)
        (d / "contig_labels.tsv").write_text(
            "contig\tlength\tlabel\tplasmid_fraction\tchromosome_fraction\tbest_plasmid\treason\n"
            "c1\t800\tPLASMID\t1\t0\tp1\t\nc2\t5000\tCHROMOSOME\t0\t1\t\t\nc3\t300\tCHIMERIC\t0.5\t0.5\tp1\t\n"
            "c4\t100\tUNPLACED\t0\t0\t\t\nc5\t200\tAMBIGUOUS\t1\t1\tp1\t\nc6\t100\tFUTURE_LABEL\t0\t0\t\t\n")
        (d / "plasmid_assembly_coverage.tsv").write_text("sequence_id\tlength\tassembly_covered_bp\np1\t1000\t800\n")
        fa = ""
        for i, (n, base) in enumerate([(100, "G"), (80, "A"), (60, "A"), (40, "G"), (20, "A")]):
            fa += f">k{i}\n{base * n}\n"
        (d / "contigs.fasta").write_text(fa)
        out = tmp / "o.tsv"
        r = run("--sample", "s1", "--contig-labels", d / "contig_labels.tsv", "--assembly-coverage",
                d / "plasmid_assembly_coverage.tsv", "--contigs-fasta", d / "contigs.fasta", "--out", out)
        check("cli exit 0", r.returncode == 0, r.stderr)
        row = rows(out)[0]
        check("adequacy 0.8", row["plasmid_adequacy"] == "0.8000", row)
        check("truth/covered bp", (row["truth_plasmid_bp"], row["assembly_covered_plasmid_bp"]) == ("1000", "800"))
        check("adequate no below 0.9", row["adequate"] == "no")
        check("chimeric counted", (row["n_chimeric"], row["chimeric_bp"]) == ("1", "300"), row)
        check("counts", (row["n_contigs"], row["contig_bp"], row["n_plasmid_contigs"], row["n_chromosome_contigs"],
                         row["n_ambiguous"], row["n_unplaced"]) == ("6", "6500", "1", "1", "1", "1"), row)
        check("fractions", (row["chimeric_fraction"], row["unplaced_fraction"]) == ("0.0462", "0.0154"), row)
        check("N50 hand value 80", row["assembly_n50"] == "80", row["assembly_n50"])
        check("total length 300 / GC 46.67", (row["assembly_total_length"], row["assembly_gc_percent"]) == ("300", "46.6667"), row)
        run("--sample", "s1", "--contig-labels", d / "contig_labels.tsv", "--assembly-coverage",
            d / "plasmid_assembly_coverage.tsv", "--out", out, "--min-adequacy", "0.75")
        check("lower threshold -> yes", rows(out)[0]["adequate"] == "yes")

        # missing files never crash
        r = run("--sample", "gone", "--contig-labels", tmp / "nope.tsv", "--assembly-coverage", tmp / "nope2.tsv", "--out", out)
        row = rows(out)[0]
        check("missing labels -> status", r.returncode == 0 and row["assembly_status"] == "contig_labels_unavailable"
              and row["adequate"] == "not_assessed" and row["reason"], row)
        # labels present, coverage missing
        r = run("--sample", "s1", "--contig-labels", d / "contig_labels.tsv", "--out", out)
        row = rows(out)[0]
        check("missing coverage -> not_assessed", row["assembly_status"] == "ok" and row["adequate"] == "not_assessed"
              and row["plasmid_adequacy"] == "")
        # no plasmid in truth: blank adequacy
        (d / "plasmid_assembly_coverage.tsv").write_text("sequence_id\tlength\tassembly_covered_bp\n")
        run("--sample", "s1", "--contig-labels", d / "contig_labels.tsv",
            "--assembly-coverage", d / "plasmid_assembly_coverage.tsv", "--out", out)
        check("no plasmid -> blank", rows(out)[0]["plasmid_adequacy"] == "" and rows(out)[0]["adequate"] == "not_assessed")

        # merge
        (d / "plasmid_assembly_coverage.tsv").write_text("sequence_id\tlength\tassembly_covered_bp\np1\t1000\t800\n")
        (tmp / "data" / "s2").mkdir()
        m = tmp / "m.tsv"
        r = run("merge", "--data-dir", tmp / "data", "--out", m)
        mr = rows(m)
        check("merge one row per sample", r.returncode == 0 and [x["sample"] for x in mr] == ["s1", "s2"], r.stderr)
        check("merge s2 unavailable", mr[1]["assembly_status"] == "contig_labels_unavailable")
        check("merge s1 contigs.fasta used", mr[0]["assembly_n50"] == "80")
    if FAILED:
        print(f"{len(FAILED)} FAILED")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
