#!/usr/bin/env bash
# Optional, opt-in thread-scaling sweep: re-runs ONE already-registered tool
# on a small sample subset at several thread counts, answering whether the
# main leaderboard's runtime numbers (and, for a genuinely parallelizable
# step, sometimes its accuracy) depend on the thread-count choice a tool
# happens to be given -- see docs/METHODS.md's "Equal CPU allocation across
# tools" fairness policy, which this sweep tests empirically rather than
# just documents.
#
# Deliberately reuses scripts/04_run_tools.sh's OWN machinery unchanged --
# its ONLY_TOOL restriction (see tool_enabled()) and its existing
# profile_exec/RSS-capture instrumentation (already writes runtime_seconds/
# peak_rss_kb into tool_status.tsv for every real run) -- rather than
# inventing a second profiling mechanism. Each sweep point is a REAL,
# complete stage-4 invocation restricted to one tool and one small sample
# set, with --force-rerun-tools implied (a "reused" result would report a
# stale runtime from a different thread count, not this sweep point's own).
#
# The samples named must already be downloaded and assembled (contigs.fasta
# present) -- this sweep only re-runs stage 4, never stages 1-3.
#
# Usage:
#   bash scripts/thread_scaling_sweep.sh --tool platon --samples s1,s2 [--threads 1,4,8]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

TOOL="" SAMPLES="" THREAD_LIST="1,4,8"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool) TOOL="$2"; shift 2 ;;
        --samples) SAMPLES="$2"; shift 2 ;;
        --threads) THREAD_LIST="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --tool <name> --samples <id[,id...]> [--threads 1,4,8]"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done
[[ -n "$TOOL" ]] || die "--tool is required (a name from config/tool_capabilities.tsv)"
[[ -n "$SAMPLES" ]] || die "--samples is required: a comma-separated list of already-assembled sample_id(s)"

# --analysis-track always prints and exits 0 for any tool the registry
# actually declares, regardless of its value -- unlike --binning-capable/
# --requires-independent-long-read-truth, which gate on a SPECIFIC yes/no
# value and exit 1 for plenty of real, valid tools. This is purely an
# existence check; its printed output is discarded.
python3 "$HERE/../python/tool_capabilities.py" --registry "$HERE/../config/tool_capabilities.tsv" \
    --tool "$TOOL" --analysis-track > /dev/null \
    || die "unknown tool '$TOOL'; see config/tool_capabilities.tsv for registered names"

TOOL_UPPER="$(printf '%s' "$TOOL" | tr '[:lower:]' '[:upper:]')"
THREADS_VAR="${TOOL_UPPER}_THREADS"

IFS=',' read -ra SAMPLE_ARRAY <<< "$SAMPLES"
for s in "${SAMPLE_ARRAY[@]}"; do
    [[ -s "$DATA_DIR/$s/contigs.fasta" ]] || die "no assembled contigs for sample '$s' at $DATA_DIR/$s/contigs.fasta -- run stages 1-3 first"
done

mkdir -p "$RESULTS_DIR" "$TMP_DIR"
OUT="$RESULTS_DIR/thread_scaling_sweep.${TOOL}.tsv"
printf 'tool\tsample\tthreads\truntime_seconds\tpeak_rss_kb\n' > "$OUT"

# One throwaway sheet reused for every sweep point, built from the REAL
# sample sheet's own accession/run columns so run_<tool>() sees the same
# values it always would -- only ONLY_TOOL/<TOOL>_THREADS/RESULTS_DIR change
# per sweep point below.
SWEEP_SHEET="$TMP_DIR/thread_scaling_sweep.sheet.tsv"
{
    printf 'sample_id\tassembly_accession\tsra_run\n'
    for s in "${SAMPLE_ARRAY[@]}"; do
        printf '%s\t%s\t%s\n' "$s" \
            "$(sample_column "$SAMPLE_SHEET" "$s" assembly_accession)" \
            "$(sample_column "$SAMPLE_SHEET" "$s" sra_run)"
    done
} > "$SWEEP_SHEET"

IFS=',' read -ra THREAD_POINTS <<< "$THREAD_LIST"
for threads in "${THREAD_POINTS[@]}"; do
    log "=== thread-scaling sweep: $TOOL at $threads thread(s) (samples: $SAMPLES) ==="
    SWEEP_RESULTS="$TMP_DIR/thread_scaling_sweep.${TOOL}.${threads}threads"
    rm -rf "$SWEEP_RESULTS"
    env ONLY_TOOL="$TOOL" "$THREADS_VAR=$threads" FORCE_RERUN_TOOLS=1 \
        SAMPLE_SHEET="$SWEEP_SHEET" RESULTS_DIR="$SWEEP_RESULTS" \
        bash "$HERE/04_run_tools.sh" > "$LOG_DIR/thread_scaling_sweep.${TOOL}.${threads}threads.log" 2>&1 \
        || die "stage 4 failed at $threads thread(s); see $LOG_DIR/thread_scaling_sweep.${TOOL}.${threads}threads.log"
    # tool_status.tsv columns: sample tool status prediction_fasta reason runtime_seconds peak_rss_kb
    awk -F'\t' -v tool="$TOOL" -v threads="$threads" '
        NR == 1 { next }
        $2 == tool { print tool "\t" $1 "\t" threads "\t" $6 "\t" $7 }
    ' "$SWEEP_RESULTS/tool_status.tsv" >> "$OUT"
done

log "Thread-scaling sweep complete: $OUT"
column -t -s $'\t' "$OUT" >&2 || cat "$OUT" >&2
