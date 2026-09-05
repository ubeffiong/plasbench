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
STATUS="$RESULTS_DIR/tool_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
reset_shard_dir "run_tools"
STATUS_SHARDS="$(shard_dir "run_tools")"

# Every (sample, tool) pair gets record_status called at most once per run,
# into its own uniquely-named file, so this needs no locking even when many
# samples/tools write concurrently: no two processes ever target the same
# path. The final status file is assembled once, after every job finishes,
# in a fixed sample x tool order -- so its row order matches a sequential
# run's exactly, however the parallel jobs actually interleaved.
record_status() {
    local sample="$1" tool="$2" rss="${7:-}"
    [[ -z "$rss" && -n "${6:-}" ]] && rss="$(profile_rss "${PROFILE_RSS_FILE:-}")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "${6:-}" "$rss" \
        > "$STATUS_SHARDS/${sample}.${tool}.tsv"
}

profile_start() { date +%s; }
profile_elapsed() { printf '%s' "$(( $(date +%s) - $1 ))"; }
profile_rss() { [[ -s "$1" ]] && tr -d '[:space:]' < "$1" || true; }
profile_exec() {
    PROFILE_RSS_FILE="$LOG_DIR/${SAMPLE}.${TOOL}.rss"; rm -f "$PROFILE_RSS_FILE"
    if [[ -x /usr/bin/time ]]; then /usr/bin/time -f '%M' -o "$PROFILE_RSS_FILE" "$@"; else "$@"; fi
}
profile_exec_in_dir() {
    local run_dir="$1"; shift
    PROFILE_RSS_FILE="$LOG_DIR/${SAMPLE}.${TOOL}.rss"; rm -f "$PROFILE_RSS_FILE"
    if [[ -x /usr/bin/time ]]; then (cd "$run_dir" && /usr/bin/time -f '%M' -o "$PROFILE_RSS_FILE" "$@"); else (cd "$run_dir" && "$@"); fi
}

is_complete() {
    [[ -e "$1" && -f "$2" && "${FORCE_RERUN_TOOLS:-0}" -ne 1 ]]
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "MOB hard-label classifier provenance: $PROVENANCE" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_GPLAS2_MOB gplas2_mob; then
        warn "gplas2_mob is enabled but gplas is not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "gplas2_mob" "skipped" "" "command unavailable"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "external classifier TSV: $CLASSIFIER" "$(profile_elapsed "$START")"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasme failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif tool_enabled RUN_PLASME plasme; then
        warn "plasme is enabled but PLASMe.py is not installed (or not on PATH); skipped for $SAMPLE"
        record_status "$SAMPLE" "plasme" "skipped" "" "command unavailable"
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
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
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
        tool_enabled RUN_PLASGRAPH2 plasgraph2 && record_status "$SAMPLE" "plasgraph2" "skipped" "" "assembly contigs unavailable"
        return 0
    fi
    log "=== Run tools on $SAMPLE ==="

    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_mob_recon "$SAMPLE" "$RDIR" "$CONTIGS" &
    local mob_recon_pid=$!
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_platon "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasmidspades "$SAMPLE" "$RDIR" "$CONTIGS" "$T1" "$T2" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_gplas2_external "$SAMPLE" "$SDIR" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_genomad "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasme "$SAMPLE" "$RDIR" "$CONTIGS" &
    job_slot_wait "$MAX_PARALLEL_TOOLS"; run_plasgraph2 "$SAMPLE" "$SDIR" "$RDIR" "$CONTIGS" &

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
    for tool in mob_recon gplas2_mob platon plasmidspades gplas2_external genomad plasme plasgraph2; do
        shards+=("$STATUS_SHARDS/${SAMPLE}.${tool}.tsv")
    done
done < <(read_samples "$SAMPLE_SHEET")
merge_shards "$STATUS" "$(printf 'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb')" "${shards[@]}"
rm -rf "$STATUS_SHARDS"

log "Stage 4 (run tools) complete."
