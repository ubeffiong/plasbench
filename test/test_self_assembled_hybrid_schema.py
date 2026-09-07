#!/usr/bin/env python3
"""Regression for validate_cohort.py's truth_source=self_assembled_hybrid
schema support: a row may leave assembly_accession blank ONLY when it
declares a valid long_read_sra_run instead, and it may NEVER declare
truth_independent_of_long_reads=yes -- a hard rule, not a judgment call,
since a self-built truth is never independent of the reads that built it
by construction. Also covers verify_self_assembled_row()'s own NCBI
cross-check (no real network access -- monkeypatched run_metadata()).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import validate_cohort as vc  # noqa: E402

FIELDS = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
          "truth_quality_tier", "biosample", "bioproject", "truth_source",
          "long_read_sra_run", "truth_independent_of_long_reads")


def base_row(**overrides):
    row = {
        "sample_id": "s1", "assembly_accession": "GCF_1.1", "sra_run": "SRR1",
        "organism": "Escherichia coli", "truth_technology": "hybrid", "truth_quality_tier": "B",
        "biosample": "SAMN1", "bioproject": "PRJNA1", "truth_source": "", "long_read_sra_run": "",
        "truth_independent_of_long_reads": "",
    }
    row.update(overrides)
    return row


def main():
    # --- Case 1: default (truth_source absent/empty) behaves exactly like
    # before -- unchanged regression check. ---
    errors = vc.schema_errors([base_row()], FIELDS)
    assert errors == [], errors
    print("a normal ncbi_deposited row (truth_source absent) validates unchanged -> PASS")

    # --- Case 2: self_assembled_hybrid with blank assembly_accession and a
    # valid long_read_sra_run is accepted -- no "invalid assembly accession". ---
    row = base_row(truth_source="self_assembled_hybrid", assembly_accession="",
                   sra_run="SRR2", long_read_sra_run="SRR100")
    errors = vc.schema_errors([row], FIELDS)
    assert errors == [], errors
    print("self_assembled_hybrid with a blank assembly_accession and valid long_read_sra_run passes -> PASS")

    # --- Case 3: self_assembled_hybrid missing long_read_sra_run is rejected. ---
    row = base_row(truth_source="self_assembled_hybrid", assembly_accession="", long_read_sra_run="")
    errors = vc.schema_errors([row], FIELDS)
    assert any("requires a valid long_read_sra_run" in e for e in errors), errors
    print("self_assembled_hybrid with no long_read_sra_run is rejected -> PASS")

    # --- Case 4: the hard safety rule -- self_assembled_hybrid can never
    # declare truth_independent_of_long_reads=yes. ---
    row = base_row(truth_source="self_assembled_hybrid", assembly_accession="",
                   long_read_sra_run="SRR100", truth_independent_of_long_reads="yes")
    errors = vc.schema_errors([row], FIELDS)
    assert any("must never declare truth_independent_of_long_reads=yes" in e for e in errors), errors
    print("self_assembled_hybrid declaring truth_independent_of_long_reads=yes is a hard schema error -> PASS")

    # --- Case 5: an invalid truth_source value is rejected outright. ---
    row = base_row(truth_source="made_up_value")
    errors = vc.schema_errors([row], FIELDS)
    assert any("truth_source must be ncbi_deposited or self_assembled_hybrid" in e for e in errors), errors
    print("an unrecognized truth_source value is rejected -> PASS")

    # --- Case 6: a normal ncbi_deposited row still requires a real
    # assembly_accession -- the exemption is scoped to self_assembled_hybrid only. ---
    row = base_row(assembly_accession="")
    errors = vc.schema_errors([row], FIELDS)
    assert any("invalid assembly accession" in e for e in errors), errors
    print("a plain ncbi_deposited row still requires a real assembly_accession -> PASS")

    # --- verify_self_assembled_row(): monkeypatched run_metadata, no
    # network access. ---
    original_run_metadata = vc.run_metadata
    try:
        vc.run_metadata = lambda run, email=None, api_key=None: (
            {"run": run, "biosample": "SAMN1", "bioproject": "PRJNA1",
             "platform": "OXFORD_NANOPORE", "layout": "SINGLE"} if run == "SRR100"
            else {"run": run, "biosample": "SAMN1", "bioproject": "PRJNA1",
                  "platform": "ILLUMINA", "layout": "PAIRED"}
        )
        row = base_row(truth_source="self_assembled_hybrid", assembly_accession="",
                       sra_run="SRR2", long_read_sra_run="SRR100", truth_quality_tier="B")
        result = vc.verify_row(row, None, None)
        assert result["errors"] == [], result["errors"]
        assert result["assembly"]["derived_truth_technology"] == "hybrid"
        print("verify_self_assembled_row accepts a matching long-read + paired-Illumina pair -> PASS")

        # A long-read run that is actually Illumina (a labeling mistake, or a
        # wrong accession) must be caught, not silently accepted.
        vc.run_metadata = lambda run, email=None, api_key=None: {
            "run": run, "biosample": "SAMN1", "bioproject": "PRJNA1", "platform": "ILLUMINA", "layout": "PAIRED",
        }
        result = vc.verify_row(row, None, None)
        assert any("not Oxford Nanopore or PacBio" in e for e in result["errors"]), result["errors"]
        print("a long_read_sra_run that is not actually a long-read platform is caught, not accepted -> PASS")
    finally:
        vc.run_metadata = original_run_metadata

    print("\nALL SELF-ASSEMBLED HYBRID SCHEMA TESTS PASSED")


if __name__ == "__main__":
    main()
