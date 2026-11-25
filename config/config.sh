#!/usr/bin/env bash
# =============================================================================
# PlasBench — central configuration
# Edit this file, then run scripts/run_all.sh
# =============================================================================
# Every script sources this file, so all paths and settings live in one place.

# --- Project root (auto-detected; normally leave as-is) ----------------------
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# --- Where things go ---------------------------------------------------------
# The installer creates this ignored file on first use. It points reusable
# downloads and databases at a stable user location, so upgrading the source
# checkout never redownloads them. Explicit environment variables still win.
LOCAL_SETTINGS="${PLASBENCH_LOCAL_SETTINGS:-$PROJECT_ROOT/config/local.env}"
if [[ -f "$LOCAL_SETTINGS" ]]; then
    # shellcheck disable=SC1090
    source "$LOCAL_SETTINGS"
fi

# --- Run profile -------------------------------------------------------------
# RUN_PROFILE: standard (default; today's behaviour), fast (switches off optional analyses that never change the leaderboard: ISEScan, the ranking-stability and rank-sensitivity sweeps,
# performance drivers, the recommender evaluation, the per-dimension tables, bin agreement, candidate multiplicity, MultiQC) or thorough (turns the optional extras on). The table is
# config/run_profiles.tsv; a profile only sets a key you did not set yourself (an explicit environment variable always wins). The name is recorded in run_manifest.json and the report.
export RUN_PROFILE="${RUN_PROFILE:-standard}"
if [[ "$RUN_PROFILE" != "standard" && -z "${_PB_PROFILE_APPLIED:-}" ]]; then
    _pb_profile_lines="$(python3 -I "$PROJECT_ROOT/python/run_profiles.py" export "$RUN_PROFILE" 2>/dev/null || true)"
    [[ -n "$_pb_profile_lines" ]] && eval "$_pb_profile_lines"
    unset _pb_profile_lines
    export _PB_PROFILE_APPLIED="$RUN_PROFILE"
fi

export DATA_DIR="${DATA_DIR:-${PLASBENCH_DATA_DIR:-$PROJECT_ROOT/data}}" # refs + reads
# Tool databases are kept once per machine, not per project or per DATA_DIR, so
# a new checkout, a new cohort folder or a rebuilt conda environment reuses them
# instead of downloading gigabytes again. A database already at the old
# per-project location ($DATA_DIR/db/...) is still used until the store has its
# own copy (bash env/preserve_databases.sh moves it there).
export PLASBENCH_DB_DIR="${PLASBENCH_DB_DIR:-$HOME/.plasbench/databases}"
plasbench_db_path() {
    local rel="$1"
    if [[ -e "$DATA_DIR/db/$rel" && ! -e "$PLASBENCH_DB_DIR/$rel" ]]; then
        printf '%s' "$DATA_DIR/db/$rel"
    else
        printf '%s' "$PLASBENCH_DB_DIR/$rel"
    fi
}
export RESULTS_DIR="${RESULTS_DIR:-$PROJECT_ROOT/results}" # all outputs
export LOG_DIR="${LOG_DIR:-$PROJECT_ROOT/logs}"
export TMP_DIR="${TMP_DIR:-$PROJECT_ROOT/tmp}"

# --- Sample sheet ------------------------------------------------------------
# TSV with header: sample_id  assembly_accession  sra_run
#   assembly_accession = a COMPLETE genome (GCF_... or GCA_...) with long-read/
#                        hybrid assembly -> ground truth.
#   sra_run            = matched Illumina run (SRR/ERR/DRR) for that isolate.
export SAMPLE_SHEET="${SAMPLE_SHEET:-$PROJECT_ROOT/config/accessions.tsv}"
# Require cohort metadata for a publishable benchmark. Set to 0 only while
# exploring a legacy three-column sample sheet.
export REQUIRE_CURATED_METADATA="${REQUIRE_CURATED_METADATA:-1}"
# When enabled, stage 1 accepts only already staged local inputs and never
# contacts NCBI/SRA. Expected filenames remain deterministic for every stage.
export LOCAL_INPUTS_ONLY="${LOCAL_INPUTS_ONLY:-0}"

# A true AMR-gene table is optional per sample. When supplied as
# data/<sample>/truth_amr.tsv it is scored alongside base-level recovery.
export PLASMID_RECOVERY_THRESHOLD="${PLASMID_RECOVERY_THRESHOLD:-0.90}"
export AMR_GENE_RECOVERY_THRESHOLD="${AMR_GENE_RECOVERY_THRESHOLD:-0.90}"
# Correct Plasmid Reconstruction Rate (CPRR, secondary endpoint; score_bins.py).
# Pre-specify these BEFORE running a benchmark and do not tune them afterwards.
# A truth plasmid counts as correctly reconstructed only if its matched bin
# covers >= CPRR_MIN_COVERAGE of it, it makes up >= CPRR_MIN_SHARE of that
# bin's aligned bases, no other bin holds a substantial part of it, and (only
# for truth NOT polished with the benchmark's own reads) the matched
# alignments reach CPRR_MIN_IDENTITY.
export CPRR_MIN_COVERAGE="${CPRR_MIN_COVERAGE:-0.95}"
export CPRR_MIN_SHARE="${CPRR_MIN_SHARE:-0.95}"
export CPRR_MIN_IDENTITY="${CPRR_MIN_IDENTITY:-0.99}"

# Evidence-based truth labels (python/label_truth_evidence.py, stage 2).
# Replicons whose plasmid/chromosome label conflicts with the evidence
# (plasmid markers, rRNA genes, long-read support) are AMBIGUOUS and excluded
# from scoring via truth.scored.tsv. Needs RUN_REFERENCE_ANNOTATION=1.
export RUN_TRUTH_LABEL_EVIDENCE="${RUN_TRUTH_LABEL_EVIDENCE:-1}"
# The plasmid-reference sketch used for marker evidence is PLASMID_REFERENCE_SKETCH,
# defined once below (DATA_DIR/db/plasmid_reference/reference.msh).
# Plasmids below this long-read depth are short-read-only evidence (lower
# confidence) when the isolate's long reads are staged.
export TRUTH_MIN_LONG_READ_DEPTH="${TRUTH_MIN_LONG_READ_DEPTH:-5}"
export TRUTH_LONG_READ_PRESET="${TRUTH_LONG_READ_PRESET:-map-ont}"
# Labelling scheme the headline is scored on (python/label_schemes.py;
# docs/PANEL_ALIGNMENT.md, decision E.15). Pre-registered primary: ncbi
# (Scheme 3, NCBI sequence-report labels, truth.tsv). Sensitivity schemes,
# always re-ranked by rank_sensitivity.py: nonchromosomal (Scheme 1, every
# replicon but the main chromosome is a plasmid) and evidence (Scheme 2,
# evidence-confirmed labels with AMBIGUOUS replicons excluded, truth.scored.tsv).
export TRUTH_LABEL_SCHEME="${TRUTH_LABEL_SCHEME:-ncbi}"
# Where stage 1 gets short reads: auto (ENA first: chunked, resumable, MD5-verified, no .sra file or FASTQ conversion; the SRA Toolkit only when ENA has no paired FASTQ for the run
# or fails after its retries), sra (SRA Toolkit only), ena (ENA only; python/fetch_ena_reads.py).
export READ_SOURCE="${READ_SOURCE:-auto}"
# Does the window look for a newer PlasBench release by itself? auto (default): when it starts and then at most once a day, one public
# request to GitHub's release list (nothing about you or this computer is sent); off: only when you press Check for updates.
# PLASBENCH_OFFLINE=1 switches every online check off. Installing an update is always your decision (Set up this computer > Updates).
export UPDATE_CHECK="${UPDATE_CHECK:-auto}"
# Keep downloads for future runs: SHA-256 manifest per sample (downloads.sha256),
# read files made read-only, verified instead of re-downloaded next time.
export PRESERVE_DOWNLOADS="${PRESERVE_DOWNLOADS:-1}"
# Tandem-dimer truth plasmids (python/detect_dimers.py, stage 2): halves at
# >= DIMER_MIN_IDENTITY over >= DIMER_MIN_HALF_COVERAGE are a dimer.
# COLLAPSE_DIMERS=1 scores the monomer; 0 only flags it (AMBIGUOUS under the
# evidence scheme). Every change is in <sample>/truth.corrections.tsv.
export RUN_DIMER_DETECTION="${RUN_DIMER_DETECTION:-1}"
# --- Scoring specification (docs/PREREGISTRATION.md, config/prereg.tsv) ------
# Every value below is pre-registered in config/prereg.tsv; freeze_prereg.py
# --verify --check-env reports a run that departs from the plan.
# REQUIRE_PREREG=1 makes stage 4 refuse to run tools unless config/prereg.lock.json
# matches prereg.tsv and no parameter is still TO_FIX.
export REQUIRE_PREREG="${REQUIRE_PREREG:-0}"
# Per-plasmid outcome states (score_bins.py --outcomes-out): perfect when the
# matched bin has precision and recall >= PERFECT_THRESHOLD; fragmented when a
# second bin holds >= FRAGMENT_SHARE of it; missed when best-bin recall <
# MISSED_RECALL; merged when its best bin also matches another plasmid.
export PERFECT_THRESHOLD="${PERFECT_THRESHOLD:-0.95}"
export FRAGMENT_SHARE="${FRAGMENT_SHARE:-0.20}"
export MISSED_RECALL="${MISSED_RECALL:-0.50}"
# Outcome states (stage 4): a failed run is retried TOOL_RETRIES times; an
# infrastructure failure (exit 125/126/127, out of disk) is never scored.
# TOOL_TIMEOUT_SECONDS is the same wall-time budget for every tool, per tool per isolate. Blank = no limit, the confirmed default (a limit scores a slow tool
# zero, and large isolates or many tools make runs of many hours normal). Set one only to stop a truly stuck run, and make it generous (172800 = two days);
# a run that exceeds it fails with exit 124 (resource failure).
export TOOL_RETRIES="${TOOL_RETRIES:-1}"
# Opt-in preset (AU-010): PLASBENCH_TOOL_TIMEOUT_PRESET=generous sets TOOL_TIMEOUT_SECONDS=172800 (two days per tool per isolate) when it is not set explicitly. It is
# off by default because any limit can turn a slow but correct run into a zero score; an explicit TOOL_TIMEOUT_SECONDS always wins; an unknown preset name is an error.
case "${PLASBENCH_TOOL_TIMEOUT_PRESET:-}" in
    "") ;;
    generous) : "${TOOL_TIMEOUT_SECONDS:=172800}" ;;
    *) echo "ERROR: PLASBENCH_TOOL_TIMEOUT_PRESET='${PLASBENCH_TOOL_TIMEOUT_PRESET}' is not a preset (known: generous = 172800 s)" >&2; return 1 2>/dev/null || exit 1 ;;
esac
export TOOL_TIMEOUT_SECONDS="${TOOL_TIMEOUT_SECONDS:-}"
# Recommender evaluation (python/evaluate_recommender.py, stage 6).
export RUN_RECOMMENDER_EVAL="${RUN_RECOMMENDER_EVAL:-1}"
export NEAR_OPTIMAL_MARGIN="${NEAR_OPTIMAL_MARGIN:-0.05}"
export ORACLE_GAP_FLOOR="${ORACLE_GAP_FLOOR:-0.02}"
export RECOMMENDATION_FAILURE_REGRET="${RECOMMENDATION_FAILURE_REGRET:-0.10}"
# Decision D11: when the best expected score is below this, no tool is named.
export RECOMMENDATION_MIN_EXPECTED_SCORE="${RECOMMENDATION_MIN_EXPECTED_SCORE:-0.40}"
# Paired comparisons: |mean delta F1| below this is reported as equivalent.
export SMALLEST_DIFFERENCE="${SMALLEST_DIFFERENCE:-0.05}"
# AMR placement (python/score_amr_placement.py; needs <sample>/truth_amr.tsv).
export RUN_AMR_PLACEMENT="${RUN_AMR_PLACEMENT:-1}"
# Pre-ranking assembly QC gate (python/assembly_qc_gate.py, stage 8; D13).
export RUN_ASSEMBLY_QC_GATE="${RUN_ASSEMBLY_QC_GATE:-1}"
export ASSEMBLY_QC_MAX_SIZE_MB="${ASSEMBLY_QC_MAX_SIZE_MB:-8.5}"
export ASSEMBLY_QC_MAX_GC_SPREAD="${ASSEMBLY_QC_MAX_GC_SPREAD:-0.12}"
export COLLAPSE_DIMERS="${COLLAPSE_DIMERS:-1}"
export DIMER_MIN_IDENTITY="${DIMER_MIN_IDENTITY:-0.95}"
export DIMER_MIN_HALF_COVERAGE="${DIMER_MIN_HALF_COVERAGE:-0.90}"

