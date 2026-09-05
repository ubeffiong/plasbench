#!/usr/bin/env python3
"""Regression for discover_ncbi_cohort.py's long-read-run discovery hint
(candidate_extra_long_read_runs): it must query for ONT/PacBio platforms, not
Illumina, and must never itself decide truth_independent_of_long_reads --
that stays a curator's manual declaration (see docs/FINDING_DATA.md).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import discover_ncbi_cohort as dnc


def main():
    captured_terms = []

    def fake_ncbi_json(url, params, email, api_key):
        captured_terms.append(params["term"])
        return {"esearchresult": {"idlist": ["1", "2"]}}

    def fake_fetch(request, timeout, retries, label, parse):
        runinfo = (
            "Run,Platform,BioSample\n"
            "SRR_ONT_1,OXFORD_NANOPORE,SAMN1\n"
            "SRR_ONT_2,OXFORD_NANOPORE,SAMN1\n"
        )
        return parse(runinfo.encode("utf-8"))

    original_ncbi_json, original_fetch = dnc.ncbi_json, dnc.fetch
    dnc.ncbi_json, dnc.fetch = fake_ncbi_json, fake_fetch
    try:
        runs = dnc.long_read_runs_for_biosample("SAMN1", None, None)
    finally:
        dnc.ncbi_json, dnc.fetch = original_ncbi_json, original_fetch

    assert len(runs) == 2, f"expected 2 long-read runs, got {runs}"
    assert {r["Run"] for r in runs} == {"SRR_ONT_1", "SRR_ONT_2"}
    assert "OXFORD_NANOPORE" in captured_terms[0] and "PACBIO_SMRT" in captured_terms[0], (
        f"expected the query term to target long-read platforms, got: {captured_terms[0]!r}"
    )
    assert "ILLUMINA" not in captured_terms[0]
    print("long_read_runs_for_biosample queries ONT/PacBio platforms, not Illumina -> PASS")

    # Exactly one long-read run is the expected, uninteresting case -- the
    # hint column exists only for the "there's a choice to review" case.
    def fake_fetch_one(request, timeout, retries, label, parse):
        return parse(b"Run,Platform,BioSample\nSRR_ONT_1,OXFORD_NANOPORE,SAMN1\n")

    dnc.ncbi_json, dnc.fetch = fake_ncbi_json, fake_fetch_one
    try:
        runs = dnc.long_read_runs_for_biosample("SAMN1", None, None)
    finally:
        dnc.ncbi_json, dnc.fetch = original_ncbi_json, original_fetch
    assert len(runs) == 1
    print("a single long-read run is returned but is the caller's job to treat as uninteresting -> PASS")

    print("ALL DISCOVER LONG-READ HINT TESTS PASSED")


if __name__ == "__main__":
    main()
