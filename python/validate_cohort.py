#!/usr/bin/env python3
"""Validate a PlasBench cohort locally and against linked NCBI metadata."""

import argparse
import csv
import hashlib
import http.client
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOCK_SCHEMA_VERSION = "1.1"
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
# A dropped keep-alive surfaces as http.client.RemoteDisconnected, which is not a
# URLError; without it here a single flaky connection discards a whole cohort run.
TRANSIENT = (URLError, TimeoutError, ConnectionError, http.client.HTTPException,
             json.JSONDecodeError, UnicodeDecodeError)


def request_interval(api_key=None):
    """Seconds to pause between per-record NCBI request bursts.

    NCBI allows 3 requests/second without an API key and 10 with one. Each
    cohort record costs several requests, so callers that loop over records
    must pace themselves rather than rely on 429 retry to absorb the overrun.
    """
    return 0.11 if api_key else 0.34


def fetch(request, timeout=30, retries=4, label="NCBI request", parse=None):
    """Read a URL with bounded retry across HTTP and connection-level failures."""
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            return parse(payload) if parse else payload
        except (HTTPError, *TRANSIENT) as exc:
            fatal = isinstance(exc, HTTPError) and exc.code not in RETRYABLE_STATUS
            if attempt == retries - 1 or fatal:
                raise ValueError(f"{label} failed after {attempt + 1} attempt(s): {exc}") from exc
            retry_after = exc.headers.get("Retry-After") if isinstance(exc, HTTPError) else None
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit()
                       else min(30, 2 ** attempt + random.random()))


REQUIRED = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
            "truth_quality_tier", "biosample", "bioproject")
ACCESSION = re.compile(r"^GC[AF]_\d+\.\d+$")
RUN = re.compile(r"^(SRR|ERR|DRR)\d+$")
LONG_READ = re.compile(r"nanopore|\bont\b|pacbio|\bsmrt\b|minion|promethion|sequel|revio", re.IGNORECASE)
SHORT_READ = re.compile(r"illumina|mgi|dnbseq|ion torrent", re.IGNORECASE)
# A source_study naming one of these is a placeholder, not a reviewed citation.
# "needs_" catches needs_review and needs_curator_review without demoting a real
# citation such as Smith_2021_systematic_review.
UNREVIEWED_STUDY = re.compile(r"pending|needs?_|unverified|unknown|tbd|candidate", re.IGNORECASE)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t")
        return list(reader), reader.fieldnames or []


def ncbi_json(endpoint, params, email=None, api_key=None, retries=4):
    """Read E-utilities JSON with bounded retry/backoff for transient errors."""
    params = {**params, "retmode": "json"}
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    request = Request(endpoint + "?" + urlencode(params), headers={"User-Agent": "PlasBench/0.1 cohort validator"})
    return fetch(request, 30, retries, "NCBI request", parse=json.loads)


def datasets_report(accession, email=None, api_key=None, retries=4):
    """Retrieve Datasets v2 assembly evidence unavailable from E-utilities."""
    params = {}
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    request = Request(
        "https://api.ncbi.nlm.nih.gov/datasets/v2alpha/genome/accession/"
        + accession + "/dataset_report" + ("?" + urlencode(params) if params else ""),
        headers={"User-Agent": "PlasBench/0.1 cohort validator"},
    )
    reports = fetch(request, 60, retries, "NCBI Datasets v2 request",
                    parse=lambda payload: json.loads(payload).get("reports", []))
    if len(reports) != 1:
        raise ValueError(f"Datasets v2 did not return one report for {accession}")
    info = reports[0].get("assembly_info", {})
    biosample = info.get("biosample", {})
    return {"sequencing_tech": info.get("sequencing_tech", ""),
            "assembly_method": info.get("assembly_method", ""),
            "datasets_assembly_level": info.get("assembly_level", ""),
            # These controlled BioSample fields provide auditable discovery
            # evidence; they never replace the exact assembly/SRA linkage rules.
            "biosample_accession": biosample.get("accession", ""),
            "bioproject_accession": info.get("bioproject_accession", ""),
            "geo_loc_name": biosample.get("geo_loc_name", ""),
            "isolation_source": biosample.get("isolation_source", ""),
            "host": biosample.get("host", ""),
            "collection_date": biosample.get("collection_date", "")}


def derive_truth_technology(sequencing_tech):
    """Classify reference technology only from explicit deposited evidence."""
    if not sequencing_tech or not LONG_READ.search(sequencing_tech):
        return None
    return "hybrid" if SHORT_READ.search(sequencing_tech) else "long_read"


def derive_truth_quality_tier(evidence_errors, source_study):
    """Grade curation confidence from evidence strength.

    A -- every deposited-evidence check passed AND source_study names a reviewed
         publication or collection, so the row is release-ready.
    B -- every evidence check passed but the study is absent or still a
         review placeholder, so the row is complete but not curator-approved.
    C -- reserved for rows that have not been verified online at all; online
         verification always resolves a row to A or B.
    """
    if evidence_errors:
        return None
    study = (source_study or "").strip()
    return "B" if not study or UNREVIEWED_STUDY.search(study) else "A"


