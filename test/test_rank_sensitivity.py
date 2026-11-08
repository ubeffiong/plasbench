#!/usr/bin/env python3
"""
rank_sensitivity.py on a hand-built case where the ranking provably depends on a
scoring choice, plus the helpers (Kendall tau, ranking, drift warning).

Reference: chromosome 10,000 bp, plasmidA 2,000 bp, plasmidB 1,000 bp (3,000 bp of plasmid).

  tool_repeat  one clean contig covering plasmidA (TP 2000) plus a 1,600 bp
               contig that maps at MAPQ 0 to plasmidA AND to the chromosome.
  tool_clean   one clean contig covering 1,500 bp of plasmidA (TP 1500).

  MAPQ >= 20:  the repeat contig is filtered out -> tool_repeat precision 1.0,
               recall 2000/3000, F1 0.800;  tool_clean F1 0.667.  tool_repeat wins.
  MAPQ 0:      the repeat's chromosome placement is charged 1600 FP ->
               tool_repeat precision 0.556, F1 0.6061 < 0.6667.  tool_clean wins.
"""

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "rank_sensitivity.py")
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import rank_sensitivity as rs  # noqa: E402


def paf(q, qlen, qs, qe, t, tlen, ts, te, mapq):
    n = min(qe - qs, te - ts)
    return f"{q}\t{qlen}\t{qs}\t{qe}\t+\t{t}\t{tlen}\t{ts}\t{te}\t{n}\t{n}\t{mapq}\n"


def build(tmp):
    results = Path(tmp) / "results" / "s1"
    results.mkdir(parents=True)
    (results / "truth.tsv").write_text(
        "sequence_id\tmolecule_type\tlength\nchromosome\tCHROMOSOME\t10000\nplasmidA\tPLASMID\t2000\nplasmidB\tPLASMID\t1000\n")

    def fasta(name, records):
        (results / f"pred_{name}.plasmid.fasta").write_text("".join(f">{r}\n{'A' * n}\n" for r, n in records.items()))

    fasta("tool_repeat", {"good": 2000, "rep": 1600})
    (results / "tool_repeat.pred_vs_ref.paf").write_text(
        paf("good", 2000, 0, 2000, "plasmidA", 2000, 0, 2000, 60)
        + paf("rep", 1600, 0, 1600, "plasmidA", 2000, 0, 1600, 0)
        + paf("rep", 1600, 0, 1600, "chromosome", 10000, 100, 1700, 0))
    fasta("tool_clean", {"c": 1500})
    (results / "tool_clean.pred_vs_ref.paf").write_text(paf("c", 1500, 0, 1500, "plasmidA", 2000, 0, 1500, 60))
    scores = Path(tmp) / "scores.tsv"
    with open(scores, "w", newline="") as handle:
        w = csv.writer(handle, delimiter="\t", lineterminator="\n")
        w.writerow(["sample", "tool", "analysis_track", "f1", "recall", "strict_precision", "plasmid_recall", "plasmid_recall_ge90"])
        # f1 values are what the pipeline filters (MAPQ 20) give; strict_precision penalises the 1600 unmapped bp.
        w.writerow(["s1", "tool_repeat", "short_read", "0.8000", "0.6667", "0.5556", "0.0", "0.0"])
        w.writerow(["s1", "tool_clean", "short_read", "0.6667", "0.5000", "1.0", "0.0", "0.0"])
    return Path(tmp) / "results", scores


