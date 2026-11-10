#!/usr/bin/env bash
# Stage 6 — aggregate per-sample scores into a per-tool leaderboard (TSV + MD).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need python3

SCORES="$RESULTS_DIR/scores.tsv"
[[ -s "$SCORES" ]] || die "no scores found at $SCORES; run 05_score.sh first"
# Optional structural evidence is accepted only after record, provenance, and
# closure-support validation. Invalid evidence remains on disk for audit but is
# excluded from selection reports.
while IFS= read -r -d '' evidence; do
    pred="${evidence%.evidence.tsv}.plasmid.fasta"
    validation="${evidence%.evidence.tsv}.structural_evidence.validation.json"
    if ! python3 "$HERE/../python/validate_structural_evidence.py" --evidence "$evidence" --pred-fasta "$pred" --out "$validation"; then
        warn "structural evidence rejected: $evidence (selection reports will not use it)"
    fi
done < <(find "$RESULTS_DIR" -type f -name 'pred_*.evidence.tsv' -print0)
# Correlated-sample detection lives in aggregate_results.py, which reads the
# score rows themselves rather than looking for a file beside the sample sheet.
# Reference-database overlap screen: which truth genomes may already be in
# each tool's own database/training data (date-based; see
# python/flag_database_overlap.py). Advisory unless EXCLUDE_DATABASE_OVERLAP=1.
OVERLAP_ARGS=()
DB_REGISTRY="$PROJECT_ROOT/config/tool_database_releases.tsv"
if [[ -s "$DB_REGISTRY" ]]; then
    if python3 "$HERE/../python/flag_database_overlap.py" \
            --sample-sheet "$SAMPLE_SHEET" --registry "$DB_REGISTRY" --scores "$SCORES" \
            --data-dir "$DATA_DIR" --out "$RESULTS_DIR/benchmark.database_overlap.tsv"; then
        OVERLAP_ARGS=(--database-overlap "$RESULTS_DIR/benchmark.database_overlap.tsv")
        [[ "${EXCLUDE_DATABASE_OVERLAP:-0}" == "1" ]] && OVERLAP_ARGS+=(--exclude-database-overlap)
    else
        warn "database-overlap screen failed; leaderboard written without it"
    fi
fi

# Headline design inputs (python/headline_design.py): how each truth was built
# (reference tiers; long-read-first vs short-read-first; same-read polishing)
# and which isolates are clonal. Each is optional; without it the headline
# falls back to the plain pooled design and says so.
DESIGN_ARGS=(--capabilities "$PROJECT_ROOT/config/tool_capabilities.tsv"
             --headline-max-tier "${HEADLINE_MAX_REFERENCE_TIER:-2}"
             --min-species-clusters "${MIN_SPECIES_CLUSTERS:-20}")
if python3 "$HERE/../python/truth_provenance.py" --sample-sheet "$SAMPLE_SHEET" --data-dir "$DATA_DIR" \
        --out "$RESULTS_DIR/benchmark.truth_provenance.tsv"; then
    DESIGN_ARGS+=(--truth-provenance "$RESULTS_DIR/benchmark.truth_provenance.tsv")
else
    warn "truth provenance failed; headline uses every reference tier"
fi
if python3 "$HERE/../python/clonal_groups.py" --sample-sheet "$SAMPLE_SHEET" --data-dir "$DATA_DIR" \
        --max-distance "${CLONAL_MASH_DISTANCE:-0.0005}" --threads "$THREADS" \
        --out "$RESULTS_DIR/benchmark.clonal_groups.tsv"; then
    DESIGN_ARGS+=(--clonal-groups "$RESULTS_DIR/benchmark.clonal_groups.tsv")
else
    warn "clonal grouping failed; clusters use BioProject/study only"
fi

