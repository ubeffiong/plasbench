#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Tests never read or write the machine's real database store (~/.plasbench/databases).
PLASBENCH_DB_DIR="$(mktemp -d)"; export PLASBENCH_DB_DIR
# ... and never move or link the machine's real MOB-suite database (scripts/lib.sh).
export PLASBENCH_DB_PRESERVE=0
# Tests never need the real internet: the connection check (plasbench/netcheck.py) assumes it is there. The network tests set their own environment.
export PLASBENCH_ASSUME_ONLINE=1
RUN_LOG="$(mktemp)"
SHARD_FILE="$(mktemp)"
trap 'rm -rf "$PLASBENCH_DB_DIR" "$RUN_LOG" "$SHARD_FILE"' EXIT
# Sharding (CI runs the suite as parallel shards, see CONTRIBUTING.md). PB_SHARDS=n PB_SHARD=i (1..n) runs only the tests test/shard_select.py assigns to shard i,
# balanced by test/shard_weights.tsv; with PB_SHARDS unset every test runs, in this order, exactly as before. PB_LIST=1 only prints the registered test names (one per
# registration, in run order) and runs nothing. Every test must be run through pb_run so that the selection and the listing see it.
PB_SHARDS="${PB_SHARDS:-}"
PB_SHARD="${PB_SHARD:-}"
pb_run() {
    local interpreter="$1" name="$2" started
    if [ "${PB_LIST:-0}" = "1" ]; then echo "$name"; return 0; fi
    if [ -n "$PB_SHARDS" ] && ! grep -qxF "$name" "$SHARD_FILE"; then return 0; fi
    # Some tests (the web UI ones) run `demo` jobs that clear results_demo; the unsharded suite rebuilds it in test_demo_end_to_end.py before the report tests.
    # A shard has no such fixed point, so it rebuilds the demo before a test that reads it whenever the demo is not whole.
    if [ -n "$PB_SHARDS" ] && grep -q results_demo "$HERE/$name" && [ ! -f "$HERE/../results_demo/ecoli_a/visualization/alignment_blocks.json" ]; then
        echo "rebuilding results_demo for $name"
        bash "$HERE/run_demo.sh" > /dev/null
    fi
    started=$SECONDS
    if [ -n "$PB_SHARDS" ]; then
        # A shard runs each test in its own session (a test that signals a process group can only reach its own) under a time limit (PB_TEST_TIMEOUT seconds, default 900),
        # so a hung test fails the job quickly and by name instead of holding the runner for hours.
        local runner=() code=0
        command -v setsid > /dev/null 2>&1 && runner+=(setsid -w)
        command -v timeout > /dev/null 2>&1 && runner+=(timeout -k 30 "${PB_TEST_TIMEOUT:-900}")
        "${runner[@]}" "$interpreter" "$HERE/$name" || code=$?
        if [ "$code" -ne 0 ]; then
            if [ "$code" -eq 124 ] || [ "$code" -eq 137 ]; then echo "TIMEOUT: $name did not finish within ${PB_TEST_TIMEOUT:-900} s (exit $code)"; else echo "FAILED: $name (exit $code)"; fi
            exit "$code"
        fi
    else
        "$interpreter" "$HERE/$name"
    fi
    # Per-test wall time, read back from CI logs to balance test/shard_weights.tsv.
    echo "PB_TIME $name $((SECONDS - started))"
}
# Tests that cannot run here (no node, minimap2, Chrome, git, results_demo) print SKIP and exit 0; a green run must not hide them (audit AU-023).
# The summary below counts them; REQUIRE_NO_SKIPS=1 (set in CI) turns any skip into a failure.
if [ "${PB_LIST:-0}" != "1" ]; then
    exec > >(tee "$RUN_LOG") 2>&1
fi
if [ -n "$PB_SHARDS" ] && [ "${PB_LIST:-0}" != "1" ]; then
    PB_LIST=1 bash "$HERE/run_tests.sh" | python3 "$HERE/shard_select.py" --weights "$HERE/shard_weights.tsv" --shard "${PB_SHARD:?PB_SHARD is required with PB_SHARDS}" --shards "$PB_SHARDS" > "$SHARD_FILE"
    echo "shard $PB_SHARD of $PB_SHARDS: $(wc -l < "$SHARD_FILE" | tr -d ' ') tests"
    # The demo results are the shared fixture of the report tests; the unsharded run builds them mid-suite (test_demo_end_to_end.py), so a shard that reads them builds them first.
    NEEDS_DEMO="$(cd "$HERE" && xargs grep -l results_demo < "$SHARD_FILE" || true)"
    if [ -n "$NEEDS_DEMO" ]; then bash "$HERE/run_demo.sh" > /dev/null; fi
