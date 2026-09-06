#!/usr/bin/env python3
"""Regression for python/build_accession_ledger.py: the ledger is generated
purely from cohorts/*.lock.json evidence, keyed on BioSample (not assembly
accession, since an assembly can be resubmitted under a new accession for
the same physical isolate), and a BioSample re-locked in a later release
resolves to the later cohort rather than being duplicated."""

import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "python", "build_accession_ledger.py")


def write_lock(path, evidence):
    payload = {"schema_version": "1.1", "sample_sheet": "x.tsv", "sample_sheet_sha256": "0" * 64, "evidence": evidence}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def run(cohorts_dir, out):
    subprocess.run([sys.executable, SCRIPT, "--cohorts-dir", cohorts_dir, "--out", out], check=True, capture_output=True, text=True)
    with open(out, newline="", encoding="utf-8") as handle:
        return {row["biosample"]: row for row in csv.DictReader(handle, delimiter="\t")}


def main():
    with tempfile.TemporaryDirectory(prefix="ledger_") as tmp:
        write_lock(os.path.join(tmp, "public-v1.lock.json"), [
            {"sample_id": "iso_a", "assembly": {"accession": "GCF_1.1", "biosample": "SAMN001"}, "run": {"run": "SRR001"}},
            {"sample_id": "iso_b", "assembly": {"accession": "GCF_2.1", "biosample": "SAMN002"}, "run": {"run": "SRR002"}},
        ])
        # v2 re-locks iso_a (same BioSample, but resubmitted under a NEW
        # assembly accession -- exactly the "assembly resubmitted, same
        # physical isolate" case the plan calls out) and adds a genuinely
        # new isolate.
        write_lock(os.path.join(tmp, "public-v2.lock.json"), [
            {"sample_id": "iso_a", "assembly": {"accession": "GCF_1.2", "biosample": "SAMN001"}, "run": {"run": "SRR001"}},
            {"sample_id": "iso_b", "assembly": {"accession": "GCF_2.1", "biosample": "SAMN002"}, "run": {"run": "SRR002"}},
            {"sample_id": "iso_c", "assembly": {"accession": "GCF_3.1", "biosample": "SAMN003"}, "run": {"run": "SRR003"}},
        ])
        ledger = run(tmp, os.path.join(tmp, "ledger.tsv"))

        assert len(ledger) == 3, f"expected 3 unique BioSamples, got {len(ledger)}"
        assert ledger["SAMN001"]["assembly_accession"] == "GCF_1.2", \
            "expected the LATER release's accession for a resubmitted BioSample, not the earlier one"
        assert ledger["SAMN001"]["source_cohort"] == "public-v2"
        assert ledger["SAMN003"]["sample_id"] == "iso_c"
        print("a BioSample resubmitted under a new accession resolves to the later release, not duplicated -> PASS")

        # Missing lock directory / no lock files at all -> a clear error, not a crash.
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        result = subprocess.run([sys.executable, SCRIPT, "--cohorts-dir", empty, "--out", os.path.join(tmp, "x.tsv")],
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert "no *.lock.json files found" in result.stderr
        print("no lock files present -> a clear error, not a crash or an empty silent success -> PASS")

    print("ALL ACCESSION LEDGER TESTS PASSED")


if __name__ == "__main__":
    main()
