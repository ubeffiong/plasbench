#!/usr/bin/env python3
"""Validate an open PlasBench cohort sheet; optionally verify NCBI records online."""
import argparse, csv, json, re, sys
from urllib.parse import urlencode
from urllib.request import urlopen

REQUIRED = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier", "biosample", "bioproject")
ACCESSION = re.compile(r"^GC[AF]_\d+\.\d+$")
RUN = re.compile(r"^(SRR|ERR|DRR)\d+$")

def online_exists(db, term):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode({"db": db, "term": term, "retmode": "json"})
    with urlopen(url, timeout=20) as response:
        return int(json.load(response)["esearchresult"]["count"]) > 0

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--samples",required=True);p.add_argument("--online",action="store_true");a=p.parse_args()
    with open(a.samples,newline="",encoding="utf-8") as f: reader=csv.DictReader((line for line in f if line.strip() and not line.lstrip().startswith('#')),delimiter='\t'); rows=list(reader); fields=reader.fieldnames or []
    if any(key not in fields for key in REQUIRED): sys.exit("ERROR: cohort sheet must include: " + ", ".join(REQUIRED))
    if not rows: print("COHORT VALIDATION PASSED: template contains no samples"); return
    seen=set(); errors=[]
    for n,r in enumerate(rows,2):
        if not r["sample_id"] or r["sample_id"] in seen: errors.append(f"row {n}: missing or duplicate sample_id")
        seen.add(r["sample_id"])
        if not ACCESSION.match(r["assembly_accession"]): errors.append(f"row {n}: invalid assembly accession")
        if not RUN.match(r["sra_run"]): errors.append(f"row {n}: invalid SRA run")
        if r["truth_technology"] not in ("long_read","hybrid"): errors.append(f"row {n}: truth_technology must be long_read or hybrid")
        if r["truth_quality_tier"] not in ("A","B","C"): errors.append(f"row {n}: truth_quality_tier must be A/B/C")
        # Origin is free text so local programmes are not forced into a narrow vocabulary.
        depth = (r.get("read_depth_x") or "").strip()
        if depth:
            try:
                if float(depth) <= 0: errors.append(f"row {n}: read_depth_x must be greater than zero when supplied")
            except ValueError: errors.append(f"row {n}: read_depth_x must be numeric when supplied")
        if a.online:
            for db,value,label in (("assembly",r["assembly_accession"],"assembly"),("sra",r["sra_run"],"SRA run"),("biosample",r["biosample"],"BioSample"),("bioproject",r["bioproject"],"BioProject")):
                try:
                    if not online_exists(db,value): errors.append(f"row {n}: NCBI {label} not found: {value}")
                except Exception as exc: errors.append(f"row {n}: NCBI {label} check failed: {exc}")
    if errors: sys.exit("COHORT VALIDATION FAILED\n" + "\n".join(errors))
    print(f"COHORT VALIDATION PASSED: {len(rows)} samples ({'online verified' if a.online else 'schema verified'})")
if __name__=='__main__': main()
