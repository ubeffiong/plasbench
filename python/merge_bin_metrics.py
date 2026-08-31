#!/usr/bin/env python3
"""Join per-sample bin summaries into the canonical PlasBench score table."""
import argparse,csv
from pathlib import Path

FIELDS=['bin_precision','bin_recall','bin_f1','matched_bins','unmatched_bins','missed_plasmids']
def main():
 p=argparse.ArgumentParser();p.add_argument('--scores',required=True);p.add_argument('--results-dir',required=True);a=p.parse_args()
 summaries={}
 for path in Path(a.results_dir).glob('*/*.bin_summary.tsv'):
  tool=path.name.removesuffix('.bin_summary.tsv'); sample=path.parent.name
  with open(path) as f: summaries[(sample,tool)]=next(csv.DictReader(f,delimiter='\t'))
 with open(a.scores) as f: rows=list(csv.DictReader(f,delimiter='\t')); names=f.readline if False else None; fieldnames=list(rows[0]) if rows else []
 for x in FIELDS:
  if x not in fieldnames: fieldnames.append(x)
 for row in rows:
  summary=summaries.get((row['sample'],row['tool']),{})
  for x in FIELDS: row[x]=summary.get(x,'')
 with open(a.scores,'w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fieldnames,delimiter='\t');w.writeheader();w.writerows(rows)
if __name__=='__main__':main()
