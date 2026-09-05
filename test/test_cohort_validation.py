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
    # A lock is only trustworthy when its checksum matches AND it carries the
    # sequencing evidence backing the long-read truth claim. Each of these locks
    # has a VALID checksum, so only the schema/evidence checks can reject them.
    digest = hashlib.sha256(open(panel, "rb").read()).hexdigest()
    evidence = [{"sample_id": "x", "assembly": {"derived_truth_technology": "hybrid"}}]
    cases = [
        ("current lock with evidence", "1.1", evidence, True, ""),
        ("pre-evidence 1.0 lock", "1.0", evidence, False, "predates the sequencing-evidence fields"),
        ("current lock, no long-read evidence", "1.1",
         [{"sample_id": "x", "assembly": {}}], False, "no long-read sequencing evidence"),
    ]
    for label, version, records, should_pass, expected in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump({"schema_version": version, "sample_sheet": "public-v1.tsv",
                       "sample_sheet_sha256": digest, "evidence": records}, handle)
            lock = handle.name
        try:
            result = subprocess.run([sys.executable, VALIDATOR, "--samples", panel,
                                     "--verify-lock", lock], text=True, capture_output=True)
            assert (result.returncode == 0) is should_pass, f"{label}: rc={result.returncode}"
            assert expected in result.stderr, f"{label}: {result.stderr!r}"
        finally:
            os.unlink(lock)

    # Both shipped panels must verify against their committed locks.
    for name in ("public-v1", "public-v2"):
        subprocess.run([sys.executable, VALIDATOR,
                        "--samples", os.path.join(ROOT, "cohorts", f"{name}.tsv"),
                        "--verify-lock", os.path.join(ROOT, "cohorts", f"{name}.lock.json")], check=True)
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\tread_depth_x\n")
        handle.write("bad\tGCF_000000000.1\tSRR0000001\tExample\thybrid\tA\tSAMN1\tPRJNA1\tnot-a-number\n")
        invalid = handle.name
    try:
        result = subprocess.run([sys.executable, VALIDATOR, "--samples", invalid], text=True, capture_output=True)
        assert result.returncode != 0 and "read_depth_x must be numeric" in result.stderr
    finally:
        os.unlink(invalid)

    # truth_independent_of_long_reads is optional (absent/empty means "assume
    # circular" -- see scripts/lib.sh: long_read_truth_eligible), but a typo'd
    # value must still be caught rather than silently mean "circular".
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\ttruth_independent_of_long_reads\n")
        handle.write("bad\tGCF_000000000.1\tSRR0000001\tExample\thybrid\tA\tSAMN1\tPRJNA1\tmaybe\n")
        invalid = handle.name
    try:
        result = subprocess.run([sys.executable, VALIDATOR, "--samples", invalid], text=True, capture_output=True)
        assert result.returncode != 0 and "truth_independent_of_long_reads must be" in result.stderr
    finally:
        os.unlink(invalid)
    # A recognized value (any case) passes cleanly.
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False, encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\ttruth_independent_of_long_reads\n")
        handle.write("ok\tGCF_000000000.1\tSRR0000001\tExample\thybrid\tA\tSAMN1\tPRJNA1\tYES\n")
        valid = handle.name
    try:
        subprocess.run([sys.executable, VALIDATOR, "--samples", valid], check=True)
    finally:
        os.unlink(valid)
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
