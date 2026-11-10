#!/usr/bin/env python3
"""
report_surfaces.py -- the registry of every pipeline output and its place in the report.

Every file the pipeline writes (per sample, per tool, aggregate) and every column group of scores.tsv and of the
leaderboard has one entry in SURFACES:

  pattern          file path relative to the results (or data) directory, with {sample} {tool} {track} {any} placeholders,
                   or "<file>::<group>" for a column group
  level            per_sample | per_tool | aggregate | column
  label            a plain-language name of the output group
  producer         the script that writes it
  section          the id of the report section that shows it (None when no section does)
  status           shown | partly | not_surfaced
  reason           why: what the report shows of it, or why it is not shown
  planned_section  not_surfaced only: the section id the report build is meant to give it
  expected         True when every complete run writes it (scan() reports it under missing_expected when absent)

`partly` means the content reaches the report only in summary (merged into a table, drawn in the sequence view, or listed in
the Artifact explorer) and the file itself is not tabulated. `not_surfaced` means the report neither shows nor summarises it.

  classify_file(relative_path)                       -> registry entry or None
  scan(results_dir, data_dir)                        -> {registered, unregistered, missing_expected}
  unregistered_columns(header, groups)               -> columns of `header` that belong to no group
  inventory_section(results_dir, data_dir, known_section_ids)  -> the "Data in this report" appendix (id data-inventory)
  inject(page, results_dir, data_dir)                -> the page with the appendix before Recommendations

Standard library only.
"""
import os
import re

import report_common as rc

SECTION_ID = "data-inventory"
NAV = [(SECTION_ID, "Data in this report")]
STATUSES = ("shown", "partly", "not_surfaced")
STATUS_LABEL = {"shown": "● Shown", "partly": "◐ Partly shown", "not_surfaced": "○ Not shown yet"}


# ------------------------------------------------------------------------------------------------ column groups
def _groups(**kw):
    return {name.replace("__", " ").replace("_and_", " and "): cols for name, cols in kw.items()}


