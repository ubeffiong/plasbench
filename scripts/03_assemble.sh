#!/usr/bin/env bash
# Stage 3 — per sample: quality-trim reads (fastp) and assemble them
# (SPAdes/Unicycler) into the base contig set that the classification tools use.
#
# Failure policy: a sample whose trimming or assembly fails is recorded in
# results/assembly_status.tsv as "failed" and the run continues with the
# remaining samples. This matches stage 4, which records a failing tool and
# carries on rather than discarding every other sample's completed work -- a
# single unassemblable isolate (too deep for the available RAM, truncated
# reads, a withdrawn run) should not void a whole cohort. Stage 4 already marks
# every enabled tool "skipped" for a sample with no contigs, so a failed
# assembly propagates through scoring and aggregation as an explicit, visible
# absence rather than a silently missing row. The run aborts only when no
# sample assembled at all, since there is then nothing to benchmark.
#
# Short-read QC (SHORT_READ_QC_MODE, default report): before fastp, python/short_read_qc.py measures the raw read pair and decides
# PASS, WARN or REJECT. enforce excludes a REJECT from assembly, the tools and the primary benchmark (status `rejected`); an
# integrity failure (unreadable, truncated, empty, malformed or unequal files) is always excluded. The policy is explained in
# FAQ Q33; the pre-registered thresholds are in config/short_read_qc_thresholds.tsv.
#
# Parallelism (config/config.sh: MAX_PARALLEL_SAMPLES): SPAdes/Unicycler are
# memory-hungry, unlike stage 1's network-bound downloads, so raise this more
# conservatively here -- warn_resource_oversubscription below checks the
# requested concurrency against detected RAM (ASSEMBLY_MEMORY_GB per job) as
# well as CPU threads, but it only warns; it never lowers your setting for
# you.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need fastp
stage_timing_begin 3        # stage_start/stage_end events, so `plasbench status` knows this is stage 3
preflight_resources 3 quiet
warn_resource_oversubscription "stage 3 (assembly)" "$MAX_PARALLEL_SAMPLES" "$THREADS" "$ASSEMBLY_MEMORY_GB"

STATUS="$RESULTS_DIR/assembly_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
reset_shard_dir "assemble"
STATUS_SHARDS="$(shard_dir "assemble")"
# Short-read QC gate (python/short_read_qc.py): one row per sample, merged into results/short_read_qc.tsv at the end.
reset_shard_dir "readqc"
QC_SHARDS="$(shard_dir "readqc")"
SHORT_READ_QC_MODE="${SHORT_READ_QC_MODE:-report}"
# Assembly selection (python/assembly_selection.py): one row per candidate assembly, merged into results/assembly_candidates.tsv.
reset_shard_dir "asmsel"
ASM_SHARDS="$(shard_dir "asmsel")"
ASSEMBLY_SELECTION_MODE="${ASSEMBLY_SELECTION_MODE:-report}"

# Every sample gets record_assembly_status called at most once per run, into
# its own uniquely-named file, so this needs no locking even when several
# assemblies run concurrently: no two processes ever target the same path. The
# final status file is assembled once, after every job finishes, in sample
# order -- so its row order matches a sequential run's exactly, however the
# parallel jobs actually interleaved.
record_assembly_status() {
    local sample="$1"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" "${7:-}" "${ASM_MEM_USED:-}" "${ASM_NEEDED_GB:-}" "${ASM_ATTEMPTS:-}" "${ASM_MODE:-}" \
        > "$STATUS_SHARDS/${sample}.tsv"
    run_event assembly_end "sample=$1" "status=$2" "reason=${4:-}" "cause=${6:-}"
    run_event sample_end "sample=$1" "step=assembly" "status=$2"
}

# --- why a step failed, what was tried, and when to stop ------------------------------------------------------------------------------
# Columns 6 and 7 of assembly_status.tsv (cause, advice) come from python/assembler_diagnosis.py, which reads the tool's log. A cause that belongs to the
# computer (a full disk, a broken Python, a CPU feature) would repeat for every sample, so the stage stops at the first one instead of spending minutes
# on each (exit 5). Out of memory gets ONE retry with fewer threads and a budget that fits the memory free now (ASSEMBLER_AUTO_RETRY=0 turns it off).
# Print one block, record the failure, and ask the stage to stop when the cause is the computer's (or STOP_EARLY=1 from the caller).
handle_step_failure() {   # handle_step_failure TOOL SAMPLE LOG START [NOTE]
    local tool="$1" sample="$2" log="$3" start="$4" note="${5:-}"
    warn "$tool failed for $sample: $DIAG_TITLE ($DIAG_EVIDENCE). What to do: $DIAG_ADVICE${note:+ $note} Log: $log. $sample is excluded from tool runs and scoring."
    record_assembly_status "$sample" "failed" "" "$tool: $DIAG_CAUSE ($DIAG_EVIDENCE)" "$(( $(date +%s) - start ))" "$DIAG_CAUSE" "$DIAG_ADVICE${note:+ $note}"
    run_event assembly_failed "sample=$sample" "tool=$tool" "cause=$DIAG_CAUSE" "confidence=$DIAG_CONFIDENCE"
    if [[ "$DIAG_ENV" == "1" || "${STOP_EARLY:-0}" == "1" ]]; then
        printf '%s\t%s\t%s\n' "$DIAG_CAUSE" "$sample" "$DIAG_TITLE" > "$STATUS_SHARDS/.stop"
    fi
}

