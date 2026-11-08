#!/usr/bin/env bash
# Stage 2 — build the ground-truth table per sample from the NCBI sequence
# report: which reference sequences are plasmid vs chromosome.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need python3

while IFS=$'\t' read -r SAMPLE _ SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    REF="$SDIR/reference.fna"
    REPORT="$SDIR/sequence_report.jsonl"
    TRUTH="$SDIR/truth.tsv"
    DEPTH="$SDIR/observed_depth.tsv"
    TRUTH_SOURCE="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" truth_source)"
    if [[ -s "$TRUTH" ]]; then
        log "  existing truth.tsv retained for $SAMPLE"
    fi
    if [[ "$TRUTH_SOURCE" == "self_assembled_hybrid" ]]; then
        # No pre-existing assembly to check for -- see build_hybrid_truth.py.
        LONG_READS="$SDIR/${LONG_READS_FILE:-long_reads.fastq.gz}"
        R1="$SDIR/${SRA}_1.fastq.gz"; R2="$SDIR/${SRA}_2.fastq.gz"
        if [[ ! -s "$TRUTH" ]]; then
            if [[ ! -s "$LONG_READS" || ! -s "$R1" || ! -s "$R2" ]]; then
                warn "missing long and/or short reads for self_assembled_hybrid sample $SAMPLE; run 01_download.sh first"
                continue
            fi
            log "=== Building self-assembled hybrid truth for $SAMPLE ==="
            if ! python3 "$HERE/../python/build_hybrid_truth.py" \
                    --long-reads "$LONG_READS" --r1 "$R1" --r2 "$R2" \
                    --out-reference "$REF" --out-truth "$TRUTH" \
                    --out-provenance "$SDIR/truth_provenance.json" \
                    --min-chromosome-length "$HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH" \
                    --threads "$HYBRID_TRUTH_THREADS" 2> >(tee -a "$LOG_DIR/${SAMPLE}.truth.log" >&2); then
                warn "self-assembled hybrid truth build failed for $SAMPLE; see $LOG_DIR/${SAMPLE}.truth.log"
                continue
            fi
            log "  truth -> $TRUTH (self-assembled hybrid; see $SDIR/truth_provenance.json)"
        fi
    else
        [[ -s "$REF" ]] || { warn "missing reference for $SAMPLE; run 01_download.sh first"; continue; }
        if [[ ! -s "$TRUTH" ]]; then
            [[ -s "$REPORT" ]] || { warn "missing sequence report and truth.tsv for $SAMPLE"; continue; }
            log "=== Truth for $SAMPLE ==="
            python3 "$HERE/../python/make_truth.py" --report "$REPORT" --fasta "$REF" --out "$TRUTH" 2> >(tee -a "$LOG_DIR/${SAMPLE}.truth.log" >&2)
            log "  truth -> $TRUTH"
        fi
    fi
    # Validate however the table arrived. A hand-written one is retained as-is,
    # and every way it can be wrong is silent: an id absent from the reference
    # scores as an unrecovered plasmid, a reference sequence absent from the
    # table lets contamination go uncounted, and an unrecognised molecule_type
    # (including an unedited REVIEW) is scored as CHROMOSOME.
    if ! python3 "$HERE/../python/validate_truth_table.py"             --truth "$TRUTH" --reference "$REF" --sample "$SAMPLE"; then
        die "truth table for $SAMPLE is not usable; fix it and re-run (nothing was scored)"
    fi
    # Cohort QC anomaly flagging (advisory-only, see flag_cohort_outliers.sh's
    # invocation at stage 6): stats computed fresh from the actually-downloaded
    # reference, not sourced from NCBI's self-reported assembly metadata.
    STATS="$SDIR/assembly_stats.tsv"
    if [[ -s "$STATS" && "$STATS" -nt "$REF" && "$STATS" -nt "$TRUTH" ]]; then
        log "  assembly stats already computed for $SAMPLE"
    else
        python3 "$HERE/../python/compute_assembly_stats.py" --fasta "$REF" --truth "$TRUTH" --sample-id "$SAMPLE" --out "$STATS" 2>> "$LOG_DIR/${SAMPLE}.truth.log"
    fi
    R1="$SDIR/${SRA}_1.fastq.gz"; R2="$SDIR/${SRA}_2.fastq.gz"
    # Coverage measurement decompresses both FASTQs, so keep stage 2 resumable:
    # recompute only when the reads or truth table are newer than the result.
    if [[ -s "$R1" && -s "$R2" ]]; then
        if [[ -s "$DEPTH" && "$DEPTH" -nt "$R1" && "$DEPTH" -nt "$R2" && "$DEPTH" -nt "$TRUTH" ]]; then
            log "  observed depth already measured for $SAMPLE"
        else
            python3 "$HERE/../python/measure_depth.py" --truth "$TRUTH" --r1 "$R1" --r2 "$R2" --out "$DEPTH"
        fi
    fi
    # read_quality_band (long-read/hybrid analog of read_depth_band): only
    # when a long-read file is actually staged for this sample -- a
    # short-read-only sample simply keeps annotate()'s "not_recorded"
    # default, same convention as every other optional per-isolate feature.
    LONG_READS="$SDIR/${LONG_READS_FILE:-long_reads.fastq.gz}"
    QUALITY="$SDIR/observed_read_quality.tsv"
    if [[ -s "$LONG_READS" ]]; then
        if [[ -s "$QUALITY" && "$QUALITY" -nt "$LONG_READS" ]]; then
            log "  observed read quality already measured for $SAMPLE"
        else
            python3 "$HERE/../python/measure_read_quality.py" --fastq "$LONG_READS" --out "$QUALITY" 2>> "$LOG_DIR/${SAMPLE}.truth.log" || warn "read-quality measurement failed for $SAMPLE; read_quality_band will be not_recorded"
        fi
    fi
    # Derive contextual features from installed annotation callers. A missing
    # caller yields "not evaluated" for its class rather than a false absence.
    FEATURES="$SDIR/truth_features.tsv"
    if [[ "${RUN_REFERENCE_ANNOTATION:-0}" -eq 1 ]]; then
        if [[ -s "$FEATURES" && "$FEATURES" -nt "$REF" ]]; then
            log "  reference annotation already present for $SAMPLE"
        else
            python3 "$HERE/../python/annotate_reference.py" --reference "$REF" --out "$FEATURES"                 --provenance "$SDIR/annotation_provenance.json" --amr-database "$ANNOTATION_AMR_DB"                 --replicon-database "$ANNOTATION_REPLICON_DB"                 >> "$LOG_DIR/${SAMPLE}.annotation.log" 2>&1 ||                 warn "reference annotation failed for $SAMPLE; contextual features are unavailable"
        fi
    fi
    # Evidence-based replicon labels (python/label_truth_evidence.py): confirm
    # each source label with plasmid markers / rRNA / long-read support and
    # mark conflicting replicons AMBIGUOUS. truth.tsv stays complete (the
    # validator above requires it); scoring reads truth.scored.tsv.
    if [[ "${RUN_TRUTH_LABEL_EVIDENCE:-1}" -eq 1 ]]; then
        LR_DEPTH_ARGS=()
        if [[ -s "${LONG_READS:-}" ]] && command -v minimap2 >/dev/null 2>&1; then
            LR_PAF="$SDIR/truth_long_reads.paf"
            if minimap2 --secondary=no -x "$TRUTH_LONG_READ_PRESET" -t "$THREADS" "$REF" "$LONG_READS" \
                    > "$LR_PAF" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
               && python3 "$HERE/../python/long_read_support.py" --paf "$LR_PAF" --truth "$TRUTH" \
                    --out "$SDIR/truth_long_read_depth.tsv" 2>> "$LOG_DIR/${SAMPLE}.truth.log"; then
                LR_DEPTH_ARGS=(--long-read-depth "$SDIR/truth_long_read_depth.tsv"
                               --min-long-read-depth "$TRUTH_MIN_LONG_READ_DEPTH")
            else
                warn "long-read support check failed for $SAMPLE; plasmids are not depth-checked"
            fi
            rm -f "$LR_PAF"
        fi
        SKETCH_ARGS=()
        [[ -s "$PLASMID_REFERENCE_SKETCH" ]] && SKETCH_ARGS=(--plasmid-sketch "$PLASMID_REFERENCE_SKETCH")
        python3 "$HERE/../python/label_truth_evidence.py" --truth "$TRUTH" --reference "$REF" \
            --features "$FEATURES" --annotation-provenance "$SDIR/annotation_provenance.json" \
            "${SKETCH_ARGS[@]}" "${LR_DEPTH_ARGS[@]}" \
            --labels-out "$SDIR/truth_labels.tsv" --scored-truth-out "$SDIR/truth.scored.tsv" \
            2>> "$LOG_DIR/${SAMPLE}.truth.log" \
            || { warn "evidence labelling failed for $SAMPLE; scoring uses source labels"; rm -f "$SDIR/truth.scored.tsv"; }
    fi
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 2 (truth) complete."
