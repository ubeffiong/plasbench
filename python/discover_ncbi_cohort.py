#!/usr/bin/env python3
"""Discover strict candidate pairs from NCBI for one or more organism names.

This is a discovery and evidence-producing tool, not a claim that every public
record is biologically matched. It accepts a pair only when the deposited
assembly and paired Illumina run have the exact same BioSample and BioProject.
"""

import argparse
import csv
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from curate_cohort import OUT_COLUMNS, safe_id, write_rows
from validate_cohort import assembly_metadata, ncbi_json


def runinfo_for_biosample(biosample, email, api_key):
    """Return all deposited SRA run-info rows linked to one BioSample."""
    result = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", {
        "db": "sra", "term": f"{biosample}[BioSample] AND ILLUMINA[Platform]", "retmax": 100,
    }, email, api_key)
    ids = result["esearchresult"].get("idlist", [])
    if not ids:
        return []
    params = {"db": "sra", "id": ",".join(ids), "rettype": "runinfo", "retmode": "text"}
    if email: params["email"] = email
    if api_key: params["api_key"] = api_key
    request = Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(params),
                      headers={"User-Agent": "PlasBench/0.1 cohort discovery"})
    with urlopen(request, timeout=60) as response:
        return list(csv.DictReader(response.read().decode("utf-8").splitlines()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organism", action="append", required=True,
                        help="Scientific name to search; repeat for each taxon.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-assemblies", type=int, default=30,
                        help="Maximum complete assemblies inspected per organism (default: 30).")
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL"))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    parser.add_argument("--truth-technology", choices=("long_read", "hybrid"), default="hybrid")
    parser.add_argument("--quality-tier", choices=("A", "B", "C"), default="A")
    args = parser.parse_args()
    if args.max_assemblies < 1:
        raise SystemExit("ERROR: --max-assemblies must be positive")
    accepted, rejected, seen = [], [], set()
    for organism in args.organism:
        query = f'"{organism}"[Organism] AND "complete genome"[Assembly Level]'
        result = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", {
            "db": "assembly", "term": query, "retmax": args.max_assemblies, "sort": "date",
        }, args.email, args.api_key)
        identifiers = result["esearchresult"].get("idlist", [])
        print(f"[discovery] {organism}: inspecting {len(identifiers)} complete-assembly candidate(s)", flush=True)
        for position, uid in enumerate(identifiers, 1):
            try:
                summary = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", {
                    "db": "assembly", "id": uid,
                }, args.email, args.api_key)["result"][uid]
                accession = summary["assemblyaccession"]
                if accession in seen: continue
                seen.add(accession)
                print(f"[discovery] {organism}: {position}/{len(identifiers)} {accession}", flush=True)
                assembly = assembly_metadata(accession, args.email, args.api_key)
                if assembly["assembly_status"].lower() != "complete genome":
                    rejected.append({"assembly_accession": accession, "organism_query": organism, "reason": "assembly is not Complete Genome"}); continue
                if not assembly["has_plasmid"]:
                    rejected.append({"assembly_accession": accession, "organism_query": organism, "reason": "assembly does not declare plasmid replicons"}); continue
                runs = runinfo_for_biosample(assembly["biosample"], args.email, args.api_key)
                paired = [run for run in runs if run.get("Platform", "").upper() == "ILLUMINA" and run.get("LibraryLayout", "").upper() == "PAIRED"
                          and run.get("BioSample") == assembly["biosample"] and run.get("BioProject") in assembly["bioprojects"]]
                if not paired:
                    rejected.append({"assembly_accession": accession, "biosample": assembly["biosample"], "organism_query": organism,
                                     "reason": "no linked paired-end Illumina run with matching BioProject"}); continue
                for run in paired:
                    accepted.append({
                        "sample_id": safe_id(f"{assembly['organism']}_{accession.split('_')[1].split('.')[0]}", len(accepted) + 1),
                        "assembly_accession": accession, "sra_run": run["Run"], "organism": assembly["organism"],
                        "truth_technology": args.truth_technology, "truth_quality_tier": args.quality_tier,
                        "biosample": assembly["biosample"], "bioproject": run["BioProject"], "sample_origin": "",
                        "read_depth_x": "", "assembly_plasmid_count": "", "source_study": "NCBI_discovery_pending_publication_review",
                    })
                time.sleep(0.11 if args.api_key else 0.34)
            except Exception as exc:
                rejected.append({"assembly_accession": locals().get("accession", "unknown"), "organism_query": organism,
                                 "reason": f"metadata lookup failed: {exc}"})
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "accepted.tsv", accepted, OUT_COLUMNS)
    rejected_fields = ("assembly_accession", "biosample", "organism_query", "reason")
    write_rows(out / "rejected.tsv", rejected, rejected_fields)
    print(f"NCBI discovery complete: accepted_pairs={len(accepted)} rejected_assemblies={len(rejected)}")
    print(f"Review {out / 'accepted.tsv'} against publications before a cohort release.")


if __name__ == "__main__":
    main()