# Headline rules (aggregate_results.py, stage 6).
# Reference tiers 1-2 form the headline; tier 3 (short-read-first or unknown
# provenance) is a sensitivity analysis. The headline averages per-species
# means over species with at least MIN_SPECIES_CLUSTERS independent
# (non-clonal) clusters; smaller species are described only.
export MIN_SPECIES_CLUSTERS="${MIN_SPECIES_CLUSTERS:-20}"
# Clonal clusters (python/clonal_groups.py): isolates whose chromosomes are
# within this Mash distance are treated as one clonal unit.
export CLONAL_MASH_DISTANCE="${CLONAL_MASH_DISTANCE:-0.0005}"
# Operational recommendations are withheld unless a tool has enough independent
# benchmark evidence. Selection reports still preserve truth-set candidates.
export RECOMMENDATION_MIN_SAMPLES="${RECOMMENDATION_MIN_SAMPLES:-5}"
export RECOMMENDATION_MIN_COVERAGE="${RECOMMENDATION_MIN_COVERAGE:-0.80}"
export ANALYSIS_TRACK="${ANALYSIS_TRACK:-short_read}"
# Optional filter for stage 5: when set, score only tools whose
# config/tool_capabilities.tsv analysis_track matches this value. Leave empty
# (default) to score every enabled tool under its own correctly-declared
# track in one run -- each tool's track comes from the registry, not this
# variable. NOTE: stage 5 rebuilds scores.tsv from scratch every run, so
# setting a filter means tools OUTSIDE it get no row at all this run, not
# merely "left unchanged" -- if you need a complete scores.tsv across every
# track, run stage 5 once with this unset rather than once per track.
export ANALYSIS_TRACK_FILTER="${ANALYSIS_TRACK_FILTER:-}"

# --- Compute -----------------------------------------------------------------
# --- Network resilience ------------------------------------------------------
# NCBI transfers fail transiently, and more often on a slow link. Stage 1
# retries each fetch this many times before recording the sample as failed.
export NETWORK_RETRIES="${NETWORK_RETRIES:-3}"
export NETWORK_RETRY_DELAY_SECONDS="${NETWORK_RETRY_DELAY_SECONDS:-15}"
# An OPT-IN limit, blank by default: PlasBench never skips an isolate because its reads are big. If YOU set a number (GB), an isolate whose reads to download (after the
# READ_DEPTH_CAP_X cut below) are above it is skipped and recorded as failed with the reason; re-running stage 1 retries it once the limit is raised or cleared.
export MAX_RUN_DOWNLOAD_GB="${MAX_RUN_DOWNLOAD_GB:-}"
# Warn (never stop) when one isolate's reads are larger than this many GB (default 5; 0 = never warn). The warning says what a read set that size costs in time, disk
# (about three times its size) and assembly memory.
export WARN_RUN_DOWNLOAD_GB="${WARN_RUN_DOWNLOAD_GB:-5}"
# Read-depth cap, in x coverage (default 150; 0 or off = whole files). For a short paired Illumina run deeper than this, stage 1 downloads only the first read pairs of both mates
# (HTTP Range prefix, cut at a complete record, recompressed): the number of pairs that gives this depth over the reference genome's size. Depth beyond about 100-150x costs hours
# of download, trimming and assembly (and gigabytes of memory) and buys nothing. The prefix is the start of the sequencer's output, not a random sample, and has no whole-file MD5
# (its structure is checked instead); both facts are recorded in <run>.ena_provenance.json and the run manifest. Long-read and unpaired runs, runs within the cap, and isolates
# without a reference size are always fetched whole. Files already on disk are kept: delete them to fetch again under a different cap.
export READ_DEPTH_CAP_X="${READ_DEPTH_CAP_X:-150}"
# With READ_SOURCE=auto: once the SRA Toolkit's prefetch has failed, and ENA has worked, for this many isolates in a row, stage 1 fetches from ENA first for the rest of
# the run. That saves about a minute per isolate when the toolkit cannot connect. 0 = always try prefetch first. The count restarts each time stage 1 starts.
export PREFETCH_FAIL_LIMIT="${PREFETCH_FAIL_LIMIT:-2}"
# While reads download, stage 1 looks at the download this often (seconds). The run log stays quiet: the first line, then at most one short line per 10% and per 5 minutes, and a
# line when something changes (a retry, a stall, a lower connection budget, a restart). The live detail is in results/download_progress.json. 0 = no progress lines.
export DOWNLOAD_PROGRESS_SECONDS="${DOWNLOAD_PROGRESS_SECONDS:-30}"
# ENA connections. ENA_MAX_CONNECTIONS is the TOTAL number of connections open at once (default 16, hard maximum 24), shared fairly by the two mates (and split between
# parallel downloads). 16 is what aria2c itself allows per server and what a measured speed test (docs/USER_GUIDE.md, "My downloads are slow or restart") kept gaining from;
# more risks the address being throttled. If ENA answers 429/503 or refuses connections, the budget is lowered for the rest of the run. ENA_DOWNLOAD_CONNECTIONS (blank by default)
# caps the connections of each FILE. `plasbench net-bench` measures 1, 4, 8 and 16 connections and recommends a figure.
export ENA_MAX_CONNECTIONS="${ENA_MAX_CONNECTIONS:-16}"
export ENA_DOWNLOAD_CONNECTIONS="${ENA_DOWNLOAD_CONNECTIONS:-}"
# Size in MiB of the pieces a file is fetched in (default 32). A failed connection costs at most one piece; finished pieces are recorded in <file>.part.state and kept for the
# next attempt or the next run.
export ENA_CHUNK_MIB="${ENA_CHUNK_MIB:-32}"
# Seconds without a single byte after which a connection is abandoned and its piece retried (default 45).
export ENA_STALL_SECONDS="${ENA_STALL_SECONDS:-45}"
# 1 uses aria2c (when installed) for the transfer instead of the built-in downloader. Off by default: the built-in one resumes by piece, reports honest progress and keeps to
# the connection budget.
export ENA_USE_ARIA2="${ENA_USE_ARIA2:-0}"
# Where reads are downloaded and checksummed. auto (default): a folder under ~/.plasbench/downloads/<study> on the local disk when the data folder is on a slow mount (a Windows
# drive seen from WSL, NTFS/exFAT, a network share, FUSE), then the verified file is moved into place; otherwise the data folder itself. data = always the data folder. Any other
# value = that folder (never a memory-backed one). Free space (file size plus a margin) is checked first.
export DOWNLOAD_TMP_DIR="${DOWNLOAD_TMP_DIR:-auto}"
# Show the estimated download size and ask before stage 1 fetches anything (1, the default). 0 skips the question. It is never asked when there is no terminal
# (the window, CI, a container), so those runs proceed.
export DOWNLOAD_CONFIRM="${DOWNLOAD_CONFIRM:-1}"
# Before stage 1 downloads, PlasBench asks ENA for the exact compressed size of each run that the cohort's lock file has no base count for, so the estimate is real and
# names the largest read set. 0 skips the lookup (it is also skipped when READ_SOURCE=sra, which never uses ENA).
export ENA_SIZE_LOOKUP="${ENA_SIZE_LOOKUP:-1}"
# Work offline on purpose. 1 switches every online-only action off at once (downloads, installs, upgrades, NCBI/ENA lookups, GitHub): each says plainly that it needs the
# internet instead of trying. Scoring, reports and runs on files already on disk (--local-inputs) keep working. 0 (default) = use the internet when it is needed.
export PLASBENCH_OFFLINE="${PLASBENCH_OFFLINE:-0}"
# Seconds to wait for each service when PlasBench checks the connection before an online step (config/network_services.tsv lists the services; `plasbench net` shows them).
# Raise it on a slow or satellite link. Default 5.
export PLASBENCH_ONLINE_TIMEOUT="${PLASBENCH_ONLINE_TIMEOUT:-5}"
# --- Run health and reliability ------------------------------------------------
# Stage 4 exits with code 4 when every tool run failed, because there is nothing to score. 1 continues anyway with a warning (the report is then empty of results).
export ALLOW_ALL_TOOLS_FAILED="${ALLOW_ALL_TOOLS_FAILED:-0}"
# Warn (never stop) before stage 1 when the drive holding the data folder has less than this many GB free. 0 turns the warning off.
export MIN_FREE_DISK_GB="${MIN_FREE_DISK_GB:-20}"
# Before stages 0, 2 and 3 PlasBench checks free disk (study, data and temporary folders, and under WSL the Windows drive holding Ubuntu's virtual disk), memory,
# usable CPUs and writable folders (python/preflight_resources.py). Too little disk for the isolates still to do stops the stage (exit 6) with the figures.
# 1 skips the disk figures only (the writable-folder and memory checks still run). Default 0.
# Only what cannot even START is a block: the first isolates' working set (peak per isolate x MAX_PARALLEL_SAMPLES) must fit. A whole cohort that will not fit is a WARNING with the
# number of isolates that will, and the run stops cleanly when space runs out (the rolling guard below), keeping every finished isolate.
export PLASBENCH_SKIP_DISK_CHECK="${PLASBENCH_SKIP_DISK_CHECK:-0}"
# The rolling guard checks, before each isolate's download (stage 1) and assembly (stage 3), that the drives it writes to have room for that isolate plus this many GB of reserve;
# if not, the stage stops cleanly with exit 6 (finished isolates are kept; run the same command again after freeing space). 0 keeps no reserve. Default 5.
export PLASBENCH_DISK_RESERVE_GB="${PLASBENCH_DISK_RESERVE_GB:-5}"
# Under WSL, Ubuntu's own disk is a file on a Windows drive. When the study, data and temporary folders are on a mounted Windows drive (/mnt/e) only small things go to Ubuntu's
# disk (conda environments, logs), so only this hard floor (GB free on the Windows drive holding Ubuntu's disk) stops the run; under 10 GB is a warning. Default 2.
export PLASBENCH_VDISK_MIN_GB="${PLASBENCH_VDISK_MIN_GB:-2}"
# 1 skips the whole resource check. Default 0.
export PLASBENCH_SKIP_RESOURCE_CHECK="${PLASBENCH_SKIP_RESOURCE_CHECK:-0}"
# 1 (default) lowers THREADS to the CPUs this process can really use (CPU count, affinity, container quota, WSL processors=) when you ask for more; 0 keeps your number.
export CAP_THREADS_TO_CPUS="${CAP_THREADS_TO_CPUS:-1}"
# 1 (default): when SPAdes fails for lack of memory, stage 3 retries that isolate ONCE with half the threads and a memory budget that fits the memory free now (never above
# it), or once more after removing its own unfinished assembly folder. Never more than one retry. 0 never retries; the failure is still diagnosed.
export ASSEMBLER_AUTO_RETRY="${ASSEMBLER_AUTO_RETRY:-1}"
# Time limit, in seconds, for every helper subprocess in python/ (subsampling, alignment helpers, analysis scripts). 0 or off removes the limit. Default 21600 (6 hours).
export PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS="${PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS:-21600}"
# A run holds RESULTS_DIR/.run.lock and touches .run.lock.heartbeat every this many seconds, so a second run on the same results folder is refused.
export PLASBENCH_LOCK_HEARTBEAT_SECONDS="${PLASBENCH_LOCK_HEARTBEAT_SECONDS:-5}"
# A lock whose heartbeat is older than this many seconds is taken over even if its process id is alive (a killed run, or a process id that was reused). Default 60.
export PLASBENCH_LOCK_STALE_SECONDS="${PLASBENCH_LOCK_STALE_SECONDS:-60}"
# 1 refuses a database download that has no pinned SHA-256 (an environment variable such as MOBSUITE_DB_SHA256, or a row in config/download_checksums.tsv). 0 (default)
# downloads, prints the checksum it observed and records it in download_provenance.jsonl.
export PLASBENCH_REQUIRE_CHECKSUMS="${PLASBENCH_REQUIRE_CHECKSUMS:-0}"
# Aggregation stops when the run tables disagree (a missing column, a non-finite value, a status that contradicts a score). 1 ranks anyway; the report then carries a
# warning not to quote it.
export ALLOW_INCONSISTENT_RUNS="${ALLOW_INCONSISTENT_RUNS:-0}"
# The report builder refuses a leaderboard that was not ranked from the scores it is given. 1 builds the report anyway (the mismatch is still printed).
export ALLOW_INPUT_MISMATCH="${ALLOW_INPUT_MISMATCH:-0}"
# The leaderboard flags a shared-sample set smaller than this fraction of the largest tool's samples (ranking_warning). The ranking itself is not changed. Default 0.5.
export SHARED_MIN_FRACTION="${SHARED_MIN_FRACTION:-0.5}"
# ...or smaller than this many samples. Default 5.
export SHARED_MIN_SAMPLES="${SHARED_MIN_SAMPLES:-5}"
# Stage 6 writes the headline with and without the replicon-database exclusion of marker-free plasmids (benchmark.truth_exclusion_sensitivity.tsv). 0 skips it.
export RUN_TRUTH_EXCLUSION_SENSITIVITY="${RUN_TRUTH_EXCLUSION_SENSITIVITY:-1}"
# --- Network resilience (continued) --------------------------------------------
# Long commands continue normally, but after this many quiet seconds PlasBench
# prints a live elapsed-time status line. This is especially useful while
# Conda links MOB-suite or a tool writes its detailed output only to a log.
export HEARTBEAT_DELAY_SECONDS="${HEARTBEAT_DELAY_SECONDS:-180}"
export HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-60}"

