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
#   7 long_read_reconstruct (optional Flye + MOB-Recon adapter)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

STAGES=("$@")
# Stage 7 (optional long-read/hybrid reconstruction) is included in the
# default run, positioned BEFORE scoring/aggregation (not after) so its
# predictions are scored and aggregated in this same pass rather than
# requiring a separate follow-up invocation. Its own top-of-script guard
# already no-ops when no RUN_FLYE_MOB_RECON/RUN_PLASSEMBLER-family flag is
# on, so including it here never forces a tool to run -- it only means the
# long-read/hybrid track no longer needs a separate, manually-remembered
# invocation once you *have* opted into one.
[[ ${#STAGES[@]} -eq 0 ]] && STAGES=(0 1 2 3 4 7 5 6)

declare -A SCRIPT=(
    [0]="00_setup.sh"
    [1]="01_download.sh"
    [2]="02_truth.sh"
    [3]="03_assemble.sh"
    [4]="04_run_tools.sh"
    [5]="05_score.sh"
    [6]="06_aggregate.sh"
    [7]="07_long_read_reconstruct.sh"
)

log "############ PlasBench ############"
log "Running stages: ${STAGES[*]}"
for s in "${STAGES[@]}"; do
    # Stages 1-5 operate on individual samples. Aggregation/reporting can be
    # rerun from an existing scores.tsv, even after the original sheet moved.
    [[ "$s" =~ ^[1-5]$|^7$ ]] && { validate_sample_sheet "$SAMPLE_SHEET"; break; }
done
for s in "${STAGES[@]}"; do
    scr="${SCRIPT[$s]:-}"
    [[ -z "$scr" ]] && die "unknown stage '$s'"
    log ">>>>> STAGE $s : $scr"
    bash "$HERE/$scr"
done
log "############ DONE ############"
if [[ -f "$RESULTS_DIR/benchmark.leaderboard.md" ]]; then
    echo; echo "Leaderboard:"; cat "$RESULTS_DIR/benchmark.leaderboard.md"
fi
exit 0
