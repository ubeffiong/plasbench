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
python3 "$HERE/../python/aggregate_results.py" \
    --scores "$SCORES" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --sample-sheet "$SAMPLE_SHEET" \
    --out-prefix "$RESULTS_DIR/benchmark"

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
        --min-studies "$RECOMMENDATION_MODEL_MIN_STUDIES" \
        --min-training-samples "$RECOMMENDATION_MODEL_MIN_SAMPLES" \
        --min-relative-improvement "$RECOMMENDATION_MODEL_MIN_IMPROVEMENT" \
        --out "$RESULTS_DIR/benchmark.recommendation_model.json"
    RECOMMENDATION_MODEL_ARGS=(--recommendation-model "$RESULTS_DIR/benchmark.recommendation_model.json")
fi

# Retain the highest-quality already reconstructed candidate for every truth
# sample. Public operational recommendations are gated by the study holdout
# validation above; this never reruns a tool or fabricates a consensus sequence.
python3 "$HERE/../python/select_operational_method.py" \
    --scores "$SCORES" --sample-sheet "$SAMPLE_SHEET" \
    --results-dir "$RESULTS_DIR" --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --recommendation-validation "$RESULTS_DIR/benchmark.recommendation_validation.tsv" \
    "${RECOMMENDATION_MODEL_ARGS[@]}" \
    --out-prefix "$RESULTS_DIR/benchmark" \
    --min-samples "$RECOMMENDATION_MIN_SAMPLES" \
    --min-coverage "$RECOMMENDATION_MIN_COVERAGE" \
    --analysis-track "$ANALYSIS_TRACK"

python3 "$HERE/../python/write_manifest.py" \
    --project-root "$PROJECT_ROOT" --sample-sheet "$SAMPLE_SHEET" \
    --data-dir "$DATA_DIR" --results-dir "$RESULTS_DIR" \
    --out "$RESULTS_DIR/run_manifest.json"

python3 "$HERE/../python/build_html_report.py" \
    --project-root "$PROJECT_ROOT" \
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
log "  Study holdout test : $RESULTS_DIR/benchmark.recommendation_validation.tsv"
log "  Cohort QC flags   : $RESULTS_DIR/benchmark.cohort_qc_flags.tsv (advisory only)"
if [[ "${RUN_RECOMMENDATION_MODEL:-0}" -eq 1 ]]; then
    log "  Recommendation model: $RESULTS_DIR/benchmark.recommendation_model.json"
fi
log "  Selected output   : $RESULTS_DIR/<sample>/selected_candidate/"
