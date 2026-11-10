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

    # Contig layer (stage 5 equivalent), on the synthetic assembly, plus the
    # independent alignment-free cross-check and the assembly statistics.
    python3 "$PY/contig_classification.py" label --contigs "$SDIR/contigs.fasta" --paf "$SDIR/contigs_vs_ref.paf" \
        --truth "$TRUTH" --labels-out "$SDIR/contig_labels.tsv" --coverage-out "$SDIR/plasmid_assembly_coverage.tsv" \
        2>/dev/null
    python3 "$PY/contig_crosscheck.py" label --contigs "$SDIR/contigs.fasta" --reference "$SDIR/reference.full.fna" \
        --truth "$TRUTH" --out "$SDIR/contig_labels.kmer.tsv" --scaled 50 2>/dev/null
    python3 "$PY/compute_assembly_stats.py" --fasta "$SDIR/reference.full.fna" --truth "$TRUTH" \
        --sample-id "$SAMPLE" --out "$SDIR/assembly_stats.tsv" 2>/dev/null
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
        CONTIG_BIN_ARGS=()
        [[ -s "$BINS" ]] && binning_capable "$TOOL" && CONTIG_BIN_ARGS=(--bins "$BINS")
        python3 "$PY/contig_classification.py" score --labels "$SDIR/contig_labels.tsv" --pred-fasta "$PRED" \
            "${CONTIG_BIN_ARGS[@]+"${CONTIG_BIN_ARGS[@]}"}" --out "$SDIR/${TOOL}.contig_classification.tsv"
        if [[ -s "$BINS" ]] && binning_capable "$TOOL"; then
            python3 "$PY/score_bins.py" --truth "$TRUTH" --paf "$PAF" --bins "$BINS" \
                --outcomes-out "$SDIR/${TOOL}.plasmid_outcomes.tsv" \
                --out "$SDIR/${TOOL}.bin_matches.tsv" --summary "$SDIR/${TOOL}.bin_summary.tsv" >/dev/null
        fi
        # AMR placement, as stage 5 runs it when curated AMR truth exists.
        if [[ -s "$AMR" ]]; then
            PLACE_ARGS=()
            [[ -s "$BINS" ]] && binning_capable "$TOOL" && PLACE_ARGS+=(--bins "$BINS")
            [[ -s "$FEATURES" ]] && PLACE_ARGS+=(--features "$FEATURES")
            python3 "$PY/score_amr_placement.py" score --sample "$SAMPLE" --tool "$TOOL" --truth "$TRUTH" \
                --amr-truth "$AMR" --paf "$PAF" --pred-fasta "$PRED" "${PLACE_ARGS[@]+"${PLACE_ARGS[@]}"}" \
                --out "$SDIR/${TOOL}.amr_placement.tsv" 2>/dev/null
        fi
    done
    shopt -u nullglob
    # Stage 2 equivalent: every replicon under the three labelling schemes.
    python3 "$PY/label_schemes.py" build --sample "$SAMPLE" --truth "$TRUTH" --truth-source demo_synthetic \
        --nonchromosomal-out "$SDIR/truth.nonchromosomal.tsv" --out "$SDIR/label_schemes.tsv" 2>/dev/null

    # Truth QC and the contig-layer additions (same scripts as stages 2 and 5). The contig-dependent ones run only when the
    # demo carries an assembly with contig labels; otherwise their report sections say "Not run".
    python3 "$PY/repeat_content.py" --reference "$SDIR/reference.fna" --truth "$TRUTH" --sample "$SAMPLE" \
        --out "$SDIR/truth_repeat_content.tsv" 2>/dev/null || true
    if [[ -s "$SDIR/contig_labels.tsv" ]]; then
        for BINS_FILE in "$SDIR"/pred_*.bins.tsv; do
            [[ -f "$BINS_FILE" ]] || continue
            TOOL_NAME="$(basename "$BINS_FILE" .bins.tsv)"; TOOL_NAME="${TOOL_NAME#pred_}"
            python3 "$PY/bin_agreement.py" eval --labels "$SDIR/contig_labels.tsv" --bins "$BINS_FILE" --sample "$SAMPLE" \
                --tool "$TOOL_NAME" --out "$SDIR/${TOOL_NAME}.bestmatch.tsv" 2>/dev/null || true
            python3 "$PY/bin_agreement.py" dissim --labels "$SDIR/contig_labels.tsv" --bins "$BINS_FILE" --sample "$SAMPLE" \
                --tool "$TOOL_NAME" --out "$SDIR/${TOOL_NAME}.dissim.tsv" 2>/dev/null || true
        done
    fi
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
python3 "$PY/contig_classification.py" merge --scores "$SCORES" --results-dir "$DEMO"
python3 "$PY/bin_agreement.py" merge --scores "$SCORES" --results-dir "$DEMO"

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
python3 "$PY/power_analysis.py" --scores "$SCORES" --sample-sheet "$SAMPLES" --leaderboard "$DEMO/benchmark.leaderboard.tsv" --out "$DIM.power.tsv"
python3 "$PY/scenario_tags.py" --scores "$SCORES" --data-dir "$DEMO" --sample-sheet "$SAMPLES" \
    --out "$DIM.scenarios.tsv" --performance-out "$DIM.scenario_performance.tsv"
