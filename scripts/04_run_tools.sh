#!/usr/bin/env bash
# Stage 4 — run each enabled plasmid-reconstruction tool on the sample, then
# use its adapter to write a standardized predicted-plasmid FASTA:
#     results/<sample>/pred_<tool>.plasmid.fasta
#
# Parallelism (see config/config.sh): MAX_PARALLEL_SAMPLES runs several
# samples' tool sets at once; MAX_PARALLEL_TOOLS runs mob_recon, platon,
# plasmidspades, and gplas2_external for the SAME sample concurrently, since
# they are independent given the same assembly. gplas2_mob is the one
# exception -- it needs MOB-recon's own membership output as its classifier
# seed -- so it always waits for that sample's mob_recon to finish first,
# however many tool slots are configured. Both default to 1, which is
# exactly today's one-sample-at-a-time, one-tool-at-a-time behavior.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
ADAPT="$HERE/../adapters"
# Pre-registration gate (python/freeze_prereg.py): with REQUIRE_PREREG=1 no tool
# runs until config/prereg.lock.json matches config/prereg.tsv, no parameter is
# TO_FIX, and no config variable departs from its pre-registered value.
if [[ "${REQUIRE_PREREG:-0}" == "1" ]]; then
    python3 "$HERE/../python/freeze_prereg.py" --verify --require-fixed --check-env \
        --prereg "${PREREG_FILE:-$HERE/../config/prereg.tsv}" --lock "${PREREG_LOCK:-$HERE/../config/prereg.lock.json}" \
        || die "pre-registration check failed (REQUIRE_PREREG=1); freeze it with: plasbench analysis freeze-prereg --write"
fi
STATUS="$RESULTS_DIR/tool_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
reset_shard_dir "run_tools"
STATUS_SHARDS="$(shard_dir "run_tools")"
reset_shard_dir "run_tools_outcomes"
OUTCOME_SHARDS="$(shard_dir "run_tools_outcomes")"
OUTCOMES="$RESULTS_DIR/tool_outcomes.tsv"

# Every (sample, tool) pair gets record_status called at most once per run,
# into its own uniquely-named file, so this needs no locking even when many
# samples/tools write concurrently: no two processes ever target the same
# path. The final status file is assembled once, after every job finishes,
# in a fixed sample x tool order -- so its row order matches a sequential
# run's exactly, however the parallel jobs actually interleaved.
record_status() {
    local sample="$1" tool="$2" reason="$5" rss="${7:-}"
    [[ -z "$rss" && -n "${6:-}" ]] && rss="$(profile_rss "${PROFILE_RSS_FILE:-}")"
    # A failed run's exit code goes into the free-text reason, not a new column:
    # tool_status.tsv has other readers (and contribution files that must keep a
    # matching header), so its schema stays fixed. aggregate_results.py reads
    # "exit_code=<n>" back to tell a timeout/OOM kill (124/137) from a tool that
    # simply failed.
    local status="$3" exit_code="" failure_class="" attempts=1
    if [[ "$status" == "reused" || "$status" == "skipped" ]]; then
        attempts=0
    elif [[ -s "$LOG_DIR/${sample}.${tool}.attempts" ]]; then
        attempts="$(tr -d '[:space:]' < "$LOG_DIR/${sample}.${tool}.attempts")"
    fi
    if [[ "$status" == "failed" && -s "$LOG_DIR/${sample}.${tool}.exit" ]]; then
        exit_code="$(tr -d '[:space:]' < "$LOG_DIR/${sample}.${tool}.exit")"
        reason="${reason:+$reason; }exit_code=$exit_code"
    fi
    if [[ "$status" == "failed" ]]; then
        failure_class="$(classify_failure "$exit_code" "$LOG_DIR/${sample}.${tool}.log")"
        # Outcome states (scoring specification WP4): an infrastructure failure
        # (container/command could not start, disk full) says nothing about the
        # tool; it is recorded as its own status, never scored, and rerun later.
        if [[ "$failure_class" == "infrastructure" ]]; then
            status="infrastructure_failure"
            reason="${reason:+$reason; }infrastructure failure: rerun, not scored"
        fi
        [[ "$attempts" -gt 1 ]] && reason="${reason:+$reason; }attempts=$attempts"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$status" "$4" "$reason" "${6:-}" "$rss" \
        > "$STATUS_SHARDS/${sample}.${tool}.tsv"
    # Side table with explicit columns (tool_status.tsv keeps its fixed schema
    # for contribution files): sample, tool, status, exit_code, failure_class, attempts.
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$status" "$exit_code" "$failure_class" "$attempts" \
        > "$OUTCOME_SHARDS/${sample}.${tool}.tsv"
}

# resource (124 timeout, 137 SIGKILL/OOM), infrastructure (125/126/127: the
# container or command could not start; or the log shows the disk filled), else tool.
classify_failure() {
    local code="$1" log_file="$2"
    case "$code" in
        124|137) echo "resource"; return ;;
        125|126|127) echo "infrastructure"; return ;;
    esac
    # Ran out of memory without the kernel's SIGKILL (exit 137): SPAdes/mimalloc
    # "Cannot allocate memory", C++ std::bad_alloc, Python MemoryError. Like a
    # timeout, that says the machine was too small, not that the tool is wrong.
    if [[ -s "$log_file" ]] && grep -qiE "cannot allocate memory|unable to allocate (os )?memory|std::bad_alloc|MemoryError|out of memory" "$log_file"; then
        echo "resource"; return
    fi
    # A tool that cannot even start (missing or incompatible Python dependency)
    # is an installation fault, not the tool's result: never scored, rerun after fixing.
    if [[ -s "$log_file" ]] && grep -qiE "no space left on device|disk quota exceeded|cannot connect to the docker daemon|ImportError|ModuleNotFoundError|cannot import name|No module named" "$log_file"; then
        echo "infrastructure"; return
    fi
    echo "tool"
}

