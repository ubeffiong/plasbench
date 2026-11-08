#!/usr/bin/env python3
"""
discover_design_cohort.py -- find NCBI isolates that satisfy the headline
design (docs/METHODS.md, "Research design"), species by species, until each
species reaches a target number of independent clusters.

An isolate is accepted only if ALL of these hold:
  * Complete Genome assembly declaring plasmid replicons, with a long-read
    platform recorded (validate_cohort.verify_row: the same online checks every
    released cohort row passes);
  * long-read-first construction (truth_provenance.classify_method), so its
    truth is reference tier <= 2;
  * exactly ONE paired-end Illumina run on its BioSample, sharing the
    assembly's BioSample and BioProject -- the benchmark reads, which are then
    recorded as the reads that polished the truth (truth_polish_reads =
    same_as_benchmark);
  * a BioProject not already used by the cohort (one isolate per BioProject,
    so each accepted isolate is its own independent cluster);
  * a BioSample not in any earlier cohort release (accepted_accessions ledger).

Newest releases are preferred, which also minimises overlap with the tools'
reference databases.

Output: a cohort-schema TSV (public-vN rows, truth_quality_tier B: verified
evidence, source study not yet curator-reviewed) plus an evidence TSV.

Standard library only; NCBI queried with NCBI_API_KEY if set, no email sent.
"""

import argparse
import csv
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_truth_provenance import get_json  # noqa: E402
from discover_ncbi_cohort import runinfo_for_biosample  # noqa: E402
from truth_provenance import classify_method  # noqa: E402
from validate_cohort import verify_row  # noqa: E402

TAXON_REPORT = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/{}/dataset_report"
COLUMNS = ["sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier",
           "biosample", "bioproject", "sample_origin", "read_depth_x", "assembly_plasmid_count", "source_study",
           "truth_assembly_strategy", "truth_polish_reads"]


def read_rows(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t"))


def complete_genomes(taxon, api_key, max_reports):
    """Yield Datasets reports for complete genomes of a taxon, newest first."""
    reports, token = [], None
    while len(reports) < max_reports:
        params = {"filters.assembly_level": "complete_genome", "page_size": 1000,
                  "filters.assembly_version": "current"}
        if token:
            params["page_token"] = token
        data = get_json(TAXON_REPORT.format(urllib.parse.quote(taxon)) + "?" + urllib.parse.urlencode(params), api_key)
        reports.extend(data.get("reports") or [])
        token = data.get("next_page_token")
        if not token:
            break
        time.sleep(0.15)
    reports.sort(key=lambda r: (r.get("assembly_info") or {}).get("release_date", ""), reverse=True)
    return reports[:max_reports]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--species", action="append", required=True, help="taxon name, e.g. 'Escherichia coli'")
    ap.add_argument("--target-clusters", type=int, default=22,
                    help="independent clusters wanted per species, counting --existing rows")
    ap.add_argument("--existing", help="current cohort TSV with provenance columns (counts toward targets)")
    ap.add_argument("--ledger", help="cohorts/accepted_accessions.tsv (BioSamples already released)")
    ap.add_argument("--max-reports", type=int, default=4000, help="newest complete genomes scanned per species")
    ap.add_argument("--max-checks", type=int, default=400, help="candidates checked online per species")
    ap.add_argument("--out", required=True)
    ap.add_argument("--evidence-out", required=True)
    ap.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    args = ap.parse_args()
    delay = 0.12 if args.api_key else 0.4

    existing = read_rows(args.existing)
    used_projects = {r.get("bioproject") for r in existing if r.get("bioproject")}
    used_biosamples = {r.get("biosample") for r in existing} | {r.get("biosample") for r in read_rows(args.ledger)}
    eligible_existing = {}
    for r in existing:
        if r.get("truth_assembly_strategy") in ("long_read_only", "long_read_first_hybrid"):
            species = " ".join((r.get("organism") or "").split()[:2])
            eligible_existing.setdefault(species, set()).add(r.get("bioproject"))

    accepted, evidence = [], []
    for species in args.species:
        have = len(eligible_existing.get(species, set()))
        need = max(0, args.target_clusters - have)
        sys.stderr.write(f"[discover] {species}: {have} eligible cluster(s) already; seeking {need}\n")
        if not need:
            continue
        found = checks = 0
        for report in complete_genomes(species, args.api_key, args.max_reports):
            if found >= need or checks >= args.max_checks:
                break
            info = report.get("assembly_info") or {}
            biosample = (info.get("biosample") or {}).get("accession", "")
            projects = [p.get("accession") for p in (info.get("bioproject_lineage") or [{}])[0].get("bioprojects", [])
                        if p.get("accession")]
            bioproject = projects[0] if projects else ""
            if not biosample or not bioproject or biosample in used_biosamples or bioproject in used_projects:
                continue
            strategy, _, reason = classify_method(info.get("assembly_method", ""), info.get("sequencing_tech", ""))
            if strategy != "long_read_first_hybrid":
                continue
            checks += 1
            runs = [r for r in runinfo_for_biosample(biosample, None, args.api_key)
                    if (r.get("Platform") or "").upper() == "ILLUMINA"]
            time.sleep(delay)
            if len(runs) != 1 or (runs[0].get("LibraryLayout") or "").upper() != "PAIRED":
                continue
            run = runs[0]
            organism = (report.get("organism") or {}).get("organism_name", species)
            row = {"sample_id": f"{slug(species)}_{slug(biosample)}", "assembly_accession": report.get("accession", ""),
                   "sra_run": run.get("Run", ""), "organism": organism, "truth_technology": "hybrid",
                   "truth_quality_tier": "B", "biosample": biosample, "bioproject": bioproject,
                   "sample_origin": "", "read_depth_x": "", "assembly_plasmid_count": "", "source_study": "",
                   "truth_assembly_strategy": strategy, "truth_polish_reads": "same_as_benchmark"}
            try:
                verdict = verify_row(row, None, args.api_key)
            except Exception as exc:  # NCBI hiccup: skip this candidate, keep going
                sys.stderr.write(f"[discover]   {row['assembly_accession']}: verification error {exc}\n")
                continue
            time.sleep(delay)
            if verdict["errors"]:
                continue
            accepted.append(row)
            used_projects.add(bioproject)
            used_biosamples.add(biosample)
            found += 1
            evidence.append({"sample_id": row["sample_id"], "assembly_accession": row["assembly_accession"],
                             "sra_run": row["sra_run"], "bioproject": bioproject,
                             "assembly_method": info.get("assembly_method", ""),
                             "sequencing_tech": info.get("sequencing_tech", ""),
                             "assembly_release_date": info.get("release_date", ""),
                             "evidence": reason + "; exactly 1 paired Illumina run on the BioSample"})
            sys.stderr.write(f"[discover]   + {row['sample_id']} {row['assembly_accession']} {bioproject} "
                             f"({info.get('assembly_method', '')})\n")
        sys.stderr.write(f"[discover] {species}: accepted {found}/{need} after {checks} online check(s)\n")

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(accepted)
    with open(args.evidence_out, "w", newline="", encoding="utf-8") as handle:
        fields = ["sample_id", "assembly_accession", "sra_run", "bioproject", "assembly_method", "sequencing_tech",
                  "assembly_release_date", "evidence"]
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(evidence)


if __name__ == "__main__":
    main()
