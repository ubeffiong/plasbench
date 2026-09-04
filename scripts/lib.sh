#!/usr/bin/env bash
# Shared helpers sourced by every stage script.

# Pretty logging with timestamps.
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; exit 1; }

# Check a command exists; die if not.
need() {
    command -v "$1" >/dev/null 2>&1 || die "required command '$1' not found in PATH. Did you activate the conda env?"
}

# Check a command exists; warn + return 1 if not (for optional tools).
have() { command -v "$1" >/dev/null 2>&1; }

# Reject a sample_id that could act as a path-traversal payload once it is
# used to build a directory name (results/<sample>/, data/<sample>/, etc).
# Mirrors the pattern enforced on sample-sheet rows in validate_sample_sheet.
valid_sample_id() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

# --- parallel job pool --------------------------------------------------
# Block until fewer than MAX background jobs of this shell are running, then
# return so the caller can start one more with `&`. MAX=1 (every stage's
# default) waits for every previously started job to finish before letting a
# new one start, which is exactly sequential execution -- so callers do not
# need to special-case the non-parallel default; they always background and
# always gate through this function.
job_slot_wait() {
    local max="$1"
    while [[ "$(jobs -rp | wc -l)" -ge "$max" ]]; do
        wait -n 2>/dev/null || break
    done
}

# Advisory only: warn (never block) when a chosen concurrency level would ask
# for more CPU threads, or more memory, than the host actually has. Runs once
# per stage invocation. Detects cores via `nproc` and available memory via
# /proc/meminfo, both Linux-only; silently skipped on any other platform
# (e.g. this reports nothing useful on macOS/WSL without /proc, and that is
# fine -- it is a courtesy check, not a scheduler).
warn_resource_oversubscription() {
    local label="$1" parallel_jobs="$2" threads_per_job="$3" memory_gb_per_job="${4:-0}"
    have nproc || return 0
    local cores wanted_threads
    cores="$(nproc)"
    wanted_threads=$(( parallel_jobs * threads_per_job ))
    if [[ "$wanted_threads" -gt "$cores" ]]; then
        warn "$label: $parallel_jobs concurrent job(s) x $threads_per_job thread(s) each = $wanted_threads threads requested, but only $cores CPU core(s) detected. Oversubscription can be SLOWER than running fewer jobs at once (context switching, cache thrashing) -- consider lowering the parallel-job count or the per-job thread count."
    fi
    if [[ "$memory_gb_per_job" -gt 0 && -r /proc/meminfo ]]; then
        local available_kb available_gb wanted_gb
        available_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
        if [[ -n "$available_kb" ]]; then
            available_gb=$(( available_kb / 1024 / 1024 ))
            wanted_gb=$(( parallel_jobs * memory_gb_per_job ))
            if [[ "$wanted_gb" -gt "$available_gb" ]]; then
                warn "$label: $parallel_jobs concurrent job(s) x ${memory_gb_per_job}GB each = ${wanted_gb}GB requested, but only ~${available_gb}GB is currently available. Running out of memory mid-job (e.g. SPAdes) can be far slower than fewer concurrent jobs, or force the OS to swap -- consider lowering the parallel-job count."
            fi
        fi
    fi
}

# --- shard-then-merge for shared output files ----------------------------
# Every stage that can now run several samples/tools concurrently writes its
# per-unit output rows to a private file under this directory instead of
# appending directly to the stage's one shared TSV -- concurrent appends from
# separate processes are not safe to assume atomic across every code path
# that writes them (a `csv.DictWriter` header check, in particular, races).
# merge_shards then rebuilds the shared file, once, after every job in the
# stage has finished, in the caller-supplied deterministic order -- so the
# merged file's row order matches today's sequential output exactly, whatever
# order the parallel jobs actually completed in.
shard_dir() {
    local stage_name="$1"
    printf '%s/.shards.%s' "${TMP_DIR:-/tmp}" "$stage_name"
}

reset_shard_dir() {
    local dir; dir="$(shard_dir "$1")"
    rm -rf "$dir"; mkdir -p "$dir"
}

