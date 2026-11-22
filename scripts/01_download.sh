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
# Parallelism: ONE isolate is downloaded at a time (MAX_PARALLEL_DOWNLOADS, default 1;
# the connection budget ENA_MAX_CONNECTIONS is split between the downloads running at
# once). Downloads are network-bound, so a second isolate only helps when one isolate
# does not already use the whole link: `plasbench net-bench` and the MB/s lines tell.
# MAX_PARALLEL_SAMPLES governs stages 2-5, not this stage.
#
# Reads: READ_SOURCE=auto fetches from ENA first (MD5-checked, chunked, resumable; no .sra
# file and no FASTQ conversion) and uses the SRA Toolkit only when ENA has no paired FASTQ
# for the run or fails after its retries. READ_DEPTH_CAP_X (default 150) fetches only the
# first read pairs of a run deeper than that; no isolate is ever skipped because of its size
# unless MAX_RUN_DOWNLOAD_GB is set.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

[[ -f "$SAMPLE_SHEET" ]] || die "sample sheet not found: $SAMPLE_SHEET"
PARALLEL_DOWNLOADS="${MAX_PARALLEL_DOWNLOADS:-1}"
[[ "$PARALLEL_DOWNLOADS" =~ ^[1-9][0-9]*$ ]] || PARALLEL_DOWNLOADS=1
warn_resource_oversubscription "stage 1 (download)" "$PARALLEL_DOWNLOADS" "$THREADS"

STATUS="$RESULTS_DIR/download_status.tsv"
mkdir -p "$RESULTS_DIR" "$LOG_DIR" "$DATA_DIR"
stage_timing_begin 1
check_free_disk "$DATA_DIR"
reset_shard_dir "download"
STATUS_SHARDS="$(shard_dir "download")"
# Honest progress for `plasbench status` and the window (bytes actually received), a lowered connection budget that later isolates of this run remember, and which isolates came via ENA or the SRA Toolkit.
DOWNLOAD_PROGRESS_FILE="$RESULTS_DIR/download_progress.json"
ENA_BUDGET_FILE="$LOG_DIR/.ena_budget"
VIA_DIR="$STATUS_SHARDS"
STAGE1_START_SECONDS=$SECONDS
rm -f "$ENA_BUDGET_FILE" "$DOWNLOAD_PROGRESS_FILE.lock"
printf '{"updated": %s, "isolates": {}}\n' "$(date +%s)" > "$DOWNLOAD_PROGRESS_FILE" 2>/dev/null || true
PLASBENCH_STUDY="$(basename "$(dirname "${RESULTS_DIR:-./results}")")"
# The connection budget is shared by the downloads running at once.
ENA_BUDGET_SHARE=""
if [[ "$PARALLEL_DOWNLOADS" -gt 1 ]]; then
    ENA_BUDGET_SHARE=$(( ${ENA_MAX_CONNECTIONS:-16} / PARALLEL_DOWNLOADS )); [[ "$ENA_BUDGET_SHARE" -ge 1 ]] || ENA_BUDGET_SHARE=1
fi
export DOWNLOAD_PROGRESS_FILE ENA_BUDGET_FILE PLASBENCH_STUDY ENA_BUDGET_SHARE

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
    chmod 0444 "$sdir/${sra}_1.fastq.gz" "$sdir/${sra}_2.fastq.gz" 2>/dev/null || true   # read-only, and never executable: a Windows drive seen from WSL reports every file as 0755, which chmod a-w turned into r-xr-xr-x
}
# 0 when every file in the manifest still matches (or there is no manifest yet).
verify_downloads() {
    local sdir="$1"
    [[ -s "$sdir/downloads.sha256" ]] || return 0
    (cd "$sdir" && sha256sum --quiet -c downloads.sha256 > /dev/null 2>&1)
}

