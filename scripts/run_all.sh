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

start_console_log
log "############ PlasBench ############"
log "Running stages: ${STAGES[*]}"
[[ -n "${_CONSOLE_LOG_FILE:-}" ]] && log "Console log of this run: $_CONSOLE_LOG_FILE (events: ${RESULTS_DIR:-results}/run_events.jsonl; 'plasbench status' shows what it is doing)"
# A run that the terminal, WSL or the computer ended cannot report it at the time. This marker says what was
# running; it is removed when the run finishes or reports its own error, so finding it means the last run was cut
# off. The next run says so, and reuses the finished work.
mkdir -p "$RESULTS_DIR"
RUN_MARK="$RESULTS_DIR/.run_in_progress"
# The marker names the pid that wrote it: a marker whose process is still alive is a run in progress, not one that was cut off (AU-001).
if [[ -s "$RUN_MARK" ]]; then
    marker_pid="$(sed -n '1s/.*pid \([0-9][0-9]*\).*/\1/p' "$RUN_MARK")"
    if [[ -n "$marker_pid" && "$marker_pid" != "$$" ]] && _pid_alive "$marker_pid"; then
        die "another PlasBench run is in progress in $RESULTS_DIR ($(head -1 "$RUN_MARK")). Wait for it, stop it, or give this run its own results folder."
    fi
fi
acquire_run_lock "run_all.sh stages ${STAGES[*]}"
run_event run_start "stages=${STAGES[*]}" "log=${_CONSOLE_LOG_FILE:-}"
while IFS= read -r _profile_line; do log "$_profile_line"; done < <(python3 -I "$HERE/../python/run_profiles.py" plan "${RUN_PROFILE:-standard}" 2>/dev/null || true)
run_event run_profile "profile=${RUN_PROFILE:-standard}"
# AUTO_PARALLEL: the isolates-at-a-time plan, said once at the start (each stage says it again when it applies it; an explicit MAX_PARALLEL_SAMPLES or AUTO_PARALLEL=0 skips this)
if [[ "${AUTO_PARALLEL:-1}" == "1" && "${PLASBENCH_SAMPLES_EXPLICIT:-0}" != "1" && -f "${SAMPLE_SHEET:-}" ]]; then
    _pb_n="$(read_samples "$SAMPLE_SHEET" 2>/dev/null | awk 'NF' | wc -l | tr -d '[:space:]')"
    if [[ "$_pb_n" =~ ^[0-9]+$ && "$_pb_n" -gt 1 ]]; then
        log "Concurrency (AUTO_PARALLEL=1; AUTO_PARALLEL=0 or MAX_PARALLEL_SAMPLES=N sets it yourself):"
        while IFS= read -r _plan_line; do log "  $_plan_line"; done < <(python3 -I "$HERE/../python/parallel_plan.py" summary --cpus "${PLASBENCH_TEST_CPUS:-$(plasbench_detect_cores)}" \
            --available-mb "${PLASBENCH_TEST_AVAILABLE_MB:-$(plasbench_detect_memory_mb)}" --isolates "$_pb_n" --slot-gb "${ASSEMBLY_SLOT_GB:-8}" --profile "$RESULTS_DIR/resource_profile.tsv" 2>/dev/null || true)
    fi
fi
_pb_sentinel_start          # keeps the computer awake while this run is active (KEEP_AWAKE=0 turns that off) and records any time it was asleep
rm -f "$RESULTS_DIR/.completed_with_warnings"
if [[ -s "$RUN_MARK" ]]; then
    warn "the previous run stopped before it finished, without a chance to report why ($(head -1 "$RUN_MARK")): the terminal, WSL or the computer ended it, or it ran out of memory. Finished work is reused; see $LOG_DIR for its last messages."
fi
for s in "${STAGES[@]}"; do
    # Stages 1-5 operate on individual samples. Aggregation/reporting can be
    # rerun from an existing scores.tsv, even after the original sheet moved.
    [[ "$s" =~ ^[1-5]$|^7$ ]] && { validate_sample_sheet "$SAMPLE_SHEET"; break; }
