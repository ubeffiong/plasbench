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
    [[ -s "$REF" && -s "$REPORT" ]] || { warn "missing reference/report for $SAMPLE; run 01_download.sh first"; continue; }
    log "=== Truth for $SAMPLE ==="
    python3 "$HERE/../python/make_truth.py" \
        --report "$REPORT" --fasta "$REF" --out "$TRUTH" \
        2> >(tee -a "$LOG_DIR/${SAMPLE}.truth.log" >&2)
    log "  truth -> $TRUTH"
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 2 (truth) complete."
