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
            # An unresolvable sequence is written as REVIEW and stops the run at
            # the validator below. ALLOW_DEFAULTED_TRUTH=1 restores the old
            # guess-CHROMOSOME behaviour; use it only after reviewing the warnings.
            TRUTH_ARGS=()
            [[ "${ALLOW_DEFAULTED_TRUTH:-0}" == "1" ]] && TRUTH_ARGS+=(--allow-default)
            python3 "$HERE/../python/make_truth.py" --report "$REPORT" --fasta "$REF" --out "$TRUTH" "${TRUTH_ARGS[@]+"${TRUTH_ARGS[@]}"}" 2> >(tee -a "$LOG_DIR/${SAMPLE}.truth.log" >&2)
            log "  truth -> $TRUTH"
        fi
    fi
    # Tandem-dimer truth plasmids (python/detect_dimers.py; panel edge case D2):
    # with COLLAPSE_DIMERS=1 a plasmid closed as two head-to-tail copies is
    # replaced by its monomer in reference.fna and truth.tsv before anything is
    # scored (original kept as reference.precollapse.fna); with 0 it is only
    # flagged. Every change is listed in truth.corrections.tsv.
    CORRECTIONS="$SDIR/truth.corrections.tsv"
    if [[ "${RUN_DIMER_DETECTION:-1}" -eq 1 && -s "$REF" && -s "$TRUTH" ]]; then
        if [[ -f "$CORRECTIONS" && ! "$CORRECTIONS" -ot "$REF" && ! "$CORRECTIONS" -ot "$TRUTH" ]]; then
            log "  dimer check already done for $SAMPLE"
        else
            DIMER_ARGS=(--min-identity "${DIMER_MIN_IDENTITY:-0.95}" --min-half-coverage "${DIMER_MIN_HALF_COVERAGE:-0.90}")
            [[ "${COLLAPSE_DIMERS:-1}" -eq 1 ]] && DIMER_ARGS+=(--collapse)
            [[ -s "$SDIR/truth_amr.tsv" ]] && DIMER_ARGS+=(--amr-truth "$SDIR/truth_amr.tsv")
            python3 "$HERE/../python/detect_dimers.py" --reference "$REF" --truth "$TRUTH" \
                --out "$CORRECTIONS" "${DIMER_ARGS[@]}" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
                || warn "dimer check failed for $SAMPLE; truth is scored as built"
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
            python3 "$HERE/../python/annotate_reference.py" --reference "$REF" --out "$FEATURES"                 --provenance "$SDIR/annotation_provenance.json" --amr-database "$ANNOTATION_AMR_DB"                 --replicon-database "$ANNOTATION_REPLICON_DB" --isfinder-fasta "${ISFINDER_FASTA:-}"                 >> "$LOG_DIR/${SAMPLE}.annotation.log" 2>&1 ||                 warn "reference annotation failed for $SAMPLE; contextual features are unavailable"
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
        CORRECTION_ARGS=()
        [[ -s "$SDIR/truth.corrections.tsv" ]] && CORRECTION_ARGS=(--multimers "$SDIR/truth.corrections.tsv")
        python3 "$HERE/../python/label_truth_evidence.py" --truth "$TRUTH" --reference "$REF" \
            --features "$FEATURES" --annotation-provenance "$SDIR/annotation_provenance.json" \
            "${SKETCH_ARGS[@]}" "${LR_DEPTH_ARGS[@]}" "${CORRECTION_ARGS[@]+"${CORRECTION_ARGS[@]}"}" \
            --labels-out "$SDIR/truth_labels.tsv" --scored-truth-out "$SDIR/truth.scored.tsv" \
            2>> "$LOG_DIR/${SAMPLE}.truth.log" \
            || { warn "evidence labelling failed for $SAMPLE; scoring uses source labels"; rm -f "$SDIR/truth.scored.tsv"; }
    fi
    # Every replicon's label under the three schemes (python/label_schemes.py):
    # writes truth.nonchromosomal.tsv (Scheme 1) and label_schemes.tsv, pinning
    # the NCBI field and the sequence report's SHA-256 behind Scheme 3 labels.
    MULTIMER_ARGS=()
    [[ -s "$SDIR/truth.corrections.tsv" ]] && MULTIMER_ARGS=(--multimers "$SDIR/truth.corrections.tsv")
    EVIDENCE_ARGS=()
    [[ -s "$SDIR/truth_labels.tsv" ]] && EVIDENCE_ARGS=(--evidence-labels "$SDIR/truth_labels.tsv")
    python3 "$HERE/../python/label_schemes.py" build --sample "$SAMPLE" --truth "$TRUTH"         --report "$REPORT" --truth-source "${TRUTH_SOURCE:-}"         "${EVIDENCE_ARGS[@]+"${EVIDENCE_ARGS[@]}"}" "${MULTIMER_ARGS[@]+"${MULTIMER_ARGS[@]}"}"         --nonchromosomal-out "$SDIR/truth.nonchromosomal.tsv" --out "$SDIR/label_schemes.tsv"         2>> "$LOG_DIR/${SAMPLE}.truth.log"         || warn "label-scheme table failed for $SAMPLE; scheme sensitivity analyses will skip it"
    # Repeat content of the truth (python/repeat_content.py, k-mer idea from GAEMR): the share of each replicon's
    # canonical k-mers that repeat inside it or are shared with the chromosome. A difficulty descriptor and the
    # repeat_rich scenario tag; it never edits truth. RUN_REPEAT_CONTENT=0 skips it.
    if [[ "${RUN_REPEAT_CONTENT:-1}" == "1" && -s "$REF" ]]; then
        python3 "$HERE/../python/repeat_content.py" --reference "$REF" --truth "$TRUTH" --sample "$SAMPLE" \
            --k "$REPEAT_KMER" --out "$SDIR/truth_repeat_content.tsv" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
            || warn "repeat-content analysis failed for $SAMPLE; the repeat_rich tag is unavailable"
    fi
    # Opt-in truth depth anomalies (python/truth_depth_anomalies.py, coverage-anomaly idea from GAEMR): map the
    # benchmark short reads to the truth reference and flag windows whose depth departs from the replicon median by
    # more than DEPTH_ANOMALY_Z robust SD (collapsed repeats, misjoins, integrated elements). Needs minimap2 and samtools.
    if [[ "${RUN_TRUTH_DEPTH_ANOMALIES:-0}" == "1" && -s "$R1" && -s "$R2" && -s "$REF" ]]; then
        if command -v minimap2 >/dev/null 2>&1 && command -v samtools >/dev/null 2>&1; then
            DEPTH_TSV="$SDIR/truth_depth.tsv"
            if minimap2 -ax sr -t "$THREADS" "$REF" "$R1" "$R2" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
                    | samtools sort -@ 2 -o "$SDIR/truth_reads.bam" - 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
               && samtools depth -a "$SDIR/truth_reads.bam" > "$DEPTH_TSV" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
               && python3 "$HERE/../python/truth_depth_anomalies.py" windows --depth-tsv "$DEPTH_TSV" \
                    --window "$DEPTH_WINDOW_BP" --out "$SDIR/truth_depth_windows.tsv" 2>> "$LOG_DIR/${SAMPLE}.truth.log" \
               && python3 "$HERE/../python/truth_depth_anomalies.py" --depth-table "$SDIR/truth_depth_windows.tsv" \
                    --truth "$TRUTH" --sample "$SAMPLE" --z "$DEPTH_ANOMALY_Z" \
                    --out "$SDIR/truth_depth_anomalies.tsv" --summary-out "$SDIR/truth_depth_anomaly_summary.tsv" \
                    2>> "$LOG_DIR/${SAMPLE}.truth.log"; then
                :
            else
                warn "truth depth-anomaly analysis failed for $SAMPLE (see $LOG_DIR/${SAMPLE}.truth.log)"
            fi
            rm -f "$SDIR/truth_reads.bam" "$DEPTH_TSV"
        else
            warn "RUN_TRUTH_DEPTH_ANOMALIES=1 needs minimap2 and samtools; skipped for $SAMPLE"
        fi
    fi
    # Opt-in: draft AMR truth from the AMRFinderPlus rows annotated on the reference.
    # Written as truth_amr.draft.tsv (evidence_tier=auto_derived), never as truth_amr.tsv:
    # a person must review it and rename it before amr_gene_recall is scored.
    if [[ "${DERIVE_AMR_TRUTH_DRAFT:-0}" -eq 1 && -s "$FEATURES" && -s "$SDIR/truth.tsv" ]]; then
        python3 "$HERE/../python/derive_amr_truth.py" --features "$FEATURES" --truth "$SDIR/truth.tsv"             --out "$SDIR/truth_amr.draft.tsv" >> "$LOG_DIR/${SAMPLE}.annotation.log" 2>&1             || warn "AMR truth draft failed for $SAMPLE; amr_gene_recall stays blank"
    fi
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 2 (truth) complete."
