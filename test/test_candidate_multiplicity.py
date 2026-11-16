#!/usr/bin/env python3
"""Candidate multiplicity: fragments, duplicates, alternatives, chimeras, off-target and unmapped records, all accounted for.

One reference plasmid P1 (100 kb) is reconstructed as several candidates, and every figure below is worked out by hand:

  A  60 kb  on P1 0-60k               primary (covers 60% of P1)
  B  35 kb  on P1 55k-90k             complementary fragment (5 kb shared with A, 30 kb new)
  C  30 kb  on P1 10k-40k             redundant (inside A: nothing new)
  D  20 kb  on P2 0-20k               P2 reconstructed once
  E  20 kb  10 kb on P1 90k-100k + 10 kb on P2 0-10k     chimeric (two plasmids)
  F  50 kb  on the chromosome         off-target
  G   5 kb  no alignment              unmapped

Combined coverage of P1 is the UNION of everything aligned to it, so it is 1.0 and not (60+35+30+10)/100.
"""
import csv
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import candidate_multiplicity as cm  # noqa: E402

TAB = chr(9)
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def near(a, b, eps=1e-6):
    return abs(float(a) - b) < eps


TRUTH = [("P1", "PLASMID", 100000), ("P2", "PLASMID", 20000), ("C1", "CHROMOSOME", 1000000)]
CANDS = {"A": 60000, "B": 35000, "C": 30000, "D": 20000, "E": 20000, "F": 50000, "G": 5000}
# qname qstart qend target tstart tend
ALIGN = [("A", 0, 60000, "P1", 0, 60000), ("B", 0, 35000, "P1", 55000, 90000), ("C", 0, 30000, "P1", 10000, 40000),
         ("D", 0, 20000, "P2", 0, 20000), ("E", 0, 10000, "P1", 90000, 100000), ("E", 10000, 20000, "P2", 0, 10000),
         ("F", 0, 50000, "C1", 0, 50000)]
TLEN = {t: n for t, _, n in TRUTH}


def write_inputs(tmp, align=ALIGN, cands=CANDS):
    truth = os.path.join(tmp, "truth.tsv")
    with open(truth, "w", newline="") as h:
        h.write(TAB.join(["sequence_id", "molecule_type", "length"]) + "\n")
        for t, m, n in TRUTH:
            h.write(TAB.join([t, m, str(n)]) + "\n")
    fasta = os.path.join(tmp, "pred.fasta")
    with open(fasta, "w") as h:
        for q, n in cands.items():
            h.write(f">{q}\n" + "A" * n + "\n")
    paf = os.path.join(tmp, "pred.paf")
    with open(paf, "w") as h:
        for q, qs, qe, t, ts, te in align:
            h.write(TAB.join([q, str(cands[q]), str(qs), str(qe), "+", t, str(TLEN[t]), str(ts), str(te), str(qe - qs), str(qe - qs), "60",
                              "tp:A:P"]) + "\n")
    return truth, paf, fasta


def read(path):
    with open(path, newline="") as h:
        return list(csv.DictReader(h, delimiter=TAB))


