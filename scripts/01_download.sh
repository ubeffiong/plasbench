#!/usr/bin/env bash
# Stage 1 — download, per sample:
#   (a) the COMPLETE reference assembly + its sequence report (ground truth)
#   (b) the matched Illumina reads from SRA
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

need datasets
need prefetch
need fasterq-dump

[[ -f "$SAMPLE_SHEET" ]] || die "sample sheet not found: $SAMPLE_SHEET"

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    mkdir -p "$SDIR"
    log "=== Sample $SAMPLE : assembly=$ASM  reads=$SRA ==="

    # ---- (a) reference assembly + sequence report ----
    REF="$SDIR/reference.fna"
    REPORT="$SDIR/sequence_report.jsonl"
    if [[ -s "$REF" && -s "$REPORT" ]]; then
        log "  reference already present, skipping download"
    else
        log "  downloading assembly $ASM ..."
        ZIP="$SDIR/ncbi.zip"
        datasets download genome accession "$ASM" \
            --include genome,seq-report \
            --filename "$ZIP" 2> "$LOG_DIR/${SAMPLE}.datasets.log" \
            || die "datasets download failed for $ASM (see $LOG_DIR/${SAMPLE}.datasets.log)"
        rm -rf "$SDIR/ncbi"; mkdir -p "$SDIR/ncbi"
        unzip -o -q "$ZIP" -d "$SDIR/ncbi"
        # locate the genomic FASTA and the sequence report inside the bundle
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
    R1="$SDIR/${SRA}_1.fastq.gz"
    R2="$SDIR/${SRA}_2.fastq.gz"
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
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 1 (download) complete."
