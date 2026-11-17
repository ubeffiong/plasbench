#!/usr/bin/env python3
"""discover_ncbi_cohort.py --negative-controls: plasmid-free complete genomes become candidates, and plasmid-bearing ones are rejected (and the reverse without the flag)."""

import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import discover_ncbi_cohort as dnc  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


ASSEMBLIES = {
    "GCF_000000001.1": {"biosample": "SAMN1", "has_plasmid": False},
    "GCF_000000002.1": {"biosample": "SAMN2", "has_plasmid": True},
}


def fake_ncbi_json(url, params, email, api_key):
    if "esearch" in url:
        return {"esearchresult": {"idlist": ["1", "2"]}}
    uid = params["id"]
    return {"result": {uid: {"assemblyaccession": f"GCF_00000000{uid}.1"}}}


def fake_metadata(accession, email, api_key):
    base = ASSEMBLIES[accession]
    return {"accession": accession, "biosample": base["biosample"], "bioprojects": ["PRJNA1"], "organism": "Escherichia coli", "assembly_status": "Complete Genome",
            "has_plasmid": base["has_plasmid"], "derived_truth_technology": "hybrid", "geo_loc_name": "", "isolation_source": "", "host": "", "sequencing_tech": "ONT; Illumina"}


def fake_runinfo(biosample, email, api_key, platform_term="ILLUMINA[Platform]"):
    return [{"Run": "SRR" + biosample[-1], "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioSample": biosample, "BioProject": "PRJNA1", "bases": "1000"}]


def run(extra):
    with tempfile.TemporaryDirectory() as d:
        saved = (dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample, dnc.long_read_runs_for_biosample, dnc.time.sleep, sys.argv)
        dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample = fake_ncbi_json, fake_metadata, fake_runinfo
        dnc.long_read_runs_for_biosample = lambda *a, **k: []
        dnc.time.sleep = lambda s: None
        sys.argv = ["discover_ncbi_cohort.py", "--organism", "Escherichia coli", "--out-dir", d, *extra]
        try:
            dnc.main()
        finally:
            dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample, dnc.long_read_runs_for_biosample, dnc.time.sleep, sys.argv = saved
        read = lambda name: list(csv.DictReader(open(os.path.join(d, name), encoding="utf-8"), delimiter=chr(9)))  # noqa: E731
        return read("accepted.tsv"), read("rejected.tsv")


accepted, rejected = run([])
check("without the flag the plasmid-bearing assembly is accepted and the plasmid-free one rejected", [r["biosample"] for r in accepted] == ["SAMN2"]
      and [r["reason"] for r in rejected] == ["assembly does not declare plasmid replicons"], (accepted, rejected))
accepted, rejected = run(["--negative-controls"])
check("with --negative-controls the plasmid-free assembly is the candidate", [r["biosample"] for r in accepted] == ["SAMN1"], accepted)
check("the plasmid-bearing assembly is rejected as not a negative control", [r["reason"] for r in rejected] == ["assembly declares plasmid replicons, so it is not a negative control"], rejected)
check("the candidate records zero plasmids and says it still needs review", accepted[0]["assembly_plasmid_count"] == "0" and "negative_control_pending_review" in accepted[0]["source_study"], accepted[0])

print("ALL DISCOVER NEGATIVE CONTROL TESTS PASSED" if ok else "DISCOVER NEGATIVE CONTROL TESTS FAILED")
sys.exit(0 if ok else 1)
