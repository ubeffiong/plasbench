#!/usr/bin/env python3
"""
collect_truth_provenance.py -- record how each cohort truth assembly was built,
from NCBI evidence, so reference tiers rest on recorded facts rather than on
truth_provenance.py's per-run guesses.

For every cohort row it fetches:
  * NCBI Datasets genome report: assembly_method, sequencing_tech, release date;
  * the Illumina runs registered on the row's BioSample (SRA E-utilities).

and derives the two sample-sheet columns truth_provenance.py reads:

  truth_assembly_strategy  long_read_only | long_read_first_hybrid |
                           short_read_first_hybrid | unknown
  truth_polish_reads       none | same_as_benchmark | independent | unknown

Polishing-read rule (the important one): when the assembly used Illumina data
and its BioSample carries exactly ONE Illumina run -- the benchmark's own
sra_run -- the polishing reads were necessarily the benchmark reads
(same_as_benchmark). When the BioSample has several Illumina runs, the record
does not say which one polished the assembly, so the value is `unknown` unless
a curator confirms it. Every derived value is written with its evidence to
--evidence-out, for review before the values are copied into a cohort sheet.

Standard library only. NCBI is queried anonymously (no email is sent); set
NCBI_API_KEY to raise the request allowance.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from truth_provenance import classify_method  # noqa: E402

DATASETS = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/{}/dataset_report"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


def get_json(url, api_key=None, retries=4):
    headers = {"User-Agent": "plasbench-provenance/1.0", "Accept": "application/json"}
    if api_key and "eutils" not in url:
        headers["api-key"] = api_key
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # network hiccup or rate limit: back off and retry
            time.sleep(2 ** attempt)
    raise RuntimeError(f"NCBI request failed after {retries} attempts: {url}")


def assembly_report(accession, api_key):
    data = get_json(DATASETS.format(urllib.parse.quote(accession)), api_key)
    reports = data.get("reports") or []
    if not reports:
        return {}
    info = reports[0].get("assembly_info") or {}
    return {"assembly_method": info.get("assembly_method", ""),
            "sequencing_tech": info.get("sequencing_tech", ""),
            "release_date": info.get("release_date", ""),
            "assembly_level": info.get("assembly_level", "")}


def illumina_runs(biosample, api_key):
    params = {"db": "sra", "term": f"{biosample}[BioSample] AND ILLUMINA[Platform]", "retmode": "json",
              "retmax": 0, "tool": "plasbench"}
    if api_key:
        params["api_key"] = api_key
    data = get_json(ESEARCH + "?" + urllib.parse.urlencode(params))
    return int((data.get("esearchresult") or {}).get("count", 0))


def derive(row, report, n_illumina):
    method, tech = report.get("assembly_method", ""), report.get("sequencing_tech", "")
    strategy, polish, reason = classify_method(method, tech)
    if strategy in ("long_read_first_hybrid", "short_read_first_hybrid"):
        if n_illumina == 1:
            polish = "same_as_benchmark"
            reason += f"; BioSample has exactly 1 Illumina run ({row.get('sra_run', '')}), so it polished the truth"
        elif n_illumina > 1:
            polish = "unknown"
            reason += f"; BioSample has {n_illumina} Illumina runs -- which one polished the truth is not recorded"
        else:
            polish = "unknown"
            reason += "; no Illumina run found on the BioSample"
    return strategy, polish, reason


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", required=True, help="cohort TSV (sample_id, assembly_accession, sra_run, biosample)")
    ap.add_argument("--evidence-out", required=True)
    ap.add_argument("--sheet-out", help="copy of --samples with truth_assembly_strategy/truth_polish_reads filled")
    ap.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    args = ap.parse_args()
    with open(args.samples, newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))
    fields = list(rows[0]) if rows else []
    delay = 0.12 if args.api_key else 0.4
    evidence = []
    for row in rows:
        accession = (row.get("assembly_accession") or "").strip()
        report = assembly_report(accession, args.api_key) if accession else {}
        time.sleep(delay)
        n_illumina = illumina_runs(row["biosample"], args.api_key) if row.get("biosample") else 0
        time.sleep(delay)
        strategy, polish, reason = derive(row, report, n_illumina)
        row["truth_assembly_strategy"], row["truth_polish_reads"] = strategy, polish
        evidence.append({"sample_id": row["sample_id"], "assembly_accession": accession,
                         "assembly_method": report.get("assembly_method", ""),
                         "sequencing_tech": report.get("sequencing_tech", ""),
                         "assembly_release_date": report.get("release_date", ""),
                         "illumina_runs_on_biosample": n_illumina,
                         "truth_assembly_strategy": strategy, "truth_polish_reads": polish, "evidence": reason})
        sys.stderr.write(f"[provenance] {row['sample_id']}: {strategy} / {polish}\n")
    with open(args.evidence_out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(evidence[0]) if evidence else ["sample_id"],
                                delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(evidence)
    if args.sheet_out:
        out_fields = fields + [f for f in ("truth_assembly_strategy", "truth_polish_reads") if f not in fields]
        with open(args.sheet_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=out_fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
