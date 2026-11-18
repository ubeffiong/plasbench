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
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" \
        > "$STATUS_SHARDS/${sample}.tsv"
    run_event assembly_end "sample=$1" "status=$2" "reason=${4:-}"
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
    local SDIR="$DATA_DIR/$SAMPLE"
    local R1="$SDIR/${SRA}_1.fastq.gz" R2="$SDIR/${SRA}_2.fastq.gz"
    if [[ ! -s "$R1" || ! -s "$R2" ]]; then
        warn "no reads for $SAMPLE; run 01_download.sh"
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
        if ! WATCH_LOG="$LOG_DIR/${SAMPLE}.fastp.log" run_with_heartbeat "$SAMPLE / fastp trimming" fastp -i "$R1" -I "$R2" -o "$P1" -O "$P2" \
            --length_required "$MIN_READ_LEN" --thread "$THREADS" \
            --json "$SDIR/fastp.json" --html "$SDIR/fastp.html" $FASTP_EXTRA \
            > "$LOG_DIR/${SAMPLE}.fastp.log" 2>&1 \
            || [[ ! -s "$P1" || ! -s "$P2" ]] || ! mv -f "$P1" "$T1" || ! mv -f "$P2" "$T2"; then
            # Remove the partial pair so a re-run retries the trim instead of
            # assembling truncated reads.
            rm -f "$P1" "$P2" "$T1" "$T2"
            warn "fastp failed for $SAMPLE; excluded from assembly and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "fastp: see $LOG_DIR/${SAMPLE}.fastp.log" "$(( $(date +%s) - START ))"
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
        if ! WATCH_LOG="$LOG_DIR/${SAMPLE}.spades.log" run_with_heartbeat "$SAMPLE / SPAdes assembly" spades.py -1 "$T1" -2 "$T2" -o "$ASMDIR" \
            --threads "$THREADS" --memory "$ASSEMBLY_MEMORY_GB" \
            > "$LOG_DIR/${SAMPLE}.spades.log" 2>&1; then
            warn "SPAdes failed for $SAMPLE; excluded from tool runs and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "spades: see $LOG_DIR/${SAMPLE}.spades.log" "$(( $(date +%s) - START ))"
            return 0
        fi
        if [[ -f "$ASMDIR/assembly_graph_with_scaffolds.gfa" ]]; then
            cp "$ASMDIR/assembly_graph_with_scaffolds.gfa" "$GRAPH.partial" && mv -f "$GRAPH.partial" "$GRAPH" || true
        fi
        # contigs last: their presence is what marks the sample as assembled on a re-run
        cp "$ASMDIR/contigs.fasta" "$CONTIGS.partial" && mv -f "$CONTIGS.partial" "$CONTIGS"
    elif [[ "$ASSEMBLER" == "unicycler" ]]; then
        need unicycler
        log "  Unicycler assembling ($SAMPLE) ..."
        run_event sample_start "sample=$SAMPLE" "step=unicycler"
        if ! WATCH_LOG="$LOG_DIR/${SAMPLE}.unicycler.log" run_with_heartbeat "$SAMPLE / Unicycler assembly" unicycler -1 "$T1" -2 "$T2" -o "$ASMDIR" -t "$THREADS" \
            > "$LOG_DIR/${SAMPLE}.unicycler.log" 2>&1; then
            warn "Unicycler failed for $SAMPLE; excluded from tool runs and scoring"
            record_assembly_status "$SAMPLE" "failed" "" \
                "unicycler: see $LOG_DIR/${SAMPLE}.unicycler.log" "$(( $(date +%s) - START ))"
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
    record_assembly_status "$SAMPLE" "completed" "$CONTIGS" "${ASM_SELECT_NOTE:-}" "$(( $(date +%s) - START ))"
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
if [[ "$USABLE" -eq 0 ]]; then
    die "no sample produced an assembly; nothing to benchmark (see $STATUS)"
fi

log "Stage 3 (assembly) complete: $USABLE assembled, $UNUSABLE unavailable. Status -> $STATUS"
