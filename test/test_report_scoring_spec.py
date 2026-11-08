#!/usr/bin/env python3
"""HTML sections for the scoring specification (python/report_scoring_spec.py):
each section appears with its values when its input exists, and with an explicit
"Not run" note (never silently absent) when it does not. Also checks that
build_html_report.py accepts every new argument and calls the module."""
import json
import re
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_scoring_spec as rss  # noqa: E402

PAGE = "<nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section>"


def write(path, header, rows):
    path.write_text("\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")


def section(page, sid):
    match = re.search(r"<section id='%s'>(.*?)</section>" % sid, page, re.S)
    assert match, f"section {sid} missing"
    return match.group(1)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write(tmp / "lb.tsv", ["analysis_track", "task", "tool", "mean_f1", "micro_f1", "mean_mcc", "mean_f2", "mean_f0_5",
                               "mean_abstention_rate", "total_outcome_perfect", "total_outcome_fragmented",
                               "total_outcome_merged", "total_outcome_fragmented_and_merged", "total_outcome_partial",
                               "total_outcome_missed", "mean_bin_ari", "mean_contig_f1_bp", "mean_contig_mcc_bp",
                               "mean_contig_bin_f1_bp"],
              [["short_read", "reconstruction", "toolA", "0.9000", "0.8800", "0.8700", "0.9100", "0.8900", "0.0000",
                7, 2, 1, 0, 1, 1, "0.6500", "0.8100", "0.7700", "0.6600"]])
        (tmp / "manifest.json").write_text(json.dumps({"preregistration": {
            "sha256": "ab" * 32, "locked": True, "matches": True, "frozen_at": "2026-11-08T00:00:00+00:00",
            "parameters": 33, "to_fix": ["tool_timeout_seconds"], "env_mismatches": [
                {"parameter": "perfect_threshold", "config_variable": "PERFECT_THRESHOLD", "planned": "0.95",
                 "actual": "0.90"}]}}))
        write(tmp / "summary.tsv", ["scheme", "role", "samples", "replicons", "plasmids", "plasmid_bp", "excluded_replicons",
                                    "plasmids_differing_from_primary", "scored_file"],
              [["ncbi", "primary", 2, 6, 3, 150000, 0, 0, "truth.tsv"],
               ["nonchromosomal", "sensitivity", 2, 6, 4, 1150000, 0, 1, "truth.nonchromosomal.tsv"]])
        write(tmp / "schemes.tsv", ["sample", "sequence_id", "length", "ncbi_label", "nonchromosomal_label",
                                    "evidence_label", "evidence_reason", "multimer", "schemes_agree", "ncbi_label_field"],
              [["S1", "chromid1", 1000000, "CHROMOSOME", "PLASMID", "AMBIGUOUS", "chromid-like", "no", "no",
                "assigned_molecule_location_type"]])
        write(tmp / "prov.tsv", ["sample", "reference_tier", "truth_quality_grade"], [["S1", "1", "B"], ["S2", "3", "C"]])
        (tmp / "data" / "S1").mkdir(parents=True)
        write(tmp / "data" / "S1" / "truth.corrections.tsv", ["sequence_id", "original_length", "corrected_length",
                                                              "identity", "half_coverage", "method", "multimer", "action"],
              [["pX", 8000, 4000, "0.9900", "1.0000", "minimap2", "yes", "collapsed"]])
        write(tmp / "states.tsv", ["analysis_track", "tool", "n_runs", "completed", "reused", "failed_tool",
                                   "failed_resource", "infrastructure_failure", "not_applicable", "retried"],
              [["short_read", "toolA", 10, 7, 0, 1, 1, 1, 0, 2]])
        write(tmp / "eval.tsv", ["profile", "metric", "n_isolates", "n_folds", "n_tools", "mean_regret", "p95_regret",
                                 "near_optimal_rate", "top1_rate", "mean_kendall_tau", "single_best_mean_regret",
                                 "oracle_mean_score", "single_best_mean_score", "recommender_mean_score", "oracle_gap",
                                 "gap_closed", "floor_flagged", "floor_true_best_below_floor", "verdict", "note"],
              [["f1", "f1", 12, 3, 4, "0.0300", "0.1200", "0.8333", "0.7500", "0.6667", "0.0900", "0.9", "0.81",
                "0.87", "0.0900", "0.6667", 1, "1.0000", "recommender_adds_value", "x"]])
        (tmp / "verdict.json").write_text(json.dumps({"verdict": "recommender_adds_value", "note": "closes part of the gap"}))
        write(tmp / "warn.tsv", ["warning", "n_evaluated", "n_fired", "n_failed", "n_fired_and_failed", "firing_rate", "ppv",
                                 "sensitivity", "n_could_not_be_applied", "status", "note"],
              [["cohort_outlier:n50", 10, 2, 3, 1, "0.2000", "0.5000", "0.3333", 0, "assessed", ""]])
        write(tmp / "lto.tsv", ["level", "held_out_group", "n_isolates", "n_training_isolates", "mean_regret",
                                "single_best_mean_regret", "near_optimal_rate", "gap_closed", "status", "note"],
              [["genus", "Klebsiella", 4, 8, "0.0500", "0.1000", "0.7500", "0.5000", "assessed", ""]])
        write(tmp / "pc.tsv", ["tool_a", "tool_b", "paired_samples", "mean_f1_difference", "permutation_p_value_holm",
                               "wilcoxon_p_value", "wilcoxon_p_value_holm", "equivalent", "smallest_difference",
                               "analysis_track", "task"],
              [["toolA", "toolB", 12, "0.0100", "0.400000", "0.380000", "0.380000", "yes", "0.05", "short_read",
                "reconstruction"]])
        write(tmp / "amr.tsv", ["tool", "gene_class", "n_gene_copies", "n_recovered", "n_correct_plasmid",
                                "n_wrong_plasmid", "n_shared_contig", "n_unassigned_contig", "correct_plasmid_rate",
                                "replicon_type_correct_rate", "n_samples"],
              [["toolA", "carbapenemase", 3, 3, 2, 1, 0, 0, "0.6667", "1.0000", 2]])
        write(tmp / "status.tsv", ["sample", "tool", "status", "prediction_fasta", "reason"],
              [["S1", "toolA", "skipped", "", "assembly graph unavailable"], ["S2", "toolA", "completed", "x", ""]])
        write(tmp / "scores.tsv", ["sample", "tool", "contigs_ambiguous_bp", "contigs_unplaced_bp"],
              [["S1", "toolA", 1500, 1200]])
        sources = {"leaderboard": tmp / "lb.tsv", "manifest": tmp / "manifest.json", "scores": tmp / "scores.tsv",
                   "comparisons": tmp / "pc.tsv", "tool_status": tmp / "status.tsv", "data_dir": tmp / "data", "label_schemes": tmp / "schemes.tsv",
                   "label_scheme_summary": tmp / "summary.tsv", "truth_provenance": tmp / "prov.tsv",
                   "outcome_states": tmp / "states.tsv", "recommender_eval": tmp / "eval.tsv",
                   "recommender_verdict": tmp / "verdict.json", "warning_eval": tmp / "warn.tsv",
                   "leave_taxon_out": tmp / "lto.tsv", "amr_placement": tmp / "amr.tsv"}
        page = rss.inject(PAGE, sources)
        checks = {"prereg": ["abababab", "frozen and unchanged", "tool_timeout_seconds", "PERFECT_THRESHOLD=0.90"],
                  "scoring-additions": ["0.8700", "0.9100", "0.8900", "0.8800"],
                  "plasmid-outcomes": [">7<", ">2<", "0.6500"],
                  "label-schemes": ["nonchromosomal", "chromid1", "chromid-like", "B 1, C 1", "collapsed", "8000"],
                  "contig-layer": ["0.8100", "0.6600", "1,500 bp", "1,200 bp"],
                  "outcome-states": ["Infrastructure failure", ">10<", ">2<", "assembly graph unavailable"],
                  "recommender-eval": ["0.8333", "0.6667", "recommender_adds_value", "cohort_outlier:n50", "0.3333"],
                  "taxon-transfer": ["Klebsiella", "0.380000", ">yes<"],
                  "amr-placement": ["carbapenemase", "0.6667"],
                  "validity": ["partially validated", "3 fold(s)"]}
        for sid, needles in checks.items():
            body = section(page, sid)
            for needle in needles:
                assert needle in body, f"{sid}: '{needle}' not in section"
            assert "Not run" not in body or sid == "contig-layer", f"{sid} unexpectedly not run"
        assert page.count("<a href='#") == len(rss.SECTIONS) + 1
        print(f"  PASS: all {len(checks)} sections render their values, with nav links")

        empty = rss.inject(PAGE, {})
        for sid in checks:
            if sid in ("validity",):
                continue
            assert "Not run" in section(empty, sid) or "not recorded" in section(empty, sid), sid
        print("  PASS: with no inputs every section states what did not run, none disappears")
        md = rss.markdown(sources)
        assert "recommender_adds_value" in md and "| nonchromosomal |" in md and "| toolA | 10 |" in md
        print("  PASS: Markdown summary carries the verdict, the scheme table and the outcome states")

    source = (ROOT / "python" / "build_html_report.py").read_text(encoding="utf-8")
    for flag in ("--label-schemes", "--label-scheme-summary", "--truth-provenance", "--outcome-states",
                 "--recommender-eval", "--recommender-verdict", "--warning-eval", "--leave-taxon-out",
                 "--amr-placement"):
        assert flag in source, flag
        assert flag in (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8"), f"06 does not pass {flag}"
    assert "report_scoring_spec.inject" in source
    print("  PASS: build_html_report.py takes every argument and 06_aggregate.sh passes each one")
    print("ALL SCORING-SPEC REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