# Same wall-time budget for every tool (TOOL_TIMEOUT_SECONDS; blank = none) and
# TOOL_RETRIES automatic retries of a failed run. A timeout (124) or OOM kill
# (137) is not retried: the same budget would fail the same way.
with_budget() {
    if [[ -n "${TOOL_TIMEOUT_SECONDS:-}" ]] && command -v timeout >/dev/null 2>&1; then
        timeout "$TOOL_TIMEOUT_SECONDS" "$@"
    else
        "$@"
    fi
}
retry_exec() {
    local attempts_file="$LOG_DIR/${SAMPLE}.${TOOL}.attempts" attempt=1 rc=0
    local max=$(( 1 + ${TOOL_RETRIES:-1} ))
    while true; do
        rc=0
        "$@" || rc=$?
        printf '%s\n' "$attempt" > "$attempts_file"
        if [[ "$rc" -eq 0 || "$rc" -eq 124 || "$rc" -eq 137 || "$attempt" -ge "$max" ]]; then
            return "$rc"
        fi
        warn "$SAMPLE / $TOOL failed (exit $rc); retry $attempt of $(( max - 1 ))"
        attempt=$(( attempt + 1 ))
    done
}

profile_start() { date +%s; }
profile_elapsed() { printf '%s' "$(( $(date +%s) - $1 ))"; }
# /usr/bin/time writes 'maxrss user_cpu system_cpu' on its LAST line (a failed run adds a status line
# before it); the memory figure is the first field, the CPU seconds are read by performance_summary.py.
profile_rss() { [[ -s "$1" ]] && awk 'END{printf "%s", $1}' "$1" || true; }
profile_exec() {
    PROFILE_RSS_FILE="$LOG_DIR/${SAMPLE}.${TOOL}.rss"; rm -f "$PROFILE_RSS_FILE"
    local exit_file="$LOG_DIR/${SAMPLE}.${TOOL}.exit" rc=0; rm -f "$exit_file" "$LOG_DIR/${SAMPLE}.${TOOL}.attempts"
    if [[ -x /usr/bin/time ]]; then retry_exec run_with_heartbeat "$SAMPLE / $TOOL" with_budget /usr/bin/time -f '%M %U %S' -o "$PROFILE_RSS_FILE" "$@" || rc=$?; else retry_exec run_with_heartbeat "$SAMPLE / $TOOL" with_budget "$@" || rc=$?; fi
    printf '%s\n' "$rc" > "$exit_file"
    return "$rc"
}
profile_exec_in_dir() {
    local run_dir="$1"; shift
    PROFILE_RSS_FILE="$LOG_DIR/${SAMPLE}.${TOOL}.rss"; rm -f "$PROFILE_RSS_FILE"
    local exit_file="$LOG_DIR/${SAMPLE}.${TOOL}.exit" rc=0; rm -f "$exit_file" "$LOG_DIR/${SAMPLE}.${TOOL}.attempts"
    if [[ -x /usr/bin/time ]]; then retry_exec run_with_heartbeat "$SAMPLE / $TOOL" with_budget bash -c 'cd "$1" && /usr/bin/time -f "%M %U %S" -o "$2" "${@:3}"' _ "$run_dir" "$PROFILE_RSS_FILE" "$@" || rc=$?; else retry_exec run_with_heartbeat "$SAMPLE / $TOOL" with_budget bash -c 'cd "$1" && "${@:2}"' _ "$run_dir" "$@" || rc=$?; fi
    printf '%s\n' "$rc" > "$exit_file"
    return "$rc"
}

# -------- result reuse --------
# A finished tool run leaves .<tool>.complete holding a FINGERPRINT of everything
# that decides its output: the PlasBench version and adapter, the tool's installed
# executable (path, size, mtime; never run to ask), its database registry row, its <TOOL>_* settings (thread
# counts excluded: they do not change results) and the input files. A later run
# reuses the result only when the fingerprint is unchanged, so upgrading a tool or
# its database, changing a parameter or re-assembling re-runs that tool instead of
# silently reusing stale predictions. Bash dynamic scoping: TOOL, CONTIGS and the
# optional T1, T2, OUTFILE, CLASSIFIER are the caller's (run_<tool>) locals.
declare -A TOOL_EXECUTABLE=(
    [mob_recon]=mob_recon [gplas2_mob]=gplas [gplas2_external]=gplas [platon]=platon
    [plasmidspades]=plasmidspades.py [genomad]=genomad [plasme]=PLASMe.py [rfplasmid]=rfplasmid
    [plasmidhunter]=plasmidhunter [plasmer]=Plasmer [plascope]=plaScope.sh
    [plasgraph2]=plASgraph2_classify.py
)
# Identity of a tool's executable without running it: resolved path, size and
# modification time. Upgrading or reinstalling a tool rewrites its entry point (conda
# and pip regenerate the console-script shim), so this changes with the installed
# version. Running `<tool> --version` instead would execute every tool before deciding
# whether to run it, and a tool that does not parse that flag could start a real run.
# The exact version strings are recorded separately in the run manifest.
executable_identity() {
    local exe="$1" path
    [[ -n "$exe" ]] || { printf 'none'; return; }
    path="$(command -v "$exe" 2>/dev/null)" || { printf 'unavailable'; return; }
    path="$(readlink -f "$path" 2>/dev/null || printf '%s' "$path")"
    printf '%s %s' "$path" "$(stat -c '%s:%Y' "$path" 2>/dev/null || printf 'unknown')"
}

