#!/usr/bin/env bash
# =============================================================================
# PlasBench — central configuration
# Edit this file, then run scripts/run_all.sh
# =============================================================================
# Every script sources this file, so all paths and settings live in one place.

# --- Project root (auto-detected; normally leave as-is) ----------------------
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# --- Where things go ---------------------------------------------------------
export DATA_DIR="${DATA_DIR:-$PROJECT_ROOT/data}"          # downloaded refs + reads
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

export THREADS="${THREADS:-$(plasbench_detect_cores)}"

# Keep headroom: the OS, the other tools in the stage, and SPAdes overshooting
# its own budget all need room. 80% of what is actually available, never below
# 2GB (SPAdes fails outright under that) and never silently capped above.
PLASBENCH_AVAILABLE_GB="$(plasbench_detect_memory_gb)"
PLASBENCH_DEFAULT_MEMORY_GB=$(( PLASBENCH_AVAILABLE_GB * 80 / 100 ))
[[ "$PLASBENCH_DEFAULT_MEMORY_GB" -lt 2 ]] && PLASBENCH_DEFAULT_MEMORY_GB=2
export PLASBENCH_AVAILABLE_GB
export MEMORY_GB="${MEMORY_GB:-$PLASBENCH_DEFAULT_MEMORY_GB}"   # assembler memory budget (GB)

# --- Parallelism ---------------------------------------------------------
# Every default below (1) is exactly today's fully sequential behavior: one
# sample at a time, one tool at a time. Raise them only after checking your
# machine's core/RAM budget below can actually support it -- e.g. 2 parallel
# samples x 2 parallel tools x THREADS=4 wants 16 CPU threads at once.
export MAX_PARALLEL_SAMPLES="${MAX_PARALLEL_SAMPLES:-1}"   # stages 1, 3, 4, 5
export MAX_PARALLEL_TOOLS="${MAX_PARALLEL_TOOLS:-1}"       # independent tools within one sample, stage 4
# Per-tool thread counts. Each defaults to $THREADS (today's behavior: every
# tool gets the same value); set these independently once you run tools
# concurrently, so N concurrent tools don't each ask for all of $THREADS.
export MOB_RECON_THREADS="${MOB_RECON_THREADS:-$THREADS}"
export PLATON_THREADS="${PLATON_THREADS:-$THREADS}"
export PLASMIDSPADES_THREADS="${PLASMIDSPADES_THREADS:-$THREADS}"
export GPLAS_THREADS="${GPLAS_THREADS:-$THREADS}"          # gplas itself is single-threaded; governs its classifier-prep step
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
export RUN_FLYE_MOB_RECON="${RUN_FLYE_MOB_RECON:-0}"
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
export PLASSEMBLER_DB="${PLASSEMBLER_DB:-$DATA_DIR/db/plassembler}"
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

# Reuse a completed tool result by default. Set FORCE_RERUN_TOOLS=1 to discard
# completed per-tool output and run it again (for example after a tool upgrade).
export FORCE_RERUN_TOOLS="${FORCE_RERUN_TOOLS:-0}"

# --- Tool databases (set after INSTALL step) ---------------------------------
# Platon needs its DB downloaded once; point to it here.
export PLATON_DB="${PLATON_DB:-$DATA_DIR/db/platon/db}"

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

# --- Mapping (scoring) -------------------------------------------------------
# minimap2 preset for aligning predicted-plasmid contigs back to the reference.
export MINIMAP2_PRESET="${MINIMAP2_PRESET:-asm5}" # asm5 = <5% divergence
export MIN_ALIGNMENT_LENGTH="${MIN_ALIGNMENT_LENGTH:-200}"
export MIN_ALIGNMENT_IDENTITY="${MIN_ALIGNMENT_IDENTITY:-0.90}"
export MIN_ALIGNMENT_MAPQ="${MIN_ALIGNMENT_MAPQ:-20}"
export MIN_ALIGNMENT_QUERY_COVERAGE="${MIN_ALIGNMENT_QUERY_COVERAGE:-0.20}"
# A second, all-mappings PAF exposes repeated query sequence that aligns to
# both plasmid and chromosome. It is a diagnostic and never alters F1.
export REPORT_MAPPING_AMBIGUITY="${REPORT_MAPPING_AMBIGUITY:-1}"
# Largest primary alignment blocks retained per tool in the offline explorer.
# This prevents a fragmented assembly from making the report unresponsive.
# Call installed annotation tools (mob_typer/abricate/amrfinder/isescan) to
# derive replicon, MOB, AMR, and IS features instead of hand-curated tables.
# Absent callers are recorded as "not evaluated", never as absent features.
export RUN_REFERENCE_ANNOTATION="${RUN_REFERENCE_ANNOTATION:-1}"
export ANNOTATION_AMR_DB="${ANNOTATION_AMR_DB:-ncbi}"
export ANNOTATION_REPLICON_DB="${ANNOTATION_REPLICON_DB:-plasmidfinder}"

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

# --- Safety: stop early if the sample sheet is missing -----------------------
if [[ ! -f "$SAMPLE_SHEET" ]]; then
    echo "WARNING: sample sheet not found at $SAMPLE_SHEET" >&2
fi
