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

python3 "$HERE/../python/aggregate_results.py" \
    --scores "$SCORES" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --sample-sheet "$SAMPLE_SHEET" \
    "${OVERLAP_ARGS[@]}" \
    "${DESIGN_ARGS[@]}" \
    --out-prefix "$RESULTS_DIR/benchmark"

# Descriptive recovery-by-replicon/MOB breakdown (python/stratify_recovery.py).
# Never ranks tools and never alters the leaderboard; a failure only warns.
if ! python3 "$HERE/../python/stratify_recovery.py" \
        --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" \
        --out "$RESULTS_DIR/benchmark.recovery_by_replicon.tsv"; then
    warn "recovery-by-replicon breakdown failed; leaderboard is unaffected"
fi

# Truth-label screen (python/audit_truth_labels.py): does each PLASMID/CHROMOSOME
# label agree with replicon/MOB evidence? Advisory; never edits truth or scores.
if ! python3 "$HERE/../python/audit_truth_labels.py"         --data-dir "$DATA_DIR" --out "$RESULTS_DIR/benchmark.truth_label_audit.tsv"; then
    warn "truth-label audit failed; scores are unaffected"
fi

# How much the ranking depends on scoring choices (python/rank_sensitivity.py):
# re-scores every PAF already on disk with one filter changed at a time, and
# re-ranks under strict F1 and per-plasmid recovery. Advisory: it writes
# benchmark.rank_robustness.tsv and never alters the leaderboard; a failure only
# warns. RUN_RANK_SENSITIVITY=0 skips it.
if [[ "${RUN_RANK_SENSITIVITY:-1}" == "1" ]]; then
    if ! python3 "$HERE/../python/rank_sensitivity.py" \
            --scores "$SCORES" --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" \
            --out-prefix "$RESULTS_DIR/benchmark"; then
        warn "rank-sensitivity analysis failed; leaderboard is unaffected"
    fi
fi

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

python3 "$HERE/../python/build_html_report.py" \
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
log "  Study holdout test : $RESULTS_DIR/benchmark.recommendation_validation.tsv"
log "  Cohort QC flags   : $RESULTS_DIR/benchmark.cohort_qc_flags.tsv (advisory only)"
if [[ "${RUN_RECOMMENDATION_MODEL:-0}" -eq 1 ]]; then
    log "  Recommendation model: $RESULTS_DIR/benchmark.recommendation_model.json"
    log "  Model card           : $RESULTS_DIR/benchmark.recommendation_model.card.md"
fi
log "  Selected output   : $RESULTS_DIR/<sample>/selected_candidate/"
log "  Candidate dataset : $RESULTS_DIR/benchmark.candidate_{features,labels}.tsv"