fi
for test in test_scoring.py test_scoring_adversarial.py test_aggregate_failures.py test_selection_undefined_metrics.py test_study_groups.py test_leakage_visibility.py test_classifier_semantics.py test_report_classifier_section.py test_rank_sensitivity.py test_research_design.py test_manifest_selected_candidates.py test_guide_docs.py test_independent_review_ledger.py test_make_truth.py test_bin_matching.py test_merge_bin_metrics.py test_amr_truth.py test_derive_amr_truth.py test_stratify_recovery.py test_report_replicon_quast.py test_recommendation_validation.py test_gplas_classifier_validation.py test_mob_to_gplas_classifier.py test_cohort_validation.py test_aggregate.py test_report_composition.py test_recovery_vocabulary.py test_explorer_view.py test_tool_versions.py test_report_javascript.py test_visual_report.py test_structural_and_annotation.py test_protein_annotation.py test_depth_ladder.py test_container_hygiene.py test_selection.py test_visualization_data.py test_operational_selection.py test_download_estimate.py test_local_inputs.py test_readme_install_paths.py test_cli_project_root.py test_tool_capabilities_registry.py test_evaluation_task.py test_reference_independence.py test_recommender_validation_designs.py test_doc_versions.py test_tool_installer_registry.py test_candidate_quality_dataset.py test_external_benchmark_import.py test_discover_long_read_hint.py test_read_quality_ladder.py test_pr_curve_scoring.py test_scores_validation.py test_merge_pr_metrics.py test_pr_curve_chart.py test_report_tracks.py test_compute_assembly_stats.py test_flag_cohort_outliers.py test_ridge_regression.py test_fit_recommendation_model.py test_select_unknown_sample_model.py test_accession_ledger.py test_curate_cohort_dedup.py test_validate_cohort_ledger.py test_recommendation_model_features.py test_analysis_track_and_read_quality_band.py test_measure_read_quality.py test_per_stratum_loso.py test_decision_profiles.py test_prepare_contribution.py test_zero_plasmid_isolate_scoring.py test_leaderboard_significance.py test_ranking_fairness.py test_redundant_coverage.py test_robustness_diagnostics.py test_bin_nmi.py test_parse_teixeira2025_supplement.py test_resolve_ncbi_accessions.py test_build_hybrid_truth.py test_self_assembled_hybrid_schema.py test_report_new_capabilities.py test_compute_difficulty_features.py test_simulated_cohort_schema.py test_simulate_reads.py test_run_quast_diagnostics.py test_audit_three_class_scoring.py test_compare_scoring_methods.py test_validate_truth_table.py test_classify_operational_plasmid.py test_build_plasmid_reference_set.py test_metagenomics.py test_metagenomics_cli.py test_metagenomic_classification.py test_metagenomic_adversarial.py test_metagenomic_ecosystem.py test_metagenomics_real_cohort.py test_metagenomic_report_dashboard.py test_orthogonal_evidence.py test_stratify_multilabel.py test_audit_truth_labels.py test_scoring_controls.py test_scoring_real_minimap2.py test_report_robustness_audit.py test_script_wiring.py test_alignment_accuracy.py test_feature_preservation.py test_bin_quality.py test_mask_accuracy.py test_performance_summary.py test_power_analysis.py test_scenario_tags.py test_composite_score.py test_compare_runs.py test_demo_end_to_end.py test_collect_truth_provenance.py test_sweep_incremental.py test_plasbench_common.py test_bin_agreement.py test_plasbin_flow_adapter.py test_user_tools_manifest.py test_user_tool_adapter.py test_user_tool_detect.py test_user_tool_source.py test_user_tool_multitask.py test_webui.py test_job_survival.py test_webui_databases.py test_ui_help.py test_ui_cleanup.py test_ut_multi_task_ui.py test_webui_env_allowlist.py test_webui_stall_activity.py test_ui_dialogs.py test_open_folder.py test_run_folders.py test_workspace_tree_ui.py test_study_data_location.py test_folder_chooser.py test_native_picker.py test_picker_diagnostics.py test_picker_ui_browser.py test_ui_cleanup_browser.py test_wizard_data_location_ui.py test_job_persistence.py test_outside_runs.py test_ui_patch.py test_run_status_panel.py test_github_signin.py test_netgate.py test_github_ops.py test_workspace_studies.py test_study_git_data_rules.py test_desktop_window.py test_update_check.py test_updates.py test_window_help_cohorts.py test_console_colours.py test_git_heavy_files.py test_annotation_additions.py test_plaseval_crosscheck.py test_assembly_adequacy.py test_copy_number.py test_repeat_content.py test_annotation_parallel.py test_truth_depth_anomalies.py test_baseline_replicon.py test_local_read_pairing.py test_circular_origin.py test_contig_chimeric.py test_report_learnings.py test_learnings_pipeline.py test_cprr_robustness.py test_matching.py test_resampling_equivalence.py test_score_entry_filters.py test_fetch_ena_parallel.py test_report_fig_binerrors.py test_plaseval_cohort.py test_plaseval_gate.py test_candidate_multiplicity.py test_short_read_qc.py test_assembly_selection.py test_report_reviewers.py test_report_readqc_panel.py test_make_demo_readqc.py test_readqc_panel_js.py test_run_multiqc.py test_external_review_log.py test_implementation_catalogue.py test_publication_cohort_candidates.py test_report_synteny.py test_report_amr_regions.py test_reviewer_matrix.py test_reference_evidence_audit.py test_assembler_sensitivity.py test_ranking_stability.py test_import_contributed_cohort.py test_ui_connection.py test_app_launch.py test_ui_connection_browser.py test_leakage_settings.py test_prereg_admin.py test_intake.py test_intake_ui_browser.py test_resolve_contributed_cohort.py test_selection_report.py test_sheet_limit.py test_tool_default_label.py test_compare_published.py test_publication_cohorts.py test_performance_drivers.py test_plsdb_novelty.py test_discover_plasmid_free.py test_workflow_steps.py test_workflow_ui.py test_stale_server.py test_stale_false_positive.py test_netcheck.py test_network_declared.py test_tool_install_proof.py test_docker_runtime.py test_docker_runtime_e2e.py; do
    pb_run python3 "$test"
