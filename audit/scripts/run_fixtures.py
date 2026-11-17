import csv, subprocess, sys, tempfile, os
from pathlib import Path
ROOT = Path(sys.argv[1]); PY = ROOT/"python"
def paf(q,ql,qs,qe,t,tl,ts,te,mapq=60):
    n=qe-qs; return "\t".join(map(str,[q,ql,qs,qe,"+",t,tl,ts,te,n,n,mapq,"tp:A:P"]))+"\n"
def fasta(d,items):
    p=d/"pred.fa"; p.write_text("".join(f">{k}\n{'A'*v}\n" for k,v in items)); return p
def truth(d,rows):
    p=d/"truth.tsv"; p.write_text("sequence_id\tmolecule_type\tlength\n"+"".join(f"{a}\t{b}\t{c}\n" for a,b,c in rows)); return p
def tsv(p):
    with open(p,newline="") as h: return list(csv.DictReader(h,delimiter="\t"))
def run(cmd):
    r=subprocess.run([sys.executable,*map(str,cmd)],capture_output=True,text=True)
    if r.returncode: print("  CMD FAILED:",r.stderr[-400:])
    return r
def sp(d,name,t,pafs,fa,extra=()):
    (d/f"{name}.paf").write_text("".join(pafs))
    out=d/f"{name}.tsv"
    run([PY/"score_plasmids.py","--truth",t,"--paf",d/f"{name}.paf","--pred-fasta",fa,"--sample","s","--tool",name,"--out",out,*extra])
    return tsv(out)[0] if out.exists() else {}
def show(r,keys): print("   ",{k:r.get(k) for k in keys})
K=["precision","recall","f1","strict_precision","plasmid_recall","redundant_pred_bp"]
with tempfile.TemporaryDirectory() as t_:
    d=Path(t_)
    T=truth(d,[("chr","CHROMOSOME",1000),("pl","PLASMID",100)])
    print("A1 junk output (expect precision/F1=1 despite 5000bp junk)")
    r=sp(d,"a1",T,[paf("p1",100,0,100,"pl",100,0,100)],fasta(d,[("p1",100),("junk",5000)])); show(r,K)
    print("A2 duplicate candidates")
    r=sp(d,"a2",T,[paf("p1",100,0,100,"pl",100,0,100),paf("p2",100,0,100,"pl",100,0,100)],fasta(d,[("p1",100),("p2",100)])); show(r,K)
    print("Fragmentation: plasmid as 20x5bp contigs")
    P=[paf(f"c{i}",5,0,5,"pl",100,5*i,5*i+5) for i in range(20)]
    r=sp(d,"frag",T,P,fasta(d,[(f"c{i}",5) for i in range(20)])); show(r,K+["plasmid_recall_ge90"] if "plasmid_recall_ge90" in r else K)
    print("A8/A7 via score_bins")
    T2=truth(d,[("chrA","CHROMOSOME",5000),("chrB","CHROMOSOME",5000),("pl","PLASMID",1000)])
    (d/"bins.tsv").write_text("sequence_id\tbin_id\nc1\tb1\n")
    (d/"b.paf").write_text(paf("c1",3000,0,1000,"pl",1000,0,1000)+paf("c1",3000,1000,2000,"chrA",5000,0,1000)+paf("c1",3000,2000,3000,"chrB",5000,0,1000))
    run([PY/"score_bins.py","--truth",T2,"--paf",d/"b.paf","--bins",d/"bins.tsv","--out",d/"bm.tsv","--summary",d/"bs.tsv","--cprr-out",d/"cprr.tsv"])
    print("    bm cols:", open(d/"bm.tsv").read()[:600])
    print("    cprr:",[{k:r[k] for k in r} for r in tsv(d/"cprr.tsv")][:1])
    print("A7 zero-plasmid isolate, tool predicts nothing")
    T3=truth(d,[("chr","CHROMOSOME",5000)]); (d/"e.tsv").write_text("sequence_id\tbin_id\n"); (d/"e.paf").write_text("")
    run([PY/"score_bins.py","--truth",T3,"--paf",d/"e.paf","--bins",d/"e.tsv","--out",d/"em.tsv","--summary",d/"es.tsv"])
    s=tsv(d/"es.tsv")[0]; print("   ",{k:s.get(k) for k in("lw_bin_f1","bin_f1","lw_bin_precision","lw_bin_recall")})
    print("   score_plasmids on same isolate f1 =", repr(sp(d,"z",T3,[],fasta(d,[])).get("f1")))
