#!/usr/bin/env bash
# =============================================================================
# run_all.sh — run the whole benchmark end to end.
#
# Usage:
#   bash scripts/run_all.sh              # run every stage
#   bash scripts/run_all.sh 3 4 5        # run only stages 3,4,5
#
# Stages:
#   0 setup    1 download   2 truth   3 assemble   4 run_tools   5 score   6 aggregate
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

STAGES=("$@")
[[ ${#STAGES[@]} -eq 0 ]] && STAGES=(0 1 2 3 4 5 6)

declare -A SCRIPT=(
    [0]="00_setup.sh"
    [1]="01_download.sh"
    [2]="02_truth.sh"
    [3]="03_assemble.sh"
    [4]="04_run_tools.sh"
    [5]="05_score.sh"
    [6]="06_aggregate.sh"
)

log "############ PlasBench ############"
log "Running stages: ${STAGES[*]}"
for s in "${STAGES[@]}"; do
    # Stages 1-5 operate on individual samples. Aggregation/reporting can be
    # rerun from an existing scores.tsv, even after the original sheet moved.
    [[ "$s" =~ ^[1-5]$ ]] && { validate_sample_sheet "$SAMPLE_SHEET"; break; }
done
for s in "${STAGES[@]}"; do
    scr="${SCRIPT[$s]:-}"
    [[ -z "$scr" ]] && die "unknown stage '$s'"
    log ">>>>> STAGE $s : $scr"
    bash "$HERE/$scr"
done
log "############ DONE ############"
[[ -f "$RESULTS_DIR/benchmark.leaderboard.md" ]] && {
    echo; echo "Leaderboard:"; cat "$RESULTS_DIR/benchmark.leaderboard.md"
}