done
pb_run bash test_gplas_adapter.sh
pb_run bash test_short_read_qc_stage.sh
pb_run bash test_assembly_selection_stage.sh
pb_run bash test_only_tool_gating.sh
pb_run bash test_failed_tool_exit_code.sh
pb_run bash test_tool_result_fingerprint.sh
pb_run bash test_capability_cache.sh
pb_run bash test_thread_budget.sh
pb_run bash test_plsmd_adapter.sh
pb_run bash test_plsmd_stage.sh
pb_run bash test_plasbin_flow_stage.sh
pb_run bash test_user_tool_stage.sh
pb_run bash test_user_tool_multitask_stage.sh
pb_run bash test_add_tool_e2e.sh
pb_run bash test_download_plsdb.sh
pb_run bash test_operational_reconstruct.sh
pb_run bash test_parallel_execution.sh
pb_run bash test_download_parallel.sh
pb_run bash test_assemble_parallel.sh
pb_run bash test_assemble_crash_safe.sh
pb_run bash test_truth_stage_speed.sh
pb_run bash test_score_parallel.sh
pb_run bash test_score_analysis_track.sh
pb_run bash test_pr_curve_stale_cleanup.sh
pb_run bash test_run_all_default_stages.sh
pb_run bash test_never_silent.sh
pb_run bash test_update_script.sh
pb_run bash test_upgrade_e2e.sh
pb_run bash test_install_latest.sh
pb_run bash test_release_archive.sh
pb_run bash test_bootstrap_conda.sh
pb_run bash test_setup_interactive.sh
pb_run bash test_database_installers.sh
pb_run bash test_plassembler.sh
pb_run bash test_flye_mob_recon_circularity.sh
pb_run bash test_long_read_truth_eligible.sh
pb_run bash test_hybracter.sh
pb_run bash test_hybracter_adapter.sh
pb_run bash test_trycycler_mob_recon.sh
pb_run bash test_genomad_adapter.sh
pb_run bash test_genomad_stage.sh
pb_run bash test_plasme_adapter.sh
pb_run bash test_plasme_stage.sh
pb_run bash test_plasgraph2_adapter.sh
pb_run bash test_plasgraph2_stage.sh
pb_run bash test_rfplasmid_adapter.sh
pb_run bash test_rfplasmid_stage.sh
pb_run bash test_plasmidhunter_adapter.sh
pb_run bash test_plasmidhunter_stage.sh
pb_run bash test_plasmer_adapter.sh
pb_run bash test_plasmer_stage.sh
pb_run bash test_plasmidec_adapter.sh
pb_run bash test_plasmidec_stage.sh
pb_run bash test_plascope_adapter.sh
pb_run bash test_plascope_stage.sh
pb_run bash test_self_assembled_hybrid_download.sh
pb_run bash test_simulated_download_stage.sh
pb_run bash test_build_hybrid_truth_stage.sh
pb_run bash test_difficulty_features_stage.sh
pb_run bash test_cohort_and_write_script.sh
pb_run bash test_stage_wiring_qc_model.sh
pb_run bash test_thread_scaling_sweep.sh
pb_run bash test_quast_diagnostics_stage.sh
pb_run bash test_stage_dimensions.sh
pb_run bash test_stage_contig_metrics.sh
pb_run python3 test_install_wiring.py
# CI shards (PB_SHARD/PB_SHARDS): the shards partition the registered tests exactly; test/shard_weights.tsv covers them all.
pb_run python3 test_shard_selection.py
pb_run bash test_install_all_optional.sh
# Tools install automatically, pinned and isolated, with consent (python/source_install.py): hermetic installs with fake conda/pip and a local upstream repository.
pb_run bash test_source_install.sh
# Docker in the tools setup: state detection, per-platform plans, winget / Homebrew argument lists, exit codes 0/20/21/1 with fake programs (no real Docker is installed or started).
pb_run python3 test_docker_setup.py
pb_run bash test_docker_install.sh
pb_run python3 test_tool_install_registry.py
pb_run python3 test_exit20_wrappers.py
pb_run python3 test_materialize_bmock12_truth.py
# Question-bank gaps (calibration, baselines, interpretation limits, metadata completeness).
pb_run python3 test_question_bank_gaps.py
pb_run python3 test_metric_rubric.py
# Panel alignment and scoring specification (docs/PANEL_ALIGNMENT.md).
for test in test_label_schemes.py test_dimer_collapse.py test_mcc_abstention.py test_prereg_freeze.py test_bin_outcomes.py test_contig_scoring.py test_recommender_eval.py test_panel_operational.py test_wilcoxon.py test_leave_taxon_out.py test_rank_axes_new.py test_amr_placement.py test_amr_placement_by_task.py test_reference_independence.py test_report_scoring_spec.py test_contig_crosscheck.py test_fetch_ena_reads.py test_report_svg.py test_report_maps.py test_plasmid_viewer.py test_report_3d.py test_report_scorecard.py test_report_workflow.py test_report_surfaces.py test_report_wiring.py test_report_condense.py test_report_layout.py test_report_pdf.py test_report_feature_manifest.py test_report_merge.py test_report_isolates.py test_report_names.py test_lazy_frames.py test_recommendation_task.py test_report_prune.py test_report_help.py test_sample_report.py test_refresh_sample_report.py test_reference_images.py test_scenario_definition.py test_report_results_dir.py test_report_collapse.py test_report_fig_ladder.py test_report_fig_landscape.py test_report_fig_heatmap.py test_report_fig_stats.py test_report_fig_pr.py test_report_fig_fingerprint.py test_report_fig_synteny.py test_report_info.py test_demo_dataset_views.py test_recommender_truth_free.py test_primary_eligibility.py test_truth_evidence_record.py test_permutation_reporting.py test_simulate_validation.py test_truth_audits.py test_metric_registry.py test_metric_wiring.py test_burden_columns.py test_sv_prr.py test_dataset_features.py test_recommender_arms.py test_report_fig_radar.py test_promote_amr_truth.py test_database_provenance.py test_tool_validation_tiers.py test_integration_audit.py test_evaluation_tasks.py test_registry_tasks.py test_dominant_fallback.py test_docs_consistency.py test_real_tool_checks.py test_report_fig_complexity.py test_report_compare_table.py test_recommend_evidence.py test_map_rings.py test_reference_groups.py test_bin_unaligned.py test_run_consistency.py test_independent_truth_only.py test_discover_negative_controls.py test_stratified_bootstrap_t.py test_study_manage.py test_threshold_freeze.py test_amr_unbinned.py test_bin_clustering_missed.py test_truth_provenance_tokens.py test_audit_web_fixes.py test_input_validation.py test_audit_report_fixes.py test_job_stall_and_group.py test_performance_per_run_threads.py test_helper_timeouts_and_atomic_tables.py test_guard_boundaries.py test_interval_bounds.py test_amr_gene_recovery_definition.py test_bin_no_bins_undefined.py test_shared_readers.py test_guard_mutants.py test_truth_exclusion_sensitivity.py test_popen_pipeline_timeouts.py test_download_checksum_registry.py test_window_git_show_and_rank_help.py test_job_retrying_state.py test_truth_exclusion_reconstruction.py test_score_bins_paf_guards.py test_sheet_check.py test_download_progress.py test_cli_help_all.py test_estimate_ena_sizes.py test_run_status.py test_report_file_tree_links.py test_report_fig_facets.py test_report_fig_presence.py test_report_fig_visuals_js.py test_report_fig_visuals_build.py test_isolate_scan.py test_isolate_scan_ui.py test_ui_markdown.py test_report_inputs.py test_regenerate_visuals.py test_manifest_sheet_without_sample_id.py test_install_outcomes.py test_computer_info.py test_setting_ranges.py test_assembler_diagnosis.py test_preflight_resources.py test_annotation_cache.py; do
    pb_run python3 "$test"
