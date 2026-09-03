#!/usr/bin/env bash
# run_demo.sh — exercise the SCORING, ANALYSIS and REPORTING path end to end on
# synthetic data, with NO downloads and NO bioinformatics tools installed.
#
# The cohort is fabricated by test/demo_dataset.py: six isolates across three
# organisms and three studies, five methods, eleven truth plasmids, and one
# deliberate method failure. Every record is shaped to drive a behaviour the
# report claims to show — split and merge bins, inversions, duplications,
# chromosomal contamination, unsupported joins and low-identity alignment — so
# the demo exercises the tracks, bin flow, structural calls and drilldown rather
# than leaving them empty.
#
# Nothing here is a biological result. Use it to confirm the engine works before
# investing in the full install.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEMO="$ROOT/results_demo"
# Clear the contents rather than the directory itself. A synced folder
# (OneDrive), an open editor or a file browser can hold the directory handle,
# and then removing the directory fails while emptying it succeeds.
mkdir -p "$DEMO"
find "$DEMO" -mindepth 1 -delete 2>/dev/null || true

PY="$ROOT/python"
SCORES="$DEMO/scores.tsv"; rm -f "$SCORES"
STATUS="$DEMO/tool_status.tsv"
SAMPLES="$DEMO/samples.tsv"

python3 "$HERE/demo_dataset.py" --out-dir "$DEMO"

CAPABILITIES="$ROOT/config/tool_capabilities.tsv"
binning_capable() {
    python3 "$PY/tool_capabilities.py" --registry "$CAPABILITIES" --tool "$1" --binning-capable >/dev/null 2>&1
}

# Stage 5 equivalent, per sample and method: score, bin-score where the method
# declares bins, call structural discordance, and build the display payload.
while IFS=$'\t' read -r SAMPLE _; do
    [[ "$SAMPLE" == "sample_id" || -z "$SAMPLE" ]] && continue
    SDIR="$DEMO/$SAMPLE"
    TRUTH="$SDIR/truth.tsv"
    AMR="$SDIR/truth_amr.tsv"
    CIRCULAR="$SDIR/truth_circular.tsv"
    FEATURES="$SDIR/truth_features.tsv"

    shopt -s nullglob
    for PAF in "$SDIR"/*.pred_vs_ref.paf; do
        TOOL="$(basename "$PAF" .pred_vs_ref.paf)"
        PRED="$SDIR/pred_${TOOL}.plasmid.fasta"
        ARGS=()
        [[ -s "$AMR" ]] && ARGS+=(--amr-genes "$AMR")
        [[ -s "$CIRCULAR" ]] && ARGS+=(--circular-plasmids "$CIRCULAR")
        python3 "$PY/score_plasmids.py" --truth "$TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            "${ARGS[@]}" --sample "$SAMPLE" --tool "$TOOL" --out "$SCORES"

        BINS="$SDIR/pred_${TOOL}.bins.tsv"
        if [[ -s "$BINS" ]] && binning_capable "$TOOL"; then
            python3 "$PY/score_bins.py" --truth "$TRUTH" --paf "$PAF" --bins "$BINS" \
                --out "$SDIR/${TOOL}.bin_matches.tsv" --summary "$SDIR/${TOOL}.bin_summary.tsv" >/dev/null
        fi
    done
    shopt -u nullglob

    python3 "$PY/call_structural_variants.py" --truth "$TRUTH" --results-dir "$DEMO" \
        --sample "$SAMPLE" --events-out "$SDIR/structural_events.tsv" \
        --summary-out "$SDIR/structural_summary.tsv" \
        --json-out "$SDIR/visualization/structural_calls.json" >/dev/null

    VIZ_ARGS=()
    [[ -s "$AMR" ]] && VIZ_ARGS+=(--amr-truth "$AMR")
    [[ -s "$CIRCULAR" ]] && VIZ_ARGS+=(--circular-truth "$CIRCULAR")
    [[ -s "$FEATURES" ]] && VIZ_ARGS+=(--feature-truth "$FEATURES")
    python3 "$PY/build_visualization_data.py" --truth "$TRUTH" --results-dir "$DEMO" \
        --sample "$SAMPLE" "${VIZ_ARGS[@]}" \
        --out "$SDIR/visualization/alignment_blocks.json" >/dev/null
done < "$SAMPLES"

python3 "$PY/merge_bin_metrics.py" --scores "$SCORES" --results-dir "$DEMO"

echo
echo "===== per-sample scores ($SCORES) ====="
if command -v column >/dev/null 2>&1; then
    column -t -s$'\t' "$SCORES" | cut -c1-150
else
    cat "$SCORES"
fi

python3 "$PY/aggregate_results.py" --scores "$SCORES" --tool-status "$STATUS" \
    --sample-sheet "$SAMPLES" --out-prefix "$DEMO/benchmark"
python3 "$PY/validate_recommendations.py" --scores "$SCORES" --samples "$SAMPLES" \
    --out "$DEMO/benchmark.recommendation_validation.tsv" --min-train-samples 1
python3 "$PY/select_operational_method.py" --scores "$SCORES" --sample-sheet "$SAMPLES" \
    --results-dir "$DEMO" --tool-status "$STATUS" --out-prefix "$DEMO/benchmark" \
    --recommendation-validation "$DEMO/benchmark.recommendation_validation.tsv" \
    --min-samples 1 --min-coverage 1

python3 "$PY/build_html_report.py" \
    --project-root "$ROOT" \
    --scores "$SCORES" \
    --tool-status "$STATUS" \
    --leaderboard "$DEMO/benchmark.leaderboard.tsv" \
    --sample-sheet "$SAMPLES" \
    --recommendations "$DEMO/benchmark.recommendations.tsv" \
    --recommendation-validation "$DEMO/benchmark.recommendation_validation.tsv" \
    --out "$DEMO/benchmark.report.html"

echo
echo "===== leaderboard markdown ====="
cat "$DEMO/benchmark.leaderboard.md"
echo
echo "===== structural discordance calls ====="
echo "Alignment-derived, not validated misassemblies."
echo "Columns: sample, tool, aligned bp, collinear bp, collinear fraction, records, events."
# sed consumes its whole input, so it cannot raise SIGPIPE under pipefail.
for summary in "$DEMO"/*/structural_summary.tsv; do
    sample="$(basename "$(dirname "$summary")")"
    cut -f1-6 "$summary" | sed -n "2,6p" | sed "s/^/  $sample  /"
done | sed -n "1,10p"

echo
echo "===== interactive HTML report ====="
echo "$DEMO/benchmark.report.html"
echo
echo "All demo data is synthetic. It demonstrates the engine, not a biological result."
echo "Demo outputs are in: $DEMO"