# Defaults are derived from the machine, not fixed. One fixed number is wrong at
# both ends: 16GB told SPAdes it had four times the RAM on a 4GB box, turning
# 12-minute assemblies into two-hour ones as it swapped, while leaving three
# quarters of a 64GB box unused. Detection is advisory -- an explicit THREADS or
# MEMORY_GB (or --threads/--memory-gb) always wins, with no upper limit imposed.
plasbench_detect_cores() {
    if command -v nproc >/dev/null 2>&1; then nproc
    elif [[ -r /proc/cpuinfo ]]; then grep -c '^processor' /proc/cpuinfo
    elif command -v sysctl >/dev/null 2>&1; then sysctl -n hw.ncpu 2>/dev/null || echo 4
    else echo 4; fi
}

# Available memory, not total: what another process already holds is not ours
# to promise SPAdes.
plasbench_detect_memory_gb() {
    local kb="" bytes=""
    if [[ -r /proc/meminfo ]]; then
        kb="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)"
        [[ -z "$kb" ]] && kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
    elif command -v sysctl >/dev/null 2>&1; then
        bytes="$(sysctl -n hw.memsize 2>/dev/null || true)"
        [[ -n "$bytes" ]] && kb=$(( bytes / 1024 ))
    fi
    [[ -z "$kb" || "$kb" -le 0 ]] && { echo 8; return; }
    echo $(( kb / 1024 / 1024 ))
}

# Same figure in MB, so a 6.9 GB machine is not treated as a 6 GB one (the integer GB figure above rounds DOWN, which cut the default budget from 5 GB to 4 GB). Memory
# available to this process: MemAvailable, or what a container/cgroup limit leaves when that is smaller (cgroup v2 memory.max/current, v1 limit/usage).
plasbench_detect_memory_mb() {
    local kb="" limit="" used="" mb=""
    if [[ -r /proc/meminfo ]]; then
        kb="$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo)"
        [[ -z "$kb" ]] && kb="$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo)"
    elif command -v sysctl >/dev/null 2>&1; then
        kb="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 ))"
    fi
    [[ "$kb" =~ ^[0-9]+$ && "$kb" -gt 0 ]] || { echo 8192; return; }
    mb=$(( kb / 1024 ))
    if [[ -r /sys/fs/cgroup/memory.max ]]; then
        limit="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)"; used="$(cat /sys/fs/cgroup/memory.current 2>/dev/null || true)"
    elif [[ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]]; then
        limit="$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)"; used="$(cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null || true)"
    fi
    if [[ "$limit" =~ ^[0-9]+$ && "$used" =~ ^[0-9]+$ && "$limit" -lt 1125899906842624 ]]; then
        local room=$(( (limit - used) / 1048576 ))
        [[ "$room" -ge 0 && "$room" -lt "$mb" ]] && mb="$room"
    fi
    echo "$mb"
}

# plasbench_default_budget_gb AVAILABLE_MB: the default assembler memory budget, in whole GB: 85% of what is available now minus 512 MB for the OS (and WSL), rounded
# down from MB (so 6.9 GB available gives 5, not the 4 an integer-GB 80% gave), never below 2 and never above 64 (a sanity bound; MEMORY_GB has no bound).
plasbench_default_budget_gb() {
    local mb="$1" gb
    gb=$(( (mb * 85 / 100 - 512) / 1024 ))
    [[ "$gb" -lt 2 ]] && gb=2
    [[ "$gb" -gt 64 ]] && gb=64
    echo "$gb"
}

# Thread budget. When THREADS is not set, the detected cores are divided across the
# concurrent job slots (MAX_PARALLEL_SAMPLES x MAX_PARALLEL_TOOLS, below), so raising
# the slots cannot make every job ask for every core at once (oversubscription:
# context switching and cache thrashing, slower than fewer jobs). With the default
# single slot this is all cores, as before; an explicit THREADS always wins.
# Which of these YOU set (AUTO_PARALLEL never changes an explicit value). Recorded once, by the first config.sh of a run, and inherited by every stage.
export PLASBENCH_THREADS_EXPLICIT="${PLASBENCH_THREADS_EXPLICIT:-$([[ -n "${THREADS:-}" ]] && echo 1 || echo 0)}"
export PLASBENCH_SAMPLES_EXPLICIT="${PLASBENCH_SAMPLES_EXPLICIT:-$([[ -n "${MAX_PARALLEL_SAMPLES:-}" ]] && echo 1 || echo 0)}"
if [[ -z "${THREADS:-}" ]]; then
    PLASBENCH_JOB_SLOTS=$(( ${MAX_PARALLEL_SAMPLES:-1} * ${MAX_PARALLEL_TOOLS:-1} ))
    [[ "$PLASBENCH_JOB_SLOTS" -ge 1 ]] || PLASBENCH_JOB_SLOTS=1
    THREADS=$(( $(plasbench_detect_cores) / PLASBENCH_JOB_SLOTS ))
    [[ "$THREADS" -ge 1 ]] || THREADS=1
fi
export THREADS

# Keep headroom: the OS, the other tools in the stage, and SPAdes overshooting
# its own budget all need room. 80% of what is actually available, never below
# 2GB (SPAdes fails outright under that) and never silently capped above.
PLASBENCH_AVAILABLE_MB="${PLASBENCH_TEST_AVAILABLE_MB:-$(plasbench_detect_memory_mb)}"   # (the TEST variable only lets a test pretend to be a smaller or larger machine)
PLASBENCH_AVAILABLE_GB="$(( PLASBENCH_AVAILABLE_MB / 1024 ))"
PLASBENCH_DEFAULT_MEMORY_GB="$(plasbench_default_budget_gb "$PLASBENCH_AVAILABLE_MB")"
export PLASBENCH_AVAILABLE_GB PLASBENCH_AVAILABLE_MB
export MEMORY_GB="${MEMORY_GB:-$PLASBENCH_DEFAULT_MEMORY_GB}"   # assembler memory budget (GB)

# AUTO_RESOURCES (1 = on, the default; 0 = fixed behaviour): PlasBench adapts resources by itself, deterministically, and logs every change. (1) the assembler memory budget starts at
# 85% of the memory free now minus 512 MB; (2) when SPAdes says what it needs ("You need approx. X GB of free RAM") the isolate is retried ONCE with -m = ceil(X x 1.15 + 0.5) when that
# fits in the free memory, and the need is remembered per isolate (results/assembly_memory.tsv) so a resume starts at the right budget; (3) when it does not fit that isolate is skipped
# with the exact need and the others continue; (4) a tool killed for memory (exit 137) in stage 4 is retried once with half the threads (tools that read THREADS at run time).
# An explicit MEMORY_GB / --memory-gb is still the starting budget. AUTO_RESOURCES=0 restores one attempt with the budget you set.
export AUTO_RESOURCES="${AUTO_RESOURCES:-1}"
# ASSEMBLER_ALLOW_ONLY_ASSEMBLER (default 0): when an isolate's need does not fit in the free memory, retry once with SPAdes --only-assembler (skips read error correction, the
# hammer step that needs the most memory). It can change the assembly, so it is off by default, and an isolate assembled this way is recorded as mode only-assembler in
# assembly_status.tsv, assembly_memory.tsv and run_manifest.json.
export ASSEMBLER_ALLOW_ONLY_ASSEMBLER="${ASSEMBLER_ALLOW_ONLY_ASSEMBLER:-0}"
# --- Work folder, annotation time limits and the slow-step note ------------------------------------
# WORK_DIR: where stages 3 and 4 do their file-heavy work. auto (default) = a local folder under ~/.plasbench/scratch/<study> when the data (or results) folder is on a slow
# mount (a Windows drive seen from WSL, NTFS/exFAT, a network share, a cloud-synced folder), else in place; data = always in place; any other value = that folder. Stage 3:
# SPAdes works there on a local copy of the trimmed reads and its results are moved back atomically. Stage 4: a tool's output folder is made there and copied back whole
# when the tool ends (results folder slow); plasmidSPAdes reads a local copy of the trimmed reads (data folder slow). Takes effect at the next stage start.
export WORK_DIR="${WORK_DIR:-auto}"
# ANNOTATION_TIMEOUT_SECONDS: per annotation caller (mob_typer, abricate, AMRFinder, ISEScan, barrnap). Blank = max(300, 150 s per Mbp of the reference), ISEScan three times that;
# a number = that many seconds; 0 or off = no limit. A caller that hits the limit is stopped and recorded as timed_out (never cached); the others are kept.
export ANNOTATION_TIMEOUT_SECONDS="${ANNOTATION_TIMEOUT_SECONDS:-}"
# STEP_SLOW_FACTOR: a long command that has run this many times its typical time (config/step_typical.tsv) gets ONE "still running, typical N min" note and a slow_step event.
# Nothing is stopped by it. 0 turns it off.
export STEP_SLOW_FACTOR="${STEP_SLOW_FACTOR:-3}"
# KEEP_AWAKE (default 1): while a run is active the computer is asked not to go to sleep (the screen may still turn off; nothing outside the run's life is changed, no administrator
# rights are needed; python/keep_awake.py). 0 = do not ask. A computer that sleeps anyway pauses the run: the gap is recorded (system_suspend event), left out of every elapsed time,
# slow-step note, "no new output" figure and caller time limit, and shown by `plasbench status`.
export KEEP_AWAKE="${KEEP_AWAKE:-1}"
# SUSPEND_MIN_SECONDS (default 60): a pause of the clock longer than this that the run did not cause is treated as the computer having been asleep.
export SUSPEND_MIN_SECONDS="${SUSPEND_MIN_SECONDS:-60}"

# --- Parallelism ---------------------------------------------------------
# Every default below (1) is exactly today's fully sequential behavior: one
# sample at a time, one tool at a time. Raise them only after checking your
# machine's core/RAM budget below can actually support it -- e.g. 2 parallel
# samples x 2 parallel tools x THREADS=4 wants 16 CPU threads at once.
export MAX_PARALLEL_SAMPLES="${MAX_PARALLEL_SAMPLES:-1}"   # stages 2, 3, 4, 5
# AUTO_PARALLEL (default 1; 0 = off): when you have not set MAX_PARALLEL_SAMPLES, stages 2 (truth and reference annotation) and 5 (scoring) run several isolates at once,
# sized to this computer's CPUs and free memory, and the threads are DIVIDED between them (never more threads than CPUs); stage 3 (assembly) stays at one isolate unless the
# free memory holds two assemblies or more; stage 4 is unchanged. The plan is printed at the start of the run and of each stage. Results are identical (python/parallel_plan.py).
export AUTO_PARALLEL="${AUTO_PARALLEL:-1}"
# ASSEMBLY_SLOT_GB (default 8): the memory one assembly is assumed to need when the run has not learned it yet; AUTO_PARALLEL runs two assemblies at once only when
# two of these (plus 15% and 0.5 GB each) fit in 85% of the free memory.
export ASSEMBLY_SLOT_GB="${ASSEMBLY_SLOT_GB:-8}"
# PIPELINE_OVERLAP (default 0 = off): 1 starts stage 2 for an isolate as soon as stage 1 has downloaded it in this run, while stage 1 goes on with the others (one isolate at a
# time, low priority, its own status files; python/pipeline_overlap.py). Stage 2 still runs afterwards over every isolate and reuses that work, so results are the same.
# Opt-in: it adds CPU and disk work during the downloads, and `plasbench status` still shows stage 1 while it runs (its progress is in logs/pipeline_overlap.log).
export PIPELINE_OVERLAP="${PIPELINE_OVERLAP:-0}"
# Isolates downloaded at the same time in stage 1 (default 1). Keep 1 while one isolate already fills your link (see the MB/s lines or `plasbench net-bench`); to try 2 or 3 raise it
# and compare the MB/s. ENA_MAX_CONNECTIONS is still the total: each download gets its share.
export MAX_PARALLEL_DOWNLOADS="${MAX_PARALLEL_DOWNLOADS:-1}"
export MAX_PARALLEL_TOOLS="${MAX_PARALLEL_TOOLS:-1}"       # independent tools within one sample, stage 4
# Stage 6's advisory analyses (stratified recovery, truth audits, copy number, repeat
# content, bin agreement, the dimension tables, rank sensitivity) are independent
# light-weight Python jobs; this many run at once. 1 restores the serial order (and a
# strictly ordered log). The leaderboard itself is always computed first, alone.
export STAGE6_PARALLEL_JOBS="${STAGE6_PARALLEL_JOBS:-4}"
# Per-tool thread counts. Each defaults to $THREADS (today's behavior: every
# tool gets the same value); set these independently once you run tools
# concurrently, so N concurrent tools don't each ask for all of $THREADS.
export MOB_RECON_THREADS="${MOB_RECON_THREADS:-$THREADS}"
export PLATON_THREADS="${PLATON_THREADS:-$THREADS}"
export PLASMIDSPADES_THREADS="${PLASMIDSPADES_THREADS:-$THREADS}"
# NOT currently wired into any invocation: the gplas binary itself takes no
# thread flag (confirmed single-threaded), and neither
# python/mob_to_gplas_classifier.py nor python/validate_gplas_classifier.py
# (gplas2_mob/gplas2_external's own classifier-prep steps) accept one either
# -- both are lightweight single-threaded table/graph transformations, not
# compute-heavy work. Kept only for interface consistency with every other
# tool's own <TOOL>_THREADS var; do not assume setting this changes gplas2's
# actual runtime.
export GPLAS_THREADS="${GPLAS_THREADS:-$THREADS}"
export GENOMAD_THREADS="${GENOMAD_THREADS:-$THREADS}"
# Per-tool memory estimates (GB), used only for the oversubscription warning
# in lib.sh's warn_resource_oversubscription -- advisory, never enforced.
export PLASMIDSPADES_MEMORY_GB="${PLASMIDSPADES_MEMORY_GB:-$MEMORY_GB}"
export ASSEMBLY_MEMORY_GB="${ASSEMBLY_MEMORY_GB:-$MEMORY_GB}"  # stage 3 (SPAdes/Unicycler)

