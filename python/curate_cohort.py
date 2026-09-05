#!/usr/bin/env python3
"""Turn candidate assembly/SRA pairs into a strict, reviewable PlasBench cohort.

Candidates are never silently accepted: every row is checked with the same
complete-reference, plasmid, BioSample, BioProject, paired-Illumina rules used
by ``validate_cohort.py``.  The accepted and rejected tables form the curation
audit trail required before publishing a cohort release.
"""

import argparse
import csv
import os
import re
import time
from pathlib import Path

from validate_cohort import (assembly_metadata, derive_truth_quality_tier,
                             request_interval, run_metadata)


OUT_COLUMNS = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
               "truth_quality_tier", "biosample", "bioproject", "sample_origin", "read_depth_x",
               "assembly_plasmid_count", "source_study", "alternate_paired_runs",
               "candidate_extra_long_read_runs")


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def safe_id(value, index):
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (value or "candidate") + f"_{index:03d}"


def write_rows(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, help="TSV with assembly_accession and sra_run; optional sample_id, sample_origin, source_study.")
    parser.add_argument("--out-dir", required=True, help="Directory for accepted.tsv and rejected.tsv.")
    parser.add_argument("--email", help="Contact email sent to NCBI E-utilities.")
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    args = parser.parse_args()
    candidates = read_rows(args.candidates)
    required = {"assembly_accession", "sra_run"}
    if not candidates or any(not required.issubset(row) or not row["assembly_accession"] or not row["sra_run"] for row in candidates):
        raise SystemExit("ERROR: candidates must contain non-empty assembly_accession and sra_run columns")
    accepted, rejected = [], []
    for index, candidate in enumerate(candidates, 1):
        accession, run_accession = candidate["assembly_accession"], candidate["sra_run"]
        try:
            assembly = assembly_metadata(accession, args.email, args.api_key)
            run = run_metadata(run_accession, args.email, args.api_key)
            reasons = []
            if assembly["assembly_status"].lower() != "complete genome": reasons.append("assembly is not Complete Genome")
            if not assembly["has_plasmid"]: reasons.append("assembly does not declare plasmid replicons")
            if not assembly["derived_truth_technology"]: reasons.append("Datasets v2 has no explicit long-read sequencing evidence")
            if not assembly["biosample"] or assembly["biosample"] != run["biosample"]: reasons.append("assembly and run BioSample do not match")
            if not run["bioproject"] or run["bioproject"] not in assembly["bioprojects"]: reasons.append("assembly and run BioProject do not match")
            if run["platform"].upper() != "ILLUMINA": reasons.append("run platform is not ILLUMINA")
            if run["layout"].upper() != "PAIRED": reasons.append("run is not paired-end")
            if reasons:
                rejected.append({**candidate, "reason": "; ".join(reasons)})
                continue
            accepted.append({
                "sample_id": candidate.get("sample_id") or safe_id(assembly["organism"], index),
                "assembly_accession": assembly["accession"], "sra_run": run["run"],
                "organism": assembly["organism"], "truth_technology": assembly["derived_truth_technology"],
                # Tier follows the same evidence rule the validator applies, so a
                # curated sheet round-trips through `validate-cohort --online`.
                "truth_quality_tier": derive_truth_quality_tier([], candidate.get("source_study")),
                "biosample": assembly["biosample"],
                "bioproject": run["bioproject"], "sample_origin": candidate.get("sample_origin", ""),
                "read_depth_x": candidate.get("read_depth_x", ""),
                "assembly_plasmid_count": "", "source_study": candidate.get("source_study", ""),
            })
        except Exception as exc:
            rejected.append({**candidate, "reason": f"metadata lookup failed: {exc}"})
        finally:
            # Every candidate costs several NCBI requests; pace the loop so a
            # large candidate table does not rely on 429 retry to stay legal.
            time.sleep(request_interval(args.api_key))
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "accepted.tsv", accepted, OUT_COLUMNS)
    rejected_fields = tuple(dict.fromkeys((*candidates[0].keys(), "reason")))
    write_rows(out / "rejected.tsv", rejected, rejected_fields)
    print(f"Curation complete: accepted={len(accepted)} rejected={len(rejected)}")
    print(f"Review {out / 'accepted.tsv'} before download/release; rejection reasons are in {out / 'rejected.tsv'}.")


if __name__ == "__main__":
    main()
