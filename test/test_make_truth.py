#!/usr/bin/env python3
"""Regression checks for accession resolution in truth generation.

An unresolvable sequence must never be guessed: it is written as REVIEW, which
validate_truth_table.py rejects, unless --allow-default is given explicitly.
"""

import csv
import json
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "make_truth.py")
VALIDATE = os.path.join(ROOT, "python", "validate_truth_table.py")


def run(tmp, fasta_text, report_rows, *extra):
    fasta = os.path.join(tmp, "reference.fna")
    report = os.path.join(tmp, "sequence_report.jsonl")
    output = os.path.join(tmp, "truth.tsv")
    with open(fasta, "w", encoding="utf-8") as handle:
        handle.write(fasta_text)
    with open(report, "w", encoding="utf-8") as handle:
        for row in report_rows:
            handle.write(json.dumps(row) + "\n")
    result = subprocess.run([sys.executable, SCRIPT, "--report", report, "--fasta", fasta,
                             "--out", output, *extra],
                            text=True, capture_output=True, check=True)
    with open(output, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return [(r["sequence_id"], r["molecule_type"], r["length"]) for r in rows], result.stderr, fasta, output


def main():
    # 1. Clean resolution: exact, version-less report key, exact refseq key.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, _, _ = run(
            tmp, ">CP000001.1 chromosome\nAAAA\n>CP000002.1 plasmid\nCCCCC\n",
            [{"genbank_accession": "CP000001", "assigned_molecule_location_type": "Chromosome"},
             {"refseq_accession": "CP000002.1", "assigned_molecule_location_type": "Plasmid"}])
        assert rows == [("CP000001.1", "CHROMOSOME", "4"), ("CP000002.1", "PLASMID", "5")], rows
        assert "0 unresolved" in err, err
    print("clean report resolves exact and version-less accessions -> PASS")

    # 2. Absent id is REVIEW, not CHROMOSOME, and the table is then rejected by the validator.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, fasta, output = run(
            tmp, ">CP000001.1 c\nAAAA\n>unknown\nGG\n",
            [{"genbank_accession": "CP000001.1", "assigned_molecule_location_type": "Chromosome"}])
        assert ("unknown", "REVIEW", "2") in rows, rows
        assert "the id is not in the report" in err and "marked REVIEW" in err, err
        check = subprocess.run([sys.executable, VALIDATE, "--truth", output, "--reference", fasta],
                               text=True, capture_output=True)
        assert check.returncode == 2 and "REVIEW" in check.stderr, (check.returncode, check.stderr)
    print("absent id -> REVIEW and validate_truth_table.py refuses it -> PASS")

    # 3. --allow-default restores the explicit legacy behaviour, with a warning.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, _, _ = run(
            tmp, ">CP000001.1 c\nAAAA\n>unknown\nGG\n",
            [{"genbank_accession": "CP000001.1", "assigned_molecule_location_type": "Chromosome"}],
            "--allow-default")
        assert ("unknown", "CHROMOSOME", "2") in rows, rows
        assert "defaulting to CHROMOSOME" in err and "--allow-default" in err, err
    print("--allow-default writes CHROMOSOME with a warning -> PASS")

    # 4. A location type that is neither Plasmid nor Chromosome is named, not silently scored.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, _, _ = run(
            tmp, ">CP000001.1 c\nAAAA\n>CP000009.1 seg\nTT\n",
            [{"genbank_accession": "CP000001.1", "assigned_molecule_location_type": "Chromosome"},
             {"genbank_accession": "CP000009.1", "assigned_molecule_location_type": "Segment"}])
        assert ("CP000009.1", "REVIEW", "2") in rows, rows
        assert "location type is 'Segment'" in err, err
    print("unsupported location type -> REVIEW, reason names the type -> PASS")

    # 5. A report that contradicts itself is not resolved by picking one.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, _, _ = run(
            tmp, ">NC_000001.1 a\nAAAA\n>NC_000001.2 b\nCCCC\n",
            [{"refseq_accession": "NC_000001.1", "assigned_molecule_location_type": "Chromosome"},
             {"refseq_accession": "NC_000001.2", "assigned_molecule_location_type": "Plasmid"}])
        # Exact accessions are unambiguous and both resolve.
        assert rows == [("NC_000001.1", "CHROMOSOME", "4"), ("NC_000001.2", "PLASMID", "4")], rows
        # A FASTA id with an unknown version only matches via the version-less key, which is contradictory.
        rows, err, _, _ = run(
            tmp, ">NC_000001.9 c\nAAAA\n",
            [{"refseq_accession": "NC_000001.1", "assigned_molecule_location_type": "Chromosome"},
             {"refseq_accession": "NC_000001.2", "assigned_molecule_location_type": "Plasmid"}])
        assert rows == [("NC_000001.9", "REVIEW", "4")], rows
        assert "both plasmid and chromosome" in err, err
    print("contradictory version-less match -> REVIEW, not order-dependent -> PASS")

    # 6. chr_name is a last resort and conflicts are not resolved by the last record winning.
    with tempfile.TemporaryDirectory(prefix="make_truth_test_") as tmp:
        rows, err, _, _ = run(
            tmp, ">1\nAAAA\n",
            [{"chr_name": "1", "assigned_molecule_location_type": "Chromosome"},
             {"chr_name": "1", "assigned_molecule_location_type": "Plasmid"}])
        assert rows == [("1", "REVIEW", "4")], rows
        assert "chr_name both plasmid and chromosome" in err, err
        rows, err, _, _ = run(
            tmp, ">pFoo\nAAAA\n",
            [{"chr_name": "pFoo", "assigned_molecule_location_type": "Plasmid"}])
        assert rows == [("pFoo", "PLASMID", "4")], rows
    print("chr_name used only as an unambiguous last resort -> PASS")

    print("ALL MAKE-TRUTH TESTS PASSED")


if __name__ == "__main__":
    main()