file_digest() {
    [[ -n "${1:-}" && -f "$1" ]] || { printf 'none'; return; }
    sha256sum "$1" | cut -d' ' -f1
}

tool_fingerprint() {
    local upper exe adapter params
    upper="$(printf '%s' "$TOOL" | tr '[:lower:]' '[:upper:]')"
    exe="${TOOL_EXECUTABLE[$TOOL]:-}"
    [[ "$TOOL" == "plsmd" ]] && exe="${PLSMD_CMD:-}"
    case "$TOOL" in
        baseline_*) adapter="$PROJECT_ROOT/python/baseline_predictors.py" ;;
        gplas2_*) adapter="$PROJECT_ROOT/adapters/adapt_gplas.sh" ;;
        *) adapter="$PROJECT_ROOT/adapters/adapt_${TOOL}.sh" ;;
    esac
    # `|| true`: a tool with no <TOOL>_* settings makes grep exit 1, which under
    # `set -euo pipefail` must not abort the stage.
    params="$( { env | grep "^${upper}_" | grep -v "^${upper}_THREADS=" | LC_ALL=C sort | tr '\n' ';'; } || true)"
    printf 'plasbench_fingerprint=1\n'
    printf 'tool=%s\n' "$TOOL"
    printf 'plasbench=%s\n' "$(sed -n 's/^__version__ *= *["'"'"']\([^"'"'"']*\).*/\1/p' "$PROJECT_ROOT/plasbench/__init__.py" 2>/dev/null)"
    printf 'adapter=%s\n' "$(file_digest "$adapter")"
    printf 'executable=%s %s\n' "${exe:-none}" "$(executable_identity "$exe")"
    printf 'database=%s\n' "$(awk -F'\t' -v t="$TOOL" '$1 == t {print $2 "|" $3 "|" $4}' \
        "$PROJECT_ROOT/config/tool_database_releases.tsv" 2>/dev/null)"
    printf 'params=%s\n' "$params"
    printf 'contigs=%s\n' "$(file_digest "${CONTIGS:-}")"
    printf 'outfile=%s\n' "$(file_digest "${OUTFILE:-}")"
    printf 'classifier=%s\n' "$(file_digest "${CLASSIFIER:-}")"
    local reads="" r
    for r in "${T1:-}" "${T2:-}"; do
        [[ -n "$r" && -f "$r" ]] && reads+="$(stat -c '%s:%Y' "$r");"
    done
    printf 'reads=%s\n' "$reads"
}

is_complete() {
    [[ -e "$1" && -f "$2" && "${FORCE_RERUN_TOOLS:-0}" -ne 1 ]] || return 1
    if [[ ! -s "$1" ]]; then
        # Marker from a release before fingerprints: its inputs cannot be checked.
        if [[ "${REUSE_UNFINGERPRINTED:-0}" -eq 1 ]]; then
            warn "  $TOOL: reusing a result with no fingerprint (REUSE_UNFINGERPRINTED=1); its inputs were not checked"
            return 0
        fi
        log "  $TOOL: earlier result has no fingerprint; re-running (REUSE_UNFINGERPRINTED=1 reuses it unchecked)"
        return 1
    fi
    if [[ "$(cat "$1")" == "$(tool_fingerprint)" ]]; then
        return 0
    fi
    log "  $TOOL: version, database, parameters or inputs changed since the last run; re-running"
    return 1
}

# Record a finished run (replaces a bare `touch` of the marker).
mark_complete() {
    tool_fingerprint > "$1"
}

# When ONLY_TOOL is unset (the default), behaves exactly like the plain
# `[[ "${!flag_var:-0}" -eq 1 ]]` check every tool block used before: nothing
# about a normal benchmark run changes. When ONLY_TOOL is set (an operational
# reconstruction run), it overrides every RUN_* flag and restricts execution
# to that one named tool, independent of whatever RUN_* flags happen to be
# configured -- except gplas2_mob, which cannot run without MOB-recon's
# membership output as its classifier seed, so requesting it also enables
# mob_recon as a silent prerequisite.
tool_enabled() {
    local flag_var="$1" tool_name="$2"
    if [[ -n "${ONLY_TOOL:-}" ]]; then
        case "$tool_name" in
            mob_recon) [[ "$ONLY_TOOL" == "mob_recon" || "$ONLY_TOOL" == "gplas2_mob" ]] ;;
            *) [[ "$ONLY_TOOL" == "$tool_name" ]] ;;
        esac
    else
        [[ "${!flag_var:-0}" -eq 1 ]]
    fi
}

# -------- one tool, one sample: each of these becomes an independent
# background job when MAX_PARALLEL_TOOLS > 1, so every variable it uses is
# either a parameter or something it sets itself -- nothing shared with a
# sibling tool's job for the same sample. --------

run_mob_recon() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_MOB_RECON mob_recon && have mob_recon; then
        local TOOL="mob_recon" OUT="$RDIR/mob_recon" PRED="$RDIR/pred_mob_recon.plasmid.fasta" DONE="$RDIR/.mob_recon.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  mob_recon: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  mob_recon ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec mob_recon --infile "$CONTIGS" --outdir "$OUT" --num_threads "$MOB_RECON_THREADS" --force > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_mob_recon.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "mob_recon failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_MOB_RECON mob_recon; then
        warn "mob_recon is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "mob_recon" "skipped" "" "command unavailable"
    fi
}

