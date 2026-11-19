#!/usr/bin/env bash
# Shared helpers sourced by every stage script.

# Pretty logging with timestamps.
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# ---- Live status and the run's event log -----------------------------------------------------------------------------------------
# The console this stage was started with (the terminal, the window's job log, or run_all.sh's tee). Heartbeats are written here, never into a tool's own log
# file: callers redirect the tool's output around a whole function (`profile_exec ... > tool.log 2>&1`), which used to swallow the "still working" lines.
# (A named descriptor needs bash 4.1; older bash, such as macOS's 3.2, falls back to stderr itself.)
_pb_set_console_fd() {
    if [[ "${BASH_VERSINFO[0]:-0}" -gt 4 || ( "${BASH_VERSINFO[0]:-0}" -eq 4 && "${BASH_VERSINFO[1]:-0}" -ge 1 ) ]]; then
        exec {PB_CONSOLE_FD}>&2
    else
        PB_CONSOLE_FD=2
    fi
}
[[ -n "${PB_CONSOLE_FD:-}" ]] || _pb_set_console_fd

# Run a potentially quiet command while keeping the user informed. Detailed stdout/stderr may be redirected to a per-tool log by the caller.
heartbeat_log() {
    local message="$*"
    if { : >&"$PB_CONSOLE_FD"; } 2>/dev/null; then
        printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" >&"$PB_CONSOLE_FD"
    elif [[ -w /dev/tty ]]; then
        printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" > /dev/tty
    else
        log "$message" >&2
    fi
}

# JSON-safe text: backslash and quote escaped, control characters turned into spaces.
_json_escape() {
    local s="${1//\\/\\\\}"
    s="${s//\"/\\\"}"; s="${s//$'\n'/ }"; s="${s//$'\r'/ }"; s="${s//$'\t'/ }"
    printf '%s' "$s"
}

