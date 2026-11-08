#!/usr/bin/env python3
"""Regression checks for the gaps closed from the reviewer question bank.

1. Probability calibration (Q66): Brier score, ECE and reliability table.
2. Trivial baselines (Q62/Q78/Q108): coverage rule, not-applicable exit,
   reference rule (when minimap2 is installed).
3. Aggregation: baseline flag, beats_best_baseline, calibration means,
   metadata completeness (Q85).
4. HTML: baselines/calibration, interpretation limits and metadata sections
   with navigation links, including empty states.
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)
from score_plasmids import calibration  # noqa: E402


def run(args, check=True):
    return subprocess.run([sys.executable] + args, check=check, capture_output=True, text=True)


def write(path, text):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check(ok, label, condition, detail=""):
    print(f"  {label} -> {bool(condition)}{(' ' + detail) if detail else ''}")
    return ok and bool(condition)


def calibration_checks(ok):
    truth = {"chr": ("CHROMOSOME", 100000), "p1": ("PLASMID", 10000)}
    covered = {"p1": [("a", 0, 5000), ("b", 5000, 10000)], "chr": [("c", 0, 5000), ("d", 5000, 10000)]}
    brier, ece, n, table = calibration(covered, {"a": 1.0, "b": 1.0, "c": 0.0, "d": 0.0}, truth)
    ok = check(ok, "perfect probabilities -> Brier 0, ECE 0", brier == 0 and ece == 0 and n == 4)
    brier, ece, n, _ = calibration(covered, {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5}, truth)
    ok = check(ok, "uninformative 0.5 everywhere -> Brier 0.25, ECE 0", abs(brier - 0.25) < 1e-9 and ece < 1e-9)
    brier, ece, n, _ = calibration(covered, {"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.9}, truth)
    ok = check(ok, "over-confident -> ECE 0.4", abs(ece - 0.4) < 1e-9, f"(ECE {ece:.3f})")
    brier, ece, n, _ = calibration(covered, {"a": 0.9, "zzz": 0.9}, truth)
    ok = check(ok, "records without truth alignment are not scored", n == 1)

    write("truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\np1\tPLASMID\t10000\n")
    write("cand.fa", ">a\n" + "A" * 5000 + "\n>c\n" + "A" * 5000 + "\n")
    write("cand.paf", "a\t5000\t0\t5000\t+\tp1\t10000\t0\t5000\t5000\t5000\t60\n"
                      "c\t5000\t0\t5000\t+\tchr\t100000\t0\t5000\t5000\t5000\t60\n")
    write("pred.fa", ">a\n" + "A" * 5000 + "\n")
    write("pred.paf", "a\t5000\t0\t5000\t+\tp1\t10000\t0\t5000\t5000\t5000\t60\n")
    write("scores.tsv", "record_id\tprobability\na\t0.8\nc\t0.3\n")
    run([os.path.join(PY, "score_plasmids.py"), "--truth", "truth.tsv", "--paf", "pred.paf", "--pred-fasta", "pred.fa",
         "--sample", "s1", "--tool", "t", "--out", "out.tsv", "--pred-scores", "scores.tsv",
         "--pred-candidates-fasta", "cand.fa", "--pred-candidates-paf", "cand.paf",
         "--pr-summary-out", "prs.tsv", "--calibration-out", "cal.tsv"])
    summary = read("prs.tsv")[0]
    ok = check(ok, "PR summary carries Brier/ECE", summary["brier_score"] == "0.065000"
               and summary["expected_calibration_error"] == "0.250000" and summary["calibration_records"] == "2")
    ok = check(ok, "reliability table has one row per occupied bin", len(read("cal.tsv")) == 2)
    return ok


def baseline_checks(ok):
    contigs = (">NODE_1_length_5000_cov_10.0\n" + "A" * 5000 + "\n>NODE_2_length_4000_cov_11.0\n" + "C" * 4000 + "\n"
               ">NODE_3_length_3000_cov_40.0\n" + "G" * 3000 + "\n>NODE_4_length_500_cov_90.0\n" + "T" * 500 + "\n")
    write("contigs.fa", contigs)
    run([os.path.join(PY, "baseline_predictors.py"), "coverage", "--contigs", "contigs.fa", "--out-prefix", "bc"])
    called = [line[1:].strip() for line in open("bc.plasmid.fasta") if line.startswith(">")]
    ok = check(ok, "coverage baseline calls the high-depth contig, not the short one",
               called == ["NODE_3_length_3000_cov_40.0"], str(called))
    ok = check(ok, "coverage baseline writes one-contig bins", len(read("bc.bins.tsv")) == 1)
    write("nodepth.fa", ">ctg1\nAAAA\n")
    result = run([os.path.join(PY, "baseline_predictors.py"), "coverage", "--contigs", "nodepth.fa",
                  "--out-prefix", "bn"], check=False)
    ok = check(ok, "no depth headers -> exit 3 (not applicable)", result.returncode == 3)
    if shutil.which("minimap2"):
        write("ref.fa", ">plasmidX\n" + ("ACGTTGCAAGGCTT" * 400) + "\n")
        write("q.fa", ">match\n" + ("ACGTTGCAAGGCTT" * 300) + "\n>other\n" + ("TTTTGGGGCCCCAAAA" * 300) + "\n")
        run([os.path.join(PY, "baseline_predictors.py"), "reference", "--contigs", "q.fa", "--reference", "ref.fa",
             "--out-prefix", "br"])
        probabilities = {r["record_id"]: float(r["probability"]) for r in read("br.scores.tsv")}
        ok = check(ok, "reference baseline scores every contig", set(probabilities) == {"match", "other"})
    else:
        print("  reference baseline: minimap2 not installed here, skipped (exercised in CI/Linux)")
    return ok


def aggregate_and_report_checks(ok):
    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1",
              "brier_score", "expected_calibration_error"]
    rows = []
    for i in range(6):
        rows.append([f"s{i}", "baseline_coverage", "short_read", 1, 0.5, 0.5, 0.5, "", ""])
        rows.append([f"s{i}", "good_tool", "short_read", 1, 0.9, 0.9, 0.9, 0.05, 0.02])
        rows.append([f"s{i}", "weak_tool", "short_read", 1, 0.3, 0.3, 0.3, "", ""])
    with open("agg.tsv", "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    write("sheet.tsv", "sample_id\torganism\tbioproject\n" + "".join(
        f"s{i}\t{'Escherichia coli' if i else ''}\tPRJ{i}\n" for i in range(6)))
    write("caps.tsv", "tool\tmethod_class\tbinning_capable\tanalysis_track\n"
                      "baseline_coverage\tbaseline\tno\tshort_read\ngood_tool\tclassification\tno\tshort_read\n"
                      "weak_tool\tclassification\tno\tshort_read\n")
    os.makedirs("results", exist_ok=True)
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "agg.tsv", "--sample-sheet", "sheet.tsv",
         "--capabilities", "caps.tsv", "--out-prefix", "results/benchmark"])
    board = {r["tool"]: r for r in read("results/benchmark.leaderboard.tsv")}
    ok = check(ok, "baseline flagged", board["baseline_coverage"]["is_baseline"] == "yes")
    ok = check(ok, "good tool beats the baseline", board["good_tool"]["beats_best_baseline"] == "yes")
    ok = check(ok, "weak tool does not beat the baseline", board["weak_tool"]["beats_best_baseline"] == "no")
    ok = check(ok, "calibration means aggregated",
               board["good_tool"]["mean_expected_calibration_error"] == "0.0200" and board["good_tool"]["n_calibrated"] == "6")
    completeness = {r["sample"]: r for r in read("results/benchmark.metadata_completeness.tsv")}
    ok = check(ok, "missing organism reported with its consequence",
               "organism" in completeness["s0"]["missing_fields"] and "species-balanced" in completeness["s0"]["consequences"])
    full = run([os.path.join(PY, "aggregate_results.py"), "--scores", "agg.tsv", "--out-prefix", "results/x"])
    ok = check(ok, "aggregation without a sample sheet still runs", full.returncode == 0)

    import report_question_bank as rq
    page = ("<nav><a href='#recommendations'>Recommendations</a></nav>"
            "<section id='recommendations'></section>")
    leaderboard = read("results/benchmark.leaderboard.tsv")
    html_out = rq.inject(page, "results", leaderboard)
    ok = check(ok, "three sections inserted before recommendations",
               html_out.index("id='baselines-calibration'") < html_out.index("id='interpretation-limits'")
               < html_out.index("id='metadata-completeness'") < html_out.index("<section id='recommendations'>"))
    ok = check(ok, "navigation links added in section order",
               html_out.index("href='#baselines-calibration'") < html_out.index("href='#metadata-completeness'")
               < html_out.index("href='#recommendations'"))
    ok = check(ok, "interpretation limits name what results do NOT show",
               "do NOT show" in html_out and "Transmission" in html_out)
    ok = check(ok, "weak tool verdict shown", "does NOT beat baseline" in html_out)
    empty = rq.inject(page, "no_such_dir", [])
    ok = check(ok, "empty states render instead of disappearing",
               "No scored tools." in empty and "No metadata-completeness table" in empty
               and "No replicon was excluded" in empty)
    os.makedirs(os.path.join("data", "s1"), exist_ok=True)
    write(os.path.join("data", "s1", "truth_labels.tsv"),
          "sequence_id\tlength\tsource_label\tfinal_label\tevidence_status\tplasmid_markers\tplasmid_reference_match\t"
          "rrna_genes\tlong_read_depth\tmarker_free\treason\n"
          "p9\t3000\tPLASMID\tAMBIGUOUS\tevaluated\t\t\t0\t\tyes\tno plasmid marker\n"
          "p1\t90000\tPLASMID\tPLASMID\tevaluated\treplicon:IncFII\t\t0\t\tno\tplasmid marker present\n")
    with_data = rq.inject(page, "results", leaderboard, "data")
    ok = check(ok, "excluded replicons listed with their reason",
               "id='excluded-replicons'" in with_data and "p9" in with_data and "no plasmid marker" in with_data
               and ">p1<" not in with_data)
    return ok


def cli_checks(ok):
    root = os.path.join(HERE, "..")
    for command in ("collect-truth-provenance", "discover-design-cohort"):
        result = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", root, command, "--help"],
                                cwd=root, capture_output=True, text=True)
        ok = check(ok, f"`plasbench {command}` is reachable from the CLI", result.returncode == 0)
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="question_bank_") as tmp:
        try:
            os.chdir(tmp)
            for step in (calibration_checks, baseline_checks, aggregate_and_report_checks, cli_checks):
                print(f"[{step.__name__}]")
                ok = step(ok)
        finally:
            os.chdir(HERE)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
