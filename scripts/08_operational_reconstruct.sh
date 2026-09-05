#!/usr/bin/env bash
# Operational reconstruction — for ONE new sample that has no complete-
# reference truth (so it cannot be scored), reconstruct plasmids using ONLY
# the single method PlasBench's benchmark already selected as the best
# operational recommendation, instead of running every benchmarked method.
#
# The benchmark cohort's own reconstructions are never repeated: this stage
# only ever runs against the one-row sample sheet it builds for the new
# sample, so it cannot touch (or re-run tools for) any sample already scored
# in a prior benchmark run. Reusing an already-benchmarked sample's own
# output is `plasbench select-unknown` / `plasbench select-candidates`,
# which only ever copy an already-produced prediction FASTA.
#
# Usage:
#   08_operational_reconstruct.sh --sample ID --sra SRA_RUN
#       [--tool TOOL]                  explicit override; skips recommendation lookup
#       [--recommendations PATH]       default: $RESULTS_DIR/benchmark.recommendations.tsv
#       [--recommendation-model PATH]  default: $RESULTS_DIR/benchmark.recommendation_model.json
#                                      when RUN_RECOMMENDATION_MODEL=1; used only if model_ready
#       [--read-depth-x N]             this isolate's own depth, if known, for live model prediction
#       [--organism NAME] [--gram-group GROUP]
#       [--analysis-track short_read|long_read|hybrid]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

SAMPLE="" SRA="" TOOL="" RECOMMENDATIONS="" RECOMMENDATION_MODEL="" READ_DEPTH_X="" ORGANISM="" GRAM_GROUP="" TRACK="short_read"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sample) SAMPLE="$2"; shift 2 ;;
        --sra) SRA="$2"; shift 2 ;;
        --tool) TOOL="$2"; shift 2 ;;
        --recommendations) RECOMMENDATIONS="$2"; shift 2 ;;
        --recommendation-model) RECOMMENDATION_MODEL="$2"; shift 2 ;;
        --read-depth-x) READ_DEPTH_X="$2"; shift 2 ;;
        --organism) ORGANISM="$2"; shift 2 ;;
        --gram-group) GRAM_GROUP="$2"; shift 2 ;;
        --analysis-track) TRACK="$2"; shift 2 ;;
        *) die "unknown argument: $1" ;;
    esac
done
[[ -n "$SAMPLE" ]] || die "--sample is required"
[[ -n "$SRA" ]] || die "--sra is required"
valid_sample_id "$SAMPLE" || die "unsafe --sample '$SAMPLE'; use only letters, digits, dot, dash, underscore"
RECOMMENDATIONS="${RECOMMENDATIONS:-$RESULTS_DIR/benchmark.recommendations.tsv}"
if [[ "${RUN_RECOMMENDATION_MODEL:-0}" -eq 1 ]]; then
    RECOMMENDATION_MODEL="${RECOMMENDATION_MODEL:-$RESULTS_DIR/benchmark.recommendation_model.json}"
fi
MODEL_ARGS=(); [[ -n "$RECOMMENDATION_MODEL" ]] && MODEL_ARGS=(--recommendation-model "$RECOMMENDATION_MODEL")
[[ -n "$READ_DEPTH_X" ]] && MODEL_ARGS+=(--read-depth-x "$READ_DEPTH_X")
# This can be the very first command run against a fresh DATA_DIR/RESULTS_DIR/
# LOG_DIR (e.g. a new deployment that never ran stage 0), so create them here
# instead of assuming stage 0 already has.
mkdir -p "$DATA_DIR" "$RESULTS_DIR" "$LOG_DIR" "${TMP_DIR:-/tmp}"

KNOWN_TOOLS=(mob_recon platon plasmidspades gplas2_mob gplas2_external genomad plasme plasgraph2)
TOOL_SOURCE="explicit"
if [[ -n "$TOOL" ]]; then
    match=0
    for known in "${KNOWN_TOOLS[@]}"; do [[ "$TOOL" == "$known" ]] && match=1; done
    [[ "$match" -eq 1 ]] || die "--tool must be one of: ${KNOWN_TOOLS[*]} (got '$TOOL')"
