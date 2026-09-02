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

# --- Compute -----------------------------------------------------------------
export THREADS="${THREADS:-4}"
export MEMORY_GB="${MEMORY_GB:-16}"           # SPAdes memory cap (GB)

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
export GPLAS2_EXTERNAL_PREDICTIONS_DIR="${GPLAS2_EXTERNAL_PREDICTIONS_DIR:-}"
export GPLAS2_MIN_CONTIG_LENGTH="${GPLAS2_MIN_CONTIG_LENGTH:-1000}"

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
export VISUALIZATION_MAX_BLOCKS_PER_TOOL="${VISUALIZATION_MAX_BLOCKS_PER_TOOL:-2000}"

# --- Safety: stop early if the sample sheet is missing -----------------------
if [[ ! -f "$SAMPLE_SHEET" ]]; then
    echo "WARNING: sample sheet not found at $SAMPLE_SHEET" >&2
fi
