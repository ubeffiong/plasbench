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
mkdir -p "$RESULTS_DIR" "$LOG_DIR" "$DATA_DIR"
stage_timing_begin 1
check_free_disk "$DATA_DIR"
reset_shard_dir "download"
STATUS_SHARDS="$(shard_dir "download")"

# One shard file per sample, so concurrent jobs never contend for one file.
record_download() {
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" > "$STATUS_SHARDS/$1.tsv"
    run_event download_end "sample=$1" "status=$2" "reason=$3"
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
    printf '%s' "Download these files now? [y/N] " >&2; read -r reply || true
    case "$reply" in
        y|Y|yes|YES|Yes) return 0 ;;
        *) die "Download declined. Nothing was fetched." ;;
    esac
}

# Downloaded inputs are kept for every later run (PRESERVE_DOWNLOADS=1, default):
# each sample's reads and NCBI records get a SHA-256 manifest (downloads.sha256)
# and the read files are made read-only. A later run with the same DATA_DIR
# verifies them against the manifest instead of downloading again; a file that
# no longer matches is reported and fetched afresh.
DOWNLOAD_FILES=(reference.fna sequence_report.jsonl assembly_data_report.jsonl)
preserve_downloads() {
    local sdir="$1" sra="$2"
    [[ "${PRESERVE_DOWNLOADS:-1}" == "1" ]] || return 0
    local files=() f
    for f in "${DOWNLOAD_FILES[@]}" "${sra}_1.fastq.gz" "${sra}_2.fastq.gz" "${sra}.ena_provenance.json"; do
        [[ -s "$sdir/$f" ]] && files+=("$f")
    done
    [[ ${#files[@]} -gt 0 ]] || return 0
    (cd "$sdir" && sha256sum "${files[@]}" > downloads.sha256)
    chmod a-w "$sdir/${sra}_1.fastq.gz" "$sdir/${sra}_2.fastq.gz" 2>/dev/null || true
}
# 0 when every file in the manifest still matches (or there is no manifest yet).
verify_downloads() {
    local sdir="$1"
    [[ -s "$sdir/downloads.sha256" ]] || return 0
    (cd "$sdir" && sha256sum --quiet -c downloads.sha256 > /dev/null 2>&1)
}

# Paired FASTQ for one run from ENA (python/fetch_ena_reads.py: HTTPS, MD5-verified).
fetch_from_ena() {
    local sample="$1" run="$2" sdir="$3" total_bytes="${4:-}"
    local interval="${DOWNLOAD_PROGRESS_SECONDS:-60}" waited=0 pid
    [[ "$interval" =~ ^[0-9]+$ ]] || interval=60
    log "  fetching $run from ENA ..."
    # The downloader writes to its own log, so a long transfer used to leave the run log silent and the window showed the run as stalled.
    # It runs in the background while this loop logs a progress line every DOWNLOAD_PROGRESS_SECONDS (0 = none).
    python3 "$HERE/../python/fetch_ena_reads.py" --run "$run" --out-dir "$sdir" > "$LOG_DIR/${sample}.ena.log" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [[ "$interval" -gt 0 && "$waited" -ge "$interval" ]]; then
            waited=0
            log "  $(python3 "$HERE/../python/download_progress.py" --data-dir "$sdir" --run "$run" ${total_bytes:+--total-bytes "$total_bytes"} 2>/dev/null || echo "$run: still downloading")"
        fi
    done
    if wait "$pid"; then
        return 0
    fi
    warn "ENA download failed for $sample ($run); see $LOG_DIR/${sample}.ena.log"
    return 1
}

# Size of a run's FASTQ files from ENA's file report, in bytes (empty when ENA cannot be reached: the download then goes ahead without a size check).
ena_run_bytes() {
    python3 "$HERE/../python/fetch_ena_reads.py" --run "$1" --size-only 2>/dev/null | awk -F'\t' 'NR == 1 && $1 ~ /^[0-9]+$/ {print $1}' || true
}

# Say how big a run's reads are before downloading them. A very large read set is slow, needs about three times its size on disk, and is slow or
# memory-hungry to assemble: warn above WARN_RUN_DOWNLOAD_GB (default 5), and skip the isolate when MAX_RUN_DOWNLOAD_GB is set and exceeded.
# Returns 1 only when the isolate was skipped (and recorded); sets READ_BYTES for the progress line.
READ_BYTES=""
read_size_gate() {
    local sample="$1" run="$2" bytes gb
    READ_BYTES=""
    # READ_SOURCE=sra never touches ENA, so it does not look sizes up there either (and offline tests that pin it stay offline).
    [[ "${READ_SOURCE:-auto}" == "sra" ]] && return 0
    bytes="$(ena_run_bytes "$run")"
    [[ "$bytes" =~ ^[0-9]+$ ]] || return 0
    READ_BYTES="$bytes"
    gb="$(awk -v b="$bytes" 'BEGIN { printf "%.1f", b / 1e9 }')"
    log "  reads $run: $(human_bytes "$bytes") compressed (ENA)"
    if [[ -n "${MAX_RUN_DOWNLOAD_GB:-}" ]] && awk -v b="$bytes" -v m="$MAX_RUN_DOWNLOAD_GB" 'BEGIN { exit !(m + 0 > 0 && b / 1e9 > m + 0) }'; then
        warn "$sample: reads are $gb GB, above MAX_RUN_DOWNLOAD_GB=$MAX_RUN_DOWNLOAD_GB; skipping this isolate"
        record_download "$sample" "failed" "skipped by choice: reads are $gb GB, above MAX_RUN_DOWNLOAD_GB=$MAX_RUN_DOWNLOAD_GB (raise or clear it to download this isolate)"
        return 1
    fi
    if awk -v b="$bytes" -v w="${WARN_RUN_DOWNLOAD_GB:-5}" 'BEGIN { exit !(w + 0 > 0 && b / 1e9 > w + 0) }'; then
        warn "  $run is a large read set ($gb GB): it takes a while to download, needs about three times that on disk, and assembling reads this deep can be slow or run out of memory. Set MAX_RUN_DOWNLOAD_GB to skip isolates this large."
    fi
    return 0
}

# SRA Toolkit failures that repeat. When prefetch has failed and ENA has worked for the last PREFETCH_FAIL_LIMIT isolates in a row (default 2), the
# toolkit itself is the problem (TLS, proxy, an old version), not the isolate: stop spending about a minute per isolate on a call that will fail, and
# go to ENA first for the rest of this run. READ_SOURCE=sra never skips prefetch; PREFETCH_FAIL_LIMIT=0 always tries it first. The history is reset each
# time stage 1 starts, so a fixed toolkit is tried again on the next run.
PREFETCH_HISTORY="$LOG_DIR/.prefetch_history"
: > "$PREFETCH_HISTORY"
prefetch_disabled() {
    local limit="${PREFETCH_FAIL_LIMIT:-2}"
    [[ "$limit" =~ ^[0-9]+$ && "$limit" -gt 0 && -s "$PREFETCH_HISTORY" ]] || return 1
    [[ "$(tail -n "$limit" "$PREFETCH_HISTORY" | grep -c '^fail$')" -ge "$limit" ]]
}
# The last line the SRA Toolkit printed, so the run log says why prefetch failed (the full output is in logs/<sample>.prefetch.log).
prefetch_reason() {
    local line
    # retry_network's own "[time] WARNING: ... failed after N attempt(s)" lines land in the same log after the tool's output: skip them.
    line="$(grep -v '^[[:space:]]*$' "$1" 2>/dev/null | grep -v '^\[[0-9-]* [0-9:]*\]' | tail -n 1 | cut -c1-160 || true)"
    printf '%s' "${line:-no output}"
}
# 9500000000 -> "9.5 GB"; below a GB it is shown in MB, so a small run does not read as 0.0 GB.
human_bytes() {
    awk -v b="$1" 'BEGIN { if (b >= 1e9) printf "%.1f GB", b / 1e9; else printf "%.0f MB", b / 1e6 }'
}

download_sample() {
    local SAMPLE="$1" ASM="$2" SRA="$3"
    local SDIR="$DATA_DIR/$SAMPLE"
    mkdir -p "$SDIR"
    log "=== Sample $SAMPLE : assembly=$ASM  reads=$SRA ==="
    run_event sample_start "sample=$SAMPLE" "step=download" "reads=$SRA"
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

    # self_assembled_hybrid: a benchmark sample (not operational) whose truth
    # is built in-house by build_hybrid_truth.py (stage 2) from this
    # isolate's own long+short reads, for cohort sources that deposit reads
    # but never submitted a formal assembly -- see docs/FINDING_DATA.md.
    # assembly_accession stays blank/NA for these rows too (HAS_REFERENCE=0,
    # same branch as an operational sample), but unlike an operational
    # sample, long reads must also be fetched here.
    local TRUTH_SOURCE LONG_READ_SRA_RUN LONG_READS
    TRUTH_SOURCE="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" truth_source)"
    LONG_READ_SRA_RUN="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" long_read_sra_run)"
    LONG_READS="$SDIR/${LONG_READS_FILE:-long_reads.fastq.gz}"

    if [[ "$LOCAL_INPUTS_ONLY" == "1" ]]; then
        local missing=()
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            [[ -s "$REF" ]] || missing+=("$REF")
            [[ -s "$REPORT" || -s "$SDIR/truth.tsv" ]] || missing+=("$REPORT or $SDIR/truth.tsv")
        elif [[ "$TRUTH_SOURCE" == "self_assembled_hybrid" ]]; then
            [[ -s "$LONG_READS" || -s "$SDIR/truth.tsv" ]] || missing+=("$LONG_READS or $SDIR/truth.tsv")
        fi
        [[ -s "$R1" ]] || missing+=("$R1")
        [[ -s "$R2" ]] || missing+=("$R2")
        if [[ ${#missing[@]} -gt 0 ]]; then
            die "local-inputs mode is missing for $SAMPLE: ${missing[*]}"
        fi
        if [[ "$HAS_REFERENCE" -eq 1 ]]; then
            log "  local reference, truth/report, and paired reads verified; download skipped"
        elif [[ "$TRUTH_SOURCE" == "self_assembled_hybrid" ]]; then
            log "  local long+short reads verified (truth_source=self_assembled_hybrid); download skipped"
        else
            log "  local paired reads verified (no accession: reference/truth skipped); download skipped"
        fi
        return 0
    fi

    # Download clients are only required when this sample actually needs them
    # -- a truth_source=simulated sample never touches SRA at all (its reads
    # are generated locally by python/simulate_reads.py below), so it does
    # not need sra-tools installed.
    [[ "$HAS_REFERENCE" -eq 1 ]] && need datasets
    if [[ "$TRUTH_SOURCE" != "simulated" ]]; then
        need prefetch
        need fasterq-dump
    fi

    # ---- (a) reference assembly + sequence report ----
    if [[ "$HAS_REFERENCE" -eq 0 && "$TRUTH_SOURCE" == "self_assembled_hybrid" ]]; then
        log "  truth_source=self_assembled_hybrid; reference will be built from reads in stage 2, not downloaded"
    elif [[ "$HAS_REFERENCE" -eq 0 ]]; then
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
        # Keep the assembly report: its releaseDate feeds the reference-database
        # overlap screen (python/flag_database_overlap.py). Optional.
        local ADR
        ADR=$(find "$SDIR/ncbi" -name 'assembly_data_report.jsonl' | head -n1)
        [[ -s "$ADR" ]] && cp "$ADR" "$SDIR/assembly_data_report.jsonl"
        rm -f "$ZIP"
        log "  reference -> $REF"
    fi

    # ---- (b) Illumina reads ----
    if [[ "$TRUTH_SOURCE" == "simulated" ]]; then
        # simulated: assembly_accession is a REAL reference (downloaded
        # above, unchanged), but sra_run is not a real SRA accession -- reads
        # are generated locally from that reference instead. Both short and
        # long reads come out of ONE simulate_reads.py invocation, so this
        # replaces both (b) and (c) below for a simulated row; the (c) block
        # only ever fires for truth_source=self_assembled_hybrid.
        if [[ -s "$R1" && -s "$R2" && -s "$LONG_READS" ]]; then
            log "  simulated reads already present, skipping simulation"
        elif [[ ! -s "$REF" ]]; then
            warn "truth_source=simulated but no reference was downloaded for $SAMPLE; skipping"
            record_download "$SAMPLE" "failed" "truth_source=simulated requires a downloaded reference to simulate reads from"
            return 0
        else
            local SEED SHORT_DEPTH LONG_DEPTH SHORT_MODEL LONG_MODEL
            SEED="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" simulation_seed)"
            SHORT_DEPTH="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" simulation_short_depth_x)"
            LONG_DEPTH="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" simulation_long_depth_x)"
            SHORT_MODEL="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" simulation_short_error_model)"
            LONG_MODEL="$(sample_column "$SAMPLE_SHEET" "$SAMPLE" simulation_long_error_model)"
            [[ -z "$SHORT_MODEL" ]] && SHORT_MODEL="$SIMULATE_SHORT_MODEL"
            [[ -z "$LONG_MODEL" ]] && LONG_MODEL="$SIMULATE_LONG_MODEL"
            log "  simulating reads from $REF (seed=$SEED, short=${SHORT_DEPTH}x $SHORT_MODEL, long=${LONG_DEPTH}x $LONG_MODEL) ..."
            if ! python3 "$HERE/../python/simulate_reads.py" --reference "$REF" \
                    --out-r1 "$R1" --out-r2 "$R2" --out-long "$LONG_READS" \
                    --out-provenance "$SDIR/simulation_provenance.json" \
                    --seed "$SEED" --short-depth "$SHORT_DEPTH" --long-depth "$LONG_DEPTH" \
                    --short-model "$SHORT_MODEL" --long-model "$LONG_MODEL" --threads "$SIMULATE_THREADS" \
                    > "$LOG_DIR/${SAMPLE}.simulate.log" 2>&1; then
                warn "read simulation failed for $SAMPLE; skipping this sample"
                record_download "$SAMPLE" "failed" "simulate_reads.py failed; see $LOG_DIR/${SAMPLE}.simulate.log"
                return 0
            fi
            log "  simulated reads -> $R1 , $R2 , $LONG_READS"
        fi
    elif [[ -s "$R1" && -s "$R2" ]] && verify_downloads "$SDIR"; then
        log "  reads already present (checked against downloads.sha256 when present), skipping download"
    elif ! read_size_gate "$SAMPLE" "$SRA"; then
        return 0   # the isolate's reads are above MAX_RUN_DOWNLOAD_GB; read_size_gate recorded the skip
    elif [[ "${READ_SOURCE:-auto}" == "ena" ]] && fetch_from_ena "$SAMPLE" "$SRA" "$SDIR" "$READ_BYTES"; then
        log "  reads (ENA) -> $R1 , $R2"
    else
        local VIA_ENA=0
        # READ_SOURCE=auto, and prefetch has just failed on the last PREFETCH_FAIL_LIMIT isolates while ENA worked: go to ENA first.
        if [[ "${READ_SOURCE:-auto}" == "auto" ]] && prefetch_disabled; then
            log "  SRA Toolkit prefetch failed on the last ${PREFETCH_FAIL_LIMIT:-2} isolates; fetching $SRA from ENA first (READ_SOURCE=ena always does this; PREFETCH_FAIL_LIMIT=0 always tries prefetch first)"
            fetch_from_ena "$SAMPLE" "$SRA" "$SDIR" "$READ_BYTES" && VIA_ENA=1
        fi
        if [[ "$VIA_ENA" -eq 0 ]]; then
            log "  prefetching $SRA ..."
            if ! retry_network "prefetch $SRA" \
                    prefetch -O "$SDIR" "$SRA" > "$LOG_DIR/${SAMPLE}.prefetch.log" 2>&1; then
                warn "  prefetch failed for $SAMPLE ($SRA): $(prefetch_reason "$LOG_DIR/${SAMPLE}.prefetch.log")"
                # READ_SOURCE=auto: the same INSDC run from ENA, checksum-verified, when
                # the SRA Toolkit cannot connect (for example an old toolkit failing TLS).
                if [[ "${READ_SOURCE:-auto}" == "auto" ]] && fetch_from_ena "$SAMPLE" "$SRA" "$SDIR" "$READ_BYTES"; then
                    VIA_ENA=1
                    echo fail >> "$PREFETCH_HISTORY"
                else
                    warn "prefetch failed for $SAMPLE ($SRA); skipping this sample"
                    record_download "$SAMPLE" "failed" "prefetch failed for $SRA: $(prefetch_reason "$LOG_DIR/${SAMPLE}.prefetch.log"); see $LOG_DIR/${SAMPLE}.prefetch.log"
                    return 0
                fi
            else
                echo ok >> "$PREFETCH_HISTORY"
            fi
        fi
        if [[ "$VIA_ENA" -eq 0 ]]; then
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
            rm -rf "${SDIR:?}/${SRA:?}"   # remove .sra cache dir
            if [[ ! -s "$R1" || ! -s "$R2" ]]; then
                warn "paired FASTQ not produced for $SRA (single-end run?); skipping $SAMPLE"
                record_download "$SAMPLE" "failed" "paired FASTQ not produced for $SRA (single-end run?)"
                return 0
            fi
            log "  reads -> $R1 , $R2"
        else
            log "  reads fetched from ENA instead of the SRA Toolkit -> $R1 , $R2"
        fi
    fi

    # ---- (c) long reads (truth_source=self_assembled_hybrid only) ----
    # Every existing long-read/hybrid cohort row stages long_reads.fastq.gz
    # manually; this is the one automated fetch path, needed because these
    # rows' whole premise is "the isolate's own long reads are deposited in
    # SRA, but no assembly is". Same prefetch/fasterq-dump pattern as (b)
    # above, into the SAME $LONG_READS_FILE location stage 7's tools already
    # read -- no new long-read staging convention is invented.
    if [[ "$TRUTH_SOURCE" == "self_assembled_hybrid" ]]; then
        if [[ -z "$LONG_READ_SRA_RUN" ]]; then
            warn "truth_source=self_assembled_hybrid but long_read_sra_run is empty for $SAMPLE; skipping"
            record_download "$SAMPLE" "failed" "truth_source=self_assembled_hybrid requires long_read_sra_run"
            return 0
        fi
        if [[ -s "$LONG_READS" ]]; then
            log "  long reads already present, skipping download"
        else
            log "  prefetching long-read run $LONG_READ_SRA_RUN ..."
            if ! retry_network "prefetch $LONG_READ_SRA_RUN" \
                    prefetch -O "$SDIR" "$LONG_READ_SRA_RUN" > "$LOG_DIR/${SAMPLE}.long_prefetch.log" 2>&1; then
                warn "prefetch failed for $SAMPLE ($LONG_READ_SRA_RUN); skipping this sample"
                record_download "$SAMPLE" "failed" "prefetch failed for $LONG_READ_SRA_RUN; see $LOG_DIR/${SAMPLE}.long_prefetch.log"
                return 0
            fi
            log "  extracting long-read FASTQ (fasterq-dump) ..."
            if ! fasterq-dump --threads "$THREADS" -O "$SDIR" \
                    "$SDIR/$LONG_READ_SRA_RUN/$LONG_READ_SRA_RUN.sra" > "$LOG_DIR/${SAMPLE}.long_fasterq.log" 2>&1 \
                 && ! retry_network "fasterq-dump $LONG_READ_SRA_RUN" \
                        fasterq-dump --threads "$THREADS" -O "$SDIR" "$LONG_READ_SRA_RUN" \
                        > "$LOG_DIR/${SAMPLE}.long_fasterq.log" 2>&1; then
                warn "fasterq-dump failed for $SAMPLE ($LONG_READ_SRA_RUN); skipping this sample"
                record_download "$SAMPLE" "failed" "fasterq-dump failed for $LONG_READ_SRA_RUN; see $LOG_DIR/${SAMPLE}.long_fasterq.log"
                return 0
            fi
            # Long reads are a single-end run (no --split-files): fasterq-dump
            # writes <RUN>.fastq directly. Rename into the fixed
            # $LONG_READS_FILE location every long-read/hybrid tool expects.
            if [[ -f "$SDIR/${LONG_READ_SRA_RUN}.fastq" ]]; then
                pigz -f "$SDIR/${LONG_READ_SRA_RUN}.fastq" 2>/dev/null || gzip -f "$SDIR/${LONG_READ_SRA_RUN}.fastq" 2>/dev/null || true
                mv -f "$SDIR/${LONG_READ_SRA_RUN}.fastq.gz" "$LONG_READS"
            fi
            rm -rf "${SDIR:?}/${LONG_READ_SRA_RUN:?}"
            if [[ ! -s "$LONG_READS" ]]; then
                warn "long-read FASTQ not produced for $LONG_READ_SRA_RUN; skipping $SAMPLE"
                record_download "$SAMPLE" "failed" "long-read FASTQ not produced for $LONG_READ_SRA_RUN"
                return 0
            fi
            log "  long reads -> $LONG_READS"
        fi
    fi

    preserve_downloads "$SDIR" "$SRA"
    record_download "$SAMPLE" "ok" ""
}

