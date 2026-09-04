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
warn_resource_oversubscription "stage 3 (assembly)" "$MAX_PARALLEL_SAMPLES" "$THREADS" "$ASSEMBLY_MEMORY_GB"

STATUS="$RESULTS_DIR/assembly_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
reset_shard_dir "assemble"
STATUS_SHARDS="$(shard_dir "assemble")"

# Every sample gets record_assembly_status called at most once per run, into
# its own uniquely-named file, so this needs no locking even when several
# assemblies run concurrently: no two processes ever target the same path. The
# final status file is assembled once, after every job finishes, in sample
# order -- so its row order matches a sequential run's exactly, however the
# parallel jobs actually interleaved.
record_assembly_status() {
    local sample="$1"
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" \
        > "$STATUS_SHARDS/${sample}.tsv"
}

assemble_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    local R1="$SDIR/${SRA}_1.fastq.gz" R2="$SDIR/${SRA}_2.fastq.gz"
    if [[ ! -s "$R1" || ! -s "$R2" ]]; then
        warn "no reads for $SAMPLE; run 01_download.sh"
        record_assembly_status "$SAMPLE" "skipped" "" "reads unavailable"
        return 0
    fi

    log "=== Assemble $SAMPLE ==="
    local START; START="$(date +%s)"
    # --- fastp trim ---
    local T1="$SDIR/${SRA}_1.trim.fastq.gz" T2="$SDIR/${SRA}_2.trim.fastq.gz"
    if [[ -s "$T1" && -s "$T2" ]]; then
        log "  trimmed reads present, skipping fastp"
    else
        log "  fastp trimming ($SAMPLE) ..."
        if ! fastp -i "$R1" -I "$R2" -o "$T1" -O "$T2" \
            --length_required "$MIN_READ_LEN" --thread "$THREADS" \
            --json "$SDIR/fastp.json" --html "$SDIR/fastp.html" $FASTP_EXTRA \
            > "$LOG_DIR/${SAMPLE}.fastp.log" 2>&1; then
            # Remove the partial pair so a re-run retries the trim instead of
            # assembling truncated reads.
            rm -f "$T1" "$T2"
            warn "fastp failed for $SAMPLE; excluded from assembly and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "fastp: see $LOG_DIR/${SAMPLE}.fastp.log" "$(( $(date +%s) - START ))"
            return 0
        fi
    fi

    # --- assemble ---
    local ASMDIR="$SDIR/assembly"
    local CONTIGS="$SDIR/contigs.fasta"
    local GRAPH="$SDIR/assembly_graph.gfa"
    if [[ -s "$CONTIGS" ]]; then
        log "  base assembly present, skipping"
        record_assembly_status "$SAMPLE" "reused" "$CONTIGS" "completed assembly reused"
        return 0
    fi

    if [[ "$ASSEMBLER" == "spades" ]]; then
        need spades.py
        log "  SPAdes assembling ($SAMPLE) ..."
        if ! spades.py -1 "$T1" -2 "$T2" -o "$ASMDIR" \
            --threads "$THREADS" --memory "$ASSEMBLY_MEMORY_GB" \
            > "$LOG_DIR/${SAMPLE}.spades.log" 2>&1; then
            warn "SPAdes failed for $SAMPLE; excluded from tool runs and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "spades: see $LOG_DIR/${SAMPLE}.spades.log" "$(( $(date +%s) - START ))"
            return 0
        fi
        cp "$ASMDIR/contigs.fasta" "$CONTIGS"
        [[ -f "$ASMDIR/assembly_graph_with_scaffolds.gfa" ]] && \
            cp "$ASMDIR/assembly_graph_with_scaffolds.gfa" "$GRAPH" || true
    elif [[ "$ASSEMBLER" == "unicycler" ]]; then
        need unicycler
        log "  Unicycler assembling ($SAMPLE) ..."
        if ! unicycler -1 "$T1" -2 "$T2" -o "$ASMDIR" -t "$THREADS" \
            > "$LOG_DIR/${SAMPLE}.unicycler.log" 2>&1; then
            warn "Unicycler failed for $SAMPLE; excluded from tool runs and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "unicycler: see $LOG_DIR/${SAMPLE}.unicycler.log" "$(( $(date +%s) - START ))"
            return 0
        fi
        cp "$ASMDIR/assembly.fasta" "$CONTIGS"
        [[ -f "$ASMDIR/assembly.gfa" ]] && cp "$ASMDIR/assembly.gfa" "$GRAPH" || true
    else
        # A misconfigured assembler is an operator error, not a data failure:
        # it would fail identically for every sample, so it stays fatal.
        die "unknown ASSEMBLER='$ASSEMBLER' (use spades or unicycler)"
    fi
    log "  contigs -> $CONTIGS"
    record_assembly_status "$SAMPLE" "completed" "$CONTIGS" "" "$(( $(date +%s) - START ))"
}

declare -A PIDS
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if [[ "$MAX_PARALLEL_SAMPLES" -le 1 ]]; then
        assemble_sample "$SAMPLE" "$ASM" "$SRA"
    else
        job_slot_wait "$MAX_PARALLEL_SAMPLES"
        assemble_sample "$SAMPLE" "$ASM" "$SRA" &
        PIDS["$SAMPLE"]=$!
    fi
done < <(read_samples "$SAMPLE_SHEET")

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

# Assemble the final status file once, in the order a sequential run produced it.
shards=()
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    shards+=("$STATUS_SHARDS/${SAMPLE}.tsv")
done < <(read_samples "$SAMPLE_SHEET")
merge_shards "$STATUS" "$(printf 'sample\tstatus\tcontigs\treason\truntime_seconds')" "${shards[@]}"
rm -rf "$STATUS_SHARDS"

USABLE="$(awk -F'\t' 'NR>1 && ($2=="completed" || $2=="reused")' "$STATUS" | wc -l | tr -d '[:space:]')"
UNUSABLE="$(awk -F'\t' 'NR>1 && ($2=="failed" || $2=="skipped")' "$STATUS" | wc -l | tr -d '[:space:]')"
if [[ "$UNUSABLE" -gt 0 ]]; then
    warn "$UNUSABLE sample(s) produced no assembly; stage 4 will record their tools as skipped:"
    awk -F'\t' 'NR>1 && ($2=="failed" || $2=="skipped") {printf "    %s\t%s\t%s\n", $1, $2, $4}' "$STATUS" >&2
fi
if [[ "$USABLE" -eq 0 ]]; then
    die "no sample produced an assembly; nothing to benchmark (see $STATUS)"
fi

log "Stage 3 (assembly) complete: $USABLE assembled, $UNUSABLE unavailable. Status -> $STATUS"