python3 "$PY/composite_score.py" --scores "$SCORES" --accuracy "$DIM.accuracy.tsv" \
    --feature-preservation "$DIM.feature_preservation.tsv" --ngoc "$DIM.ngoc.tsv" \
    --bin-quality "$DIM.bin_quality.tsv" --performance "$DIM.performance.tsv" \
    --out "$DIM.composite.tsv" --sensitivity-out "$DIM.composite_sensitivity.tsv"

python3 "$PY/validate_recommendations.py" --scores "$SCORES" --samples "$SAMPLES" \
    --out "$DEMO/benchmark.recommendation_validation.tsv" --min-train-samples 1
# Evaluation additions learned from PlasEval, plsMD and GAEMR, same scripts as stage 6 (each says "Not run" without its input).
python3 "$PY/repeat_content.py" summary --data-dir "$DEMO" --out "$DEMO/benchmark.repeat_content.tsv" || true
python3 "$PY/assembly_adequacy.py" merge --data-dir "$DEMO" --out "$DEMO/benchmark.assembly_adequacy.tsv" || true
python3 "$PY/copy_number.py" merge --results-dir "$DEMO" --out "$DEMO/benchmark.copy_number.tsv" || true
python3 "$PY/bin_agreement.py" matrix --results-dir "$DEMO" --data-dir "$DEMO" --out "$DEMO/benchmark.tool_agreement.tsv" || true
# Scoring specification layers, same scripts as stage 6.
python3 "$PY/label_schemes.py" collect --data-dir "$DEMO" --out "$DEMO/benchmark.label_schemes.tsv" \
    --summary-out "$DEMO/benchmark.label_scheme_summary.tsv"
python3 "$PY/truth_provenance.py" --sample-sheet "$SAMPLES" --data-dir "$DEMO" \
    --out "$DEMO/benchmark.truth_provenance.tsv" >/dev/null
python3 "$PY/score_amr_placement.py" collect --results-dir "$DEMO" --out "$DEMO/benchmark.amr_placement.tsv"
python3 "$PY/evaluate_recommender.py" --scores "$SCORES" --samples "$SAMPLES" --tool-status "$STATUS" \
    --out-prefix "$DEMO/benchmark" --min-train-samples 1
python3 "$PY/flag_cohort_outliers.py" --stats-dir "$DEMO" --samples "$SAMPLES" \
    --out "$DEMO/benchmark.cohort_qc_flags.tsv"
python3 "$PY/assembly_qc_gate.py" --data-dir "$DEMO" --out "$DEMO/benchmark.assembly_qc.tsv" 2>/dev/null
python3 "$PY/evaluate_warnings.py" --regret "$DEMO/benchmark.recommender_regret.tsv" \
    --cohort-qc-flags "$DEMO/benchmark.cohort_qc_flags.tsv" --assembly-qc "$DEMO/benchmark.assembly_qc.tsv" \
    --out-prefix "$DEMO/benchmark"
python3 "$PY/contig_crosscheck.py" compare --results-dir "$DEMO" --data-dir "$DEMO" \
    --out "$DEMO/benchmark.contig_crosscheck.tsv"
python3 "$PY/leave_taxon_out.py" --scores "$SCORES" --samples "$SAMPLES" --tool-status "$STATUS" \
    --out-prefix "$DEMO/benchmark" --min-train-samples 1
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
    --data-dir "$DEMO" \
    --label-schemes "$DEMO/benchmark.label_schemes.tsv" \
    --label-scheme-summary "$DEMO/benchmark.label_scheme_summary.tsv" \
    --truth-provenance "$DEMO/benchmark.truth_provenance.tsv" \
    --outcome-states "$DEMO/benchmark.outcome_states.tsv" \
    --recommender-eval "$DEMO/benchmark.recommender_eval.tsv" \
    --recommender-verdict "$DEMO/benchmark.recommender_verdict.json" \
    --warning-eval "$DEMO/benchmark.warning_eval.tsv" \
    --leave-taxon-out "$DEMO/benchmark.leave_taxon_out.tsv" \
    --amr-placement "$DEMO/benchmark.amr_placement.tsv" \
    --contig-crosscheck "$DEMO/benchmark.contig_crosscheck.tsv" \
    --embed-dashboard \
    --out "$DEMO/benchmark.report.html"

# Every generated demo report replaces the sample report in the repository (docs/sample_report/); it is skipped, with a printed reason, when that folder is absent,
# PLASBENCH_SAMPLE_REPORT=0, or the report is incomplete or holds a local path. It never fails the demo.
python3 "$PY/refresh_sample_report.py" --project-root "$ROOT" || true

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