# In local-inputs mode the staged files ARE the experiment, so check them all
# up front. Existence alone is a weak test: a FASTQ that is not really gzipped,
# reads that do not pair, a reference with duplicate ids, or a missing truth
# table each fail hours later or, worse, not at all.
if [[ "$LOCAL_INPUTS_ONLY" == "1" ]]; then
    if ! python3 "$HERE/../python/validate_local_inputs.py" \
            --samples "$SAMPLE_SHEET" --data-dir "$DATA_DIR"; then
        die "local inputs are not usable; nothing was run"
    fi
fi

# Before any download: work out, the same way download_sample will, what this run has to FETCH, and refuse at once (naming the service
# and what to do) when that needs the internet and there is none. Nothing is demanded when every file is already on disk, when
# --local-inputs is used, or for a simulated sample's reads (made locally). READ_SOURCE=ena skips NCBI's SRA, READ_SOURCE=sra skips ENA,
# and with auto either is enough (ENA is the fallback for the SRA Toolkit).
require_downloads_online() {
    local sample asm sra sdir truth long_run has_ref need_ref=0 need_reads=0 need_long=0 lacking=""
    [[ "$LOCAL_INPUTS_ONLY" == "1" ]] && return 0
    while IFS=$'\t' read -r sample asm sra; do
        [[ -z "${sample:-}" ]] && continue
        sdir="$DATA_DIR/$sample"
        has_ref=1; [[ -z "$asm" || "$asm" == "NA" ]] && has_ref=0
        truth="$(sample_column "$SAMPLE_SHEET" "$sample" truth_source)"
        long_run="$(sample_column "$SAMPLE_SHEET" "$sample" long_read_sra_run)"
        if [[ "$has_ref" -eq 1 && ! ( -s "$sdir/reference.fna" && -s "$sdir/sequence_report.jsonl" ) ]]; then
            need_ref=1; lacking+=" $sample:reference"
        fi
        if [[ "$truth" != "simulated" ]] && ! { [[ -s "$sdir/${sra}_1.fastq.gz" && -s "$sdir/${sra}_2.fastq.gz" ]] && verify_downloads "$sdir"; }; then
            need_reads=1; lacking+=" $sample:reads"
        fi
        if [[ "$truth" == "self_assembled_hybrid" && -n "$long_run" && ! -s "$sdir/${LONG_READS_FILE:-long_reads.fastq.gz}" ]]; then
            need_long=1; lacking+=" $sample:long-reads"
        fi
    done < <(read_samples "$SAMPLE_SHEET")
    [[ "$need_ref$need_reads$need_long" == "000" ]] && return 0
    local hint="Connect, or place the lacking files in $DATA_DIR/<sample>/ and run with --local-inputs. Missing:${lacking:0:240}"
    [[ "$need_ref" -eq 1 ]] && require_internet --action "Stage 1 (download the reference assemblies)" --hint "$hint" ncbi_datasets
    if [[ "$need_reads" -eq 1 ]]; then
        case "${READ_SOURCE:-auto}" in
            ena) require_internet --action "Stage 1 (download reads from ENA)" --hint "$hint" ena ;;
            sra) require_internet --action "Stage 1 (download reads from the SRA)" --hint "$hint" sra ;;
            *)   require_internet --any --action "Stage 1 (download reads from the SRA or ENA)" --hint "$hint" sra ena ;;
        esac
    fi
    [[ "$need_long" -eq 1 ]] && require_internet --action "Stage 1 (download long reads from the SRA)" --hint "$hint" sra
    return 0
}
require_downloads_online

confirm_download

declare -A PIDS
DISK_STOP=""
DISK_STOP_AT=""
while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if ! disk_guard 1 "$SAMPLE" "$SRA"; then      # the next isolate no longer fits (plus the reserve): stop cleanly BEFORE it starts downloading
        DISK_STOP=1; DISK_STOP_AT="$SAMPLE"
        break
    fi
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

if [[ -n "$DISK_STOP" ]]; then
    run_event stage_stopped "cause=disk_space" "sample=$DISK_STOP_AT"
    warn "Stage 1 stopped cleanly before $DISK_STOP_AT because the disk is nearly full. Nothing was lost: isolates already downloaded are kept. Free space (or use a bigger drive), then run the same plasbench run command again to continue with the isolates not downloaded yet."
    exit 6
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