# After a read-related failure: test the raw reads (gzip, and downloads.sha256 when there is one) and the trimmed copy. Sets READS_NOTE. Never retries.
verify_reads() {   # verify_reads SDIR R1 R2 T1 T2
    local sdir="$1" r1="$2" r2="$3" t1="$4" t2="$5" f bad=() tbad=0
    READS_NOTE=""
    for f in "$r1" "$r2"; do gzip -t "$f" 2>/dev/null || bad+=("$f"); done
    if [[ ${#bad[@]} -eq 0 && -s "$sdir/downloads.sha256" ]] && ! (cd "$sdir" && sha256sum --quiet -c downloads.sha256 > /dev/null 2>&1); then
        bad+=("a file listed in $sdir/downloads.sha256")
    fi
    for f in "$t1" "$t2"; do if [[ -e "$f" ]] && ! gzip -t "$f" 2>/dev/null; then tbad=1; fi; done
    if [[ ${#bad[@]} -gt 0 ]]; then
        READS_NOTE="Checked: the downloaded reads are damaged (${bad[*]}). Re-download: rm -f \"$r1\" \"$r2\" \"$sdir/downloads.sha256\" then run the same plasbench run command again; stage 1 fetches them afresh and finished work is reused."
        rm -f "$t1" "$t2" "$sdir/.fastp.complete"
    elif [[ "$tbad" -eq 1 ]]; then
        READS_NOTE="Checked: the downloaded reads are intact but the trimmed copy was damaged; it was removed, so run the same plasbench run command again to trim afresh."
        rm -f "$t1" "$t2" "$sdir/.fastp.complete"
    else
        READS_NOTE="Checked: the downloaded reads pass the gzip and checksum tests, so the download is not the problem."
    fi
}

# ---- assembly work folder (WORK_DIR, python/work_dir.py) -----------------------------------------------------------------------------------
# SPAdes writes tens of thousands of small files; on a Windows drive seen from WSL (9p), NTFS/exFAT, a network share or a cloud-synced folder that is hundreds of times
# slower than on a local disk. When the data folder is on such a mount the assembler works in a scratch folder (~/.plasbench/scratch/<study>/<sample>.<pid>) and only the
# finished results are moved back, atomically. WORK_DIR=data turns it off; WORK_DIR=<folder> chooses one. Prints the scratch folder, or nothing (and returns 1) when the
# assembly runs in the data folder. Leftovers of runs that died are removed here, with a log line.
assembly_scratch_dir() {   # assembly_scratch_dir SAMPLE T1 T2
    local sample="$1" t1="$2" t2="$3" study line dir reason fs kind need name bytes=0 f
    have python3 || return 1
    for f in "$t1" "$t2"; do bytes=$(( bytes + $(stat -c %s "$f" 2>/dev/null || stat -f %z "$f" 2>/dev/null || echo 0) )); done
    need="$(awk -v b="$bytes" 'BEGIN { printf "%.1f", b * 8 / 1e9 + 2 }')"
    study="$(basename "$(dirname "${RESULTS_DIR:-./results}")")"
    line="$(python3 -I "${PROJECT_ROOT:-.}/python/work_dir.py" resolve --data-dir "$DATA_DIR" --study "$study" --mode "${WORK_DIR:-auto}" --need-gb "$need" 2>/dev/null </dev/null)" || return 1
    IFS=$'\t' read -r dir reason fs kind <<< "$line"
    if [[ "$kind" != "scratch" ]]; then
        heartbeat_log "  assembly work folder: $DATA_DIR/$sample ($reason)"
        return 1
    fi
    mkdir -p "$dir" 2>/dev/null || { heartbeat_log "  assembly work folder: $dir cannot be created; working in the data folder"; return 1; }
    while IFS= read -r name; do
        [[ -n "$name" ]] && heartbeat_log "  removed a leftover scratch folder from an earlier run: $dir/$name"
    done < <(python3 -I "${PROJECT_ROOT:-.}/python/work_dir.py" clean --root "$dir" 2>/dev/null </dev/null)
    mkdir -p "$dir/$sample.$$" || return 1
    heartbeat_log "  assembly work folder: $dir/$sample.$$ (fast local disk; $reason; results are copied back to $DATA_DIR/$sample when done)"
    run_event work_dir "sample=$sample" "dir=$dir" "fs=$fs"
    printf '%s' "$dir/$sample.$$"
}

assembly_scratch_finish() {   # assembly_scratch_finish SCRATCH OUT ASMDIR: move the results back (atomic), say how much
    local scratch="$1" out="$2" asmdir="$3" moved
    moved="$(python3 -I "${PROJECT_ROOT:-.}/python/work_dir.py" finish --src "$out" --dst "$asmdir" 2>&1 </dev/null)" || { warn "could not move the assembly back from $scratch to $asmdir: $moved"; return 1; }
    heartbeat_log "  assembly results moved back from the scratch folder: $moved"
    return 0
}

# SPAdes with diagnosis and at most ONE automatic adjustment-and-retry. Returns 0 when it assembled (ASM_RETRY_NOTE says what was changed), 1 when it failed or was skipped (recorded).
# AUTO_RESOURCES (default 1) is the adaptive part: the memory budget starts from what is free; when SPAdes says what it needs ("You need approx. X GB of free RAM") the isolate is
# retried ONCE with -m = ceil(X * 1.15 + 0.5) when that fits in the free memory (else the bare need, rounded up, when that fits in 92%); the need is remembered per isolate
# (results/assembly_memory.d, keyed by a checksum of the reads) so a resume starts at the right budget without the failing attempt; when it does not fit, THIS isolate is skipped
# with the exact need and the others continue (or, only with ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1, SPAdes --only-assembler is tried, recorded as a different mode).
# Sets ASM_MEM_USED, ASM_NEEDED_GB, ASM_ATTEMPTS and ASM_MODE for assembly_status.tsv.
run_spades_checked() {   # run_spades_checked SAMPLE T1 T2 ASMDIR START R1 R2 SDIR
    local sample="$1" t1="$2" t2="$3" asmdir="$4" start="$5" r1="$6" r2="$7" sdir="$8"
    local log="$LOG_DIR/${sample}.spades.log" threads="$THREADS" mem="$ASSEMBLY_MEMORY_GB" rc attempt=1 plan="" note="" first="" own="" nm avail
    local verdict vact vmem vmsg STOP_EARLY=0 MEMORY_REFUSAL="" out="$asmdir" scratch="" sig="" known="" needed="" mode="spades" opt=() auto="${AUTO_RESOURCES:-1}" memdir="$RESULTS_DIR" free_now=""
    ASM_RETRY_NOTE=""
    rm -f "$RESULTS_DIR/resource_state.d/spades.$sample.txt"
    ASM_MEM_USED="" ASM_NEEDED_GB="" ASM_ATTEMPTS="" ASM_MODE=""
    # --- remembered need: start at the right budget, do not repeat the failing attempt ---
    if [[ "$auto" == "1" ]] && have python3; then
        sig="$(python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" sig --r1 "$r1" --r2 "$r2" 2>/dev/null </dev/null || true)"
        [[ -n "$sig" ]] && known="$(python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" lookup --dir "$memdir" --sample "$sample" --sig "$sig" 2>/dev/null </dev/null || true)"
        if [[ -n "$known" && "$known" != "none" ]]; then
            read -r needed nm own _ <<< "$known"        # needed_gb, budget_gb, mode
            own="${own:-spades}"; free_now="$(python3 -I "${PROJECT_ROOT:-.}/python/preflight_resources.py" available 2>/dev/null </dev/null || true)"
            if [[ "$needed" != "0.000" && "$needed" != "0" ]]; then
                plan="$(python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" plan --need "$needed" ${free_now:+--available-gb "$free_now"} 2>/dev/null </dev/null || true)"
                if [[ "${plan%% *}" =~ ^[0-9]+$ ]]; then
                    if [[ "${plan%% *}" -gt "$mem" ]]; then
                        log "  SPAdes needs about $(awk -v n="$needed" 'BEGIN { printf "%.1f", n }') GB for this isolate (remembered from an earlier attempt); starting with a memory budget of ${plan%% *} GB instead of $mem GB (${free_now:-?} GB are free)"
                        run_event resource_adjust "sample=$sample" "what=memory" "from=$mem" "to=${plan%% *}" "needed=$needed" "why=remembered"
                        mem="${plan%% *}"
                    fi
                    [[ "$own" == "only-assembler" && "${ASSEMBLER_ALLOW_ONLY_ASSEMBLER:-0}" == "1" ]] && { opt=(--only-assembler); mode="only-assembler"; }
                elif [[ "${ASSEMBLER_ALLOW_ONLY_ASSEMBLER:-0}" == "1" ]]; then
                    opt=(--only-assembler); mode="only-assembler"
                    log "  SPAdes needs about $needed GB for this isolate and ${free_now:-?} GB are free: using --only-assembler (ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1; a different assembly mode, recorded)"
                else
                    memory_skip "$sample" "$needed" "${free_now:-?}" "$start" "remembered"
                    return 1
                fi
            fi
        fi
    fi
    scratch="$(assembly_scratch_dir "$sample" "$t1" "$t2")" || scratch=""
    [[ -n "$scratch" ]] && out="$scratch/asm"
    while :; do
        rc=0
        WATCH_LOG="$log" run_with_heartbeat "$SAMPLE / SPAdes assembly" spades.py -1 "$t1" -2 "$t2" -o "$out" \
            --threads "$threads" --memory "$mem" ${opt[@]+"${opt[@]}"} > "$log" 2>&1 || rc=$?
        if [[ "$rc" -eq 0 ]]; then
            [[ -n "$note" ]] && ASM_RETRY_NOTE="retried once after $first: $note"
            if [[ -n "$scratch" ]] && ! assembly_scratch_finish "$scratch" "$out" "$asmdir"; then
                record_assembly_status "$sample" "failed" "" "SPAdes: the finished assembly could not be moved back from the scratch folder $scratch (see the message above; the scratch folder is kept)" "$(( $(date +%s) - start ))" "scratch_move_failed" "Free space where the data folder is, or set WORK_DIR=data, then run the same plasbench run command again."
                return 1
            fi
            [[ -n "$scratch" ]] && rm -rf "$scratch"
            ASM_MEM_USED="$mem" ASM_NEEDED_GB="$needed" ASM_ATTEMPTS="$attempt" ASM_MODE="$mode"
            [[ -n "$sig" && "$auto" == "1" && ( -n "$needed" || "$mode" != "spades" ) ]] && python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" record --dir "$memdir" --sample "$sample" --sig "$sig" \
                --needed "${needed:-0}" --budget "$mem" --attempts "$attempt" --mode "$mode" --status completed 2>/dev/null </dev/null || true
            return 0
        fi
        # keep what the failed attempt left (spades.log, params.txt) in the isolate's folder for inspection, as before, then clear the scratch folder
        if [[ -n "$scratch" ]]; then assembly_scratch_finish "$scratch" "$out" "$asmdir" > /dev/null 2>&1 || true; fi
        THREADS="$threads" ASSEMBLY_MEMORY_GB="$mem" diagnose_failed_step "$log" "$rc" "$sample"
        if [[ "$DIAG_RETRY" == "memory_need" ]]; then
            needed="$(python3 -I "${PROJECT_ROOT:-.}/python/assembler_diagnosis.py" "$log" --format need 2>/dev/null </dev/null || true)"
            [[ "$needed" == "-" ]] && needed=""
        fi
        if [[ "$attempt" -ge 3 || "${ASSEMBLER_AUTO_RETRY:-1}" != "1" || "$auto" != "1" ]]; then break; fi
        case "$DIAG_RETRY" in
            memory_need)
                # SPAdes said exactly how much memory it needs: raise the budget to that (never lower it), once, only when it fits in what is free now.
                avail="$(python3 -I "${PROJECT_ROOT:-.}/python/preflight_resources.py" available 2>/dev/null </dev/null || true)"
                # the response ladder engine (python/resource_adapt.py, config/resource_signatures.tsv) chooses: raise the memory budget when it fits, else skip with the exact reason
                verdict="$(python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" decide --tool spades --isolate "$sample" --exit-code "$rc" --log "$log" --threads "$threads" --memory-gb "$mem"                     ${avail:+--available-gb "$avail"} --state "$RESULTS_DIR/resource_state.d/spades.$sample.txt" 2>/dev/null </dev/null || true)"
                IFS=$'\t' read -r vact _ vmem _ _ _ _ _ vmsg <<< "$verdict"
                if [[ "$vact" != "retry" || ! "$vmem" =~ ^[0-9]+$ ]]; then
                    MEMORY_REFUSAL="${vmsg:-the memory needed does not fit}"; free_now="$avail"; break
                fi
                nm="$vmem"; note="$vmsg"
                log "  $vmsg"
                run_event resource_adjust "tool=spades" "sample=$sample" "what=memory" "from=$mem" "to=$nm" "needed=$needed" "message=$vmsg"
                note="memory budget $mem -> $nm GB ($note)"
                [[ -n "$sig" ]] && python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" record --dir "$memdir" --sample "$sample" --sig "$sig" --needed "${needed:-0}" --budget "$nm" --attempts 1 --mode "$mode" --status started 2>/dev/null </dev/null || true
                mem="$nm" ;;
            memory)
                # killed or refused for memory with no stated need: the same response engine decides (lower a budget larger than the free memory, halve threads, or raise
                # SPAdes' own -m limit when SPAdes stopped at it), once per response, at most two adjustments for this isolate
                avail="$(python3 -I "${PROJECT_ROOT:-.}/python/preflight_resources.py" available 2>/dev/null </dev/null || true)"
                verdict="$(python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" decide --tool spades --isolate "$sample" --exit-code "$rc" --log "$log" --threads "$threads" --memory-gb "$mem"                     ${avail:+--available-gb "$avail"} --state "$RESULTS_DIR/resource_state.d/spades.$sample.txt" 2>/dev/null </dev/null || true)"
                IFS=$'	' read -r vact _ vmem vthr _ _ _ _ vmsg <<< "$verdict"
                [[ "$vact" == "retry" ]] || break
                [[ "$vmem" =~ ^[0-9]+$ ]] && mem="$vmem"
                [[ "$vthr" =~ ^[0-9]+$ ]] && threads="$vthr"
                note="$vmsg (memory available now: ${avail:-unknown} GB)"
                run_event resource_adjust "tool=spades" "sample=$sample" "what=memory" "to=$mem" "threads=$threads" "message=$vmsg" ;;
            stale)
                [[ "$attempt" -ge 2 ]] && break    # a stale folder is cleared once; a second retry is only for the memory responses
                note="removed this isolate's own unfinished assembly folder and started it again" ;;
            *) break ;;
        esac
        first="$DIAG_CAUSE"
        warn "SPAdes failed for $sample ($DIAG_TITLE); trying once more: $note"
        run_event assembly_retry "sample=$sample" "cause=$first" "change=$note"
        cp "$log" "$LOG_DIR/${sample}.spades.attempt${attempt}.log" 2>/dev/null || true
        rm -rf "$asmdir" "$out"
        attempt=$((attempt + 1))
    done
    [[ -n "$scratch" ]] && rm -rf "$scratch"
    # The need does not fit in the free memory: --only-assembler only when the user allowed it (one attempt), else THIS isolate is skipped and the others go on.
    if [[ -n "$MEMORY_REFUSAL" && "$attempt" -lt 2 ]]; then
        if [[ "${ASSEMBLER_ALLOW_ONLY_ASSEMBLER:-0}" == "1" ]]; then
            warn "SPAdes for $sample: $MEMORY_REFUSAL. ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1: trying once with --only-assembler (skips read error correction; a different assembly mode, recorded)."
            run_event resource_adjust "sample=$sample" "what=mode" "from=spades" "to=only-assembler" "needed=$needed" "why=does_not_fit"
            cp "$log" "$LOG_DIR/${sample}.spades.attempt${attempt}.log" 2>/dev/null || true
            rm -rf "$asmdir" "$out"
            local oa_rc=0
            WATCH_LOG="$log" run_with_heartbeat "$SAMPLE / SPAdes assembly (only-assembler)" spades.py -1 "$t1" -2 "$t2" -o "$asmdir" \
                --threads "$threads" --memory "$mem" --only-assembler > "$log" 2>&1 || oa_rc=$?
            if [[ "$oa_rc" -eq 0 ]]; then
                ASM_RETRY_NOTE="retried once after spades_needs_memory: --only-assembler (mode change; $MEMORY_REFUSAL)"
                ASM_MEM_USED="$mem" ASM_NEEDED_GB="$needed" ASM_ATTEMPTS=2 ASM_MODE="only-assembler"
                [[ -n "$sig" ]] && python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" record --dir "$memdir" --sample "$sample" --sig "$sig" --needed "${needed:-0}" --budget "$mem" --attempts 2 --mode only-assembler --status completed 2>/dev/null </dev/null || true
                return 0
            fi
            THREADS="$threads" ASSEMBLY_MEMORY_GB="$mem" diagnose_failed_step "$log" "$oa_rc" "$sample"
            handle_step_failure "SPAdes" "$sample" "$log" "$start" "Tried --only-assembler as well (ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1) and it failed."
            return 1
        fi
        memory_skip "$sample" "$needed" "${free_now:-?}" "$start" "spades_said"
        return 1
    fi
    local extra=""
    if [[ "$attempt" -ge 2 ]]; then
        extra="PlasBench already retried $((attempt - 1)) time(s) (last change: $note) and it failed again."
    elif [[ "$DIAG_RETRY" == "memory" ]]; then
        extra="Memory and threads are already at the smallest setting PlasBench will try; this isolate is skipped and the others continue."
    fi
    # Memory belongs to this isolate's read set, not to the computer: the stage goes on with the next isolate (only disk, Python, CPU or folder causes stop it).
    if [[ "$DIAG_RETRY" == "reads" ]]; then
        verify_reads "$sdir" "$r1" "$r2" "$t1" "$t2"
        extra="$READS_NOTE"
    fi
    ASM_MEM_USED="$mem" ASM_NEEDED_GB="$needed" ASM_ATTEMPTS="$attempt" ASM_MODE="$mode"
    handle_step_failure "SPAdes" "$sample" "$log" "$start" "$extra"
    return 1
}

