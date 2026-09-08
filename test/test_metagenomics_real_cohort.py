#!/usr/bin/env python3
"""The accession-resolved real-community review panel must stay non-deceptive."""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    cohort = ROOT / "cohorts" / "metagenomics-real-v1.tsv"
    ledger = ROOT / "cohorts" / "metagenomics-real-v1.accessions.tsv"
    rows = list(csv.DictReader(cohort.open(encoding="utf-8"), delimiter="\t"))
    runs = list(csv.DictReader(ledger.open(encoding="utf-8"), delimiter="\t"))
    assert len(rows) == len(runs) == 6
    assert {row["truth_status"] for row in rows} == {"mock", "unavailable"}
    assert all("not independently validated" in row["truth_provenance"].lower() or row["truth_status"] == "unavailable" for row in rows)
    with tempfile.TemporaryDirectory() as temporary:
        audit = Path(temporary) / "audit.json"
        valid = subprocess.run([sys.executable, "python/metagenomics.py", "validate", "--manifest", str(cohort)], cwd=ROOT, capture_output=True, text=True)
        assert valid.returncode == 0, valid.stderr
        release = subprocess.run([sys.executable, "python/audit_metagenomic_cohort.py", "--manifest", str(cohort), "--out", str(audit), "--release-ready"], cwd=ROOT, capture_output=True, text=True)
        assert release.returncode != 0 and "mock" in release.stderr
        assert "zymobiomics_hmw_standard" in json.loads(audit.read_text())["reused_reference_clusters"]
    print("REAL METAGENOMIC REVIEW COHORT IS ACCESSION-RESOLVED AND RELEASE-GATED")


if __name__ == "__main__":
    main()
