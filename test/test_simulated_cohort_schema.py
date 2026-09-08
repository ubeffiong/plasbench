#!/usr/bin/env python3
"""Regression for validate_cohort.py's truth_source=simulated schema
support: the opposite shape from self_assembled_hybrid -- assembly_accession
is a REAL, independently-deposited reference (so it IS the truth, unchanged,
and IS verified against NCBI), but sra_run is never a real SRA accession
(it is reused as the local simulated-read file prefix, so the RUN regex is
skipped for it), and simulation_seed/simulation_short_depth_x/
simulation_long_depth_x provenance fields are required. Also covers
verify_simulated_row()'s own NCBI cross-check (no real network access --
monkeypatched assembly_metadata()).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import validate_cohort as vc  # noqa: E402

FIELDS = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
          "truth_quality_tier", "biosample", "bioproject", "truth_source",
          "simulation_seed", "simulation_short_depth_x", "simulation_long_depth_x")


def base_row(**overrides):
    row = {
        "sample_id": "s1", "assembly_accession": "GCF_1.1", "sra_run": "SIMULATED",
        "organism": "Escherichia coli", "truth_technology": "long_read", "truth_quality_tier": "A",
        "biosample": "SAMN1", "bioproject": "PRJNA1", "truth_source": "simulated",
        "simulation_seed": "42", "simulation_short_depth_x": "60", "simulation_long_depth_x": "40",
    }
    row.update(overrides)
    return row


def main():
    # --- Case 1: a well-formed simulated row passes. ---
    errors = vc.schema_errors([base_row()], FIELDS)
    assert errors == [], errors
    print("a well-formed truth_source=simulated row validates -> PASS")

    # --- Case 2: simulated still requires a REAL assembly_accession -- this
    # is the opposite exemption from self_assembled_hybrid. ---
    row = base_row(assembly_accession="")
    errors = vc.schema_errors([row], FIELDS)
    assert any("requires a valid assembly_accession" in e for e in errors), errors
    print("truth_source=simulated still requires a real assembly_accession -> PASS")

    # --- Case 3: sra_run is NOT validated as a real SRA accession for a
    # simulated row -- any filesystem-safe local prefix is accepted. ---
    row = base_row(sra_run="my_sim_reads")
    errors = vc.schema_errors([row], FIELDS)
    assert errors == [], errors
    print("truth_source=simulated accepts a non-SRA-shaped sra_run (local read-file prefix) -> PASS")

    # --- Case 4: an empty or unsafe sra_run is still rejected (it becomes a
    # filename prefix downstream, so it cannot be blank or path-breaking). ---
    row = base_row(sra_run="")
    errors = vc.schema_errors([row], FIELDS)
    assert any("filesystem-safe sra_run" in e for e in errors), errors
    print("truth_source=simulated rejects an empty sra_run -> PASS")

    # --- Case 5: simulation_seed/short_depth/long_depth are all required. ---
    for missing_field, expected_message in (
        ("simulation_seed", "requires an integer simulation_seed"),
        ("simulation_short_depth_x", "requires simulation_short_depth_x > 0"),
        ("simulation_long_depth_x", "requires simulation_long_depth_x > 0"),
    ):
        row = base_row(**{missing_field: ""})
        errors = vc.schema_errors([row], FIELDS)
        assert any(expected_message in e for e in errors), (missing_field, errors)
    print("truth_source=simulated requires simulation_seed/short_depth_x/long_depth_x -> PASS")

    # --- Case 6: a non-numeric depth or non-integer seed is rejected, not
    # silently coerced. ---
    row = base_row(simulation_seed="not_an_int")
    errors = vc.schema_errors([row], FIELDS)
    assert any("requires an integer simulation_seed" in e for e in errors), errors
    row = base_row(simulation_short_depth_x="lots")
    errors = vc.schema_errors([row], FIELDS)
    assert any("simulation_short_depth_x must be numeric" in e for e in errors), errors
    print("non-numeric simulation_seed/simulation_short_depth_x are rejected -> PASS")

    # --- verify_simulated_row(): monkeypatched assembly_metadata, no network
    # access. A simulated row's truth is a REAL assembly, so it is checked
    # against the exact same Complete-Genome/plasmid-replicon bar as any
    # ncbi_deposited row, with no SRA-run check at all (sra_run isn't real). ---
    original_assembly_metadata = vc.assembly_metadata
    try:
        vc.assembly_metadata = lambda accession, email=None, api_key=None: {
            "assembly_status": "Complete Genome", "datasets_assembly_level": "Complete Genome",
            "has_plasmid": True, "biosample": "SAMN1", "bioprojects": ["PRJNA1"],
        }
        row = base_row()
        result = vc.verify_row(row, None, None)
        assert result["errors"] == [], result["errors"]
        assert result["run"] is None and result["long_read_run"] is None
        print("verify_simulated_row accepts a real Complete Genome reference with no SRA-run check -> PASS")

        # An incomplete or plasmid-free reference must still be caught --
        # simulating from it would be exactly as meaningless as scoring
        # against it directly.
        vc.assembly_metadata = lambda accession, email=None, api_key=None: {
            "assembly_status": "Contig", "datasets_assembly_level": "Contig",
            "has_plasmid": False, "biosample": "SAMN1", "bioprojects": ["PRJNA1"],
        }
        result = vc.verify_row(row, None, None)
        assert any("not Complete Genome" in e for e in result["errors"]), result["errors"]
        assert any("does not declare plasmid replicons" in e for e in result["errors"]), result["errors"]
        print("verify_simulated_row still enforces Complete Genome + plasmid replicons on the reference -> PASS")
    finally:
        vc.assembly_metadata = original_assembly_metadata

    print("\nALL SIMULATED COHORT SCHEMA TESTS PASSED")


if __name__ == "__main__":
    main()