tmp = tempfile.mkdtemp(prefix="multiplicity_")
try:
    truth, paf, fasta = write_inputs(tmp)
    out_p, out_c = os.path.join(tmp, "p.tsv"), os.path.join(tmp, "c.tsv")
    out_i = os.path.join(tmp, "i.tsv")
    code = cm.main(["--truth", truth, "--paf", paf, "--pred-fasta", fasta, "--sample", "S1", "--tool", "T", "--out-plasmids", out_p,
                    "--out-candidates", out_c, "--out-intervals", out_i])
    plasmids = {r["plasmid"]: r for r in read(out_p)}
    cands = {r["candidate"]: r for r in read(out_c)}
    check("runs and writes both tables", code == 0 and set(plasmids) == {"P1", "P2"} and set(cands) == set(CANDS))

    iv = [(r["plasmid"], r["candidate"], int(r["start"]), int(r["end"]), r["relationship"]) for r in read(out_i)]
    check("the intervals table places each candidate on each plasmid it touches, with its relationship",
          ("P1", "A", 0, 60000, "primary") in iv and ("P1", "B", 55000, 90000, "complementary_fragment") in iv
          and ("P1", "C", 10000, 40000, "redundant") in iv and ("P1", "E", 90000, 100000, "chimeric") in iv
          and ("P2", "E", 0, 10000, "chimeric") in iv and ("P2", "D", 0, 20000, "primary") in iv and len(iv) == 6, iv)
    check("an off-target or unmapped candidate has no interval on any plasmid", not any(r[1] in ("F", "G") for r in iv))
    print("candidate relationships")
    check("A is the primary of P1", cands["A"]["relationship"] == "primary" and cands["A"]["home_plasmid"] == "P1")
    check("B adds 30 kb of new sequence: a complementary fragment", cands["B"]["relationship"] == "complementary_fragment"
          and cands["B"]["new_bp_on_home"] == "30000")
    check("C lies inside A: redundant, 0 new bp", cands["C"]["relationship"] == "redundant" and cands["C"]["new_bp_on_home"] == "0")
    check("D is the only candidate of P2 (primary)", cands["D"]["relationship"] == "primary" and cands["D"]["home_plasmid"] == "P2")
    check("E spans two plasmids: chimeric, and both are named", cands["E"]["relationship"] == "chimeric"
          and cands["E"]["chimeric_with"] == "P1,P2")
    check("F lands on the chromosome: off-target", cands["F"]["relationship"] == "off_target" and cands["F"]["chromosome_bp"] == "50000")
    check("G aligns nowhere: unmapped, and still listed", cands["G"]["relationship"] == "unmapped" and cands["G"]["aligned_bp"] == "0")

    print("plasmid P1: union, not sum")
    p1 = plasmids["P1"]
    check("best candidate covers 60%", near(p1["best_candidate_coverage"], 0.60) and p1["best_candidate"] == "A", p1)
    check("combined coverage is the union (100%), not 135%", near(p1["combined_coverage"], 1.0), p1["combined_coverage"])
    check("coverage gained over the best candidate is 40%", near(p1["coverage_gain"], 0.40))
    check("redundant bases = 135 kb summed - 100 kb union = 35 kb", p1["redundant_bp"] == "35000" and near(p1["redundancy_fraction"], 35000 / 135000))
    check("candidate bases are 1.35 times the union", near(p1["candidate_bp_to_union_ratio"], 1.35))
    check("3 member candidates, 4 touch P1 (the chimera is not a member)", p1["n_candidates"] == "3" and p1["n_touching"] == "4")
    check("one fragment, one redundant, one chimeric touching", (p1["n_fragments"], p1["n_redundant"], p1["n_chimeric_touching"]) == ("1", "1", "1"))
    check("outcome: fragmented and duplicated", p1["outcome"] == "fragmented_and_duplicated", p1["outcome"])
    p2 = plasmids["P2"]
    check("P2 is a single reconstruction, fully covered", p2["outcome"] == "single" and near(p2["combined_coverage"], 1.0), p2)
    check("the chimera's overlap with D shows up as redundancy on P2 (10 kb of 30 kb)", p2["redundant_bp"] == "10000"
          and near(p2["redundancy_fraction"], 1 / 3))

    print("what extra output does")
    more = dict(CANDS, A2=60000)
    t2, paf2, fa2 = write_inputs(os.path.join(tmp, "dup") if os.makedirs(os.path.join(tmp, "dup")) is None else tmp, ALIGN + [("A2", 0, 60000, "P1", 0, 60000)], more)
    cm.main(["--truth", t2, "--paf", paf2, "--pred-fasta", fa2, "--out-plasmids", os.path.join(tmp, "p2.tsv"), "--out-candidates",
             os.path.join(tmp, "c2.tsv")])
    q1 = {r["plasmid"]: r for r in read(os.path.join(tmp, "p2.tsv"))}["P1"]
    check("an exact duplicate of A changes neither the best nor the combined coverage", near(q1["best_candidate_coverage"], 0.6)
          and near(q1["combined_coverage"], 1.0))
    check("but it raises the redundancy burden and is labelled redundant", float(q1["redundancy_fraction"]) > float(p1["redundancy_fraction"])
          and q1["n_redundant"] == "2" and q1["redundant_bp"] == "95000", q1)

    print("edge cases")
    empty_fa = os.path.join(tmp, "empty.fa")
    open(empty_fa, "w").close()
    open(os.path.join(tmp, "empty.paf"), "w").close()
    cm.main(["--truth", truth, "--paf", os.path.join(tmp, "empty.paf"), "--pred-fasta", empty_fa, "--sample", "S1", "--tool", "none",
             "--out-plasmids", os.path.join(tmp, "ep.tsv"), "--out-candidates", os.path.join(tmp, "ec.tsv")])
    ep = {r["plasmid"]: r for r in read(os.path.join(tmp, "ep.tsv"))}
    check("a tool that predicted nothing: every plasmid is missed with zero coverage",
          {r["outcome"] for r in ep.values()} == {"missed"} and all(near(r["combined_coverage"], 0.0) for r in ep.values()))
    check("and the candidate table is empty (header only)", read(os.path.join(tmp, "ec.tsv")) == [])
    check("an alignment filter drops a short hit (min length 40 kb removes B, C, D, E halves)", True)
    cm.main(["--truth", truth, "--paf", paf, "--pred-fasta", fasta, "--out-plasmids", os.path.join(tmp, "fp.tsv"), "--out-candidates",
             os.path.join(tmp, "fc.tsv"), "--min-alignment-length", "40000"])
    fp = {r["plasmid"]: r for r in read(os.path.join(tmp, "fp.tsv"))}
    fc = {r["candidate"]: r for r in read(os.path.join(tmp, "fc.tsv"))}
    check("with the scorer's length filter at 40 kb only A and F keep alignments",
          {q for q, r in fc.items() if r["aligned_bp"] != "0"} == {"A", "F"} and fp["P2"]["outcome"] == "missed", fc)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL CANDIDATE MULTIPLICITY TESTS PASSED" if ok else "CANDIDATE MULTIPLICITY TESTS FAILED")
sys.exit(0 if ok else 1)
