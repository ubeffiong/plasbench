#!/usr/bin/env python3
"""Assembly selection: a declared policy, evidence from the assembly only, every candidate kept, no silent substitution.

Acceptance test from the plan: given several candidate assemblies, the selected one is identified by the declared policy and the QC
evidence for every alternative is retained.
"""
import csv
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import assembly_selection as sel  # noqa: E402

TAB = chr(9)
ok = True
LIMITS = ["--min-total-mb", "0.5", "--max-total-mb", "1.0"]


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def write_fasta(path, lengths, seed):
    rng = random.Random(seed)
    with open(path, "w") as h:
        for i, n in enumerate(lengths):
            h.write(f">c{i}\n")
            seq = "".join(rng.choice("ACGT") for _ in range(n))
            for k in range(0, n, 80):
                h.write(seq[k:k + 80] + "\n")


def read(path):
    with open(path, newline="") as h:
        return list(csv.DictReader(h, delimiter=TAB))


def run(tmp, tag, cands, policy, primary, extra=()):
    out = os.path.join(tmp, tag + ".tsv")
    args = ["select", "--sample", "S1", "--policy", policy, "--primary", primary, "--out", out,
            "--selected-out", os.path.join(tmp, tag + ".sel")] + LIMITS + list(extra)
    for name, path in cands.items():
        args += ["--candidate", f"{name}={path}"]
    sel.main(args)
    return {r["assembler"]: r for r in read(out)}, open(os.path.join(tmp, tag + ".sel")).read().strip()