# memory_skip SAMPLE NEEDED_GB FREE_GB START WHY: this isolate needs more memory than is free; say so exactly, remember the need, record it as skipped (needs_more_memory), go on.
memory_skip() {
    local sample="$1" needed="$2" free="$3" start="$4" why="$5" want msg
    want="$(awk -v n="${needed:-0}" 'BEGIN { c = int(n); if (c < n) c++; printf "%d", c + 2 }')"
    msg="needs $(awk -v n="${needed:-0}" 'BEGIN { printf "%.1f", n }') GB, $free GB are free; close programs or raise WSL memory in C:\\Users\\<you>\\.wslconfig (memory=${want}GB) then \`wsl --shutdown\`, or raise MEMORY_GB. This isolate is skipped and the others continue."
    warn "SPAdes for $sample $msg"
    run_event resource_adjust "sample=$sample" "what=skipped" "needed=$needed" "free=$free" "why=$why"
    if [[ "${AUTO_RESOURCES:-1}" == "1" && -n "${sig:-}" ]]; then
        python3 -I "${PROJECT_ROOT:-.}/python/resource_adapt.py" record --dir "$RESULTS_DIR" --sample "$sample" --sig "$sig" --needed "${needed:-0}" --budget "${ASSEMBLY_MEMORY_GB:-0}" --attempts 1 --status skipped 2>/dev/null </dev/null || true
    fi
    ASM_MEM_USED="${ASSEMBLY_MEMORY_GB:-}" ASM_NEEDED_GB="$needed" ASM_ATTEMPTS="1" ASM_MODE="spades"
    record_assembly_status "$sample" "skipped" "" "needs_more_memory: $msg" "$(( $(date +%s) - start ))" "needs_more_memory" "$msg"
}