run_gplas2_mob() {
    local SAMPLE="$1" SDIR="$2" RDIR="$3" CONTIGS="$4"
    if tool_enabled RUN_GPLAS2_MOB gplas2_mob && have gplas; then
        local TOOL="gplas2_mob" OUT="$RDIR/gplas2_mob" PRED="$RDIR/pred_gplas2_mob.plasmid.fasta" DONE="$RDIR/.gplas2_mob.complete"
        local GRAPH="$SDIR/assembly_graph.gfa" MOB_OUT="$RDIR/mob_recon"
        local CLASSIFIER="$OUT/${SAMPLE}.mob_classifier.tsv" PROVENANCE="$OUT/${SAMPLE}.mob_classifier.provenance.json"
        if is_complete "$DONE" "$PRED"; then
            log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -s "$GRAPH" ]]; then
            warn "  $TOOL needs an assembly graph; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly graph unavailable"
        elif [[ ! -d "$MOB_OUT" ]]; then
            warn "  $TOOL requires successful mob_recon output; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "MOB-recon output unavailable"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"; log "  $TOOL ($SAMPLE, MOB hard-label seeds) ..."
            local START; START=$(profile_start)
            if python3 "$HERE/../python/mob_to_gplas_classifier.py" --graph "$GRAPH" --mob-output "$MOB_OUT" \
                --out "$CLASSIFIER" --provenance "$PROVENANCE" --min-contig-length "$GPLAS2_MIN_CONTIG_LENGTH" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                profile_exec_in_dir "$OUT" gplas -i "$GRAPH" -P "$CLASSIFIER" -n "$SAMPLE" >> "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_gplas.sh" "$OUT/results" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "MOB hard-label classifier provenance: $PROVENANCE" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_GPLAS2_MOB gplas2_mob; then
        warn "gplas2_mob is enabled but gplas is not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "gplas2_mob" "skipped" "" "command unavailable"
    fi
}

# Trivial baselines (python/baseline_predictors.py): reference points every
# tool should beat. Exit status 3 means "cannot apply to this input" (no
# depth in contig headers / no plasmid reference set built) and is recorded
# as skipped, never as a failed run that would be scored zero.
run_baseline() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3" TOOL="$4" FLAG="$5"
    tool_enabled "$FLAG" "$TOOL" || return 0
    local PRED="$RDIR/pred_${TOOL}.plasmid.fasta" DONE="$RDIR/.${TOOL}.complete"
    if is_complete "$DONE" "$PRED"; then
        log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        return 0
    fi
    rm -f "$PRED" "$DONE" "$RDIR/pred_${TOOL}.bins.tsv" "$RDIR/pred_${TOOL}.candidates.fasta" "$RDIR/pred_${TOOL}.scores.tsv"
    local ARGS=()
    if [[ "$TOOL" == "baseline_coverage" ]]; then
        ARGS=(coverage --contigs "$CONTIGS" --out-prefix "$RDIR/pred_${TOOL}"
              --ratio "$BASELINE_COVERAGE_RATIO" --min-length "$BASELINE_MIN_CONTIG_LENGTH")
    elif [[ "$TOOL" == "baseline_replicon" ]]; then
        # Replicon-seeded baseline (plsMD's enumeration idea): contigs carrying a replicon marker. The markers come from
        # Abricate databases named in REPLICON_ABRICATE_DBS (default plasmidfinder; add a second, for example a
        # rep.mob.typer database built from MOB-suite's rep.dna.fas, by listing it too). Missing Abricate or database
        # means not applicable, never a failure.
        if ! have abricate; then
            record_status "$SAMPLE" "$TOOL" "skipped" "" "abricate not installed"
            return 0
        fi
        local HITS="$RDIR/${TOOL}.replicon_hits.tsv" db first=1
        : > "$HITS"
        for db in $REPLICON_ABRICATE_DBS; do
            if abricate --db "$db" --threads "$THREADS" "$CONTIGS" > "$HITS.tmp" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                if [[ "$first" -eq 1 ]]; then cat "$HITS.tmp" >> "$HITS"; first=0; else tail -n +2 "$HITS.tmp" >> "$HITS"; fi
            else
                warn "abricate database '$db' failed for $SAMPLE; the replicon baseline uses the others"
            fi
            rm -f "$HITS.tmp"
        done
        ARGS=(replicon --contigs "$CONTIGS" --replicon-hits "$HITS" --out-prefix "$RDIR/pred_${TOOL}"
              --min-length "$BASELINE_MIN_CONTIG_LENGTH")
    else
        if [[ ! -s "$PLASMID_REFERENCE_FASTA" ]]; then
            record_status "$SAMPLE" "$TOOL" "skipped" "" "plasmid reference set not built (build_plasmid_reference_set.py)"
            return 0
        fi
        ARGS=(reference --contigs "$CONTIGS" --reference "$PLASMID_REFERENCE_FASTA" --out-prefix "$RDIR/pred_${TOOL}"
              --min-query-coverage "$BASELINE_REFERENCE_MIN_QUERY_COVERAGE" --threads "$THREADS")
    fi
    log "  $TOOL ($SAMPLE) ..."
    local START; START=$(profile_start)
    local status=0
    python3 "$HERE/../python/baseline_predictors.py" "${ARGS[@]}" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 || status=$?
    if [[ "$status" -eq 0 ]]; then
        mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "trivial baseline" "$(profile_elapsed "$START")"
    elif [[ "$status" -eq 3 ]]; then
        rm -f "$PRED"; record_status "$SAMPLE" "$TOOL" "skipped" "" "baseline not applicable: see $LOG_DIR/${SAMPLE}.${TOOL}.log"
    else
        rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE"
        record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
    fi
}