# --- Which tools to benchmark (1 = on, 0 = off) ------------------------------
# Turn tools off if you have not installed them yet.
export RUN_MOB_RECON="${RUN_MOB_RECON:-1}"
export RUN_PLATON="${RUN_PLATON:-1}"
export RUN_PLASMIDSPADES="${RUN_PLASMIDSPADES:-1}"
 # gplas2 modes are kept separate because binning quality depends on the source
# classifier. External prediction TSVs must use gplas2's documented columns.
export RUN_GPLAS2_MOB="${RUN_GPLAS2_MOB:-0}"
export RUN_GPLAS2_EXTERNAL="${RUN_GPLAS2_EXTERNAL:-0}"
# ML/graph-based classifier, off by default. Exposes a per-contig
# plasmid_score, so it is also scored with an optional PR-curve/PR-AUC sweep
# alongside its own hard call -- see adapters/SCORES.md.
export RUN_GENOMAD="${RUN_GENOMAD:-0}"
# Alignment+transformer classifier, off by default. Like geNomad, exposes a
# per-contig score (its own "score" column) and is PR-curve/PR-AUC scored.
# Distributed as a git checkout with its own conda env, not a bioconda
# package (see env/install_tools.sh's plasme case) -- PLASMe.py itself is
# expected on PATH after manual setup, the same convention this project
# already uses for gplas2.
export RUN_PLASME="${RUN_PLASME:-0}"
export PLASME_THREADS="${PLASME_THREADS:-$THREADS}"
export PLASME_PROBABILITY="${PLASME_PROBABILITY:-0.5}"
# Purely informational (like PLASGRAPH2_VERSION below): the git checkout has
# no version command to query. PLASME_VERSION records the git tag/commit for
# readability; PLASME_CHECKOUT_DIR (optional) points at the actual clone so
# write_manifest.py can additionally record its content-hash identity
# (directory_identity()) for provenance, the same treatment plASgraph2 gets.
export PLASME_VERSION="${PLASME_VERSION:-}"
export PLASME_CHECKOUT_DIR="${PLASME_CHECKOUT_DIR:-}"
# plASgraph2: a GNN per-node classifier over the assembly graph (needs the
# same assembly_graph.gfa gplas2 uses -- set ASSEMBLER=unicycler for the
# cleanest graphs). Off by default. Like geNomad/PLASMe, exposes a per-node
# plasmid_score and is PR-curve/PR-AUC scored; unlike them it produces no
# derived multi-contig grouping in its own output, so binning_capable=no
# (config/tool_capabilities.tsv). Distributed as a git checkout with its own
# conda env (TensorFlow/Spektral), not a bioconda package -- see
# env/install_tools.sh's plasgraph2 case -- and the pretrained model ships
# inside that checkout, so PLASGRAPH2_MODEL_DIR must point at it.
export RUN_PLASGRAPH2="${RUN_PLASGRAPH2:-0}"
export PLASGRAPH2_MODEL_DIR="${PLASGRAPH2_MODEL_DIR:-}"
# Purely informational (like a database, the checkout has no version command
# to query): record the git tag/commit of the plASgraph2 checkout you cloned,
# for readability in run_manifest.json alongside PLASGRAPH2_MODEL_DIR's own
# content hash (directory_identity(), which identifies the actual state used
# regardless of whether this string is kept in sync).
export PLASGRAPH2_VERSION="${PLASGRAPH2_VERSION:-}"
# Forces CPU-only execution (CUDA_VISIBLE_DEVICES="") for deterministic,
# GPU-independent runs. Set to 0 to let plASgraph2/TensorFlow use a GPU if
# one is available and configured.
export PLASGRAPH2_CPU_ONLY="${PLASGRAPH2_CPU_ONLY:-1}"
# RFPlasmid: a random-forest classifier over single-copy marker genes,
# plasmid genes, and kmers, trained per species/genus (see specieslist.txt
# in its own checkout/package for the full list -- e.g. Enterobacteriaceae,
# Enterococcus, Staphylococcus, Generic). Off by default. Exposes a per-contig
# "votes plasmid" fraction in [0,1] (its underlying random forest's vote
# share), so it is also PR-curve/PR-AUC scored alongside its own hard call --
# see adapters/SCORES.md. Bioconda package (env/install_tools.sh's rfplasmid
# case), but bundles CheckM as a transitive dependency, and CheckM always
# needs its own ~1.4GB reference data directory set up once regardless of how
# it was installed (`checkm data setRoot`, see CheckM's own docs) -- a real
# prerequisite beyond the bioconda install itself, not a PlasBench-specific
# database this project downloads for you.
export RUN_RFPLASMID="${RUN_RFPLASMID:-0}"
export RFPLASMID_THREADS="${RFPLASMID_THREADS:-$THREADS}"
export RFPLASMID_SPECIES="${RFPLASMID_SPECIES:-Enterobacteriaceae}"
# --jelly (Jellyfish-based kmer counting) is RFPlasmid's own recommended,
# faster path and is bundled by the bioconda package -- on by default here.
export RFPLASMID_JELLY="${RFPLASMID_JELLY:-1}"
# PlasmidHunter: a Diamond+Prodigal gene-content classifier over a single
# species-agnostic Naive Bayes model (no per-species/genus model choice,
# unlike RFPlasmid). Off by default. Exposes a per-contig "Probability of 1"
# (plasmid-class probability) in [0,1], so it is also PR-curve/PR-AUC scored
# alongside its own hard call -- see adapters/SCORES.md. Installed via
# `pip install plasmidhunter` plus its diamond/prodigal conda deps (both
# already available via existing profiles; see env/install_tools.sh).
export RUN_PLASMIDHUNTER="${RUN_PLASMIDHUNTER:-0}"
export PLASMIDHUNTER_THREADS="${PLASMIDHUNTER_THREADS:-$THREADS}"
# Plasmer: a heavy multi-tool ensemble classifier (kmer-db + Prodigal +
# HMMER + BLAST + Infernal + Diamond + Kraken2 feeding an R random-forest)
# requiring a custom conda channel and a real, documented minimum of 32GB
# system RAM (its own README: "A minimum of 32GB system memory is required
# for kmer-db to load the databases"). Off by default. Exposes a per-contig
# plasmid-class probability for every contig that actually went through its
# random-forest model (its own predProb.tsv -- contigs excluded by its own
# length rules have no probability at all), so it is also PR-curve/PR-AUC
# scored -- see adapters/SCORES.md. A pre-built database (Zenodo/Google
# Drive, not bundled by the package) must be downloaded separately and
# pointed at via PLASMER_DB; see INSTALL.md.
export RUN_PLASMER="${RUN_PLASMER:-0}"
export PLASMER_THREADS="${PLASMER_THREADS:-$THREADS}"
export PLASMER_DB="${PLASMER_DB:-$(plasbench_db_path plasmer)}"
export PLASMER_MIN_LENGTH="${PLASMER_MIN_LENGTH:-500}"     # Plasmer's own -m default
export PLASMER_LENGTH="${PLASMER_LENGTH:-500000}"          # Plasmer's own -l (chromosome length threshold) default
# A real, documented kmer-db RAM floor -- deliberately NOT derived from the
# general $MEMORY_GB assembler budget above, since this is a fixed
# requirement of Plasmer's own database-loading step, not something that
# scales with this machine's available memory.
export PLASMER_MEMORY_GB="${PLASMER_MEMORY_GB:-32}"
# PlaScope: Centrifuge classification (chromosome/plasmid/unclassified hard
# call, no continuous score) against a SPECIES-SPECIFIC custom database.
# Off by default. Only two pre-built databases exist (Zenodo), so
# run_plascope() (scripts/04_run_tools.sh) skips every sample whose
# config/accessions.tsv "organism" column is not Escherichia coli or
# Klebsiella, with a distinct "no PlaScope database for organism <X>" reason
# -- a structural limitation, never conflated with "command unavailable".
export RUN_PLASCOPE="${RUN_PLASCOPE:-0}"
export PLASCOPE_THREADS="${PLASCOPE_THREADS:-$THREADS}"
# Each is a full Centrifuge index PREFIX (dir + basename, no .N.cf suffix),
# matching the basename each Zenodo record actually ships -- the two
# databases use different basenames, so no shared PLASCOPE_DB_DIR var is
# needed; run_plascope() derives --db_dir/--db_name from whichever prefix
# applies via dirname/basename.
export PLASCOPE_ECOLI_DB="${PLASCOPE_ECOLI_DB:-$(plasbench_db_path plascope/ecoli/chromosome_plasmid_db)}"           # Zenodo 10.5281/zenodo.1311641
export PLASCOPE_KLEBSIELLA_DB="${PLASCOPE_KLEBSIELLA_DB:-$(plasbench_db_path plascope/klebsiella/Klebsiella_PlaScope)}"  # Zenodo 10.5281/zenodo.1311647
export RUN_FLYE_MOB_RECON="${RUN_FLYE_MOB_RECON:-0}"
export FLYE_MOB_RECON_THREADS="${FLYE_MOB_RECON_THREADS:-$THREADS}"
# CIRCULARITY GUARD (see scripts/lib.sh: long_read_truth_eligible). Off by
# default: a sample without a declared truth_independent_of_long_reads=yes is
# skipped for flye_mob_recon rather than scored against its own input. Setting
# this to 1 overrides that for every sample; the override is recorded in
# tool_status.tsv so a result can never silently look independent when it was
# not -- same policy as PLASSEMBLER_ALLOW_CIRCULAR_TRUTH below.
export FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH="${FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH:-0}"

# Plassembler assembles plasmids from HYBRID input: the short reads stage 1
# already downloads, plus long reads staged as data/<sample>/$LONG_READS_FILE.
# Off by default. It is scored on its own track (ANALYSIS_TRACK=hybrid) and is
# never ranked against short-read-only tools -- see docs/METHODS.md.
export RUN_PLASSEMBLER="${RUN_PLASSEMBLER:-0}"
export PLASSEMBLER_THREADS="${PLASSEMBLER_THREADS:-$THREADS}"
export PLASSEMBLER_DB="${PLASSEMBLER_DB:-$(plasbench_db_path plassembler)}"
# Passed to plassembler -c: contigs at least this long are treated as
# chromosome. Must be smaller than the smallest chromosome in the cohort.
export PLASSEMBLER_CHROMOSOME_LENGTH="${PLASSEMBLER_CHROMOSOME_LENGTH:-1000000}"
# CIRCULARITY GUARD. A cohort whose truth assembly was built from the same long
# reads Plassembler is given would score the tool against its own input. Stage 7
# therefore skips such samples unless the cohort declares independence in a
# truth_independent_of_long_reads column. Setting this to 1 overrides that for
# every sample; the override is recorded in tool_status.tsv so a result can
# never silently look independent when it was not.
export PLASSEMBLER_ALLOW_CIRCULAR_TRUTH="${PLASSEMBLER_ALLOW_CIRCULAR_TRUTH:-0}"
export GPLAS2_EXTERNAL_PREDICTIONS_DIR="${GPLAS2_EXTERNAL_PREDICTIONS_DIR:-}"
export GPLAS2_MIN_CONTIG_LENGTH="${GPLAS2_MIN_CONTIG_LENGTH:-1000}"

# Hybracter (long-only and/or hybrid modes). Each mode is its own opt-in tool:
# a user may want one, the other, or both, since long-only vs hybrid recovery
# differs materially on ONT data. Off by default. Both modes reuse
# PLASSEMBLER_DB above (Hybracter's own Plassembler step needs the same PLSDB
# database) rather than a second copy of the same ~500MB database.
export RUN_HYBRACTER_LONG="${RUN_HYBRACTER_LONG:-0}"
export RUN_HYBRACTER_HYBRID="${RUN_HYBRACTER_HYBRID:-0}"
export HYBRACTER_THREADS="${HYBRACTER_THREADS:-$THREADS}"
# Passed to hybracter's --chromosome_size (minimum contig length treated as
# chromosome, before plasmid recovery runs on the rest). Must be smaller than
# the smallest chromosome in the cohort. Mirrors PLASSEMBLER_CHROMOSOME_LENGTH.
export HYBRACTER_CHROMOSOME_LENGTH="${HYBRACTER_CHROMOSOME_LENGTH:-1000000}"
# CIRCULARITY GUARD overrides, one per mode (see scripts/lib.sh:
# long_read_truth_eligible) -- same policy as PLASSEMBLER_ALLOW_CIRCULAR_TRUTH.
export HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH="${HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH:-0}"
export HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH="${HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH:-0}"
# Trycycler -> MOB-Recon: a second long-read-only assembly path alongside
# flye_mob_recon, since assembler choice materially affects plasmid
# completeness on ONT data. Off by default. TRYCYCLER_READ_TYPE is defined
# further below, alongside FLYE_READ_TYPE, since it defaults from it.
export RUN_TRYCYCLER_MOB_RECON="${RUN_TRYCYCLER_MOB_RECON:-0}"
export TRYCYCLER_THREADS="${TRYCYCLER_THREADS:-$THREADS}"
# How many independent long-read assemblies to reconcile. Trycycler's own
# guidance: >=3 minimum, 8-12 for full robustness. Kept modest by default,
# since this multiplies assembly time by roughly this many Flye runs.
export TRYCYCLER_ASSEMBLY_COUNT="${TRYCYCLER_ASSEMBLY_COUNT:-4}"
# Off by default: adds a Medaka polishing pass after Trycycler consensus.
export TRYCYCLER_MEDAKA_POLISH="${TRYCYCLER_MEDAKA_POLISH:-0}"
export TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH="${TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH:-0}"