# merge_shards STAGE_NAME OUT_FILE HEADER SHARD_FILE...
# Writes HEADER once, then the content of every existing shard file, in the
# order given. A shard that a job never created (skipped/never reached) is
# simply absent from OUT_FILE, matching what a direct sequential append would
# have produced for that same skip.
merge_shards() {
    local out="$1" header="$2"; shift 2
    printf '%s\n' "$header" > "$out"
    local shard
    for shard in "$@"; do
        [[ -s "$shard" ]] && cat "$shard" >> "$out"
    done
    # A shard that a job never wrote (a skipped/never-reached unit) makes the
    # loop's last `[[ ]]` false. Under `set -e`, when a bare `test && cmd` is
    # the LAST command a function runs, the false test's own exit status
    # becomes the function's -- which then aborts the calling script. This
    # trailing `true` keeps the function's exit status 0 regardless of how
    # the loop's last iteration came out.
    true
}

# Iterate real rows of the sample sheet (skip blank lines, comments, header).
# Prints: sample_id <TAB> assembly_accession <TAB> sra_run
read_samples() {
    local sheet="$1"
    # skip header (first non-comment line), comments, blanks
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        {
            if (!seen_header) { seen_header=1; next }  # drop header row
            print $1"\t"$2"\t"$3
        }
    ' "$sheet"
}

# Fail before expensive stages when the template sheet has not been populated,
# or when identifiers would collide in the per-sample output directories.
validate_sample_sheet() {
    local sheet="$1"
    [[ -f "$sheet" ]] || die "sample sheet not found: $sheet"
    awk -F'\t' '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*$/ {next}
        !seen_header {seen_header=1; next}
        NF < 3 || $1 == "" || $2 == "" || $3 == "" {
            print "ERROR: invalid sample-sheet row " NR "; expected sample_id, assembly_accession, sra_run" > "/dev/stderr"
            bad=1; next
        }
        $1 !~ /^[A-Za-z0-9][A-Za-z0-9._-]*$/ {
            print "ERROR: unsafe sample_id \047" $1 "\047 in row " NR "; use only letters, digits, dot, dash, underscore (it becomes a directory name)" > "/dev/stderr"
            bad=1; next
        }
        curated && (NF < 8 || $4 == "" || $5 == "" || $6 !~ /^[ABC]$/ || $7 == "" || $8 == "") {
            print "ERROR: uncurated sample-sheet row " NR "; require organism, truth_technology, truth_quality_tier (A/B/C), biosample, bioproject" > "/dev/stderr"
            bad=1; next
        }
        seen_sample[$1]++ {
            print "ERROR: duplicate sample_id \047" $1 "\047 in sample sheet" > "/dev/stderr"
            bad=1; next
        }
        {count++}
        END {
            if (bad) exit 2
            if (count == 0) {
                print "ERROR: sample sheet has no data rows; add samples to config/accessions.tsv" > "/dev/stderr"
                exit 3
            }
        }
    ' curated="${REQUIRE_CURATED_METADATA:-1}" "$sheet" || die "fix sample-sheet errors in $sheet"
}

# retry_network DESCRIPTION -- COMMAND...
# Run a network command, retrying with linear backoff. NCBI's SRA and datasets
# endpoints fail transiently, and on a slow or lossy link they fail often. A
# single dropped transfer should not end a multi-hour cohort download, so every
# fetch goes through here. Attempts and delay are configurable via
# NETWORK_RETRIES and NETWORK_RETRY_DELAY_SECONDS.
retry_network() {
    local what="$1"; shift
    local attempts="${NETWORK_RETRIES:-3}"
    local delay="${NETWORK_RETRY_DELAY_SECONDS:-15}"
    local n=1
    while true; do
        if "$@"; then
            [[ "$n" -gt 1 ]] && log "  $what succeeded on attempt $n/$attempts"
            return 0
        fi
        if [[ "$n" -ge "$attempts" ]]; then
            warn "  $what failed after $n attempt(s)"
            return 1
        fi
        warn "  $what failed (attempt $n/$attempts); retrying in $((delay * n))s"
        sleep $((delay * n))
        n=$((n + 1))
    done
}

# sample_column SHEET SAMPLE_ID COLUMN_NAME
# Print one metadata field for one sample, or nothing when the sheet has no
# such column. read_samples() deliberately yields only the three columns every
# stage needs; this is for the optional curation fields (truth_technology,
# gram_group, and the long-read independence declaration Plassembler needs).
sample_column() {
    local sheet="$1" sample="$2" column="$3"
    [[ -f "$sheet" ]] || return 0
    awk -F'\t' -v want="$sample" -v col="$column" '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        !seen { for (i = 1; i <= NF; i++) if ($i == col) c = i; seen = 1; next }
        c && $1 == want { print $c; exit }
    ' "$sheet"
}