# Every truth replicon's label under the three labelling schemes (python/label_schemes.py;
# stage 2 writes <sample>/label_schemes.tsv). The headline is scored on
# TRUTH_LABEL_SCHEME (ncbi, pre-registered); the others are re-ranked by
# rank_sensitivity.py below.
python3 "$HERE/../python/label_schemes.py" collect --data-dir "$DATA_DIR" \
    --primary "${TRUTH_LABEL_SCHEME:-ncbi}" \
    --out "$RESULTS_DIR/benchmark.label_schemes.tsv" \
    --summary-out "$RESULTS_DIR/benchmark.label_scheme_summary.tsv" \
    || warn "label-scheme collection failed; the report shows no scheme table"

# Contig layer cross-check (python/contig_crosscheck.py compare): the minimap2-based
# contig scores against an independent alignment-free scorer, per sample and tool.
if [[ "${RUN_CONTIG_CROSSCHECK:-1}" == "1" ]]; then
    python3 "$HERE/../python/contig_crosscheck.py" compare --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" \
        --out "$RESULTS_DIR/benchmark.contig_crosscheck.tsv" \
        || warn "contig cross-check failed; the report shows no cross-check table"
fi

# AMR placement by gene class (python/score_amr_placement.py collect): one row per
# tool and gene class (carbapenemase / ESBL / colistin / ... / all).
if [[ "${RUN_AMR_PLACEMENT:-1}" -eq 1 ]]; then
    python3 "$HERE/../python/score_amr_placement.py" collect --results-dir "$RESULTS_DIR" \
        --out "$RESULTS_DIR/benchmark.amr_placement.tsv" \
        || warn "AMR placement collection failed; the report shows no AMR placement table"
fi

# Sequence-level leakage check (python/database_containment.py): is each truth
# plasmid already inside a tool's own database? The installed MOB-suite
# database is found automatically; add others via TOOL_DATABASE_FASTAS
# ("tool1,tool2=/path.fasta;tool3=/other.fasta"). Advisory: never re-ranks.
if [[ "${RUN_DATABASE_CONTAINMENT:-1}" == "1" ]] && command -v minimap2 >/dev/null 2>&1; then
    CONTAINMENT_DBS=()
    # The database of the MOB-suite that actually runs (follows the wrapper; scripts/lib.sh).
    MOB_DB_DIR="$(mobsuite_db_dir)"
    MOB_DB_FASTA="${MOB_DB_DIR:+$MOB_DB_DIR/ncbi_plasmid_full_seqs.fas}"
    [[ -s "$MOB_DB_FASTA" ]] && CONTAINMENT_DBS+=(--database "mob_recon,flye_mob_recon,trycycler_mob_recon,gplas2_mob=$MOB_DB_FASTA")
    IFS=';' read -r -a EXTRA_DBS <<< "${TOOL_DATABASE_FASTAS:-}"
    for spec in "${EXTRA_DBS[@]}"; do
        [[ -n "$spec" ]] && CONTAINMENT_DBS+=(--database "$spec")
    done
    if [[ "${#CONTAINMENT_DBS[@]}" -gt 0 ]]; then
        mapfile -t CONTAINMENT_SAMPLES < <(read_samples "$SAMPLE_SHEET" | cut -f1)
        if python3 "$HERE/../python/database_containment.py" --data-dir "$DATA_DIR" \
                --samples "${CONTAINMENT_SAMPLES[@]}" "${CONTAINMENT_DBS[@]}" \
                --min-coverage "${DATABASE_CONTAINMENT_MIN_COVERAGE:-0.95}" \
                --min-identity "${DATABASE_CONTAINMENT_MIN_IDENTITY:-0.99}" --threads "$THREADS" \
                --out "$RESULTS_DIR/benchmark.database_containment.tsv"; then
            DESIGN_ARGS+=(--database-containment "$RESULTS_DIR/benchmark.database_containment.tsv")
        else
            warn "database containment check failed; recovery is not split by database membership"
        fi
    fi
fi

python3 "$HERE/../python/aggregate_results.py" \
    --scores "$SCORES" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --sample-sheet "$SAMPLE_SHEET" \
    "${OVERLAP_ARGS[@]}" \
    "${DESIGN_ARGS[@]}" \
    --out-prefix "$RESULTS_DIR/benchmark"