def assembly_metadata(accession, email=None, api_key=None):
    ids = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    {"db": "assembly", "term": f"{accession}[Assembly Accession]", "retmax": 2}, email, api_key)["esearchresult"]["idlist"]
    if len(ids) != 1:
        raise ValueError(f"assembly not found uniquely: {accession}")
    result = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                       {"db": "assembly", "id": ids[0]}, email, api_key)["result"][ids[0]]
    projects = {item["bioprojectaccn"] for key in ("gb_bioprojects", "rs_bioprojects") for item in result.get(key, [])}
    report_url = result.get("ftppath_assembly_rpt", "").replace("ftp://", "https://")
    report_text = fetch(Request(report_url, headers={"User-Agent": "PlasBench/0.1 cohort validator"}),
                        30, 4, "NCBI assembly report request", parse=lambda payload: payload.decode("utf-8"))
    has_plasmid = any("\tplasmid\t" in line.lower() for line in report_text.splitlines())
    datasets = datasets_report(accession, email, api_key)
    if datasets["bioproject_accession"]:
        projects.add(datasets["bioproject_accession"])
    technology = derive_truth_technology(datasets["sequencing_tech"])
    return {"accession": result["assemblyaccession"], "biosample": result.get("biosampleaccn", ""),
            "bioprojects": sorted(projects), "organism": result.get("speciesname") or result.get("organism", ""),
            "assembly_status": result.get("assemblystatus", ""), "has_plasmid": has_plasmid,
            "sequencing_tech": datasets["sequencing_tech"], "assembly_method": datasets["assembly_method"],
            "datasets_assembly_level": datasets["datasets_assembly_level"], "derived_truth_technology": technology,
            "geo_loc_name": datasets["geo_loc_name"], "isolation_source": datasets["isolation_source"],
            "host": datasets["host"], "collection_date": datasets["collection_date"]}


def run_metadata(run, email=None, api_key=None):
    ids = ncbi_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    {"db": "sra", "term": f"{run}[Accession]", "retmax": 2}, email, api_key)["esearchresult"]["idlist"]
    if len(ids) != 1:
        raise ValueError(f"SRA run not found uniquely: {run}")
    params = {"db": "sra", "id": ids[0], "rettype": "runinfo", "retmode": "text"}
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    runinfo = fetch(Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(params),
                            headers={"User-Agent": "PlasBench/0.1 cohort validator"}),
                    30, 4, "NCBI run-info request", parse=lambda payload: payload.decode("utf-8"))
    rows = list(csv.DictReader(runinfo.splitlines()))
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


def verify_row(row, email=None, api_key=None):
    assembly = assembly_metadata(row["assembly_accession"], email, api_key)
    time.sleep(0.11 if api_key else 0.34)
    run = run_metadata(row["sra_run"], email, api_key)
    errors = []
    if assembly["assembly_status"].lower() != "complete genome": errors.append("assembly is not Complete Genome")
    if assembly["datasets_assembly_level"].lower() != "complete genome": errors.append("Datasets v2 assembly level is not Complete Genome")
    if not assembly["has_plasmid"]: errors.append("assembly metadata does not declare plasmid replicons")
    if not assembly["derived_truth_technology"]:
        errors.append("Datasets v2 sequencing_tech has no explicit long-read platform")
    elif row["truth_technology"] != assembly["derived_truth_technology"]:
        errors.append("declared truth_technology does not match Datasets v2 sequencing evidence")
    if assembly["biosample"] != row["biosample"]: errors.append("assembly BioSample does not match cohort row")
    if row["bioproject"] not in assembly["bioprojects"]: errors.append("assembly BioProject does not match cohort row")
    if run["biosample"] != row["biosample"]: errors.append("SRA BioSample does not match cohort row")
    if run["bioproject"] != row["bioproject"]: errors.append("SRA BioProject does not match cohort row")
    if run["platform"].upper() != "ILLUMINA": errors.append("SRA platform is not ILLUMINA")
    if run["layout"].upper() != "PAIRED": errors.append("SRA library is not paired-end")
    # Tier grades curation confidence, not just pass/fail: see derive_truth_quality_tier.
    derived_tier = derive_truth_quality_tier(errors, row.get("source_study"))
    if derived_tier and row["truth_quality_tier"] != derived_tier:
        errors.append(
            f"declared truth_quality_tier {row['truth_quality_tier']} does not match "
            f"evidence-derived tier {derived_tier} "
            f"({'reviewed source_study' if derived_tier == 'A' else 'source_study absent or pending review'})"
        )
    assembly["derived_truth_quality_tier"] = derived_tier
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
    # A matching checksum only proves the sheet is unchanged. A lock written
    # before the sequencing-evidence schema carries none of the fields that
    # back the long-read truth claim, so report it as stale rather than verified.
    if str(lock.get("schema_version", "")) != LOCK_SCHEMA_VERSION:
        raise ValueError(
            f"verification lock schema is {lock.get('schema_version') or 'absent'}, expected "
            f"{LOCK_SCHEMA_VERSION}; it predates the sequencing-evidence fields. "
            "Run --online --write-lock again."
        )
    missing = [record.get("sample_id", "?") for record in evidence
               if not (record.get("assembly") or {}).get("derived_truth_technology")]
    if missing:
        raise ValueError(
            "verification lock has no long-read sequencing evidence for: "
            + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")
        )
    return len(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, help="cohort TSV")
    parser.add_argument("--online", action="store_true", help="verify complete assembly, linked BioSample/BioProject, and paired Illumina run at NCBI")
    parser.add_argument("--email", help="contact email sent to NCBI E-utilities")
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"),
                        help="NCBI API key (default: NCBI_API_KEY); raises the request allowance.")
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
                result = verify_row(row, args.email, args.api_key)
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
        # LOCK_SCHEMA_VERSION 1.1 adds Datasets v2 sequencing evidence and derived technology/tier.
        path.write_text(json.dumps({"schema_version": LOCK_SCHEMA_VERSION, "sample_sheet": Path(args.samples).name,
                                    "sample_sheet_sha256": hashlib.sha256(source).hexdigest(), "evidence": evidence}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote cohort verification lock: {path}")
    scope = "NCBI-linked pair verified" if args.online else "schema verified"
    print(f"COHORT VALIDATION PASSED: {len(rows)} samples ({scope})")


if __name__ == "__main__":
    main()