# Paired FASTQ for one run from ENA (python/fetch_ena_reads.py: chunked and resumable, MD5-checked, the read-depth cap applies; see READ_DEPTH_CAP_X).
# Every attempt is APPENDED to logs/<sample>.ena.log under a header with its number and time, so the message of an earlier failure is never overwritten.
# Returns 0 when the reads are in place, 4 when ENA has no usable paired FASTQ for the run, 1 for any other failure (finished chunks stay on disk for the next attempt).
fetch_from_ena() {
    local sample="$1" run="$2" sdir="$3" total_bytes="${4:-}" ref="${5:-}"
    local interval="${DOWNLOAD_PROGRESS_SECONDS:-30}" waited=0 pid rc attempt logf="$LOG_DIR/${sample}.ena.log"
    [[ "$interval" =~ ^[0-9]+$ ]] || interval=30
    attempt=$(( $(grep -c '^===== attempt ' "$logf" 2>/dev/null || true) + 1 ))
    printf '===== attempt %s, %s, run %s =====\n' "$attempt" "$(date '+%Y-%m-%d %H:%M:%S')" "$run" >> "$logf"
    log "  fetching $run from ENA (attempt $attempt) ..."
    # The downloader writes to its own log, so a long transfer would leave the run log silent and the window would show the run as stalled.
    # It runs in the background while this loop logs a progress line every DOWNLOAD_PROGRESS_SECONDS (0 = none): bytes actually received, not file sizes.
    python3 "$HERE/../python/fetch_ena_reads.py" --run "$run" --out-dir "$sdir" --sample "$sample" --study "$PLASBENCH_STUDY" \
        --progress-file "$DOWNLOAD_PROGRESS_FILE" ${ref:+--reference "$ref"} >> "$logf" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [[ "$interval" -gt 0 && "$waited" -ge "$interval" ]]; then
            waited=0
            log "  $(python3 "$HERE/../python/download_progress.py" --data-dir "$sdir" --run "$run" --progress-file "$DOWNLOAD_PROGRESS_FILE" ${total_bytes:+--total-bytes "$total_bytes"} 2>/dev/null || echo "$run: still downloading")"
        fi
    done
    rc=0
    wait "$pid" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
        printf 'ena\n' > "$VIA_DIR/$sample.via"
        return 0
    fi
    if [[ "$rc" -eq 4 ]]; then
        log "  ENA has no usable paired FASTQ for $run"
        return 4
    fi
    warn "ENA download failed for $sample ($run), attempt $attempt: $(grep -v '^[[:space:]]*$' "$logf" | tail -n 1 | cut -c1-200). Chunks already downloaded are kept and the next attempt resumes from them; every attempt is in $logf"
    return 1
}

# What ENA will be asked for, from its file report: sets READ_BYTES (bytes to download: with the read-depth cap, the capped size), READ_FULL_BYTES (the whole files), READ_CAPPED (1 when the
# cap applies) and READ_PLAN_LINE (the plain one-line message). All empty/0 when ENA cannot be reached: the download then goes ahead without a size check.
READ_BYTES=""; READ_FULL_BYTES=""; READ_CAPPED=0; READ_PLAN_LINE=""
read_plan() {
    local out
    READ_BYTES=""; READ_FULL_BYTES=""; READ_CAPPED=0; READ_PLAN_LINE=""
    out="$(python3 "$HERE/../python/fetch_ena_reads.py" --run "$1" --plan ${2:+--reference "$2"} 2>/dev/null | head -n 1 || true)"
    IFS=$'\t' read -r READ_BYTES READ_FULL_BYTES READ_CAPPED READ_PLAN_LINE <<< "$out" || true
    [[ "$READ_BYTES" =~ ^[0-9]+$ && "$READ_FULL_BYTES" =~ ^[0-9]+$ ]] || { READ_BYTES=""; READ_FULL_BYTES=""; READ_CAPPED=0; READ_PLAN_LINE=""; }
}

# Say how big a run's reads are before downloading them, and what PlasBench will do about it. NO isolate is skipped because of its size, unless the person set MAX_RUN_DOWNLOAD_GB
# themselves (default: unset). A large read set is downloaded in resumable chunks (an interruption costs one chunk, not the file); a run deeper than READ_DEPTH_CAP_X (default 150)
# is fetched as its first read pairs only. Returns 1 only when the isolate was skipped through MAX_RUN_DOWNLOAD_GB (and recorded).
read_size_gate() {
    local sample="$1" run="$2" ref="${3:-}" gb
    # READ_SOURCE=sra never touches ENA, so it does not look sizes up there either (and offline tests that pin it stay offline).
    [[ "${READ_SOURCE:-auto}" == "sra" ]] && { READ_BYTES=""; return 0; }
    read_plan "$run" "$ref"
    [[ -n "$READ_BYTES" ]] || return 0
    gb="$(awk -v b="$READ_BYTES" 'BEGIN { printf "%.1f", b / 1e9 }')"
    log "  reads $run: $(human_bytes "$READ_FULL_BYTES") compressed (ENA)"
    [[ "$READ_CAPPED" == "1" ]] && log "  $READ_PLAN_LINE"
    if [[ -n "${MAX_RUN_DOWNLOAD_GB:-}" ]] && awk -v b="$READ_BYTES" -v m="$MAX_RUN_DOWNLOAD_GB" 'BEGIN { exit !(m + 0 > 0 && b / 1e9 > m + 0) }'; then
        warn "$sample: $gb GB to download is above MAX_RUN_DOWNLOAD_GB=$MAX_RUN_DOWNLOAD_GB, a limit you set; skipping this isolate"
        record_download "$sample" "failed" "skipped by choice: $gb GB to download, above MAX_RUN_DOWNLOAD_GB=$MAX_RUN_DOWNLOAD_GB, a limit set by you (clear it to download this isolate)"
        return 1
    fi
    if awk -v b="$READ_BYTES" -v w="${WARN_RUN_DOWNLOAD_GB:-5}" 'BEGIN { exit !(w + 0 > 0 && b / 1e9 > w + 0) }'; then
        warn "  $run is a large read set ($gb GB to download): it takes a while. PlasBench downloads it in resumable chunks, so a dropped connection costs one chunk and not the file, and a later run continues from what is on disk; this isolate is not skipped. Reads this deep can also be slow to trim and assemble; READ_DEPTH_CAP_X (default 150) limits the depth wherever the reference size is known."
    fi
    return 0
}