# Difficulty features (RUN_DIFFICULTY_FEATURES, off by default; see
# python/compute_difficulty_features.py). Computed HERE, not in
# 02_truth.sh, because the assembly graph this needs (assembly_graph.gfa)
# does not exist until this stage produces it. Runs whenever contigs exist
# (a fresh assembly or a reused one) and truth.tsv is already there from
# stage 2 -- so a sample re-assembled before this flag was ever turned on
# still gets its difficulty features computed on the next run, not skipped
# forever because assembly itself was already "reused".
maybe_compute_difficulty_features() {
    local sample="$1" sdir="$2" t1="$3" t2="$4"
    [[ "${RUN_DIFFICULTY_FEATURES:-0}" -eq 1 ]] || return 0
    local ref="$sdir/reference.fna" truth="$sdir/truth.tsv" graph="$sdir/assembly_graph.gfa"
    local out="$sdir/difficulty_features.tsv"
    if [[ ! -s "$ref" || ! -s "$truth" ]]; then
        warn "  difficulty features: no truth reference yet for $sample; skipped"
        return 0
    fi
    if [[ -s "$out" && "$out" -nt "$ref" ]]; then
        log "  difficulty features already computed for $sample"
        return 0
    fi
    python3 "$HERE/../python/compute_difficulty_features.py" --fasta "$ref" --truth "$truth" \
            --out "$out" --graph "$graph" --r1 "$t1" --r2 "$t2" \
            --threads "$DIFFICULTY_FEATURES_THREADS" --sample-id "$sample" \
            > "$LOG_DIR/${sample}.difficulty.log" 2>&1 || \
        warn "difficulty-feature computation failed for $sample; see $LOG_DIR/${sample}.difficulty.log"
}

