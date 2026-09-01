#!/usr/bin/env python3
"""Regression checks for accession and version resolution in truth generation."""

import csv
import json
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "make_truth.py")


def main():
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        fasta = os.path.join(tmp, "reference.fna")
        report = os.path.join(tmp, "sequence_report.jsonl")
        output = os.path.join(tmp, "truth.tsv")
        with open(fasta, "w", encoding="utf-8") as handle:
            handle.write(">CP000001.1 chromosome\nAAAA\n>CP000002.1 plasmid\nCCCCC\n>unknown\nGG\n")
        with open(report, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"genbank_accession": "CP000001", "assigned_molecule_location_type": "Chromosome"}) + "\n")
            handle.write(json.dumps({"refseq_accession": "CP000002.1", "assigned_molecule_location_type": "Plasmid"}) + "\n")
        result = subprocess.run([sys.executable, SCRIPT, "--report", report, "--fasta", fasta, "--out", output],
                                text=True, capture_output=True, check=True)
        with open(output, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        assert [(row["sequence_id"], row["molecule_type"], row["length"]) for row in rows] == [
            ("CP000001.1", "CHROMOSOME", "4"), ("CP000002.1", "PLASMID", "5"),
            ("unknown", "CHROMOSOME", "2"),
        ]
        assert "defaulting to CHROMOSOME" in result.stderr
    print("ALL MAKE-TRUTH TESTS PASSED")


if __name__ == "__main__":
    main()
