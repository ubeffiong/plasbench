#!/usr/bin/env python3
"""The short-read QC gate: PASS, WARN and REJECT, with reasons, on deliberately good and deliberately bad read pairs.

Acceptance test from the plan: a deliberately invalid or below-threshold dataset is REJECTED with a documented reason; a warning-level
dataset proceeds but stays flagged. The thresholds used here are a small-data copy of the shipped ones so the files stay small; the
shipped thresholds are tested separately (they are provisional, and a 3,000-pair file fails their read-count minimum).
"""
import csv
import gzip
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import short_read_qc as qc  # noqa: E402

TAB = chr(9)
ok = True
LEN = 100
Q40, Q15 = "I", "0"


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def reads(n, seed, qual_mix=((1.0, Q40),), adapter=0.0, n_frac=0.0, same=False, names=None, drop_last=0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        s = "".join(rng.choice("ACGT") for _ in range(LEN))
        out.append(s)
    if same:
        out = [out[0]] * n
    if adapter:
        out = [("AGATCGGAAGAGC" + s[13:]) if rng.random() < adapter else s for s in out]
    if n_frac:
        out = ["".join("N" if rng.random() < n_frac else c for c in s) for s in out]
    quals = []
    for _ in range(n):
        r, acc = rng.random(), 0.0
        for share, ch in qual_mix:
            acc += share
            if r <= acc:
                quals.append(ch * LEN)
                break
        else:
            quals.append(qual_mix[-1][1] * LEN)
    return out, quals


def write_fastq(path, seqs, quals, mate, names=None, gz=True, break_quality=False, stop=None):
    names = names or [f"r{i}" for i in range(len(seqs))]
    opener = gzip.open if gz else open
    with opener(path, "wt") as h:
        for i, (s, q) in enumerate(zip(seqs, quals)):
            if stop is not None and i >= stop:
                break
            h.write(f"@{names[i]}/{mate}\n{s}\n+\n{q[:-1] if (break_quality and i == 3) else q}\n")


def pair(tmp, tag, n=2000, seed=1, **kw):
    seqs1, quals1 = reads(n, seed, **kw)
    seqs2, quals2 = reads(n, seed + 7, **{k: v for k, v in kw.items() if k != "same"})
    if kw.get("same"):
        seqs2, quals2 = [seqs2[0]] * n, quals2
    r1, r2 = os.path.join(tmp, tag + "_1.fastq.gz"), os.path.join(tmp, tag + "_2.fastq.gz")
    write_fastq(r1, seqs1, quals1, 1)
    write_fastq(r2, seqs2, quals2, 2)
    return r1, r2


def run(tmp, tag, thresholds, r1, r2, **kw):
    out = os.path.join(tmp, tag + ".tsv")
    args = ["qc", "--sample", tag, "--r1", r1, "--r2", r2, "--out", out, "--thresholds", thresholds]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    qc.main(args)
    with open(out, newline="") as h:
        return next(csv.DictReader(h, delimiter=TAB))


tmp = tempfile.mkdtemp(prefix="srqc_")
try:
    small = os.path.join(tmp, "thresholds.tsv")
    with open(small, "w") as h:
        h.write("metric\tdirection\twarn\treject\tstatus\trationale\n")
        for row in open(qc.DEFAULT_THRESHOLDS, encoding="utf-8"):
            if row.startswith("#") or row.startswith("metric") or not row.strip():
                continue
            f = row.rstrip("\n").split(TAB)
            if f[0] == "read_pairs":
                f[2], f[3] = "1000", "200"
            if f[0] in ("estimated_depth_x", "median_read_length"):
                f[2], f[3] = "", ""
            h.write(TAB.join(f) + "\n")

    print("good, warning and reject-level reads")
    good = run(tmp, "good", small, *pair(tmp, "good"))
    check("good reads PASS with no reasons", good["qc_status"] == "PASS" and good["reasons"] == "", good)
    check("the QC row records exact counts, quality and the thresholds' hash",
          good["pairs_basis"] == "exact" and good["read_pairs_total"] == "2000" and float(good["mean_quality"]) > 39
          and len(good["thresholds_sha"]) == 12 and good["contamination_screen"] == "not_evaluated", good)
    warn = run(tmp, "warn", small, *pair(tmp, "warn", qual_mix=((0.7, Q40), (0.3, Q15))))
    check("a quality concern is a WARN (the sample proceeds, flagged), not a reject",
          warn["qc_status"] == "WARN" and "q30_fraction" in warn["reasons"] and "(warn)" in warn["reasons"], warn)
    low = run(tmp, "low", small, *pair(tmp, "low", qual_mix=((1.0, Q15),)))
    check("very low quality is REJECTed with the metric named", low["qc_status"] == "REJECT" and "mean_quality" in low["reasons"]
          and "(reject)" in low["reasons"], low)
    a_warn = run(tmp, "a_warn", small, *pair(tmp, "a_warn", adapter=0.25))
    a_rej = run(tmp, "a_rej", small, *pair(tmp, "a_rej", adapter=0.80))
    check("adapters in a quarter of reads: WARN; in most reads: REJECT", a_warn["qc_status"] == "WARN" and a_rej["qc_status"] == "REJECT"
          and float(a_rej["adapter_fraction"]) > 0.5, (a_warn["reasons"], a_rej["reasons"]))
    dup = run(tmp, "dup", small, *pair(tmp, "dup", same=True))
    check("every pair identical: duplication REJECT", dup["qc_status"] == "REJECT" and "duplication_fraction" in dup["reasons"], dup)
    nn = run(tmp, "nn", small, *pair(tmp, "nn", n_frac=0.2))
    check("20% N bases: REJECT", nn["qc_status"] == "REJECT" and "n_fraction" in nn["reasons"], nn)

    print("integrity failures always reject")
    r1, r2 = pair(tmp, "sync")
    seqs, quals = reads(2000, 99)
    write_fastq(r2, seqs, quals, 2, names=[f"other{i}" for i in range(2000)])
    sync = run(tmp, "sync", small, r1, r2)
    check("read names out of sync between the files: REJECT", sync["qc_status"] == "REJECT" and "pair_mismatch_fraction" in sync["reasons"], sync)
    r1, r2 = pair(tmp, "trunc")
    blob = open(r1, "rb").read()
    open(r1, "wb").write(blob[: len(blob) // 2])
    tr = run(tmp, "trunc", small, r1, r2)
    check("a truncated gzip file: REJECT for integrity", tr["qc_status"] == "REJECT" and tr["integrity"].startswith("truncated"), tr)
    r1, r2 = pair(tmp, "empty")
    open(r1, "wb").close()
    em = run(tmp, "empty", small, r1, r2)
    check("an empty file: REJECT for integrity", em["qc_status"] == "REJECT" and em["integrity"] == "empty", em)
    r1, r2 = pair(tmp, "unequal")
    seqs, quals = reads(1900, 8)
    write_fastq(r2, seqs, quals, 2)
    un = run(tmp, "unequal", small, r1, r2)
    check("unequal read counts: REJECT for integrity", un["qc_status"] == "REJECT" and un["integrity"] == "unequal_read_counts", un)
    r1, r2 = pair(tmp, "bad")
    seqs, quals = reads(2000, 5)
    write_fastq(r1, seqs, quals, 1, break_quality=True)
    bad = run(tmp, "bad", small, r1, r2)
    check("a sequence and quality of different lengths: REJECT, malformed FASTQ", bad["qc_status"] == "REJECT"
          and bad["integrity"] == "malformed_fastq", bad)
    with open(qc.DEFAULT_THRESHOLDS, encoding="utf-8") as h:
        shipped_integrity = run(tmp, "trunc_shipped", qc.DEFAULT_THRESHOLDS, *pair(tmp, "ts"))
    check("even with the shipped thresholds a tiny but valid file is rejected for too few reads (3,000 is not a bacterial run)",
          shipped_integrity["qc_status"] == "REJECT" and "read_pairs" in shipped_integrity["reasons"], shipped_integrity)

    print("counts, depth and thresholds")
    big = run(tmp, "big", small, *pair(tmp, "big", n=40000), max_pairs=10000, exact_below_mb=0)
    check("a sample shorter than the file gives an ESTIMATED total, labelled, within 30% of the truth", big["pairs_basis"] == "estimated"
          and big["read_pairs_sampled"] == "10000" and 28000 < int(big["read_pairs_total"]) < 52000, big)
    small_file = run(tmp, "small_file", small, *pair(tmp, "sf", n=3000), max_pairs=1000)
    check("a small file is counted exactly even when the sample is shorter (3,000, not 1,000)",
          small_file["pairs_basis"] == "exact" and small_file["read_pairs_total"] == "3000" and small_file["read_pairs_sampled"] == "1000", small_file)
    r1, r2 = pair(tmp, "late")
    seqs, quals = reads(2300, 11)
    write_fastq(r2, seqs, quals, 2)
    late = run(tmp, "late", small, r1, r2, max_pairs=500)
    check("unequal counts are found even beyond the sample when the file is small", late["integrity"] == "unequal_read_counts", late)
    dep = run(tmp, "dep", small, *pair(tmp, "dep", n=2000), genome_size_mb=0.01)
    check("depth uses the genome size given and says it was not assumed",
          dep["genome_size_assumed"] == "no" and abs(float(dep["estimated_depth_x"]) - 2000 * 2 * LEN / 1e4) < 1.0, dep)
    check("without a genome size the 5 Mb assumption is flagged", good["genome_size_assumed"] == "yes" and good["genome_size_mb"] == "5")
    gc = run(tmp, "gc", small, *pair(tmp, "gc"), expected_gc=70)
    check("an expected GC far from the observed one is flagged", "gc_deviation" in gc["reasons"], gc)
    th, policy, sha = qc.read_thresholds(qc.DEFAULT_THRESHOLDS)
    measured = set(qc.measure(*pair(tmp, "keys"), expected_gc=50))
    check("every threshold row names a metric the gate actually measures (a typo would silently never apply)",
          {t["metric"] for t in qc.read_thresholds(qc.DEFAULT_THRESHOLDS)[0]} <= measured,
          {t["metric"] for t in qc.read_thresholds(qc.DEFAULT_THRESHOLDS)[0]} - measured)
    check("the shipped thresholds parse, are marked provisional and have a hash",
          len(th) == 10 and policy == "provisional" and len(sha) == 12 and all(t["status"] == "provisional" for t in th))
    check("shipped thresholds have a documented rationale per row",
          all(len(line.split(TAB)) == 6 and line.split(TAB)[5].strip() for line in open(qc.DEFAULT_THRESHOLDS, encoding="utf-8")
              if line.strip() and not line.startswith("#") and not line.startswith("metric")))

    print("merge and the action taken")
    shards = os.path.join(tmp, "shards")
    os.makedirs(shards)
    for name in ("good", "warn", "low"):
        shutil.copy(os.path.join(tmp, name + ".tsv"), os.path.join(shards, name + ".tsv"))
    qc.main(["merge", "--shards", shards, "--out", os.path.join(tmp, "m.tsv"), "--status-out", os.path.join(tmp, "s_enf.tsv"), "--mode", "enforce"])
    qc.main(["merge", "--shards", shards, "--out", os.path.join(tmp, "m.tsv"), "--status-out", os.path.join(tmp, "s_rep.tsv"), "--mode", "report"])
    enf = {r["sample"]: r for r in csv.DictReader(open(os.path.join(tmp, "s_enf.tsv")), delimiter=TAB)}
    rep = {r["sample"]: r for r in csv.DictReader(open(os.path.join(tmp, "s_rep.tsv")), delimiter=TAB)}
    check("enforce: the rejected sample is excluded from the primary benchmark; PASS and WARN proceed",
          enf["low"]["action"] == "excluded from the primary benchmark" and enf["good"]["action"] == "proceeded"
          and enf["warn"]["action"] == "proceeded (flagged)", enf)
    check("report-only: nothing is excluded, but the REJECT is still recorded and flagged", rep["low"]["qc_status"] == "REJECT"
          and rep["low"]["action"] == "proceeded (flagged)", rep)
    check("the merged table has one row per sample and every QC column", len(list(csv.DictReader(open(os.path.join(tmp, "m.tsv")), delimiter=TAB))) == 3
          and open(os.path.join(tmp, "m.tsv")).readline().strip().split(TAB) == qc.FIELDS)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL SHORT-READ QC TESTS PASSED" if ok else "SHORT-READ QC TESTS FAILED")
sys.exit(0 if ok else 1)