# Extra assemblers (ASSEMBLY_ALSO) produce alternative candidates beside the primary; each is kept under assemblies/<name>/.
run_alt_assembler() {   # run_alt_assembler NAME T1 T2 OUTDIR SAMPLE
    local name="$1" t1="$2" t2="$3" out="$4" sample="$5"
    [[ -s "$out/contigs.fasta" ]] && return 0
    rm -rf "$out"; mkdir -p "$out"
    case "$name" in
        spades)
            need spades.py
            WATCH_LOG="$LOG_DIR/${sample}.alt.spades.log" run_with_heartbeat "$sample / alternative SPAdes assembly" \
                spades.py -1 "$t1" -2 "$t2" -o "$out/work" --threads "$THREADS" --memory "$ASSEMBLY_MEMORY_GB" \
                > "$LOG_DIR/${sample}.alt.spades.log" 2>&1 || return 1
            cp "$out/work/contigs.fasta" "$out/contigs.fasta"
            [[ -f "$out/work/assembly_graph_with_scaffolds.gfa" ]] && cp "$out/work/assembly_graph_with_scaffolds.gfa" "$out/assembly_graph.gfa" ;;
        unicycler)
            need unicycler
            WATCH_LOG="$LOG_DIR/${sample}.alt.unicycler.log" run_with_heartbeat "$sample / alternative Unicycler assembly" \
                unicycler -1 "$t1" -2 "$t2" -o "$out/work" -t "$THREADS" > "$LOG_DIR/${sample}.alt.unicycler.log" 2>&1 || return 1
            cp "$out/work/assembly.fasta" "$out/contigs.fasta"
            [[ -f "$out/work/assembly.gfa" ]] && cp "$out/work/assembly.gfa" "$out/assembly_graph.gfa" ;;
        *) warn "  ASSEMBLY_ALSO names an unknown assembler '$name' (use spades or unicycler); ignored"; return 1 ;;
    esac
    [[ -s "$out/contigs.fasta" ]]
}

# Measure every candidate assembly and apply the declared selection policy (ASSEMBLY_SELECTION_POLICY: fixed or quality). The policy
# sees assembly-side evidence only, never the truth or a score. report records the choice and acts on nothing; enforce makes the
# chosen assembly the one the tools run on, and returns 1 when no candidate qualifies (nothing is substituted silently).
# Sets ASM_SELECT_REASON and ASM_SELECT_NOTE.
select_assembly() {   # select_assembly SAMPLE SDIR T1 T2
    local sample="$1" sdir="$2" t1="$3" t2="$4"
    ASM_SELECT_REASON="" ASM_SELECT_NOTE=""
    [[ "$ASSEMBLY_SELECTION_MODE" == "off" ]] && return 0
    local primary_dir="$sdir/assemblies/$ASSEMBLER" alt
    mkdir -p "$primary_dir"
    if [[ ! -s "$primary_dir/contigs.fasta" ]]; then
        cp "$sdir/contigs.fasta" "$primary_dir/contigs.fasta"
        [[ -s "$sdir/assembly_graph.gfa" ]] && cp "$sdir/assembly_graph.gfa" "$primary_dir/assembly_graph.gfa"
    fi
    local cands=(--candidate "${ASSEMBLER}=$primary_dir/contigs.fasta")
    for alt in $ASSEMBLY_ALSO; do
        [[ "$alt" == "$ASSEMBLER" ]] && continue
        run_alt_assembler "$alt" "$t1" "$t2" "$sdir/assemblies/$alt" "$sample" \
            || warn "  the alternative assembly with $alt failed for $sample; it is listed as having no assembly"
        cands+=(--candidate "${alt}=$sdir/assemblies/$alt/contigs.fasta")
    done
    local reads=()
    [[ "$ASSEMBLY_READ_SUPPORT" == "1" && -s "$t1" && -s "$t2" ]] && reads=(--reads1 "$t1" --reads2 "$t2")
    local chosen_file="$sdir/.assembly_selected"
    if ! python3 "$HERE/../python/assembly_selection.py" select --sample "$sample" --policy "$ASSEMBLY_SELECTION_POLICY" \
            --primary "$ASSEMBLER" "${cands[@]}" "${reads[@]}" --min-total-mb "$ASSEMBLY_MIN_TOTAL_MB" \
            --max-total-mb "$ASSEMBLY_MAX_TOTAL_MB" --min-mapped-fraction "$ASSEMBLY_MIN_MAPPED_FRACTION" \
            --out "$ASM_SHARDS/${sample}.tsv" --selected-out "$chosen_file" > "$LOG_DIR/${sample}.assembly_selection.log" 2>&1; then
        warn "  assembly selection could not run for $sample (see $LOG_DIR/${sample}.assembly_selection.log); the primary assembly is used"
        return 0
    fi
    local chosen; chosen="$(tr -d '[:space:]' < "$chosen_file")"
    ASM_SELECT_REASON="$(awk -F'\t' 'NR > 1 && ($15 == "yes" || $16 != "") {print $16; exit}' "$ASM_SHARDS/${sample}.tsv")"
    rm -f "$sdir/.assembly_ineligible"
    if [[ -z "$chosen" ]]; then
        if [[ "$ASSEMBLY_SELECTION_MODE" == "enforce" ]]; then
            warn "assembly selection for $sample: no eligible assembly ($ASM_SELECT_REASON); excluded from the tools and the primary benchmark"
            printf '%s\n' "$ASM_SELECT_REASON" > "$sdir/.assembly_ineligible"
            return 1
        fi
        warn "  assembly selection for $sample: no eligible assembly ($ASM_SELECT_REASON); ASSEMBLY_SELECTION_MODE=report, so the primary is used, flagged"
        ASM_SELECT_NOTE="assembly QC: no eligible assembly (flagged)"
        return 0
    fi
    ASM_SELECT_NOTE="assembly selected: $chosen ($ASSEMBLY_SELECTION_POLICY)"
    if [[ "$ASSEMBLY_SELECTION_MODE" == "enforce" ]] && ! cmp -s "$sdir/assemblies/$chosen/contigs.fasta" "$sdir/contigs.fasta"; then
        cp "$sdir/assemblies/$chosen/contigs.fasta" "$sdir/contigs.fasta.partial" && mv -f "$sdir/contigs.fasta.partial" "$sdir/contigs.fasta"
        if [[ -s "$sdir/assemblies/$chosen/assembly_graph.gfa" ]]; then
            cp "$sdir/assemblies/$chosen/assembly_graph.gfa" "$sdir/assembly_graph.gfa"
        else
            rm -f "$sdir/assembly_graph.gfa"
        fi
        log "  assembly selection: $chosen replaces the primary assembly for $sample ($ASM_SELECT_REASON)"
    fi
    return 0
}

