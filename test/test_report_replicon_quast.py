#!/usr/bin/env python3
"""The recovery-by-replicon and QUAST report sections: content, escaping, empty states.

Self-contained: builds its own tiny scores/status/leaderboard fixtures (the same
columns test_report_new_capabilities.py uses), so it needs no checked-in results.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "python", "build_html_report.py")

SCORE_COLUMNS = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                 "mapped_pred_bp", "unambiguously_mapped_pred_bp", "unmapped_pred_bp",
                 "off_truth_pred_bp", "ambiguously_mapped_pred_bp", "true_plasmid_count",
                 "recovered_plasmid_count", "plasmid_recall", "predicted_record_count",
                 "true_amr_gene_count", "recovered_amr_gene_count", "amr_gene_recall",
                 "true_circular_plasmid_count", "recovered_circular_plasmid_count",
                 "circular_truth_plasmid_recovery", "circular_plasmid_recall", "alignment_total",
                 "alignment_retained", "filtered_alignment_count", "precision", "recall", "f1"]
LEADER_COLUMNS = ["rank", "tool", "n_samples", "n_completed", "n_failed", "n_skipped",
                  "mean_precision", "mean_recall", "mean_f1", "mean_plasmid_recall",
                  "mean_plasmid_recall_ge50", "mean_plasmid_recall_ge90",
                  "n_complete_circular_assessed", "mean_complete_circular_plasmid_recall",
                  "mean_bin_f1", "mean_nmi", "mean_variation_of_information", "mean_pr_auc",
                  "significant_vs_runner_up", "n_zero_plasmid_isolates",
                  "mean_zero_plasmid_specificity", "total_zero_plasmid_chromosome_fp_bp"]


def write_fixtures(d):
    score = {"sample": "s1", "tool": "toolA", "analysis_track": "short_read", "true_plasmid_bp": "10000",
             "TP_bp": "9000", "FP_bp": "100", "FN_bp": "1000", "mapped_pred_bp": "9100",
             "unambiguously_mapped_pred_bp": "9100", "true_plasmid_count": "2",
             "recovered_plasmid_count": "2", "plasmid_recall": "0.900", "predicted_record_count": "2",
             "precision": "0.900", "recall": "0.900", "f1": "0.900"}
    leader = {"rank": "1", "tool": "toolA", "n_samples": "1", "n_completed": "1", "n_failed": "0",
              "n_skipped": "0", "mean_precision": "0.900", "mean_recall": "0.900", "mean_f1": "0.900",
              "mean_plasmid_recall": "0.900", "n_complete_circular_assessed": "0",
              "significant_vs_runner_up": "not_assessed", "n_zero_plasmid_isolates": "0"}
    paths = {name: os.path.join(d, name) for name in ("scores.tsv", "tool_status.tsv", "leaderboard.tsv")}
    with open(paths["scores.tsv"], "w") as fh:
        fh.write("\t".join(SCORE_COLUMNS) + "\n" + "\t".join(score.get(c, "0") for c in SCORE_COLUMNS) + "\n")
    with open(paths["tool_status.tsv"], "w") as fh:
        fh.write("sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\ns1\ttoolA\tcompleted\tpred.fasta\t\t1\t1000\n")
    with open(paths["leaderboard.tsv"], "w") as fh:
        fh.write("\t".join(LEADER_COLUMNS) + "\n" + "\t".join(leader.get(c, "") for c in LEADER_COLUMNS) + "\n")
    return paths


def build(paths, out, *extra):
    result = subprocess.run(
        [sys.executable, BUILD, "--project-root", ROOT, "--scores", paths["scores.tsv"],
         "--tool-status", paths["tool_status.tsv"], "--leaderboard", paths["leaderboard.tsv"],
         "--out", out, *extra], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return open(out, encoding="utf-8").read()


def main():
    with tempfile.TemporaryDirectory() as d:
        paths = write_fixtures(d)
        # Empty states: both sections exist and say why they are empty.
        html = build(paths, os.path.join(d, "empty.html"))
        assert "id='replicon-recovery'" in html and "No recovery-by-replicon table" in html
        assert "id='quast-diagnostics'" in html and "RUN_QUAST_DIAGNOSTICS=0" in html
        assert "id='replicon-recovery'" in html and "id='quast-diagnostics'" in html

        replicon = os.path.join(d, "r.tsv")
        with open(replicon, "w") as fh:
            fh.write("analysis_track\ttool\tfeature_type\tlabel\tn_plasmids\tn_samples\tmean_completeness\t"
                     "recovered_fraction\tunderpowered\n"
                     "short_read\ttoolA\treplicon\tIncFII<x>\t3\t2\t0.8000\t0.6667\ttrue\n")
        quast = os.path.join(d, "q.tsv")
        with open(quast, "w") as fh:
            fh.write("sample\ttool\treference_type\treference_id\tgenome_fraction_pct\tmisassembly_count\t"
                     "duplication_ratio\n"
                     "s1\ttoolA\tchromosome\tchromosome\t10.0\t2\t1.0\n"
                     "s2\ttoolA\tchromosome\tchromosome\t20.0\t3\t1.2\n"
                     "s3\ttoolA\tchromosome\tchromosome\t\t\t\n")                  # blank fields: skipped, not zero
        html = build(paths, os.path.join(d, "full.html"), "--recovery-by-replicon", replicon,
                     "--quast-diagnostics", quast)
        assert "IncFII&lt;x&gt;" in html and "IncFII<x>" not in html            # escaped
        assert "underpowered (small n)" in html
        assert "<td>3</td><td>15.00</td><td>5</td><td>1.10</td>" in html, "QUAST mean/total must skip blanks"
        assert "No recovery-by-replicon table" not in html
    print("ALL REPORT REPLICON/QUAST TESTS PASSED")


if __name__ == "__main__":
    main()
