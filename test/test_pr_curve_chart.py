#!/usr/bin/env python3
"""Regression for the PR-curve/PR-AUC pieces of python/build_html_report.py:
the leaderboard's supplementary Mean PR-AUC column, the per-sample PR-curve
chart (a genuinely new 2-axis XY chart, unlike this report's other bar-style
charts), and that a tool with no probability data is completely unaffected
(no chart, no column noise, no crash on the direct-indexing paths the rest of
the per-sample table relies on).
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from build_html_report import pr_curve_chart, read_pr_curve  # noqa: E402


def test_pr_curve_chart_unit():
    assert "No PR-curve data" in pr_curve_chart([])

    points = [
        {"threshold": "inf", "precision": "1.0000", "recall": "0.0000"},
        {"threshold": "0.9", "precision": "0.9000", "recall": "0.5000"},
        {"threshold": "0.3", "precision": "0.6000", "recall": "1.0000"},
    ]
    svg = pr_curve_chart(points, pr_auc=0.75)
    assert "pr-chart" in svg, "expected the pr-chart class on the rendered svg"
    assert svg.count("<circle") == 3, "expected one point per swept threshold"
    assert "PR-AUC 0.750" in svg, "expected the PR-AUC value to be labelled on the chart"
    assert "polyline" in svg, "expected a connecting line across the swept points"

    # No pr_auc supplied: chart still renders (points alone are still useful),
    # but the label says so honestly rather than fabricating a number.
    svg_no_auc = pr_curve_chart(points, pr_auc=None)
    assert "PR-AUC not available" in svg_no_auc


def test_read_pr_curve(tmp_path):
    results_dir = tmp_path / "results"
    (results_dir / "s1").mkdir(parents=True)
    curve = results_dir / "s1" / "genomad.pr_curve.tsv"
    curve.write_text("threshold\tprecision\trecall\ttp_bp\tfp_bp\tfn_bp\n"
                      "inf\t1.0000\t0.0000\t0\t0\t100\n"
                      "0.9\t0.9000\t0.5000\t50\t6\t50\n", encoding="utf-8")
    points = read_pr_curve(results_dir, "s1", "genomad")
    assert len(points) == 2
    assert points[0]["threshold"] == "inf"

    # Absent entirely (a tool with no probability output) -- not an error.
    assert read_pr_curve(results_dir, "s1", "mob_recon") == []


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def test_end_to_end_report(tmp_path):
    """A real (minimal) build_html_report.py invocation: one tool with real
    PR-curve data, one tool with none, in the same sample."""
    results_dir = tmp_path / "results"
    sample_dir = results_dir / "s1"
    sample_dir.mkdir(parents=True)

    scores_header = ("sample\ttool\tanalysis_track\ttrue_plasmid_bp\tTP_bp\tFP_bp\tFN_bp\t"
                      "mapped_pred_bp\tunambiguously_mapped_pred_bp\tunmapped_pred_bp\t"
                      "off_truth_pred_bp\tambiguously_mapped_pred_bp\tprecision\trecall\tf1\t"
                      "pr_auc\tpr_n_thresholds\n")
    genomad_row = "s1\tgenomad\tshort_read\t1000\t900\t100\t100\t1000\t1000\t0\t0\t0\t0.9000\t0.9000\t0.9000\t0.8000\t3\n"
    mob_row = "s1\tmob_recon\tshort_read\t1000\t950\t0\t50\t950\t950\t0\t0\t0\t1.0000\t0.9500\t0.9744\t\t\n"
    write(results_dir / "scores.tsv", scores_header + genomad_row + mob_row)

    write(sample_dir / "genomad.pr_curve.tsv",
          "threshold\tprecision\trecall\ttp_bp\tfp_bp\tfn_bp\n"
          "inf\t1.0000\t0.0000\t0\t0\t1000\n"
          "0.5\t0.9000\t0.9000\t900\t100\t100\n")

    write(results_dir / "tool_status.tsv",
          "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n"
          "s1\tgenomad\tcompleted\tpred_genomad.plasmid.fasta\t\t1\t1000\n"
          "s1\tmob_recon\tcompleted\tpred_mob_recon.plasmid.fasta\t\t1\t1000\n")

    write(results_dir / "benchmark.leaderboard.tsv",
          "rank\ttool\tn_samples\tn_completed\tn_failed\tn_skipped\tmean_precision\t"
          "mean_recall\tmean_plasmid_recall\tn_bin_scored\tmean_bin_f1\tn_pr_scored\tmean_pr_auc\t"
          "mean_f1\tf1_ci_low\tf1_ci_high\tmedian_f1\n"
          "1\tmob_recon\t1\t1\t0\t0\t1.0000\t0.9500\t\t0\t\t0\t\t0.9744\t\t\t0.9744\n"
          "2\tgenomad\t1\t1\t0\t0\t0.9000\t0.9000\t\t0\t\t1\t0.8000\t0.9000\t\t\t0.9000\n")

    # build_html_report.py resolves results_dir as out.parent, matching
    # scripts/06_aggregate.sh's convention of writing the report directly
    # into $RESULTS_DIR -- so the report must live inside results_dir here
    # too, for read_pr_curve() to find sibling per-sample pr_curve.tsv files.
    out = results_dir / "report.html"
    subprocess.run([
        sys.executable, os.path.join(ROOT, "python", "build_html_report.py"),
        "--project-root", str(ROOT),
        "--scores", str(results_dir / "scores.tsv"),
        "--tool-status", str(results_dir / "tool_status.tsv"),
        "--leaderboard", str(results_dir / "benchmark.leaderboard.tsv"),
        "--out", str(out),
    ], check=True, capture_output=True, text=True)

    html = out.read_text(encoding="utf-8")
    assert "Mean PR-AUC" in html, "expected the leaderboard's new supplementary column header"
    assert "0.8000" in html, "expected genomad's mean_pr_auc value in the leaderboard"
    assert "not probability-scored" in html, "expected mob_recon's leaderboard cell to say so honestly, not blank or zero"
    assert "pr-chart" in html, "expected a PR-curve chart to be rendered for genomad"
    assert "PR-AUC 0.800" in html, "expected genomad's per-sample PR-AUC label"
    # mob_recon has no pr_auc: it must get exactly one chart-card (genomad's),
    # not a second one rendered for a tool with no probability data. (The
    # class name also appears once in the page's own <style> block.)
    assert html.count("class='chart-card pr-chart-card'") == 1


def main():
    test_pr_curve_chart_unit()
    print("pr_curve_chart(): PASS")

    import pathlib
    with tempfile.TemporaryDirectory(prefix="pr_curve_") as tmp:
        test_read_pr_curve(pathlib.Path(tmp))
    print("read_pr_curve(): PASS")

    with tempfile.TemporaryDirectory(prefix="pr_curve_e2e_") as tmp:
        test_end_to_end_report(pathlib.Path(tmp))
    print("end-to-end report (leaderboard column + per-sample chart): PASS")

    print("ALL PR CURVE CHART TESTS PASSED")


if __name__ == "__main__":
    main()