def run(tmp, *extra):
    results, scores = build(tmp)
    prefix = str(Path(tmp) / "out")
    done = subprocess.run([sys.executable, SCRIPT, "--scores", str(scores), "--results-dir", str(results),
                           "--out-prefix", prefix, *extra], capture_output=True, text=True)
    table = []
    out = Path(prefix + ".rank_robustness.tsv")
    if out.is_file():
        with open(out, newline="") as handle:
            table = list(csv.DictReader(handle, delimiter="\t"))
    return done, table


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("helpers")
    check("tau of identical orderings is 1", rs.kendall_tau({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}) == 1.0)
    check("tau of reversed orderings is -1", rs.kendall_tau({"a": 1, "b": 2, "c": 3}, {"a": 3, "b": 2, "c": 1}) == -1.0)
    check("one swap among three tools gives tau 1/3", abs(rs.kendall_tau({"a": 1, "b": 2, "c": 3}, {"a": 2, "b": 1, "c": 3}) - 1 / 3) < 1e-9)
    check("fewer than two tools has no tau", rs.kendall_tau({"a": 1}, {"a": 1}) is None)
    order = rs.ranked({"b": {"s": 0.5}, "a": {"s": 0.5}, "c": {"s": 0.9}})
    check("ties rank by tool name", [t for t, _, _, _ in order] == ["c", "a", "b"])
    check("ranking uses only the samples every tool has",
          rs.ranked({"a": {"s1": 1.0, "s2": 0.0}, "b": {"s1": 0.5}})[0][2] == 1)

    print("a ranking that depends on a scoring choice")
    with tempfile.TemporaryDirectory() as tmp:
        done, table = run(tmp, "--min-alignment-length", "1", "--min-alignment-identity", "0.0",
                          "--min-alignment-mapq", "20", "--min-alignment-query-coverage", "0.0")
        check("the script succeeds", done.returncode == 0)
        by = {(r["variant"], r["tool"]): r for r in table}
        check("baseline (MAPQ 20): tool_repeat is first, F1 0.8",
              by[("baseline", "tool_repeat")]["rank"] == "1" and by[("baseline", "tool_repeat")]["mean_value"] == "0.8000")
        check("baseline: tool_clean F1 0.6667", by[("baseline", "tool_clean")]["mean_value"] == "0.6667")
        check("MAPQ 0: the chromosome placement is charged and the order flips",
              by[("mapq=0", "tool_clean")]["rank"] == "1" and by[("mapq=0", "tool_repeat")]["rank"] == "2")
        check("MAPQ 0 F1 for tool_repeat is 0.6061", by[("mapq=0", "tool_repeat")]["mean_value"] == "0.6061")
        check("tau against baseline is -1 for the flip", by[("mapq=0", "tool_clean")]["kendall_tau_vs_baseline"] == "-1.000")
        check("the top tool is reported as changed", by[("mapq=0", "tool_clean")]["top_matches_baseline"] == "no")
        check("MAPQ 30 does not change it (the repeat is still filtered)", by[("mapq=30", "tool_clean")]["rank"] == "2")
        check("strict F1 flips it too (the 1600 unmapped bp are charged)", by[("metric:strict_f1", "tool_clean")]["rank"] == "1")
        check("the summary says the ranking is not settled", "do not present it as settled" in done.stdout)
        check("no drift warning when the baseline filters match scores.tsv", "WARNING" not in done.stderr)

    print("the baseline must be the leaderboard's")
    with tempfile.TemporaryDirectory() as tmp:
        done, _ = run(tmp, "--min-alignment-length", "1", "--min-alignment-identity", "0.0",
                      "--min-alignment-mapq", "0", "--min-alignment-query-coverage", "0.0")
        check("different filters than scores.tsv used -> a drift warning", "differs from scores.tsv" in done.stderr)

    print("nothing to re-score")
    with tempfile.TemporaryDirectory() as tmp:
        scores = Path(tmp) / "scores.tsv"
        scores.write_text("sample\ttool\tanalysis_track\tf1\ns1\tt\tshort_read\t0.5\n")
        done = subprocess.run([sys.executable, SCRIPT, "--scores", str(scores), "--results-dir", tmp,
                               "--out-prefix", str(Path(tmp) / "o")], capture_output=True, text=True)
        check("a missing PAF is a clear error, not a crash", done.returncode != 0 and "nothing to re-score" in done.stderr)

    print()
    if not ok:
        print("RANK SENSITIVITY TESTS FAILED")
        sys.exit(1)
    print("ALL RANK SENSITIVITY TESTS PASSED")


if __name__ == "__main__":
    main()