# plsMD (reference-guided reconstruction against PLSDB; see adapters/REGISTRY.md). It reads a Unicycler assembly
# (circular= and depth= headers) and a PLSDB BLAST index, in two steps: --preprocessing then --processing. The
# reconstructed plasmids are plasmid_files/<sample>_plasmid_contigs.fasta in the processing output directory.
# Skipped, with the reason recorded, when the command, the database or a Unicycler assembly is missing: a missing
# prerequisite is not the tool's failure.
run_plsmd() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLSMD plsmd; then
        local TOOL="plsmd" OUT="$RDIR/plsmd" PRED="$RDIR/pred_plsmd.plasmid.fasta" DONE="$RDIR/.plsmd.complete"
        if ! have "$PLSMD_CMD"; then
            warn "plsmd is enabled but '$PLSMD_CMD' is not installed; skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "command unavailable"
        elif [[ -z "${PLSMD_DB:-}" ]]; then
            warn "plsmd needs PLSMD_DB (the PLSDB BLAST index prefix); skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "PLSMD_DB not set"
        elif [[ "${ASSEMBLER:-spades}" != "unicycler" ]]; then
            warn "plsmd needs a Unicycler assembly (ASSEMBLER=unicycler); skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly is not from Unicycler (set ASSEMBLER=unicycler)"
        elif is_complete "$DONE" "$PRED"; then
            log "  plsmd: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT/input"
            cp "$CONTIGS" "$OUT/input/${SAMPLE}.fasta"
            log "  plsmd ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec "$PLSMD_CMD" --preprocessing --input fasta --dir "$OUT/input" --output "$OUT/preprocessing" --threads "$PLSMD_THREADS" --db "$PLSMD_DB" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                profile_exec "$PLSMD_CMD" --processing --dir "$OUT/preprocessing" --output "$OUT/processing" >> "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plsmd.sh" "$OUT/processing" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "database: $PLSMD_DB" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plsmd failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    fi
}

# PlasBin-flow (flow-based MILP binning of an assembly graph). It needs a Gurobi licence, a gzipped GFA with dp or KC tags,
# a contig plasmid-score file and a GC-probability file, so PlasBench does not run it: like gplas2_external it adapts the
# tool's own output. PLASBIN_FLOW_OUTPUTS_DIR/<sample>.tsv is the output of `plasbin_flow.py -outfile`, produced from the SAME
# assembly. A missing directory or file is a skip with the reason recorded; ids that do not belong to this assembly are
# also a skip (an incompatible input is not the tool's failure and is never relabelled).
run_plasbin_flow() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    tool_enabled RUN_PLASBIN_FLOW plasbin_flow || return 0
    local TOOL="plasbin_flow" PRED="$RDIR/pred_plasbin_flow.plasmid.fasta" DONE="$RDIR/.plasbin_flow.complete"
    local OUTFILE="${PLASBIN_FLOW_OUTPUTS_DIR:-}/${SAMPLE}.tsv"
    if [[ -z "${PLASBIN_FLOW_OUTPUTS_DIR:-}" ]]; then
        record_status "$SAMPLE" "$TOOL" "skipped" "" "PLASBIN_FLOW_OUTPUTS_DIR not set"
    elif [[ ! -f "$OUTFILE" ]]; then
        record_status "$SAMPLE" "$TOOL" "skipped" "" "PlasBin-flow output not found: $OUTFILE"
    elif is_complete "$DONE" "$PRED"; then
        log "  plasbin_flow: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
    else
        rm -f "$PRED" "$DONE" "$RDIR/pred_plasbin_flow.bins.tsv"
        log "  plasbin_flow ($SAMPLE) ..."
        local START; START=$(profile_start)
        if bash "$ADAPT/adapt_plasbin_flow.sh" "$OUTFILE" "$CONTIGS" "$PRED" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1; then
            mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "PlasBin-flow output: $OUTFILE" "$(profile_elapsed "$START")"
        else
            rm -f "$PRED" "$DONE"; warn "plasbin_flow output does not match the assembly of $SAMPLE; skipped"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "PlasBin-flow output unusable for this assembly: see $LOG_DIR/${SAMPLE}.${TOOL}.log"
        fi
    fi
}

run_platon() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLATON platon && have platon; then
        local TOOL="platon" OUT="$RDIR/platon" PRED="$RDIR/pred_platon.plasmid.fasta" DONE="$RDIR/.platon.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  platon: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"
            log "  platon ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec platon --db "$PLATON_DB" --threads "$PLATON_THREADS" --output "$OUT" --prefix "$SAMPLE" "$CONTIGS" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_platon.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "platon failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLATON platon; then
        warn "platon is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "platon" "skipped" "" "command unavailable"
    fi
}

run_plasmidspades() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3" T1="$4" T2="$5"
    if tool_enabled RUN_PLASMIDSPADES plasmidspades && have plasmidspades.py; then
        local TOOL="plasmidspades" OUT="$RDIR/plasmidspades" PRED="$RDIR/pred_plasmidspades.plasmid.fasta" DONE="$RDIR/.plasmidspades.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  plasmidSPAdes: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  plasmidSPAdes ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec plasmidspades.py -1 "$T1" -2 "$T2" -o "$OUT" --threads "$PLASMIDSPADES_THREADS" --memory "$PLASMIDSPADES_MEMORY_GB" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasmidspades.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasmidSPAdes failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASMIDSPADES plasmidspades; then
        warn "plasmidSPAdes is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "plasmidspades" "skipped" "" "command unavailable"
    fi
}