assemble_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    ASM_MEM_USED="" ASM_NEEDED_GB="" ASM_ATTEMPTS="" ASM_MODE=""
    local SDIR="$DATA_DIR/$SAMPLE"
    local R1="$SDIR/${SRA}_1.fastq.gz" R2="$SDIR/${SRA}_2.fastq.gz"
    if [[ ! -s "$R1" || ! -s "$R2" ]]; then
        note_missing reads "$SAMPLE"
        record_assembly_status "$SAMPLE" "skipped" "" "reads unavailable"
        return 0
    fi

    # --- short-read QC gate: PASS, WARN or REJECT before anything is assembled ---
    # SHORT_READ_QC_MODE=off skips it; report measures and flags but never excludes (except an integrity failure: unreadable,
    # truncated, empty, malformed or unequal files cannot be assembled meaningfully); enforce also excludes a threshold REJECT.
    # A rejected sample is recorded as `rejected` (not `failed`), is skipped by stage 4 and is not scored as a tool failure.
    rm -f "$SDIR/.qc_rejected"
    if [[ "$SHORT_READ_QC_MODE" != "off" ]]; then
        local QCROW="$QC_SHARDS/${SAMPLE}.tsv"
        if python3 "$HERE/../python/short_read_qc.py" qc --sample "$SAMPLE" --r1 "$R1" --r2 "$R2" --out "$QCROW" \
                --thresholds "$SHORT_READ_QC_THRESHOLDS" --max-pairs "$SHORT_READ_QC_MAX_PAIRS" \
                ${SHORT_READ_QC_GENOME_MB:+--genome-size-mb "$SHORT_READ_QC_GENOME_MB"} \
                > "$LOG_DIR/${SAMPLE}.short_read_qc.log" 2>&1 && [[ -s "$QCROW" ]]; then
            local QCSTATUS QCREASONS QCINTEGRITY
            QCSTATUS="$(awk -F'\t' 'NR==2 {print $2}' "$QCROW")"
            QCREASONS="$(awk -F'\t' 'NR==2 {print $3}' "$QCROW")"
            QCINTEGRITY="$(awk -F'\t' 'NR==2 {print $4}' "$QCROW")"
            [[ "$QCSTATUS" == "WARN" ]] && warn "  short-read QC WARN for $SAMPLE: $QCREASONS (proceeds, flagged)"
            if [[ "$QCSTATUS" == "REJECT" ]]; then
                if [[ "$SHORT_READ_QC_MODE" == "enforce" || "$QCINTEGRITY" != "ok" ]]; then
                    warn "short-read QC REJECT for $SAMPLE ($QCREASONS); excluded from assembly, the tools and the primary benchmark"
                    printf '%s\n' "$QCREASONS" > "$SDIR/.qc_rejected"
                    record_assembly_status "$SAMPLE" "rejected" "" "short-read QC: $QCREASONS"
                    return 0
                fi
                warn "  short-read QC REJECT for $SAMPLE ($QCREASONS); SHORT_READ_QC_MODE=report, so it proceeds, flagged"
            fi
        else
            warn "short-read QC could not run for $SAMPLE (see $LOG_DIR/${SAMPLE}.short_read_qc.log); it proceeds unassessed"
        fi
    fi

    log "=== Assemble $SAMPLE ==="
    local START; START="$(date +%s)"
    # --- fastp trim ---
    # Crash-safe: fastp writes to *.partial.fastq.gz names, which are renamed only after it succeeds, and a
    # .fastp.complete marker records the finished pair. A run that is killed mid-trim (a full disk, WSL or the
    # machine stopping) therefore never leaves a truncated pair that a re-run would mistake for finished reads.
    local T1="$SDIR/${SRA}_1.trim.fastq.gz" T2="$SDIR/${SRA}_2.trim.fastq.gz"
    local P1="$SDIR/${SRA}_1.trim.partial.fastq.gz" P2="$SDIR/${SRA}_2.trim.partial.fastq.gz"
    local TRIM_DONE="$SDIR/.fastp.complete"
    local ASMDIR="$SDIR/assembly"
    local CONTIGS="$SDIR/contigs.fasta"
    local GRAPH="$SDIR/assembly_graph.gfa"
    rm -f "$P1" "$P2"                      # leftovers of an interrupted trim
    # Trimmed reads count as finished when the marker says so, or (for data trimmed by an earlier PlasBench, which
    # wrote no marker) when an assembly already exists, i.e. the trim completed long ago. Otherwise they are redone.
    if [[ -s "$T1" && -s "$T2" ]] && [[ -f "$TRIM_DONE" || -s "$CONTIGS" ]]; then
        log "  trimmed reads present, skipping fastp"
    else
        [[ -s "$T1" || -s "$T2" ]] && log "  trimmed reads from an unfinished run found: trimming again"
        rm -f "$T1" "$T2" "$TRIM_DONE"
        log "  fastp trimming ($SAMPLE) ..."
        run_event sample_start "sample=$SAMPLE" "step=fastp"
        local FASTP_RC=0
        WATCH_LOG="$LOG_DIR/${SAMPLE}.fastp.log" run_with_heartbeat "$SAMPLE / fastp trimming" fastp -i "$R1" -I "$R2" -o "$P1" -O "$P2" \
            --length_required "$MIN_READ_LEN" --thread "$THREADS" \
            --json "$SDIR/fastp.json" --html "$SDIR/fastp.html" $FASTP_EXTRA \
            > "$LOG_DIR/${SAMPLE}.fastp.log" 2>&1 || FASTP_RC=$?
        if [[ "$FASTP_RC" -ne 0 || ! -s "$P1" || ! -s "$P2" ]] || ! mv -f "$P1" "$T1" || ! mv -f "$P2" "$T2"; then
            # Remove the partial pair so a re-run retries the trim instead of
            # assembling truncated reads.
            rm -f "$P1" "$P2" "$T1" "$T2"
            diagnose_failed_step "$LOG_DIR/${SAMPLE}.fastp.log" "$FASTP_RC" "$SAMPLE"
            DIAG_RETRY="-"
            handle_step_failure "fastp" "$SAMPLE" "$LOG_DIR/${SAMPLE}.fastp.log" "$START"
            return 0
        fi
        : > "$TRIM_DONE"
    fi

    # --- assemble ---
    if [[ -s "$CONTIGS" ]]; then
        log "  base assembly present, skipping"
        # Trimmed reads may not exist yet on a reused-assembly re-run with
        # RUN_DIFFICULTY_FEATURES newly turned on (they are only re-derived
        # above if missing); fall back to the untrimmed pair, which is
        # always present whenever an assembly is.
        local dt1="$T1" dt2="$T2"
        [[ -s "$dt1" && -s "$dt2" ]] || { dt1="$R1"; dt2="$R2"; }
        maybe_compute_difficulty_features "$SAMPLE" "$SDIR" "$dt1" "$dt2"
        if ! select_assembly "$SAMPLE" "$SDIR" "$dt1" "$dt2"; then
            record_assembly_status "$SAMPLE" "rejected" "" "assembly selection: $ASM_SELECT_REASON"
            return 0
        fi
        record_assembly_status "$SAMPLE" "reused" "$CONTIGS" "completed assembly reused${ASM_SELECT_NOTE:+; $ASM_SELECT_NOTE}"
        return 0
    fi

    # A fresh assembly starts from an empty folder: one interrupted earlier (the machine stopped, the disk filled)
    # must not be resumed half-written, and the copied contigs are only put in place once complete.
    rm -rf "$ASMDIR" "$CONTIGS.partial" "$GRAPH.partial"
    if [[ "$ASSEMBLER" == "spades" ]]; then
        need spades.py
        log "  SPAdes assembling ($SAMPLE) ..."
        run_event sample_start "sample=$SAMPLE" "step=spades"
        run_spades_checked "$SAMPLE" "$T1" "$T2" "$ASMDIR" "$START" "$R1" "$R2" "$SDIR" || return 0
        if [[ -f "$ASMDIR/assembly_graph_with_scaffolds.gfa" ]]; then
            cp "$ASMDIR/assembly_graph_with_scaffolds.gfa" "$GRAPH.partial" && mv -f "$GRAPH.partial" "$GRAPH" || true
        fi
        # contigs last: their presence is what marks the sample as assembled on a re-run
        cp "$ASMDIR/contigs.fasta" "$CONTIGS.partial" && mv -f "$CONTIGS.partial" "$CONTIGS"
    elif [[ "$ASSEMBLER" == "unicycler" ]]; then
        need unicycler
        log "  Unicycler assembling ($SAMPLE) ..."
        run_event sample_start "sample=$SAMPLE" "step=unicycler"
        local UNI_RC=0
        WATCH_LOG="$LOG_DIR/${SAMPLE}.unicycler.log" run_with_heartbeat "$SAMPLE / Unicycler assembly" unicycler -1 "$T1" -2 "$T2" -o "$ASMDIR" -t "$THREADS" \
            > "$LOG_DIR/${SAMPLE}.unicycler.log" 2>&1 || UNI_RC=$?
        if [[ "$UNI_RC" -ne 0 ]]; then
            diagnose_failed_step "$LOG_DIR/${SAMPLE}.unicycler.log" "$UNI_RC" "$SAMPLE"
            DIAG_RETRY="-"
            handle_step_failure "Unicycler" "$SAMPLE" "$LOG_DIR/${SAMPLE}.unicycler.log" "$START"
            return 0
        fi
        if [[ -f "$ASMDIR/assembly.gfa" ]]; then
            cp "$ASMDIR/assembly.gfa" "$GRAPH.partial" && mv -f "$GRAPH.partial" "$GRAPH" || true
        fi
        cp "$ASMDIR/assembly.fasta" "$CONTIGS.partial" && mv -f "$CONTIGS.partial" "$CONTIGS"
    else
        # A misconfigured assembler is an operator error, not a data failure:
        # it would fail identically for every sample, so it stays fatal.
        die "unknown ASSEMBLER='$ASSEMBLER' (use spades or unicycler)"
    fi
    log "  contigs -> $CONTIGS"
    maybe_compute_difficulty_features "$SAMPLE" "$SDIR" "$T1" "$T2"
    if ! select_assembly "$SAMPLE" "$SDIR" "$T1" "$T2"; then
        record_assembly_status "$SAMPLE" "rejected" "" "assembly selection: $ASM_SELECT_REASON" "$(( $(date +%s) - START ))"
        return 0
    fi
    local RETRY_PART="${ASM_RETRY_NOTE:+SPAdes $ASM_RETRY_NOTE}"
    record_assembly_status "$SAMPLE" "completed" "$CONTIGS" "${RETRY_PART}${RETRY_PART:+${ASM_SELECT_NOTE:+; }}${ASM_SELECT_NOTE:-}" "$(( $(date +%s) - START ))"
}

