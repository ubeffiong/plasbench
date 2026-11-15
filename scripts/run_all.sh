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
# A run that the terminal, WSL or the computer ended cannot report it at the time. This marker says what was
# running; it is removed when the run finishes or reports its own error, so finding it means the last run was cut
# off. The next run says so, and reuses the finished work.
mkdir -p "$RESULTS_DIR"
RUN_MARK="$RESULTS_DIR/.run_in_progress"
if [[ -s "$RUN_MARK" ]]; then
    warn "the previous run stopped before it finished, without a chance to report why ($(head -1 "$RUN_MARK")): the terminal, WSL or the computer ended it, or it ran out of memory. Finished work is reused; see $LOG_DIR for its last messages."
fi
for s in "${STAGES[@]}"; do
    # Stages 1-5 operate on individual samples. Aggregation/reporting can be
    # rerun from an existing scores.tsv, even after the original sheet moved.
    [[ "$s" =~ ^[1-5]$|^7$ ]] && { validate_sample_sheet "$SAMPLE_SHEET"; break; }
done
for s in "${STAGES[@]}"; do
    scr="${SCRIPT[$s]:-}"
    [[ -z "$scr" ]] && die "unknown stage '$s'"
    log ">>>>> STAGE $s : $scr"
    printf 'started %s, stage %s (%s), pid %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$s" "$scr" "$$" > "$RUN_MARK"
    rc=0
    bash "$HERE/$scr" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        rm -f "$RUN_MARK"
        _plasbench_record_error "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: the run stopped in stage $s ($scr): $(explain_exit "$rc") (exit $rc). The messages above say why; logs are in $LOG_DIR."
        exit "$rc"
    fi
done
rm -f "$RUN_MARK"
log "############ DONE ############"
if [[ -f "$RESULTS_DIR/benchmark.leaderboard.md" ]]; then
    echo; echo "Leaderboard:"; cat "$RESULTS_DIR/benchmark.leaderboard.md"
fi
exit 0
