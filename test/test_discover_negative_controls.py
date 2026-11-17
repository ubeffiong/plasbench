#!/usr/bin/env python3
"""discover_ncbi_cohort.py --negative-controls: plasmid-free complete genomes become candidates, and plasmid-bearing ones are rejected (and the reverse without the flag)."""

import csv
import json
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
    return {"result": {uid: {"assemblyaccession": f"GCF_00000000{uid}.1"} for uid in params["id"].split(",")}}


DATASETS_CALLS = []


def fake_fetch(request, timeout, retries, label, parse):
    # the bulk Datasets report: assembly 1 is a single sequence, assembly 2 has a plasmid (3 sequences)
    DATASETS_CALLS.append(request.full_url)
    sizes = {"GCF_000000001.1": 1, "GCF_000000002.1": 3}
    wanted = request.full_url.split("/accession/")[1].split("/")[0].split(",")
    return parse(json.dumps({"reports": [{"accession": a, "assembly_stats": {"number_of_component_sequences": sizes[a]}} for a in wanted]}).encode())


def fake_metadata(accession, email, api_key):
    base = ASSEMBLIES[accession]
    return {"accession": accession, "biosample": base["biosample"], "bioprojects": ["PRJNA1"], "organism": "Escherichia coli", "assembly_status": "Complete Genome",
            "has_plasmid": base["has_plasmid"], "derived_truth_technology": "hybrid", "geo_loc_name": "", "isolation_source": "", "host": "", "sequencing_tech": "ONT; Illumina"}


def fake_runinfo(biosample, email, api_key, platform_term="ILLUMINA[Platform]"):
    return [{"Run": "SRR" + biosample[-1], "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioSample": biosample, "BioProject": "PRJNA1", "bases": "1000"}]


def run(extra):
    with tempfile.TemporaryDirectory() as d:
        saved = (dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample, dnc.long_read_runs_for_biosample, dnc.time.sleep, sys.argv, dnc.fetch)
        dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample, dnc.fetch = fake_ncbi_json, fake_metadata, fake_runinfo, fake_fetch
        dnc.long_read_runs_for_biosample = lambda *a, **k: []
        dnc.time.sleep = lambda s: None
        sys.argv = ["discover_ncbi_cohort.py", "--organism", "Escherichia coli", "--out-dir", d, *extra]
        try:
            dnc.main()
        finally:
            dnc.ncbi_json, dnc.assembly_metadata, dnc.runinfo_for_biosample, dnc.long_read_runs_for_biosample, dnc.time.sleep, sys.argv, dnc.fetch = saved
        read = lambda name: list(csv.DictReader(open(os.path.join(d, name), encoding="utf-8"), delimiter=chr(9)))  # noqa: E731
        return read("accepted.tsv"), read("rejected.tsv")


accepted, rejected = run([])
check("without the flag the plasmid-bearing assembly is accepted and the plasmid-free one rejected", [r["biosample"] for r in accepted] == ["SAMN2"]
      and [r["reason"] for r in rejected] == ["assembly does not declare plasmid replicons"], (accepted, rejected))
accepted, rejected = run(["--negative-controls"])
check("with --negative-controls the plasmid-free assembly is the candidate", [r["biosample"] for r in accepted] == ["SAMN1"], accepted)
check("the plasmid-bearing assembly never reaches the per-assembly lookups: the bulk single-sequence filter removed it", rejected == [] and len(DATASETS_CALLS) == 1, (rejected, DATASETS_CALLS))
check("the bulk filter asked the Datasets report for both candidates in one request", "GCF_000000001.1,GCF_000000002.1" in DATASETS_CALLS[0], DATASETS_CALLS)
check("without --negative-controls the bulk filter is not used", len(DATASETS_CALLS) == 1)
check("the candidate records zero plasmids and says it still needs review", accepted[0]["assembly_plasmid_count"] == "0" and "negative_control_pending_review" in accepted[0]["source_study"], accepted[0])

print("ALL DISCOVER NEGATIVE CONTROL TESTS PASSED" if ok else "DISCOVER NEGATIVE CONTROL TESTS FAILED")
sys.exit(0 if ok else 1)
