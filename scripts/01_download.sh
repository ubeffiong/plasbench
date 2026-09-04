#!/usr/bin/env bash
# Stage 1 — download, per sample:
#   (a) the COMPLETE reference assembly + its sequence report (ground truth)
#   (b) the matched Illumina reads from SRA
#
# A sample whose download fails is RECORDED and SKIPPED, not fatal: one
# transient SRA error must not discard hours of successful downloads in a
# 32-sample cohort. Failures land in results/download_status.tsv; stage 3
# skips a sample with no reads and stage 4 records its tools as skipped --
# the same contract those stages already follow. This stage aborts only if NO
# sample downloaded at all, since then there is nothing to benchmark.
#
# Every fetch is retried (config/config.sh: NETWORK_RETRIES) before a sample is
# given up on.
#
# Parallelism (config/config.sh: MAX_PARALLEL_SAMPLES): downloads are network-
# bound, not CPU-bound, so this is usually the safest stage to raise well
# above the reconstruction-stage concurrency.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

[[ -f "$SAMPLE_SHEET" ]] || die "sample sheet not found: $SAMPLE_SHEET"
warn_resource_oversubscription "stage 1 (download)" "$MAX_PARALLEL_SAMPLES" "$THREADS"

STATUS="$RESULTS_DIR/download_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR"
reset_shard_dir "download"
STATUS_SHARDS="$(shard_dir "download")"

# One shard file per sample, so concurrent jobs never contend for one file.
record_download() {
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" > "$STATUS_SHARDS/$1.tsv"
}

# Show what this run is about to fetch, and get consent, before fetching it.
# A cohort download is tens of gigabytes and hours long; a user should see the
# number first rather than learn it from a full disk. Skipped when there is
# nothing to download, when stdin is not a terminal (CI, nohup, a container),
# or when DOWNLOAD_CONFIRM=0.
confirm_download() {
    local estimate reply
    # Asked not to confirm? Then do not spend time computing an estimate for a
    # prompt that will never be shown.
    if [[ "${DOWNLOAD_CONFIRM:-1}" -ne 1 ]]; then
        return 0
    fi
    estimate="$(python3 "$HERE/../python/estimate_download.py" \
                    --samples "$SAMPLE_SHEET" --data-dir "$DATA_DIR" 2>/dev/null || true)"
    [[ -z "$estimate" ]] && return 0
    printf '%s\n' "$estimate"
    case "$estimate" in
        *"nothing to fetch"*|*"nothing to download"*) return 0 ;;
    esac
    if [[ ! -t 0 ]]; then
        log "Not an interactive terminal; proceeding with the download."
        return 0
    fi
    reply=""
    read -r -p "Download these files now? [y/N] " reply || true
    case "$reply" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) die "Download declined. Nothing was fetched." ;;
    esac
}

