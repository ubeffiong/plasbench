#!/usr/bin/env python3
"""Offline regression checks for the public cohort schema and CLI validation."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, "python", "validate_cohort.py")


def main():
    panel = os.path.join(ROOT, "cohorts", "public-v1.tsv")
    subprocess.run([sys.executable, VALIDATOR, "--samples", panel], check=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump({"schema_version": "1.0", "sample_sheet": "public-v1.tsv",
                   "sample_sheet_sha256": hashlib.sha256(open(panel, "rb").read()).hexdigest(),
                   "evidence": []}, handle)
        lock = handle.name
    try:
        subprocess.run([sys.executable, VALIDATOR, "--samples", panel, "--verify-lock", lock], check=True)
    finally:
        os.unlink(lock)
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\tread_depth_x\n")
        handle.write("bad\tGCF_000000000.1\tSRR0000001\tExample\thybrid\tA\tSAMN1\tPRJNA1\tnot-a-number\n")
        invalid = handle.name
    try:
        result = subprocess.run([sys.executable, VALIDATOR, "--samples", invalid], text=True, capture_output=True)
        assert result.returncode != 0 and "read_depth_x must be numeric" in result.stderr
    finally:
        os.unlink(invalid)
    print("ALL COHORT VALIDATION TESTS PASSED")


if __name__ == "__main__":
    main()