declare -A PIDS
while IFS=$'\t' read -r -u 3 SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    [[ -e "$STATUS_SHARDS/.stop" ]] && break      # a cause that belongs to the computer was found: do not try the rest
    if ! disk_guard 3 "$SAMPLE" "$SRA"; then      # the next isolate no longer fits (plus the reserve): stop cleanly BEFORE SPAdes, not in the middle of it
        printf '%s\t%s\t%s\n' "disk_space" "$SAMPLE" "not enough free disk space for the next isolate" > "$STATUS_SHARDS/.stop"
        break
    fi
    if [[ "$MAX_PARALLEL_SAMPLES" -le 1 ]]; then
        assemble_sample "$SAMPLE" "$ASM" "$SRA"
    else
        job_slot_wait "$MAX_PARALLEL_SAMPLES"
        assemble_sample "$SAMPLE" "$ASM" "$SRA" &
        PIDS["$SAMPLE"]=$!
    fi
done 3< <(read_samples "$SAMPLE_SHEET")

if [[ "$MAX_PARALLEL_SAMPLES" -gt 1 ]]; then
    # assemble_sample returns 0 for a per-sample trim/assembly failure, having
    # recorded it. A non-zero exit here is therefore an unexpected abort (a
    # misconfigured assembler, a missing binary), which stays fatal.
    aborted=()
    for sample in "${!PIDS[@]}"; do
        wait "${PIDS[$sample]}" || aborted+=("$sample")
    done
    if [[ ${#aborted[@]} -gt 0 ]]; then
        die "assembly aborted unexpectedly for: ${aborted[*]} (see logs/<sample>.spades.log or .unicycler.log for each)"
    fi
fi

report_missing reads "have no downloaded reads yet (stage 1 has not fetched them)" "Each is recorded as skipped in assembly_status.tsv."
# Assemble the final status file once, in the order a sequential run produced it.
STOP_INFO=""
[[ -e "$STATUS_SHARDS/.stop" ]] && STOP_INFO="$(cat "$STATUS_SHARDS/.stop")"
shards=()
N_NOT_TRIED=0
while IFS=$'\t' read -r -u 3 SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if [[ -n "$STOP_INFO" && ! -e "$STATUS_SHARDS/${SAMPLE}.tsv" ]]; then
        record_assembly_status "$SAMPLE" "skipped" "" "not attempted (stopped early: ${STOP_INFO%%$'\t'*})" "" "${STOP_INFO%%$'\t'*}" "fix the cause above, then run the same plasbench run command again"
        N_NOT_TRIED=$((N_NOT_TRIED + 1))
    elif [[ ! -e "$STATUS_SHARDS/${SAMPLE}.tsv" ]]; then
        # Never silent: an isolate of the sheet that no step recorded (the loop was cut short) is listed, so it cannot vanish from the table.
        record_assembly_status "$SAMPLE" "skipped" "" "not attempted: stage 3 did not reach this isolate (the sample list ended early)" "" "not_attempted" "run the same plasbench run command again; finished isolates are reused"
        N_NOT_TRIED=$((N_NOT_TRIED + 1))
        warn "stage 3 did not reach $SAMPLE; it is recorded as not attempted"
    fi
    shards+=("$STATUS_SHARDS/${SAMPLE}.tsv")
done 3< <(read_samples "$SAMPLE_SHEET")
merge_shards "$STATUS" "$(printf 'sample\tstatus\tcontigs\treason\truntime_seconds\tcause\tadvice\tmemory_gb_used\tneeded_gb\tattempts\tassembly_mode')" "${shards[@]}"
rm -rf "$STATUS_SHARDS"
if [[ "${AUTO_RESOURCES:-1}" == "1" ]]; then
    python3 -I "$HERE/../python/resource_adapt.py" merge --dir "$RESULTS_DIR" --out "$RESULTS_DIR/resource_profile.tsv" 2>/dev/null </dev/null || true
fi
if [[ "$ASSEMBLY_SELECTION_MODE" != "off" ]] && compgen -G "$ASM_SHARDS/*.tsv" > /dev/null; then
    { head -1 "$(ls "$ASM_SHARDS"/*.tsv | head -1)"; for f in "$ASM_SHARDS"/*.tsv; do tail -n +2 "$f"; done; } > "$RESULTS_DIR/assembly_candidates.tsv"
fi
rm -rf "$ASM_SHARDS"
if [[ "$SHORT_READ_QC_MODE" != "off" ]] && compgen -G "$QC_SHARDS/*.tsv" > /dev/null; then
    python3 "$HERE/../python/short_read_qc.py" merge --shards "$QC_SHARDS" --out "$RESULTS_DIR/short_read_qc.tsv" \
        --status-out "$RESULTS_DIR/short_read_qc_status.tsv" --mode "$SHORT_READ_QC_MODE" \
        || warn "could not merge the short-read QC tables"
fi
rm -rf "$QC_SHARDS"

USABLE="$(awk -F'\t' 'NR>1 && ($2=="completed" || $2=="reused")' "$STATUS" | wc -l | tr -d '[:space:]')"
UNUSABLE="$(awk -F'\t' 'NR>1 && ($2=="failed" || $2=="skipped" || $2=="rejected")' "$STATUS" | wc -l | tr -d '[:space:]')"
if [[ "$UNUSABLE" -gt 0 ]]; then
    warn "$UNUSABLE sample(s) produced no assembly; stage 4 will record their tools as skipped:"
    awk -F'\t' 'NR>1 && ($2=="failed" || $2=="skipped" || $2=="rejected") {printf "    %s\t%s\t%s\n", $1, $2, $4}' "$STATUS" >&2
fi
N_FAILED="$(awk -F'\t' 'NR>1 && $2=="failed"' "$STATUS" | wc -l | tr -d '[:space:]')"
N_CAUSES="$(awk -F'\t' 'NR>1 && $2=="failed" && $6!="" {print $6}' "$STATUS" | sort -u | wc -l | tr -d '[:space:]')"
if [[ "$N_FAILED" -gt 1 && "$N_CAUSES" -eq 1 && "$N_FAILED" -eq "$UNUSABLE" ]]; then
    warn "All $N_FAILED samples failed for the same reason: $(awk -F'\t' 'NR>1 && $2=="failed" {print $6; exit}' "$STATUS"). One fix: $(awk -F'\t' 'NR>1 && $2=="failed" {print $7; exit}' "$STATUS")"
fi
if [[ -n "$STOP_INFO" ]]; then
    IFS=$'\t' read -r STOP_CAUSE STOP_SAMPLE STOP_TITLE <<< "$STOP_INFO"
    run_event stage_stopped "cause=$STOP_CAUSE" "sample=$STOP_SAMPLE" "not_attempted=$N_NOT_TRIED"
    if [[ "$STOP_CAUSE" == "disk_space" ]]; then
        warn "Stage 3 stopped cleanly before $STOP_SAMPLE because the disk is nearly full ($N_NOT_TRIED isolate(s) not attempted). Nothing was lost: finished isolates are kept. Free space (or use a bigger drive), then run the same plasbench run command again to continue. Status: $STATUS"
        exit 6
    fi
    warn "Stage 3 stopped early at $STOP_SAMPLE: $STOP_TITLE ($STOP_CAUSE). This belongs to the computer, not the isolate, so every other sample would fail the same way ($N_NOT_TRIED not attempted). Fix it, then run the same plasbench run command again: finished isolates, downloads and trimmed reads are reused (there is no separate --resume option). Status: $STATUS"
    exit 5
fi
if [[ "$USABLE" -eq 0 ]]; then
    # The verdict is only reached after EVERY isolate of the sheet was attempted (or recorded as not attempted): each one is listed with its cause.
    die "no sample produced an assembly; nothing to benchmark: $(awk -F'\t' 'NR>1 {printf "%s%s [%s: %s]", sep, $1, $2, ($6 != "" ? $6 : $4); sep="; "}' "$STATUS") (see $STATUS)"
fi
N_ROWS=$(( USABLE + UNUSABLE ))
if [[ "$UNUSABLE" -gt 0 ]]; then
    PARTIAL_WHY="$(awk -F'\t' 'NR>1 && ($2=="failed"||$2=="skipped"||$2=="rejected") {c[($6 != "" ? $6 : $4)]++} END {for (k in c) {printf "%s%s x%d", sep, k, c[k]; sep=", "}}' "$STATUS")"
    log "Stage 3 (assembly) complete WITH WARNINGS: $USABLE of $N_ROWS assembled; $UNUSABLE unavailable ($PARTIAL_WHY). The isolates that assembled go on to the tools. Status -> $STATUS"
    run_event stage_partial "assembled=$USABLE" "unavailable=$UNUSABLE" "total=$N_ROWS"
else
    log "Stage 3 (assembly) complete: $USABLE of $N_ROWS assembled. Status -> $STATUS"
fi
