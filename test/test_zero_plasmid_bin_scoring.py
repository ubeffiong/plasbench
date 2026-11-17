#!/usr/bin/env python3
"""Bin scoring on an isolate with no true plasmid (docs/METHODS.md, "Zero-true-plasmid isolates").

recall and F1 are 0/0 there, so they are blank, never 0.0: a 0.0 would score a tool that correctly predicted nothing like one that failed,
and would pull every negative-control isolate into a binner's mean as a forced zero. score_plasmids.py already did this; score_bins.py wrote
"0.0000". Precision is a real 0.0 when something was binned (none of it can be correct) and blank when nothing was.

The cases that DO have true plasmid must be unchanged: a tool that bins nothing there has F1 0.0 (that is a failure to recover, not an undefined ratio).
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failures = []


def check(label, ok, detail=""):
    print(("  PASS: " if ok else "  FAIL: ") + label + ("" if ok else f"  [{detail}]"))
    if not ok:
        failures.append(label)


def run(tmp, truth_rows, bins, paf, fasta=None):
    (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\n" + "".join(f"{a}\t{b}\t{c}\n" for a, b, c in truth_rows))
    (tmp / "bins.tsv").write_text("sequence_id\tbin_id\n" + "".join(f"{a}\t{b}\n" for a, b in bins))
    (tmp / "a.paf").write_text(paf)
    command = [sys.executable, str(ROOT / "python" / "score_bins.py"), "--truth", str(tmp / "truth.tsv"), "--paf", str(tmp / "a.paf"),
               "--bins", str(tmp / "bins.tsv"), "--out", str(tmp / "m.tsv"), "--summary", str(tmp / "s.tsv")]
    if fasta is not None:
        (tmp / "pred.fa").write_text(fasta)
        command += ["--pred-fasta", str(tmp / "pred.fa")]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with open(tmp / "s.tsv", newline="") as handle:
        return next(csv.DictReader(handle, delimiter="\t")), result.stdout


def paf_row(query, qlen, target, tlen, start, end):
    n = end - start
    return f"{query}\t{qlen}\t0\t{n}\t+\t{target}\t{tlen}\t{start}\t{end}\t{n}\t{n}\t60\ttp:A:P\n"


ZERO = ("lw_bin_recall", "lw_bin_f1", "bin_recall", "bin_f1", "lw_bin_f1_strict")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    chromosome_only = [("chr", "CHROMOSOME", 5000)]

    print("zero true plasmid, nothing binned")
    row, out = run(tmp, chromosome_only, [], "")
    check("recall and F1 are blank (both the length-weighted and the count-based)", all(row[k] == "" for k in ZERO), {k: row[k] for k in ZERO})
    check("precision is blank too (nothing was predicted)", row["lw_bin_precision"] == "" and row["bin_precision"] == "", (row["lw_bin_precision"], row["bin_precision"]))
    check("stdout says undefined, not 0.0000", "undefined" in out and "lw_bin_f1=0.0000" not in out, out)

    print("zero true plasmid, a bin sits wholly on the chromosome")
    row, _ = run(tmp, chromosome_only, [("c1", "A")], paf_row("c1", 1000, "chr", 5000, 0, 1000), fasta=">c1\n" + "A" * 1000 + "\n")
    check("precision is a real 0.0 (something was binned, none of it can be correct)", row["lw_bin_precision"] == "0.0000" and row["bin_precision"] == "0.0000", (row["lw_bin_precision"], row["bin_precision"]))
    check("recall and F1 stay blank", all(row[k] == "" for k in ZERO), {k: row[k] for k in ZERO})
    check("the chromosome claim is still reported (the negative-control signal)", row["chromosome_aligned_bp"] == "1000" and row["contamination_fraction"] == "1.0000", (row["chromosome_aligned_bp"], row["contamination_fraction"]))

    print("true plasmid present, tool bins nothing: UNCHANGED (a failure to recover scores 0)")
    row, _ = run(tmp, chromosome_only + [("pl", "PLASMID", 1000)], [], "")
    check("lw_bin_f1 and bin_f1 are 0.0000 (not blank)", row["lw_bin_f1"] == "0.0000" and row["bin_f1"] == "0.0000", (row["lw_bin_f1"], row["bin_f1"]))
    check("recall is 0.0000", row["lw_bin_recall"] == "0.0000" and row["bin_recall"] == "0.0000")

    print("true plasmid present, perfect bin: UNCHANGED")
    row, _ = run(tmp, chromosome_only + [("pl", "PLASMID", 1000)], [("c1", "A")], paf_row("c1", 1000, "pl", 1000, 0, 1000))
    check("lw_bin_f1 1.0000 and bin_f1 1.0000", row["lw_bin_f1"] == "1.0000" and row["bin_f1"] == "1.0000", (row["lw_bin_f1"], row["bin_f1"]))

    print("downstream readers treat the blank as missing, not zero")
    sys.path.insert(0, str(ROOT / "python"))
    import merge_bin_metrics
    check("merge_bin_metrics.value() returns None for a blank", merge_bin_metrics.value({"lw_bin_f1": ""}, "lw_bin_f1") is None)

print("ALL ZERO-PLASMID BIN SCORING TESTS PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
