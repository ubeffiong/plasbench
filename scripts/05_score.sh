#!/usr/bin/env bash
# Stage 5 — for every predicted-plasmid FASTA: map it back to the reference with
# minimap2 and score it against the truth table. Appends rows to the combined
# scores TSV.
#
# Parallelism (config/config.sh: MAX_PARALLEL_SAMPLES): scoring is lightweight
# (one minimap2 call plus pure-Python scoring per tool), so this is normally
# safe to run at higher concurrency than reconstruction. Every sample already
# tolerates a failed tool without aborting (this stage never calls die()), so
# there is no fail-fast behavior to preserve here the way stages 1 and 3
# have -- samples are always run through the same job pool, and at the
# default MAX_PARALLEL_SAMPLES=1 that pool serializes them exactly as before.
# Each sample writes its score/failure rows to a private shard instead of
# appending straight to the shared scores.tsv/score_failures.tsv, since
# score_plasmids.py's own "write a header if this file is new" check would
# race across concurrent processes targeting the same shared file.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need minimap2
need python3
warn_resource_oversubscription "stage 5 (scoring)" "$MAX_PARALLEL_SAMPLES" "$THREADS"

SCORES="$RESULTS_DIR/scores.tsv"
SCORE_FAILURES="$RESULTS_DIR/score_failures.tsv"
CAPABILITIES="$PROJECT_ROOT/config/tool_capabilities.tsv"
[[ -s "$CAPABILITIES" ]] || die "tool capability registry missing: $CAPABILITIES"
reset_shard_dir "score"
reset_shard_dir "score_failures"
SCORE_SHARDS="$(shard_dir "score")"
FAILURE_SHARDS="$(shard_dir "score_failures")"

binning_capable() {
    python3 "$HERE/../python/tool_capabilities.py" --registry "$CAPABILITIES" --tool "$1" --binning-capable >/dev/null
}

# Each tool's own declared track (config/tool_capabilities.tsv), not one value
# blanket-applied to every tool in this run -- see the module header comment
# in scripts/07_long_read_reconstruct.sh for why that used to be unsafe: a
# single global --analysis-track re-stamped every already-scored tool's rows
# on each stage-5 rebuild, not just the tool it was intended for.
tool_analysis_track() {
    python3 "$HERE/../python/tool_capabilities.py" --registry "$CAPABILITIES" --tool "$1" --analysis-track 2>/dev/null
}

