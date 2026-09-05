#!/usr/bin/env python3
"""Discover strict candidate pairs from NCBI for one or more organism names.

This is a discovery and evidence-producing tool, not a claim that every public
record is biologically matched. It accepts a pair only when the deposited
assembly and paired Illumina run have the exact same BioSample and BioProject.
"""

import argparse
import csv
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request

from curate_cohort import OUT_COLUMNS, safe_id, write_rows
from validate_cohort import assembly_metadata, fetch, ncbi_json, request_interval


def runinfo_for_biosample(biosample, email, api_key, platform_term="ILLUMINA[Platform]"):
    """Return all deposited SRA run-info rows linked to one BioSample matching
    the given platform term (default Illumina; pass a long-read platform term
    to instead list ONT/PacBio runs)."""
    result = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", {
        "db": "sra", "term": f"{biosample}[BioSample] AND {platform_term}", "retmax": 100,
    }, email, api_key)
    ids = result["esearchresult"].get("idlist", [])
    if not ids:
        return []
    params = {"db": "sra", "id": ",".join(ids), "rettype": "runinfo", "retmode": "text"}
    if email: params["email"] = email
    if api_key: params["api_key"] = api_key
    request = Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(params),
                      headers={"User-Agent": "PlasBench/0.1 cohort discovery"})
    # Shared retry: a dropped keep-alive here would otherwise discard the row.
    runinfo = fetch(request, 60, 4, "NCBI run-info request",
                    parse=lambda payload: payload.decode("utf-8", "replace"))
    return list(csv.DictReader(runinfo.splitlines()))


