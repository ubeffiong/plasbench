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
    # The quality tier grades curation confidence, so B must stay reachable for
    # rows whose evidence verifies but whose source study is still unreviewed.
    sys.path.insert(0, os.path.join(ROOT, "python"))
    from validate_cohort import derive_truth_quality_tier as tier
    import validate_cohort
    assert tier([], "Snyder_2020_recurrent_UTI") == "A"
    assert tier([], "Smith_2021_systematic_review") == "A"
    assert tier([], "NCBI_discovery_pending_publication_review") == "B"
    assert tier([], "needs_curator_review") == "B"
    assert tier([], "") == "B"
    assert tier(["assembly is not Complete Genome"], "Snyder_2020_recurrent_UTI") is None

    # Country-scoped discovery must use deposited BioSample evidence rather
    # than relying on an Assembly full-text result alone.
    original_fetch = validate_cohort.fetch
    try:
        validate_cohort.fetch = lambda request, timeout, retries, label, parse: parse(json.dumps({"reports": [{
            "assembly_info": {"sequencing_tech": "Illumina + Oxford Nanopore",
                              "assembly_method": "Unicycler",
                              "assembly_level": "Complete Genome",
                              "bioproject_accession": "PRJNA123",
                              "biosample": {"accession": "SAMN123", "geo_loc_name": "Nigeria: Abuja",
                                            "isolation_source": "clinical swab", "host": "human",
                                            "collection_date": "2025-01-01"}}
        }]}).encode("utf-8"))
        evidence = validate_cohort.datasets_report("GCF_000000000.1")
    finally:
        validate_cohort.fetch = original_fetch
    assert evidence["geo_loc_name"] == "Nigeria: Abuja"
    assert evidence["isolation_source"] == "clinical swab"
    assert evidence["bioproject_accession"] == "PRJNA123"
    print("ALL COHORT VALIDATION TESTS PASSED")


if __name__ == "__main__":
    main()
