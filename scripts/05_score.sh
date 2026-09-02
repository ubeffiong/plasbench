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
SCORE_FAILURES="$RESULTS_DIR/score_failures.tsv"
printf 'sample\ttool\tstage\treason\n' > "$SCORE_FAILURES"
CAPABILITIES="$PROJECT_ROOT/config/tool_capabilities.tsv"
[[ -s "$CAPABILITIES" ]] || die "tool capability registry missing: $CAPABILITIES"

binning_capable() {
    python3 "$HERE/../python/tool_capabilities.py" --registry "$CAPABILITIES" --tool "$1" --binning-capable >/dev/null
}

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    RDIR="$RESULTS_DIR/$SAMPLE"
    REF="$SDIR/reference.fna"
    TRUTH="$SDIR/truth.tsv"
    AMR="$SDIR/truth_amr.tsv"
    CIRCULAR="$SDIR/truth_circular.tsv"
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
        AMBIGUITY_PAF="$RDIR/${tool}.pred_vs_ref.all.paf"
        AMBIGUITY_ARGS=()
        if [[ -s "$PRED" ]]; then
            # Secondary mappings can make repetitive sequence appear to be claimed on
            # multiple reference replicons. Score each prediction from its best hit.
            if ! minimap2 --secondary=no -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$PRED" > "$PAF" 2> "$LOG_DIR/${SAMPLE}.${tool}.minimap2.log"; then
                rm -f "$PAF"; warn "minimap2 failed for $SAMPLE/$tool; excluded from scoring"; continue
            fi
            if [[ "$REPORT_MAPPING_AMBIGUITY" == "1" ]]; then
                if minimap2 --secondary=yes -N 20 -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$PRED" > "$AMBIGUITY_PAF" 2> "$LOG_DIR/${SAMPLE}.${tool}.minimap2.all.log"; then
                    AMBIGUITY_ARGS=(--ambiguity-paf "$AMBIGUITY_PAF")
                else
                    rm -f "$AMBIGUITY_PAF"
                    warn "secondary-map diagnostic failed for $SAMPLE/$tool; core score retained"
                fi
            fi
        else
            : > "$PAF"   # tool predicted nothing -> empty PAF (all FN)
        fi
        AMR_ARGS=()
        if [[ -s "$AMR" ]]; then
            if ! python3 "$HERE/../python/validate_amr_truth.py" --amr-truth "$AMR" --truth "$TRUTH" >> "$LOG_DIR/${SAMPLE}.${tool}.score.log" 2>&1; then
                warn "curated AMR truth failed validation for $SAMPLE; AMR recovery omitted"
            else
                AMR_ARGS=(--amr-genes "$AMR" --amr-gene-recovery-threshold "$AMR_GENE_RECOVERY_THRESHOLD")
            fi
        fi
        CIRCULAR_ARGS=()
        [[ -s "$CIRCULAR" ]] && CIRCULAR_ARGS=(--circular-plasmids "$CIRCULAR")
        if ! python3 "$HERE/../python/score_plasmids.py" \
            --truth "$TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            --plasmid-recovery-threshold "$PLASMID_RECOVERY_THRESHOLD" \
            --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
            --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
            --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
            --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
            --analysis-track "$ANALYSIS_TRACK" \
            "${AMBIGUITY_ARGS[@]}" \
            "${AMR_ARGS[@]}" \
            "${CIRCULAR_ARGS[@]}" \
            --sample "$SAMPLE" --tool "$tool" --out "$SCORES" \
            2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log"; then
            warn "scoring failed for $SAMPLE/$tool; excluded from aggregation"
            printf '%s\t%s\tscore\t%s\n' "$SAMPLE" "$tool" "see $LOG_DIR/${SAMPLE}.${tool}.score.log" >> "$SCORE_FAILURES"
            continue
        fi
        BINS="$RDIR/pred_${tool}.bins.tsv"
        if [[ -s "$BINS" ]] && binning_capable "$tool"; then
            if ! python3 "$HERE/../python/score_bins.py" --truth "$TRUTH" --paf "$PAF" --bins "$BINS" "${AMBIGUITY_ARGS[@]}" \
                --threshold "$PLASMID_RECOVERY_THRESHOLD" --out "$RDIR/${tool}.bin_matches.tsv" \
                --summary "$RDIR/${tool}.bin_summary.tsv" 2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log"; then
                warn "bin scoring failed for $SAMPLE/$tool; retaining base-level score"
                printf '%s\t%s\tbin_score\t%s\n' "$SAMPLE" "$tool" "see $LOG_DIR/${SAMPLE}.${tool}.score.log" >> "$SCORE_FAILURES"
            fi
        elif [[ -s "$BINS" ]]; then
            # Contig-level classifiers may emit one record per contig, but that
            # is not evidence of a biological plasmid bin.
            rm -f "$RDIR/${tool}.bin_matches.tsv" "$RDIR/${tool}.bin_summary.tsv"
            log "  $tool: bin diagnostics not applicable to declared method class"
        fi
    done
    # Keep retained reference-coordinate blocks separate from the aggregate TSV.
    # The HTML explorer consumes this bounded artifact; it never treats it as a
    # nucleotide alignment or structural-validation result.
    python3 "$HERE/../python/build_visualization_data.py" --truth "$TRUTH" --results-dir "$RESULTS_DIR" \
        --sample "$SAMPLE" --amr-truth "$AMR" --max-blocks-per-tool "$VISUALIZATION_MAX_BLOCKS_PER_TOOL" \
        --out "$RDIR/visualization/alignment_blocks.json" >> "$LOG_DIR/${SAMPLE}.visualization.log" 2>&1 || \
        warn "visualization data generation failed for $SAMPLE; scores are retained"
done < <(read_samples "$SAMPLE_SHEET")

[[ -s "$SCORES" ]] && python3 "$HERE/../python/merge_bin_metrics.py" --scores "$SCORES" --results-dir "$RESULTS_DIR"

log "Stage 5 (score) complete. Combined scores: $SCORES"
