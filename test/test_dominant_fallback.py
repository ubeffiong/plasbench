#!/usr/bin/env python3
"""A study that holds most of the isolates switches the default interval to the percentile bootstrap (python/resampling.py; third review, statistical validation).

The full simulation found the cluster-t interval covers only 64-79% of a nominal 95% when one study holds about 60% of the isolates or two hold 80%. So:
  - dominant_share() is the largest cluster's share; interval_method_used() gives cluster_t below PLASBENCH_DOMINANT_SHARE (0.30) and percentile above it;
  - an explicit method is always honoured, and PLASBENCH_DOMINANT_FALLBACK=0 (DOMINANT_FALLBACK) turns the fallback off;
  - the real aggregate_results.py records the method actually used (leaderboard ci_method, paired table ci_method), the largest study share and a dominant_study flag;
  - the report says so in the Headline design tab;
  - the production CLI default needs the pre-registered five independent clusters: four qualifying clusters cannot give an available primary headline.
"""
import csv
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import resampling as rs  # noqa: E402

AGGREGATE = ROOT / "python" / "aggregate_results.py"
HEADER = ["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "unmapped_pred_bp", "precision", "recall", "f1", "bin_precision", "bin_recall", "bin_f1",
          "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events", "contaminated_bins"]


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the rule")
    rng = random.Random(1)
    values = [rng.gauss(0.5, 0.1) for _ in range(30)]
    dominated = ["big"] * 18 + [f"s{i}" for i in range(12)]
    balanced = [f"s{i % 10}" for i in range(30)]
    check("dominant_share is the largest cluster's share", rs.dominant_share(values, dominated) == 0.6 and abs(rs.dominant_share(values, balanced) - 0.1) < 1e-9)
    check("no cluster labels means no dominance", rs.dominant_share(values, None) == 0.0)
    check("the default is cluster t, and percentile when one study holds more than the limit",
          rs.interval_method_used(values, balanced) == rs.INTERVAL_METHOD == "cluster_t" and rs.interval_method_used(values, dominated) == "percentile")
    check("an explicit method is honoured even when one study dominates", rs.interval_method_used(values, dominated, method="cluster_t") == "cluster_t")
    check("the limit is 0.30 by default", rs.DOMINANT_STUDY_SHARE == 0.30)
    low, high = rs.interval(values, dominated)
    check("the interval of a dominated cohort is the percentile bootstrap's", (low, high) == rs.stratified_bootstrap(values, dominated, None, iterations=1000))
    saved = rs.DOMINANT_FALLBACK
    rs.DOMINANT_FALLBACK = False
    check("the fallback can be turned off", rs.interval_method_used(values, dominated) == "cluster_t")
    rs.DOMINANT_FALLBACK = saved

    print("aggregation records what was used")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def build(sizes):
            """scores for two tools over studies of the given sizes (one study per BioProject)."""
            sheet, rows, n = ["sample_id\tbioproject\torganism"], [], 0
            for study, size in enumerate(sizes):
                for _ in range(size):
                    sample = f"s{n}"
                    n += 1
                    sheet.append(f"{sample}\tPRJ{study}\tEscherichia coli")
                    for tool, f1 in (("tool_a", 0.8), ("tool_b", 0.6)):
                        value = f"{max(0.0, min(1.0, f1 + rng.gauss(0, 0.05))):.3f}"
                        rows.append([sample, tool, 100, 80, 20, 20, 0, value, value, value, "0.5", "0.5", "0.5", 1, 1, 1, 2, 3, 4])
            (tmp / "sheet.tsv").write_text("\n".join(sheet) + "\n", encoding="utf-8")
            with open(tmp / "scores.tsv", "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                writer.writerow(HEADER)
                writer.writerows(rows)
            (tmp / "prov.tsv").write_text("sample\treference_tier\tevaluation_independence\n" + "".join(f"s{i}\t1\tindependent\n" for i in range(n)), encoding="utf-8")

        def run(prefix, *extra):
            done = subprocess.run([sys.executable, str(AGGREGATE), "--scores", str(tmp / "scores.tsv"), "--sample-sheet", str(tmp / "sheet.tsv"), "--tool-status", str(tmp / "none.tsv"),
                                   "--truth-provenance", str(tmp / "prov.tsv"), "--out-prefix", str(tmp / prefix), *extra], capture_output=True, text=True)
            board = list(csv.DictReader(open(tmp / f"{prefix}.leaderboard.tsv", newline="", encoding="utf-8"), delimiter="\t")) if done.returncode == 0 else []
            pairs = list(csv.DictReader(open(tmp / f"{prefix}.paired_comparisons.tsv", newline="", encoding="utf-8"), delimiter="\t")) if done.returncode == 0 else []
            return done, board, pairs

        build([12] + [2] * 8)   # one study holds 12 of 28 isolates (43%)
        done, board, pairs = run("dom", "--headline-min-clusters", "1")
        check("a dominated cohort: ci_method percentile, share 0.4286, dominant_study yes", board and board[0]["ci_method"] == "percentile" and board[0]["dominant_study"] == "yes"
              and abs(float(board[0]["max_cluster_share"]) - 12 / 28) < 1e-3, (done.stderr[-300:], board[:1]))
        check("the paired comparisons record the method used", pairs and pairs[0]["ci_method"] == "percentile", pairs[:1])
        design = list(csv.DictReader(open(tmp / "dom.headline_design.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        check("the headline design records the limit", design and abs(float(design[0]["dominant_study_share_limit"]) - 0.3) < 1e-9, design[:1])
        build([3] * 10)
        done, board, pairs = run("bal", "--headline-min-clusters", "1")
        check("a balanced cohort keeps cluster t, share 0.1, dominant_study no", board and board[0]["ci_method"] == "cluster_t" and board[0]["dominant_study"] == "no"
              and abs(float(board[0]["max_cluster_share"]) - 0.1) < 1e-3 and pairs[0]["ci_method"] == "cluster_t", (done.stderr[-300:], board[:1]))

        print("the production default needs five independent clusters")
        build([3] * 4)
        done, board, _ = run("four")   # no --headline-min-clusters: the CLI default (HEADLINE_MIN_CLUSTERS, 5)
        check("four independent clusters: the primary analysis is unavailable", board and board[0]["primary_status"] == "unavailable" and "only 4 independent cluster" in done.stdout, (done.stdout[-400:], board[:1]))
        build([3] * 5)
        done, board, _ = run("five")
        check("five independent clusters: available", board and board[0]["primary_status"] == "available", (done.stdout[-300:], board[:1]))

        print("the report")
        out = tmp / "report.html"
        (tmp / "tool_status.tsv").write_text("sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\n", encoding="utf-8")
        build([12] + [2] * 8)
        run("benchmark", "--headline-min-clusters", "1")   # the report reads the benchmark.* tables beside the scores
        (tmp / "benchmark.truth_provenance.tsv").write_text((tmp / "prov.tsv").read_text(encoding="utf-8"), encoding="utf-8")
        report = subprocess.run([sys.executable, str(ROOT / "python" / "build_html_report.py"), "--project-root", str(ROOT), "--scores", str(tmp / "scores.tsv"),
                                 "--tool-status", str(tmp / "tool_status.tsv"), "--leaderboard", str(tmp / "benchmark.leaderboard.tsv"), "--out", str(out)], capture_output=True, text=True)
        html = out.read_text(encoding="utf-8") if out.is_file() else ""
        check("the Headline design tab shows the study structure and the dominated flag",
              "Study structure and interval method" in html and "one study holds most of the isolates" in html and "percentile" in html, report.stderr[-300:])

    print("ALL DOMINANT FALLBACK TESTS PASSED" if ok else "DOMINANT FALLBACK TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