# -------- advisory analyses, run as a bounded parallel group --------
# Everything from here to the cohort QC flags is advisory: each step reads the
# score rows, results and data, writes its own benchmark.*.tsv, never alters
# scores.tsv or a rank, and only warns on failure. Nothing below reads another
# step's output before `wait`, so the steps run concurrently, at most
# STAGE6_PARALLEL_JOBS at a time (config/config.sh; 1 restores the serial order).
# They used to run one after another: in the audit, stage 6 wall time was the
# sum of ~35 sequential Python processes (docs/PERFORMANCE_AUDIT.md).
STAGE6_JOBS="${STAGE6_PARALLEL_JOBS:-4}"
advisory_job() {
    job_slot_wait "$STAGE6_JOBS"
    "$@" &
}

# Descriptive recovery-by-replicon/MOB breakdown (python/stratify_recovery.py),
# with CPRR per stratum (size, replicon, MOB, AMR carriage).
job_stratify_recovery() {
    local args=()
    [[ -s "$RESULTS_DIR/benchmark.truth_provenance.tsv" ]] && \
        args=(--truth-provenance "$RESULTS_DIR/benchmark.truth_provenance.tsv")
    python3 "$HERE/../python/stratify_recovery.py" \
        --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" "${args[@]}" \
        --out "$RESULTS_DIR/benchmark.recovery_by_replicon.tsv" \
        || warn "recovery-by-replicon breakdown failed; leaderboard is unaffected"
}

# Truth-label screen (python/audit_truth_labels.py): does each PLASMID/CHROMOSOME
# label agree with replicon/MOB evidence? Never edits truth or scores.
job_audit_truth_labels() {
    python3 "$HERE/../python/audit_truth_labels.py" \
        --data-dir "$DATA_DIR" --out "$RESULTS_DIR/benchmark.truth_label_audit.tsv" \
        || warn "truth-label audit failed; scores are unaffected"
}

# Assembly adequacy (was the short-read assembly good enough to blame a tool?), plasmid
# copy-number concordance, truth repeat content and truth depth anomalies, and tool-vs-tool
# bin agreement (PlasEval-style dissimilarity). A table that cannot be produced is absent
# and the report says "Not run".
job_assembly_adequacy() {
    python3 "$HERE/../python/assembly_adequacy.py" merge --data-dir "$DATA_DIR" --out "$RESULTS_DIR/benchmark.assembly_adequacy.tsv" \
        --min-adequacy "$MIN_ASSEMBLY_ADEQUACY" || warn "assembly-adequacy table failed; the leaderboard is unaffected"
}
job_copy_number() {
    python3 "$HERE/../python/copy_number.py" merge --results-dir "$RESULTS_DIR" --out "$RESULTS_DIR/benchmark.copy_number.tsv" \
        || warn "could not merge copy-number shards; that table is not evaluated"
}
job_repeat_content() {
    python3 "$HERE/../python/repeat_content.py" summary --data-dir "$DATA_DIR" --out "$RESULTS_DIR/benchmark.repeat_content.tsv" \
        || warn "could not merge repeat-content tables; that table is not evaluated"
}
job_truth_depth_anomalies() {
    python3 "$HERE/../python/merge_tables.py" --results-dir "$DATA_DIR" --suffix "truth_depth_anomaly_summary.tsv" \
        --out "$RESULTS_DIR/benchmark.truth_depth_anomalies.tsv" || warn "could not merge truth depth-anomaly tables"
}
job_bin_agreement() {
    python3 "$HERE/../python/bin_agreement.py" matrix --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" \
        --alpha "$DISSIMILARITY_ALPHA" --out "$RESULTS_DIR/benchmark.tool_agreement.tsv" \
        || warn "tool agreement matrix failed; the leaderboard is unaffected"
}

