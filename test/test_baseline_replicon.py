#!/usr/bin/env python3
"""Regression for baseline_predictors.py replicon: marker hits, Col-vs-Inc rule, thresholds."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "baseline_predictors.py"
HEADER = ("#FILE\tSEQUENCE\tSTART\tEND\tSTRAND\tGENE\tCOVERAGE\tCOVERAGE_MAP\tGAPS\t%COVERAGE\t"
          "%IDENTITY\tDATABASE\tACCESSION\tPRODUCT\tRESISTANCE\n")


def hit(contig, gene, cov=100.0, ident=99.0):
    return (f"asm.fa\t{contig}\t1\t200\t+\t{gene}\t1-200/200\t=====\t0/0\t{cov}\t{ident}\t"
            f"plasmidfinder\tX00001\t.\t.\n")


def check(name, ok):
    if not ok:
        print("FAIL: " + name, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " ? True")


def run(tmp, hits_text, *extra):
    tmp = Path(tmp)
    (tmp / "c.fa").write_text(
        ">fii\n" + "A" * 2000 + "\n>mixed\n" + "C" * 2000 + "\n>colonly\n" + "G" * 2000 + "\n"
        ">lowid\n" + "T" * 2000 + "\n>short\n" + "A" * 500 + "\n>none\n" + "C" * 2000 + "\n")
    hits = tmp / "hits.tsv"
    hits.unlink(missing_ok=True)
    if hits_text is not None:
        hits.write_text(hits_text)
    prefix = tmp / "out"
    for suffix in (".plasmid.fasta", ".bins.tsv"):
        (tmp / ("out" + suffix)).unlink(missing_ok=True)
    result = subprocess.run([sys.executable, str(SCRIPT), "replicon", "--contigs", str(tmp / "c.fa"),
                             "--replicon-hits", str(hits), "--out-prefix", str(prefix), *extra],
                            capture_output=True, text=True)
    called = set()
    fasta = tmp / "out.plasmid.fasta"
    if fasta.is_file():
        called = {ln[1:].strip() for ln in fasta.read_text().splitlines() if ln.startswith(">")}
    return result, called


HITS = HEADER + (hit("fii", "IncFII(pCoo)_1_pCoo_AP001918") + hit("mixed", "ColRNAI_1__DQ298019")
                 + hit("mixed", "IncFIB(AP001918)_1__AP001918") + hit("colonly", "Col(BS512)_1__CP001063")
                 + hit("lowid", "IncX1_1__EU370913", ident=85.0) + hit("short", "IncFII_1__X", )
                 + hit("ghost", "IncFII_1__Y"))

with tempfile.TemporaryDirectory() as d:
    r, called = run(d, HITS)
    check("default exit 0", r.returncode == 0)
    check("IncFII called", "fii" in called)
    check("Col+Inc on same contig still called via Inc", "mixed" in called)
    check("Col alone called", "colonly" in called)
    check("low identity not called", "lowid" not in called)
    check("short contig not called", "short" not in called)
    check("contig without hit not called", "none" not in called)
    bins = (Path(d) / "out.bins.tsv").read_text().splitlines()
    check("bins header and one-per-contig", bins[0] == "bin_id\tsequence_id" and "fii\tfii" in bins)

with tempfile.TemporaryDirectory() as d:
    only_col = HEADER + hit("mixed", "ColRNAI_1__DQ298019") + hit("mixed", "IncFIB_1__A")
    r, called = run(d, only_col)
    check("Col dropped, Inc keeps contig", called == {"mixed"} and "(1 Col hit" in r.stderr)
    r, called = run(d, HEADER + hit("mixed", "ColRNAI_1__DQ298019") + hit("fii", "IncFII_1__A"),
                    "--keep-col-with-inc")
    check("--keep-col-with-inc keeps Col on Inc contig", called == {"mixed", "fii"})
    r, called = run(d, HEADER + hit("colonly", "Col156_1__X", cov=40.0))
    check("low coverage not called", "colonly" not in called)
    r, called = run(d, HEADER + hit("colonly", "Col156_1__X", ident=85.0), "--min-identity", "80")
    check("--min-identity override", called == {"colonly"})

with tempfile.TemporaryDirectory() as d:
    r, _ = run(d, HEADER)
    check("header-only hits => not applicable (3)", r.returncode == 3)
    r, _ = run(d, "")
    check("empty hits => not applicable (3)", r.returncode == 3)
    r, _ = run(d, None)
    check("missing hits => not applicable (3)", r.returncode == 3)
print("BASELINE REPLICON TEST PASSED")