# SRA Toolkit failures that repeat. prefetch's recent results are kept across runs in ~/.plasbench/prefetch_history.json (python/prefetch_history.py: entries expire after 24 hours and
# are ignored when PlasBench or sra-tools changed). When its last PREFETCH_FAIL_LIMIT results (default 2) all failed, the toolkit itself is the problem (TLS, proxy, an old version),
# not the isolate: it is not tried again, saving about a minute per isolate. PREFETCH_FAIL_LIMIT=0 always tries it; READ_SOURCE=sra never skips it.
PREFETCH_SKIP_REASON=""
prefetch_disabled() {
    local limit="${PREFETCH_FAIL_LIMIT:-2}"
    [[ "$limit" =~ ^[0-9]+$ && "$limit" -gt 0 ]] || return 1
    PREFETCH_SKIP_REASON="$(python3 -I "$HERE/../python/prefetch_history.py" disabled --limit "$limit" 2>/dev/null)"
}
prefetch_note() { python3 -I "$HERE/../python/prefetch_history.py" record "$1" --reason "${2:-}" >/dev/null 2>&1 || true; }
# The last line the SRA Toolkit printed, so the run log says why prefetch failed (the full output is in logs/<sample>.prefetch.log).
prefetch_reason() {
    local line
    # retry_network's own "[time] WARNING: ... failed after N attempt(s)" lines land in the same log after the tool's output: skip them.
    line="$(grep -v '^[[:space:]]*$' "$1" 2>/dev/null | grep -v '^\[[0-9-]* [0-9:]*\]' | tail -n 1 | cut -c1-160 || true)"
    printf '%s' "${line:-no output}"
}
# Explain a prefetch failure in plain words, ONCE per run (python/download_diagnosis.py): what it means, what is used instead, what to check.
PREFETCH_DIAGNOSED="$LOG_DIR/.prefetch_diagnosed"
rm -f "$PREFETCH_DIAGNOSED"
explain_prefetch_failure() {
    [[ -e "$PREFETCH_DIAGNOSED" ]] && return 0
    local text
    text="$(python3 -I "$HERE/../python/download_diagnosis.py" "$1" 2>/dev/null)" || return 0
    : > "$PREFETCH_DIAGNOSED"
    warn "  $text"
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
    # The SRA Toolkit is only needed when it will be used: always with READ_SOURCE=sra, otherwise only if ENA cannot supply a run (checked at that point).
    if [[ "$TRUTH_SOURCE" != "simulated" && "${READ_SOURCE:-auto}" == "sra" ]]; then
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
    elif ! read_size_gate "$SAMPLE" "$SRA" "$([[ -s "$REF" ]] && echo "$REF")"; then
        return 0   # the person set MAX_RUN_DOWNLOAD_GB and this isolate is above it; read_size_gate recorded the skip
    else
        # Reads. READ_SOURCE=auto tries ENA FIRST (checksum-verified, chunked and resumable, no .sra file and no FASTQ conversion) and uses the SRA Toolkit only when ENA has no
        # paired FASTQ for the run or still fails after its retries. READ_SOURCE=ena uses ENA only, READ_SOURCE=sra the SRA Toolkit only.
        local VIA="" ENA_RC=1
        if [[ "${READ_SOURCE:-auto}" != "sra" ]]; then
            fetch_from_ena "$SAMPLE" "$SRA" "$SDIR" "$READ_BYTES" "$([[ -s "$REF" ]] && echo "$REF")" && VIA=ena || ENA_RC=$?
            if [[ -z "$VIA" && "${READ_SOURCE:-auto}" == "ena" ]]; then
                warn "ENA download failed for $SAMPLE ($SRA); skipping this sample (READ_SOURCE=ena uses ENA only; the log is $LOG_DIR/${SAMPLE}.ena.log)"
                record_download "$SAMPLE" "failed" "ENA download failed for $SRA; see $LOG_DIR/${SAMPLE}.ena.log (chunks already downloaded are kept; run the same command again to resume)"
                return 0
            fi
            if [[ -z "$VIA" ]]; then
                if [[ "$ENA_RC" -eq 4 ]]; then
                    log "  ENA has no paired FASTQ for $SRA: using the SRA Toolkit (prefetch, fasterq-dump)"
                else
                    log "  ENA failed for $SRA after its retries: trying the SRA Toolkit (prefetch, fasterq-dump)"
                fi
            fi
        fi
        if [[ -z "$VIA" ]]; then
            if [[ "${READ_SOURCE:-auto}" == "auto" ]] && prefetch_disabled; then
                warn "  not trying the SRA Toolkit for $SRA: $PREFETCH_SKIP_REASON. (PREFETCH_FAIL_LIMIT=0 tries it anyway; the record is ~/.plasbench/prefetch_history.json and expires after 24 hours.)"
                record_download "$SAMPLE" "failed" "ENA could not supply $SRA and the SRA Toolkit is known not to work here: $PREFETCH_SKIP_REASON; see $LOG_DIR/${SAMPLE}.ena.log"
                return 0
            fi
            need prefetch
            need fasterq-dump
            log "  prefetching $SRA ..."
            if ! retry_network "prefetch $SRA" \
                    prefetch -O "$SDIR" "$SRA" > "$LOG_DIR/${SAMPLE}.prefetch.log" 2>&1; then
                warn "  prefetch failed for $SAMPLE ($SRA): $(prefetch_reason "$LOG_DIR/${SAMPLE}.prefetch.log")"
                prefetch_note fail "$(prefetch_reason "$LOG_DIR/${SAMPLE}.prefetch.log")"
                explain_prefetch_failure "$LOG_DIR/${SAMPLE}.prefetch.log"
                warn "prefetch failed for $SAMPLE ($SRA); skipping this sample"
                record_download "$SAMPLE" "failed" "prefetch failed for $SRA: $(prefetch_reason "$LOG_DIR/${SAMPLE}.prefetch.log"); see $LOG_DIR/${SAMPLE}.prefetch.log"
                return 0
            fi
            prefetch_note ok
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
            printf 'sra\n' > "$VIA_DIR/$SAMPLE.via"
            log "  reads (SRA Toolkit) -> $R1 , $R2"
        else
            log "  reads (ENA) -> $R1 , $R2"
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
    while IFS=$'\t' read -r -u 3 sample asm sra; do
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
    done 3< <(read_samples "$SAMPLE_SHEET")
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
while IFS=$'\t' read -r -u 3 SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    if ! disk_guard 1 "$SAMPLE" "$SRA"; then      # the next isolate no longer fits (plus the reserve): stop cleanly BEFORE it starts downloading
        DISK_STOP=1; DISK_STOP_AT="$SAMPLE"
        break
    fi
    if [[ "$PARALLEL_DOWNLOADS" -le 1 ]]; then
        # Not backgrounded: a die() inside download_sample aborts this whole
        # script immediately, exactly like before parallelism existed.
        download_sample "$SAMPLE" "$ASM" "$SRA"
    else
        job_slot_wait "$PARALLEL_DOWNLOADS"
        download_sample "$SAMPLE" "$ASM" "$SRA" &
        PIDS["$SAMPLE"]=$!
    fi
done 3< <(read_samples "$SAMPLE_SHEET")

if [[ "$PARALLEL_DOWNLOADS" -gt 1 ]]; then
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
while IFS=$'\t' read -r -u 3 SAMPLE _ _; do
    [[ -z "${SAMPLE:-}" ]] && continue
    shards+=("$STATUS_SHARDS/$SAMPLE.tsv")
done 3< <(read_samples "$SAMPLE_SHEET")
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

log "$(python3 -I "$HERE/../python/download_progress.py" --summary --progress-file "$DOWNLOAD_PROGRESS_FILE" --via-dir "$VIA_DIR" --seconds "$(( SECONDS - STAGE1_START_SECONDS ))" 2>/dev/null || true)"
log "Stage 1 (download) complete: $DOWNLOADED ok, $FAILED failed."