# --- Cohort QC anomaly flagging (advisory-only, never blocks or excludes) ---
# Stats are computed fresh from each downloaded reference.fna at stage 2
# (python/compute_assembly_stats.py), then compared across the whole cohort
# at stage 6 (python/flag_cohort_outliers.py) via robust (median/MAD)
# z-scores. Unlike every optional tool above, this is cheap, stdlib-only, and
# strictly advisory, so it defaults ON rather than off; set to 0 to disable.
export COHORT_QC_FLAGS_ENABLED="${COHORT_QC_FLAGS_ENABLED:-1}"
# Below this many samples with stats, outlier detection is withheld rather
# than computed on too little data to be meaningful (same "withhold, don't
# guess" policy as recommendation_validation.tsv's leave-one-study-out gate).
export COHORT_QC_MIN_COHORT_SIZE="${COHORT_QC_MIN_COHORT_SIZE:-8}"
# Modified (Iglewicz-Hoaglin) z-score magnitude beyond which a value is
# flagged. 3.5 is the commonly-cited threshold for this statistic.
export COHORT_QC_ZSCORE_THRESHOLD="${COHORT_QC_ZSCORE_THRESHOLD:-3.5}"

# --- Decision-support recommendation model (descriptive, not a scoring change) ---
# A hand-rolled, pure-stdlib ridge regression predicting a tool's F1/
# plasmid_recall directly from an isolate's own continuous features
# (read_depth_x, true_plasmid_bp, true_plasmid_count) instead of a discrete
# stratum mean. Off by default: unlike Part 1's QC flagging, this does real
# cross-validated fitting work, and is only ever used when its own
# leave-one-study-out gate (below) actually passes -- otherwise
# select_operational_method.py/select_unknown_sample.py behave exactly as if
# this were never enabled. See docs/USER_GUIDE.md for the full caveat.
export RUN_RECOMMENDATION_MODEL="${RUN_RECOMMENDATION_MODEL:-0}"
# At least this many distinct source_study groups are required for
# leave-one-study-out to mean anything for a fitted model (higher than
# validate_recommendations.py's own 2-study minimum, since a multi-parameter
# fit benefits from more folds than a plain mean-selector does).
export RECOMMENDATION_MODEL_MIN_STUDIES="${RECOMMENDATION_MODEL_MIN_STUDIES:-3}"
export RECOMMENDATION_MODEL_MIN_SAMPLES="${RECOMMENDATION_MODEL_MIN_SAMPLES:-20}"
# The model's LOSO mean-absolute-error must beat the fixed-weight baseline's
# (the training studies' own per-tool mean, evaluated under the identical
# folds) by at least this relative fraction, for every target -- never
# "ready" on a technicality that is actually worse than just using the mean.
export RECOMMENDATION_MODEL_MIN_IMPROVEMENT="${RECOMMENDATION_MODEL_MIN_IMPROVEMENT:-0.05}"
# At this scale the model changes from approximate LOSO (where the same folds
# select lambda and estimate error) to nested, study-level LOSO.  The latter
# keeps every outer held-out study out of hyperparameter selection.
export RECOMMENDATION_MODEL_NESTED_MIN_SAMPLES="${RECOMMENDATION_MODEL_NESTED_MIN_SAMPLES:-60}"
export RECOMMENDATION_MODEL_NESTED_MIN_STUDIES="${RECOMMENDATION_MODEL_NESTED_MIN_STUDIES:-5}"
# Rules-only (no ML) decision_score weight profile -- accuracy_first (today's
# original formula), amr_surveillance, amr_context (requires curated AMR truth),
# or rapid_screening. Changing this only
# changes which tool is ranked highest; it never changes eligibility.
export DECISION_PROFILE="${DECISION_PROFILE:-accuracy_first}"

# Reuse a completed tool result by default, but only when its fingerprint still
# matches: the tool's installed executable (path, size, mtime), its adapter, its database registry row, its
# <TOOL>_* settings (thread counts excluded) and its input files are recorded in
# results/<sample>/.<tool>.complete, and any change re-runs that tool. Set
# FORCE_RERUN_TOOLS=1 to re-run every tool regardless.
export FORCE_RERUN_TOOLS="${FORCE_RERUN_TOOLS:-0}"
# Results from releases before fingerprints have an empty marker, so their inputs
# cannot be checked and they re-run once. REUSE_UNFINGERPRINTED=1 reuses them
# unchecked instead (with a warning), e.g. to avoid re-running a long finished cohort.
export REUSE_UNFINGERPRINTED="${REUSE_UNFINGERPRINTED:-0}"
# INSTALL_MISSING_TOOLS=1: stage 0 installs any enabled tool that is not installed instead of stopping (plasbench run --install-missing-tools). Unset, a run with
# no terminal stops at the first check and names every missing tool with the command that installs it; at a terminal it asks. The window asks, then sets it.
export INSTALL_MISSING_TOOLS="${INSTALL_MISSING_TOOLS:-0}"
# A plASgraph2 installed by `plasbench install-tools plasgraph2` carries its pretrained model: use it unless a model directory is set.
if [[ -z "${PLASGRAPH2_MODEL_DIR:-}" && "${RUN_PLASGRAPH2:-0}" == "1" ]] && command -v plASgraph2_classify.py >/dev/null 2>&1; then
    _pg_env="$(python3 "$PROJECT_ROOT/python/source_install.py" command-info plASgraph2_classify.py 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("env_prefix",""))' 2>/dev/null || true)"
    [[ -n "$_pg_env" && -d "$_pg_env/plasbench-src/model/ESKAPEE_model" ]] && export PLASGRAPH2_MODEL_DIR="$_pg_env/plasbench-src/model/ESKAPEE_model"
    unset _pg_env
fi

# --- Tool databases (set after INSTALL step) ---------------------------------
# Platon needs its DB downloaded once; point to it here.
export PLATON_DB="${PLATON_DB:-$(plasbench_db_path platon/db)}"
export GENOMAD_DB="${GENOMAD_DB:-$(plasbench_db_path genomad)}"
export PLASME_DB="${PLASME_DB:-$(plasbench_db_path plasme)}"

# --- Read handling -----------------------------------------------------------
export MIN_READ_LEN="${MIN_READ_LEN:-50}"   # fastp: discard shorter reads
export FASTP_EXTRA="${FASTP_EXTRA:-}"       # extra fastp args if you want them

# --- Assembly ----------------------------------------------------------------
# "spades" (default) or "unicycler". Unicycler gives cleaner graphs but is slower.
export ASSEMBLER="${ASSEMBLER:-spades}"

# --- Native long-read reconstruction (optional stage 7) ---------------------
# Stage 7 accepts ONT or PacBio reads staged as data/<sample>/long_reads.fastq.gz.
# Flye assembles the reads, then MOB-Recon classifies plasmid bins from that
# assembly. This is opt-in so short-read benchmarks remain unchanged.
export LONG_READS_FILE="${LONG_READS_FILE:-long_reads.fastq.gz}"
export FLYE_READ_TYPE="${FLYE_READ_TYPE:-nano-hq}"
# Trycycler's own Flye assemblies default to the same read type as
# flye_mob_recon's, since both feed the same instrument's reads to Flye.
export TRYCYCLER_READ_TYPE="${TRYCYCLER_READ_TYPE:-$FLYE_READ_TYPE}"

# --- Self-built hybrid truth (truth_source=self_assembled_hybrid rows) ------
# For cohort sources that deposit long+short reads but never submitted a
# formal Complete Genome assembly (see docs/FINDING_DATA.md): stage 2 builds
# the truth reference itself via python/build_hybrid_truth.py (Unicycler
# hybrid assembly), instead of downloading an existing one. Chromosome/
# plasmid labeling comes only from Unicycler's own circular=/length topology
# -- never a gene-content classifier -- and a non-circularizing assembly is
# rejected outright, never accepted as a partial/uncertain truth. Unrelated
# to LONG_READS_FILE above (which stage 7's BENCHMARKED long-read/hybrid
# tools consume); this is truth CONSTRUCTION, gated separately.
export HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH="${HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH:-1500000}"
export HYBRID_TRUTH_THREADS="${HYBRID_TRUTH_THREADS:-$THREADS}"

# --- Simulated reads (truth_source=simulated rows) ---------------------------
# The mirror image of self-built hybrid truth above: assembly_accession is a
# REAL, independently-deposited Complete Genome assembly (so it IS the truth,
# downloaded and used exactly like an ncbi_deposited row -- see
# validate_cohort.py's verify_simulated_row()), but short+long reads are
# generated locally by python/simulate_reads.py (InSilicoSeq + Badread)
# instead of downloaded from SRA. Per-row seed/depth/error-model values live
# in the cohort sheet itself (simulation_seed, simulation_short_depth_x,
# simulation_long_depth_x -- required; simulation_short_error_model,
# simulation_long_error_model -- optional, these are just the defaults below).
export SIMULATE_SHORT_MODEL="${SIMULATE_SHORT_MODEL:-novaseq}"
export SIMULATE_LONG_MODEL="${SIMULATE_LONG_MODEL:-nanopore2020}"
export SIMULATE_THREADS="${SIMULATE_THREADS:-$THREADS}"

# --- Mapping (scoring) -------------------------------------------------------
# minimap2 preset for aligning predicted-plasmid contigs back to the reference.
export MINIMAP2_PRESET="${MINIMAP2_PRESET:-asm5}" # asm5 = <5% divergence
export MIN_ALIGNMENT_LENGTH="${MIN_ALIGNMENT_LENGTH:-200}"
export MIN_ALIGNMENT_IDENTITY="${MIN_ALIGNMENT_IDENTITY:-0.90}"
export MIN_ALIGNMENT_MAPQ="${MIN_ALIGNMENT_MAPQ:-20}"
export MIN_ALIGNMENT_QUERY_COVERAGE="${MIN_ALIGNMENT_QUERY_COVERAGE:-0.20}"
# Reference-database overlap (python/flag_database_overlap.py, stage 6): flag
# sample x tool pairs whose truth assembly was public before the tool's own
# database (dates in config/tool_database_releases.tsv -- fill them in). 0 =
# report only (mean_f1_after_database); 1 = drop flagged rows before ranking.
export EXCLUDE_DATABASE_OVERLAP="${EXCLUDE_DATABASE_OVERLAP:-0}"

# Recall-ceiling diagnostic (python/scorable_truth.py): tile each truth plasmid
# into windows and map them back with the scoring preset and filters, to find
# plasmid bases no prediction could ever be scored on (repeats shared with the
# chromosome, duplicate plasmids). Adds recall_ceiling/ceiling_adjusted_recall;
# never changes F1. Cheap (plasmids only), so on by default.
export RUN_SCORABLE_TRUTH="${RUN_SCORABLE_TRUTH:-1}"
export SCORABLE_WINDOW_BP="${SCORABLE_WINDOW_BP:-1000}"
export SCORABLE_STEP_BP="${SCORABLE_STEP_BP:-250}"
# A second, all-mappings PAF exposes repeated query sequence that aligns to
# both plasmid and chromosome. It is a diagnostic and never alters F1.
export REPORT_MAPPING_AMBIGUITY="${REPORT_MAPPING_AMBIGUITY:-1}"
# Largest primary alignment blocks retained per tool in the offline explorer.
# This prevents a fragmented assembly from making the report unresponsive.
# Call installed annotation tools (mob_typer/abricate/amrfinder/isescan) to
# derive replicon, MOB, AMR, and IS features instead of hand-curated tables.
# Absent callers are recorded as "not evaluated", never as absent features.
export RUN_REFERENCE_ANNOTATION="${RUN_REFERENCE_ANNOTATION:-1}"
# One switch per annotation caller (each default 1 = on; 0 = off). A caller switched off is not run and is recorded as "not evaluated (switched off)", never as "no such feature".
# They only matter while RUN_REFERENCE_ANNOTATION=1. Install a caller from the window (Tools, or the Workflow card) or with: plasbench install-tools reference-annotation
export ANNOTATE_WITH_MOB_TYPER="${ANNOTATE_WITH_MOB_TYPER:-1}"   # replicon and relaxase typing (MOB-typer)
export ANNOTATE_WITH_ABRICATE="${ANNOTATE_WITH_ABRICATE:-1}"     # AMR genes and replicons by BLAST (abricate)
export ANNOTATE_WITH_AMRFINDER="${ANNOTATE_WITH_AMRFINDER:-1}"   # AMR genes (AMRFinderPlus; needs its database)
export ANNOTATE_WITH_ISESCAN="${ANNOTATE_WITH_ISESCAN:-1}"       # insertion sequences (ISEScan; the slowest caller)
# ISESCAN_SCOPE: plasmids (default) = ISEScan searches only the replicons the truth table labels PLASMID; the chromosome is NOT searched and is recorded as "not evaluated
# (chromosome not searched)", never as "no insertion sequences". all = every sequence of the reference (the earlier behaviour; the annotation cache never mixes the two).
# Every table and figure that uses insertion sequences is about the truth plasmids, so the plasmid results are the same; on a 5-7 Mbp isolate the chromosome is 90% of the search.
export ISESCAN_SCOPE="${ISESCAN_SCOPE:-plasmids}"
export ANNOTATE_WITH_BARRNAP="${ANNOTATE_WITH_BARRNAP:-1}"       # rRNA genes (barrnap)
export ANNOTATION_AMR_DB="${ANNOTATION_AMR_DB:-ncbi}"
# Finished reference annotations are kept here, keyed by the reference's SHA-256 and the annotation tools' versions and databases, so a second study of the same
# isolate reuses them (the truth annotation does not depend on the study). The stored result is byte-identical to a fresh one; the provenance file says it was reused.
# Empty turns the cache off. Default: .annotation_cache inside the data folder.
export ANNOTATION_CACHE_DIR="${ANNOTATION_CACHE_DIR-$DATA_DIR/.annotation_cache}"
export ANNOTATION_REPLICON_DB="${ANNOTATION_REPLICON_DB:-plasmidfinder}"
# Opt-in (default off): stage 2 also writes data/<sample>/truth_amr.draft.tsv from the
# AMRFinderPlus rows (python/derive_amr_truth.py). A draft is never scored: review it and
# rename it to truth_amr.tsv yourself. See docs/METHODS.md, "Drafting AMR truth".
export DERIVE_AMR_TRUTH_DRAFT="${DERIVE_AMR_TRUTH_DRAFT:-0}"

