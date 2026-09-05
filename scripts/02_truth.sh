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
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 2 (truth) complete."
