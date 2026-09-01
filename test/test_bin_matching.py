#!/usr/bin/env python3
"""Synthetic regression coverage for exact and split bin matching."""
import csv, os, subprocess, sys, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); SCRIPT=os.path.join(ROOT,'python','score_bins.py')
def run(paf,bins):
 with tempfile.TemporaryDirectory() as d:
  truth=os.path.join(d,'truth.tsv'); open(truth,'w').write('sequence_id\tmolecule_type\tlength\np1\tPLASMID\t100\np2\tPLASMID\t100\n')
  pp=os.path.join(d,'x.paf'); open(pp,'w').write(paf); bb=os.path.join(d,'x.bins.tsv'); open(bb,'w').write(bins)
  out=os.path.join(d,'out.tsv'); summary=os.path.join(d,'summary.tsv'); subprocess.run([sys.executable,SCRIPT,'--truth',truth,'--paf',pp,'--bins',bb,'--out',out,'--summary',summary],check=True)
  return next(csv.DictReader(open(summary),delimiter='\t'))
def main():
 exact=run('a\t100\t0\t100\t+\tp1\t100\t0\t100\t100\t100\t60\nb\t100\t0\t100\t+\tp2\t100\t0\t100\t100\t100\t60\n','bin_id\tsequence_id\nA\ta\nB\tb\n')
 assert exact['bin_f1']=='1.0000' and exact['split_events']=='0' and exact['merge_events']=='0'
 split=run('a\t100\t0\t100\t+\tp1\t100\t0\t100\t100\t100\t60\nb\t100\t0\t100\t+\tp1\t100\t0\t100\t100\t100\t60\n','bin_id\tsequence_id\nA\ta\nB\tb\n')
 assert split['split_events']=='1' and split['unmatched_bins']=='1'
 print('ALL BIN MATCHING TESTS PASSED')
if __name__=='__main__': main()