SCORE_COLUMN_GROUPS = {
    "Identity": ["sample", "tool", "analysis_track"],
    "Core": ["true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "precision", "recall", "f1", "predicted_record_count"],
    "Recovery": [
        "true_plasmid_count", "recovered_plasmid_count", "plasmid_recall",
        "true_amr_gene_count", "recovered_amr_gene_count", "amr_gene_recall",
        "true_circular_plasmid_count", "recovered_circular_plasmid_count", "circular_truth_plasmid_recovery", "circular_plasmid_recall",
        "recovered_complete_circular_plasmid_count", "complete_circular_plasmid_recall",
        "scorable_plasmid_bp", "recall_ceiling", "ceiling_adjusted_recall"],
    "Graded recovery": [
        "recovered_plasmid_count_ge50", "plasmid_recall_ge50", "recovered_plasmid_count_ge90", "plasmid_recall_ge90",
        "outcome_perfect", "outcome_fragmented", "outcome_merged", "outcome_fragmented_and_merged", "outcome_partial", "outcome_missed",
        "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity", "cprr_sweep_correct", "cprr_sweep_correct_without_identity"],
    "Confusion and abstention": [
        "TN_bp", "mcc", "f2", "f0_5", "abstention_rate", "isolate_specificity", "chromosome_fp_bp", "fp_predicted_record_count",
        "strict_precision", "redundant_pred_bp"],
    "Bins": [
        "bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events",
        "contaminated_bins", "chromosome_aligned_bp", "repeat_ambiguity_bp", "bin_total_mapped_bp", "contamination_fraction",
        "nmi", "variation_of_information", "perfect_reference_recovery", "strict_reference_reconstruction",
        "lw_bin_precision", "lw_bin_recall", "lw_bin_f1", "bin_ari", "lw_bin_recall_assembly_aware", "lw_bin_f1_assembly_aware"],
    "Contig layer": [
        "contig_min_length", "contigs_evaluable", "contigs_short", "contigs_ambiguous", "contigs_unplaced", "contigs_chimeric",
        "contigs_chimeric_bp", "contig_tp", "contig_fp", "contig_fn", "contig_tn", "contig_precision_count", "contig_recall_count",
        "contig_f1_count", "contig_mcc_count", "contig_tp_bp", "contig_fp_bp", "contig_fn_bp", "contig_tn_bp", "contig_precision_bp",
        "contig_recall_bp", "contig_f1_bp", "contig_mcc_bp", "contig_classification_status", "contigs_ambiguous_bp",
        "contigs_unplaced_bp", "contig_bin_precision_bp", "contig_bin_recall_bp", "contig_bin_f1_bp"],
    "Agreement": [
        "bestmatch_status", "bestmatch_precision_count", "bestmatch_recall_count", "bestmatch_f1_count", "bestmatch_precision_bp",
        "bestmatch_recall_bp", "bestmatch_f1_bp", "bestmatch_contigs_excluded", "dissim_status", "bin_dissimilarity",
        "dissim_split_cost", "dissim_join_cost", "dissim_extra_cost", "dissim_missing_cost", "dissim_norm", "dissim_repeats_dropped"],
    "Calibration": ["pr_auc", "pr_n_thresholds", "brier_score", "expected_calibration_error", "calibration_records"],
    "Diagnostics": [
        "mapped_pred_bp", "unambiguously_mapped_pred_bp", "unmapped_pred_bp", "off_truth_pred_bp", "ambiguously_mapped_pred_bp",
        "alignment_total", "alignment_retained", "filtered_alignment_count"],
}

LEADERBOARD_COLUMN_GROUPS = {
    "Rank and basis": [
        "rank", "analysis_track", "task", "tool", "is_baseline", "beats_best_baseline", "ranking_metric", "ranking_score",
        "ranking_ci_low", "ranking_ci_high", "ranking_basis", "ranking_species_basis", "n_headline_species", "n_ranking_clusters",
        "significant_vs_runner_up", "n_independent_clusters", "n_ranking_samples"],
    "Run counts": [
        "n_samples", "n_completed", "n_failed", "n_skipped", "n_failed_resource", "n_failed_tool", "n_infrastructure_failure",
        "n_not_applicable", "n_f1_scored", "n_failures_scored_zero"],
    "Base-level accuracy": [
        "mean_precision", "mean_recall", "mean_f1", "median_f1", "mean_f1_all_scored", "f1_ci_low", "f1_ci_high", "micro_precision",
        "micro_recall", "micro_f1", "mean_mcc", "mean_f2", "mean_f0_5", "mean_abstention_rate", "mean_strict_precision",
        "total_redundant_pred_bp", "mean_recall_ceiling", "mean_ceiling_adjusted_recall"],
    "Plasmid recovery": [
        "mean_plasmid_recall", "mean_plasmid_recall_ge50", "mean_plasmid_recall_ge90", "n_complete_circular_assessed",
        "mean_complete_circular_plasmid_recall", "n_reference_perfect_assessed", "reference_perfect_recovery_rate",
        "n_strict_reconstruction_assessed", "strict_reference_reconstruction_rate", "cprr", "cprr_ci_low", "cprr_ci_high",
        "cprr_correct", "cprr_plasmids", "cprr_isolate_mean", "cprr_isolates", "cprr_auc", "total_outcome_perfect", "total_outcome_fragmented", "total_outcome_merged",
        "total_outcome_fragmented_and_merged", "total_outcome_partial", "total_outcome_missed"],
    "Bins": ["n_bin_scored", "mean_bin_f1", "mean_nmi", "mean_variation_of_information", "mean_lw_bin_f1", "mean_bin_ari",
             "mean_lw_bin_f1_assembly_aware"],
    "Contig layer": ["mean_contig_f1_count", "mean_contig_mcc_count", "mean_contig_f1_bp", "mean_contig_mcc_bp", "mean_contig_bin_f1_bp"],
    "Calibration": ["n_pr_scored", "mean_pr_auc", "mean_brier_score", "mean_expected_calibration_error", "n_calibrated"],
    "Database leakage": [
        "n_possible_db_overlap", "n_after_database", "mean_f1_after_database", "n_unknown_overlap", "n_plasmids_in_tool_database",
        "mean_recovery_in_tool_database", "mean_recovery_not_in_tool_database"],
    "Zero-plasmid isolates": ["n_zero_plasmid_isolates", "mean_zero_plasmid_specificity", "total_zero_plasmid_chromosome_fp_bp"],
}


# ------------------------------------------------------------------------------------------------ registry
def _entry(pattern, level, label, producer, section, status, reason, planned=None, expected=False):
    return {"pattern": pattern, "level": level, "label": label, "producer": producer, "section": section, "status": status,
            "reason": reason, "planned_section": planned, "expected": expected}


def _file_entries():
    S = _entry
    ps, pt, ag = "per_sample", "per_tool", "aggregate"
    NS = "not_surfaced"
    explorer = " It is listed in the Artifact explorer only."
    rows = [
        # ---- per sample: truth side (02_truth.sh) -----------------------------------------------------------------
        S("{sample}/truth.tsv", ps, "Truth table (molecule labels)", "make_truth.py / build_hybrid_truth.py", "samples", "shown",
          "Sample drill-down and every score are computed from it; label audit summarises it."),
        S("{sample}/truth.scored.tsv", ps, "Truth after evidence labelling (ambiguous removed)", "label_truth_evidence.py", "label-schemes", "partly",
          "Counted in the labelling-scheme comparison; rows are not listed."),
        S("{sample}/truth.nonchromosomal.tsv", ps, "Truth, non-chromosomal labelling scheme", "label_schemes.py", "label-schemes", "partly",
          "Counted in the labelling-scheme comparison; rows are not listed."),
        S("{sample}/truth.corrections.tsv", ps, "Dimer and multimer corrections to the truth", "detect_dimers.py", "label-schemes", "shown",
          "Every correction is listed with the dimers section."),
        S("{sample}/truth_labels.tsv", ps, "Evidence label per truth replicon", "label_truth_evidence.py", "truth-label-audit", "partly",
          "Evidence-label counts are summarised; the per-replicon rows are not."),
        S("{sample}/label_schemes.tsv", ps, "Label under each labelling scheme", "label_schemes.py", "label-schemes", "shown",
          "Merged into the labelling-scheme table."),
        S("{sample}/truth_provenance.json", ps, "Truth provenance (how the truth was built)", "build_hybrid_truth.py", "headline-design", "partly",
          "Summarised as the truth-provenance tier in the headline design."),
        S("{sample}/truth_features.tsv", ps, "Annotated features of the reference", "annotate_reference.py", "replicon-recovery", "partly",
          "Replicon and relaxase labels feed recovery by plasmid type; features are not tabulated."),
        S("{sample}/truth_proteins.tsv", ps, "Truth proteins", "annotate_proteins.py", "feature-preservation", "partly",
          "Used as the reference for feature preservation; proteins are not listed."),
        S("{sample}/truth_proteins.provenance.json", ps, "Truth protein annotation provenance", "annotate_proteins.py", None, "partly",
          "Recorded for reproducibility." + explorer),
        S("{sample}/annotation_provenance.json", ps, "Annotation database versions", "annotate_reference.py", "replicon-recovery", "partly",
          "Database versions are not repeated in the report." + explorer),
        S("{sample}/truth_amr.tsv", ps, "Curated truth AMR genes", "validate_amr_truth.py", "amr-placement", "partly",
          "Gene counts and placement appear; the curated list is not shown."),
        S("{sample}/truth_amr.draft.tsv", ps, "Auto-derived AMR truth draft", "derive_amr_truth.py", None, "partly",
          "A draft for curation, never scored." + explorer),
        S("{sample}/truth_amr.scored.tsv", ps, "AMR truth restricted to scored plasmids", "05_score.sh", None, "partly",
          "Intermediate of the scorer." + explorer),
        S("{sample}/truth_circular.tsv", ps, "Truth circular plasmids", "make_truth.py", "scores", "partly",
          "Appears as circular-truth recovery in the score table."),
        S("{sample}/truth_circular.scored.tsv", ps, "Circular truth restricted to scored plasmids", "05_score.sh", None, "partly",
          "Intermediate of the scorer." + explorer),
        S("{sample}/truth_repeat_regions.tsv", ps, "Repeat regions of the truth", "repeat_content.py", "plasmid-maps", "shown",
          "Drawn as the repeat track of the circular plasmid maps."),
        S("{sample}/truth_repeat_content.tsv", ps, "Repeat content of the truth", "repeat_content.py", "learn-truthqc", "shown",
          "Merged into the repeat-content table."),
        S("{sample}/truth_depth.tsv", ps, "Read depth of the truth", "02_truth.sh", None, "partly",
          "Input of the depth-window step." + explorer),
        S("{sample}/truth_depth_windows.tsv", ps, "Read-depth windows along the truth", "truth_depth_anomalies.py", "learn-truthqc", "shown",
          "Drawn as a depth strip per sample with the anomalous regions marked."),
        S("{sample}/truth_depth_anomalies.tsv", ps, "Depth-anomaly regions on the truth", "truth_depth_anomalies.py", "learn-truthqc", "shown",
          "The regions are marked on the depth strip; the per-replicon summary is tabulated."),
        S("{sample}/truth_depth_anomaly_summary.tsv", ps, "Depth-anomaly summary per replicon", "truth_depth_anomalies.py", "learn-truthqc", "shown",
          "Merged into the depth-anomaly table."),
        S("{sample}/truth_long_read_depth.tsv", ps, "Long-read depth of truth replicons", "02_truth.sh", "learn-copynumber", "partly",
          "Gives the truth copy number; the depths are not listed."),
        S("{sample}/truth_long_reads.paf", ps, "Long reads mapped to the truth", "02_truth.sh", None, "partly", "Intermediate." + explorer),
        S("{sample}/truth_plasmid_windows.paf", ps, "Window alignments on truth plasmids", "02_truth.sh", None, "partly", "Intermediate." + explorer),
        S("{sample}/truth_reads.bam", ps, "Reads mapped to the truth", "02_truth.sh", None, "partly", "Intermediate." + explorer),
        S("{sample}/truth_reads.bam.bai", ps, "Index of the truth read mapping", "02_truth.sh", None, "partly", "Intermediate." + explorer),
        S("{sample}/truth_scorable.tsv", ps, "Which truth bases the assembly can reach", "scorable_truth.py", "learn-adequacy", "partly",
          "Gives the recall ceiling; the table is not listed."),
        S("{sample}/truth_scorable.provenance.json", ps, "Scorable-truth provenance", "scorable_truth.py", None, "partly", "Provenance." + explorer),
        S("{sample}/sequence_report.jsonl", ps, "NCBI sequence report", "01_download.sh", None, "partly",
          "Source of truth molecule types." + explorer),
        S("{sample}/assembly_data_report.jsonl", ps, "NCBI assembly data report", "01_download.sh", None, "partly",
          "Source of truth metadata." + explorer),
        S("{sample}/simulation_provenance.json", ps, "Read simulation provenance", "simulate_reads.py", None, "partly",
          "Present only for simulated reads." + explorer),
        S("{sample}/reference.fna", ps, "Truth plasmid sequences", "01_download.sh", "samples", "partly", "Drawn in the sequence view."),
        S("{sample}/reference.full.fna", ps, "Complete reference genome", "01_download.sh", "samples", "partly", "Used by the sequence view and scoring."),
        # ---- per sample: assembly side (03_assemble.sh) ---------------------------------------------------------------
        S("{sample}/contigs.fasta", ps, "Short-read assembly", "03_assemble.sh", "samples", "partly", "Contigs appear in the sequence and bin views."),
        S("{sample}/assembly.fasta", ps, "Long-read or hybrid assembly", "07_long_read_reconstruct.sh", None, "partly", "Input of long-read tools." + explorer),
        S("{sample}/contigs_vs_ref.paf", ps, "Contigs mapped to the reference", "05_score.sh", "contig-layer", "partly", "Gives contig labels; alignments are not listed."),
        S("{sample}/contig_labels.tsv", ps, "Truth label of each contig", "contig_classification.py", "contig-layer", "shown",
          "The contig layer scores against it; excluded contigs are counted."),
        S("{sample}/contig_labels.kmer.tsv", ps, "Contig labels by k-mer (independent scorer)", "contig_crosscheck.py", "contig-layer", "shown",
          "Compared with the alignment labels in the cross-check."),
        S("{sample}/plasmid_assembly_coverage.tsv", ps, "How much of each truth plasmid the assembly contains", "assembly_adequacy.py", "learn-adequacy", "partly",
          "Summarised as assembly adequacy; the per-plasmid coverage is not listed."),
        S("{sample}/assembly_stats.tsv", ps, "Assembly statistics (N50, contigs, GC)", "compute_assembly_stats.py", "assembly-quality", "shown",
          "Size, contigs, N50 and GC of each assembly are tabulated."),
        S("{sample}/assembly_qc.tsv", ps, "Assembly quality gate", "assembly_qc_gate.py", "assembly-quality", "shown",
          "The pass or fail of each assembly and its reasons are tabulated."),
        S("{sample}/observed_depth.tsv", ps, "Observed read depth", "measure_depth.py", "isolate-difficulty", "partly", "Gives the depth stratum; not listed."),
        S("{sample}/observed_read_quality.tsv", ps, "Observed read quality", "measure_read_quality.py", "isolate-difficulty", "partly", "Gives the quality stratum; not listed."),
        S("{sample}/plasmid_similarity.tsv", ps, "Similarity between truth plasmids", "compute_difficulty_features.py", "isolate-difficulty", "partly",
          "Summarised as a difficulty signal."),
        S("{sample}/difficulty_features.tsv", ps, "Isolate difficulty features", "compute_difficulty_features.py", "isolate-difficulty", "shown",
          "Listed per isolate."),
        S("{sample}/fastp.json", ps, "Read trimming report", "03_assemble.sh", None, "partly", "Trimming log." + explorer),
        S("{sample}/fastp.html", ps, "Read trimming report (HTML)", "03_assemble.sh", None, "partly", "Trimming log." + explorer),
        S("{sample}/selection_report.json", ps, "Operational selection report", "select_unknown_sample.py", "selected", "shown",
          "Each card translates it into a decision."),
        S("{sample}/selected_candidate/{any}", ps, "Selected candidate sequence", "select_unknown_sample.py", "selected", "shown",
          "Download link on the selection card."),
        S("{sample}/structural_events.tsv", ps, "Structural events versus the truth", "call_structural_variants.py", "samples", "partly",
          "Counts appear in the drill-down; the events are listed there per tool."),
        S("{sample}/structural_summary.tsv", ps, "Structural summary", "call_structural_variants.py", "samples", "shown", "Shown in the drill-down."),
        S("{sample}/visualization/alignment_blocks.json", ps, "Alignment blocks for the sequence view", "build_visualization_data.py", "samples", "shown", "Drawn."),
        S("{sample}/visualization/structural_calls.json", ps, "Structural calls for the sequence view", "call_structural_variants.py", "samples", "shown", "Drawn."),
        S("{sample}/visualization/structural_metrics.tsv", ps, "Structural metrics for the sequence view", "build_visualization_data.py", "samples", "partly",
          "Drawn as marks, not listed."),
        S("{sample}/{sample2}.mob_classifier.tsv", ps, "MOB classifier table (gplas2 seed)", "mob_to_gplas_classifier.py", None, "partly", "Intermediate." + explorer),
        S("{sample}/{sample2}.mob_classifier.provenance.json", ps, "MOB classifier provenance", "mob_to_gplas_classifier.py", None, "partly", "Provenance." + explorer),
        # ---- per tool ---------------------------------------------------------------------------------------------------
        S("{sample}/pred_{tool}.plasmid.fasta", pt, "Standardised plasmid prediction", "04_run_tools.sh", "samples", "partly",
          "Compared against the truth in the sequence view; sequences are not tabulated."),
        S("{sample}/pred_{tool}.bins.tsv", pt, "Predicted bins (contig to bin)", "04_run_tools.sh", "bin-diagnostics", "partly", "Scored as bin metrics; membership shown in the bin view."),
        S("{sample}/pred_{tool}.candidates.fasta", pt, "Scored candidate sequences", "04_run_tools.sh", "baselines-calibration", "partly", "Source of the PR curve."),
        S("{sample}/pred_{tool}.scores.tsv", pt, "Per-record probability", "04_run_tools.sh", "baselines-calibration", "partly", "Gives PR-AUC and calibration."),
        S("{sample}/pred_{tool}.evidence.tsv", pt, "Structural evidence supplied by the tool", "04_run_tools.sh", "orthogonal-evidence", "partly", "Validated, summarised."),
        S("{sample}/pred_{tool}.structural_evidence.validation.json", pt, "Validation of the supplied structural evidence", "validate_structural_evidence.py", "orthogonal-evidence", "partly", "Summarised."),
        S("{sample}/{tool}.pred_vs_ref.paf", pt, "Prediction mapped to the reference", "05_score.sh", "samples", "partly", "Drawn as alignment blocks."),
        S("{sample}/{tool}.pred_vs_ref.all.paf", pt, "All prediction alignments, unfiltered", "05_score.sh", "rank-robustness", "partly", "Re-scored for ranking robustness."),
        S("{sample}/{tool}.candidates_vs_ref.paf", pt, "Candidates mapped to the reference", "05_score.sh", "baselines-calibration", "partly", "Source of the PR curve."),
        S("{sample}/{tool}.per_plasmid.tsv", pt, "Result for each truth plasmid", "score_plasmids.py", "per-plasmid-detail", "shown",
          "One row per truth plasmid and tool, with filters."),
        S("{sample}/{tool}.plasmid_outcomes.tsv", pt, "Outcome class of each truth plasmid", "score_bins.py", "per-plasmid-detail", "shown",
          "The outcome class of each truth plasmid is a column of the per-plasmid table."),
        S("{sample}/{tool}.bin_matches.tsv", pt, "Bin to plasmid matches", "score_bins.py", "bin-diagnostics", "shown", "Drawn as the bin flow."),
        S("{sample}/{tool}.bin_summary.tsv", pt, "Bin summary", "score_bins.py", "bin-diagnostics", "partly", "Counts appear in the bin diagnostics."),
        S("{sample}/{tool}.cprr.tsv", pt, "Correct plasmid reconstruction per plasmid", "score_bins.py", "bin-diagnostics", "partly", "Rate and counts shown; per-plasmid rows are not."),
        S("{sample}/{tool}.amr_placement.tsv", pt, "AMR gene placement", "score_amr_placement.py", "amr-placement", "shown", "Every gene copy is a marker on that tool's ring in the 3D ring tower, with a detail panel and CSV export."),
        S("{sample}/{tool}.copy_number.tsv", pt, "Copy number per matched bin", "copy_number.py", "learn-copynumber", "partly", "Merged into the copy-number table."),
        S("{sample}/{tool}.bestmatch.tsv", pt, "Best-match precision and recall", "bin_agreement.py", "learn-agreement", "partly", "Merged into scores and summarised."),
        S("{sample}/{tool}.dissim.tsv", pt, "Bin dissimilarity", "bin_agreement.py", "learn-agreement", "partly", "Merged into scores and summarised."),
        S("{sample}/{tool}.plaseval.{any}", pt, "PlasEval export files", "bin_agreement.py", None, "partly", "For the external PlasEval tool." + explorer),
        S("{sample}/{tool}.contig_classification.tsv", pt, "Contig-level classification", "contig_classification.py", "contig-layer", "partly", "Scored; contigs are not listed."),
        S("{sample}/{tool}.pr_curve.tsv", pt, "Precision-recall curve", "score_plasmids.py", "samples", "shown", "Drawn in the drill-down."),
        S("{sample}/{tool}.pr_summary.tsv", pt, "Precision-recall summary", "score_plasmids.py", "baselines-calibration", "partly", "PR-AUC is merged into scores."),
        S("{sample}/{tool}.calibration.tsv", pt, "Calibration bins", "score_plasmids.py", "baselines-calibration", "shown", "Pooled into the calibration view."),
        S("{sample}/{tool}.accuracy.tsv", pt, "Nucleotide accuracy", "alignment_accuracy.py", "accuracy-dimension", "partly", "Merged into benchmark.accuracy."),
        S("{sample}/{tool}.missing_regions.tsv", pt, "Truth regions the tool missed", "alignment_accuracy.py", "accuracy-dimension", "partly", "Merged into benchmark.missing_regions."),
        S("{sample}/{tool}.feature_preservation.tsv", pt, "Feature preservation", "feature_preservation.py", "feature-preservation", "partly", "Merged into benchmark.feature_preservation."),
        S("{sample}/{tool}.ngoc.tsv", pt, "Gene order conservation", "feature_preservation.py", "feature-preservation", "partly", "Merged into benchmark.ngoc."),
        S("{sample}/{tool}.bin_quality.tsv", pt, "Bin quality tier", "bin_quality.py", "bin-quality", "partly", "Merged into benchmark.bin_quality."),
        S("{sample}/{tool}.quast_diagnostics.tsv", pt, "QUAST diagnostics", "run_quast_diagnostics.py", "quast-diagnostics", "partly", "Merged into quast_diagnostics."),
        S("{sample}/{tool}.proteins.tsv", pt, "Predicted proteins", "annotate_proteins.py", "feature-preservation", "partly", "Compared with the truth proteins."),
        S("{sample}/{tool}.proteins.provenance.json", pt, "Predicted protein provenance", "annotate_proteins.py", None, "partly", "Provenance." + explorer),
        S("{sample}/{tool}.replicon_hits.tsv", pt, "Replicon marker hits (baseline)", "04_run_tools.sh", None, "partly", "Input of the replicon baseline." + explorer),
        # ---- run-level files -------------------------------------------------------------------------------------------------
        S("scores.tsv", ag, "Scores, one row per sample and tool", "score_plasmids.py", "scores", "shown", "Table with filters and download.", expected=True),
        S("score_failures.tsv", ag, "Runs that could not be scored", "05_score.sh", "outcome-states", "shown", "Listed with the reason.", expected=False),
        S("tool_status.tsv", ag, "How each run ended", "04_run_tools.sh", "outcome-states", "shown", "Every run's status and reason.", expected=True),
        S("tool_outcomes.tsv", ag, "Outcome of each tool run", "aggregate_results.py", "outcome-states", "partly", "Folded into outcome states."),
        S("assembly_status.tsv", ag, "How each assembly ended", "03_assemble.sh", "health", "partly", "Failures are counted in the health summary."),
        S("download_status.tsv", ag, "How each download ended", "01_download.sh", "health", "partly", "Failures are counted in the health summary."),
        S("quast_diagnostics.tsv", ag, "QUAST diagnostics, merged", "run_quast_diagnostics.py", "quast-diagnostics", "shown", "Table."),
        S("run_manifest.json", ag, "Run manifest (versions, settings)", "write_manifest.py", "method", "shown", "Method and reproducibility section.", expected=True),
        S("orthogonal_validation.summary.json", ag, "Orthogonal-evidence summary", "validate_orthogonal_evidence.py", "orthogonal-evidence", "shown", "Summarised."),
        S("samples.tsv", ag, "Sample sheet", "curate_cohort.py", "samples", "shown", "Sample metadata drives the strata and the drill-down.", expected=True),
        S("selected_candidates/{any}", ag, "Selected candidate downloads", "select_unknown_sample.py", "selected", "shown", "Linked from the selection cards."),
        S("benchmark.report.html", ag, "This report", "build_html_report.py", None, "shown", "The report itself."),
        S("benchmark.manifest.json", ag, "Benchmark manifest", "write_manifest.py", "method", "partly", "Settings appear in the method section."),
        S("{any}.log", ag, "Run logs", "scripts/*.sh", None, "partly", "Kept for debugging." + explorer),
        # ---- benchmark.* tables ----------------------------------------------------------------------------------------------
        S("benchmark.leaderboard.tsv", ag, "Leaderboard", "aggregate_results.py", "leaderboard", "shown", "Ranked table.", expected=True),
        S("benchmark.leaderboard.md", ag, "Leaderboard as Markdown", "aggregate_results.py", "files", "shown",
          "Linked from the Run files panel."),
        S("benchmark.{track}.leaderboard.tsv", ag, "Per-track leaderboard", "aggregate_results.py", "leaderboard", "shown", "One table per track."),
        S("benchmark.{track}.leaderboard.md", ag, "Per-track leaderboard as Markdown", "aggregate_results.py", "files", "shown",
          "Linked from the Run files panel."),
        S("benchmark.headline_design.tsv", ag, "Headline design (units of analysis)", "headline_design.py", "headline-design", "shown", "Table."),
        S("benchmark.metadata_completeness.tsv", ag, "Metadata completeness", "aggregate_results.py", "metadata-completeness", "shown", "Table."),
        S("benchmark.outcome_states.tsv", ag, "Run outcome states", "aggregate_results.py", "outcome-states", "shown", "Table."),
        S("benchmark.paired_comparisons.tsv", ag, "Paired tool comparisons", "aggregate_results.py", "statistics", "shown", "Table."),
        S("benchmark.reference_tiers.tsv", ag, "Reference tiers", "aggregate_results.py", "headline-design", "partly", "Tier counts are shown."),
        S("benchmark.species.tsv", ag, "Species of the cohort", "aggregate_results.py", "headline-design", "partly", "Species counts are shown."),
        S("benchmark.rank_robustness.tsv", ag, "Rank robustness", "rank_sensitivity.py", "rank-robustness", "shown", "Table."),
        S("benchmark.cprr_threshold_sweep.tsv", ag, "CPRR threshold sweep", "aggregate_results.py", "leaderboard", "partly",
          "Only the area under the sweep (cprr_auc) is shown, in the leaderboard; the per-threshold table is a downloadable file."),
        S("benchmark.recovery_by_replicon.tsv", ag, "Recovery by replicon type", "stratify_recovery.py", "replicon-recovery", "shown", "Table."),
        S("benchmark.truth_label_audit.tsv", ag, "Truth-label audit", "audit_truth_labels.py", "truth-label-audit", "shown", "Table."),
        S("benchmark.truth_provenance.tsv", ag, "Truth provenance", "truth_provenance.py", "headline-design", "shown", "Tier shown with the design."),
        S("benchmark.stratified.tsv", ag, "Performance by stratum", "select_operational_method.py", "stratified", "shown", "Table."),
        S("benchmark.recommendations.tsv", ag, "Recommendations", "select_operational_method.py", "recommendations", "shown", "Table."),
        S("benchmark.recommendation_validation.tsv", ag, "Recommendation validation", "validate_recommendations.py", "validation", "shown", "Table."),
        S("benchmark.recommendation_model.json", ag, "Recommendation model", "fit_recommendation_model.py", "recommendations", "partly", "Described by its model card."),
        S("benchmark.recommendation_model.card.md", ag, "Recommendation model card", "fit_recommendation_model.py", "recommendations", "partly", "Quoted in the recommendations."),
        S("benchmark.cohort_qc_flags.tsv", ag, "Cohort QC flags", "flag_cohort_outliers.py", "cohort-qc", "shown", "Table."),
        S("benchmark.clonal_groups.tsv", ag, "Clonal groups of isolates", "clonal_groups.py", "cohort-qc", "shown",
          "The groups and their members are listed under the cohort QC flags."),
        S("benchmark.database_overlap.tsv", ag, "Truth plasmids present in tool databases", "flag_database_overlap.py", "database-membership", "shown", "Table."),
        S("benchmark.database_containment.tsv", ag, "Recovery inside and outside tool databases", "database_containment.py", "database-membership", "shown", "Table."),
        S("benchmark.label_schemes.tsv", ag, "Labelling schemes, merged", "label_schemes.py", "label-schemes", "shown", "Table."),
        S("benchmark.label_scheme_summary.tsv", ag, "Labelling scheme summary", "label_schemes.py", "label-schemes", "shown", "Table."),
        S("benchmark.contig_crosscheck.tsv", ag, "Contig cross-check", "contig_crosscheck.py", "contig-layer", "shown", "Marker on each 3D bar, per-tool rows in the detail panel (CSV export), full table collapsed under the view."),
        S("benchmark.amr_placement.tsv", ag, "AMR placement", "score_amr_placement.py", "amr-placement", "shown", "Per-tool correct-plasmid rate bars beside the 3D ring tower; table collapsed under the view."),
        S("benchmark.assembly_adequacy.tsv", ag, "Assembly adequacy", "assembly_adequacy.py", "learn-adequacy", "shown", "Table."),
        S("benchmark.assembly_qc.tsv", ag, "Assembly quality gate, all samples", "assembly_qc_gate.py", "assembly-quality", "shown",
          "The gate result of every sample is tabulated."),
        S("benchmark.copy_number.tsv", ag, "Copy number", "copy_number.py", "learn-copynumber", "shown", "Table."),
        S("benchmark.repeat_content.tsv", ag, "Repeat content of the truth", "repeat_content.py", "learn-truthqc", "shown", "Table."),
        S("benchmark.truth_depth_anomalies.tsv", ag, "Depth anomalies of the truth", "truth_depth_anomalies.py", "learn-truthqc", "shown", "Table."),
        S("benchmark.tool_agreement.tsv", ag, "Tool-versus-tool dissimilarity", "bin_agreement.py", "learn-agreement", "shown", "Matrix."),
        S("benchmark.recommender_eval.tsv", ag, "Recommender evaluation", "evaluate_recommender.py", "recommender-eval", "shown", "Profile selector and summary beside the 3D strategy scene; table in a detail tab."),
        S("benchmark.recommender_verdict.json", ag, "Recommender verdict", "evaluate_recommender.py", "recommender-eval", "shown", "Verdict text."),
        S("benchmark.recommender_regret.tsv", ag, "Recommender regret per isolate", "evaluate_recommender.py", "recommender-eval", "shown",
          "Each isolate is a column of bars in the 3D strategy scene (recommender, single best, oracle) with regret gaps; rows in the detail panel."),
        S("benchmark.warning_eval.tsv", ag, "Evaluation of the warnings", "evaluate_warnings.py", "recommender-eval", "shown", "Tab in the recommender detail panel (CSV export), table collapsed under the view."),
        S("benchmark.warnings.tsv", ag, "Warnings issued per isolate", "evaluate_warnings.py", "recommender-eval", "partly", "Counted in the warning evaluation."),
        S("benchmark.leave_taxon_out.tsv", ag, "Leave-taxon-out transfer", "leave_taxon_out.py", "taxon-transfer", "shown", "Table."),
        S("benchmark.accuracy.tsv", ag, "Nucleotide accuracy", "alignment_accuracy.py", "accuracy-dimension", "shown", "Table."),
        S("benchmark.missing_regions.tsv", ag, "Missing regions", "alignment_accuracy.py", "accuracy-dimension", "shown", "Table."),
        S("benchmark.feature_preservation.tsv", ag, "Feature preservation", "feature_preservation.py", "feature-preservation", "shown", "Table."),
        S("benchmark.ngoc.tsv", ag, "Gene order conservation", "feature_preservation.py", "feature-preservation", "shown", "Table."),
        S("benchmark.bin_quality.tsv", ag, "Bin quality tiers", "bin_quality.py", "bin-quality", "shown", "Table."),
        S("benchmark.performance.tsv", ag, "Computational performance", "performance_summary.py", "performance", "shown", "Table."),
        S("benchmark.power.tsv", ag, "Statistical power", "power_analysis.py", "power", "shown", "Table."),
        S("benchmark.scenarios.tsv", ag, "Scenario tags", "scenario_tags.py", "scenarios", "partly", "Used to group the scenario table."),
        S("benchmark.scenario_performance.tsv", ag, "Performance by scenario", "scenario_tags.py", "scenarios", "shown", "Table."),
        S("benchmark.composite.tsv", ag, "Five-dimension composite", "composite_score.py", "composite", "shown", "Table."),
        S("benchmark.composite_sensitivity.tsv", ag, "Composite weight sensitivity", "composite_score.py", "composite", "shown", "Table."),
        S("benchmark.reproducibility_tools.tsv", ag, "Reproducibility across runs", "compare_runs.py", "reproducibility", "shown", "Table."),
        S("benchmark.accuracy.masked.tsv", ag, "Accuracy with low-confidence truth masked", "mask_accuracy.py", "accuracy-dimension", "partly", "Quoted beside the accuracy table."),
        S("benchmark.scoring_spec.md", ag, "Scoring specification (text)", "report_scoring_spec.py", "files", "shown",
          "Linked from the Run files panel."),
    ]
    return rows


def _column_entries():
    S = _entry
    scores = {
        "Identity": ("shown", "scores", "Sample, tool and track label every row."),
        "Core": ("shown", "scores", "Base counts, precision, recall and F1 are columns of the score table."),
        "Recovery": ("partly", "scores", "Recall, AMR and circular recovery are shown; the counts behind them are in the download only."),
        "Graded recovery": ("partly", "graded-tiers", "Mean recall at 50 and 90 percent and the outcome totals are shown; per-row counts are not."),
        "Confusion and abstention": ("partly", "scoring-additions", "MCC, F2, F0.5 and abstention are shown as means; per-row values are in the download."),
        "Bins": ("partly", "bin-diagnostics", "Bin F1, splits and merges are shown; the other bin columns are in the download."),
        "Contig layer": ("partly", "contig-layer", "Contig F1 and MCC are shown; the contig counts are in the download."),
        "Agreement": ("partly", "learn-agreement", "Best-match F1 and dissimilarity are shown as means; the cost components are in the download."),
        "Calibration": ("partly", "baselines-calibration", "PR-AUC, Brier score and calibration error are shown for tools that give probabilities."),
        "Diagnostics": ("partly", "scores", "Unmapped and ambiguous predicted bases are shown; alignment counts are in the download."),
    }
    board = {
        "Rank and basis": ("shown", "leaderboard", "Rank, basis and significance are columns of the leaderboard."),
        "Run counts": ("partly", "leaderboard", "Completed and failed runs are shown; the failure sub-counts are in the download."),
        "Base-level accuracy": ("shown", "leaderboard", "Mean and interval columns of the leaderboard."),
        "Plasmid recovery": ("shown", "leaderboard", "Recall, circular and perfect recovery and CPRR are in the leaderboard and graded-tiers views."),
        "Bins": ("partly", "bin-diagnostics", "Mean bin F1 and clustering agreement are shown; the counts are in the download."),
        "Contig layer": ("shown", "contig-layer", "Compared with the reference layer."),
        "Calibration": ("partly", "baselines-calibration", "Shown for tools that give probabilities."),
        "Database leakage": ("shown", "database-membership", "Recovery inside and outside the tool database."),
        "Zero-plasmid isolates": ("shown", "zero-plasmid", "The negative-control section."),
    }
    out = []
    for name in SCORE_COLUMN_GROUPS:
        status, section, reason = scores[name]
        status, section = "shown", "scores"
        reason = reason.rstrip(".") + "; every column is in the column-group table under All scores."
        out.append(S(f"scores.tsv::{name}", "column", f"scores.tsv columns: {name}", "score_plasmids.py and the merge scripts",
                     section, status, reason))
    for name in LEADERBOARD_COLUMN_GROUPS:
        status, section, reason = board[name]
        reason = reason.rstrip(".") + "; every column is under More columns of the leaderboard."
        status = "shown"
        out.append(S(f"benchmark.leaderboard.tsv::{name}", "column", f"Leaderboard columns: {name}", "aggregate_results.py",
                     section, status, reason))
    return out


SURFACES = _file_entries() + _column_entries()


# ------------------------------------------------------------------------------------------------ matching
_TOKENS = {"{sample}": "[^/]+", "{sample2}": "[^/]+", "{tool}": "[^/.]+", "{track}": "[a-z_]+", "{any}": ".+"}


def _regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern[i] == "{":
            end = pattern.index("}", i)
            out += _TOKENS[pattern[i:end + 1]]
            i = end + 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


_COMPILED = [(e, _regex(e["pattern"])) for e in SURFACES if "::" not in e["pattern"]]
# Specific before generic: a pattern with fewer wildcards wins, then the longer literal text.
_COMPILED.sort(key=lambda pair: (pair[0]["pattern"].count("{"), -len(pair[0]["pattern"])))


def classify_file(relative_path):
    """The registry entry for a path relative to the results (or data) directory, or None."""
    path = str(relative_path).replace("\\", "/").lstrip("./")
    for entry, regex in _COMPILED:
        if regex.match(path):
            return entry
    return None


def _walk(directory):
    if not directory or not os.path.isdir(directory):
        return []
    found = []
    for root, _, files in os.walk(directory):
        for name in files:
            found.append(os.path.relpath(os.path.join(root, name), directory).replace(os.sep, "/"))
    return sorted(found)


def scan(results_dir, data_dir=None):
    """Classify every file under results_dir (and data_dir when different).

    registered        [{pattern, count, paths}] one per registry entry with at least one file
    unregistered      files no entry matches (a new output nobody registered)
    missing_expected  patterns of `expected` entries with no file (a run that did not finish, or a stale registry)
    """
    paths = _walk(results_dir)
    if data_dir and os.path.abspath(data_dir) != os.path.abspath(results_dir or ""):
        paths += [p for p in _walk(data_dir) if p not in set(paths)]
    hits, unregistered = {}, []
    for rel in paths:
        entry = classify_file(rel)
        if entry is None:
            unregistered.append(rel)
        else:
            hits.setdefault(entry["pattern"], []).append(rel)
    registered = [{"pattern": e["pattern"], "count": len(hits[e["pattern"]]), "paths": hits[e["pattern"]]}
                  for e in SURFACES if e["pattern"] in hits]
    missing = [e["pattern"] for e in SURFACES if e["expected"] and e["pattern"] not in hits]
    return {"registered": registered, "unregistered": unregistered, "missing_expected": missing}


def unregistered_columns(header, groups):
    """Columns of `header` that belong to no group of `groups` (a name -> [columns] mapping)."""
    known = {c for cols in groups.values() for c in cols}
    return [c for c in header if c not in known]


def _read_header(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.readline().rstrip("\n").split("\t")


# ------------------------------------------------------------------------------------------------ inventory
def _present(entry, counts, headers):
    """(present: bool, text) for one registry entry in this run."""
    if entry["level"] == "column":
        fname, group = entry["pattern"].split("::")
        header = headers.get(fname)
        groups = SCORE_COLUMN_GROUPS if fname == "scores.tsv" else LEADERBOARD_COLUMN_GROUPS
        if header is None:
            return False, "not in this run"
        n = sum(1 for c in groups[group] if c in header)
        return (n > 0), (f"{n} of {len(groups[group])} columns" if n else "not in this run")
    n = counts.get(entry["pattern"], 0)
    return (n > 0), (f"{n} file" + ("" if n == 1 else "s") if n else "not in this run")


def inventory_section(results_dir, data_dir=None, known_section_ids=()):
    known = set(known_section_ids or ())
    result = scan(results_dir, data_dir)
    counts = {r["pattern"]: r["count"] for r in result["registered"]}
    headers = {"scores.tsv": _read_header(os.path.join(results_dir, "scores.tsv")) if results_dir else None,
               "benchmark.leaderboard.tsv": _read_header(os.path.join(results_dir, "benchmark.leaderboard.tsv")) if results_dir else None}
    rows = []
    for e in SURFACES:
        present, text = _present(e, counts, headers)
        present_cell = rc.Raw(f"<span class='di-present'>{rc.esc(text)}</span>" if present
                              else f"<span class='rpt-missing'>{rc.esc(text)}</span>")
        target = e["section"] if e["section"] in known and e["status"] != "not_surfaced" else None
        if target:
            where = rc.Raw(f"<a href='#{rc.esc(target)}'>{rc.esc(target)}</a>")
        elif e["status"] == "not_surfaced":
            where = rc.Raw(f"<span class='rpt-missing'>planned: {rc.esc(e['planned_section'])}</span>")
        else:
            where = rc.missing("no section shows it", "none")
        reason = e["reason"]
        if e["status"] == "not_surfaced":
            reason = "Not shown yet: " + reason
        rows.append([rc.Raw(f"<code>{rc.esc(e['pattern'])}</code> {rc.esc(e['label'])}"), e["level"].replace("_", " "), present_cell,
                     e["producer"], STATUS_LABEL[e["status"]], where, reason])
    n_not = sum(1 for e in SURFACES if e["status"] == "not_surfaced")
    n_partly = sum(1 for e in SURFACES if e["status"] == "partly")
    lead = (f"Every output the pipeline writes, and where this report shows it. <strong>{len(SURFACES) - n_not - n_partly}</strong> "
            f"groups are shown, <strong>{n_partly}</strong> only in summary and <strong>{n_not}</strong> not yet. "
            "A group marked <em>not in this run</em> was not written this time (the step was off, skipped or failed).")
    body = str(rc.panel(["Output group", "Level", "In this run", "Written by", "Status", "Shown in", "Why"], rows, sortable=True))
    extra = ""
    if result["unregistered"]:
        items = "".join(f"<li><code>{rc.esc(p)}</code></li>" for p in result["unregistered"][:50])
        extra = (f"<div class='insight caution'><p><strong>{len(result['unregistered'])} files in this run are not in the registry</strong> "
                 f"(a newer output than this report knows):</p><ul>{items}</ul></div>")
    if result["missing_expected"]:
        extra += ("<div class='insight caution'><p><strong>Expected but absent:</strong> "
                  + ", ".join(f"<code>{rc.esc(p)}</code>" for p in result["missing_expected"]) + ".</p></div>")
    return rc.section(SECTION_ID, "Appendix: Data in this report", lead, body + extra)


_FILE_ITEM = re.compile(r"(<li class='file'><a href='([^']*)' download>[^<]*</a><span>[^<]*</span>)(</li>)")
FILE_STYLE = ("<style id='rpt-filedesc-style'>.file-tree .file .file-desc{display:block;margin:1px 0 4px 0;color:#4a5a50;font:12px Arial,sans-serif}"
              ".file-tree .file .file-desc a{font-weight:600}</style>")


def describe_files(page, known_section_ids=None):
    """Put a description under every file of the Artifact explorer: what the file is, which step wrote it and which section shows it.

    This replaces the separate "Data in this report" table (176 rows listing the same files again): the explorer is the one file list, and the registry
    that table was built from now describes each file where it is listed. A file the registry does not know keeps its name and size only.
    """
    import report_aliases
    ids = (set(re.findall(r"<section id='([^']+)'", page)) | set(report_aliases.LEGACY_IDS)) if known_section_ids is None else set(known_section_ids)

    def one(m):
        from urllib.parse import unquote
        entry = classify_file(unquote(m.group(2)))
        if not entry:
            return m.group(0)
        section = entry.get("section")
        where = (f" · shown in <a href='#{rc.esc(section)}'>{rc.esc(section.replace('-', ' '))}</a>" if section and section in ids
                 else " · listed here only" if entry.get("status") in ("not_surfaced", "partly") else "")
        return (m.group(1) + f"<span class='file-desc'>{rc.esc(entry['label'])} (written by {rc.esc(entry['producer'])}){where}</span>" + m.group(3))
    out = _FILE_ITEM.sub(one, page)
    if out != page and "id='rpt-filedesc-style'" not in out and "</head>" in out:
        h = out.index("</head>")
        out = out[:h] + FILE_STYLE + out[h:]
    return out


def inject(page, results_dir, data_dir=None, known_section_ids=None):
    """Describe the files of the Artifact explorer. The separate "Data in this report" appendix section is no longer added (inventory_section still builds it)."""
    return describe_files(page, known_section_ids)
