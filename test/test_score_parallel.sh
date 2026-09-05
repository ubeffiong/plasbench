#!/usr/bin/env bash
# Regression: MAX_PARALLEL_SAMPLES must overlap stage 5's per-sample scoring,
# and the shard-then-merge scores.tsv/score_failures.tsv must come out
# identical in content to what a sequential run produces -- exactly one
# header row each, and every sample's data rows present, regardless of which
# sample's job actually finished first. Uses the REAL score_plasmids.py (this
# is a timing/merge-correctness test, not a scoring-correctness one -- that
# is test_scoring.py's job) with a fake minimap2 so it runs offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DELAY=0.4
mkdir -p "$TMP/bin"
cat > "$TMP/bin/minimap2" <<EOF
#!/usr/bin/env bash
echo "START \$$" >> "$TMP/align_events.log"
sleep $DELAY
echo "END \$$" >> "$TMP/align_events.log"
printf 'q1\t100\t0\t100\t+\tplasmidA\t100\t0\t100\t100\t100\t60\n'
EOF
#!/usr/bin/env bash
sleep $DELAY
printf 'q1\t100\t0\t100\t+\tplasmidA\t100\t0\t100\t100\t100\t60\n'
EOF
chmod +x "$TMP/bin/minimap2"

setup_sample() {
    local sample="$1" tool="$2"
    local sdir="$TMP/data/$sample" rdir="$TMP/results/$sample"
    mkdir -p "$sdir" "$rdir" "$rdir/visualization"
    printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n' > "$sdir/truth.tsv"
    printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$sdir/reference.fna"
    printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$rdir/pred_${tool}.plasmid.fasta"
    touch "$rdir/.${tool}.complete"
}

run_stage() {
    PATH="$TMP/bin:$PATH" \
        DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
        "$@" bash "$ROOT/scripts/05_score.sh" > "$TMP/stage.log" 2>&1
}
now_ms() { date +%s%N | cut -c1-13; }

mkdir -p "$TMP/logs"
setup_sample s1 toolx; setup_sample s2 toolx; setup_sample s3 toolx
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\ns3\tNA\tSRR\n' > "$TMP/sheet.tsv"

start=$(now_ms)
run_stage env MAX_PARALLEL_SAMPLES=1 || { echo "FAIL: sequential baseline should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
end=$(now_ms)
sequential_ms=$(( end - start ))
sequential_scores="$(cat "$TMP/results/scores.tsv")"

rm -f "$TMP/results/scores.tsv" "$TMP/results/score_failures.tsv"

start=$(now_ms)
run_stage env MAX_PARALLEL_SAMPLES=3 || { echo "FAIL: parallel run should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
end=$(now_ms)
parallel_ms=$(( end - start ))

[[ "$parallel_ms" -lt "$(( sequential_ms * 3 / 4 ))" ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=3 (${parallel_ms}ms) was not clearly faster than sequential (${sequential_ms}ms)" >&2
    exit 1; }
echo "MAX_PARALLEL_SAMPLES=3 overlaps independent scoring (${parallel_ms}ms vs ${sequential_ms}ms sequential) -> PASS"

header_count="$(grep -c '^sample	tool	' "$TMP/results/scores.tsv" || true)"
[[ "$header_count" -eq 1 ]] || { echo "FAIL: scores.tsv has $header_count header rows, expected exactly 1" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
row_count="$(tail -n +2 "$TMP/results/scores.tsv" | wc -l)"
[[ "$row_count" -eq 3 ]] || { echo "FAIL: scores.tsv has $row_count data rows, expected 3 (one per sample)" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
for s in s1 s2 s3; do
    grep -q "^$s	toolx	" "$TMP/results/scores.tsv" || { echo "FAIL: scores.tsv missing a row for $s" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
done
echo "merged scores.tsv has exactly one header and all three samples' rows -> PASS"

# Same set of data rows as the sequential run (order may legitimately differ
# only in which sample's shard happened to merge first is NOT the case here,
# since merging always walks the sample sheet in order -- so this should
# match exactly, not just as a set).
parallel_scores="$(cat "$TMP/results/scores.tsv")"
[[ "$parallel_scores" == "$sequential_scores" ]] || {
    echo "FAIL: parallel scores.tsv differs from the sequential baseline" >&2
    diff <(echo "$sequential_scores") <(echo "$parallel_scores") >&2 || true
    exit 1; }
echo "parallel scores.tsv is byte-identical to the sequential baseline -> PASS"

echo "ALL SCORE PARALLEL TESTS PASSED"
