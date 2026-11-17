#!/usr/bin/env python3
"""A bin padded with sequence that aligns to no truth sequence keeps its headline score (documented) but is charged by the strict columns."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "score_bins.py")
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def paf(q, qlen, t, tlen):
    return f"{q}\t{qlen}\t0\t{qlen}\t+\t{t}\t{tlen}\t0\t{qlen}\t{qlen}\t{qlen}\t60\n"


def run(directory, paf_text, bins, fasta=None):
    truth, pafp, binp, out, summ = (os.path.join(directory, n) for n in ("t.tsv", "a.paf", "b.tsv", "o.tsv", "s.tsv"))
    open(truth, "w").write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t4000\np1\tPLASMID\t1000\n")
    open(pafp, "w").write(paf_text)
    open(binp, "w").write("bin_id\tsequence_id\n" + "".join(f"{b}\t{s}\n" for b, s in bins))
    cmd = [sys.executable, SCRIPT, "--truth", truth, "--paf", pafp, "--bins", binp, "--out", out, "--summary", summ]
    if fasta is not None:
        fp = os.path.join(directory, "p.fa")
        open(fp, "w").write("".join(f">{n}\n{'A' * length}\n" for n, length in fasta))
        cmd += ["--pred-fasta", fp]
    subprocess.run(cmd, check=True, capture_output=True)
    return next(csv.DictReader(open(summ), delimiter="\t"))


with tempfile.TemporaryDirectory() as d:
    alignments = paf("a", 1000, "p1", 1000)
    plain = run(d, alignments, [("B1", "a")], [("a", 1000)])
    check("an exact bin has no unaligned bases and a strict F1 of 1", plain["bin_unaligned_bp"] == "0" and plain["lw_bin_f1_strict"] == "1.0000", plain)
    padded = run(d, alignments, [("B1", "a"), ("B1", "junk")], [("a", 1000), ("junk", 9000)])
    check("the headline length-weighted F1 does not see 9,000 unalignable bases (documented behaviour)", padded["lw_bin_f1"] == "1.0000", padded["lw_bin_f1"])
    check("the unaligned bases are counted", padded["bin_unaligned_bp"] == "9000" and padded["bin_unaligned_fraction"] == "0.9000", padded)
    check("the strict precision charges them: 1000 / (1000 + 9000)", padded["lw_bin_precision_strict"] == "0.1000", padded["lw_bin_precision_strict"])
    check("recall is unchanged by padding", padded["lw_bin_recall"] == "1.0000")
    blank = run(d, alignments, [("B1", "a"), ("B1", "junk")])
    check("without the predicted sequences the strict columns are blank, never 0", blank["bin_unaligned_bp"] == "" and blank["lw_bin_f1_strict"] == "", blank)
    half = run(d, "a\t1000\t0\t500\t+\tp1\t1000\t0\t500\t500\t500\t60\n", [("B1", "a")], [("a", 1000)])
    check("a contig only half aligned counts its other half as unaligned", half["bin_unaligned_bp"] == "500", half["bin_unaligned_bp"])

print("ALL BIN UNALIGNED TESTS PASSED" if ok else "BIN UNALIGNED TESTS FAILED")
sys.exit(0 if ok else 1)
