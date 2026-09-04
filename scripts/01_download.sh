#!/usr/bin/env bash
# Stage 1 — download, per sample:
#   (a) the COMPLETE reference assembly + its sequence report (ground truth)
#   (b) the matched Illumina reads from SRA
#
# Parallelism (config/config.sh: MAX_PARALLEL_SAMPLES): downloads are network-
# bound, not CPU-bound, so this is usually the safest stage to raise well
# above the reconstruction-stage concurrency. At the default of 1, samples
# run one at a time exactly as before, and a download failure aborts the
# whole stage immediately (matching today's fail-fast behavior). Above 1,
# samples download concurrently; a failure no longer aborts sibling downloads
# already in flight (that is what concurrency means), but it is still
# collected and reported, and the stage still exits non-zero overall.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

[[ -f "$SAMPLE_SHEET" ]] || die "sample sheet not found: $SAMPLE_SHEET"
warn_resource_oversubscription "stage 1 (download)" "$MAX_PARALLEL_SAMPLES" "$THREADS"

download_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    mkdir -p "$SDIR"
    log "=== Sample $SAMPLE : assembly=$ASM  reads=$SRA ==="
    local REF="$SDIR/reference.fna"
    local REPORT="$SDIR/sequence_report.jsonl"
    local R1="$SDIR/${SRA}_1.fastq.gz"
    local R2="$SDIR/${SRA}_2.fastq.gz"
    # An operational sample with no known truth reference leaves this column
    # blank (or "NA"): it has reads to reconstruct from but no complete
    # assembly to score against, so skip the reference/sequence-report half
    # of this stage entirely and fetch reads only.
    local HAS_REFERENCE=1
    [[ -z "$ASM" || "$ASM" == "NA" ]] && HAS_REFERENCE=0

    if [[ "$LOCAL_INPUTS_ONLY" == "1" ]]; then
        local missing=()
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            [[ -s "$REF" ]] || missing+=("$REF")
            [[ -s "$REPORT" || -s "$SDIR/truth.tsv" ]] || missing+=("$REPORT or $SDIR/truth.tsv")
        fi
        [[ -s "$R1" ]] || missing+=("$R1")
        [[ -s "$R2" ]] || missing+=("$R2")
        if [[ ${#missing[@]} -gt 0 ]]; then
            die "local-inputs mode is missing for $SAMPLE: ${missing[*]}"
        fi
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            log "  local reference, truth/report, and paired reads verified; download skipped"
        else
            log "  local paired reads verified (no accession: reference/truth skipped); download skipped"
        fi
        return 0
    fi

    # Download clients are only required when this sample actually needs them.
    [[ "$HAS_REFERENCE" -eq 1 ]] && need datasets
    need prefetch
    need fasterq-dump

    # ---- (a) reference assembly + sequence report ----
    if [[ "$HAS_REFERENCE" -eq 0 ]]; then
        log "  no assembly_accession given; skipping reference download (operational sample)"
    elif [[ -s "$REF" && -s "$REPORT" ]]; then
        log "  reference already present, skipping download"
    else
        log "  downloading assembly $ASM ..."
        local ZIP="$SDIR/ncbi.zip"
        datasets download genome accession "$ASM" \
            --include genome,seq-report,gff3 \
            --filename "$ZIP" 2> "$LOG_DIR/${SAMPLE}.datasets.log" \
            || die "datasets download failed for $ASM (see $LOG_DIR/${SAMPLE}.datasets.log)"
        rm -rf "$SDIR/ncbi"; mkdir -p "$SDIR/ncbi"
        unzip -o -q "$ZIP" -d "$SDIR/ncbi"
        # locate the genomic FASTA and the sequence report inside the bundle
        local FNA SR
        FNA=$(find "$SDIR/ncbi" -name '*_genomic.fna' -o -name '*.fna' | head -n1)
        SR=$(find "$SDIR/ncbi" -name 'sequence_report.jsonl' | head -n1)
        [[ -s "$FNA" ]] || die "no genomic FASTA found in bundle for $ASM"
        [[ -s "$SR"  ]] || die "no sequence_report.jsonl found for $ASM (was --include seq-report used?)"
        cp "$FNA" "$REF"
        cp "$SR" "$REPORT"
        rm -f "$ZIP"
        log "  reference -> $REF"
    fi

    # ---- (b) Illumina reads ----
    if [[ -s "$R1" && -s "$R2" ]]; then
        log "  reads already present, skipping download"
    else
        log "  prefetching $SRA ..."
        prefetch -O "$SDIR" "$SRA" > "$LOG_DIR/${SAMPLE}.prefetch.log" 2>&1 \
            || die "prefetch failed for $SRA"
        log "  extracting FASTQ (fasterq-dump) ..."
        fasterq-dump --split-files --threads "$THREADS" -O "$SDIR" \
            "$SDIR/$SRA/$SRA.sra" > "$LOG_DIR/${SAMPLE}.fasterq.log" 2>&1 \
            || fasterq-dump --split-files --threads "$THREADS" -O "$SDIR" "$SRA" \
               > "$LOG_DIR/${SAMPLE}.fasterq.log" 2>&1 \
            || die "fasterq-dump failed for $SRA"
        # compress
        [[ -f "$SDIR/${SRA}_1.fastq" ]] && pigz -f "$SDIR/${SRA}_1.fastq" 2>/dev/null || gzip -f "$SDIR/${SRA}_1.fastq" 2>/dev/null || true
        [[ -f "$SDIR/${SRA}_2.fastq" ]] && pigz -f "$SDIR/${SRA}_2.fastq" 2>/dev/null || gzip -f "$SDIR/${SRA}_2.fastq" 2>/dev/null || true
        rm -rf "$SDIR/$SRA"   # remove .sra cache dir
        [[ -s "$R1" && -s "$R2" ]] || die "expected paired FASTQ not produced for $SRA (single-end run? edit pipeline)"
        log "  reads -> $R1 , $R2"
    fi
}

declare -A PIDS
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if [[ "$MAX_PARALLEL_SAMPLES" -le 1 ]]; then
        # Not backgrounded: a die() inside download_sample aborts this whole
        # script immediately, exactly like before parallelism existed.
        download_sample "$SAMPLE" "$ASM" "$SRA"
    else
        job_slot_wait "$MAX_PARALLEL_SAMPLES"
        download_sample "$SAMPLE" "$ASM" "$SRA" &
        PIDS["$SAMPLE"]=$!
    fi
done < <(read_samples "$SAMPLE_SHEET")

if [[ "$MAX_PARALLEL_SAMPLES" -gt 1 ]]; then
    failed=()
    for sample in "${!PIDS[@]}"; do
        wait "${PIDS[$sample]}" || failed+=("$sample")
    done
    if [[ ${#failed[@]} -gt 0 ]]; then
        die "download failed for: ${failed[*]} (see logs/<sample>.*.log for each)"
    fi
fi

log "Stage 1 (download) complete."