download_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    mkdir -p "$SDIR"
    log "=== Sample $SAMPLE : assembly=$ASM  reads=$SRA ==="
    local REF="$SDIR/reference.fna"
    local REPORT="$SDIR/sequence_report.jsonl"
    local R1="$SDIR/${SRA}_1.fastq.gz"
    local R2="$SDIR/${SRA}_2.fastq.gz"
    # An operational sample with no known truth reference leaves this column
    # blank (or "NA"): it has reads to reconstruct from but no complete
    # assembly to score against, so skip the reference/sequence-report half
    # of this stage entirely and fetch reads only.
    local HAS_REFERENCE=1
    [[ -z "$ASM" || "$ASM" == "NA" ]] && HAS_REFERENCE=0

    if [[ "$LOCAL_INPUTS_ONLY" == "1" ]]; then
        local missing=()
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            [[ -s "$REF" ]] || missing+=("$REF")
            [[ -s "$REPORT" || -s "$SDIR/truth.tsv" ]] || missing+=("$REPORT or $SDIR/truth.tsv")
        fi
        [[ -s "$R1" ]] || missing+=("$R1")
        [[ -s "$R2" ]] || missing+=("$R2")
        if [[ ${#missing[@]} -gt 0 ]]; then
            die "local-inputs mode is missing for $SAMPLE: ${missing[*]}"
        fi
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            log "  local reference, truth/report, and paired reads verified; download skipped"
        else
            log "  local paired reads verified (no accession: reference/truth skipped); download skipped"
        fi
        return 0
    fi

    # Download clients are only required when this sample actually needs them.
    [[ "$HAS_REFERENCE" -eq 1 ]] && need datasets
    need prefetch
    need fasterq-dump

    # ---- (a) reference assembly + sequence report ----
    if [[ "$HAS_REFERENCE" -eq 0 ]]; then
        log "  no assembly_accession given; skipping reference download (operational sample)"
    elif [[ -s "$REF" && -s "$REPORT" ]]; then
        log "  reference already present, skipping download"
    else
        log "  downloading assembly $ASM ..."
        local ZIP="$SDIR/ncbi.zip"
        if ! retry_network "datasets download for $ASM" \
                datasets download genome accession "$ASM" \
                --include genome,seq-report,gff3 \
                --filename "$ZIP" 2> "$LOG_DIR/${SAMPLE}.datasets.log"; then
            warn "reference download failed for $SAMPLE; skipping this sample"
            record_download "$SAMPLE" "failed" "datasets download failed for $ASM; see $LOG_DIR/${SAMPLE}.datasets.log"
            return 0
        fi
        rm -rf "$SDIR/ncbi"; mkdir -p "$SDIR/ncbi"
        unzip -o -q "$ZIP" -d "$SDIR/ncbi"
        # locate the genomic FASTA and the sequence report inside the bundle
        local FNA SR
        FNA=$(find "$SDIR/ncbi" -name '*_genomic.fna' -o -name '*.fna' | head -n1)
        SR=$(find "$SDIR/ncbi" -name 'sequence_report.jsonl' | head -n1)
        if [[ ! -s "$FNA" ]]; then
            warn "no genomic FASTA in the bundle for $ASM; skipping $SAMPLE"
            record_download "$SAMPLE" "failed" "no genomic FASTA in bundle for $ASM"
            return 0
        fi
        if [[ ! -s "$SR" ]]; then
            warn "no sequence_report.jsonl for $ASM; skipping $SAMPLE (truth labels need it)"
            record_download "$SAMPLE" "failed" "no sequence_report.jsonl for $ASM"
            return 0
        fi
        cp "$FNA" "$REF"
        cp "$SR" "$REPORT"
        rm -f "$ZIP"
        log "  reference -> $REF"
    fi

    # ---- (b) Illumina reads ----
    if [[ -s "$R1" && -s "$R2" ]]; then
        log "  reads already present, skipping download"
    else
        log "  prefetching $SRA ..."
        if ! retry_network "prefetch $SRA" \
                prefetch -O "$SDIR" "$SRA" > "$LOG_DIR/${SAMPLE}.prefetch.log" 2>&1; then
            warn "prefetch failed for $SAMPLE ($SRA); skipping this sample"
            record_download "$SAMPLE" "failed" "prefetch failed for $SRA; see $LOG_DIR/${SAMPLE}.prefetch.log"
            return 0
        fi
        log "  extracting FASTQ (fasterq-dump) ..."
        if ! fasterq-dump --split-files --threads "$THREADS" -O "$SDIR" \
                "$SDIR/$SRA/$SRA.sra" > "$LOG_DIR/${SAMPLE}.fasterq.log" 2>&1 \
             && ! retry_network "fasterq-dump $SRA" \
                    fasterq-dump --split-files --threads "$THREADS" -O "$SDIR" "$SRA" \
                    > "$LOG_DIR/${SAMPLE}.fasterq.log" 2>&1; then
            warn "fasterq-dump failed for $SAMPLE ($SRA); skipping this sample"
            record_download "$SAMPLE" "failed" "fasterq-dump failed for $SRA; see $LOG_DIR/${SAMPLE}.fasterq.log"
            return 0
        fi
        # compress
        [[ -f "$SDIR/${SRA}_1.fastq" ]] && pigz -f "$SDIR/${SRA}_1.fastq" 2>/dev/null || gzip -f "$SDIR/${SRA}_1.fastq" 2>/dev/null || true
        [[ -f "$SDIR/${SRA}_2.fastq" ]] && pigz -f "$SDIR/${SRA}_2.fastq" 2>/dev/null || gzip -f "$SDIR/${SRA}_2.fastq" 2>/dev/null || true
        rm -rf "$SDIR/$SRA"   # remove .sra cache dir
        if [[ ! -s "$R1" || ! -s "$R2" ]]; then
            warn "paired FASTQ not produced for $SRA (single-end run?); skipping $SAMPLE"
            record_download "$SAMPLE" "failed" "paired FASTQ not produced for $SRA (single-end run?)"
            return 0
        fi
        log "  reads -> $R1 , $R2"
    fi

    record_download "$SAMPLE" "ok" ""
}

confirm_download

declare -A PIDS
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if [[ "$MAX_PARALLEL_SAMPLES" -le 1 ]]; then
        # Not backgrounded: a die() inside download_sample aborts this whole
        # script immediately, exactly like before parallelism existed.
        download_sample "$SAMPLE" "$ASM" "$SRA"
    else
        job_slot_wait "$MAX_PARALLEL_SAMPLES"
        download_sample "$SAMPLE" "$ASM" "$SRA" &
        PIDS["$SAMPLE"]=$!
    fi
done < <(read_samples "$SAMPLE_SHEET")

if [[ "$MAX_PARALLEL_SAMPLES" -gt 1 ]]; then
    for sample in "${!PIDS[@]}"; do
        wait "${PIDS[$sample]}" || true
    done
fi

# Assemble the status table in sample-sheet order, so its rows read the same
# however the parallel jobs happened to interleave.
shards=()
while IFS=$'\t' read -r SAMPLE _ _; do
    [[ -z "${SAMPLE:-}" ]] && continue
    shards+=("$STATUS_SHARDS/$SAMPLE.tsv")
done < <(read_samples "$SAMPLE_SHEET")
merge_shards "$STATUS" "$(printf 'sample\tstatus\treason')" "${shards[@]}"

DOWNLOADED=$(awk -F'\t' 'NR>1 && $2=="ok"' "$STATUS" | wc -l)
FAILED=$(awk -F'\t' 'NR>1 && $2=="failed"' "$STATUS" | wc -l)

if [[ "$FAILED" -gt 0 ]]; then
    warn "$FAILED sample(s) could not be downloaded and will be skipped:"
    awk -F'\t' 'NR>1 && $2=="failed" {printf "    %s: %s\n", $1, $3}' "$STATUS" >&2
    warn "Recorded in $STATUS. Re-running this stage retries only the failed samples."
fi

# Nothing downloaded at all means there is nothing to benchmark -- that, and
# only that, is fatal.
if [[ "$DOWNLOADED" -eq 0 ]]; then
    die "no sample downloaded successfully; see $STATUS and logs/<sample>.*.log"
fi

log "Stage 1 (download) complete: $DOWNLOADED ok, $FAILED failed."
