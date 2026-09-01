#!/usr/bin/env bash
# Stage 4 — run each enabled plasmid-reconstruction tool on the sample, then
# use its adapter to write a standardized predicted-plasmid FASTA:
#     results/<sample>/pred_<tool>.plasmid.fasta
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
ADAPT="$HERE/../adapters"
STATUS="$RESULTS_DIR/tool_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
printf 'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n' > "$STATUS"

record_status() {
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "${6:-}" "${7:-$(profile_rss "${PROFILE_RSS_FILE:-}")}" >> "$STATUS"
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

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    RDIR="$RESULTS_DIR/$SAMPLE"; mkdir -p "$RDIR"
    CONTIGS="$SDIR/contigs.fasta"
    T1="$SDIR/${SRA}_1.trim.fastq.gz"; T2="$SDIR/${SRA}_2.trim.fastq.gz"
    if [[ ! -s "$CONTIGS" ]]; then
        warn "no contigs for $SAMPLE; run 03_assemble.sh"
        [[ "${RUN_MOB_RECON:-0}" -eq 1 ]] && record_status "$SAMPLE" "mob_recon" "skipped" "" "assembly contigs unavailable"
        [[ "${RUN_PLATON:-0}" -eq 1 ]] && record_status "$SAMPLE" "platon" "skipped" "" "assembly contigs unavailable"
        [[ "${RUN_PLASMIDSPADES:-0}" -eq 1 ]] && record_status "$SAMPLE" "plasmidspades" "skipped" "" "assembly contigs unavailable"
        [[ "${RUN_GPLAS2_MOB:-0}" -eq 1 ]] && record_status "$SAMPLE" "gplas2_mob" "skipped" "" "assembly contigs unavailable"
        [[ "${RUN_GPLAS2_EXTERNAL:-0}" -eq 1 ]] && record_status "$SAMPLE" "gplas2_external" "skipped" "" "assembly contigs unavailable"
        continue
    fi
    log "=== Run tools on $SAMPLE ==="

    # -------- mob_recon --------
    if [[ "${RUN_MOB_RECON:-0}" -eq 1 ]] && have mob_recon; then
        TOOL="mob_recon"; OUT="$RDIR/$TOOL"; PRED="$RDIR/pred_${TOOL}.plasmid.fasta"; DONE="$RDIR/.${TOOL}.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  mob_recon: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  mob_recon ..."
            START=$(profile_start)
            if profile_exec mob_recon --infile "$CONTIGS" --outdir "$OUT" --num_threads "$THREADS" --force > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_mob_recon.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "mob_recon failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif [[ "${RUN_MOB_RECON:-0}" -eq 1 ]]; then
        warn "mob_recon is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "mob_recon" "skipped" "" "command unavailable"
    fi

    # -------- gplas2 seeded by MOB-recon membership --------
    if [[ "${RUN_GPLAS2_MOB:-0}" -eq 1 ]] && have gplas; then
        TOOL="gplas2_mob"; OUT="$RDIR/$TOOL"; PRED="$RDIR/pred_${TOOL}.plasmid.fasta"; DONE="$RDIR/.${TOOL}.complete"
        GRAPH="$SDIR/assembly_graph.gfa"; MOB_OUT="$RDIR/mob_recon"
        CLASSIFIER="$OUT/${SAMPLE}.mob_classifier.tsv"; PROVENANCE="$OUT/${SAMPLE}.mob_classifier.provenance.json"
        if is_complete "$DONE" "$PRED"; then
            log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -s "$GRAPH" ]]; then
            warn "  $TOOL needs an assembly graph; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly graph unavailable"
        elif [[ ! -d "$MOB_OUT" ]]; then
            warn "  $TOOL requires successful mob_recon output; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "MOB-recon output unavailable"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"; log "  $TOOL (MOB hard-label seeds) ..."
            START=$(profile_start)
            if python3 "$HERE/../python/mob_to_gplas_classifier.py" --graph "$GRAPH" --mob-output "$MOB_OUT" \
                --out "$CLASSIFIER" --provenance "$PROVENANCE" --min-contig-length "$GPLAS2_MIN_CONTIG_LENGTH" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                profile_exec_in_dir "$OUT" gplas -i "$GRAPH" -P "$CLASSIFIER" -n "$SAMPLE" >> "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_gplas.sh" "$OUT/results" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "MOB hard-label classifier provenance: $PROVENANCE" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif [[ "${RUN_GPLAS2_MOB:-0}" -eq 1 ]]; then
        warn "gplas2_mob is enabled but gplas is not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "gplas2_mob" "skipped" "" "command unavailable"
    fi

    # -------- Platon --------
    if [[ "${RUN_PLATON:-0}" -eq 1 ]] && have platon; then
        TOOL="platon"; OUT="$RDIR/$TOOL"; PRED="$RDIR/pred_${TOOL}.plasmid.fasta"; DONE="$RDIR/.${TOOL}.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  platon: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; mkdir -p "$OUT"
            log "  platon ..."
            START=$(profile_start)
            if profile_exec platon --db "$PLATON_DB" --threads "$THREADS" --output "$OUT" --prefix "$SAMPLE" "$CONTIGS" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_platon.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "platon failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif [[ "${RUN_PLATON:-0}" -eq 1 ]]; then
        warn "platon is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "platon" "skipped" "" "command unavailable"
    fi

    # -------- plasmidSPAdes --------
    if [[ "${RUN_PLASMIDSPADES:-0}" -eq 1 ]] && have plasmidspades.py; then
        TOOL="plasmidspades"; OUT="$RDIR/$TOOL"; PRED="$RDIR/pred_${TOOL}.plasmid.fasta"; DONE="$RDIR/.${TOOL}.complete"
        if is_complete "$DONE" "$PRED"; then
            log "  plasmidSPAdes: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        else
            rm -rf "$OUT" "$PRED" "$DONE"
            log "  plasmidSPAdes ..."
            START=$(profile_start)
            if profile_exec plasmidspades.py -1 "$T1" -2 "$T2" -o "$OUT" --threads "$THREADS" --memory "$MEMORY_GB" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_plasmidspades.sh" "$OUT" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "plasmidSPAdes failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif [[ "${RUN_PLASMIDSPADES:-0}" -eq 1 ]]; then
        warn "plasmidSPAdes is enabled but not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "plasmidspades" "skipped" "" "command unavailable"
    fi

    # -------- gplas2 external classifier mode --------
    if [[ "${RUN_GPLAS2_EXTERNAL:-0}" -eq 1 ]] && have gplas; then
        TOOL="gplas2_external"; OUT="$RDIR/$TOOL"; PRED="$RDIR/pred_${TOOL}.plasmid.fasta"; DONE="$RDIR/.${TOOL}.complete"
        GRAPH="$SDIR/assembly_graph.gfa"
        CLASSIFIER="${GPLAS2_EXTERNAL_PREDICTIONS_DIR:-}/$SAMPLE.tsv"
        if is_complete "$DONE" "$PRED"; then
            log "  $TOOL: reusing completed result"; record_status "$SAMPLE" "$TOOL" "reused" "$PRED" "completed result reused"
        elif [[ ! -s "$GRAPH" ]]; then
            warn "  $TOOL needs an assembly graph; skipped for $SAMPLE"; record_status "$SAMPLE" "$TOOL" "skipped" "" "assembly graph unavailable"
        elif [[ ! -s "$CLASSIFIER" ]]; then
            warn "  $TOOL prediction table missing: $CLASSIFIER"; record_status "$SAMPLE" "$TOOL" "skipped" "" "external classifier TSV unavailable"
        else
            rm -rf "$OUT" "$PRED" "$DONE"; log "  $TOOL ..."
            START=$(profile_start)
            if python3 "$HERE/../python/validate_gplas_classifier.py" --graph "$GRAPH" --classifier "$CLASSIFIER" --min-contig-length "$GPLAS2_MIN_CONTIG_LENGTH" > "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                profile_exec_in_dir "$OUT" gplas -i "$GRAPH" -P "$CLASSIFIER" -n "$SAMPLE" >> "$LOG_DIR/${SAMPLE}.${TOOL}.log" 2>&1 && \
                bash "$ADAPT/adapt_gplas.sh" "$OUT/results" "$CONTIGS" "$PRED" 2>> "$LOG_DIR/${SAMPLE}.${TOOL}.log"; then
                touch "$DONE"; record_status "$SAMPLE" "$TOOL" "completed" "$PRED" "external classifier TSV: $CLASSIFIER" "$(profile_elapsed "$START")"
            else
                rm -f "$PRED" "$DONE"; warn "$TOOL failed for $SAMPLE; excluded from scoring"; record_status "$SAMPLE" "$TOOL" "failed" "" "see $LOG_DIR/${SAMPLE}.${TOOL}.log" "$(profile_elapsed "$START")"
            fi
        fi
    elif [[ "${RUN_GPLAS2_EXTERNAL:-0}" -eq 1 ]]; then
        warn "gplas2_external is enabled but gplas is not installed; skipped for $SAMPLE"
        record_status "$SAMPLE" "gplas2_external" "skipped" "" "command unavailable"
    fi
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 4 (run tools) complete."
