#!/usr/bin/env bash
# Regression for run_plasgraph2() in scripts/04_run_tools.sh: RUN_PLASGRAPH2=1
# actually gzips the assembly graph and invokes `plASgraph2_classify.py gfa
# <graph.gfa.gz> <model_dir> <output.csv>` with the right arguments, records a
# completed status with a real prediction, and skips cleanly (not a stage
# failure) when the binary/graph/model dir is missing. Adapter correctness
# itself is covered separately by test_plasgraph2_adapter.sh; this test is
# about the stage-4 wiring (tool_enabled gate, gzip step, ADAPT invocation,
# tool_status.tsv, hardcoded merge list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/model"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf 'H\tVN:Z:1.0\nS\tc1\tACGTACGT\n' > "$TMP/data/s1/assembly_graph.gfa"
: > "$TMP/model/.marker"

cat > "$TMP/bin/plASgraph2_classify.py" <<'EOS'
#!/usr/bin/env bash
echo "plASgraph2_classify.py $*" >> "$PLASGRAPH2_CALLS_LOG"
sub="$1"; shift
[[ "$sub" == "gfa" ]] || { echo "unexpected subcommand: $sub" >&2; exit 1; }
graph="$1"; model_dir="$2"; out_csv="$3"
[[ -s "$graph" ]] || { echo "graph not found: $graph" >&2; exit 1; }
[[ -d "$model_dir" ]] || { echo "model dir not found: $model_dir" >&2; exit 1; }
# Confirm the graph really is gzipped, not passed through as plain .gfa.
gzip -t "$graph" 2>/dev/null || { echo "expected a gzipped graph: $graph" >&2; exit 1; }
printf 'sample,contig,length,plasmid_score,chrom_score,label\n' > "$out_csv"
printf 'sample,c1,8,0.9,0.1,plasmid\n' >> "$out_csv"
EOS
chmod +x "$TMP/bin/plASgraph2_classify.py"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 \
    PLASGRAPH2_CALLS_LOG="$TMP/plasgraph2_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="plasgraph2" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/plasgraph2_calls.log"
run_stage env RUN_PLASGRAPH2=1 PLASGRAPH2_MODEL_DIR="$TMP/model" || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "gfa" "$TMP/plasgraph2_calls.log" || { echo "FAIL: expected plASgraph2_classify.py to be called with the gfa subcommand" >&2; cat "$TMP/plasgraph2_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasgraph2.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasgraph2.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasgraph2.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
echo "RUN_PLASGRAPH2=1 gzips the graph and invokes plASgraph2_classify.py, recording a completed prediction with scores/candidates -> PASS"

# Missing binary skips cleanly, not a stage failure.
run_stage env RUN_PLASGRAPH2=1 PLASGRAPH2_MODEL_DIR="$TMP/model" PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when plASgraph2_classify.py is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when the binary is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_PLASGRAPH2=1 with plASgraph2_classify.py missing skips cleanly (not a stage failure) -> PASS"

# Missing PLASGRAPH2_MODEL_DIR skips cleanly with a specific reason.
run_stage env RUN_PLASGRAPH2=1 PLASGRAPH2_MODEL_DIR="" || { echo "FAIL: stage should not abort when PLASGRAPH2_MODEL_DIR is unset" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when PLASGRAPH2_MODEL_DIR is unset, got: $(status_field 3)" >&2; exit 1; }
status_field 5 | grep -qi "PLASGRAPH2_MODEL_DIR" || { echo "FAIL: expected a PLASGRAPH2_MODEL_DIR-specific reason" >&2; exit 1; }
echo "missing PLASGRAPH2_MODEL_DIR skips cleanly with a specific reason -> PASS"

# Missing assembly graph skips cleanly with a specific reason.
mv "$TMP/data/s1/assembly_graph.gfa" "$TMP/data/s1/assembly_graph.gfa.bak"
run_stage env RUN_PLASGRAPH2=1 PLASGRAPH2_MODEL_DIR="$TMP/model" || { echo "FAIL: stage should not abort when the assembly graph is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when the assembly graph is missing, got: $(status_field 3)" >&2; exit 1; }
status_field 5 | grep -qi "assembly graph unavailable" || { echo "FAIL: expected an 'assembly graph unavailable' reason" >&2; exit 1; }
mv "$TMP/data/s1/assembly_graph.gfa.bak" "$TMP/data/s1/assembly_graph.gfa"
echo "missing assembly graph skips cleanly with a specific reason -> PASS"

echo "ALL PLASGRAPH2 STAGE TESTS PASSED"