score_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    local RDIR="$RESULTS_DIR/$SAMPLE"
    local REF="$SDIR/reference.fna"
    local TRUTH="$SDIR/truth.tsv"
    local AMR="$SDIR/truth_amr.tsv"
    local CIRCULAR="$SDIR/truth_circular.tsv"
    local FEATURES="$SDIR/truth_features.tsv"
    local TRUTH_PROTEINS="$SDIR/truth_proteins.tsv"
    local SCORE_SHARD="$SCORE_SHARDS/${SAMPLE}.tsv"
    local FAILURE_SHARD="$FAILURE_SHARDS/${SAMPLE}.tsv"
    [[ -s "$REF" && -s "$TRUTH" ]] || { warn "missing reference/truth for $SAMPLE"; return 0; }
    log "=== Score $SAMPLE ==="

    local preds
    shopt -s nullglob
    preds=("$RDIR"/pred_*.plasmid.fasta)
    shopt -u nullglob
    if [[ ${#preds[@]} -eq 0 ]]; then
        warn "  no predictions found for $SAMPLE (did stage 4 run?)"
        return 0
    fi

    local CACHE PROTEIN_DB_ARGS
    if [[ "${RUN_PROTEIN_ANNOTATION:-0}" -eq 1 ]]; then
        CACHE="$RESULTS_DIR/.protein_annotation_cache"
        PROTEIN_DB_ARGS=()
        [[ -n "${PROTEIN_ANNOTATION_DATABASE:-}" ]] && PROTEIN_DB_ARGS=(--database "$PROTEIN_ANNOTATION_DATABASE")
        if [[ ! -s "$TRUTH_PROTEINS" || "$TRUTH_PROTEINS" -ot "$REF" ]]; then
            python3 "$HERE/../python/annotate_proteins.py" --fasta "$REF" --out "$TRUTH_PROTEINS" \
                --provenance "$SDIR/truth_proteins.provenance.json" --engine "$PROTEIN_ANNOTATION_ENGINE" \
                --cache-dir "$CACHE" --threads "$PROTEIN_ANNOTATION_THREADS" --minimum-bp "$PROTEIN_ANNOTATION_MIN_BP" "${PROTEIN_DB_ARGS[@]}" \
                >> "$LOG_DIR/${SAMPLE}.protein_annotation.log" 2>&1 || warn "truth protein annotation failed for $SAMPLE"
        fi
    fi

    local PRED
    for PRED in "${preds[@]}"; do
        local base tool DONE
        base=$(basename "$PRED")
        tool="${base#pred_}"; tool="${tool%.plasmid.fasta}"
        DONE="$RDIR/.${tool}.complete"
        [[ -e "$DONE" ]] || { warn "  ignoring incomplete $tool result for $SAMPLE"; continue; }
        local TOOL_TRACK
        TOOL_TRACK="$(tool_analysis_track "$tool" || true)"
        if [[ -z "$TOOL_TRACK" ]]; then
            warn "  $tool: no analysis_track declared in $CAPABILITIES; scoring under \$ANALYSIS_TRACK=$ANALYSIS_TRACK"
            TOOL_TRACK="$ANALYSIS_TRACK"
        fi
        if [[ -n "${ANALYSIS_TRACK_FILTER:-}" && "$TOOL_TRACK" != "$ANALYSIS_TRACK_FILTER" ]]; then
            log "  $tool: excluded from this run (analysis_track=$TOOL_TRACK, filter=$ANALYSIS_TRACK_FILTER)"
            continue
        fi
        if [[ "${RUN_PROTEIN_ANNOTATION:-0}" -eq 1 ]]; then
            local PROTEINS="$RDIR/${tool}.proteins.tsv"
            if [[ ! -s "$PROTEINS" || "$PROTEINS" -ot "$PRED" ]]; then
                python3 "$HERE/../python/annotate_proteins.py" --fasta "$PRED" --out "$PROTEINS" \
                    --provenance "$RDIR/${tool}.proteins.provenance.json" --engine "$PROTEIN_ANNOTATION_ENGINE" \
                    --cache-dir "$CACHE" --threads "$PROTEIN_ANNOTATION_THREADS" --minimum-bp "$PROTEIN_ANNOTATION_MIN_BP" "${PROTEIN_DB_ARGS[@]}" \
                    >> "$LOG_DIR/${SAMPLE}.${tool}.protein_annotation.log" 2>&1 || warn "protein annotation failed for $SAMPLE/$tool"
            fi
        fi
        local PAF="$RDIR/${tool}.pred_vs_ref.paf"
        local AMBIGUITY_PAF="$RDIR/${tool}.pred_vs_ref.all.paf"
        local AMBIGUITY_ARGS=()
        if [[ -s "$PRED" ]]; then
            # Secondary mappings can make repetitive sequence appear to be claimed on
            # multiple reference replicons. Score each prediction from its best hit.
            if ! minimap2 --secondary=no -c -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$PRED" > "$PAF" 2> "$LOG_DIR/${SAMPLE}.${tool}.minimap2.log"; then
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
        local AMR_ARGS=()
        if [[ -s "$AMR" ]]; then
            if ! python3 "$HERE/../python/validate_amr_truth.py" --amr-truth "$AMR" --truth "$TRUTH" >> "$LOG_DIR/${SAMPLE}.${tool}.score.log" 2>&1; then
                warn "curated AMR truth failed validation for $SAMPLE; AMR recovery omitted"
            else
                AMR_ARGS=(--amr-genes "$AMR" --amr-gene-recovery-threshold "$AMR_GENE_RECOVERY_THRESHOLD")
            fi
        fi
        local CIRCULAR_ARGS=()
        [[ -s "$CIRCULAR" ]] && CIRCULAR_ARGS=(--circular-plasmids "$CIRCULAR")
        if ! python3 "$HERE/../python/score_plasmids.py" \
            --truth "$TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            --plasmid-recovery-threshold "$PLASMID_RECOVERY_THRESHOLD" \
            --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
            --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
            --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
            --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
            --analysis-track "$TOOL_TRACK" \
            "${AMBIGUITY_ARGS[@]}" \
            "${AMR_ARGS[@]}" \
            "${CIRCULAR_ARGS[@]}" \
            --sample "$SAMPLE" --tool "$tool" --out "$SCORE_SHARD" \
            2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log"; then
            warn "scoring failed for $SAMPLE/$tool; excluded from aggregation"
            printf '%s\t%s\tscore\t%s\n' "$SAMPLE" "$tool" "see $LOG_DIR/${SAMPLE}.${tool}.score.log" >> "$FAILURE_SHARD"
            continue
        fi
        local BINS="$RDIR/pred_${tool}.bins.tsv"
        if [[ -s "$BINS" ]] && binning_capable "$tool"; then
            if ! python3 "$HERE/../python/score_bins.py" --truth "$TRUTH" --paf "$PAF" --bins "$BINS" "${AMBIGUITY_ARGS[@]}" \
                --threshold "$PLASMID_RECOVERY_THRESHOLD" --out "$RDIR/${tool}.bin_matches.tsv" \
                --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
                --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
                --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
                --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
                --summary "$RDIR/${tool}.bin_summary.tsv" 2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log"; then
                warn "bin scoring failed for $SAMPLE/$tool; retaining base-level score"
                printf '%s\t%s\tbin_score\t%s\n' "$SAMPLE" "$tool" "see $LOG_DIR/${SAMPLE}.${tool}.score.log" >> "$FAILURE_SHARD"
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
    # Typed structural discordance calls with evidence, alongside the bounded
    # display payload. These are alignment-derived, not validated misassemblies.
    python3 "$HERE/../python/call_structural_variants.py" --truth "$TRUTH" --results-dir "$RESULTS_DIR" \
        --sample "$SAMPLE" --events-out "$RDIR/structural_events.tsv" \
        --summary-out "$RDIR/structural_summary.tsv" \
        --json-out "$RDIR/visualization/structural_calls.json" \
        >> "$LOG_DIR/${SAMPLE}.visualization.log" 2>&1 || \
        warn "structural calling failed for $SAMPLE; scores are retained"
    python3 "$HERE/../python/build_visualization_data.py" --truth "$TRUTH" --reference "$REF" --results-dir "$RESULTS_DIR" \
        --sample "$SAMPLE" --amr-truth "$AMR" --feature-truth "$FEATURES" --protein-truth "$TRUTH_PROTEINS" --circular-truth "$CIRCULAR" --max-blocks-per-tool "$VISUALIZATION_MAX_BLOCKS_PER_TOOL" --max-nucleotide-bp "$VISUALIZATION_MAX_NUCLEOTIDE_ALIGNMENT_BP" \
        --out "$RDIR/visualization/alignment_blocks.json" --structural-out "$RDIR/visualization/structural_metrics.tsv" >> "$LOG_DIR/${SAMPLE}.visualization.log" 2>&1 || \
        warn "visualization data generation failed for $SAMPLE; scores are retained"
}

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    job_slot_wait "$MAX_PARALLEL_SAMPLES"
    score_sample "$SAMPLE" "$ASM" "$SRA" &
done < <(read_samples "$SAMPLE_SHEET")
wait

# Merge per-sample score shards. Each carries its own header (written by the
# first score_plasmids.py call for that sample), so the header is taken from
# the first non-empty shard only; every other shard contributes data rows.
: > "$SCORES"
header_written=0
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    shard="$SCORE_SHARDS/${SAMPLE}.tsv"
    if [[ -s "$shard" ]]; then
        if [[ "$header_written" -eq 0 ]]; then
            cat "$shard" >> "$SCORES"; header_written=1
        else
            tail -n +2 "$shard" >> "$SCORES"
        fi
    fi
done < <(read_samples "$SAMPLE_SHEET")

failure_shards=()
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    failure_shards+=("$FAILURE_SHARDS/${SAMPLE}.tsv")
done < <(read_samples "$SAMPLE_SHEET")
merge_shards "$SCORE_FAILURES" "$(printf 'sample\ttool\tstage\treason')" "${failure_shards[@]}"
rm -rf "$SCORE_SHARDS" "$FAILURE_SHARDS"

[[ -s "$SCORES" ]] && python3 "$HERE/../python/merge_bin_metrics.py" --scores "$SCORES" --results-dir "$RESULTS_DIR"

log "Stage 5 (score) complete. Combined scores: $SCORES"
