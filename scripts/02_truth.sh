#!/usr/bin/env bash
# Stage 2 — build the ground-truth table per sample from the NCBI sequence
# report: which reference sequences are plasmid vs chromosome.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need python3

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    REF="$SDIR/reference.fna"
    REPORT="$SDIR/sequence_report.jsonl"
    TRUTH="$SDIR/truth.tsv"
    DEPTH="$SDIR/observed_depth.tsv"
    [[ -s "$REF" ]] || { warn "missing reference for $SAMPLE; run 01_download.sh first"; continue; }
    if [[ -s "$TRUTH" ]]; then
        log "  existing truth.tsv retained for $SAMPLE"
    fi
    if [[ ! -s "$TRUTH" ]]; then
        [[ -s "$REPORT" ]] || { warn "missing sequence report and truth.tsv for $SAMPLE"; continue; }
        log "=== Truth for $SAMPLE ==="
        python3 "$HERE/../python/make_truth.py" --report "$REPORT" --fasta "$REF" --out "$TRUTH" 2> >(tee -a "$LOG_DIR/${SAMPLE}.truth.log" >&2)
        log "  truth -> $TRUTH"
    fi
    R1="$SDIR/${SRA}_1.fastq.gz"; R2="$SDIR/${SRA}_2.fastq.gz"
    [[ -s "$R1" && -s "$R2" ]] && python3 "$HERE/../python/measure_depth.py" --truth "$TRUTH" --r1 "$R1" --r2 "$R2" --out "$DEPTH"
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 2 (truth) complete."
