#!/usr/bin/env python3
"""Tests for python/plasbin_flow_adapter.py and adapters/adapt_plasbin_flow.sh.

Hand-computed expectations. Assembly: a(100 bp), b(170), c(30), d(5).
Output bins: P1 = a:2,b:3 ; P2 = c:1,b:1  (b shared).
  - bins.tsv rows: P1 a, P1 b, P2 c   (b stays in P1; d never listed)
  - FASTA ids: a, b, c ; lengths 100, 170, 30
  - provenance: bin_count 2, contig_count 3, contigs_in_multiple_bins {b:[P1,P2]},
    contigs_with_multiplicity_gt1 = 2 (a:2, b:3)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY_HELPER = os.path.join(ROOT, "python", "plasbin_flow_adapter.py")
SH = os.path.join(ROOT, "adapters", "adapt_plasbin_flow.sh").replace("\\", "/")


BASH = shutil.which("bash") or "bash"


def fwd(p):
    return p.replace("\\", "/")
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)))
    if not cond:
        FAILS.append(name)


def fasta(path, d):
    with open(path, "w", newline="\n") as fh:
        for k, v in d.items():
            fh.write(">%s some description\n%s\n" % (k, v))


def read_fa(path):
    out, cur = [], None
    for l in open(path).read().splitlines():
        if l.startswith(">"):
            cur = [l[1:], ""]
            out.append(cur)
            assert len(l) <= 81
        else:
            assert len(l) <= 80
            cur[1] += l
    return out


def write(path, text):
    with open(path, "wb") as fh:
        fh.write(text.encode())


def run(pb, asm, out, prov=None):
    cmd = [sys.executable, PY_HELPER, "--plasbin-output", pb, "--contigs", asm, "--out-fasta", out]
    if prov:
        cmd += ["--provenance", prov]
    return subprocess.run(cmd, capture_output=True, text=True)


def bins(out):
    stem = out[:-len(".plasmid.fasta")]
    return open(stem + ".bins.tsv").read().splitlines()


tmp = tempfile.mkdtemp()
try:
    asm = os.path.join(tmp, "asm.fasta")
    seqs = {"a": "ACGT" * 25, "b": "GATTACA" * 24 + "GG", "c": "C" * 30, "d": "TTTTT"}
    fasta(asm, seqs)
    HDR = "#Pls_ID\tFlow\tGC_bin\tContigs\n"
    pb = os.path.join(tmp, "pb.tsv")
    write(pb, HDR + "P1\t2.5\t0.4-0.45\ta:2,b:3\n\nP2\t1.0\t0.5-0.55\tc:1,b:1\n")
    out = os.path.join(tmp, "o1.plasmid.fasta")
    prov = os.path.join(tmp, "o1.prov.json")
    r = run(pb, asm, out, prov)
    check("main run ok", r.returncode == 0, r.stderr)
    recs = read_fa(out)
    check("fasta ids unique, ordered", [x[0] for x in recs] == ["a", "b", "c"], recs)
    check("sequences preserved", all(s == seqs[i] for i, s in recs))
    check("bins.tsv", bins(out) == ["bin_id\tsequence_id", "P1\ta", "P1\tb", "P2\tc"], bins(out))
    p = json.load(open(prov))
    check("prov counts", p["bin_count"] == 2 and p["contig_count"] == 3, p)
    check("prov multi-bin", p["contigs_in_multiple_bins"] == {"b": ["P1", "P2"]}, p)
    check("prov multiplicity", p["contigs_with_multiplicity_gt1"] == 2, p)
    check("prov flow/gc", p["bins"][0]["flow"] == "2.5" and p["bins"][1]["gc_bin"] == "0.5-0.55", p)
    check("prov sha", p["plasbin_output_sha256"] == hashlib.sha256(open(pb, "rb").read()).hexdigest())

    # empty and header-only
    for nm, txt in (("empty", ""), ("header-only", HDR)):
        f = os.path.join(tmp, nm + ".tsv")
        write(f, txt)
        o = os.path.join(tmp, nm + ".plasmid.fasta")
        r = run(f, asm, o)
        check(nm + " valid", r.returncode == 0 and open(o).read() == ""
              and bins(o) == ["bin_id\tsequence_id"], r.stderr)

    # unknown contig
    f = os.path.join(tmp, "unk.tsv")
    write(f, HDR + "P1\t1\t0.4\ta:1,zzz_missing:2\n")
    r = run(f, asm, os.path.join(tmp, "unk.plasmid.fasta"))
    check("unknown contig fails", r.returncode != 0 and "zzz_missing" in r.stderr, r.stderr)

    # duplicate plasmid id
    f = os.path.join(tmp, "dup.tsv")
    write(f, HDR + "P1\t1\t0.4\ta:1\nP1\t1\t0.4\tc:1\n")
    r = run(f, asm, os.path.join(tmp, "dup.plasmid.fasta"))
    check("duplicate id fails", r.returncode != 0 and "P1" in r.stderr, r.stderr)

    # garbage in non-empty file
    f = os.path.join(tmp, "bad.tsv")
    write(f, "garbage\n")
    r = run(f, asm, os.path.join(tmp, "bad.plasmid.fasta"))
    check("unparsable fails", r.returncode != 0, r.stderr)

    # bare ids, no header
    f = os.path.join(tmp, "bare.tsv")
    write(f, "P1\t1\t0.4\ta,d\n")
    o = os.path.join(tmp, "bare.plasmid.fasta")
    r = run(f, asm, o)
    check("bare ids", r.returncode == 0 and [x[0] for x in read_fa(o)] == ["a", "d"]
          and bins(o)[1:] == ["P1\ta", "P1\td"], r.stderr)

    # CRLF
    f = os.path.join(tmp, "crlf.tsv")
    write(f, HDR.replace("\n", "\r\n") + "P1\t2\t0.4\ta:2,b:1\r\nP2\t1\t0.5\tc:1\r\n")
    o = os.path.join(tmp, "crlf.plasmid.fasta")
    r = run(f, asm, o)
    check("CRLF", r.returncode == 0 and bins(o) == ["bin_id\tsequence_id", "P1\ta", "P1\tb", "P2\tc"], r.stderr)

    # bash adapter
    o = os.path.join(tmp, "pred_plasbin_flow.plasmid.fasta")
    r = subprocess.run([BASH, SH, fwd(pb), fwd(asm), fwd(o)], capture_output=True, text=True)
    pj = os.path.join(tmp, "pred_plasbin_flow.plasbin_flow.provenance.json")
    check("bash adapter", r.returncode == 0 and os.path.exists(pj)
          and os.path.exists(os.path.join(tmp, "pred_plasbin_flow.bins.tsv"))
          and len(read_fa(o)) == 3, r.stderr)
    r = subprocess.run([BASH, SH, fwd(os.path.join(tmp, "nope.tsv")), fwd(asm), fwd(o)], capture_output=True, text=True)
    check("bash adapter missing input fails", r.returncode != 0 and r.stderr, r.stderr)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if FAILS:
    print("FAILED: %s" % FAILS)
    sys.exit(1)
print("all passed")