done
# PIPELINE_OVERLAP=1 (default 0; python/pipeline_overlap.py): while stage 1 downloads, stage 2 runs for each isolate stage 1 has finished in this run (one at a time, low priority,
# private status files); stage 2 then runs as always and reuses that work. Only when this run has both stages 1 and 2.
_PB_OVERLAP_PID="" _PB_OVERLAP_SINCE="$(date +%s)" _PB_OVERLAP_WORK="$RESULTS_DIR/.pipeline_overlap"
_pb_overlap_stop() {
    [[ -n "$_PB_OVERLAP_PID" ]] || return 0
    kill "$_PB_OVERLAP_PID" 2>/dev/null || true
    wait "$_PB_OVERLAP_PID" 2>/dev/null || true
    _PB_OVERLAP_PID=""
}
_pb_overlap_wanted=0
if [[ "${PIPELINE_OVERLAP:-0}" == "1" && " ${STAGES[*]} " == *" 1 "* && " ${STAGES[*]} " == *" 2 "* ]]; then _pb_overlap_wanted=1; fi
for s in "${STAGES[@]}"; do
    scr="${SCRIPT[$s]:-}"
    [[ -z "$scr" ]] && die "unknown stage '$s'"
    log ">>>>> STAGE $s : $scr"
    printf 'started %s, stage %s (%s), pid %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$s" "$scr" "$$" > "$RUN_MARK"
    rc=0
    if [[ "$s" == "1" && "$_pb_overlap_wanted" == "1" ]]; then
        rm -rf "$_PB_OVERLAP_WORK"; mkdir -p "$_PB_OVERLAP_WORK"
        log "PIPELINE_OVERLAP=1: stage 2 starts for each isolate as soon as stage 1 has it (one at a time, low priority; log: $LOG_DIR/pipeline_overlap.log)"
        python3 -I "$HERE/../python/pipeline_overlap.py" follow --events "${RUN_EVENTS_FILE:-$RESULTS_DIR/run_events.jsonl}" --since "$_PB_OVERLAP_SINCE"             --sheet "$SAMPLE_SHEET" --work "$_PB_OVERLAP_WORK" --stop "$_PB_OVERLAP_WORK/stage1.done" --log "$LOG_DIR/pipeline_overlap.log"             --poll "${PIPELINE_OVERLAP_POLL_SECONDS:-20}" < /dev/null &
        _PB_OVERLAP_PID=$!
        on_exit_add _pb_overlap_stop
    fi
    bash "$HERE/$scr" || rc=$?
    if [[ "$s" == "1" && -n "$_PB_OVERLAP_PID" ]]; then
        if [[ "$rc" -eq 0 ]]; then
            : > "$_PB_OVERLAP_WORK/stage1.done"
            log "PIPELINE_OVERLAP: stage 1 is done; waiting for the stage 2 already started to finish its current isolate"
            wait "$_PB_OVERLAP_PID" 2>/dev/null || warn "PIPELINE_OVERLAP: the early stage 2 ended with an error; stage 2 does every isolate it did not finish (see $LOG_DIR/pipeline_overlap.log)"
            _PB_OVERLAP_PID=""
        else
            _pb_overlap_stop
        fi
        rm -rf "$_PB_OVERLAP_WORK"
    fi
    if [[ "$rc" -ne 0 ]]; then
        rm -f "$RUN_MARK"
        _plasbench_record_error "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: the run stopped in stage $s ($scr): $(explain_exit "$rc") (exit $rc). The messages above say why; logs are in $LOG_DIR."
        exit "$rc"
    fi
done
rm -f "$RUN_MARK"
_pb_sentinel_stop           # lets the computer sleep again as soon as the work is done
run_event run_end "status=finished"
# A run that finished but in which some tool runs failed is "completed with warnings": exit 0 (the other tools' results are valid), but never a plain DONE.
n_failed=0
[[ -f "$RESULTS_DIR/tool_status.tsv" ]] && n_failed="$(awk -F'\t' 'NR > 1 && ($3 == "failed" || $3 == "infrastructure_failure") { n++ } END { print n + 0 }' "$RESULTS_DIR/tool_status.tsv")"
if [[ "$n_failed" -gt 0 ]]; then
    printf '%s tool run(s) failed; see tool_status.tsv\n' "$n_failed" > "$RESULTS_DIR/.completed_with_warnings"
    warn "the run finished WITH WARNINGS: $n_failed tool run(s) failed and are excluded from scoring (see $RESULTS_DIR/tool_status.tsv)"
    log "############ DONE (completed with warnings) ############"
else
    log "############ DONE ############"
fi
# Where the time went (awake time; a sleep is shown separately). `plasbench profile-run` has the full table and the biggest costs with suggestions.
_time_spent="$(python3 -I "$HERE/../python/run_profile.py" --results-dir "$RESULTS_DIR" --data-dir "$DATA_DIR" --log-dir "$LOG_DIR" --summary 2>/dev/null || true)"
if [[ -n "$_time_spent" ]]; then log "Time spent (awake time; 'plasbench profile-run' has the table and suggestions):"; while IFS= read -r _l; do log "  $_l"; done <<< "$_time_spent"; fi
if [[ -f "$RESULTS_DIR/benchmark.leaderboard.md" ]]; then
    echo; echo "Leaderboard:"; cat "$RESULTS_DIR/benchmark.leaderboard.md"
fi
exit 0