# Further benchmark dimensions (accuracy and missing regions, feature preservation and NGOC,
# bin quality, performance, statistical power, scenarios, and an optional composite with gates
# and weight sensitivity). A table that cannot be produced is simply absent, which the report
# shows as "not evaluated". RUN_DIMENSION_ANALYSES=0 skips all of it. Internally ordered:
# shard merges -> accuracy masking -> performance / power / scenarios (in parallel) -> composite,
# which reads the performance table.
job_dimension_analyses() {
    local DIM="$RESULTS_DIR/benchmark" table pair
    for table in accuracy missing_regions feature_preservation ngoc bin_quality; do
        python3 "$HERE/../python/merge_tables.py" --results-dir "$RESULTS_DIR" --suffix ".${table}.tsv" \
            --out "$DIM.${table}.tsv" || warn "could not merge the ${table} shards; that table is not evaluated"
    done
    # Base-level accuracy is not assessable against truth polished with the benchmark's own reads
    # (the same rule the CPRR identity criterion uses); blank those rates and say why.
    if [[ -s "$DIM.accuracy.tsv" ]]; then
        local MASK_ARGS=()
        [[ -s "$RESULTS_DIR/benchmark.truth_provenance.tsv" ]] && MASK_ARGS=(--truth-provenance "$RESULTS_DIR/benchmark.truth_provenance.tsv")
        python3 "$HERE/../python/mask_accuracy.py" --accuracy "$DIM.accuracy.tsv" "${MASK_ARGS[@]}" \
            || warn "accuracy masking failed; rates are left as computed"
    fi
    python3 "$HERE/../python/performance_summary.py" --tool-status "$RESULTS_DIR/tool_status.tsv" \
        --scores "$SCORES" --logs-dir "$LOG_DIR" --data-dir "$DATA_DIR" --threads "${THREADS:-1}" \
        --out "$DIM.performance.tsv" || warn "performance summary failed; leaderboard is unaffected" &
    python3 "$HERE/../python/power_analysis.py" --scores "$SCORES" --sample-sheet "$SAMPLE_SHEET" \
        --leaderboard "$RESULTS_DIR/benchmark.leaderboard.tsv" --out "$DIM.power.tsv" || warn "power analysis failed; leaderboard is unaffected" &
    python3 "$HERE/../python/scenario_tags.py" --scores "$SCORES" --data-dir "$DATA_DIR" \
        --sample-sheet "$SAMPLE_SHEET" --out "$DIM.scenarios.tsv" \
        --performance-out "$DIM.scenario_performance.tsv" || warn "scenario tags failed; leaderboard is unaffected" &
    wait
    local COMPOSITE_ARGS=()
    for pair in "accuracy:accuracy" "feature-preservation:feature_preservation" "ngoc:ngoc" \
                "bin-quality:bin_quality" "performance:performance"; do
        [[ -s "$DIM.${pair#*:}.tsv" ]] && COMPOSITE_ARGS+=("--${pair%%:*}" "$DIM.${pair#*:}.tsv")
    done
    python3 "$HERE/../python/composite_score.py" --scores "$SCORES" "${COMPOSITE_ARGS[@]}" \
        --out "$DIM.composite.tsv" --sensitivity-out "$DIM.composite_sensitivity.tsv" \
        || warn "composite view failed; leaderboard is unaffected"
}

# How much the ranking depends on scoring choices (python/rank_sensitivity.py):
# re-scores every PAF already on disk with one filter changed at a time, and
# re-ranks under strict F1 and per-plasmid recovery. It writes
# benchmark.rank_robustness.tsv and never alters the leaderboard.
# RUN_RANK_SENSITIVITY=0 skips it.
job_rank_sensitivity() {
    python3 "$HERE/../python/rank_sensitivity.py" \
        --scores "$SCORES" --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" \
        --label-scheme "${TRUTH_LABEL_SCHEME:-ncbi}" \
        --truth-provenance "$RESULTS_DIR/benchmark.truth_provenance.tsv" \
        --out-prefix "$RESULTS_DIR/benchmark" \
        || warn "rank-sensitivity analysis failed; leaderboard is unaffected"
}

