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

    print("alignment length, the headline metrics and the CPRR thresholds (plan A8)")
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results" / "s1"
        results.mkdir(parents=True)
        (results / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchromosome\tCHROMOSOME\t10000\nplasmidA\tPLASMID\t2000\n")
        (results / "pred_tool_short.plasmid.fasta").write_text(">c\n" + "A" * 300 + "\n")
        (results / "tool_short.pred_vs_ref.paf").write_text(paf("c", 300, 0, 300, "plasmidA", 2000, 0, 300, 60))
        (results / "pred_tool_long.plasmid.fasta").write_text(">c\n" + "A" * 1500 + "\n")
        (results / "tool_long.pred_vs_ref.paf").write_text(paf("c", 1500, 0, 1500, "plasmidA", 2000, 0, 1500, 60))
        scores = Path(tmp) / "scores.tsv"
        with open(scores, "w", newline="") as handle:
            w = csv.writer(handle, delimiter="\t", lineterminator="\n")
            w.writerow(["sample", "tool", "analysis_track", "f1", "recall", "strict_precision", "plasmid_recall", "plasmid_recall_ge90", "plasmid_recall_ge50", "lw_bin_f1", "lw_bin_f1_strict"])
            # tool_short pads its bins with sequence that aligns nowhere: first on the headline lw_bin_f1 (0.30), second once that sequence is charged (strict 0.15).
            w.writerow(["s1", "tool_short", "short_read", "0.2609", "0.15", "1.0", "0.0", "0.0", "0.0", "0.30", "0.15"])
            w.writerow(["s1", "tool_long", "short_read", "0.8571", "0.75", "1.0", "0.0", "0.0", "1.0", "0.20", "0.20"])
        prefix = str(Path(tmp) / "out")
        sweep = Path(prefix + ".cprr_threshold_sweep.tsv")
        sweep_rows = [("0.80", "tool_x", 0.5), ("0.80", "tool_y", 0.4), ("0.95", "tool_x", 0.2), ("0.95", "tool_y", 0.3), ("0.99", "tool_x", 0.1), ("0.99", "tool_y", 0.2), ("0.90", "tool_x", 0.3), ("0.90", "tool_y", 0.35)]
        sweep.write_text("analysis_track\ttask\ttool\tthreshold\tcprr\tcprr_isolate_mean\tn_isolates\tn_plasmids\n"
                         + "".join(f"short_read\treconstruction\t{tool}\t{t}\t{v}\t{v}\t6\t11\n" for t, tool, v in sweep_rows)
                         + "short_read\tclassification\ttool_z\t0.95\t0.9\t0.9\t6\t11\n")
        done = subprocess.run([sys.executable, SCRIPT, "--scores", str(scores), "--results-dir", str(Path(tmp) / "results"), "--out-prefix", prefix,
                               "--min-alignment-length", "1", "--min-alignment-identity", "0.0", "--min-alignment-mapq", "0", "--min-alignment-query-coverage", "0.0"],
                              capture_output=True, text=True)
        table = list(csv.DictReader(open(prefix + ".rank_robustness.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        by = {(r["variant"], r["tool"]): r for r in table}
        check("the script succeeds and the table ends with compared_with", done.returncode == 0 and list(table[0])[-1] == "compared_with")
        check("min_length=100 keeps a 300 bp alignment: the same F1 as the baseline", by[("min_length=100", "tool_short")]["mean_value"] == by[("baseline", "tool_short")]["mean_value"] == "0.2609")
        check("min_length=500 drops it: tool_short has no retained alignment, F1 0", by[("min_length=500", "tool_short")]["mean_value"] == "0.0000"
              and by[("min_length=500", "tool_long")]["mean_value"] == by[("baseline", "tool_long")]["mean_value"])
        check("the headline short-read endpoint is an alternative ranking: tool_short first on lw_bin_f1, tool_long first on the baseline",
              by[("metric:lw_bin_f1", "tool_short")]["rank"] == "1" and by[("baseline", "tool_long")]["rank"] == "1" and by[("metric:lw_bin_f1", "tool_short")]["top_matches_baseline"] == "no")
        check("padding shows up: tool_short is first on lw_bin_f1 but second on lw_bin_f1_strict, and the strict row says its top differs from the headline row",
              by[("metric:lw_bin_f1", "tool_short")]["rank"] == "1" and by[("metric:lw_bin_f1_strict", "tool_short")]["rank"] == "2"
              and by[("metric:lw_bin_f1_strict", "tool_long")]["rank"] == "1")
        check("the 50% recovery band is an alternative ranking", ("metric:plasmid_recall_ge50", "tool_long") in by and by[("metric:plasmid_recall_ge50", "tool_long")]["rank"] == "1")
        check("the baseline-family rows say they are compared with the baseline", all(r["compared_with"] == "baseline" for r in table if not r["variant"].startswith("cprr@")))
        cprr = [r for r in table if r["variant"].startswith("cprr@")]
        check("CPRR thresholds 0.80, 0.90, 0.95 and 0.99 are re-ranked, for reconstruction only (the classification row is ignored)",
              sorted({r["variant"] for r in cprr}) == ["cprr@0.80", "cprr@0.90", "cprr@0.95", "cprr@0.99"] and "tool_z" not in {r["tool"] for r in cprr})
        by = {(r["variant"], r["tool"]): r for r in cprr}
        check("they are compared with the pre-registered 0.95 ranking, not with the F1 baseline", all(r["compared_with"] == "cprr@0.95" for r in cprr)
              and by[("cprr@0.95", "tool_x")]["kendall_tau_vs_baseline"] == "1.000" and by[("cprr@0.95", "tool_x")]["top_matches_baseline"] == "yes")
        check("a reversed order at 0.80 gives tau -1 and a changed top tool; the same order at 0.99 gives tau 1",
              by[("cprr@0.80", "tool_x")]["kendall_tau_vs_baseline"] == "-1.000" and by[("cprr@0.80", "tool_x")]["top_tool"] == "tool_x"
              and by[("cprr@0.80", "tool_x")]["top_matches_baseline"] == "no" and by[("cprr@0.99", "tool_x")]["kendall_tau_vs_baseline"] == "1.000")
        check("the summary flags the changed rankings", "cprr@0.80" in done.stdout and "ranking changes" in done.stdout)
    # the report's table shows the new column
    source = (Path(SCRIPT).parent / "build_html_report.py").read_text(encoding="utf-8")
    check("the report's sensitivity table has a Compared with column", "<th>Compared with</th>" in source and "versus=esc(row.get(\"compared_with\") or \"baseline\")" in source)
    print("the CPRR baseline follows the configured criteria")
    check("the default configuration is the 0.95 line", rs.cprr_baseline({}) == "0.95")
    check("a configured 0.90 moves the baseline with it", rs.cprr_baseline({"CPRR_MIN_COVERAGE": "0.90", "CPRR_MIN_SHARE": "0.90"}) == "0.90")
    check("coverage and share set apart, or off the grid, give no baseline (no sweep is labelled pre-registered)",
          rs.cprr_baseline({"CPRR_MIN_COVERAGE": "0.90", "CPRR_MIN_SHARE": "0.95"}) is None and rs.cprr_baseline({"CPRR_MIN_COVERAGE": "0.97", "CPRR_MIN_SHARE": "0.97"}) is None
          and rs.cprr_baseline({"CPRR_MIN_COVERAGE": "x"}) is None)
    check("the docstring says what the sweeps cover", "BASE-LEVEL F1" in rs.__doc__ and "metric:lw_bin_f1" in rs.__doc__)
    print("the audit-clean cohort variant")
    check("audit_clean_only is a cohort variant", "audit_clean_only" in rs.COHORT_VARIANTS and "audit_clean_only" in rs.variant_order())
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        tab, nl = chr(9), chr(10)
        for sample, flagged in (("clean", False), ("odd", True)):
            (t / sample).mkdir()
            rows = ["sequence_id" + tab + "molecule_type" + tab + "length", "chr" + tab + "CHROMOSOME" + tab + "4000000"]
            rows += ["chr2" + tab + "CHROMOSOME" + tab + "600000"] if flagged else []
            rows += ["p1" + tab + "PLASMID" + tab + "5000"]
            (t / sample / "truth.tsv").write_text(nl.join(rows) + nl)
        found = rs.audit_clean_samples(t, None, {"clean", "odd", "nodata"})
        check("a sample the audit flags (a second large chromosome) is left out, an unflagged one kept, one without truth files is not audited", found == {"clean"})
        check("no truth files at all: the variant is not written", rs.audit_clean_samples(t, None, {"nodata"}) is None)

    print()
    if not ok:
        print("RANK SENSITIVITY TESTS FAILED")
        sys.exit(1)
    print("ALL RANK SENSITIVITY TESTS PASSED")


if __name__ == "__main__":
    main()
