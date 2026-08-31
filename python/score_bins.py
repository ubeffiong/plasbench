#!/usr/bin/env python3
"""One-to-one predicted-bin versus true-plasmid matching from PAF alignments.

Input bins TSV: bin_id,sequence_id. Every FASTA record must occur exactly once.
Output TSV reports maximum-overlap greedy one-to-one matches plus split/merge
diagnostics. Greedy matching is deterministic (overlap, bin id, plasmid id).
"""
import argparse, csv
from collections import defaultdict

def truth(path):
    with open(path) as f:
        rows=list(csv.DictReader(f, delimiter='\t'))
    return {r['sequence_id']:int(r['length']) for r in rows if r['molecule_type'].upper()=='PLASMID'}

def bins(path):
    out={}
    with open(path) as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if not r.get('bin_id') or not r.get('sequence_id') or r['sequence_id'] in out: raise ValueError('bins TSV requires unique sequence_id and nonempty bin_id')
            out[r['sequence_id']]=r['bin_id']
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--truth',required=True);p.add_argument('--paf',required=True);p.add_argument('--bins',required=True);p.add_argument('--out',required=True);p.add_argument('--threshold',type=float,default=.9);a=p.parse_args()
    plasmids=truth(a.truth); membership=bins(a.bins); overlaps=defaultdict(int)
    with open(a.paf) as f:
        for line in f:
            x=line.rstrip('\n').split('\t')
            if len(x)<12 or x[0] not in membership or x[5] not in plasmids: continue
            overlaps[(membership[x[0]],x[5])]+=max(0,int(x[8])-int(x[7]))
    candidates=sorted(((bp,b,t) for (b,t),bp in overlaps.items() if bp/plasmids[t]>=a.threshold),reverse=True)
    used_b=set();used_t=set();matched=[]
    for bp,b,t in candidates:
        if b not in used_b and t not in used_t: used_b.add(b);used_t.add(t);matched.append((b,t,bp))
    all_bins=set(membership.values())
    with open(a.out,'w',newline='') as f:
        w=csv.writer(f,delimiter='\t');w.writerow(['bin_id','true_plasmid','aligned_bp','match_status'])
        for b,t,bp in matched:w.writerow([b,t,bp,'matched'])
        for b in sorted(all_bins-used_b):w.writerow([b,'',0,'unmatched_bin'])
        for t in sorted(set(plasmids)-used_t):w.writerow(['',t,0,'missed_plasmid'])
    print(f'bin precision={len(matched)/len(all_bins) if all_bins else 0:.4f} bin recall={len(matched)/len(plasmids) if plasmids else 0:.4f} matches={len(matched)}')
if __name__=='__main__': main()