done
pb_run bash test_outcome_states.sh
pb_run bash test_preserve_downloads.sh
pb_run bash test_mobsuite_env.sh
pb_run bash test_isolated_tool_envs.sh
pb_run bash test_platon_db_download.sh
pb_run bash test_resumable_download.sh
pb_run bash test_preserve_databases.sh
# Audit P0 fixes (see audit/): inline-handler injection, zero-plasmid bin scoring, sleep/Resume, silent stage failures and orphans.
pb_run python3 test_webui_inline_handlers.py
# The window loads from caches (loadcache.py): counted spawns/file reads on the load path, invalidation, gzip, and the Tools filter render (node).
pb_run python3 test_window_load.py
pb_run python3 test_zero_plasmid_bin_scoring.py
pb_run python3 test_job_sleep_resume.py
pb_run bash test_stage_failure_visibility.sh
pb_run bash test_stage3_failure_diagnosis.sh
pb_run bash test_download_gate_and_prefetch.sh
pb_run bash test_require_internet.sh
pb_run bash test_run_events_and_heartbeat.sh
for t in test_run_isolation_lock.sh test_stage4_outcomes.sh test_adapter_no_output.sh test_stage8_fresh_prediction.sh test_score_failure_reason.sh test_stage4_preflight_and_fasta.sh test_run_lock_race.sh test_run_lock_heartbeat.sh test_tool_timeout_preset.sh test_disk_guard.sh; do pb_run bash "$t"; done
if [ "${PB_LIST:-0}" = "1" ]; then exit 0; fi
sleep 1
# Count lines that START with a skip notice ("SKIP:", "SKIPPED:", "  skip  "), not every line that contains the word: passing checks such as "PASS: SKIP set: ..." mention it too.
SKIPPED="$(grep -c -E '^[[:space:]]*(SKIP|SKIPPED|skip)([: ]|$)' "$RUN_LOG" || true)"
echo "SKIPPED CHECKS: $SKIPPED (each is a test that did not run in this environment; see the SKIP lines above)"
if [ "${REQUIRE_NO_SKIPS:-0}" = "1" ] && [ "$SKIPPED" != "0" ]; then echo "REQUIRE_NO_SKIPS=1 and $SKIPPED check(s) were skipped"; exit 1; fi
echo "ALL PLASBENCH TESTS PASSED"