# run_event EVENT [key=value ...]: append one JSON line to RESULTS_DIR/run_events.jsonl (RUN_EVENTS_FILE overrides). Every stage, every isolate step, every
# long command and every heartbeat is recorded, so `plasbench status` and `plasbench diagnose` can say what a run is doing, and what it did, without reading
# logs. One line per write (an append of a single short line is atomic), no secrets (callers pass names and numbers, never environment or commands).
run_event() {
    local event="$1"; shift
    local file="${RUN_EVENTS_FILE:-${RESULTS_DIR:+$RESULTS_DIR/run_events.jsonl}}"
    [[ -n "$file" ]] || return 0
    local line kv
    line="{\"ts\":\"$(date '+%Y-%m-%dT%H:%M:%S%z')\",\"epoch\":$(date +%s),\"pid\":$$,\"event\":\"$(_json_escape "$event")\""
    [[ -n "${_STAGE_TIMING_ID:-}" ]] && line+=",\"stage\":\"$(_json_escape "$_STAGE_TIMING_ID")\""
    for kv in "$@"; do
        [[ "$kv" == *=* ]] || continue
        line+=",\"$(_json_escape "${kv%%=*}")\":\"$(_json_escape "${kv#*=}")\""
    done
    printf '%s}\n' "$line" >> "$file" 2>/dev/null || true
}

# proc_stats PID: "cpu=NN% rss=NNNMB procs=N" for PID and everything it started (Linux and macOS ps). Empty when ps cannot say.
proc_stats() {
    ps -eo pid=,ppid=,pcpu=,rss= 2>/dev/null | awk -v root="$1" '
        { ppid[$1] = $2; cpu[$1] = $3; rss[$1] = $4 }
        END {
            for (p in ppid) { q = p; d = 0
                while ((q in ppid) && d < 64) { if (q == root) { n++; c += cpu[p]; r += rss[p]; break } q = ppid[q]; d++ } }
            if (n > 0) printf "cpu=%.0f%% rss=%.0fMB procs=%d", c, r / 1024, n
        }'
}

# sys_stats [DIR]: "mem_avail=NNNMB swap_used=NNNMB disk_free=NNGB" (Linux /proc/meminfo; the fields it cannot read are left out).
sys_stats() {
    local out="" avail swap free
    if [[ -r /proc/meminfo ]]; then
        avail="$(awk '/^MemAvailable:/ { printf "%d", $2 / 1024 }' /proc/meminfo 2>/dev/null)"
        swap="$(awk '/^SwapTotal:/ { t = $2 } /^SwapFree:/ { f = $2 } END { printf "%d", (t - f) / 1024 }' /proc/meminfo 2>/dev/null)"
        [[ -n "$avail" ]] && out+="mem_avail=${avail}MB"
        [[ -n "$swap" ]] && out+="${out:+ }swap_used=${swap}MB"
    fi
    free="$(df -Pk "${1:-.}" 2>/dev/null | awk 'NR == 2 { printf "%.0f", $4 / 1048576 }')"
    [[ -n "$free" ]] && out+="${out:+ }disk_free=${free}GB"
    printf '%s' "$out"
}

# One heartbeat: elapsed time, CPU and memory of the command and what it started, memory/swap/disk of the machine, how long ago its log (WATCH_LOG, set by
# the caller) last changed and that log's last line, plus a plain warning when memory is nearly gone or the command is idle. Also written to the event log.
heartbeat_report() {
    local pid="$1" description="$2" elapsed="$3" stats sysstats idle="" tail_line="" now mtime avail cpu
    stats="$(proc_stats "$pid")"
    sysstats="$(sys_stats "${RESULTS_DIR:-.}")"
    if [[ -n "${WATCH_LOG:-}" && -f "$WATCH_LOG" ]]; then
        now="$(date +%s)"
        mtime="$(stat -c %Y "$WATCH_LOG" 2>/dev/null || stat -f %m "$WATCH_LOG" 2>/dev/null || true)"
        [[ "$mtime" =~ ^[0-9]+$ ]] && idle=$(( now - mtime ))
        tail_line="$(grep -v '^[[:space:]]*$' "$WATCH_LOG" 2>/dev/null | tail -n 1 | tr -d '\r' | cut -c1-110 || true)"
    fi
    heartbeat_log "still working: $description (${elapsed}s elapsed; ${stats:-no process figures}${sysstats:+; $sysstats}${idle:+; its log last changed ${idle}s ago}${tail_line:+: \"$tail_line\"})"
    run_event heartbeat "what=$description" "elapsed=$elapsed" "stats=${stats}" "system=${sysstats}" "log_idle=${idle}"
    avail="$(sed -n 's/.*mem_avail=\([0-9]*\)MB.*/\1/p' <<< "$sysstats")"
    if [[ "$avail" =~ ^[0-9]+$ && "$avail" -lt 300 ]]; then
        heartbeat_log "WARNING: only ${avail} MB of memory is available: $description may be killed (exit 137) or crawl in swap. Lower THREADS or ASSEMBLY_MEMORY_GB, or skip isolates with very large read sets (MAX_RUN_DOWNLOAD_GB)."
        run_event warning "what=$description" "kind=low_memory" "mem_avail_mb=$avail"
    fi
    cpu="$(sed -n 's/.*cpu=\([0-9]*\)%.*/\1/p' <<< "$stats")"
    if [[ "$cpu" =~ ^[0-9]+$ && "$cpu" -lt 5 && "$idle" =~ ^[0-9]+$ && "$idle" -gt 600 ]]; then
        heartbeat_log "WARNING: $description has used almost no CPU and written nothing to its log for $(( idle / 60 )) minutes: it may be waiting on the network or a lock. 'plasbench diagnose' shows what it is waiting on."
        run_event warning "what=$description" "kind=idle" "log_idle=$idle"
    fi
}

run_with_heartbeat() {
    local description="$1"; shift
    local delay="${HEARTBEAT_DELAY_SECONDS:-180}" interval="${HEARTBEAT_INTERVAL_SECONDS:-60}"
    local started elapsed=0 last_notice=0 pid rc=0
    started="$(date +%s)"
    run_event command_start "what=$description"
    "$@" & pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        # Poll cheaply so a fast command returns promptly; only print at the
        # much less frequent configured interval once the quiet-delay passes.
        sleep 1
        elapsed=$(( $(date +%s) - started ))
        if [[ "$elapsed" -ge "$delay" && $(( elapsed - last_notice )) -ge "$interval" ]] && kill -0 "$pid" 2>/dev/null; then
            heartbeat_report "$pid" "$description" "$elapsed"
            last_notice="$elapsed"
        fi
    done
    wait "$pid" || rc=$?
    run_event command_end "what=$description" "seconds=$(( $(date +%s) - started ))" "exit=$rc"
    return "$rc"
}
# Warnings print yellow and errors red, when they go to a terminal (never into a log file or the window, which
# colours them itself). NO_COLOR (https://no-color.org) or PLASBENCH_COLOR=never turns colour off;
# PLASBENCH_COLOR=always forces it.
if [[ "${PLASBENCH_COLOR:-auto}" == "always" ]] \
   || { [[ -t 2 && -z "${NO_COLOR:-}" && "${PLASBENCH_COLOR:-auto}" != "never" && "${TERM:-}" != "dumb" ]]; }; then
    _C_WARN=$'\033[33m'; _C_ERR=$'\033[1;31m'; _C_OFF=$'\033[0m'
else
    _C_WARN=""; _C_ERR=""; _C_OFF=""
fi
warn() { printf '%s[%s] WARNING: %s%s\n' "$_C_WARN" "$(date '+%Y-%m-%d %H:%M:%S')" "$*" "$_C_OFF" >&2; }
die()  { printf '%s[%s] ERROR: %s%s\n' "$_C_ERR" "$(date '+%Y-%m-%d %H:%M:%S')" "$*" "$_C_OFF" >&2; exit 1; }

# Check a command exists; die if not.
need() {
    command -v "$1" >/dev/null 2>&1 || die "required command '$1' not found in PATH. Did you activate the conda env?"
}

# Check a command exists; warn + return 1 if not (for optional tools).
have() { command -v "$1" >/dev/null 2>&1; }

# Reject a sample_id that could act as a path-traversal payload once it is
# used to build a directory name (results/<sample>/, data/<sample>/, etc).
# Mirrors the pattern enforced on sample-sheet rows in validate_sample_sheet.
valid_sample_id() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

# True when a tool left something in its output directory. A tool that ran, even one that found no plasmid, writes at least a log or a
# table there; a directory that is missing or empty means it crashed or wrote somewhere else, which must not be read as "no plasmids".
# A log alone does not count (AU-008): only files that are not *.log, *.err, *.stderr, *.stdout, *.out or the run.log/command files are real output; each adapter
# additionally checks for its own tool's result files (adapters/_require_output.sh).
tool_output_present() {
    [[ -d "$1" ]] && [[ -n "$(find "$1" -type f ! -iname '*.log' ! -iname '*.err' ! -iname '*.stderr' ! -iname '*.stdout' ! -iname '*.out' ! -name 'command*' -print -quit 2>/dev/null)" ]]
}

# --- crash-aware sample jobs ---------------------------------------------
# A stage runs one background job per sample. `wait` with no arguments returns 0 whatever those jobs did, and a job that dies under
# `set -e` leaves no row behind, so a crashed sample used to vanish from the results while the stage reported success.
# start_sample_job runs COMMAND in the background exactly as `COMMAND &` would (a subshell, still under set -e) and, if it exits non-zero
# for any reason, leaves CRASH_DIR/SAMPLE holding the exit code. report_crashed_sample_jobs reads those once the stage has merged what the
# other samples produced, so their results are kept, and then fails the stage (or only warns when ALLOW_CRASHED_SAMPLE_JOBS=1).
start_sample_job() {
    local crash_dir="$1" sample="$2"; shift 2
    (
        trap 'rc=$?; [[ $rc -eq 0 ]] || printf "%s\n" "$rc" > "$crash_dir/$sample" 2>/dev/null' EXIT
        "$@"
    ) &
}

report_crashed_sample_jobs() {
    local stage="$1" crash_dir="$2" crashed=() f msg
    for f in "$crash_dir"/*; do [[ -e "$f" ]] && crashed+=("$(basename "$f")"); done
    rm -rf "$crash_dir"
    (( ${#crashed[@]} )) || return 0
    msg="$stage: the job for ${#crashed[@]} sample(s) crashed before it finished: ${crashed[*]}. Their results are MISSING, not zero (see ${LOG_DIR:-the log directory}/run_errors.log and the sample's log)."
    if [[ "${ALLOW_CRASHED_SAMPLE_JOBS:-0}" == "1" ]]; then
        warn "$msg Continuing because ALLOW_CRASHED_SAMPLE_JOBS=1."
    else
        die "$msg Fix the cause and re-run, or set ALLOW_CRASHED_SAMPLE_JOBS=1 to continue without them."
    fi
}

# --- parallel job pool --------------------------------------------------
# Block until fewer than MAX background jobs of this shell are running, then
# return so the caller can start one more with `&`. MAX=1 (every stage's
# default) waits for every previously started job to finish before letting a
# new one start, which is exactly sequential execution -- so callers do not
# need to special-case the non-parallel default; they always background and
# always gate through this function.
job_slot_wait() {
    local max="$1"
    while [[ "$(jobs -rp | wc -l)" -ge "$max" ]]; do
        wait -n 2>/dev/null || break
    done
}

# Advisory only: warn (never block) when a chosen concurrency level would ask
# for more CPU threads, or more memory, than the host actually has. Runs once
# per stage invocation. Detects cores via `nproc` and available memory via
# /proc/meminfo, both Linux-only; silently skipped on any other platform
# (e.g. this reports nothing useful on macOS/WSL without /proc, and that is
# fine -- it is a courtesy check, not a scheduler).
warn_resource_oversubscription() {
    local label="$1" parallel_jobs="$2" threads_per_job="$3" memory_gb_per_job="${4:-0}"
    have nproc || return 0
    local cores wanted_threads
    cores="$(nproc)"
    wanted_threads=$(( parallel_jobs * threads_per_job ))
    if [[ "$wanted_threads" -gt "$cores" ]]; then
        warn "$label: $parallel_jobs concurrent job(s) x $threads_per_job thread(s) each = $wanted_threads threads requested, but only $cores CPU core(s) detected. Oversubscription can be SLOWER than running fewer jobs at once (context switching, cache thrashing) -- consider lowering the parallel-job count or the per-job thread count."
    fi
    if [[ "$memory_gb_per_job" -gt 0 && -r /proc/meminfo ]]; then
        local available_kb available_gb wanted_gb
        available_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
        if [[ -n "$available_kb" ]]; then
            available_gb=$(( available_kb / 1024 / 1024 ))
            wanted_gb=$(( parallel_jobs * memory_gb_per_job ))
            if [[ "$wanted_gb" -gt "$available_gb" ]]; then
                warn "$label: $parallel_jobs concurrent job(s) x ${memory_gb_per_job}GB each = ${wanted_gb}GB requested, but only ~${available_gb}GB is currently available. Running out of memory mid-job (e.g. SPAdes) can be far slower than fewer concurrent jobs, or force the OS to swap -- consider lowering the parallel-job count."
            fi
        fi
    fi
}

# --- shard-then-merge for shared output files ----------------------------
# Every stage that can now run several samples/tools concurrently writes its
# per-unit output rows to a private file under this directory instead of
# appending directly to the stage's one shared TSV -- concurrent appends from
# separate processes are not safe to assume atomic across every code path
# that writes them (a `csv.DictWriter` header check, in particular, races).
# merge_shards then rebuilds the shared file, once, after every job in the
# stage has finished, in the caller-supplied deterministic order -- so the
# merged file's row order matches today's sequential output exactly, whatever
# order the parallel jobs actually completed in.
# Every process gets its own temporary area (TMP_DIR/.run.XXXXXX, made on first use), so two runs that share TMP_DIR (two terminals, the window
# beside a terminal, two non-study runs) can no longer wipe each other's shards (audit AU-001). It is removed when the process ends; a run killed with
# SIGKILL leaves it behind and the next run reports and keeps it (recover_stale_run_dirs).
shard_dir() {
    local stage_name="$1"
    printf '%s/.shards.%s' "${RUN_TMP_DIR:-${TMP_DIR:-/tmp}}" "$stage_name"
}

reset_shard_dir() {
    init_run_tmp
    local dir; dir="$(shard_dir "$1")"
    rm -rf "$dir"; mkdir -p "$dir"
}

# --- exit hooks, unique temp area, run lock, stage timing -------------------------------------------------------------
_PLASBENCH_MAIN_PID="$BASHPID"
_PLASBENCH_EXIT_HOOKS=()
_PLASBENCH_EXIT_RC=0
# on_exit_add FUNCTION: run FUNCTION (no arguments) when this script ends, however it ends (a subshell never runs them).
_plasbench_run_exit_hooks() {
    _PLASBENCH_EXIT_RC=$?
    [[ "$BASHPID" == "$_PLASBENCH_MAIN_PID" ]] || return 0
    trap - EXIT
    local hook
    for hook in "${_PLASBENCH_EXIT_HOOKS[@]}"; do "$hook" || true; done
    stop_console_log || true      # last, so the hooks' own messages are still captured
    return 0
}

# start_console_log: keep this run's console output in the study as LOG_DIR/run_<date>-<time>.log (the newest LOG_RETENTION_RUNS, default 20, are kept; run.latest.log
# points at the newest), in addition to showing it. Called once by run_all.sh. RUN_CONSOLE_LOG=0 turns it off. The tee is closed and waited for at exit, so the last
# lines are never lost. Heartbeats follow the redirect (PB_CONSOLE_FD is re-pointed), so they land in the log too.
start_console_log() {
    [[ "${RUN_CONSOLE_LOG:-1}" == "1" && -n "${LOG_DIR:-}" && -z "${_CONSOLE_LOG_FILE:-}" ]] || return 0
    mkdir -p "$LOG_DIR" 2>/dev/null || return 0
    local file
    file="$LOG_DIR/run_$(date +%Y%m%d-%H%M%S).log"
    : > "$file" 2>/dev/null || return 0
    ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +"$(( ${LOG_RETENTION_RUNS:-20} + 1 ))" | while read -r old; do rm -f "$old"; done
    _CONSOLE_LOG_FILE="$file"
    exec > >(tee -a "$file") 2>&1
    _CONSOLE_TEE_PID=$!
    _pb_set_console_fd
    ln -sf "$(basename "$file")" "$LOG_DIR/run.latest.log" 2>/dev/null || cp -f "$file" "$LOG_DIR/run.latest.log" 2>/dev/null || true
}
stop_console_log() {
    [[ -n "${_CONSOLE_TEE_PID:-}" ]] || return 0
    local pid="$_CONSOLE_TEE_PID"; _CONSOLE_TEE_PID=""
    # Every copy of the tee's pipe must be closed before it sees end-of-input: stdout, stderr and the heartbeat descriptor.
    if [[ "${PB_CONSOLE_FD:-2}" -gt 2 ]]; then eval "exec ${PB_CONSOLE_FD}>&-"; PB_CONSOLE_FD=2; fi
    exec >&- 2>&-
    wait "$pid" 2>/dev/null || true
    return 0
}
on_exit_add() {
    _PLASBENCH_EXIT_HOOKS+=("$1")
    trap '_plasbench_run_exit_hooks' EXIT
}

init_run_tmp() {
    [[ -n "${RUN_TMP_DIR:-}" && -d "${RUN_TMP_DIR:-}" && "${_RUN_TMP_OWNER:-}" == "$BASHPID" ]] && return 0
    mkdir -p "${TMP_DIR:-/tmp}"
    recover_stale_run_dirs
    RUN_TMP_DIR="$(mktemp -d "${TMP_DIR:-/tmp}/.run.XXXXXX")"
    _RUN_TMP_OWNER="$BASHPID"
    printf '%s\n' "$$" > "$RUN_TMP_DIR/owner"
    on_exit_add cleanup_run_tmp
}

cleanup_run_tmp() {
    [[ "${_RUN_TMP_OWNER:-}" == "$BASHPID" && -n "${RUN_TMP_DIR:-}" ]] && rm -rf "$RUN_TMP_DIR"
    return 0
}

# A run that was killed (SIGKILL, power loss) cannot clean up. Its temp area is moved to LOG_DIR/recovered_shards/ and reported, never silently
# deleted: finished tools are reused through their .complete markers on the next run, and the shard rows show what the killed run had recorded.
recover_stale_run_dirs() {
    local d owner n dest
    for d in "${TMP_DIR:-/tmp}"/.run.*; do
        [[ -d "$d" ]] || continue
        owner="$(cat "$d/owner" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then continue; fi
        n="$(find "$d" -name '*.tsv' 2>/dev/null | wc -l | tr -d ' ')"
        dest="${LOG_DIR:-${TMP_DIR:-/tmp}}/recovered_shards"
        mkdir -p "$dest" 2>/dev/null || true
        if mv "$d" "$dest/$(basename "$d")" 2>/dev/null; then
            warn "found the temporary results of a run that was killed (pid ${owner:-unknown}; ${n} unmerged status row file(s)); kept in $dest/$(basename "$d"). Tools it finished are reused through their .complete markers."
        fi
    done
    return 0
}

_pid_alive() { [[ "${1:-}" =~ ^[0-9]+$ ]] && kill -0 "$1" 2>/dev/null; }
# True when a process other than $2 (not a zombie) still belongs to process group $1.
_pgroup_alive() {
    [[ "${1:-}" =~ ^[0-9]+$ ]] || return 1
    ps -eo pgid=,pid=,stat= 2>/dev/null | awk -v g="$1" -v me="${2:-0}" '$1 == g && $2 != me && $3 !~ /^Z/ { found = 1 } END { exit !found }'
}

# acquire_run_lock WHAT: one run at a time per results folder. The lock file RESULTS_DIR/.run.lock holds the pid, the start time and the process group
# (when this run leads one: setsid, or the window's job runner). It refuses, with a message, while the pid or any member of the recorded group is alive,
# and removes a stale lock (audit AU-001/AU-009). run_all.sh holds the lock for its stages and exports PLASBENCH_LOCK_PID, so they do not refuse themselves.
# The check-then-remove-then-create sequence below runs inside a short mutex, the directory RESULTS_DIR/.run.lock.guard (mkdir is atomic): before it,
# two starters that both saw the same stale lock could both delete it, and the second delete removed the first starter's fresh lock, so both ran
# (AU-009). Residual limits: a guard left by a killed starter is reclaimed when its pid is dead (that reclaim is itself a small window); a guard
# whose owner is alive is waited for up to ~10 s and then refused; the lock is still pid based, so pid reuse can refuse a start that was safe and
# the pids of a WSL run are not visible to a Windows check (and the reverse); SIGKILL of the lock holder leaves the lock until the next start.
# Heartbeat (AU-009 follow-up): the holder also touches RESULTS_DIR/.run.lock.heartbeat every PLASBENCH_LOCK_HEARTBEAT_SECONDS (default 5) from a small background
# loop (its own session where setsid exists, so a killed run's group does not count it as a survivor; it ends when the holder's pid is gone or the file is
# removed). A lock whose heartbeat file is older than PLASBENCH_LOCK_STALE_SECONDS (default 60) is stale EVEN WHEN ITS PID IS ALIVE: a pid that was reused by an
# unrelated process after a SIGKILL or a reboot no longer blocks the next start, and neither does a holder that has been stopped for longer than the threshold.
# Residual limits: a lock without a heartbeat file (written by an older version) is still judged by its pid alone; a holder that is merely suspended (SIGSTOP, a
# laptop sleep, a machine too loaded to schedule the loop for the whole threshold) is declared stale and can be taken over while it still runs, which the
# process-group check below only prevents for a holder that leads a group; a heartbeat younger than the threshold after a SIGKILL still refuses for up to that
# long when the pid has been reused; the file clock is the local one, so a results folder on a network share with a skewed clock can misjudge; the WSL/Windows pid
# difference above still applies.
_lock_file_age() {   # seconds since the file was last modified; empty when it does not exist
    local m
    [[ -e "$1" ]] || return 0
    m="$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || true)"
    [[ "$m" =~ ^[0-9]+$ ]] && echo $(( $(date +%s) - m ))
    return 0
}
_lock_heartbeat_start() {
    local hb="$1.heartbeat" interval="${PLASBENCH_LOCK_HEARTBEAT_SECONDS:-5}"
    [[ "$interval" =~ ^[0-9]+([.][0-9]+)?$ ]] || interval=5
    : > "$hb" 2>/dev/null || return 0
    local loop='owner="$1"; hb="$2"; every="$3"; while kill -0 "$owner" 2>/dev/null && [[ -f "$hb" ]]; do sleep "$every"; [[ -f "$hb" ]] && touch "$hb" 2>/dev/null; done'
    if command -v setsid >/dev/null 2>&1; then
        setsid bash -c "$loop" _ "$$" "$hb" "$interval" >/dev/null 2>&1 < /dev/null &
    else
        bash -c "$loop" _ "$$" "$hb" "$interval" >/dev/null 2>&1 < /dev/null &
    fi
    disown 2>/dev/null || true
}
_lock_guard_enter() {
    local guard="$1.guard" tries=0 owner
    until mkdir "$guard" 2>/dev/null; do
        owner="$(cat "$guard/pid" 2>/dev/null || true)"
        if [[ -n "$owner" ]] && ! _pid_alive "$owner"; then rm -rf "$guard"; continue; fi
        tries=$(( tries + 1 ))
        if (( tries > 100 )); then
            die "the run lock of $RESULTS_DIR is being changed by another start (guard $guard, pid ${owner:-unknown}) and did not free within 10 seconds; try again."
        fi
        sleep 0.1
    done
    printf '%s\n' "$$" > "$guard/pid"
}

_lock_guard_leave() {
    local guard="${RESULTS_DIR:-/nonexistent}/.run.lock.guard"
    [[ "$(cat "$guard/pid" 2>/dev/null || true)" == "$$" ]] && rm -rf "$guard"
    return 0
}

acquire_run_lock() {
    local what="$1" lock="${RESULTS_DIR:?}/.run.lock" holder_pid holder_pgid holder_start holder_what my_pgid hb_age stale_after
    mkdir -p "$RESULTS_DIR"
    if [[ -n "${PLASBENCH_LOCK_PID:-}" && -f "$lock" ]] && grep -qx "pid=$PLASBENCH_LOCK_PID" "$lock" && _pid_alive "$PLASBENCH_LOCK_PID"; then
        return 0
    fi
    _lock_guard_enter "$lock"
    on_exit_add _lock_guard_leave
    if [[ -s "$lock" ]]; then
        holder_pid="$(sed -n 's/^pid=//p' "$lock" | head -1)"
        holder_pgid="$(sed -n 's/^pgid=//p' "$lock" | head -1)"
        holder_start="$(sed -n 's/^started=//p' "$lock" | head -1)"
        holder_what="$(sed -n 's/^what=//p' "$lock" | head -1)"
        hb_age="$(_lock_file_age "$lock.heartbeat")"
        stale_after="${PLASBENCH_LOCK_STALE_SECONDS:-60}"
        [[ "$stale_after" =~ ^[0-9]+$ ]] || stale_after=60
        if [[ "$holder_pid" != "$$" ]] && _pid_alive "$holder_pid" && [[ -n "$hb_age" ]] && (( hb_age > stale_after )); then
            warn "the run lock in $RESULTS_DIR names pid $holder_pid, which is alive, but its heartbeat is ${hb_age} s old (limit ${stale_after} s): treating the lock as stale (the pid was probably reused by another program, or that run has been stopped)."
        elif [[ "$holder_pid" != "$$" ]] && _pid_alive "$holder_pid"; then
            _lock_guard_leave
            die "another PlasBench run is already using $RESULTS_DIR (pid $holder_pid, ${holder_what:-unknown stage}, started ${holder_start:-unknown}). Wait for it, stop it, or give this run its own results folder (--results-dir or --study)."
        fi
        if _pgroup_alive "$holder_pgid" "$$"; then
            _lock_guard_leave
            die "a previous run in $RESULTS_DIR (pid ${holder_pid:-?}) is gone, but processes of its process group $holder_pgid are still running (a killed run leaves its tools behind). Stop them first (kill -- -$holder_pgid), then start again."
        fi
        warn "removing a stale run lock in $RESULTS_DIR (pid ${holder_pid:-unknown}, ${holder_what:-unknown stage}, started ${holder_start:-unknown}): that run is no longer alive."
        rm -f "$lock" "$lock.heartbeat"
    fi
    my_pgid="$(ps -o pgid= -p "$$" 2>/dev/null | tr -d ' ' || true)"
    [[ "$my_pgid" == "$$" || ( -n "$my_pgid" && "${PLASBENCH_JOB_GROUP:-}" == "1" ) ]] || my_pgid=""
    if ! ( set -o noclobber; printf 'pid=%s\npgid=%s\nstarted=%s\nwhat=%s\n' "$$" "$my_pgid" "$(date '+%Y-%m-%d %H:%M:%S')" "$what" > "$lock" ) 2>/dev/null; then
        _lock_guard_leave
        die "another PlasBench run took the lock on $RESULTS_DIR at the same moment ($(sed -n 's/^pid=//p' "$lock" 2>/dev/null | head -1)); start again when it has finished."
    fi
    _lock_heartbeat_start "$lock"
    _lock_guard_leave
    _RUN_LOCK_OWNER="$BASHPID"
    export PLASBENCH_LOCK_PID="$$"
    on_exit_add release_run_lock
}

release_run_lock() {
    [[ "${_RUN_LOCK_OWNER:-}" == "$BASHPID" ]] && rm -f "${RESULTS_DIR:-/nonexistent}/.run.lock" "${RESULTS_DIR:-/nonexistent}/.run.lock.heartbeat"
    return 0
}

# tool_timeout_notice: said once at the start of stage 4. No tool time limit is the confirmed default (a limit can score a slow tool zero), so a wedged tool can hold
# a run for ever; this tells the user, and names the opt-in (AU-010). Silent when a limit is set.
tool_timeout_notice() {
    [[ -n "${TOOL_TIMEOUT_SECONDS:-}" ]] && return 0
    log "NOTE: no tool time limit is set (TOOL_TIMEOUT_SECONDS is blank), so a tool that hangs will hold this run until you stop it. This is the default because a limit can score a slow but correct tool as failed. To guard against a stuck run set PLASBENCH_TOOL_TIMEOUT_PRESET=generous (two days per tool per isolate) or TOOL_TIMEOUT_SECONDS=<seconds>."
}

# stage_timing_begin STAGE: record how long this stage script ran into RESULTS_DIR/stage_timing.tsv when it ends (one row per stage, the latest run
# replaces the earlier one), including a stage that failed (audit AU-033).
stage_timing_begin() {
    _STAGE_TIMING_ID="$1"; _STAGE_TIMING_START="$(date +%s)"
    on_exit_add record_stage_timing
    run_event stage_start "${SAMPLE_SHEET:+sheet=$(basename "$SAMPLE_SHEET")}" "$(sys_stats "${RESULTS_DIR:-.}" | sed 's/^/system=/')"
}

record_stage_timing() {
    [[ -n "${_STAGE_TIMING_ID:-}" && -d "${RESULTS_DIR:-/nonexistent}" ]] || return 0
    run_event stage_end "seconds=$(( $(date +%s) - _STAGE_TIMING_START ))" "exit=${_PLASBENCH_EXIT_RC:-}"
    local file="$RESULTS_DIR/stage_timing.tsv" tmp end
    tmp="$file.$$.tmp"; end="$(date +%s)"
    {
        printf 'stage\tstarted\tended\telapsed_seconds\texit_code\n'
        if [[ -f "$file" ]]; then awk -F'\t' -v s="$_STAGE_TIMING_ID" 'NR > 1 && $1 != s' "$file"; fi
        printf '%s\t%s\t%s\t%s\t%s\n' "$_STAGE_TIMING_ID" "$_STAGE_TIMING_START" "$end" "$(( end - _STAGE_TIMING_START ))" "$_PLASBENCH_EXIT_RC"
    } > "$tmp" 2>/dev/null && mv -f "$tmp" "$file" 2>/dev/null
    return 0
}

# check_free_disk DIR [MIN_GB]: warn (never stop) when the folder's drive has less than MIN_GB free (default MIN_FREE_DISK_GB, 20; 0 turns it off).
check_free_disk() {
    local dir="$1" min_gb="${2:-${MIN_FREE_DISK_GB:-20}}" kb
    [[ "$min_gb" =~ ^[0-9]+$ && "$min_gb" -gt 0 ]] || return 0
    kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }')"
    [[ "$kb" =~ ^[0-9]+$ ]] || return 0
    if (( kb / 1048576 < min_gb )); then
        warn "only about $(( kb / 1048576 )) GB is free where $dir is (below the ${min_gb} GB threshold, MIN_FREE_DISK_GB): downloads and assemblies may fill the disk."
    fi
    return 0
}

# merge_shards STAGE_NAME OUT_FILE HEADER SHARD_FILE...
# Writes HEADER once, then the content of every existing shard file, in the
# order given. A shard that a job never created (skipped/never reached) is
# simply absent from OUT_FILE, matching what a direct sequential append would
# have produced for that same skip.
merge_shards() {
    local out="$1" header="$2"; shift 2
    printf '%s\n' "$header" > "$out"
    local shard
    for shard in "$@"; do
        [[ -s "$shard" ]] && cat "$shard" >> "$out"
    done
    # A shard that a job never wrote (a skipped/never-reached unit) makes the
    # loop's last `[[ ]]` false. Under `set -e`, when a bare `test && cmd` is
    # the LAST command a function runs, the false test's own exit status
    # becomes the function's -- which then aborts the calling script. This
    # trailing `true` keeps the function's exit status 0 regardless of how
    # the loop's last iteration came out.
    true
}

# Iterate real rows of the sample sheet (skip blank lines, comments, header).
# Prints: sample_id <TAB> assembly_accession <TAB> sra_run
read_samples() {
    local sheet="$1"
    # skip header (first non-comment line), comments, blanks
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        {
            if (!seen_header) { seen_header=1; next }  # drop header row
            # An empty accession (a reads-only, "operational" row) must stay a field: bash `read` with a tab separator would otherwise
            # collapse the two tabs and shift the read prefix into the accession column. NA is what the stages already treat as "no reference".
            print $1"\t"($2 == "" ? "NA" : $2)"\t"$3
        }
    ' "$sheet"
}

# Fail before expensive stages when the template sheet has not been populated,
# or when identifiers would collide in the per-sample output directories.
validate_sample_sheet() {
    local sheet="$1"
    [[ -f "$sheet" ]] || die "sample sheet not found: $sheet"
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        !seen_header {seen_header=1; next}
        {data_rows++}
        NF < 3 || $1 == "" || $2 == "" || $3 == "" {
            print "ERROR: invalid sample-sheet row " NR "; expected sample_id, assembly_accession, sra_run" > "/dev/stderr"
            bad=1; next
        }
        $1 !~ /^[A-Za-z0-9][A-Za-z0-9._-]*$/ {
            print "ERROR: unsafe sample_id \047" $1 "\047 in row " NR "; use only letters, digits, dot, dash, underscore (it becomes a directory name)" > "/dev/stderr"
            bad=1; next
        }
        curated && (NF < 8 || $4 == "" || $5 == "" || $6 !~ /^[ABC]$/ || $7 == "" || $8 == "") {
            # Name the first three rows, then count the rest: a sheet with the wrong kind of columns used to print one identical line per isolate.
            n_uncurated++
            if (n_uncurated <= 3)
                print "ERROR: uncurated sample-sheet row " NR "; require organism, truth_technology, truth_quality_tier (A/B/C), biosample, bioproject" > "/dev/stderr"
            bad=1; next
        }
        seen_sample[$1]++ {
            print "ERROR: duplicate sample_id \047" $1 "\047 in sample sheet" > "/dev/stderr"
            bad=1; next
        }
        {count++}
        END {
            if (n_uncurated > 3)
                print "ERROR: ... and " (n_uncurated - 3) " more uncurated rows (" n_uncurated " of " data_rows " rows lack the curated columns)" > "/dev/stderr"
            if (n_uncurated > 0 && n_uncurated == data_rows)
                print "NOTE: not one row has the curated columns, so this file is probably not a cohort sheet (the accession ledger cohorts/accepted_accessions.tsv, for example, only lists accessions). Use a sheet from cohorts/ such as public-v4, or fill in the columns (docs/INPUT_GUIDE.md); REQUIRE_CURATED_METADATA=0 skips this check for a sheet that only has sample_id, assembly_accession and sra_run." > "/dev/stderr"
            if (bad) exit 2
            if (count == 0) {
                print "ERROR: sample sheet has no data rows; add samples to config/accessions.tsv" > "/dev/stderr"
                exit 3
            }
        }
    ' curated="${REQUIRE_CURATED_METADATA:-1}" "$sheet" || die "fix sample-sheet errors in $sheet"
}

# retry_network DESCRIPTION -- COMMAND...
# Run a network command, retrying with linear backoff. NCBI's SRA and datasets
# endpoints fail transiently, and on a slow or lossy link they fail often. A
# single dropped transfer should not end a multi-hour cohort download, so every
# fetch goes through here. Attempts and delay are configurable via
# NETWORK_RETRIES and NETWORK_RETRY_DELAY_SECONDS.
retry_network() {
    local what="$1"; shift
    local attempts="${NETWORK_RETRIES:-3}"
    local delay="${NETWORK_RETRY_DELAY_SECONDS:-15}"
    local n=1
    while true; do
        if "$@"; then
            [[ "$n" -gt 1 ]] && log "  $what succeeded on attempt $n/$attempts"
            return 0
        fi
        if [[ "$n" -ge "$attempts" ]]; then
            warn "  $what failed after $n attempt(s)"
            return 1
        fi
        warn "  $what failed (attempt $n/$attempts); retrying in $((delay * n))s"
        sleep $((delay * n))
        n=$((n + 1))
    done
}

# sample_column SHEET SAMPLE_ID COLUMN_NAME
# Print one metadata field for one sample, or nothing when the sheet has no
# such column. read_samples() deliberately yields only the three columns every
# stage needs; this is for the optional curation fields (truth_technology,
# gram_group, and the truth_independent_of_long_reads declaration the
# long-read/hybrid circularity guard below needs).
sample_column() {
    local sheet="$1" sample="$2" column="$3"
    [[ -f "$sheet" ]] || return 0
    awk -F'\t' -v want="$sample" -v col="$column" '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        !seen { for (i = 1; i <= NF; i++) if ($i == col) c = i; seen = 1; next }
        c && $1 == want { print $c; exit }
    ' "$sheet"
}

# -------- tool-capability registry, read once per process --------
# config/tool_capabilities.tsv is static for a run, but it used to be queried by
# launching python3 per question (up to five times per sample x tool in stage 5:
# 12.5% of the demo's wall time in docs/PERFORMANCE_AUDIT.md). It is now validated
# and loaded once into associative arrays; background jobs inherit them. A tool
# missing from the registry, or a registry that fails validation, answers exactly
# as the per-call lookups did: not binning-capable, no track, not applicable.
declare -gA PB_CAP_BINNING=() PB_CAP_TRACK=() PB_CAP_LR_TRUTH=() PB_CAP_TASK=()
PB_CAP_LOADED=""
load_capabilities() {
    local registry="$1" tool binning track lr task
    [[ "$PB_CAP_LOADED" == "$registry" ]] && return 0
    PB_CAP_BINNING=(); PB_CAP_TRACK=(); PB_CAP_LR_TRUTH=(); PB_CAP_TASK=()
    while IFS=$'\t' read -r tool binning track lr task; do
        [[ -n "$tool" ]] || continue
        task="${task%$'\r'}"   # a Windows python3 ends lines with \r\n
        PB_CAP_BINNING[$tool]="$binning"; PB_CAP_TRACK[$tool]="$track"; PB_CAP_LR_TRUTH[$tool]="$lr"; PB_CAP_TASK[$tool]="${task:-binning_reconstruction}"
    done < <(python3 "$PROJECT_ROOT/python/tool_capabilities.py" --registry "$registry" --dump 2>/dev/null)
    PB_CAP_LOADED="$registry"
}
capability_binning() { load_capabilities "$1"; [[ "${PB_CAP_BINNING[$2]:-}" == "yes" ]]; }
capability_track() {
    load_capabilities "$1"
    [[ -n "${PB_CAP_TRACK[$2]:-}" ]] || return 1
    printf '%s\n' "${PB_CAP_TRACK[$2]}"
}
capability_task() { load_capabilities "$1"; printf '%s\n' "${PB_CAP_TASK[$2]:-binning_reconstruction}"; }
capability_requires_lr_truth() { load_capabilities "$1"; [[ "${PB_CAP_LR_TRUTH[$2]:-}" == "yes" ]]; }

# long_read_truth_eligible TOOL SAMPLE
# Prints the eligibility reason on stdout; returns 0 if the sample is
# eligible for TOOL, 1 otherwise. Generalizes what used to be a single
# Plassembler-only check: any tool config/tool_capabilities.tsv declares
# requires_independent_long_read_truth=yes must clear this before it runs,
# since scoring it against a truth assembly built from the very same long
# reads it is handed would score the tool against its own input (see
# docs/METHODS.md's circularity section). A tool the registry does not
# require this for (short-read tools, or a tool missing from the registry)
# is always eligible.
#
# Eligibility, in order:
#   1. The sample sheet declares truth_independent_of_long_reads=yes/true/1
#      (case-insensitive) for this sample -> eligible ("independent").
#   2. The tool's own override variable, <TOOL_UPPERCASE>_ALLOW_CIRCULAR_TRUTH,
#      is 1 -> eligible ("override"). Bash indirect expansion means every
#      tool gets this override for free with no changes needed here; e.g.
#      "plassembler" reads $PLASSEMBLER_ALLOW_CIRCULAR_TRUTH, unchanged from
#      before this function existed.
#   3. Otherwise -> ineligible; prints the sample's truth_technology (or
#      "unknown") as the reason, for the caller to fold into its own
#      tool_status.tsv message.
long_read_truth_eligible() {
    local tool="$1" sample="$2"
    local registry="$PROJECT_ROOT/config/tool_capabilities.tsv"
    if ! capability_requires_lr_truth "$registry" "$tool"; then
        printf 'not-applicable'
        return 0
    fi
    local declared truth override_var override_value
    declared="$(sample_column "$SAMPLE_SHEET" "$sample" truth_independent_of_long_reads)"
    case "$(printf '%s' "${declared:-}" | tr '[:upper:]' '[:lower:]')" in
        yes|true|1) printf 'independent'; return 0 ;;
    esac
    override_var="$(printf '%s' "$tool" | tr '[:lower:]' '[:upper:]')_ALLOW_CIRCULAR_TRUTH"
    override_value="${!override_var:-0}"
    if [[ "$override_value" -eq 1 ]]; then
        printf 'override'
        return 0
    fi
    truth="$(sample_column "$SAMPLE_SHEET" "$sample" truth_technology)"
    printf '%s' "${truth:-unknown}"
    return 1
}

# mobsuite_db_dir -- print where the MOB-suite that will actually run keeps its
# databases, or nothing if it cannot be located.
#
# Order matters. `import mob_suite` from this interpreter can find a DIFFERENT
# installation from the one mob_recon executes: the container ships a pinned
# mob_suite in its own environment behind a PATH shim, because its pandas cannot
# co-exist with the main lock, while an unused copy may still sit in the main
# environment. The database that matters is the one the running tool reads, so
# resolve mob_recon first and only fall back to the import.
# mobsuite_db_complete DIR -- 0 when DIR holds a finished MOB-suite database.
mobsuite_db_complete() {
    local dir="$1" f
    [[ -n "$dir" && -d "$dir" ]] || return 1
    for f in status.txt ncbi_plasmid_full_seqs.fas ncbi_plasmid_full_seqs.fas.msh repetitive.dna.fas; do
        [[ -s "$dir/$f" ]] || return 1
    done
}

# mobsuite_db_preserve -- keep MOB-suite's database in the machine-wide store
# ($PLASBENCH_DB_DIR/mob_suite/databases) and make the environment's folder a link
# to it, so rebuilding or replacing the conda environment never loses it.
#   * env has a database, store has none: move it to the store (same disk: a rename),
#     then link the env folder to the store;
#   * env has none, store has one: set the env's empty folder aside and link;
#   * both, or already linked: nothing.
# Nothing is deleted: a folder set aside keeps its contents under *.pre-store.
mobsuite_db_preserve() {
    # PLASBENCH_DB_PRESERVE=0 (the test suite) never moves or links a real database.
    [[ "${PLASBENCH_DB_PRESERVE:-1}" == "0" ]] && return 0
    local env_db store="${PLASBENCH_DB_DIR:-$HOME/.plasbench/databases}/mob_suite/databases"
    env_db="$(mobsuite_db_dir)"
    [[ -n "$env_db" ]] || return 0
    if [[ -L "$env_db" ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$store")"
    if mobsuite_db_complete "$env_db" && ! mobsuite_db_complete "$store"; then
        if [[ -e "$store" ]]; then mv "$store" "$store.incomplete.$(date +%s)"; fi
        mv "$env_db" "$store" && ln -s "$store" "$env_db" \
            && log "  MOB-suite database moved to the machine store: $store (linked from the environment)"
    elif mobsuite_db_complete "$store"; then
        mv "$env_db" "$env_db.pre-store.$(date +%s)" && ln -s "$store" "$env_db" \
            && log "  MOB-suite environment linked to the stored database: $store"
    fi
    return 0
}

# --- resumable downloads (same approach as GenoSuv's BaseSpace transfers) ------
# net_online HOST: can a TCP connection to HOST:443 be opened? Cheap, no download.
net_online() {
    local host="$1"
    [[ "${PLASBENCH_ASSUME_ONLINE:-0}" == "1" ]] && return 0   # tests
    timeout "${PLASBENCH_ONLINE_TIMEOUT:-5}" bash -c ">/dev/tcp/$host/443" 2>/dev/null
}

# wait_online HOST: when the connection is down, pause (log once, poll every
# PLASBENCH_ONLINE_POLL seconds) instead of spending retries; continue as soon
# as it is back. Gives up after PLASBENCH_OFFLINE_MAX_MINUTES (default 120).
wait_online() {
    local host="$1" waited=0 poll="${PLASBENCH_ONLINE_POLL:-30}"
    local max=$(( ${PLASBENCH_OFFLINE_MAX_MINUTES:-120} * 60 ))
    net_online "$host" && return 0
    log "  internet is down ($host unreachable): download paused, will continue when it is back"
    while ! net_online "$host"; do
        (( waited >= max )) && return 1
        sleep "$poll"; waited=$(( waited + poll ))
    done
    log "  internet is back: download resumed"
}

# url_needs_internet URL: 0 unless URL is a local file or points at this computer (a mirror on disk or a test server needs no internet).
url_needs_internet() {
    case "$1" in
        file://*|/*|http://localhost*|http://127.*|https://localhost*|https://127.*|http://\[::1\]*) return 1 ;;
    esac
    return 0
}

# require_internet [--any] [--warn] [--action TEXT] [--hint TEXT] SERVICE...
# Stop (die) before any work when an online-only step cannot reach SERVICE (names are in config/network_services.tsv: github, ncbi,
# ncbi_datasets, sra, ena, pypi, conda, zenodo, plsdb, ...). One plain sentence says which service and why (no network at all, DNS
# not working, one service down, a sign-in page in the way). --any accepts one reachable service out of several; --warn prints the
# sentence and returns 1 instead of stopping. Honours PLASBENCH_ASSUME_ONLINE=1 (no probing: tests, air-gapped mirrors), PLASBENCH_OFFLINE=1
# (refuse at once) and PLASBENCH_ONLINE_TIMEOUT. Call it only on the path that really fetches: an action that can be done from files
# already on disk must not demand the internet. Uses plasbench/netcheck.py when python3 is present, else a TCP probe of the catalogue hosts.
require_internet() {
    local any=() warn_only=0 action="" hint="" services=() root msg="" rc=0 svc host bad=() ok=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --any) any=(--any) ;;
            --warn) warn_only=1 ;;
            --action) action="$2"; shift ;;
            --hint) hint="$2"; shift ;;
            *) services+=("$1") ;;
        esac
        shift
    done
    [[ "${PLASBENCH_ASSUME_ONLINE:-0}" == "1" ]] && return 0
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    if command -v python3 >/dev/null 2>&1 && [[ -f "$root/plasbench/netcheck.py" ]]; then
        msg="$(python3 -I "$root/plasbench/netcheck.py" require "${any[@]}" --action "$action" --hint "$hint" "${services[@]}" 2>&1)" || rc=$?
        [[ "$rc" -eq 0 ]] && return 0
        if [[ "$rc" -eq 3 ]]; then
            msg="${msg#ERROR: }"
            if [[ "$warn_only" -eq 1 ]]; then warn "$msg"; return 1; fi
            die "$msg"
        fi
        msg=""    # python itself failed: fall back to the plain probe below
    fi
    if [[ "${PLASBENCH_OFFLINE:-0}" == "1" ]]; then
        msg="${action:-This action} needs the internet (PLASBENCH_OFFLINE=1 is set). Online-only actions are switched off on purpose; unset PLASBENCH_OFFLINE to go online again. ${hint}"
    else
        for svc in "${services[@]}"; do
            host="$(awk -F'\t' -v s="$svc" 'NR > 1 && $1 == s { n = split($4, a, ","); print a[1]; exit }' "$root/config/network_services.tsv" 2>/dev/null || true)"
            [[ -n "$host" ]] || continue
            if net_online "$host"; then ok=$(( ok + 1 )); else bad+=("$host"); fi
        done
        if [[ ${#bad[@]} -gt 0 && ( ${#any[@]} -eq 0 || "$ok" -eq 0 ) ]]; then
            if net_online 1.1.1.1 && ! getent hosts "${bad[0]}" >/dev/null 2>&1; then
                msg="${action:-This action} needs the internet (${bad[0]} unreachable: DNS failure). DNS is not working; in WSL try wsl --shutdown in PowerShell, check the VPN, or set a DNS server. ${hint}"
            else
                msg="${action:-This action} needs the internet (${bad[*]} unreachable). Check the connection, VPN or proxy and try again. ${hint}"
            fi
        fi
    fi
    [[ -z "$msg" ]] && return 0
    if [[ "$warn_only" -eq 1 ]]; then warn "$msg"; return 1; fi
    die "$msg"
}

# download_pin LABEL URL: print the SHA-256 that config/download_checksums.tsv (override: PLASBENCH_DOWNLOAD_CHECKSUMS) pins for LABEL, or nothing.
# A registry row applies to its own URL only (a custom URL gets no pin); a row with an empty url applies to any URL. Rows with status other than
# "pinned", or a sha256 that is not 64 hex characters, give no pin (AU-026).
download_pin() {
    local label="$1" url="${2:-}" registry="${PLASBENCH_DOWNLOAD_CHECKSUMS:-${PROJECT_ROOT:-.}/config/download_checksums.tsv}"
    [[ -f "$registry" ]] || return 0
    awk -F'\t' -v label="$label" -v url="$url" '
        NR > 1 && $1 == label && $5 == "pinned" && length($3) == 64 && $3 ~ /^[0-9A-Fa-f]+$/ && ($2 == "" || $2 == url) { print tolower($3); exit }' "$registry"
}

# verify_or_record_download FILE URL LABEL [EXPECTED_SHA256] [PROVENANCE_FILE]
# Supply-chain check for a downloaded database or archive. Where a SHA-256 is configured, a mismatch fails (returns 1; the caller deletes the file).
# EXPECTED_SHA256 defaults to the pin in config/download_checksums.tsv (see download_pin); PLASBENCH_REQUIRE_CHECKSUMS=1 refuses a download with no pin.
# Where none is configured, the observed checksum is printed with an explicit notice and appended as one JSON line to PROVENANCE_FILE
# (default: download_provenance.jsonl next to FILE), so the run can be traced to the exact bytes that were installed. Never fails on a missing pin.
verify_or_record_download() {
    local file="$1" url="$2" label="$3" want="${4:-}" prov="${5:-$(dirname "$1")/download_provenance.jsonl}" got verified=false
    if have sha256sum; then got="$(sha256sum "$file" | awk '{print $1}')"
    elif have shasum; then got="$(shasum -a 256 "$file" | awk '{print $1}')"
    else got="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$file" 2>/dev/null || true)"; fi
    [[ -n "$got" ]] || { warn "$label: no SHA-256 tool found; the download could not be checksummed"; return 0; }
    [[ -n "$want" ]] || want="$(download_pin "$label" "$url")"
    if [[ -z "$want" && "${PLASBENCH_REQUIRE_CHECKSUMS:-0}" == "1" ]]; then
        warn "$label: no SHA-256 is pinned (environment variable or config/download_checksums.tsv) and PLASBENCH_REQUIRE_CHECKSUMS=1; refusing it. Observed SHA-256: $got"
        return 1
    fi
    if [[ -n "$want" ]]; then
        if [[ "$got" != "$(printf '%s' "$want" | tr 'A-F' 'a-f')" ]]; then
            warn "$label: SHA-256 $got does not match the pinned $want"
            return 1
        fi
        verified=true
        log "$label: SHA-256 verified ($got)"
    else
        warn "NOTICE: no SHA-256 is pinned for the $label download, so it could not be verified. Observed SHA-256: $got (recorded in $prov). Pin it to make a later install fail on a changed file."
    fi
    mkdir -p "$(dirname "$prov")" 2>/dev/null || true
    printf '{"label": "%s", "url": "%s", "file": "%s", "downloaded_utc": "%s", "sha256": "%s", "sha256_verified": %s}\n' \
        "$label" "$url" "$(basename "$file")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$got" "$verified" >> "$prov" 2>/dev/null || true
    return 0
}

# resumable_download URL DEST [EXPECTED_BYTES]
# Downloads to DEST.part and keeps every byte already received: a dropped
# connection, a closed laptop or a later re-run continues where it stopped
# (curl -C -), never from zero. Retries with back-off, pauses while offline,
# checks the size (EXPECTED_BYTES, else the server's Content-Length) and only
# then renames DEST.part to DEST. A finished DEST is not downloaded again.
resumable_download() {
    local url="$1" dest="$2" want="${3:-}" part="$2.part" host attempt max got
    host="$(printf '%s' "$url" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
    max="${PLASBENCH_DOWNLOAD_ATTEMPTS:-30}"
    mkdir -p "$(dirname "$dest")"
    if [[ -z "$want" ]]; then
        want="$(curl -sSIL --max-time 30 "$url" 2>/dev/null | tr -d '\r' \
                | awk 'tolower($1)=="content-length:"{n=$2} END{print n}')" || want=""
    fi
    if [[ -s "$dest" ]] && { [[ -z "$want" ]] || [[ "$(stat -c %s "$dest")" == "$want" ]]; }; then
        log "  already downloaded: $dest"; return 0
    fi
    for (( attempt = 1; attempt <= max; attempt++ )); do
        wait_online "$host" || { warn "still offline after ${PLASBENCH_OFFLINE_MAX_MINUTES:-120} min; the partial file is kept: $part"; return 1; }
        got="$( [[ -f "$part" ]] && stat -c %s "$part" || echo 0)"
        if [[ -n "$want" && "$got" -gt "$want" ]]; then
            warn "  partial file is larger than the source ($got > $want bytes); starting it again"
            rm -f "$part"; got=0
        fi
        if (( got > 0 )); then
            local total="unknown size"
            [[ -n "$want" ]] && total="$(( want / 1048576 )) MB"
            log "  resuming at $(( got / 1048576 )) MB of $total (attempt $attempt/$max)"
        fi
        if curl -fL -C - --connect-timeout 30 --speed-limit 1024 --speed-time 120 \
               -o "$part" "$url"; then
            got="$(stat -c %s "$part")"
            if [[ -z "$want" || "$got" == "$want" ]]; then
                mv -f "$part" "$dest"
                log "  download complete: $dest ($(( got / 1048576 )) MB)"
                return 0
            fi
            warn "  download ended at $got of $want bytes; continuing"
        else
            local rc=$?
            # 33 = the server refused the range (a stale partial file): start over once.
            [[ "$rc" -eq 33 ]] && { warn "  server could not resume this file; starting it again"; rm -f "$part"; }
            local wait=$(( attempt * 15 )); (( wait > 300 )) && wait=300
            warn "  download interrupted (curl exit $rc); keeping $(( $( [[ -f "$part" ]] && stat -c %s "$part" || echo 0) / 1048576 )) MB, retrying in ${wait}s"
            sleep "${PLASBENCH_RETRY_SLEEP:-$wait}"
        fi
    done
    warn "download did not finish after $max attempts; the partial file is kept, re-run to continue: $part"
    return 1
}

# mobsuite_env_root: the conda environment that holds MOB-suite (follows the
# mob_recon wrapper), or nothing.
mobsuite_env_root() {
    local exe target
    exe="$(command -v mob_recon 2>/dev/null || true)"
    [[ -n "$exe" ]] || return 0
    target="$(grep -o "/[^\"]*/bin/mob_recon" "$exe" 2>/dev/null | head -1 || true)"
    [[ -n "$target" ]] && exe="$target"
    (cd "$(dirname "$exe")/.." 2>/dev/null && pwd) || true
}

mobsuite_db_dir() {
    local exe target env_root candidate found
    exe="$(command -v mob_recon 2>/dev/null || true)"
    if [[ -n "$exe" ]]; then
        # A shim names the real interpreter path inside it; follow that.
        target="$(grep -o "/[^\"]*/bin/mob_recon" "$exe" 2>/dev/null | head -1 || true)"
        [[ -n "$target" ]] && exe="$target"
        if env_root="$(cd "$(dirname "$exe")/.." 2>/dev/null && pwd)"; then
            # conda-forge adds lib/python3.1 -> python3.10 as an alias; it sorts
            # first and made messages show ".../python3.1/..." paths. Skip
            # aliases and directories without a real mob_suite package.
            for candidate in "$env_root"/lib/python*/site-packages/mob_suite/databases; do
                [[ -L "${candidate%/site-packages/*}" ]] && continue
                [[ -f "$(dirname "$candidate")/__init__.py" ]] || continue
                [[ -s "$candidate/status.txt" ]] && { printf %s "$candidate"; return 0; }
            done
            for candidate in "$env_root"/lib/python*/site-packages/mob_suite/databases; do
                [[ -L "${candidate%/site-packages/*}" ]] && continue
                [[ -f "$(dirname "$candidate")/__init__.py" ]] || continue
                [[ -d "$candidate" ]] && { printf %s "$candidate"; return 0; }
            done
        fi
    fi
    found="$(python3 -c 'import os,mob_suite; print(os.path.join(os.path.dirname(os.path.abspath(mob_suite.__file__)),"databases"))' 2>/dev/null || true)"
    [[ -n "$found" && -d "$found" ]] && printf %s "$found"
    return 0
}

# --- never stop silently ------------------------------------------------------------------------------------------
# A stage that stops on an unexpected failure (set -e), or is stopped by a signal (Ctrl+C, a closed terminal, the
# window's Cancel, the system), says so on the console in red: which script, which command, the exit code and what
# it usually means. The same line goes to logs/run_errors.log. SIGKILL (out of memory) cannot be caught by the process
# it kills, so run_all.sh, the plasbench command and the window report it from outside. PLASBENCH_NO_TRAPS=1 disables
# this (for scripts that install their own).
explain_exit() {
    local code="$1"
    case "$code" in
        0) echo "finished" ;;
        1) echo "a command reported an error" ;;
        2) echo "a command was given a wrong option or a missing file" ;;
        4) echo "every tool run of stage 4 failed (nothing was produced to score)" ;;
        20) echo "a manual installation step is needed (nothing failed; the notice above lists the steps)" ;;
        124) echo "a time limit was reached" ;;
        126) echo "a program could not be run (permissions)" ;;
        127) echo "a program was not found (not installed, or not on PATH)" ;;
        129) echo "stopped (SIGHUP): the terminal was closed" ;;
        130) echo "stopped with Ctrl+C" ;;
        134) echo "aborted (SIGABRT): the program crashed" ;;
        137) echo "killed (SIGKILL): usually out of memory, or WSL or the system ended it" ;;
        139) echo "crashed (segmentation fault)" ;;
        143) echo "stopped (SIGTERM): cancelled, or the system asked it to stop" ;;
        *) if [[ "$code" =~ ^[0-9]+$ ]] && (( code > 128 )); then echo "stopped by signal $(( code - 128 ))";
           else echo "failed with exit code $code"; fi ;;
    esac
}