# The two longest jobs start first.
[[ "${RUN_RANK_SENSITIVITY:-1}" == "1" ]] && advisory_job job_rank_sensitivity
[[ "${RUN_DIMENSION_ANALYSES:-1}" -eq 1 ]] && advisory_job job_dimension_analyses
advisory_job job_stratify_recovery
advisory_job job_audit_truth_labels
[[ "${RUN_ASSEMBLY_ADEQUACY:-1}" == "1" ]] && advisory_job job_assembly_adequacy
advisory_job job_copy_number
advisory_job job_repeat_content
advisory_job job_truth_depth_anomalies
[[ "${RUN_BIN_AGREEMENT:-1}" == "1" ]] && advisory_job job_bin_agreement
wait

if [[ "${COHORT_QC_FLAGS_ENABLED:-1}" -eq 1 ]]; then
    python3 "$HERE/../python/flag_cohort_outliers.py" \
        --stats-dir "$DATA_DIR" --samples "$SAMPLE_SHEET" \
        --min-cohort-size "$COHORT_QC_MIN_COHORT_SIZE" \
        --zscore-threshold "$COHORT_QC_ZSCORE_THRESHOLD" \
        --out "$RESULTS_DIR/benchmark.cohort_qc_flags.tsv"
fi

python3 "$HERE/../python/validate_recommendations.py" \
    --scores "$SCORES" --samples "$SAMPLE_SHEET" \
    --min-train-samples "$RECOMMENDATION_MIN_SAMPLES" \
    --out "$RESULTS_DIR/benchmark.recommendation_validation.tsv"

# Assembly QC gate over every cohort assembly (python/assembly_qc_gate.py, D13):
# the same check stage 8 applies before recommending, here so its warnings can be
# scored against failed recommendations below.
if [[ "${RUN_ASSEMBLY_QC_GATE:-1}" -eq 1 ]]; then
    python3 "$HERE/../python/assembly_qc_gate.py" --data-dir "$DATA_DIR" \
        --out "$RESULTS_DIR/benchmark.assembly_qc.tsv" 2>> "$LOG_DIR/aggregate.assembly_qc.log" \
        || warn "assembly QC gate found no assemblies; benchmark.assembly_qc.tsv not written"
fi

# Recommender evaluation (python/evaluate_recommender.py; scoring specification
# sections 9-10): leave-one-study-out regret, near-optimal and top-1 rates, gap
# closed against the single best tool, and the oracle-gap verdict. Then every
# existing warning is scored against failed recommendations (evaluate_warnings.py).
# Advisory: a failure warns and never stops the run.
if [[ "${RUN_RECOMMENDER_EVAL:-1}" -eq 1 ]]; then
    if python3 "$HERE/../python/evaluate_recommender.py" --scores "$SCORES" --samples "$SAMPLE_SHEET" \
            --tool-status "$RESULTS_DIR/tool_status.tsv" --out-prefix "$RESULTS_DIR/benchmark" \
            --min-train-samples "$RECOMMENDATION_MIN_SAMPLES"; then
        python3 "$HERE/../python/evaluate_warnings.py" --regret "$RESULTS_DIR/benchmark.recommender_regret.tsv" \
            --cohort-qc-flags "$RESULTS_DIR/benchmark.cohort_qc_flags.tsv" \
            --assembly-qc "$RESULTS_DIR/benchmark.assembly_qc.tsv" --out-prefix "$RESULTS_DIR/benchmark" \
            || warn "warning evaluation failed; the report shows no warning table"
    else
        warn "recommender evaluation failed; the report shows no recommender section"
    fi
    # Leave-one-genus/phylum-out transfer (python/leave_taxon_out.py). split=holdout
    # isolates stay locked here; evaluate them once by hand with
    # "plasbench analysis leave-taxon-out ... --confirm-holdout".
    python3 "$HERE/../python/leave_taxon_out.py" --scores "$SCORES" --samples "$SAMPLE_SHEET"         --tool-status "$RESULTS_DIR/tool_status.tsv" --out-prefix "$RESULTS_DIR/benchmark"         --min-train-samples "$RECOMMENDATION_MIN_SAMPLES"         || warn "leave-taxon-out evaluation failed; the report shows no taxon-transfer table"
fi

