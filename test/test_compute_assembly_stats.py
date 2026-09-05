#!/usr/bin/env python3
"""Regression for python/compute_assembly_stats.py: exact N50/GC%/contig-count/
plasmid-count against a hand-computable fixture (analytic, not approximate)."""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "python", "compute_assembly_stats.py")


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def run(fasta, truth, out, sample_id=None):
    cmd = [sys.executable, SCRIPT, "--fasta", fasta, "--truth", truth, "--out", out]
    if sample_id:
        cmd += ["--sample-id", sample_id]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with open(out, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        row = handle.readline().rstrip("\n").split("\t")
    return dict(zip(header, row))


def main():
    with tempfile.TemporaryDirectory(prefix="assembly_stats_") as tmp:
        # 3 contigs: 100bp (all A), 60bp (all C), 40bp (all G).
        # assembly_size_bp = 200, contig_count = 3.
        # N50: sorted desc [100, 60, 40], cumulative sum reaches half (100) at
        # the very first (largest) contig -> N50 = 100.
        # gc_percent: 60 C's + 40 G's over 200 total ACGT bases = 50.0000.
        fasta = write(os.path.join(tmp, "reference.fna"),
                      ">c1\n" + "A" * 100 + "\n>c2\n" + "C" * 60 + "\n>c3\n" + "G" * 40 + "\n")
        truth = write(os.path.join(tmp, "truth.tsv"),
                      "sequence_id\tmolecule_type\tlength\nc1\tCHROMOSOME\t100\nc2\tPLASMID\t60\nc3\tPLASMID\t40\n")
        out = os.path.join(tmp, "assembly_stats.tsv")
        row = run(fasta, truth, out, sample_id="s1")
        assert row["sample_id"] == "s1"
        assert row["assembly_size_bp"] == "200"
        assert row["contig_count"] == "3"
        assert row["n50"] == "100"
        assert row["gc_percent"] == "50.0000"
        assert row["plasmid_count"] == "2"
        print("exact N50/GC%/contig-count/plasmid-count against a hand-computed fixture -> PASS")

        # sample_id defaults to the FASTA's parent directory name.
        sdir = os.path.join(tmp, "sampleXYZ")
        os.makedirs(sdir)
        fasta2 = write(os.path.join(sdir, "reference.fna"), ">c1\n" + "A" * 10 + "\n")
        truth2 = write(os.path.join(sdir, "truth.tsv"), "sequence_id\tmolecule_type\tlength\nc1\tCHROMOSOME\t10\n")
        row2 = run(fasta2, truth2, os.path.join(sdir, "assembly_stats.tsv"))
        assert row2["sample_id"] == "sampleXYZ"
        print("sample_id defaults to the reference FASTA's parent directory name -> PASS")

        # N50 with an even split: [100, 100] -> cumulative reaches half (100)
        # at the first 100 -> N50 = 100 (not the smaller contig).
        fasta3 = write(os.path.join(tmp, "even.fna"), ">c1\n" + "A" * 100 + "\n>c2\n" + "A" * 100 + "\n")
        truth3 = write(os.path.join(tmp, "even.truth.tsv"),
                       "sequence_id\tmolecule_type\tlength\nc1\tCHROMOSOME\t100\nc2\tCHROMOSOME\t100\n")
        row3 = run(fasta3, truth3, os.path.join(tmp, "even.stats.tsv"), sample_id="even")
        assert row3["n50"] == "100"
        assert row3["plasmid_count"] == "0"
        print("N50 tie-breaking and zero-plasmid samples handled correctly -> PASS")

    print("ALL COMPUTE ASSEMBLY STATS TESTS PASSED")


if __name__ == "__main__":
    main()