else
    TOOL_SOURCE="recommended"
    [[ -s "$RECOMMENDATIONS" ]] || die "no --tool given and no recommendations file at $RECOMMENDATIONS; run the benchmark first, or pass --tool explicitly"
    log "No --tool given; asking the benchmark recommendation for organism='$ORGANISM' gram-group='$GRAM_GROUP' ..."
    if ! TOOL="$(python3 "$HERE/../python/select_unknown_sample.py" --recommendations "$RECOMMENDATIONS" \
            --tool-only --organism "$ORGANISM" --gram-group "$GRAM_GROUP" "${MODEL_ARGS[@]}")"; then
        die "no evidence-gated recommendation matched this sample's metadata in $RECOMMENDATIONS; pass --tool explicitly"
    fi
    log "Benchmark recommends: $TOOL"
fi

TMP_SHEET="$(mktemp "${TMP_DIR:-/tmp}/plasbench_operational_XXXXXX.tsv")"
trap 'rm -f "$TMP_SHEET"' EXIT
printf 'sample_id\tassembly_accession\tsra_run\n%s\tNA\t%s\n' "$SAMPLE" "$SRA" > "$TMP_SHEET"

log "=== Operational reconstruction: $SAMPLE (tool: $TOOL, source: $TOOL_SOURCE) ==="
log "--- stage 1: download reads only (no reference; this sample is not truth-scored) ---"
SAMPLE_SHEET="$TMP_SHEET" bash "$HERE/01_download.sh"
log "--- stage 3: QC + assembly ---"
SAMPLE_SHEET="$TMP_SHEET" bash "$HERE/03_assemble.sh"
log "--- stage 4: reconstruct with $TOOL only ---"
SAMPLE_SHEET="$TMP_SHEET" ONLY_TOOL="$TOOL" ANALYSIS_TRACK="$TRACK" bash "$HERE/04_run_tools.sh"

PRED="$RESULTS_DIR/$SAMPLE/pred_${TOOL}.plasmid.fasta"
[[ -s "$PRED" ]] || die "$TOOL did not produce a prediction for $SAMPLE; see $LOG_DIR/${SAMPLE}.${TOOL}.log"

if [[ "$TOOL_SOURCE" == "recommended" ]]; then
    # The tool that just ran IS the benchmark recommendation for this
    # metadata, so the normal selection path can re-derive it, find the
    # prediction it just produced, and write the standard report.
    python3 "$HERE/../python/select_unknown_sample.py" --recommendations "$RECOMMENDATIONS" \
        --sample-id "$SAMPLE" --results-dir "$RESULTS_DIR" --organism "$ORGANISM" \
        --gram-group "$GRAM_GROUP" --analysis-track "$TRACK" "${MODEL_ARGS[@]}"
else
    # An explicit --tool override may not match whatever the benchmark would
    # have recommended (or no recommendations file may exist at all yet), so
    # record that plainly instead of routing through recommendation-based
    # selection, which would silently look for a possibly-different tool.
    OUT_DIR="$RESULTS_DIR/$SAMPLE/selected_candidate"
    mkdir -p "$OUT_DIR"
    cp "$PRED" "$OUT_DIR/candidate.plasmid.fasta"
    python3 "$HERE/../python/write_operational_override_report.py" \
        --sample-id "$SAMPLE" --tool "$TOOL" --analysis-track "$TRACK" \
        --organism "$ORGANISM" --gram-group "$GRAM_GROUP" \
        --out "$RESULTS_DIR/$SAMPLE/selection_report.json"
fi

log "=== Done: $RESULTS_DIR/$SAMPLE/selected_candidate/candidate.plasmid.fasta ==="
