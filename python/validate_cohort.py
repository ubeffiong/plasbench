#!/usr/bin/env python3
"""Validate a PlasBench cohort locally and against linked NCBI metadata."""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REQUIRED = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
            "truth_quality_tier", "biosample", "bioproject")
ACCESSION = re.compile(r"^GC[AF]_\d+\.\d+$")
RUN = re.compile(r"^(SRR|ERR|DRR)\d+$")


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t")
        return list(reader), reader.fieldnames or []


def ncbi_json(endpoint, params, email=None):
    params = {**params, "retmode": "json"}
    if email:
        params["email"] = email
    request = Request(endpoint + "?" + urlencode(params), headers={"User-Agent": "PlasBench cohort validator"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def assembly_metadata(accession, email=None):
    ids = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    {"db": "assembly", "term": f"{accession}[Assembly Accession]", "retmax": 2}, email)["esearchresult"]["idlist"]
    if len(ids) != 1:
        raise ValueError(f"assembly not found uniquely: {accession}")
    result = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                       {"db": "assembly", "id": ids[0]}, email)["result"][ids[0]]
    projects = {item["bioprojectaccn"] for key in ("gb_bioprojects", "rs_bioprojects") for item in result.get(key, [])}
    report_url = result.get("ftppath_assembly_rpt", "").replace("ftp://", "https://")
    with urlopen(report_url, timeout=30) as response:
        has_plasmid = any("\tplasmid\t" in line.lower() for line in response.read().decode("utf-8").splitlines())
    return {"accession": result["assemblyaccession"], "biosample": result.get("biosampleaccn", ""),
            "bioprojects": sorted(projects), "organism": result.get("speciesname") or result.get("organism", ""),
            "assembly_status": result.get("assemblystatus", ""), "has_plasmid": has_plasmid}


def run_metadata(run, email=None):
    ids = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    {"db": "sra", "term": f"{run}[Accession]", "retmax": 2}, email)["esearchresult"]["idlist"]
    if len(ids) != 1:
        raise ValueError(f"SRA run not found uniquely: {run}")
    params = {"db": "sra", "id": ids[0], "rettype": "runinfo", "retmode": "text"}
    if email:
        params["email"] = email
    with urlopen("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(params), timeout=30) as response:
        rows = list(csv.DictReader(response.read().decode("utf-8").splitlines()))
    if len(rows) != 1 or rows[0].get("Run") != run:
        raise ValueError(f"could not retrieve run-info row for {run}")
    row = rows[0]
    return {"run": run, "biosample": row.get("BioSample", ""), "bioproject": row.get("BioProject", ""),
            "sample_name": row.get("SampleName", ""), "platform": row.get("Platform", ""),
            "layout": row.get("LibraryLayout", ""), "bases": row.get("bases", "")}


def schema_errors(rows, fields):
    errors = []
    if any(key not in fields for key in REQUIRED):
        return ["cohort sheet must include: " + ", ".join(REQUIRED)]
    seen = set()
    for number, row in enumerate(rows, 2):
        if not row["sample_id"] or row["sample_id"] in seen:
            errors.append(f"row {number}: missing or duplicate sample_id")
        seen.add(row["sample_id"])
        if not ACCESSION.match(row["assembly_accession"]): errors.append(f"row {number}: invalid assembly accession")
        if not RUN.match(row["sra_run"]): errors.append(f"row {number}: invalid SRA run")
        if row["truth_technology"] not in ("long_read", "hybrid"): errors.append(f"row {number}: truth_technology must be long_read or hybrid")
        if row["truth_quality_tier"] not in ("A", "B", "C"): errors.append(f"row {number}: truth_quality_tier must be A/B/C")
        depth = (row.get("read_depth_x") or "").strip()
        try:
            if depth and float(depth) <= 0: errors.append(f"row {number}: read_depth_x must be greater than zero when supplied")
        except ValueError:
            errors.append(f"row {number}: read_depth_x must be numeric when supplied")
    return errors


def verify_row(row, email=None):
    assembly = assembly_metadata(row["assembly_accession"], email)
    time.sleep(0.34)
    run = run_metadata(row["sra_run"], email)
    errors = []
    if assembly["assembly_status"].lower() != "complete genome": errors.append("assembly is not Complete Genome")
    if not assembly["has_plasmid"]: errors.append("assembly metadata does not declare plasmid replicons")
    if assembly["biosample"] != row["biosample"]: errors.append("assembly BioSample does not match cohort row")
    if row["bioproject"] not in assembly["bioprojects"]: errors.append("assembly BioProject does not match cohort row")
    if run["biosample"] != row["biosample"]: errors.append("SRA BioSample does not match cohort row")
    if run["bioproject"] != row["bioproject"]: errors.append("SRA BioProject does not match cohort row")
    if run["platform"].upper() != "ILLUMINA": errors.append("SRA platform is not ILLUMINA")
    if run["layout"].upper() != "PAIRED": errors.append("SRA library is not paired-end")
    return {"sample_id": row["sample_id"], "assembly": assembly, "run": run, "errors": errors}


def verify_lock(lock_path, samples_path):
    """Verify that a cohort sheet is exactly the one verified in its lock file."""
    try:
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read verification lock: {exc}") from exc
    expected = lock.get("sample_sheet_sha256")
    if not isinstance(expected, str) or not expected:
        raise ValueError("verification lock has no sample_sheet_sha256")
    observed = hashlib.sha256(Path(samples_path).read_bytes()).hexdigest()
    if observed != expected:
        raise ValueError(
            "sample-sheet checksum differs from verification lock; run --online --write-lock again"
        )
    evidence = lock.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("verification lock has no evidence list")
    return len(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, help="cohort TSV")
    parser.add_argument("--online", action="store_true", help="verify complete assembly, linked BioSample/BioProject, and paired Illumina run at NCBI")
    parser.add_argument("--email", help="contact email sent to NCBI E-utilities")
    parser.add_argument("--write-lock", help="write retrieved verification evidence as JSON")
    parser.add_argument("--verify-lock", help="require a verification lock matching --samples")
    args = parser.parse_args()
    rows, fields = read_rows(args.samples)
    errors = schema_errors(rows, fields)
    if args.verify_lock:
        try:
            evidence_count = verify_lock(args.verify_lock, args.samples)
            print(f"COHORT LOCK VERIFIED: {evidence_count} evidence record(s)")
        except ValueError as exc:
            errors.append(str(exc))
    if not rows and not errors:
        print("COHORT VALIDATION PASSED: template contains no samples")
        return
    evidence = []
    if args.online and not errors:
        for row in rows:
            try:
                result = verify_row(row, args.email)
                evidence.append(result)
                errors.extend(f"{row['sample_id']}: {message}" for message in result["errors"])
            except Exception as exc:
                errors.append(f"{row['sample_id']}: NCBI verification failed: {exc}")
    if errors:
        raise SystemExit("COHORT VALIDATION FAILED\n" + "\n".join(errors))
    if args.write_lock:
        if not args.online:
            raise SystemExit("ERROR: --write-lock requires --online")
        path = Path(args.write_lock)
        path.parent.mkdir(parents=True, exist_ok=True)
        source = Path(args.samples).read_bytes()
        path.write_text(json.dumps({"schema_version": "1.0", "sample_sheet": Path(args.samples).name,
                                    "sample_sheet_sha256": hashlib.sha256(source).hexdigest(), "evidence": evidence}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote cohort verification lock: {path}")
    scope = "NCBI-linked pair verified" if args.online else "schema verified"
    print(f"COHORT VALIDATION PASSED: {len(rows)} samples ({scope})")


if __name__ == "__main__":
    main()