_plasbench_record_error() {
    local line="$1"
    printf '%s%s%s\n' "${_C_ERR:-}" "$line" "${_C_OFF:-}" >&2
    if [[ -n "${LOG_DIR:-}" ]]; then
        { mkdir -p "$LOG_DIR" && printf '%s\n' "$line" >> "$LOG_DIR/run_errors.log"; } 2>/dev/null || true
    fi
}

_plasbench_on_err() {
    local code=$? cmd="$BASH_COMMAND" src="${BASH_SOURCE[1]:-$0}" lineno="${BASH_LINENO[0]:-?}"
    [[ $- == *e* ]] || return 0                 # only when set -e is about to stop the script
    [[ "${_PLASBENCH_ERR_REPORTED:-0}" == "1" ]] && return 0
    _PLASBENCH_ERR_REPORTED=1
    _plasbench_record_error "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $(basename "$0") stopped: \`${cmd}\` failed, $(explain_exit "$code") (exit $code, ${src##*/} line $lineno)"
}

# Every process below $1, children first. Uses ps (procps); where ps cannot report parents (Git Bash), nothing is returned and the caller
# falls back to this shell's own job list.
_plasbench_descendants() {
    local parent="$1" child
    for child in $(ps -eo pid=,ppid= 2>/dev/null | awk -v p="$parent" '$2 == p { print $1 }'); do
        _plasbench_descendants "$child"
        printf '%s\n' "$child"
    done
}