# Descriptive decision-support model, off by default (see docs/USER_GUIDE.md).
# Always writes its own JSON verdict, ready or not; select_operational_method.py
# below only appends --recommendation-model when this guard is on, so a
# disabled/not-ready model changes nothing about its output.
RECOMMENDATION_MODEL_ARGS=()
if [[ "${RUN_RECOMMENDATION_MODEL:-0}" -eq 1 ]]; then
    python3 "$HERE/../python/fit_recommendation_model.py" \
        --scores "$SCORES" --sample-sheet "$SAMPLE_SHEET" \
        --data-dir "$DATA_DIR" \
        --min-studies "$RECOMMENDATION_MODEL_MIN_STUDIES" \
        --min-training-samples "$RECOMMENDATION_MODEL_MIN_SAMPLES" \
        --min-relative-improvement "$RECOMMENDATION_MODEL_MIN_IMPROVEMENT" \
        --nested-min-training-samples "$RECOMMENDATION_MODEL_NESTED_MIN_SAMPLES" \
        --nested-min-studies "$RECOMMENDATION_MODEL_NESTED_MIN_STUDIES" \
        --model-card "$RESULTS_DIR/benchmark.recommendation_model.card.md" \
        --out "$RESULTS_DIR/benchmark.recommendation_model.json"
    RECOMMENDATION_MODEL_ARGS=(--recommendation-model "$RESULTS_DIR/benchmark.recommendation_model.json")
fi

# Retain the highest-quality already reconstructed candidate for every truth
# sample. Public operational recommendations are gated by the study holdout
# validation above; this never reruns a tool or fabricates a consensus sequence.
python3 "$HERE/../python/select_operational_method.py" \
    --scores "$SCORES" --sample-sheet "$SAMPLE_SHEET" \
    --results-dir "$RESULTS_DIR" --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --data-dir "$DATA_DIR" \
    --recommendation-validation "$RESULTS_DIR/benchmark.recommendation_validation.tsv" \
    "${RECOMMENDATION_MODEL_ARGS[@]}" \
    --out-prefix "$RESULTS_DIR/benchmark" \
    --min-samples "$RECOMMENDATION_MIN_SAMPLES" \
    --min-coverage "$RECOMMENDATION_MIN_COVERAGE" \
    --analysis-track "$ANALYSIS_TRACK" \
    --decision-profile "${DECISION_PROFILE:-accuracy_first}"

# Preserve a separate, truth-label-safe candidate dataset for future
# selection-model research. This does not change today's recommendations.
python3 "$HERE/../python/build_candidate_quality_dataset.py" \
    --scores "$SCORES" --sample-sheet "$SAMPLE_SHEET" --results-dir "$RESULTS_DIR" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" --out-prefix "$RESULTS_DIR/benchmark"

python3 "$HERE/../python/write_manifest.py" \
    --project-root "$PROJECT_ROOT" --sample-sheet "$SAMPLE_SHEET" \
    --data-dir "$DATA_DIR" --results-dir "$RESULTS_DIR" \
    --out "$RESULTS_DIR/run_manifest.json"

# The interactive cohort dashboard repeats the heatmap and metric tables and adds about 1 MB: embedded only when REPORT_EMBED_DASHBOARD=1.
REPORT_FLAGS=()
if [ "${REPORT_EMBED_DASHBOARD:-0}" = "1" ]; then REPORT_FLAGS+=(--embed-dashboard); fi