run_gplas2_external() {
    local SAMPLE="$1" SDIR="$2" RDIR="$3" CONTIGS="$4"
    if tool_enabled RUN_GPLAS2_EXTERNAL gplas2_external && have gplas; then
        local TOOL="gplas2_external" OUT="$RDIR/gplas2_external" PRED="$RDIR/pred_gplas2_external.plasmid.fasta" DONE="$RDIR/.gplas2_external.complete"
        local GRAPH="$SDIR/assembly_graph.gfa"
        local CLASSIFIER="${GPLAS2_EXTERNAL_PREDICTIONS_DIR:-}/$SAMPLE.tsv"
        if is_complete "$DONE" "$PRED"; then
            log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -s "$GRAPH" ]]; then
            warn "  $TOOL needs an assembly graph; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly graph unavailable"
        elif [[ ! -s "$CLASSIFIER" ]]; then
            warn "  $TOOL prediction table missing: $CLASSIFIER"; record_status "$SAMPLE" "$TOOL" "skipped" "" "external classifier TSV unavailable"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; log "  $TOOL ($SAMPLE) ..."
            local START; START=$(profile_start)
            if python3 "$HERE/../python/validate_gplas_classifier.py" --graph "$GRAPH" --classifier "$CLASSIFIER" --min-contig-length "$GPLAS2_MIN_CONTIG_LENGTH" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                profile_exec_in_dir "$OUT" gplas -i "$GRAPH" -P "$CLASSIFIER" -n "$SAMPLE" >> "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_gplas.sh" "$OUT/results" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "external classifier TSV: $CLASSIFIER" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_GPLAS2_EXTERNAL gplas2_external; then
        warn "gplas2_external is enabled but gplas is not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "gplas2_external" "skipped" "" "command unavailable"
    fi
}

run_genomad() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_GENOMAD genomad && have genomad; then
        local TOOL="genomad" OUT="$RDIR/genomad" PRED="$RDIR/pred_genomad.plasmid.fasta" DONE="$RDIR/.genomad.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  genomad: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  genomad ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec genomad end-to-end --threads "$GENOMAD_THREADS" "$CONTIGS" "$OUT" "$GENOMAD_DB/genomad_db" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_genomad.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "genomad failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_GENOMAD genomad; then
        warn "genomad is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "genomad" "skipped" "" "command unavailable"
    fi
}

run_plasme() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLASME plasme && have PLASMe.py; then
        local TOOL="plasme" OUT="$RDIR/plasme" PRED="$RDIR/pred_plasme.plasmid.fasta" DONE="$RDIR/.plasme.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  plasme: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"
            log "  plasme ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec PLASMe.py "$CONTIGS" "$OUT/plasme_output.fasta" -d "$PLASME_DB" \
                    -p "$PLASME_PROBABILITY" -t "$PLASME_THREADS" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasme.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasme failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASME plasme; then
        warn "plasme is enabled but PLASMe.py is not installed (or not on PATH); skipped for $SAMPLE"
        record_status "$SAMPLE" "plasme" "skipped" "" "command unavailable"
    fi
}

run_rfplasmid() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_RFPLASMID rfplasmid && have rfplasmid; then
        local TOOL="rfplasmid" OUT="$RDIR/rfplasmid" PRED="$RDIR/pred_rfplasmid.plasmid.fasta" DONE="$RDIR/.rfplasmid.complete"
        local STAGE="$RDIR/rfplasmid_input"
        if is_complete "$DONE" "$PRED"; then
            log "  rfplasmid: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            # RFPlasmid takes a DIRECTORY of *.fasta files as --input (not a
            # single file, unlike geNomad/PLASMe), and auto-appends a
            # timestamp to --out if that path already exists -- so OUT must
            # NOT exist yet when rfplasmid runs (it creates it itself), and
            # this sample's contigs are staged alone so RFPlasmid's own
            # internal genome/contig numbering stays this-sample-only.
            rm -rf "$OUT" "$PRED" "$DONE" "$STAGE"; mkdir -p "$STAGE"
            cp "$CONTIGS" "$STAGE/${SAMPLE}.fasta"
            log "  rfplasmid ($SAMPLE) ..."
            local START; START=$(profile_start)
            local jelly_flag=(); [[ "$RFPLASMID_JELLY" == "1" ]] && jelly_flag=(--jelly)
            if profile_exec rfplasmid --species "$RFPLASMID_SPECIES" --input "$STAGE" --out "$OUT" \
                    --threads "$RFPLASMID_THREADS" "${jelly_flag[@]}" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_rfplasmid.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "rfplasmid failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
            rm -rf "$STAGE"
        fi
    elif tool_enabled RUN_RFPLASMID rfplasmid; then
        warn "rfplasmid is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "rfplasmid" "skipped" "" "command unavailable"
    fi
}

run_plasmidhunter() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLASMIDHUNTER plasmidhunter && have plasmidhunter; then
        local TOOL="plasmidhunter" OUT="$RDIR/plasmidhunter" PRED="$RDIR/pred_plasmidhunter.plasmid.fasta" DONE="$RDIR/.plasmidhunter.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  plasmidhunter: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            # plasmidhunter errors if -o already exists, like PLASMe/RFPlasmid.
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  plasmidhunter ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec plasmidhunter -i "$CONTIGS" -o "$OUT" -c "$PLASMIDHUNTER_THREADS" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasmidhunter.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasmidhunter failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASMIDHUNTER plasmidhunter; then
        warn "plasmidhunter is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "plasmidhunter" "skipped" "" "command unavailable"
    fi
}

