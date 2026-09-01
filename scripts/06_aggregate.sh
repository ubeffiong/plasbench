#!/usr/bin/env bash
# Stage 6 — aggregate per-sample scores into a per-tool leaderboard (TSV + MD).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need python3

SCORES="$RESULTS_DIR/scores.tsv"
[[ -s "$SCORES" ]] || die "no scores found at $SCORES; run 05_score.sh first"

python3 "$HERE/../python/aggregate_results.py" \
    --scores "$SCORES" \
    --tool-status "$RESULTS_DIR/tool_status.tsv" \
    --out-prefix "$RESULTS_DIR/benchmark"

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
    --out "$RESULTS_DIR/benchmark.report.html"

log "Stage 6 complete."
log "  Per-sample scores : $SCORES"
log "  Tool status       : $RESULTS_DIR/tool_status.tsv"
log "  Leaderboard (TSV) : $RESULTS_DIR/benchmark.leaderboard.tsv"
log "  Leaderboard (MD)  : $RESULTS_DIR/benchmark.leaderboard.md"
log "  HTML dashboard    : $RESULTS_DIR/benchmark.report.html"
log "  Run manifest      : $RESULTS_DIR/run_manifest.json"