python3 "$HERE/../python/build_html_report.py" \
    ${REPORT_FLAGS[@]+"${REPORT_FLAGS[@]}"} \
    --project-root "$PROJECT_ROOT" \
    --data-dir "$DATA_DIR" \
    --scores "$SCORES" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --leaderboard "$RESULTS_DIR/benchmark.leaderboard.tsv" \
    --sample-sheet "$SAMPLE_SHEET" \
    --manifest "$RESULTS_DIR/run_manifest.json" \
    --comparisons "$RESULTS_DIR/benchmark.paired_comparisons.tsv" \
    --score-failures "$RESULTS_DIR/score_failures.tsv" \
    --recommendations "$RESULTS_DIR/benchmark.recommendations.tsv" \
    --recommendation-validation "$RESULTS_DIR/benchmark.recommendation_validation.tsv" \
    --cohort-qc-flags "$RESULTS_DIR/benchmark.cohort_qc_flags.tsv" \
    --recovery-by-replicon "$RESULTS_DIR/benchmark.recovery_by_replicon.tsv" \
    --quast-diagnostics "$RESULTS_DIR/quast_diagnostics.tsv" \
    --rank-robustness "$RESULTS_DIR/benchmark.rank_robustness.tsv" \
    --truth-label-audit "$RESULTS_DIR/benchmark.truth_label_audit.tsv" \
    --stratified "$RESULTS_DIR/benchmark.stratified.tsv" \
    --orthogonal-summary "$RESULTS_DIR/orthogonal_validation.summary.json" \
    --dimensions-prefix "$RESULTS_DIR/benchmark" \
    --label-schemes "$RESULTS_DIR/benchmark.label_schemes.tsv" \
    --label-scheme-summary "$RESULTS_DIR/benchmark.label_scheme_summary.tsv" \
    --truth-provenance "$RESULTS_DIR/benchmark.truth_provenance.tsv" \
    --outcome-states "$RESULTS_DIR/benchmark.outcome_states.tsv" \
    --recommender-eval "$RESULTS_DIR/benchmark.recommender_eval.tsv" \
    --recommender-verdict "$RESULTS_DIR/benchmark.recommender_verdict.json" \
    --warning-eval "$RESULTS_DIR/benchmark.warning_eval.tsv" \
    --leave-taxon-out "$RESULTS_DIR/benchmark.leave_taxon_out.tsv" \
    --amr-placement "$RESULTS_DIR/benchmark.amr_placement.tsv" \
    --contig-crosscheck "$RESULTS_DIR/benchmark.contig_crosscheck.tsv" \
    --out "$RESULTS_DIR/benchmark.report.html"

log "Stage 6 complete."
log "  Per-sample scores : $SCORES"
log "  Tool status       : $RESULTS_DIR/tool_status.tsv"
log "  Leaderboard (TSV) : $RESULTS_DIR/benchmark.leaderboard.tsv"
log "  Leaderboard (MD)  : $RESULTS_DIR/benchmark.leaderboard.md"
log "  Track leaderboard : $RESULTS_DIR/benchmark.<short_read|long_read|hybrid>.leaderboard.tsv"
log "  HTML dashboard    : $RESULTS_DIR/benchmark.report.html"
log "  Run manifest      : $RESULTS_DIR/run_manifest.json"
log "  Recommendations   : $RESULTS_DIR/benchmark.recommendations.tsv"
log "  Stratified metrics: $RESULTS_DIR/benchmark.stratified.tsv"
log "  Recovery by replicon/MOB: $RESULTS_DIR/benchmark.recovery_by_replicon.tsv (descriptive only)"
log "  Truth-label audit : $RESULTS_DIR/benchmark.truth_label_audit.tsv (advisory only)"
log "  Further dimensions: $RESULTS_DIR/benchmark.{accuracy,missing_regions,feature_preservation,ngoc,bin_quality,performance,power,scenarios,scenario_performance,composite,composite_sensitivity}.tsv (advisory only)"
log "  Study holdout test : $RESULTS_DIR/benchmark.recommendation_validation.tsv"
log "  Cohort QC flags   : $RESULTS_DIR/benchmark.cohort_qc_flags.tsv (advisory only)"
log "  Scoring spec      : $RESULTS_DIR/benchmark.{label_schemes,label_scheme_summary,outcome_states,recommender_eval,recommender_regret,warning_eval,leave_taxon_out,amr_placement,assembly_qc}.tsv and benchmark.scoring_spec.md"
if [[ "${RUN_RECOMMENDATION_MODEL:-0}" -eq 1 ]]; then
    log "  Recommendation model: $RESULTS_DIR/benchmark.recommendation_model.json"
    log "  Model card           : $RESULTS_DIR/benchmark.recommendation_model.card.md"
fi
log "  Selected output   : $RESULTS_DIR/<sample>/selected_candidate/"
log "  Candidate dataset : $RESULTS_DIR/benchmark.candidate_{features,labels}.tsv"