# Further benchmark dimensions, computed per sample and tool in stage 5 and summarised in stage 6
# (python/alignment_accuracy.py, feature_preservation.py, bin_quality.py). Advisory: they never
# alter scores.tsv or the ranking. Set to 0 to skip them.
export RUN_DIMENSION_ANALYSES="${RUN_DIMENSION_ANALYSES:-1}"

# Truth-derived DIFFICULTY descriptors (python/compute_difficulty_features.py):
# how intrinsically hard this isolate is to separate into plasmid vs.
# chromosome, independent of any tool's own performance -- dead-end count in
# the assembly graph, plasmid-vs-chromosome read-depth ratio, and
# plasmid-vs-chromosome Mash distance. Benchmark-only stratifiers, same as
# plasmid_count and Inc-type: a genuinely unknown operational isolate has no
# truth reference to compute these from, so they are never wired into
# recommendation_model.py. Off by default (real per-isolate compute cost:
# an alignment plus two external-tool calls), same convention as
# RUN_REFERENCE_ANNOTATION. Each of the three fields is independently
# skipped (left empty, not guessed) when its own prerequisite is missing.
export RUN_DIFFICULTY_FEATURES="${RUN_DIFFICULTY_FEATURES:-0}"
export DIFFICULTY_FEATURES_THREADS="${DIFFICULTY_FEATURES_THREADS:-$THREADS}"

# Optional QUAST supplementary diagnostics (python/run_quast_diagnostics.py,
# stage 5): three QUAST runs per sample/tool -- combined all-plasmids
# reference, one per individual truth plasmid, and chromosome-only
# reference (C-Connor/PlasmidToolBenchMarking's own verified pattern, see
# docs/METHODS.md) -- surfacing genome fraction/misassembly count/
# duplication ratio to explain WHY a low F1 happened, never a replacement
# for score_plasmids.py's own base-level precision/recall/F1 ranking. Off
# by default (real per-tool-per-sample compute cost: up to
# 2+n_truth_plasmids QUAST invocations). --min-contig 0 is always passed
# (QUAST's own 500bp default would silently drop short plasmid contigs).
export RUN_QUAST_DIAGNOSTICS="${RUN_QUAST_DIAGNOSTICS:-0}"
export QUAST_DIAGNOSTICS_THREADS="${QUAST_DIAGNOSTICS_THREADS:-$THREADS}"
export QUAST_DIAGNOSTICS_MIN_CONTIG="${QUAST_DIAGNOSTICS_MIN_CONTIG:-0}"

# Optional MultiQC companion (python/run_multiqc.py, stage 6, before the report is built). PlasBench's own QC panel in the report is NOT made with
# MultiQC (QC is fastp plus python/short_read_qc.py); MultiQC is the community-standard view of the same fastp (and QUAST) output files, with more plots
# (per-base quality, adapter content, duplication). auto (default) = run `multiqc` only when it is installed (plasbench install-tools multiqc); on = always
# try, and warn when it is missing; off = never. It writes results/multiqc/multiqc_report.html (a separate file the report links to, never embeds) and can
# never fail a run: a problem is a warning in run_events.jsonl and a note in the report's QC panel.
export MULTIQC_REPORT="${MULTIQC_REPORT:-auto}"
export MULTIQC_TIMEOUT_SECONDS="${MULTIQC_TIMEOUT_SECONDS:-600}"

# Optional operational-mode (no-truth) nearest-reference screen -- EXPERIMENTAL
# AND UNVALIDATED (python/classify_operational_plasmid.py,
# scripts/08_operational_reconstruct.sh): Mash distance from this isolate's own
# reconstructed candidate plasmid to a small, PlasBench-curated reference set,
# built once by python/build_plasmid_reference_set.py, following the pattern of
# COPLA's membership call -- see that script's own docstring for how it differs
# from COPLA's live graph-tool/SBM machinery, and for why a Mash distance of
# 0.05 is NOT "95% similar" for plasmids. It reports how close a record is to
# 16 references; it is not a taxonomy, not relatedness, and "no_close_reference"
# is not evidence of novelty. This is an OPERATIONAL-only signal:
# it is never computed for a benchmark isolate that has truth, and its
# output must never be wired into recommendation_model.py's training
# features. Off by default (a new, unvalidated signal with only a 16-plasmid
# starting reference set). PLASMID_REFERENCE_SKETCH/_METADATA point at the
# build script's own output; absent files or a missing `mash` leave the
# classification empty ("insufficient_reference"), never guessed. The
# curated INPUT accession list is committed (cohorts/reference_plasmids/
# curated_accessions.tsv, small, real provenance); the actual downloaded
# sequences/sketch built FROM it are real data, not metadata, so -- same
# convention as PLATON_DB/GENOMAD_DB/PLASME_DB above -- they live under
# DATA_DIR/db, gitignored, built once by build_plasmid_reference_set.py.
export RUN_PLASMID_NOVELTY_CLASSIFICATION="${RUN_PLASMID_NOVELTY_CLASSIFICATION:-0}"
export PLASMID_REFERENCE_SKETCH="${PLASMID_REFERENCE_SKETCH:-$(plasbench_db_path plasmid_reference/reference.msh)}"
export PLASMID_REFERENCE_METADATA="${PLASMID_REFERENCE_METADATA:-$(plasbench_db_path plasmid_reference/reference_metadata.tsv)}"
export PLASMID_NOVELTY_SIMILARITY_THRESHOLD="${PLASMID_NOVELTY_SIMILARITY_THRESHOLD:-0.05}"
export PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS="${PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS:-2}"
export PLASMID_REFERENCE_FASTA="${PLASMID_REFERENCE_FASTA:-$(plasbench_db_path plasmid_reference/reference.fasta)}"

# Trivial baselines (python/baseline_predictors.py, stage 4): reference points
# every tool should beat, scored and ranked like tools on the classification
# track. Cheap, so on by default. baseline_coverage calls contigs with depth
# >= BASELINE_COVERAGE_RATIO x the length-weighted median depth;
# baseline_reference calls contigs whose aligned fraction against
# PLASMID_REFERENCE_FASTA reaches BASELINE_REFERENCE_MIN_QUERY_COVERAGE.
# Contig-level classification (python/contig_classification.py, stage 5):
# assembly contigs >= CONTIG_MIN_LENGTH are labelled PLASMID/CHROMOSOME when
# >= CONTIG_MIN_COVERAGE of the contig aligns at >= CONTIG_MIN_IDENTITY to that
# kind of truth; contigs aligning that well to both are AMBIGUOUS (excluded,
# counted). Adds count-based and length-weighted P/R/F1/MCC per tool.
export RUN_CONTIG_CLASSIFICATION="${RUN_CONTIG_CLASSIFICATION:-1}"
# Independent second scorer for the contig layer (python/contig_crosscheck.py):
# alignment-free k-mer containment labels (k=21, FracMinHash 1/CONTIG_CROSSCHECK_SCALED)
# compared with the minimap2 labels; benchmark.contig_crosscheck.tsv.
export RUN_CONTIG_CROSSCHECK="${RUN_CONTIG_CROSSCHECK:-1}"
export CONTIG_CROSSCHECK_SCALED="${CONTIG_CROSSCHECK_SCALED:-10}"
# Sequence-level leakage check (python/database_containment.py, stage 6): a
# truth plasmid is "in" a tool's database when one database record covers
# >= DATABASE_CONTAINMENT_MIN_COVERAGE of it at >= ..._MIN_IDENTITY. MOB-suite's
# database is found automatically; add others as "tools=/path.fasta;..." here.
export RUN_DATABASE_CONTAINMENT="${RUN_DATABASE_CONTAINMENT:-1}"
export DATABASE_CONTAINMENT_MIN_COVERAGE="${DATABASE_CONTAINMENT_MIN_COVERAGE:-0.95}"
export DATABASE_CONTAINMENT_MIN_IDENTITY="${DATABASE_CONTAINMENT_MIN_IDENTITY:-0.99}"
export TOOL_DATABASE_FASTAS="${TOOL_DATABASE_FASTAS:-}"
export CONTIG_MIN_LENGTH="${CONTIG_MIN_LENGTH:-1000}"
export CONTIG_MIN_IDENTITY="${CONTIG_MIN_IDENTITY:-0.95}"
export CONTIG_MIN_COVERAGE="${CONTIG_MIN_COVERAGE:-0.80}"
export RUN_BASELINE_COVERAGE="${RUN_BASELINE_COVERAGE:-1}"
export RUN_BASELINE_REFERENCE="${RUN_BASELINE_REFERENCE:-1}"
# baseline_replicon (off by default; needs Abricate): a contig is plasmid when it carries a replicon marker (plsMD's enumeration idea, with its Col-vs-Inc
# rule). REPLICON_ABRICATE_DBS is the space-separated list of Abricate databases searched.
export RUN_BASELINE_REPLICON="${RUN_BASELINE_REPLICON:-0}"
export REPLICON_ABRICATE_DBS="${REPLICON_ABRICATE_DBS:-plasmidfinder}"
export BASELINE_COVERAGE_RATIO="${BASELINE_COVERAGE_RATIO:-1.5}"
export BASELINE_MIN_CONTIG_LENGTH="${BASELINE_MIN_CONTIG_LENGTH:-1000}"
export BASELINE_REFERENCE_MIN_QUERY_COVERAGE="${BASELINE_REFERENCE_MIN_QUERY_COVERAGE:-0.8}"

# Optional standardized CDS/product annotation for truth and every predicted
# plasmid FASTA. FASTA alone has no protein names. Bakta is preferred; Prokka
# is a compatible fallback. Annotation failure never changes DNA-level scores.
export RUN_PROTEIN_ANNOTATION="${RUN_PROTEIN_ANNOTATION:-0}"
export PROTEIN_ANNOTATION_ENGINE="${PROTEIN_ANNOTATION_ENGINE:-bakta}"
export PROTEIN_ANNOTATION_THREADS="${PROTEIN_ANNOTATION_THREADS:-$THREADS}"
export PROTEIN_ANNOTATION_MIN_BP="${PROTEIN_ANNOTATION_MIN_BP:-90}"
# Optional pinned Bakta database directory. Its identity is recorded in the
# annotation provenance and cache key; leave empty only when Bakta has a
# configured default database.
export PROTEIN_ANNOTATION_DATABASE="${PROTEIN_ANNOTATION_DATABASE:-}"

export VISUALIZATION_MAX_BLOCKS_PER_TOOL="${VISUALIZATION_MAX_BLOCKS_PER_TOOL:-2000}"
# Largest aligned block rendered as base-level text in the local viewer.
export VISUALIZATION_MAX_NUCLEOTIDE_ALIGNMENT_BP="${VISUALIZATION_MAX_NUCLEOTIDE_ALIGNMENT_BP:-2000}"

# Keep the small per-sample inputs the report needs INSIDE the results folder (python/keep_report_inputs.py, end of stage 5): the truth
# tables that otherwise live only in the data folder (truth, features, AMR, circularity, proteins, repeats) and a record/length/hash summary
# of every tool's prediction. Reads, assemblies and reference FASTAs are never copied. With the default, a results folder copied to another
# machine can rebuild its report and its figures (plasbench check-results RESULTS_DIR says which sections will draw). KEEP_REPORT_INPUTS=0
# turns it off; KEEP_REPORT_INPUTS_MAX_KB is the budget per sample (files that would exceed it are listed as skipped in <sample>/report_inputs.json).
export KEEP_REPORT_INPUTS="${KEEP_REPORT_INPUTS:-1}"
export KEEP_REPORT_INPUTS_MAX_KB="${KEEP_REPORT_INPUTS_MAX_KB:-2048}"

