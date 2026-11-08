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
# Per sample*tool job, minimap2 (at $THREADS) and, when enabled, the QUAST
# diagnostics step (at QUAST_DIAGNOSTICS_THREADS) run sequentially -- so the
# job's PEAK thread demand is the max of the two, not their sum. Defaults to
# $THREADS (a no-op here) unless a user overrides QUAST_DIAGNOSTICS_THREADS
# independently higher.
SCORE_STAGE_THREADS="$THREADS"
if [[ "${RUN_QUAST_DIAGNOSTICS:-0}" == "1" && "$QUAST_DIAGNOSTICS_THREADS" -gt "$SCORE_STAGE_THREADS" ]]; then
    SCORE_STAGE_THREADS="$QUAST_DIAGNOSTICS_THREADS"
fi
warn_resource_oversubscription "stage 5 (scoring)" "$MAX_PARALLEL_SAMPLES" "$SCORE_STAGE_THREADS"

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

# Keep only rows of a per-plasmid truth TSV (AMR genes, circular plasmids)
# whose sequence_id is a PLASMID in the scored truth, so a replicon that
# evidence labelling marked AMBIGUOUS cannot fail the curated-truth checks.
filter_to_scored_plasmids() {
    awk -F'\t' -v OFS='\t' '
        NR == FNR { if (FNR > 1 && $2 == "PLASMID") keep[$1] = 1; next }
        FNR == 1 { for (i = 1; i <= NF; i++) if ($i == "sequence_id") col = i; print; next }
        col && ($col in keep)' "$1" "$2" > "$3"
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
    # TRUTH_LABEL_SCHEME picks the scored truth (python/label_schemes.py):
    # ncbi (primary, pre-registered) = truth.tsv; nonchromosomal =
    # truth.nonchromosomal.tsv; evidence = truth.scored.tsv (AMBIGUOUS removed).
    # A missing or stale scheme file falls back to truth.tsv with a warning.
    local SCORE_TRUTH="$TRUTH"
    local SCHEME_FILE=""
    case "${TRUTH_LABEL_SCHEME:-ncbi}" in
        ncbi) ;;
        nonchromosomal) SCHEME_FILE="$SDIR/truth.nonchromosomal.tsv" ;;
        evidence) SCHEME_FILE="$SDIR/truth.scored.tsv" ;;
        *) die "TRUTH_LABEL_SCHEME must be ncbi, nonchromosomal or evidence (got '${TRUTH_LABEL_SCHEME}')" ;;
    esac
    if [[ -n "$SCHEME_FILE" && ! ( -s "$SCHEME_FILE" && ! "$SCHEME_FILE" -ot "$TRUTH" ) ]]; then
        warn "$SAMPLE: no current $(basename "$SCHEME_FILE") for TRUTH_LABEL_SCHEME=${TRUTH_LABEL_SCHEME}; scoring truth.tsv (ncbi)"
        SCHEME_FILE=""
    fi
    if [[ -n "$SCHEME_FILE" ]]; then
        SCORE_TRUTH="$SCHEME_FILE"
        if [[ -s "$AMR" ]]; then
            filter_to_scored_plasmids "$SCORE_TRUTH" "$AMR" "$SDIR/truth_amr.scored.tsv"
            AMR="$SDIR/truth_amr.scored.tsv"
        fi
        if [[ -s "$CIRCULAR" ]]; then
            filter_to_scored_plasmids "$SCORE_TRUTH" "$CIRCULAR" "$SDIR/truth_circular.scored.tsv"
            CIRCULAR="$SDIR/truth_circular.scored.tsv"
        fi
    fi
    log "=== Score $SAMPLE ==="

    # Contig-level classification (python/contig_classification.py): label each
    # short-read assembly contig against truth once per sample, then score every
    # tool on those contigs (count-based and length-weighted P/R/F1/MCC). The
    # same step records how much of each truth plasmid the assembly covers,
    # which score_bins.py uses for assembly-aware binning recall.
    local CONTIGS="$SDIR/contigs.fasta" CONTIG_LABELS="$SDIR/contig_labels.tsv"
    local ASM_COVERAGE="$SDIR/plasmid_assembly_coverage.tsv"
    local CONTIG_READY=0 ASM_COV_ARGS=()
    if [[ "${RUN_CONTIG_CLASSIFICATION:-1}" == "1" && -s "$CONTIGS" ]]; then
        local CONTIG_PARAMS="len=$CONTIG_MIN_LENGTH id=$CONTIG_MIN_IDENTITY cov=$CONTIG_MIN_COVERAGE preset=$MINIMAP2_PRESET"
        if [[ ! -s "$CONTIG_LABELS" || "$CONTIG_LABELS" -ot "$CONTIGS" || "$CONTIG_LABELS" -ot "$SCORE_TRUTH" \
              || "$(cat "$CONTIG_LABELS.params" 2>/dev/null)" != "$CONTIG_PARAMS" ]]; then
            local CONTIG_LOG="$LOG_DIR/${SAMPLE}.contig_classification.log"
            if minimap2 -c --secondary=yes -N 5 -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$CONTIGS" \
                    > "$SDIR/contigs_vs_ref.paf" 2> "$CONTIG_LOG" \
               && python3 "$HERE/../python/contig_classification.py" label --contigs "$CONTIGS" \
                    --paf "$SDIR/contigs_vs_ref.paf" --truth "$SCORE_TRUTH" --labels-out "$CONTIG_LABELS" \
                    --coverage-out "$ASM_COVERAGE" --min-length "$CONTIG_MIN_LENGTH" \
                    --min-identity "$CONTIG_MIN_IDENTITY" --min-coverage "$CONTIG_MIN_COVERAGE" >> "$CONTIG_LOG" 2>&1; then
                printf '%s' "$CONTIG_PARAMS" > "$CONTIG_LABELS.params"
            else
                rm -f "$CONTIG_LABELS" "$CONTIG_LABELS.params" "$ASM_COVERAGE"
                warn "contig labelling failed for $SAMPLE (see $CONTIG_LOG); contig-level metrics omitted"
            fi
            rm -f "$SDIR/contigs_vs_ref.paf"
        fi
        [[ -s "$CONTIG_LABELS" ]] && CONTIG_READY=1
        [[ -s "$ASM_COVERAGE" ]] && ASM_COV_ARGS=(--assembly-coverage "$ASM_COVERAGE")
        # Independent second scorer for the contig layer (python/contig_crosscheck.py):
        # alignment-free k-mer labels, compared with the minimap2 labels in stage 6.
        local KMER_LABELS="$SDIR/contig_labels.kmer.tsv"
        if [[ "${RUN_CONTIG_CROSSCHECK:-1}" == "1" && "$CONTIG_READY" -eq 1 ]] \
                && [[ ! -s "$KMER_LABELS" || "$KMER_LABELS" -ot "$CONTIGS" || "$KMER_LABELS" -ot "$SCORE_TRUTH" ]]; then
            python3 "$HERE/../python/contig_crosscheck.py" label --contigs "$CONTIGS" --reference "$REF" \
                --truth "$SCORE_TRUTH" --out "$KMER_LABELS" --min-length "$CONTIG_MIN_LENGTH" \
                --min-containment "$CONTIG_MIN_COVERAGE" --scaled "${CONTIG_CROSSCHECK_SCALED:-10}" \
                2>> "$LOG_DIR/${SAMPLE}.contig_classification.log" \
                || { rm -f "$KMER_LABELS"; warn "contig cross-check labelling failed for $SAMPLE"; }
        fi
    fi

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

    # Recall ceiling (python/scorable_truth.py): which true-plasmid bases can a
    # prediction be scored on at all under the alignment filters? Built once
    # per sample, rebuilt when the reference, truth or filters change. A
    # failure only drops the diagnostic; scores are unaffected.
    local SCORABLE="$SDIR/truth_scorable.tsv"
    local SCORABLE_ARGS=()
    if [[ "${RUN_SCORABLE_TRUTH:-1}" == "1" ]]; then
        local SCORABLE_PARAMS="window=$SCORABLE_WINDOW_BP step=$SCORABLE_STEP_BP preset=$MINIMAP2_PRESET len=$MIN_ALIGNMENT_LENGTH id=$MIN_ALIGNMENT_IDENTITY mapq=$MIN_ALIGNMENT_MAPQ qcov=$MIN_ALIGNMENT_QUERY_COVERAGE"
        if [[ ! -s "$SCORABLE" || "$SCORABLE" -ot "$REF" || "$SCORABLE" -ot "$SCORE_TRUTH" \
              || "$(cat "$SCORABLE.params" 2>/dev/null)" != "$SCORABLE_PARAMS" ]]; then
            local WINDOWS="$SDIR/truth_plasmid_windows.fa" WINDOWS_PAF="$SDIR/truth_plasmid_windows.paf"
            local SCORABLE_LOG="$LOG_DIR/${SAMPLE}.scorable_truth.log"
            if python3 "$HERE/../python/scorable_truth.py" windows --reference "$REF" --truth "$SCORE_TRUTH" \
                    --out "$WINDOWS" --window "$SCORABLE_WINDOW_BP" --step "$SCORABLE_STEP_BP" > "$SCORABLE_LOG" 2>&1 \
                && minimap2 --secondary=no -c -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$WINDOWS" \
                    > "$WINDOWS_PAF" 2>> "$SCORABLE_LOG" \
                && python3 "$HERE/../python/scorable_truth.py" intervals --paf "$WINDOWS_PAF" --truth "$SCORE_TRUTH" \
                    --out "$SCORABLE.tmp" \
                    --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
                    --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
                    --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
                    --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" >> "$SCORABLE_LOG" 2>&1; then
                mv "$SCORABLE.tmp" "$SCORABLE"
                printf '%s' "$SCORABLE_PARAMS" > "$SCORABLE.params"
            else
                rm -f "$SCORABLE.tmp" "$SCORABLE" "$SCORABLE.params"
                warn "recall-ceiling diagnostic failed for $SAMPLE (see $SCORABLE_LOG); scores are unaffected"
            fi
        fi
        [[ -s "$SCORABLE" ]] && SCORABLE_ARGS=(--scorable-truth "$SCORABLE")
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
            # multiple reference replicons, so --secondary=no keeps only each region's
            # primary placement. A chimeric record still contributes every one of its
            # primary pieces; the scorer also drops any tp:A:S row it is handed. Which
            # copy of a repeat is "primary" is minimap2's arbitrary choice at low MAPQ,
            # which is why the MAPQ filter below, not this flag, protects precision.
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
            if ! python3 "$HERE/../python/validate_amr_truth.py" --amr-truth "$AMR" --truth "$SCORE_TRUTH" >> "$LOG_DIR/${SAMPLE}.${tool}.score.log" 2>&1; then
                warn "curated AMR truth failed validation for $SAMPLE; AMR recovery omitted"
            else
                AMR_ARGS=(--amr-genes "$AMR" --amr-gene-recovery-threshold "$AMR_GENE_RECOVERY_THRESHOLD")
            fi
        fi
        local CIRCULAR_ARGS=()
        [[ -s "$CIRCULAR" ]] && CIRCULAR_ARGS=(--circular-plasmids "$CIRCULAR")
        # Optional PR-curve sweep (adapters/SCORES.md): only when the adapter
        # wrote both a wider candidates universe and a per-record probability
        # for it. A mapping failure here only warns and omits the curve; it
        # never affects the point-estimate score below.
        #
        # Always clear any pr_curve/pr_summary from a PRIOR run first: unlike
        # $PAF above (rebuilt via truncating `>` redirection every pass) and
        # scores.tsv (fully rebuilt at the end of this script), these two
        # files are only written when score_plasmids.py is actually given
        # --pr-curve-out/--pr-summary-out this pass. Skipping that (no
        # candidates/scores this run, or the candidate-PAF mapping below
        # fails) must mean "no curve for this pass" -- not a stale one from a
        # previous successful pass silently re-merged as if it were fresh by
        # merge_pr_metrics.py's unconditional glob.
        local PRSCORE_ARGS=()
        local CANDIDATES="$RDIR/pred_${tool}.candidates.fasta"
        local PRED_SCORES="$RDIR/pred_${tool}.scores.tsv"
        rm -f "$RDIR/${tool}.pr_curve.tsv" "$RDIR/${tool}.pr_summary.tsv" "$RDIR/${tool}.calibration.tsv"
        if [[ -s "$CANDIDATES" && -s "$PRED_SCORES" ]]; then
            local CAND_PAF="$RDIR/${tool}.candidates_vs_ref.paf"
            if minimap2 --secondary=no -c -x "$MINIMAP2_PRESET" -t "$THREADS" "$REF" "$CANDIDATES" \
                    > "$CAND_PAF" 2> "$LOG_DIR/${SAMPLE}.${tool}.candidates.minimap2.log"; then
                PRSCORE_ARGS=(--pred-scores "$PRED_SCORES" --pred-candidates-fasta "$CANDIDATES" \
                              --pred-candidates-paf "$CAND_PAF" \
                              --pr-curve-out "$RDIR/${tool}.pr_curve.tsv" \
                              --pr-summary-out "$RDIR/${tool}.pr_summary.tsv" \
                              --calibration-out "$RDIR/${tool}.calibration.tsv")
            else
                warn "candidate-set mapping failed for $SAMPLE/$tool; PR curve omitted, point score retained"
            fi
        fi
        if ! python3 "$HERE/../python/score_plasmids.py" \
            --truth "$SCORE_TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            --plasmid-recovery-threshold "$PLASMID_RECOVERY_THRESHOLD" \
            --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
            --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
            --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
            --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
            --analysis-track "$TOOL_TRACK" \
            "${AMBIGUITY_ARGS[@]}" \
            "${AMR_ARGS[@]}" \
            "${CIRCULAR_ARGS[@]}" \
            "${SCORABLE_ARGS[@]}" \
            "${PRSCORE_ARGS[@]}" \
            --per-plasmid-out "$RDIR/${tool}.per_plasmid.tsv" \
            --sample "$SAMPLE" --tool "$tool" --out "$SCORE_SHARD" \
            2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log"; then
            warn "scoring failed for $SAMPLE/$tool; excluded from aggregation"
            printf '%s\t%s\tscore\t%s\n' "$SAMPLE" "$tool" "see $LOG_DIR/${SAMPLE}.${tool}.score.log" >> "$FAILURE_SHARD"
            continue
        fi
        rm -f "$RDIR/${tool}.contig_classification.tsv"
        if [[ "$CONTIG_READY" -eq 1 ]]; then
            local CONTIG_BIN_ARGS=()
            [[ -s "$RDIR/pred_${tool}.bins.tsv" ]] && binning_capable "$tool" \
                && CONTIG_BIN_ARGS=(--bins "$RDIR/pred_${tool}.bins.tsv")
            python3 "$HERE/../python/contig_classification.py" score --labels "$CONTIG_LABELS" --pred-fasta "$PRED" \
                "${CONTIG_BIN_ARGS[@]+"${CONTIG_BIN_ARGS[@]}"}" \
                --min-length "$CONTIG_MIN_LENGTH" --out "$RDIR/${tool}.contig_classification.tsv" \
                2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log" || warn "contig-level scoring failed for $SAMPLE/$tool"
        fi
        local BINS="$RDIR/pred_${tool}.bins.tsv"
        if [[ -s "$BINS" ]] && binning_capable "$tool"; then
            if ! python3 "$HERE/../python/score_bins.py" --truth "$SCORE_TRUTH" --paf "$PAF" --bins "$BINS" "${AMBIGUITY_ARGS[@]}" "${ASM_COV_ARGS[@]}" \
                --threshold "$PLASMID_RECOVERY_THRESHOLD" --out "$RDIR/${tool}.bin_matches.tsv" \
                --min-alignment-length "$MIN_ALIGNMENT_LENGTH" \
                --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
                --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
                --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
                --cprr-out "$RDIR/${tool}.cprr.tsv" \
                --outcomes-out "$RDIR/${tool}.plasmid_outcomes.tsv" \
                --perfect-threshold "${PERFECT_THRESHOLD:-0.95}" --fragment-share "${FRAGMENT_SHARE:-0.20}" \
                --missed-recall "${MISSED_RECALL:-0.50}" \
                --cprr-min-coverage "$CPRR_MIN_COVERAGE" \
                --cprr-min-share "$CPRR_MIN_SHARE" \
                --cprr-min-identity "$CPRR_MIN_IDENTITY" \
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
        # AMR placement (python/score_amr_placement.py): is each curated AMR gene copy
        # placed on its own plasmid (level 2) and a plasmid of the same replicon type
        # (level 1)? Only with validated curated AMR truth (AMR_ARGS set above).
        rm -f "$RDIR/${tool}.amr_placement.tsv"
        if [[ "${RUN_AMR_PLACEMENT:-1}" -eq 1 && ${#AMR_ARGS[@]} -gt 0 ]]; then
            local PLACEMENT_ARGS=()
            [[ -s "$BINS" ]] && binning_capable "$tool" && PLACEMENT_ARGS+=(--bins "$BINS")
            [[ -s "$CONTIG_LABELS" ]] && PLACEMENT_ARGS+=(--contig-labels "$CONTIG_LABELS")
            [[ -s "$FEATURES" ]] && PLACEMENT_ARGS+=(--features "$FEATURES")
            python3 "$HERE/../python/score_amr_placement.py" score --sample "$SAMPLE" --tool "$tool" \
                --truth "$SCORE_TRUTH" --amr-truth "$AMR" --paf "$PAF" --pred-fasta "$PRED" \
                "${PLACEMENT_ARGS[@]+"${PLACEMENT_ARGS[@]}"}" \
                --min-alignment-length "$MIN_ALIGNMENT_LENGTH" --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY" \
                --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ" \
                --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE" \
                --out "$RDIR/${tool}.amr_placement.tsv" 2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log" \
                || warn "AMR placement failed for $SAMPLE/$tool"
        fi
        # Further dimensions of the same run (advisory; never alter scores.tsv): nucleotide-level
        # accuracy and missing regions, feature preservation and gene-order conservation, and
        # quality-tier bins. Written as per-run shard files and merged in stage 6, so parallel
        # jobs never write one shared file. RUN_DIMENSION_ANALYSES=0 skips them.
        if [[ "${RUN_DIMENSION_ANALYSES:-1}" -eq 1 ]]; then
            local DIM_FILTERS=(--min-alignment-length "$MIN_ALIGNMENT_LENGTH"
                               --min-alignment-identity "$MIN_ALIGNMENT_IDENTITY"
                               --min-alignment-mapq "$MIN_ALIGNMENT_MAPQ"
                               --min-alignment-query-coverage "$MIN_ALIGNMENT_QUERY_COVERAGE")
            rm -f "$RDIR/${tool}.accuracy.tsv" "$RDIR/${tool}.missing_regions.tsv" \
                  "$RDIR/${tool}.feature_preservation.tsv" "$RDIR/${tool}.ngoc.tsv" "$RDIR/${tool}.bin_quality.tsv"
            python3 "$HERE/../python/alignment_accuracy.py" --truth "$SCORE_TRUTH" --paf "$PAF" \
                --sample "$SAMPLE" --tool "$tool" --analysis-track "$TOOL_TRACK" "${DIM_FILTERS[@]}" \
                --out "$RDIR/${tool}.accuracy.tsv" --regions-out "$RDIR/${tool}.missing_regions.tsv" \
                2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log" || \
                warn "accuracy analysis failed for $SAMPLE/$tool; base-level score is retained"
            # The protein/gene table is preferred over the landmark table: using both would count the
            # same replicon or AMR gene twice under two names.
            local FEATURE_TABLE=""
            if [[ -s "$TRUTH_PROTEINS" ]]; then FEATURE_TABLE="$TRUTH_PROTEINS"
            elif [[ -s "$FEATURES" ]]; then FEATURE_TABLE="$FEATURES"; fi
            if [[ -n "$FEATURE_TABLE" ]]; then
                python3 "$HERE/../python/feature_preservation.py" --truth "$SCORE_TRUTH" --paf "$PAF" \
                    --features "$FEATURE_TABLE" "${CIRCULAR_ARGS[@]}" \
                    --sample "$SAMPLE" --tool "$tool" --analysis-track "$TOOL_TRACK" "${DIM_FILTERS[@]}" \
                    --out "$RDIR/${tool}.feature_preservation.tsv" --ngoc-out "$RDIR/${tool}.ngoc.tsv" \
                    2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log" || \
                    warn "feature-preservation analysis failed for $SAMPLE/$tool; base-level score is retained"
            fi
            if [[ -s "$BINS" ]] && binning_capable "$tool"; then
                python3 "$HERE/../python/bin_quality.py" --truth "$SCORE_TRUTH" --paf "$PAF" --bins "$BINS" \
                    --sample "$SAMPLE" --tool "$tool" --analysis-track "$TOOL_TRACK" "${DIM_FILTERS[@]}" \
                    --out "$RDIR/${tool}.bin_quality.tsv" \
                    2>> "$LOG_DIR/${SAMPLE}.${tool}.score.log" || \
                    warn "bin-quality analysis failed for $SAMPLE/$tool; base-level score is retained"
            fi
        fi
        if [[ "${RUN_QUAST_DIAGNOSTICS:-0}" -eq 1 ]]; then
            python3 "$HERE/../python/run_quast_diagnostics.py" --query "$PRED" --reference "$REF" --truth "$TRUTH" \
                --sample "$SAMPLE" --tool "$tool" --out "$RDIR/${tool}.quast_diagnostics.tsv" \
                --threads "$QUAST_DIAGNOSTICS_THREADS" --min-contig "$QUAST_DIAGNOSTICS_MIN_CONTIG" \
                >> "$LOG_DIR/${SAMPLE}.${tool}.quast.log" 2>&1 || \
                warn "QUAST diagnostics failed for $SAMPLE/$tool; base-level score is retained"
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
[[ -s "$SCORES" ]] && python3 "$HERE/../python/merge_pr_metrics.py" --scores "$SCORES" --results-dir "$RESULTS_DIR"
[[ -s "$SCORES" ]] && python3 "$HERE/../python/contig_classification.py" merge --scores "$SCORES" --results-dir "$RESULTS_DIR"

# Merge every per-sample-per-tool QUAST diagnostics file into one combined
# TSV, same "first non-empty file's header, then every file's data rows"
# convention as the score-shard merge above. Each file already carries its
# own header (written unconditionally by run_quast_diagnostics.py, even for
# a tool with zero comparisons), so an empty-of-DATA file still contributes
# its header if it happens to be first, harmlessly.
if [[ "${RUN_QUAST_DIAGNOSTICS:-0}" -eq 1 ]]; then
    QUAST_DIAGNOSTICS="$RESULTS_DIR/quast_diagnostics.tsv"
    : > "$QUAST_DIAGNOSTICS"
    header_written=0
    shopt -s nullglob
    for shard in "$RESULTS_DIR"/*/*.quast_diagnostics.tsv; do
        if [[ "$header_written" -eq 0 ]]; then
            cat "$shard" >> "$QUAST_DIAGNOSTICS"; header_written=1
        else
            tail -n +2 "$shard" >> "$QUAST_DIAGNOSTICS"
        fi
    done
    shopt -u nullglob
fi

log "Stage 5 (score) complete. Combined scores: $SCORES"
