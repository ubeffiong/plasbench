#!/usr/bin/env bash
# Stage 5 — for every predicted-plasmid FASTA: map it back to the reference with
# minimap2 and score it against the truth table. Appends rows to the combined
# scores TSV.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need minimap2
need python3

SCORES="$RESULTS_DIR/scores.tsv"
rm -f "$SCORES"   # rebuild fresh each run

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    RDIR="$RESULTS_DIR/$SAMPLE"
    REF="$SDIR/reference.fna"
    TRUTH="$SDIR/truth.tsv"
    [[ -s "$REF" && -s "$TRUTH" ]] || { warn "missing reference/truth for $SAMPLE"; continue; }
    log "=== Score $SAMPLE ==="

    shopt -s nullglob
    preds=("$RDIR"/pred_*.plasmid.fasta)
    shopt -u nullglob
    if [[ ${#preds[@]} -eq 0 ]]; then
        warn "  no predictions found for $SAMPLE (did stage 4 run?)"
        continue
    fi

    for PRED in "${preds[@]}"; do
        base=$(basename "$PRED")
        tool="${base#pred_}"; tool="${tool%.plasmid.fasta}"
        DONE="$RDIR/.${tool}.complete"
        [[ -e "$DONE" ]] || { warn "  ignoring incomplete $tool result for $SAMPLE"; continue; }
        PAF="$RDIR/${tool}.pred_vs_ref.paf"
        if [[ -s "$PRED" ]]; then
            # Secondary mappings can make repetitive sequence appear to be claimed on
            # multiple reference replicons. Score each prediction from its best hit.
            if ! minimap2 --secondary=no -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$PRED" > "$PAF" 2> "$LOG_DIR/${SAMPLE}.${tool}.minimap2.log"; then
                rm -f "$PAF"; warn "minimap2 failed for $SAMPLE/$tool; excluded from scoring"; continue
            fi
        else
            : > "$PAF"   # tool predicted nothing -> empty PAF (all FN)
        fi
        python3 "$HERE/../python/score_plasmids.py" \
            --truth "$TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            --sample "$SAMPLE" --tool "$tool" --out "$SCORES"
    done
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 5 (score) complete. Combined scores: $SCORES"
