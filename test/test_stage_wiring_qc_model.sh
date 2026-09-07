#!/usr/bin/env bash
# Regression: the cohort-QC and recommendation-model features must actually be
# INVOKED by the stage scripts, not merely exist as standalone Python.
#
# Their units were well covered from the start, but nothing executed the code
# that calls them: test_run_all_default_stages.sh replaces every stage with a
# stub (it checks ordering), and test/run_demo.sh calls aggregate_results.py
# directly, bypassing scripts/06_aggregate.sh entirely. So the stage-2 stats
# block, the stage-6 flagger and fitter blocks, their config gates, and the
# --cohort-qc-flags passthrough to the report had no executing test at all.
# This runs the real scripts.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/tmp"
# GGGCCCATAT is exactly 6 G/C in 10 bases, so the expected GC% is exactly 60.
{
    printf '>chr1 chromosome\n'
    for _ in $(seq 1 20); do printf 'GGGCCCATAT\n'; done
    printf '>p1 plasmid\n'
    for _ in $(seq 1 5); do printf 'GGGCCCATAT\n'; done
} > "$TMP/data/s1/reference.fna"
printf 'sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t200\np1\tPLASMID\t50\n' > "$TMP/data/s1/truth.tsv"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"

truth_stage() {
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
        RUN_REFERENCE_ANNOTATION=0 bash "$ROOT/scripts/02_truth.sh" > "$1" 2>&1
}

aggregate() {
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
        "$@" bash "$ROOT/scripts/06_aggregate.sh" > "$TMP/stage6.log" 2>&1
}

# --- stage 2 must compute assembly stats -------------------------------------
truth_stage "$TMP/stage2.log" || { echo "FAIL: stage 2 did not complete" >&2; cat "$TMP/stage2.log" >&2; exit 1; }

STATS="$TMP/data/s1/assembly_stats.tsv"
[[ -s "$STATS" ]] || { echo "FAIL: stage 2 did not produce assembly_stats.tsv" >&2; cat "$TMP/stage2.log" >&2; exit 1; }
echo "stage 2 invokes compute_assembly_stats.py and writes assembly_stats.tsv -> PASS"

gc="$(awk -F'\t' 'NR==2 {print $5}' "$STATS")"
[[ "${gc%%.*}" -eq 60 ]] || { echo "FAIL: expected 60% GC from this fixture, got '$gc'" >&2; cat "$STATS" >&2; exit 1; }
plasmids="$(awk -F'\t' 'NR==2 {print $6}' "$STATS")"
[[ "$plasmids" -eq 1 ]] || { echo "FAIL: expected 1 plasmid from truth.tsv, got '$plasmids'" >&2; cat "$STATS" >&2; exit 1; }
echo "the stats are computed from the real reference (60% GC, 1 plasmid) -> PASS"

# Resumability: a second pass must reuse rather than recompute.
truth_stage "$TMP/stage2b.log"
grep -q "assembly stats already computed" "$TMP/stage2b.log" || {
    echo "FAIL: stage 2 recomputed stats that were already current" >&2; cat "$TMP/stage2b.log" >&2; exit 1; }
echo "stage 2 reuses current stats instead of recomputing -> PASS"

# --- stage 6 must run the flagger and honour its gate ------------------------
SCORE_HEADER='sample\ttool\tanalysis_track\ttrue_plasmid_bp\tTP_bp\tFP_bp\tFN_bp\tmapped_pred_bp\tunambiguously_mapped_pred_bp\tunmapped_pred_bp\toff_truth_pred_bp\tambiguously_mapped_pred_bp\ttrue_plasmid_count\trecovered_plasmid_count\tplasmid_recall\tpredicted_record_count\ttrue_amr_gene_count\trecovered_amr_gene_count\tamr_gene_recall\ttrue_circular_plasmid_count\trecovered_circular_plasmid_count\tcircular_truth_plasmid_recovery\tcircular_plasmid_recall\talignment_total\talignment_retained\tfiltered_alignment_count\tprecision\trecall\tf1\n'
SCORE_ROW='s1\ttoolA\tshort_read\t50\t45\t0\t5\t45\t45\t0\t0\t0\t1\t1\t0.9\t1\t0\t0\t0\t0\t0\t0\t0\t1\t1\t0\t0.9\t0.9\t0.9\n'
printf "$SCORE_HEADER" > "$TMP/results/scores.tsv"
printf "$SCORE_ROW" >> "$TMP/results/scores.tsv"
printf 'sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\ns1\ttoolA\tcompleted\tp.fasta\t\t1\t1000\n' > "$TMP/results/tool_status.tsv"