run_plasmer() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLASMER plasmer && have Plasmer; then
        local TOOL="plasmer" OUT="$RDIR/plasmer" PRED="$RDIR/pred_plasmer.plasmid.fasta" DONE="$RDIR/.plasmer.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  plasmer: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -d "$PLASMER_DB" ]]; then
            warn "  $TOOL has no database at $PLASMER_DB; skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "no Plasmer database at $PLASMER_DB"
        else
            # Unlike PLASMe/RFPlasmid/PlasmidHunter, real Plasmer does not
            # error on an existing -o directory (a plain mkdir, no set -e in
            # its own driver script) -- but this project still removes it
            # first for a clean, idempotent rerun, since a stale
            # intermediate/ left over from a different sample could
            # otherwise leak into this one's outputs.
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  plasmer ($SAMPLE) ..."
            local START; START=$(profile_start)
            if profile_exec Plasmer -g "$CONTIGS" -p "$SAMPLE" -d "$PLASMER_DB" -t "$PLASMER_THREADS" \
                    -m "$PLASMER_MIN_LENGTH" -l "$PLASMER_LENGTH" -o "$OUT" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasmer.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "database: $PLASMER_DB" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasmer failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASMER plasmer; then
        warn "plasmer is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "plasmer" "skipped" "" "command unavailable"
    fi
}

run_plascope() {
    local SAMPLE="$1" RDIR="$2" CONTIGS="$3"
    if tool_enabled RUN_PLASCOPE plascope && have plaScope.sh; then
        local TOOL="plascope" OUT="$RDIR/plascope" PRED="$RDIR/pred_plascope.plasmid.fasta" DONE="$RDIR/.plascope.complete"
        # PlaScope needs a species-specific Centrifuge database; only E. coli
        # and Klebsiella pre-built databases exist (see config/config.sh), so
        # every other organism is a structural, not a tool-install, gap.
        local organism; organism="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" organism)"
        local db=""
        case "$organism" in
            "Escherichia coli"*) db="$PLASCOPE_ECOLI_DB" ;;
            "Klebsiella"*) db="$PLASCOPE_KLEBSIELLA_DB" ;;
        esac
        if is_complete "$DONE" "$PRED"; then
            log "  plascope: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ -z "$db" ]]; then
            warn "  $TOOL has no database for organism '${organism:-not_recorded}'; skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "no PlaScope database for organism ${organism:-not_recorded}"
        else
            # plaScope.sh errors out if <out>/<sample>_PlaScope/{PlaScope_predictions,
            # Centrifuge_results} already exist -- OUT must not exist yet; it
            # creates the whole tree itself.
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  plascope ($SAMPLE, organism=$organism) ..."
            local START; START=$(profile_start)
            if profile_exec plaScope.sh --fasta "$CONTIGS" -a "$ASSEMBLER" -o "$OUT" --sample "$SAMPLE" \
                    --db_dir "$(dirname "$db")" --db_name "$(basename "$db")" -t "$PLASCOPE_THREADS" \
                    > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plascope.sh" "$OUT/${SAMPLE}_PlaScope" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "database: $db" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASCOPE plascope; then
        warn "plascope is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "plascope" "skipped" "" "command unavailable"
    fi
}

run_plasgraph2() {
    local SAMPLE="$1" SDIR="$2" RDIR="$3" CONTIGS="$4"
    if tool_enabled RUN_PLASGRAPH2 plasgraph2 && have plASgraph2_classify.py; then
        local TOOL="plasgraph2" OUT="$RDIR/plasgraph2" PRED="$RDIR/pred_plasgraph2.plasmid.fasta" DONE="$RDIR/.plasgraph2.complete"
        local GRAPH="$SDIR/assembly_graph.gfa"
        if is_complete "$DONE" "$PRED"; then
            log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -s "$GRAPH" ]]; then
            warn "  $TOOL needs an assembly graph; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly graph unavailable"
        elif [[ -z "$PLASGRAPH2_MODEL_DIR" ]]; then
            warn "  $TOOL needs PLASGRAPH2_MODEL_DIR set to a pretrained model directory; skipped for $SAMPLE"
            record_status "$SAMPLE" "$TOOL" "skipped" "" "PLASGRAPH2_MODEL_DIR not set"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"
            log "  $TOOL ($SAMPLE) ..."
            local START; START=$(profile_start)
            # plASgraph2 requires a gzipped GFA (its own examples/docs never
            # show a plain .gfa input); the pipeline's own graph is plain, so
            # gzip a copy into this tool's own output directory.
            local GRAPH_GZ="$OUT/assembly_graph.gfa.gz" CSV="$OUT/${SAMPLE}_output.csv"
            gzip -c "$GRAPH" > "$GRAPH_GZ"
            [[ "$PLASGRAPH2_CPU_ONLY" == "1" ]] && export CUDA_VISIBLE_DEVICES=""
            if profile_exec plASgraph2_classify.py gfa "$GRAPH_GZ" "$PLASGRAPH2_MODEL_DIR" "$CSV" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasgraph2.sh" "$CSV" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                mark_complete "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASGRAPH2 plasgraph2; then
        warn "plasgraph2 is enabled but plASgraph2_classify.py is not installed (or not on PATH); skipped for $SAMPLE"
        record_status "$SAMPLE" "plasgraph2" "skipped" "" "command unavailable"
    fi
}

