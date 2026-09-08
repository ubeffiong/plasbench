#!/usr/bin/env python3
"""Regression for python/validate_truth_table.py's own row-level checks --
no prior test exercised this script directly (test_local_inputs.py only
covers it as a downstream step of init-local scaffolding), so the Round-2
audit fix making a duplicate sequence_id a reported problem (previously the
`seen` set was populated but never checked before adding, so a repeated id
silently passed validation even though score_plasmids.py's own read_truth()
dict-overwrites on it, scoring only the LAST matching row) had no direct
coverage at all.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATE_TRUTH = ROOT / "python" / "validate_truth_table.py"

REFERENCE = (
    ">chr1 chromosome\n" + "ACGT" * 250 + "\n"
    ">plas1 plasmid\n" + "ACGT" * 50 + "\n"
)


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " -> True")


def validate_truth(truth, reference, *extra):
    return subprocess.run([sys.executable, str(VALIDATE_TRUTH), "--truth", str(truth),
                           "--reference", str(reference), *extra],
                          capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    reference = tmp / "reference.fna"
    reference.write_text(REFERENCE, encoding="utf-8")

    valid_truth = tmp / "truth.tsv"
    valid_truth.write_text(
        "sequence_id\tmolecule_type\tlength\n"
        "chr1\tCHROMOSOME\t1000\n"
        "plas1\tPLASMID\t200\n",
        encoding="utf-8",
    )
    result = validate_truth(valid_truth, reference)
    check("a valid truth table with no duplicates passes (exit 0)", result.returncode == 0, result.stdout + result.stderr)

    duplicate_truth = tmp / "truth_dup.tsv"
    duplicate_truth.write_text(
        "sequence_id\tmolecule_type\tlength\n"
        "chr1\tCHROMOSOME\t1000\n"
        "plas1\tPLASMID\t200\n"
        "chr1\tPLASMID\t1000\n",  # same id repeated, even with a conflicting molecule_type
        encoding="utf-8",
    )
    result = validate_truth(duplicate_truth, reference)
    check("a duplicate sequence_id is rejected (exit 2)", result.returncode == 2, result.stdout + result.stderr)
    check("the duplicate-id problem is reported by name", "duplicate sequence_id" in result.stderr, result.stderr)

print("\nALL VALIDATE TRUTH TABLE TESTS PASSED")
