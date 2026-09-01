#!/usr/bin/env python3
"""Create evidence-preserving candidate and balanced-shortlist tables."""
import argparse, csv
from collections import Counter
from pathlib import Path

def rows(path):
    with open(path, newline="", encoding="utf-8") as h: return list(csv.DictReader(h, delimiter="\t"))
def write(path, data, fields):
    with open(path, "w", newline="", encoding="utf-8") as h:
        w=csv.DictWriter(h, fieldnames=fields, delimiter="\t", extrasaction="ignore"); w.writeheader(); w.writerows(data)
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--candidates", required=True); p.add_argument("--out-dir", required=True); p.add_argument("--max-per-bioproject", type=int, default=3); p.add_argument("--max-per-organism", type=int, default=8); a=p.parse_args()
    source=rows(a.candidates)
    if not source or a.max_per_bioproject < 1 or a.max_per_organism < 1: raise SystemExit("ERROR: candidates and positive balance limits are required")
    fields=list(dict.fromkeys([*source[0], "candidate_status", "origin_review", "source_study_review", "review_flags"]))
    enriched=[]
    for r in source:
        flags=["origin_unverified", "publication_unverified"]
        enriched.append({**r, "candidate_status":"metadata_qualified", "origin_review":"needs_curator_review", "source_study_review":"needs_curator_review", "review_flags":";".join(flags)})
    project, organism=Counter(), Counter(); shortlist=[]
    for r in sorted(enriched, key=lambda x:(x["organism"],x["bioproject"],x["sample_id"])):
        if project[r["bioproject"]] >= a.max_per_bioproject or organism[r["organism"]] >= a.max_per_organism: continue
        project[r["bioproject"]]+=1; organism[r["organism"]]+=1
        shortlist.append({**r, "candidate_status":"balanced_shortlist_pending_manual_review"})
    out=Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    write(out/"candidates.enriched.tsv", enriched, fields); write(out/"balanced_shortlist.pending_review.tsv", shortlist, fields)
    write(out/"study_dependence.tsv", [{"bioproject":k,"candidate_count":v} for k,v in sorted(Counter(x["bioproject"] for x in enriched).items())], ["bioproject","candidate_count"])
    print(f"Reviewed {len(enriched)} candidates; balanced shortlist={len(shortlist)}. No row is release-approved automatically.")
if __name__ == "__main__": main()