# One sample's whole tool set. mob_recon, platon, plasmidspades, and
# gplas2_external are independent given the same assembly, so they are
# always launched through the same MAX_PARALLEL_TOOLS-gated job pool
# regardless of its value -- at MAX_PARALLEL_TOOLS=1 that pool serializes
# them one at a time (today's behavior, just not in today's exact order,
# which does not matter: none of them depend on another's output). Only
# gplas2_mob is order-sensitive, so it explicitly waits for this sample's own
# mob_recon job before it is even launched into the pool.
process_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    local RDIR="$RESULTS_DIR/$SAMPLE"; mkdir -p "$RDIR"
    local CONTIGS="$SDIR/contigs.fasta"
    local T1="$SDIR/${SRA}_1.trim.fastq.gz" T2="$SDIR/${SRA}_2.trim.fastq.gz"
    if [[ ! -s "$CONTIGS" ]]; then
        warn "no contigs for $SAMPLE; run 03_assemble.sh"
        tool_enabled RUN_MOB_RECON mob_recon && record_status "$SAMPLE" "mob_recon" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLATON platon && record_status "$SAMPLE" "platon" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASMIDSPADES plasmidspades && record_status "$SAMPLE" "plasmidspades" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_GPLAS2_MOB gplas2_mob && record_status "$SAMPLE" "gplas2_mob" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_GPLAS2_EXTERNAL gplas2_external && record_status "$SAMPLE" "gplas2_external" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_GENOMAD genomad && record_status "$SAMPLE" "genomad" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASME plasme && record_status "$SAMPLE" "plasme" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_RFPLASMID rfplasmid && record_status "$SAMPLE" "rfplasmid" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASMIDHUNTER plasmidhunter && record_status "$SAMPLE" "plasmidhunter" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASMER plasmer && record_status "$SAMPLE" "plasmer" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASCOPE plascope && record_status "$SAMPLE" "plascope" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_PLASGRAPH2 plasgraph2 && record_status "$SAMPLE" "plasgraph2" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_BASELINE_COVERAGE baseline_coverage && record_status "$SAMPLE" "baseline_coverage" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_BASELINE_REFERENCE baseline_reference && record_status "$SAMPLE" "baseline_reference" "skipped" "" "assembly contigs unavailable"
        tool_enabled RUN_BASELINE_REPLICON baseline_replicon && record_status "$SAMPLE" "baseline_replicon" "skipped" "" "assembly contigs unavailable"
        return 0
    fi
    log "=== Run tools on $SAMPLE ==="

    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_mob_recon "$SAMPLE" "$RDIR" "$CONTIGS" &
    local mob_recon_pid=$!
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_platon "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plsmd "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasbin_flow "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasmidspades "$SAMPLE" "$RDIR" "$CONTIGS" "$T1" "$T2" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_gplas2_external "$SAMPLE" "$SDIR" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_genomad "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasme "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_rfplasmid "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasmidhunter "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasmer "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plascope "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasgraph2 "$SAMPLE" "$SDIR" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_baseline "$SAMPLE" "$RDIR" "$CONTIGS" baseline_coverage RUN_BASELINE_COVERAGE &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_baseline "$SAMPLE" "$RDIR" "$CONTIGS" baseline_reference RUN_BASELINE_REFERENCE &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_baseline "$SAMPLE" "$RDIR" "$CONTIGS" baseline_replicon RUN_BASELINE_REPLICON &

    # gplas2_mob's classifier seed comes straight from mob_recon's own output
    # directory, so it must not start until that finished (successfully or
    # not -- run_gplas2_mob itself checks for the output it needs).
    wait "$mob_recon_pid" 2>/dev/null || true
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_gplas2_mob "$SAMPLE" "$SDIR" "$RDIR" "$CONTIGS" &

    wait
}

warn_resource_oversubscription "stage 4 (reconstruction)" "$(( MAX_PARALLEL_SAMPLES * MAX_PARALLEL_TOOLS ))" \
    "$(( (MOB_RECON_THREADS>PLATON_THREADS?MOB_RECON_THREADS:PLATON_THREADS)>PLASMIDSPADES_THREADS ? (MOB_RECON_THREADS>PLATON_THREADS?MOB_RECON_THREADS:PLATON_THREADS) : PLASMIDSPADES_THREADS ))" \
    "$PLASMIDSPADES_MEMORY_GB"
# Plasmer's real, documented kmer-db RAM floor is a fixed cost per
# concurrent job, unrelated to its own thread count -- checked separately
# from the general reconstruction-stage warning above, and only when it is
# actually enabled.
if [[ "${RUN_PLASMER:-0}" -eq 1 ]]; then
    warn_resource_oversubscription "stage 4 (plasmer)" "$(( MAX_PARALLEL_SAMPLES * MAX_PARALLEL_TOOLS ))" "$PLASMER_THREADS" "$PLASMER_MEMORY_GB"
fi

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    job_slot_wait "$MAX_PARALLEL_SAMPLES"
    process_sample "$SAMPLE" "$ASM" "$SRA" &
done < <(read_samples "$SAMPLE_SHEET")
wait

# Assemble the final status file once, in the same sample x tool order a
# sequential run would have produced it in.
shards=()
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    for tool in mob_recon gplas2_mob platon plasmidspades gplas2_external genomad plasme rfplasmid plasmidhunter plasmer plascope plasgraph2 baseline_coverage baseline_reference plsmd baseline_replicon plasbin_flow; do
        shards+=("$STATUS_SHARDS/${SAMPLE}.${tool}.tsv")
    done
done < <(read_samples "$SAMPLE_SHEET")
merge_shards "$STATUS" "$(printf 'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb')" "${shards[@]}"
outcome_shards=("${shards[@]/#$STATUS_SHARDS/$OUTCOME_SHARDS}")
merge_shards "$OUTCOMES" "$(printf 'sample\ttool\tstatus\texit_code\tfailure_class\tattempts')" "${outcome_shards[@]}"
rm -rf "$STATUS_SHARDS" "$OUTCOME_SHARDS"

log "Stage 4 (run tools) complete."