FLAGS="$TMP/results/benchmark.cohort_qc_flags.tsv"
rm -f "$FLAGS"
aggregate env COHORT_QC_FLAGS_ENABLED=1 || { echo "FAIL: stage 6 did not complete" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
[[ -s "$FLAGS" ]] || { echo "FAIL: stage 6 did not produce benchmark.cohort_qc_flags.tsv" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
echo "stage 6 invokes flag_cohort_outliers.py and writes the advisory table -> PASS"

grep -q "required for outlier detection" "$FLAGS" || {
    echo "FAIL: a 1-sample cohort must withhold, not report outliers" >&2; cat "$FLAGS" >&2; exit 1; }
echo "a cohort below the minimum withholds instead of guessing -> PASS"

rm -f "$FLAGS"
aggregate env COHORT_QC_FLAGS_ENABLED=0 || { echo "FAIL: stage 6 failed with QC disabled" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
[[ ! -e "$FLAGS" ]] || { echo "FAIL: COHORT_QC_FLAGS_ENABLED=0 still produced the flags file" >&2; exit 1; }
echo "COHORT_QC_FLAGS_ENABLED=0 is honoured by the stage script -> PASS"

# --- the report must actually receive the flags ------------------------------
aggregate env COHORT_QC_FLAGS_ENABLED=1
REPORT="$TMP/results/benchmark.report.html"
[[ -s "$REPORT" ]] || { echo "FAIL: stage 6 produced no HTML report" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
grep -q "cohort-qc" "$REPORT" || { echo "FAIL: the report has no cohort QC section" >&2; exit 1; }
grep -q "Advisory only" "$REPORT" || { echo "FAIL: the QC section lost its advisory caveat" >&2; exit 1; }
# The section renders whether or not the file was passed, so those two greps
# alone cannot detect a dropped --cohort-qc-flags. Assert on content that can
# ONLY come from the file itself: the flagger's own withholding note, and the
# absence of the "no file available" placeholder.
grep -q "required for outlier detection" "$REPORT" || {
    echo "FAIL: the report did not receive the flags file (its content is absent)" >&2
    grep -o "No cohort QC flags file was available[^<]*" "$REPORT" >&2 || true
    exit 1; }
grep -q "No cohort QC flags file was available" "$REPORT" && {
    echo "FAIL: the report says no flags file was available, but stage 6 wrote one" >&2; exit 1; }
echo "stage 6 passes --cohort-qc-flags through and the report renders its content -> PASS"

# --- the model gate must not be faked on a tiny cohort -----------------------
MODEL="$TMP/results/benchmark.recommendation_model.json"
MODEL_CARD="$TMP/results/benchmark.recommendation_model.card.md"
rm -f "$MODEL" "$MODEL_CARD"
aggregate env RUN_RECOMMENDATION_MODEL=1 || { echo "FAIL: stage 6 failed with the model enabled" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
[[ -s "$MODEL" ]] || { echo "FAIL: RUN_RECOMMENDATION_MODEL=1 produced no model JSON" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
[[ -s "$MODEL_CARD" ]] || { echo "FAIL: RUN_RECOMMENDATION_MODEL=1 produced no model card" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
python3 - "$MODEL" <<'PYEOF' || { echo "FAIL: the model gate was satisfied on data that cannot support it" >&2; exit 1; }
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["model_ready"] is False, "a 1-sample, 1-study cohort must never be model_ready"
assert "source_study" in payload["reason"] or "training row" in payload["reason"], payload["reason"]
PYEOF
grep -q "Model ready:\*\* no" "$MODEL_CARD" || { echo "FAIL: model card does not disclose the withheld model" >&2; exit 1; }
echo "RUN_RECOMMENDATION_MODEL=1 fits, writes a card, withholds on insufficient data, and says why -> PASS"

rm -f "$MODEL" "$MODEL_CARD"
aggregate env RUN_RECOMMENDATION_MODEL=0 || { echo "FAIL: stage 6 failed with the model disabled" >&2; cat "$TMP/stage6.log" >&2; exit 1; }
[[ ! -e "$MODEL" ]] || { echo "FAIL: RUN_RECOMMENDATION_MODEL=0 still fitted a model" >&2; exit 1; }
[[ ! -e "$MODEL_CARD" ]] || { echo "FAIL: RUN_RECOMMENDATION_MODEL=0 still wrote a model card" >&2; exit 1; }
echo "RUN_RECOMMENDATION_MODEL=0 fits nothing -> PASS"

echo "ALL STAGE WIRING (QC + MODEL) TESTS PASSED"
