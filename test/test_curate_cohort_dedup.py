#!/usr/bin/env python3
"""Regression for curate_cohort.py's --ledger cross-cohort dedup check: a
candidate whose BioSample is already in a prior released cohort is rejected
with a clear reason, keyed on BioSample (not assembly accession, since an
assembly can be resubmitted under a new accession for the same physical
isolate) -- matches test_cohort_validation.py's established monkeypatch
convention (fake metadata functions, no real network access)."""

import csv
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import curate_cohort  # noqa: E402


def write_ledger(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("biosample", "sample_id", "assembly_accession", "sra_run", "source_cohort"), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def run_curate(tmp, ledger_path=None):
    candidates = os.path.join(tmp, "candidates.tsv")
    with open(candidates, "w", encoding="utf-8") as handle:
        handle.write("assembly_accession\tsra_run\n")
        handle.write("GCF_9.2\tSRR999\n")  # NEW accession, but the fake assembly_metadata below always reports SAMN_DUP
    out_dir = os.path.join(tmp, "out")
    argv = ["curate_cohort.py", "--candidates", candidates, "--out-dir", out_dir]
    if ledger_path:
        argv += ["--ledger", ledger_path]
    old_argv = sys.argv
    sys.argv = argv
    try:
        curate_cohort.main()
    finally:
        sys.argv = old_argv
    with open(os.path.join(out_dir, "accepted.tsv"), newline="", encoding="utf-8") as handle:
        accepted = list(csv.DictReader(handle, delimiter="\t"))
    with open(os.path.join(out_dir, "rejected.tsv"), newline="", encoding="utf-8") as handle:
        rejected = list(csv.DictReader(handle, delimiter="\t"))
    return accepted, rejected


def main():
    original_assembly_metadata = curate_cohort.assembly_metadata
    original_run_metadata = curate_cohort.run_metadata
    curate_cohort.assembly_metadata = lambda accession, email=None, api_key=None: {
        "accession": accession, "biosample": "SAMN_DUP", "bioprojects": ["PRJNA1"],
        "organism": "Example bacterium", "assembly_status": "Complete Genome",
        "has_plasmid": True, "derived_truth_technology": "hybrid",
    }
    curate_cohort.run_metadata = lambda run, email=None, api_key=None: {
        "run": run, "biosample": "SAMN_DUP", "bioproject": "PRJNA1", "platform": "ILLUMINA", "layout": "PAIRED",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="curate_dedup_") as tmp:
            ledger = os.path.join(tmp, "ledger.tsv")
            write_ledger(ledger, [{"biosample": "SAMN_DUP", "sample_id": "already_here",
                                   "assembly_accession": "GCF_9.1", "sra_run": "SRR000",
                                   "source_cohort": "public-v2"}])

            # A candidate whose assembly was resubmitted under a NEW accession
            # (GCF_9.2, not the ledger's GCF_9.1) but is the SAME physical
            # isolate (same BioSample) must still be caught.
            accepted, rejected = run_curate(tmp, ledger_path=ledger)
            assert len(accepted) == 0, f"expected the duplicate BioSample to be rejected, got accepted={accepted}"
            assert len(rejected) == 1
            assert "already in cohort public-v2" in rejected[0]["reason"], rejected[0]["reason"]
            print("a candidate resubmitted under a new accession is still caught by BioSample -> PASS")

            # Without --ledger, the exact same candidate is accepted (today's
            # unchanged behavior) -- the check is additive/optional.
            accepted2, rejected2 = run_curate(tmp, ledger_path=None)
            assert len(accepted2) == 1, f"expected acceptance with no ledger given, got {accepted2}, {rejected2}"
            print("omitting --ledger reproduces today's unchanged behavior (no cross-cohort check) -> PASS")
    finally:
        curate_cohort.assembly_metadata = original_assembly_metadata
        curate_cohort.run_metadata = original_run_metadata

    print("ALL CURATE COHORT DEDUP TESTS PASSED")


if __name__ == "__main__":
    main()
