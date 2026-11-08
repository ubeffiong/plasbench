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
    PROTEINS="$SDIR/truth_proteins.tsv"

    shopt -s nullglob
    for PAF in "$SDIR"/*.pred_vs_ref.paf; do
        TOOL="$(basename "$PAF" .pred_vs_ref.paf)"
        PRED="$SDIR/pred_${TOOL}.plasmid.fasta"
        ARGS=()
        [[ -s "$AMR" ]] && ARGS+=(--amr-genes "$AMR")
        [[ -s "$CIRCULAR" ]] && ARGS+=(--circular-plasmids "$CIRCULAR")
        python3 "$PY/score_plasmids.py" --truth "$TRUTH" --paf "$PAF" --pred-fasta "$PRED" \
            "${ARGS[@]}" --per-plasmid-out "$SDIR/${TOOL}.per_plasmid.tsv" \
            --sample "$SAMPLE" --tool "$TOOL" --out "$SCORES"

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
    [[ -s "$PROTEINS" ]] && VIZ_ARGS+=(--protein-truth "$PROTEINS")
    python3 "$PY/build_visualization_data.py" --truth "$TRUTH" --results-dir "$DEMO" \
        --sample "$SAMPLE" --reference "$SDIR/reference.fna" "${VIZ_ARGS[@]}" \
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
# Advisory layers, same scripts and arguments as stage 6: never ranked, never alter scores.
python3 "$PY/stratify_recovery.py" --results-dir "$DEMO" --data-dir "$DEMO" \
    --out "$DEMO/benchmark.recovery_by_replicon.tsv"
python3 "$PY/audit_truth_labels.py" --data-dir "$DEMO" --out "$DEMO/benchmark.truth_label_audit.tsv"
python3 "$PY/rank_sensitivity.py" --scores "$SCORES" --results-dir "$DEMO" --data-dir "$DEMO" \
    --out-prefix "$DEMO/benchmark" --min-alignment-length 1 --min-alignment-identity 0 \
    --min-alignment-mapq 0 --min-alignment-query-coverage 0   # the demo scores with the scorer's own permissive filters
# Further dimensions: the same scripts and arguments as stages 5 and 6, so the offline demo exercises them.
for SDIR_X in "$DEMO"/*/; do
    SAMPLE_X="$(basename "$SDIR_X")"; [[ -s "$SDIR_X/truth.tsv" ]] || continue
    for PAF_X in "$SDIR_X"*.pred_vs_ref.paf; do
        TOOL_X="$(basename "$PAF_X" .pred_vs_ref.paf)"
        python3 "$PY/alignment_accuracy.py" --truth "$SDIR_X/truth.tsv" --paf "$PAF_X" --sample "$SAMPLE_X" \
            --tool "$TOOL_X" --out "$SDIR_X/${TOOL_X}.accuracy.tsv" --regions-out "$SDIR_X/${TOOL_X}.missing_regions.tsv"
        FEATURES_X="$SDIR_X/truth_features.tsv"; [[ -s "$SDIR_X/truth_proteins.tsv" ]] && FEATURES_X="$SDIR_X/truth_proteins.tsv"
        CIRC_X=(); [[ -s "$SDIR_X/truth_circular.tsv" ]] && CIRC_X=(--circular-plasmids "$SDIR_X/truth_circular.tsv")
        [[ -s "$FEATURES_X" ]] && python3 "$PY/feature_preservation.py" --truth "$SDIR_X/truth.tsv" --paf "$PAF_X" \
            --features "$FEATURES_X" "${CIRC_X[@]}" --sample "$SAMPLE_X" --tool "$TOOL_X" \
            --out "$SDIR_X/${TOOL_X}.feature_preservation.tsv" --ngoc-out "$SDIR_X/${TOOL_X}.ngoc.tsv"
        BINS_X="$SDIR_X/pred_${TOOL_X}.bins.tsv"
        if [[ -s "$BINS_X" ]] && binning_capable "$TOOL_X"; then
            python3 "$PY/bin_quality.py" --truth "$SDIR_X/truth.tsv" --paf "$PAF_X" --bins "$BINS_X" \
                --sample "$SAMPLE_X" --tool "$TOOL_X" --out "$SDIR_X/${TOOL_X}.bin_quality.tsv"
        fi
    done
done
DIM="$DEMO/benchmark"
for table in accuracy missing_regions feature_preservation ngoc bin_quality; do
    python3 "$PY/merge_tables.py" --results-dir "$DEMO" --suffix ".${table}.tsv" --out "$DIM.${table}.tsv"
done
python3 "$PY/mask_accuracy.py" --accuracy "$DIM.accuracy.tsv"
python3 "$PY/performance_summary.py" --tool-status "$STATUS" --scores "$SCORES" --data-dir "$DEMO" \
    --threads 1 --out "$DIM.performance.tsv"
python3 "$PY/power_analysis.py" --scores "$SCORES" --sample-sheet "$SAMPLES" --out "$DIM.power.tsv"
python3 "$PY/scenario_tags.py" --scores "$SCORES" --data-dir "$DEMO" --sample-sheet "$SAMPLES" \
    --out "$DIM.scenarios.tsv" --performance-out "$DIM.scenario_performance.tsv"
python3 "$PY/composite_score.py" --scores "$SCORES" --accuracy "$DIM.accuracy.tsv" \
    --feature-preservation "$DIM.feature_preservation.tsv" --ngoc "$DIM.ngoc.tsv" \
    --bin-quality "$DIM.bin_quality.tsv" --performance "$DIM.performance.tsv" \
    --out "$DIM.composite.tsv" --sensitivity-out "$DIM.composite_sensitivity.tsv"

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
    --manifest "$DEMO/run_manifest.json" \
    --recovery-by-replicon "$DEMO/benchmark.recovery_by_replicon.tsv" \
    --truth-label-audit "$DEMO/benchmark.truth_label_audit.tsv" \
    --dimensions-prefix "$DEMO/benchmark" \
    --comparisons "$DEMO/benchmark.paired_comparisons.tsv" \
    --stratified "$DEMO/benchmark.stratified.tsv" \
    --rank-robustness "$DEMO/benchmark.rank_robustness.tsv" \
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
echo "Open it with: plasbench open-report --report \"$DEMO/benchmark.report.html\""
echo
echo "All demo data is synthetic. It demonstrates the engine, not a biological result."
echo "Demo outputs are in: $DEMO"