# Stop every process this script started (the tool, its wrapper, the profiler, a heartbeat) so Ctrl+C or a scheduler cancel does not leave a
# tool running with nothing watching it. TERM first, then KILL for anything still alive after a few seconds.
_plasbench_stop_children() {
    local pids p waited=0 alive
    pids="$(_plasbench_descendants "$$")"
    [[ -n "$pids" ]] || pids="$(jobs -p 2>/dev/null)"
    [[ -n "$pids" ]] || return 0
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true
    while (( waited < 5 )); do
        alive=0
        for p in $pids; do kill -0 "$p" 2>/dev/null && alive=1; done
        (( alive )) || return 0
        sleep 1; waited=$(( waited + 1 ))
    done
    # shellcheck disable=SC2086
    kill -KILL $pids 2>/dev/null || true
}

_plasbench_on_signal() {
    local sig="$1" code="$2"
    trap - "$sig"
    _plasbench_record_error "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $(basename "$0") $(explain_exit "$code")"
    _plasbench_stop_children
    exit "$code"
}

if [[ "${PLASBENCH_NO_TRAPS:-0}" != "1" ]]; then
    set -o errtrace                               # the ERR trap also covers functions and subshells
    trap '_plasbench_on_err' ERR
    trap '_plasbench_on_signal INT 130' INT
    trap '_plasbench_on_signal TERM 143' TERM
    trap '_plasbench_on_signal HUP 129' HUP
fi