def long_read_runs_for_biosample(biosample, email, api_key):
    """Return every ONT/PacBio SRA run deposited for one BioSample.

    This is an informational hint only, surfaced so a curator reviewing a
    candidate notices when more than one long-read run exists for its
    BioSample -- one may have built the truth assembly while another is held
    out, which is exactly the kind of pair docs/FINDING_DATA.md's long-read
    track needs. NCBI metadata cannot say which run (if any) is independent;
    only a curator checking the source publication can, so this never sets
    truth_independent_of_long_reads itself -- see scripts/lib.sh:
    long_read_truth_eligible for where that declaration is actually consumed.
    """
    return runinfo_for_biosample(
        biosample, email, api_key,
        platform_term="(OXFORD_NANOPORE[Platform] OR PACBIO_SMRT[Platform])",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organism", action="append", required=True,
                        help="Scientific name to search; repeat for each taxon.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--country", action="append", default=[],
                        help="Require a country/place term in deposited BioSample geo_loc_name; repeat as needed.")
    parser.add_argument("--max-assemblies", type=int, default=30,
                        help="Maximum complete assemblies inspected per organism (default: 30).")
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL"))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    args = parser.parse_args()
    if args.max_assemblies < 1:
        raise SystemExit("ERROR: --max-assemblies must be positive")
    accepted, rejected, seen = [], [], set()
    for organism in args.organism:
        query = f'"{organism}"[Organism] AND "complete genome"[Assembly Level]'
        if args.country:
            query += " AND (" + " OR ".join(f'\"{country}\"[All Fields]' for country in args.country) + ")"
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
                origin_evidence = "; ".join(value for value in (
                    assembly.get("geo_loc_name", ""), assembly.get("isolation_source", ""),
                    assembly.get("host", "")) if value)
                if args.country and not any(re.search(re.escape(country), assembly.get("geo_loc_name", ""), re.IGNORECASE)
                                            for country in args.country):
                    rejected.append({"assembly_accession": accession, "biosample": assembly.get("biosample", ""),
                                     "organism_query": organism, "country_query": ", ".join(args.country),
                                     "country_evidence": origin_evidence,
                                     "reason": "BioSample geo_loc_name does not confirm requested country/place"}); continue
                if assembly["assembly_status"].lower() != "complete genome":
                    rejected.append({"assembly_accession": accession, "biosample": assembly.get("biosample", ""), "organism_query": organism, "country_query": ", ".join(args.country), "country_evidence": origin_evidence, "sequencing_tech": assembly.get("sequencing_tech", ""), "reason": "assembly is not Complete Genome"}); continue
                if not assembly["has_plasmid"]:
                    rejected.append({"assembly_accession": accession, "biosample": assembly.get("biosample", ""), "organism_query": organism, "country_query": ", ".join(args.country), "country_evidence": origin_evidence, "sequencing_tech": assembly.get("sequencing_tech", ""), "reason": "assembly does not declare plasmid replicons"}); continue
                if not assembly["derived_truth_technology"]:
                    rejected.append({"assembly_accession": accession, "biosample": assembly.get("biosample", ""), "organism_query": organism, "country_query": ", ".join(args.country), "country_evidence": origin_evidence, "sequencing_tech": assembly.get("sequencing_tech", ""),
                                     "reason": "Datasets v2 has no explicit long-read sequencing evidence"}); continue
                runs = runinfo_for_biosample(assembly["biosample"], args.email, args.api_key)
                paired = [run for run in runs if run.get("Platform", "").upper() == "ILLUMINA" and run.get("LibraryLayout", "").upper() == "PAIRED"
                          and run.get("BioSample") == assembly["biosample"] and run.get("BioProject") in assembly["bioprojects"]]
                if not paired:
                    rejected.append({"assembly_accession": accession, "biosample": assembly["biosample"], "organism_query": organism, "country_query": ", ".join(args.country), "country_evidence": origin_evidence, "sequencing_tech": assembly.get("sequencing_tech", ""),
                                     "reason": "no linked paired-end Illumina run with matching BioProject"}); continue
                # One assembly is one biological benchmark unit. Prefer the
                # deepest paired run and retain alternates for curator review.
                paired.sort(key=lambda row: int(row.get("bases") or 0), reverse=True)
                selected, alternates = paired[0], ",".join(row["Run"] for row in paired[1:])
                # Informational only: surfaces a possible independent-long-read
                # pair for the long-read/hybrid track (docs/FINDING_DATA.md).
                # Never populated for a normal single-run BioSample, since one
                # run is the expected, uninteresting case -- only worth a
                # curator's attention when there is a genuine choice.
                long_read_runs = long_read_runs_for_biosample(assembly["biosample"], args.email, args.api_key)
                extra_long_read_runs = (",".join(run["Run"] for run in long_read_runs)
                                        if len(long_read_runs) > 1 else "")
                accepted.append({
                        "sample_id": safe_id(f"{assembly['organism']}_{accession.split('_')[1].split('.')[0]}", len(accepted) + 1),
                        "assembly_accession": accession, "sra_run": selected["Run"], "organism": assembly["organism"],
                        # Discovery never reviews the source publication, so these
                        # rows are tier B until a curator supplies a real study.
                        "truth_technology": assembly["derived_truth_technology"], "truth_quality_tier": "B",
                        "biosample": assembly["biosample"], "bioproject": selected["BioProject"], "sample_origin": origin_evidence,
                        "read_depth_x": "", "assembly_plasmid_count": "", "source_study": "NCBI_discovery_pending_publication_review",
                        "alternate_paired_runs": alternates,
                        "candidate_extra_long_read_runs": extra_long_read_runs,
                    })
            except Exception as exc:
                rejected.append({"assembly_accession": locals().get("accession", "unknown"), "organism_query": organism,
                                 "reason": f"metadata lookup failed: {exc}"})
            finally:
                # Pace failures as well as successes: an unpaced error path is
                # exactly what turns transient rate limiting into a cascade.
                time.sleep(request_interval(args.api_key))
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "accepted.tsv", accepted, OUT_COLUMNS)
    rejected_fields = ("assembly_accession", "biosample", "organism_query", "country_query", "country_evidence", "sequencing_tech", "reason")
    write_rows(out / "rejected.tsv", rejected, rejected_fields)
    print(f"NCBI discovery complete: accepted_pairs={len(accepted)} rejected_assemblies={len(rejected)}")
    print(f"Review {out / 'accepted.tsv'} against publications before a cohort release.")


if __name__ == "__main__":
    main()
