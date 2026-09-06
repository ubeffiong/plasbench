#!/usr/bin/env python3
"""Regression for validate_cohort.py's --ledger cross-cohort dedup check: a
hand-edited cohort sheet whose BioSample is already in a prior released
cohort fails validation, not just discovery-sourced candidates
(curate_cohort.py's own check is covered separately in
test_curate_cohort_dedup.py)."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VALIDATOR = os.path.join(ROOT, "python", "validate_cohort.py")

ROW = "ok\tGCF_000000000.1\tSRR0000001\tExample\thybrid\tA\tSAMN_DUP\tPRJNA1\n"
HEADER = "sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\n"


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="validate_ledger_") as tmp:
        samples = write(os.path.join(tmp, "samples.tsv"), HEADER + ROW)
        ledger = os.path.join(tmp, "ledger.tsv")
        with open(ledger, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("biosample", "sample_id", "assembly_accession", "sra_run", "source_cohort"), delimiter="\t")
            writer.writeheader()
            writer.writerow({"biosample": "SAMN_DUP", "sample_id": "already_here",
                             "assembly_accession": "GCF_999.1", "sra_run": "SRR000", "source_cohort": "public-v2"})

        result = subprocess.run([sys.executable, VALIDATOR, "--samples", samples, "--ledger", ledger],
                                capture_output=True, text=True)
        assert result.returncode != 0, "expected validation to fail for a BioSample already in a released cohort"
        assert "already in cohort public-v2" in result.stderr, result.stderr
        print("a hand-edited sheet's BioSample already in a released cohort fails validation -> PASS")

        result2 = subprocess.run([sys.executable, VALIDATOR, "--samples", samples], capture_output=True, text=True)
        assert result2.returncode == 0, "omitting --ledger must reproduce today's unchanged (passing) behavior"
        print("omitting --ledger reproduces today's unchanged behavior (no cross-cohort check) -> PASS")

    print("ALL VALIDATE COHORT LEDGER TESTS PASSED")


if __name__ == "__main__":
    main()
