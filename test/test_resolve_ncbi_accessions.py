#!/usr/bin/env python3
"""Regression for python/resolve_ncbi_accessions.py's resolve_one(): turns a
BioSample-only candidate into assembly_accession/sra_run, or a specific
rejection reason -- never a guess. Matches test_curate_cohort_dedup.py's
established monkeypatch convention (fake NCBI functions bound into the
module under test, no real network access).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import resolve_ncbi_accessions as rna  # noqa: E402


def esummary(accession, status="Complete Genome"):
    return {"assemblyaccession": accession, "assemblystatus": status}


def main():
    original_ncbi_json = rna.ncbi_json
    original_assembly_metadata = rna.assembly_metadata
    original_runinfo = rna.runinfo_for_biosample
    original_long_read_runs = rna.long_read_runs_for_biosample
    try:
        # --- Case 1: clean resolution -- one complete-genome assembly, one
        # matching paired Illumina run. ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: (
            {"esearchresult": {"idlist": ["1"]}} if endpoint == rna.ESEARCH
            else {"result": {"1": esummary("GCF_1.1")}}
        )
        rna.assembly_metadata = lambda accession, email=None, api_key=None: {
            "accession": accession, "biosample": "SAMN1", "bioprojects": ["PRJNA1"],
        }
        rna.runinfo_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR1", "BioSample": "SAMN1", "BioProject": "PRJNA1",
             "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "bases": "100"},
        ]
        fields, reason = rna.resolve_one({"biosample": "SAMN1"}, None, None)
        assert fields == {"assembly_accession": "GCF_1.1", "sra_run": "SRR1",
                          "bioproject": "PRJNA1", "alternate_paired_runs": ""}, fields
        assert "resolved to GCF_1.1 / SRR1" in reason
        print("a BioSample with one complete assembly and one matching paired run resolves cleanly -> PASS")

        # --- Case 2: no assembly deposited at all. ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: {"esearchresult": {"idlist": []}}
        fields, reason = rna.resolve_one({"biosample": "SAMN2"}, None, None)
        assert fields is None
        assert "no assembly deposited for BioSample SAMN2" in reason, reason
        print("a BioSample with no deposited assembly is rejected with a specific reason -> PASS")

        # --- Case 3: assemblies exist but none is Complete Genome. ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: (
            {"esearchresult": {"idlist": ["1"]}} if endpoint == rna.ESEARCH
            else {"result": {"1": esummary("GCA_2.1", status="Contig")}}
        )
        fields, reason = rna.resolve_one({"biosample": "SAMN3"}, None, None)
        assert fields is None
        assert "no complete-genome assembly found for BioSample SAMN3" in reason, reason
        assert "1 non-complete candidate" in reason, reason
        print("a BioSample with only non-complete assemblies is rejected, not guessed at -> PASS")

        # --- Case 4: two complete-genome assemblies -- ambiguous, never
        # silently picked. ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: (
            {"esearchresult": {"idlist": ["1", "2"]}} if endpoint == rna.ESEARCH
            else {"result": {"1": esummary("GCF_4.1"), "2": esummary("GCA_4.1")}}
        )
        fields, reason = rna.resolve_one({"biosample": "SAMN4"}, None, None)
        assert fields is None
        assert "ambiguous: 2 complete-genome assemblies" in reason, reason
        assert "GCA_4.1" in reason and "GCF_4.1" in reason, reason
        print("a BioSample with two complete-genome assemblies is flagged ambiguous, never guessed -> PASS")

        # --- Case 5: assembly resolves but no paired Illumina run matches
        # its BioProject. ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: (
            {"esearchresult": {"idlist": ["1"]}} if endpoint == rna.ESEARCH
            else {"result": {"1": esummary("GCF_5.1")}}
        )
        rna.assembly_metadata = lambda accession, email=None, api_key=None: {
            "accession": accession, "biosample": "SAMN5", "bioprojects": ["PRJNA5"],
        }
        rna.runinfo_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR5", "BioSample": "SAMN5", "BioProject": "PRJNA_OTHER",
             "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "bases": "100"},
        ]
        fields, reason = rna.resolve_one({"biosample": "SAMN5"}, None, None)
        assert fields is None
        assert "GCF_5.1 found, but no paired Illumina run matches its BioProject" in reason, reason
        print("an assembly with no BioProject-matching paired run is rejected, not force-matched -> PASS")

        # --- Case 6: multiple paired runs -- deepest wins, rest listed as
        # alternates (same convention as discover_ncbi_cohort.py). ---
        rna.ncbi_json = lambda endpoint, params, email=None, api_key=None: (
            {"esearchresult": {"idlist": ["1"]}} if endpoint == rna.ESEARCH
            else {"result": {"1": esummary("GCF_6.1")}}
        )
        rna.assembly_metadata = lambda accession, email=None, api_key=None: {
            "accession": accession, "biosample": "SAMN6", "bioprojects": ["PRJNA6"],
        }
        rna.runinfo_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR_SHALLOW", "BioSample": "SAMN6", "BioProject": "PRJNA6",
             "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "bases": "50"},
            {"Run": "SRR_DEEP", "BioSample": "SAMN6", "BioProject": "PRJNA6",
             "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "bases": "500"},
        ]
        fields, reason = rna.resolve_one({"biosample": "SAMN6"}, None, None)
        assert fields["sra_run"] == "SRR_DEEP" and fields["alternate_paired_runs"] == "SRR_SHALLOW", fields
        print("the deepest paired run is selected; shallower ones are kept as alternates -> PASS")

        # --- Case 7: self-build fallback -- no complete-genome assembly, but
        # a long-read run AND a paired Illumina run exist on the same
        # BioSample/BioProject. ---
        rna.long_read_runs_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR_ONT", "BioSample": "SAMN7", "BioProject": "PRJNA7", "Platform": "OXFORD_NANOPORE", "bases": "900"},
        ]
        rna.runinfo_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR_SHORT", "BioSample": "SAMN7", "BioProject": "PRJNA7",
             "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "bases": "400"},
        ]
        fields, reason = rna.resolve_self_build_fallback({"biosample": "SAMN7"}, None, None)
        assert fields == {"sra_run": "SRR_SHORT", "long_read_sra_run": "SRR_ONT", "bioproject": "PRJNA7",
                          "alternate_long_read_runs": "", "alternate_paired_runs": ""}, fields
        assert "self-build candidate: long read SRR_ONT + short read SRR_SHORT" in reason
        print("a BioSample with deposited long+short reads but no assembly resolves as a self-build candidate -> PASS")

        # --- Case 8: self-build fallback fails too -- no long-read run at
        # all, so there is nothing to self-build from. ---
        rna.long_read_runs_for_biosample = lambda biosample, email=None, api_key=None: []
        fields, reason = rna.resolve_self_build_fallback({"biosample": "SAMN8"}, None, None)
        assert fields is None
        assert "no long-read (ONT/PacBio) run deposited for BioSample SAMN8 either" in reason, reason
        print("a BioSample with no long-read run either fails the self-build fallback too, with its own reason -> PASS")

        # --- Case 9: a long-read run exists, but no paired Illumina run to
        # pair it with. ---
        rna.long_read_runs_for_biosample = lambda biosample, email=None, api_key=None: [
            {"Run": "SRR_ONT9", "BioSample": "SAMN9", "BioProject": "PRJNA9", "Platform": "OXFORD_NANOPORE", "bases": "900"},
        ]
        rna.runinfo_for_biosample = lambda biosample, email=None, api_key=None: []
        fields, reason = rna.resolve_self_build_fallback({"biosample": "SAMN9"}, None, None)
        assert fields is None
        assert "no paired Illumina run to pair it with" in reason, reason
        print("a long-read run with no paired Illumina run fails the self-build fallback, not force-matched -> PASS")
    finally:
        rna.ncbi_json = original_ncbi_json
        rna.assembly_metadata = original_assembly_metadata
        rna.runinfo_for_biosample = original_runinfo
        rna.long_read_runs_for_biosample = original_long_read_runs

    print("\nALL RESOLVE NCBI ACCESSIONS TESTS PASSED")


if __name__ == "__main__":
    main()