tmp = tempfile.mkdtemp(prefix="asmsel_")
try:
    paths = {name: os.path.join(tmp, name + ".fa") for name in ("spades", "unicycler", "tiny", "huge")}
    write_fasta(paths["spades"], [300000, 300000, 200000, 100000], 1)        # 900 kb, N50 300 kb, 4 contigs
    write_fasta(paths["unicycler"], [600000, 250000, 50000], 2)              # 900 kb, N50 600 kb, 3 contigs
    write_fasta(paths["tiny"], [100000], 3)                                  # 100 kb: too small to be a genome
    write_fasta(paths["huge"], [600000, 600000], 4)                          # 1.2 Mb: over the limit set for this test

    print("measuring every candidate")
    rows, chosen = run(tmp, "quality", {k: v for k, v in paths.items()}, "quality", "spades")
    u, s = rows["unicycler"], rows["spades"]
    check("N50, L50, contigs, total length and GC are measured for each candidate", u["n50"] == "600000" and u["l50"] == "1"
          and u["n_contigs"] == "3" and u["total_length"] == "900000" and s["n50"] == "300000" and s["n_contigs"] == "4"
          and 45 < float(u["gc_percent"]) < 55, (u, s))
    check("bases in long contigs are counted (>= 10 kb)", u["bp_ge_10kb"] == "900000" and u["bp_ge_1kb"] == "900000")
    check("an implausibly small and an oversize assembly are ineligible, with the reason",
          rows["tiny"]["eligible"] == "no" and "total length 0.10 Mb < 0.5 Mb" in rows["tiny"]["reasons"]
          and rows["huge"]["eligible"] == "no" and "1.20 Mb > 1 Mb" in rows["huge"]["reasons"], rows["tiny"])
    check("the evidence for EVERY alternative is retained, not only the winner", set(rows) == set(paths)
          and all(r["n_contigs"] != "" for r in rows.values()))
    check("read support is reported as not_evaluated when no reads are given (never assumed)",
          u["mapped_read_fraction"] == "not_evaluated")

    print("policies")
    check("quality: the eligible candidate with the highest N50 is selected", chosen == "unicycler" and u["selected"] == "yes"
          and s["selected"] == "no", chosen)
    check("quality: the selection reason is recorded", "highest N50 (600000)" in u["selection_reason"] and "2 eligible" in u["selection_reason"],
          u["selection_reason"])
    rows_f, chosen_f = run(tmp, "fixed", paths, "fixed", "spades")
    check("fixed: the configured assembler is selected even though another has a better N50", chosen_f == "spades"
          and rows_f["spades"]["selected"] == "yes" and rows_f["unicycler"]["selected"] == "no")
    rows_n, chosen_n = run(tmp, "fixed_bad", paths, "fixed", "tiny")
    check("fixed: an ineligible primary is NOT silently replaced by a better candidate", chosen_n == ""
          and all(r["selected"] == "no" for r in rows_n.values())
          and "no other candidate was substituted" in rows_n["tiny"]["selection_reason"], rows_n["tiny"])
    rows_q, chosen_q = run(tmp, "quality_none", {k: paths[k] for k in ("tiny", "huge")}, "quality", "tiny")
    check("quality: no eligible candidate means none is selected", chosen_q == ""
          and "no candidate is eligible" in rows_q["tiny"]["selection_reason"], rows_q)
    rows_m, chosen_m = run(tmp, "missing", {"spades": paths["spades"], "unicycler": os.path.join(tmp, "absent.fa")}, "quality", "spades")
    check("a candidate whose assembly was not produced is listed as ineligible, not skipped",
          rows_m["unicycler"]["eligible"] == "no" and rows_m["unicycler"]["reasons"] == "no assembly file" and chosen_m == "spades")

    print("independent of any score")
    measured = [dict(r, benchmark_f1="0.1" if r["assembler"] == "unicycler" else "0.99", truth_recall="0.0" if r["assembler"] == "unicycler" else "1.0")
                for r in rows.values()]
    check("columns a score would live in change nothing: the policy reads assembly measurements only",
          sel.select(measured, "quality", "spades")[0] == "unicycler")
    check("the module reads no truth, tool output or score file", all(w not in open(os.path.join(ROOT, "python", "assembly_selection.py")).read()
                                                                   .split('"""', 2)[2] for w in ("truth.tsv", "scores.tsv", "leaderboard", "per_plasmid")))

    print("read support (needs minimap2)")
    if shutil.which("minimap2"):
        rng = random.Random(9)
        seqs = {}
        with open(paths["unicycler"]) as h:
            name = None
            for line in h:
                if line.startswith(">"):
                    name = line[1:].strip(); seqs[name] = []
                else:
                    seqs[name].append(line.strip())
        genome = "".join("".join(v) for v in seqs.values())
        r1, r2 = os.path.join(tmp, "r1.fq"), os.path.join(tmp, "r2.fq")
        with open(r1, "w") as a, open(r2, "w") as b:
            for i in range(3000):
                p = rng.randrange(0, len(genome) - 400)
                frag = genome[p:p + 400]
                rev = frag[::-1].translate(str.maketrans("ACGT", "TGCA"))
                a.write(f"@r{i}/1\n{frag[:100]}\n+\n{'I' * 100}\n")
                b.write(f"@r{i}/2\n{rev[:100]}\n+\n{'I' * 100}\n")
        rows_r, chosen_r = run(tmp, "reads", {"unicycler": paths["unicycler"], "spades": paths["spades"]}, "quality", "spades",
                               ["--reads1", r1, "--reads2", r2])
        check("reads from one genome map to that assembly (read support near 1) and not to an unrelated one",
              float(rows_r["unicycler"]["mapped_read_fraction"]) > 0.95 and float(rows_r["spades"]["mapped_read_fraction"]) < 0.10,
              (rows_r["unicycler"]["mapped_read_fraction"], rows_r["spades"]["mapped_read_fraction"]))
        check("an assembly with no read support is ineligible and cannot be selected", rows_r["spades"]["eligible"] == "no"
              and "read support" in rows_r["spades"]["reasons"] and chosen_r == "unicycler")
    else:
        print("  (skipped: minimap2 is not on PATH)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL ASSEMBLY SELECTION TESTS PASSED" if ok else "ASSEMBLY SELECTION TESTS FAILED")
sys.exit(0 if ok else 1)
