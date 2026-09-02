#!/usr/bin/env python3
"""Regression checks for the linked visual explorer in the HTML report.

The offline demo produces no visualization payload, so this exercises the
build_visualization_data -> build_html_report path directly.
"""

import csv
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
VISUAL = os.path.join(ROOT, "python", "build_visualization_data.py")
REPORT = os.path.join(ROOT, "python", "build_html_report.py")

PAF = [
    # q1 recovers pA cleanly; q2 recovers pB; q3 is a chromosomal record wrongly
    # called plasmid; q4 is chimeric -- it supports pA but also maps to pB.
    ("q1", 2000, 0, 2000, "+", "pA", 2000, 0, 2000),
    ("q2", 1500, 0, 1500, "+", "pB", 1500, 0, 1500),
    ("q3", 400, 0, 400, "+", "chr1", 8000, 0, 400),
    ("q4", 300, 0, 300, "-", "pA", 2000, 100, 400),
    ("q4", 300, 0, 300, "+", "pB", 1500, 10, 310),
]


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, delimiter="\t").writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="visual_report_") as tmp:
        results = os.path.join(tmp, "results")
        sample_dir = os.path.join(results, "s1")
        os.makedirs(sample_dir)
        truth = os.path.join(tmp, "truth.tsv")
        write(truth, [["sequence_id", "molecule_type", "length"],
                      ["chr1", "CHROMOSOME", 8000], ["pA", "PLASMID", 2000], ["pB", "PLASMID", 1500]])
        circular = os.path.join(tmp, "circular.tsv")
        write(circular, [["sequence_id"], ["pA"]])
        with open(os.path.join(sample_dir, "toolx.pred_vs_ref.paf"), "w", encoding="utf-8") as handle:
            for row in PAF:
                handle.write("\t".join(str(x) for x in row) + "\t100\t100\t60\n")

        blocks = os.path.join(sample_dir, "visualization", "alignment_blocks.json")
        subprocess.run([sys.executable, VISUAL, "--truth", truth, "--results-dir", results,
                        "--sample", "s1", "--circular-truth", circular, "--out", blocks], check=True)
        assert os.path.isfile(blocks), "visualization payload was not written"

        scores = os.path.join(results, "scores.tsv")
        write(scores, [["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                        "unmapped_pred_bp", "plasmid_recall", "precision", "recall", "f1"],
                       ["s1", "toolx", 3500, 3500, 400, 0, 0, "1.0000", "0.8974", "1.0000", "0.9459"]])
        leaderboard = os.path.join(results, "benchmark.leaderboard.tsv")
        write(leaderboard, [["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped",
                             "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1",
                             "mean_f1", "f1_ci_low", "f1_ci_high", "median_f1"],
                            [1, "toolx", 1, 1, 0, 0, "0.8974", "1.0000", "1.0000", "",
                             "0.9459", "0.9459", "0.9459", "0.9459"]])
        out = os.path.join(results, "report.html")
        subprocess.run([sys.executable, REPORT, "--project-root", ROOT, "--scores", scores,
                        "--tool-status", os.path.join(results, "absent.tsv"),
                        "--leaderboard", leaderboard, "--out", out], check=True)
        page = open(out, encoding="utf-8").read()

    # Accessibility: status must not be encoded by colour alone, and the grid
    # must be reachable without a pointer.
    for needed in ("vq-glyph", "tabindex", "aria-label", "ArrowDown", "focus-visible"):
        assert needed in page, f"accessibility affordance missing: {needed}"
    # Selections must be shareable.
    assert "history.replaceState" in page and "URLSearchParams" in page, "URL state missing"
    # Cohort narrowing and the visible-record count.
    for needed in ("vq-filters", "vq-reset", "vq-search", "vq-order", "Showing "):
        assert needed in page, f"filter affordance missing: {needed}"
    assert "Number(c.innerText)" not in page, "row ordering must use source metrics, not decorated cell text"
    assert 'id="vq-filter"' not in page, "legacy duplicate visual filters must not be emitted"
    # Per-plasmid summary and the contamination surfacing that completeness hides.
    for needed in ("vq-summary", "Impure records", "Chromosomal contamination for",
                   "not attributable to any truth plasmid", "vq-impure"):
        assert needed in page, f"plasmid summary affordance missing: {needed}"
    # Dot plots retain one query-coordinate system per selected predicted record,
    # while diagnostics and curated context are visibly wired into the report.
    for needed in ("Predicted record", "One predicted-record coordinate system",
                   "Structural alignment diagnostics", "data-context-feature",
                   "Concordance proxy"):
        assert needed in page, f"visual diagnostic affordance missing: {needed}"
    assert "function renderDot" not in page, "legacy mixed-coordinate dot-plot renderer must not be emitted"

    # Cohort dashboard: headline cards and distribution plots from measured data.
    for needed in ("vq-stats", "vq-dist", "Leading method", "Hardest sample",
                   "Excluded runs", "Mean plasmid recall",
                   "Structural collinearity", "Runtime (min)", "Peak memory (GB)"):
        assert needed in page, f"cohort dashboard affordance missing: {needed}"
    # An unmeasured metric must say so rather than plot fabricated zeros.
    assert "No measured values for this metric" in page, "missing-metric wording absent"
    assert "not counted as zero" in page or "rather than as zero" in page or         "excluded rather than counted as zero" in page, "zero-substitution caveat absent"
    # Only cohort selects may filter; an ordering control must not hide every row.
    assert "select[data-k]" in page, "filter loop must be scoped to cohort selects"
    # The programme rename must hold in the shipped page.
    assert "PlasBench plasmid benchmark report" in page, "report title not renamed"
    assert "PlasBench plasmid reconstruction benchmark" in page, "report heading not renamed"
    # Only the report's own branding is asserted: a user's directory may legitimately
    # contain "SPREAD" and would surface through the artifact explorer's file paths.
    for banner in ("SPREAD plasmid benchmark report", "SPREAD plasmid reconstruction benchmark"):
        assert banner not in page, f"legacy programme branding remains: {banner}"

    print("ALL VISUAL REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