# --- Safety: stop early if the sample sheet is missing -----------------------
if [[ ! -f "$SAMPLE_SHEET" ]]; then
    echo "WARNING: sample sheet not found at $SAMPLE_SHEET" >&2
fi

# ---- Added with the plsMD / PlasEval / GAEMR work (kept at the end so existing line citations in docs stay valid) ----
# plsMD (python adapter adapters/adapt_plsmd.sh): reference-guided plasmid reconstruction from a Unicycler assembly
# against a PLSDB BLAST index. Off by default. It is Docker-packaged upstream: PLSMD_CMD can be the wrapper script
# `plsMD`. PLSMD_DB is the BLAST index PREFIX (a file PLSMD_DB.nhr must exist). Needs ASSEMBLER=unicycler. The
# PLSDB release it uses must be entered in config/tool_database_releases.tsv or leakage is reported as not assessed.
export RUN_PLSMD="${RUN_PLSMD:-0}"
export PLSMD_CMD="${PLSMD_CMD:-plsMD}"
export PLSMD_DB="${PLSMD_DB:-}"
export PLSMD_THREADS="${PLSMD_THREADS:-$THREADS}"
# Evaluation additions learned from PlasEval, plsMD and GAEMR (docs/SCIENTIFIC_GUIDE.md section 7.9). All descriptive.
#   RUN_BIN_AGREEMENT      best-match (non-one-to-one) P/R/F1 and split/join dissimilarity on the contig labels;
#                          DISSIMILARITY_ALPHA is the length exponent (0 ignores contig length, 1 is fully weighted).
#   RUN_COPY_NUMBER        tool vs truth plasmid copy number per matched bin (needs depth headers and truth depth).
#   RUN_ASSEMBLY_ADEQUACY  share of each truth plasmid the short-read assembly contains, flagged below MIN_ASSEMBLY_ADEQUACY.
#   RUN_REPEAT_CONTENT     k-mer repeat content of the truth (REPEAT_KMER, GAEMR used 29).
#   RUN_TRUTH_DEPTH_ANOMALIES (off) windows of unusual read depth on the truth (DEPTH_WINDOW_BP, DEPTH_ANOMALY_Z).
export RUN_BIN_AGREEMENT="${RUN_BIN_AGREEMENT:-1}"
export DISSIMILARITY_ALPHA="${DISSIMILARITY_ALPHA:-0.5}"
#   DISSIMILARITY_REPEATS  aware (default) pairs a contig that sits in several bins as PlasEval does (branch and bound);
#                          drop scores the first copy only. DISSIMILARITY_MAX_CALLS caps the search; a capped search
#                          keeps the best pairing found and is marked capped in dissim_repeat_search.
export DISSIMILARITY_REPEATS="${DISSIMILARITY_REPEATS:-aware}"
export DISSIMILARITY_MAX_CALLS="${DISSIMILARITY_MAX_CALLS:-200000}"
#   RUN_PLASEVAL_GATE      the comparison gate (python/plaseval_gate.py): runs the ORIGINAL PlasEval program on this run's exported
#                          bins and compares it with PlasBench's reimplementation. auto (default) compares when the original is
#                          found and otherwise records NOT_RUN; on also stops the run when it is missing or disagrees (use it for
#                          the plaseval-ecoli53 replication cohort and on a machine that has the original); off skips it.
#                          PLASEVAL_SRC is the src/ folder of a PlasEval checkout (found automatically in $DATA_DIR/tools/PlasEval,
#                          ~/.local/share/plasbench/tools/PlasEval or ~/PlasEval; PlasEval has no licence, so it is never bundled).
#                          PLASEVAL_PYTHON runs it (needs networkx, pandas, bidict, psutil); PLASEVAL_TIMEOUT is seconds per pair.
#   SHORT_READ_QC_MODE     the short-read QC gate (python/short_read_qc.py), before assembly. report (default): measure, decide PASS, WARN or
#                          REJECT and flag, but exclude only an integrity failure (unreadable, truncated, empty, malformed or unequal
#                          files); enforce: also exclude a threshold REJECT (status `rejected`, never scored as a tool failure); off: skip.
#                          SHORT_READ_QC_THRESHOLDS is the pre-registered threshold file (PROVISIONAL until frozen on pilot data; its hash
#                          is written to every QC row). SHORT_READ_QC_MAX_PAIRS is the sampled read pairs; SHORT_READ_QC_GENOME_MB the
#                          genome size for the depth estimate (5 Mb is assumed, and flagged, when empty).
export SHORT_READ_QC_MODE="${SHORT_READ_QC_MODE:-report}"
export SHORT_READ_QC_THRESHOLDS="${SHORT_READ_QC_THRESHOLDS:-$PROJECT_ROOT/config/short_read_qc_thresholds.tsv}"
export SHORT_READ_QC_MAX_PAIRS="${SHORT_READ_QC_MAX_PAIRS:-200000}"
export SHORT_READ_QC_GENOME_MB="${SHORT_READ_QC_GENOME_MB:-}"
#   ASSEMBLY_SELECTION_MODE  which short-read assembly the tools run on (python/assembly_selection.py). Every candidate is measured (contigs,
#                          N50, total length, GC, optional read support) and kept in results/assembly_candidates.tsv. report (default):
#                          record the policy's choice and act on nothing; enforce: the chosen assembly is the one the tools run on, and
#                          a sample with no eligible assembly is excluded (status `rejected`, nothing substituted silently); off: skip.
#                          ASSEMBLY_SELECTION_POLICY: fixed (the configured ASSEMBLER) or quality (highest N50 among the eligible, then
#                          fewest contigs). The policy never sees the truth or a score. ASSEMBLY_ALSO lists extra assemblers
#                          (spades, unicycler) to run as alternatives beside the primary. Do not select when COMPARING assemblers: keep
#                          each as its own input condition. Eligibility: total length in [ASSEMBLY_MIN_TOTAL_MB, ASSEMBLY_MAX_TOTAL_MB]
#                          and read support >= ASSEMBLY_MIN_MAPPED_FRACTION (ASSEMBLY_READ_SUPPORT=1 maps a sample of the trimmed reads).
export ASSEMBLY_SELECTION_MODE="${ASSEMBLY_SELECTION_MODE:-report}"
export ASSEMBLY_SELECTION_POLICY="${ASSEMBLY_SELECTION_POLICY:-fixed}"
export ASSEMBLY_ALSO="${ASSEMBLY_ALSO:-}"
export ASSEMBLY_MIN_TOTAL_MB="${ASSEMBLY_MIN_TOTAL_MB:-1.0}"
export ASSEMBLY_MAX_TOTAL_MB="${ASSEMBLY_MAX_TOTAL_MB:-10.0}"
export ASSEMBLY_MIN_MAPPED_FRACTION="${ASSEMBLY_MIN_MAPPED_FRACTION:-0.80}"
export ASSEMBLY_READ_SUPPORT="${ASSEMBLY_READ_SUPPORT:-1}"
#   RUN_CANDIDATE_MULTIPLICITY  account for EVERY predicted record: per truth plasmid the number of candidates, the best candidate's
#                          coverage, the combined (union) coverage, redundancy, and per candidate its relationship (primary,
#                          complementary_fragment, redundant, chimeric, off_target, unmapped). Descriptive; never changes a score.
#                          MULTIPLICITY_NEW_FRACTION: a candidate with less than this share of new bases is redundant (0.10).
#                          MULTIPLICITY_CHIMERA_MIN_BP / _FRACTION: two replicons each carrying at least this much make it chimeric.
export RUN_CANDIDATE_MULTIPLICITY="${RUN_CANDIDATE_MULTIPLICITY:-1}"
export MULTIPLICITY_NEW_FRACTION="${MULTIPLICITY_NEW_FRACTION:-0.10}"
export MULTIPLICITY_CHIMERA_MIN_BP="${MULTIPLICITY_CHIMERA_MIN_BP:-1000}"
export MULTIPLICITY_CHIMERA_FRACTION="${MULTIPLICITY_CHIMERA_FRACTION:-0.10}"
export RUN_REFERENCE_EVIDENCE_AUDIT="${RUN_REFERENCE_EVIDENCE_AUDIT:-1}"   # per-isolate reference evidence audit (python/reference_evidence_audit.py)
#   ASSEMBLER_SENSITIVITY_RUNS   "name=path/to/scores.tsv ..." of other runs of this cohort that differ only in the assembly; stage 6 then writes
#                                benchmark.assembler_sensitivity.tsv/.html (python/assembler_sensitivity.py). Unset: skipped.
export ASSEMBLER_SENSITIVITY_RUNS="${ASSEMBLER_SENSITIVITY_RUNS:-}"
export RUN_RANKING_STABILITY="${RUN_RANKING_STABILITY:-1}"   # leave-one-study/species-out ranking stability (python/ranking_stability.py)
export RUN_PLASEVAL_GATE="${RUN_PLASEVAL_GATE:-auto}"
export PLASEVAL_SRC="${PLASEVAL_SRC:-}"
export PLASEVAL_PYTHON="${PLASEVAL_PYTHON:-python3}"
export PLASEVAL_TIMEOUT="${PLASEVAL_TIMEOUT:-300}"
export PLASEVAL_GATE_TOLERANCE="${PLASEVAL_GATE_TOLERANCE:-0.001}"
export PLASEVAL_GATE_WORKERS="${PLASEVAL_GATE_WORKERS:-2}"
export RUN_COPY_NUMBER="${RUN_COPY_NUMBER:-1}"
export RUN_ASSEMBLY_ADEQUACY="${RUN_ASSEMBLY_ADEQUACY:-1}"
export MIN_ASSEMBLY_ADEQUACY="${MIN_ASSEMBLY_ADEQUACY:-0.90}"
export RUN_REPEAT_CONTENT="${RUN_REPEAT_CONTENT:-1}"
export REPEAT_KMER="${REPEAT_KMER:-29}"
export RUN_TRUTH_DEPTH_ANOMALIES="${RUN_TRUTH_DEPTH_ANOMALIES:-0}"
export DEPTH_WINDOW_BP="${DEPTH_WINDOW_BP:-1000}"
export DEPTH_ANOMALY_Z="${DEPTH_ANOMALY_Z:-3}"
# PlasBin-flow (adapters/adapt_plasbin_flow.sh): adapts the tool's own output; PlasBench does not run it (it needs a Gurobi
# licence, a gzipped GFA with dp/KC tags, a contig plasmid-score file and a GC-probability file). Off by default.
# PLASBIN_FLOW_OUTPUTS_DIR/<sample>.tsv is the file written by `plasbin_flow.py -outfile`, made from the same assembly.
export RUN_PLASBIN_FLOW="${RUN_PLASBIN_FLOW:-0}"
export PLASBIN_FLOW_OUTPUTS_DIR="${PLASBIN_FLOW_OUTPUTS_DIR:-}"
# User-added tools (docs/ADDING_TOOLS.md): each is a folder with a plasbench-tool.ini manifest, found on
# $PLASBENCH_TOOLS_PATH, ~/.plasbench/tools or tools.d/. USER_TOOLS selects which run: a comma-separated list of
# names, or "all". `plasbench run --tool NAME` sets it. USER_TOOL_THREADS is the default {threads} for each.
export USER_TOOLS="${USER_TOOLS:-}"
export USER_TOOL_THREADS="${USER_TOOL_THREADS:-${THREADS:-4}}"
# Optional extra label evidence for the truth (all off unless set; a missing one is "not evaluated", never absent):
#   ANNOTATION_REPLICON_DB may list several Abricate databases, comma or space separated (default plasmidfinder).
#   ISFINDER_FASTA is a curated ISFinder IS sequence FASTA you downloaded from ISFinder under its terms (not shipped);
#   it adds BLAST-based IS annotation beside ISEScan and feeds the repeat_rich scenario tag.
export ISFINDER_FASTA="${ISFINDER_FASTA:-}"
export SCORECARD_MIN_SAMPLES="${SCORECARD_MIN_SAMPLES:-5}"
# 1 embeds the interactive cohort dashboard in the HTML report (about 1 MB; it repeats the heatmap and metric tables). Default 0.
export REPORT_EMBED_DASHBOARD="${REPORT_EMBED_DASHBOARD:-0}"
# ---- Release 0.4: primary analysis, statistics validation, truth audits and AMR context (new settings are kept at the end of the file so the line citations of the review ledger stay valid) ----
# 1 keeps the all-sample numbers as the headline when no sample has a reference in the headline tiers (status fallback_allowed, warning kept). Default 0: the primary analysis is then unavailable and the ranking is provisional.
export ALLOW_PRIMARY_FALLBACK="${ALLOW_PRIMARY_FALLBACK:-0}"
# 1 runs the statistics simulation (python/simulate_validation.py) in stage 6 and shows it in the report (Sensitivity, power and reproducibility). STATS_VALIDATION_MODE is smoke (seconds, indicative) or full (minutes, the evidence).
export RUN_STATS_VALIDATION="${RUN_STATS_VALIDATION:-0}"
# smoke (seconds, indicative: its verdicts are labelled so) or full (minutes, the evidence). Anything else is refused by simulate_validation.py.
export STATS_VALIDATION_MODE="${STATS_VALIDATION_MODE:-smoke}"
# Truth audit size flags (python/audit_truth_labels.py): a non-largest chromosome at least CHROMID_MIN_BP is flagged secondary_chromosome; a PLASMID at least LARGE_PLASMID_BP is flagged large_plasmid.
export CHROMID_MIN_BP="${CHROMID_MIN_BP:-350000}"
# A PLASMID of at least this many bases is flagged large_plasmid by the truth audit (advisory; it never excludes a sample).
export LARGE_PLASMID_BP="${LARGE_PLASMID_BP:-500000}"
# Bases either side of an AMR gene copy whose coverage by the same predicted record is its flank context (python/score_amr_placement.py). Descriptive, never ranks a tool; pre-registration row amr_flank_bp.
export AMR_FLANK_BP="${AMR_FLANK_BP:-1000}"
# Highest reference tier the primary analysis accepts (1 = long-read-first and independently validated, 2 = long-read-first, 3 = anything else). Pre-registration row headline_max_reference_tier.
export HEADLINE_MAX_REFERENCE_TIER="${HEADLINE_MAX_REFERENCE_TIER:-2}"
# Whether a tier 1-2 reference must also be independent of the benchmark reads to enter the primary analysis. independent (default): a reference polished with the
# benchmark's own Illumina reads is a dependent reference and goes to the reference-independence sensitivity table, not the primary analysis. any: the tier alone decides.
# Pre-registration row headline_reference_independence.
export HEADLINE_REFERENCE_INDEPENDENCE="${HEADLINE_REFERENCE_INDEPENDENCE:-independent}"
# Interval method of the leaderboard and the paired comparisons (python/resampling.py): cluster_t (default; chosen by simulate_validation.py), bootstrap_t or percentile.
# Pre-registration row interval_method.
export PLASBENCH_CI_METHOD="${PLASBENCH_CI_METHOD:-cluster_t}"
# Interval method for a species-balanced (stratified) mean, the headline's usual form: bootstrap_t (default; the studentised cluster bootstrap is at least as good as
# cluster_t in every simulated stratified design and 6 points better with a dominant species), cluster_t or percentile. Pre-registration row interval_method_stratified.
export PLASBENCH_CI_METHOD_STRATIFIED="${PLASBENCH_CI_METHOD_STRATIFIED:-bootstrap_t}"
# Independent clusters (BioProjects or clonal groups) the references in those tiers must come from for the primary analysis to be available. Below it the ranking is shown as provisional:
# a headline from fewer clusters has no interval and no test. Default 5 is the interval minimum (MIN_CLUSTERS_CI). Pre-registration row headline_min_clusters.
export HEADLINE_MIN_CLUSTERS="${HEADLINE_MIN_CLUSTERS:-5}"
# 1 (default) runs the ranking-robustness sweeps (python/rank_sensitivity.py) in stage 6; 0 skips them.
export RUN_RANK_SENSITIVITY="${RUN_RANK_SENSITIVITY:-1}"
# Evaluation independence the primary analysis accepts (comma-separated from independent, partially_independent, dependent, unknown), in ADDITION to reference tier <= HEADLINE_MAX_REFERENCE_TIER.
# Default "independent": long-read-first truth polished with no reads or reads independent of the benchmark. Sensitivity analyses add partially independent, then every reference. Pre-registration row headline_independence.
export HEADLINE_INDEPENDENCE="${HEADLINE_INDEPENDENCE:-independent}"
# Processes the statistics simulation (python/simulate_validation.py) uses in stage 6 (1 = one process). It never changes a number; the full mode takes minutes with 8 or more.
export STATS_VALIDATION_WORKERS="${STATS_VALIDATION_WORKERS:-1}"
# A study that holds more than this share of the isolates makes the default interval fall back to the percentile cluster bootstrap (the full simulation found cluster-t covers only 64-79% then).
# PLASBENCH_DOMINANT_FALLBACK=0 turns the fallback off. Pre-registration row dominant_study_share.
export PLASBENCH_DOMINANT_SHARE="${PLASBENCH_DOMINANT_SHARE:-0.30}"
export PLASBENCH_DOMINANT_FALLBACK="${PLASBENCH_DOMINANT_FALLBACK:-1}"

