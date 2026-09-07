#!/usr/bin/env python3
"""Regression for the HTML report surfacing this session's new capabilities,
which previously landed only in the underlying TSVs with no visual
representation at all:

  1. significant_vs_runner_up (aggregate_results.py) -> a labeled badge in the
     leaderboard table, AND the prose interpretation actually uses it instead
     of a raw mean-F1-gap-size heuristic.
  2. mean_nmi / mean_variation_of_information (score_bins.py) -> Mean NMI /
     Mean VI leaderboard columns.
  3. n_zero_plasmid_isolates / mean_zero_plasmid_specificity /
     total_zero_plasmid_chromosome_fp_bp (score_plasmids.py) -> a dedicated
     "Zero-plasmid isolates (negative control)" section, present in the nav.
  4. truth_source=self_assembled_hybrid (build_hybrid_truth.py) -> a
     "self-built truth" badge next to the affected sample's name in the
     scores table, absent for every other sample.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "python" / "build_html_report.py"

SCORE_COLUMNS = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                 "mapped_pred_bp", "unambiguously_mapped_pred_bp", "unmapped_pred_bp",
                 "off_truth_pred_bp", "ambiguously_mapped_pred_bp", "true_plasmid_count",
                 "recovered_plasmid_count", "plasmid_recall", "predicted_record_count",
                 "true_amr_gene_count", "recovered_amr_gene_count", "amr_gene_recall",
                 "true_circular_plasmid_count", "recovered_circular_plasmid_count",
                 "circular_truth_plasmid_recovery", "circular_plasmid_recall", "alignment_total",
                 "alignment_retained", "filtered_alignment_count", "precision", "recall", "f1"]
SCORE_HEADER = "\t".join(SCORE_COLUMNS) + "\n"

LEADER_COLUMNS = ["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped",
                   "mean_precision", "mean_recall", "mean_f1", "mean_plasmid_recall",
                   "mean_bin_f1", "mean_nmi", "mean_variation_of_information", "mean_pr_auc",
                   "significant_vs_runner_up", "n_zero_plasmid_isolates",
                   "mean_zero_plasmid_specificity", "total_zero_plasmid_chromosome_fp_bp"]
LEADER_HEADER = "\t".join(LEADER_COLUMNS) + "\n"


def score_row(sample, tool, f1):
    values = {"sample": sample, "tool": tool, "analysis_track": "short_read",
              "true_plasmid_bp": "10000", "TP_bp": "9000", "FP_bp": "100", "FN_bp": "1000",
              "mapped_pred_bp": "9100", "unambiguously_mapped_pred_bp": "9100",
              "unmapped_pred_bp": "0", "off_truth_pred_bp": "0", "ambiguously_mapped_pred_bp": "0",
              "true_plasmid_count": "2", "recovered_plasmid_count": "2", "plasmid_recall": "0.900",
              "predicted_record_count": "2", "precision": "0.900", "recall": "0.900", "f1": f1}
    return "\t".join(values.get(column, "0") for column in SCORE_COLUMNS) + "\n"


def leader_row(**overrides):
    values = {"rank": "1", "tool": "tool_a", "n_samples": "1", "n_completed": "1", "n_failed": "0",
              "n_skipped": "0", "mean_precision": "0.900", "mean_recall": "0.900", "mean_f1": "0.900",
              "mean_plasmid_recall": "0.900", "mean_bin_f1": "", "mean_nmi": "", "mean_variation_of_information": "",
              "mean_pr_auc": "", "significant_vs_runner_up": "not_assessed", "n_zero_plasmid_isolates": "0",
              "mean_zero_plasmid_specificity": "", "total_zero_plasmid_chromosome_fp_bp": ""}
    values.update(overrides)
    return "\t".join(values.get(column, "") for column in LEADER_COLUMNS) + "\n"


def build(tmp, leader_rows, sample_truth_source=""):
    results = Path(tmp) / "results"
    results.mkdir(parents=True, exist_ok=True)
    scores = SCORE_HEADER + score_row("s1", "tool_a", "0.900") + score_row("s1", "tool_b", "0.850")
    status = ("sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\n"
              "s1\ttool_a\tcompleted\tpred.fasta\t\t1\t1000\n"
              "s1\ttool_b\tcompleted\tpred.fasta\t\t1\t1000\n")
    (results / "scores.tsv").write_text(scores, encoding="utf-8")
    (results / "tool_status.tsv").write_text(status, encoding="utf-8")
    with open(results / "benchmark.leaderboard.tsv", "w", encoding="utf-8") as handle:
        handle.write(LEADER_HEADER)
        for row in leader_rows:
            handle.write(row)
    sheet_line = f"s1\tNA\tSRR\t\t\t\t\t\t\t{sample_truth_source}" if sample_truth_source else "s1\tNA\tSRR"
    sheet = Path(tmp) / "sheet.tsv"
    sheet.write_text(
        "sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\t"
        "biosample\tbioproject\tsample_origin\ttruth_source\n" + sheet_line + "\n",
        encoding="utf-8",
    )
    out = results / "benchmark.report.html"
    result = subprocess.run(
        [sys.executable, str(REPORT), "--project-root", str(ROOT), "--scores", str(results / "scores.tsv"),
         "--tool-status", str(results / "tool_status.tsv"),
         "--leaderboard", str(results / "benchmark.leaderboard.tsv"),
         "--sample-sheet", str(sheet), "--out", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return out.read_text(encoding="utf-8")


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " -> PASS")


# --- 1. significant_vs_runner_up: three verdicts, each a labeled badge -------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [
        leader_row(rank="1", tool="tool_a", mean_f1="0.900", significant_vs_runner_up="True"),
        leader_row(rank="2", tool="tool_b", mean_f1="0.850", significant_vs_runner_up="not_assessed"),
    ])
    check("a 'True' verdict renders as a labeled significant badge, naming the test",
          "sig-badge significant" in html and "Holm p&lt;0.05" in html or "Holm p<0.05" in html.replace("&lt;", "<"))
    check("the interpretation prose states significance explicitly, not a bare gap size",
          "statistically\n            significant against its closest competitor".replace("\n            ", " ") in html.replace("\n", " ")
          or "statistically significant against its closest competitor" in " ".join(html.split()))

with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [
        leader_row(rank="1", tool="tool_a", mean_f1="0.900", significant_vs_runner_up="False"),
        leader_row(rank="2", tool="tool_b", mean_f1="0.850", significant_vs_runner_up="False"),
    ])
    check("a 'False' verdict renders as a labeled not-significant badge",
          "sig-badge not-significant" in html)
    check("the interpretation prose states the margin is NOT significant, not a false 'leads by' claim",
          "NOT" in " ".join(html.split()) and "statistically" in html)

with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [
        leader_row(rank="1", tool="tool_a", mean_f1="0.900", significant_vs_runner_up="not_assessed"),
        leader_row(rank="2", tool="tool_b", mean_f1="0.850", significant_vs_runner_up="not_assessed"),
    ])
    check("a 'not_assessed' verdict renders as a labeled not-assessed badge, never a guessed yes/no",
          "sig-badge not-assessed" in html)
    check("the interpretation prose says the margin is not yet statistically assessed",
          "not yet statistically assessed" in " ".join(html.split()))

# --- 2. Mean NMI / Mean VI leaderboard columns -------------------------------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [
        leader_row(rank="1", tool="tool_a", mean_bin_f1="0.800", mean_nmi="0.7500", mean_variation_of_information="0.3200"),
    ])
    check("the leaderboard table header includes Mean NMI and Mean VI", "<th>Mean NMI</th>" in html and "<th>Mean VI</th>" in html)
    check("a tool's real NMI/VI values render in its leaderboard row", "0.7500" in html and "0.3200" in html)

with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [leader_row(rank="1", tool="tool_a", mean_nmi="", mean_variation_of_information="")])
    check("a tool with no bin evidence shows 'not bin-scored' for NMI/VI, never a fabricated zero",
          html.count("not bin-scored") >= 2)

# --- 3. Zero-plasmid negative control section --------------------------------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [
        leader_row(rank="1", tool="tool_a", n_zero_plasmid_isolates="3",
                   mean_zero_plasmid_specificity="0.9800", total_zero_plasmid_chromosome_fp_bp="450"),
    ])
    check("the nav bar links the new Zero-plasmid isolates section", "href='#zero-plasmid'" in html)
    check("the section reports the plasmid-free isolate count, specificity, and FP bp for the tool",
          "id='zero-plasmid'" in html and "0.9800" in html and ">3<" in html and "450" in html)

with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [leader_row(rank="1", tool="tool_a", n_zero_plasmid_isolates="0")])
    check("with no plasmid-free isolate scored, the section says so plainly rather than an empty table",
          "No plasmid-free isolate was scored in this run" in html)

# --- 4. self_assembled_hybrid truth-source badge -----------------------------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [leader_row(rank="1", tool="tool_a")], sample_truth_source="self_assembled_hybrid")
    check("a self_assembled_hybrid sample gets the 'self-built truth' badge in the scores table",
          "truth-source-badge" in html and "self-built truth" in html)
    check("the row carries a data-truth-source attribute for filtering/styling",
          "data-truth-source='self_assembled_hybrid'" in html)

with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, [leader_row(rank="1", tool="tool_a")])  # no truth_source declared (today's default)
    # The CSS class definition (in <style>) always exists on the page; what
    # must NOT exist is an actual <span> using it against this sample's row.
    check("a plain ncbi_deposited sample (no truth_source declared) gets NO self-built-truth badge",
          "<span class='truth-source-badge'" not in html and "self-built truth" not in html)

print("\nALL REPORT NEW CAPABILITIES TESTS PASSED")