# Leakage screen (python/flag_database_overlap.py, stage 6): when does a truth genome count as "possibly in a tool's database"?
# LEAKAGE_CUTOFF_POLICY: per_tool (default, recommended) compares each genome with each tool's own database date in
# config/tool_database_releases.tsv; fixed_date compares every database-using tool with LEAKAGE_CUTOFF_DATE instead
# (e.g. 2025-01-01, to ask "was this genome public before 2025?"). fixed_date needs LEAKAGE_CUTOFF_DATE as YYYY-MM-DD.
export LEAKAGE_CUTOFF_POLICY="${LEAKAGE_CUTOFF_POLICY:-per_tool}"
# LEAKAGE_CUTOFF_DATE: YYYY-MM-DD, used only when LEAKAGE_CUTOFF_POLICY=fixed_date (suggested 2025-01-01).
export LEAKAGE_CUTOFF_DATE="${LEAKAGE_CUTOFF_DATE:-}"
# LEAKAGE_DATE_BASIS: which date counts as "public": earliest_public (default; the earlier of the assembly release and the
# first paired read run's year, read as 1 January), assembly, or read. Sheets without first_read_year behave as assembly.
# The screen only flags; EXCLUDE_DATABASE_OVERLAP=1 (above) is what drops the flagged rows before ranking.
export LEAKAGE_DATE_BASIS="${LEAKAGE_DATE_BASIS:-earliest_public}"
# RUN_PUBLISHED_COMPARISON: auto (default) or off. When the cohort holds isolates of a published benchmark (the pub-* cohorts and
# publication-v1; tables in cohorts/published/), stage 6 writes benchmark.published_comparison.* putting PlasBench's results beside the
# paper's own, matched by BioSample. Descriptive: it never changes a score or a ranking, and a failure only warns.
export RUN_PUBLISHED_COMPARISON="${RUN_PUBLISHED_COMPARISON:-auto}"
# PlasmidEC (Paganini et al.; MIT; github.com/lisavader/plasmidEC, maintained at gitlab.com/mmb-umcu/plasmidec): an ensemble that calls a contig
# plasmid by majority vote of RFPlasmid, PlaScope and Platon (add mlplasmids with PLASMIDEC_CLASSIFIERS). Off by default. It supports eight
# species only (E. coli, K. pneumoniae, A. baumannii, S. enterica, P. aeruginosa, E. faecium, E. faecalis, S. aureus): any other organism is
# skipped with a recorded reason, not failed. PLASMIDEC_CMD is how plasmidEC.sh is started (it installs its own conda environments and
# databases on first use). Hard call only (no continuous score), so it is not PR-curve scored.
export RUN_PLASMIDEC="${RUN_PLASMIDEC:-0}"
export PLASMIDEC_CMD="${PLASMIDEC_CMD:-plasmidEC.sh}"
export PLASMIDEC_THREADS="${PLASMIDEC_THREADS:-$THREADS}"
export PLASMIDEC_MIN_LENGTH="${PLASMIDEC_MIN_LENGTH:-1000}"     # PlasmidEC's own -l default
export PLASMIDEC_CLASSIFIERS="${PLASMIDEC_CLASSIFIERS:-}"       # empty: its default; or lowercase, comma separated (its -c)
# RUN_PERFORMANCE_DRIVERS: 1 (default) or 0. Stage 6 fits, per tool, one model of per-plasmid recovery on plasmid size, repeat content, replicon family,
# resistance genes, species, read depth and the recent/older arm, with study-clustered intervals (benchmark.performance_drivers.*; the report's
# "Performance drivers" section). A tool with too few plasmids or studies is reported as not estimable. Descriptive: never changes a score or ranking.
export RUN_PERFORMANCE_DRIVERS="${RUN_PERFORMANCE_DRIVERS:-1}"
# PLSDB novelty (python/plsdb_novelty.py): each truth plasmid is aligned to PLSDB and called known (a record covers at least NOVELTY_KNOWN_COVERAGE of it at
# NOVELTY_KNOWN_IDENTITY), related (a record covers at least NOVELTY_RELATED_COVERAGE) or novel; recovery is then split by class (benchmark.plsdb_novelty*;
# the report's "Novelty" section) and the class is a driver in the performance-drivers model. RUN_PLSDB_NOVELTY is auto (run when PLSDB_FASTA exists) or off.
# PLSDB_FASTA is the sequences FASTA written by env/download_plsdb.sh. Novelty is relative to that PLSDB release. Descriptive: never changes a score or ranking.
export RUN_PLSDB_NOVELTY="${RUN_PLSDB_NOVELTY:-auto}"
export PLSDB_FASTA="${PLSDB_FASTA:-$(plasbench_db_path plsdb)/sequences.fasta}"
export NOVELTY_KNOWN_COVERAGE="${NOVELTY_KNOWN_COVERAGE:-0.80}"
export NOVELTY_KNOWN_IDENTITY="${NOVELTY_KNOWN_IDENTITY:-0.95}"
export NOVELTY_RELATED_COVERAGE="${NOVELTY_RELATED_COVERAGE:-0.30}"

# --- Where the tools run (conda or Docker) -----------------------------------
# conda (the default) runs the benchmark tools from the plasbench conda environment on this computer. docker runs every command that needs them (a run, check,
# install-tools) inside a container of the PlasBench image, with your study, data and database folders mounted at the same paths; conda stays installed and you can switch back at any time (Set up this computer, Environment, or plasbench runtime use conda|docker).
export PLASBENCH_RUNTIME="${PLASBENCH_RUNTIME:-conda}"
# The image used when the runtime is docker. Empty means the published image of this PlasBench version (ghcr.io/ubeffiong/plasbench:v<version>), else the image built here from the Dockerfile (plasbench:<version>-local). Never latest by default; give a name to use another image.
export PLASBENCH_DOCKER_IMAGE="${PLASBENCH_DOCKER_IMAGE:-}"
# When to pull the image from the registry: missing (only when it is not on this computer; the default), always (refresh it every time), or never (use only what is here, or build it).
export PLASBENCH_DOCKER_PULL="${PLASBENCH_DOCKER_PULL:-missing}"
# Where tools and databases added in Docker mode are kept between containers (empty: ~/.plasbench/docker/<version>/extras). The image itself is never changed.
export PLASBENCH_DOCKER_EXTRA="${PLASBENCH_DOCKER_EXTRA:-}"

# --- AI help (the assistant in the side panel; free OpenRouter models only) ---------------------------------
# 1 shows the AI help (the AI help tab of the side panel, the top-bar button and `plasbench ask`); 0 hides it and the window refuses its requests. Nothing is sent anywhere until you sign in to OpenRouter, accept the notice, and ask a question.
export AI_HELP_ENABLED="${AI_HELP_ENABLED:-1}"
# The free OpenRouter model to use, for example google/gemma-4-31b-it:free. Empty means the best-suited free model in OpenRouter's current list. A model that is not free (by its price in the list) is refused.
export AI_MODEL="${AI_MODEL:-}"
# The most tokens (questions plus answers) the AI help may use per day on this computer; it stops with a clear message at the limit. The default 0 means no limit of its own (OpenRouter's own free limits still apply).
export AI_DAILY_TOKEN_CAP="${AI_DAILY_TOKEN_CAP:-0}"
# 1 asks the model for short answers (fewer tokens); the pane also has a Brief answers switch.
export AI_BRIEF="${AI_BRIEF:-0}"
# 1 tries the next free model when the chosen one hits a limit or is down (never a paid model); 0 stops with the message instead.
export AI_FREE_FALLBACK="${AI_FREE_FALLBACK:-1}"
# For tests and for a self-hosted gateway that speaks the OpenRouter API: the address that replaces https://openrouter.ai/api/v1. Leave empty for OpenRouter. The key is sent to this address, so set it only to a service you trust.
export AI_OPENROUTER_BASE="${AI_OPENROUTER_BASE:-}"
# Which provider answers: openrouter (free models, sign-in in a pop-up), huggingface (needs AI_HF_CLIENT_ID) or local (a model server on this computer: Ollama or LM Studio). The window offers the choice and remembers it.
export AI_PROVIDER="${AI_PROVIDER:-openrouter}"
# The client id of a PUBLIC Hugging Face OAuth app (no secret) registered with the redirect address http://localhost/ai/hf/callback and the scope inference-api (see docs/AI_HELP.md). Empty: the Hugging Face sign-in button is off.
export AI_HF_CLIENT_ID="${AI_HF_CLIENT_ID:-}"
# 1 also allows cheap Hugging Face models that spend YOUR Hugging Face credits (free accounts have none); 0 uses only models that Hugging Face lists as free.
export AI_HF_USE_CREDITS="${AI_HF_USE_CREDITS:-0}"
# For tests and for a self-hosted gateway: the addresses that replace https://router.huggingface.co/v1 and https://huggingface.co. Leave empty for Hugging Face.
export AI_HF_BASE="${AI_HF_BASE:-}"
export AI_HF_HUB="${AI_HF_HUB:-}"
# The address of the local model server (empty: Ollama http://localhost:11434/v1, then LM Studio http://localhost:1234/v1). Only addresses on this computer are used unless AI_LOCAL_ALLOW_REMOTE is 1.
export AI_LOCAL_BASE="${AI_LOCAL_BASE:-}"
export AI_LOCAL_ALLOW_REMOTE="${AI_LOCAL_ALLOW_REMOTE:-0}"
