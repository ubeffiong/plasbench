#!/usr/bin/env bash
# Regression for run_genomad() in scripts/04_run_tools.sh: RUN_GENOMAD=1
# actually invokes `genomad end-to-end` with the right arguments, records a
# completed status with a real prediction, and skips cleanly (not a stage
# failure) when the binary is missing. Adapter correctness itself is covered
# separately by test_genomad_adapter.sh; this test is about the stage-4
# wiring (tool_enabled gate, ADAPT invocation, tool_status.tsv, hardcoded
# merge list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/db/genomad_db"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/genomad" <<'EOS'
#!/usr/bin/env bash
echo "genomad $*" >> "$GENOMAD_CALLS_LOG"
sub="$1"; shift
[[ "$sub" == "end-to-end" ]] || { echo "unexpected subcommand: $sub" >&2; exit 1; }
# Parse: genomad end-to-end --threads N <contigs> <out_dir> <db_dir>
threads="" contigs="" out="" db=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --threads) threads="$2"; shift 2 ;;
        *) if [[ -z "$contigs" ]]; then contigs="$1"; elif [[ -z "$out" ]]; then out="$1"; else db="$1"; fi; shift ;;
    esac
done
mkdir -p "$out/sample_summary" "$out/sample_aggregated_classification"
printf '>c1\nACGTACGT\n' > "$out/sample_summary/sample_plasmid.fna"
printf 'seq_name\tplasmid_score\nc1\t0.9\n' > "$out/sample_aggregated_classification/sample_aggregated_classification.tsv"
EOS
chmod +x "$TMP/bin/genomad"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 \
    GENOMAD_DB="$TMP/db" GENOMAD_CALLS_LOG="$TMP/genomad_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="genomad" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/genomad_calls.log"
run_stage env RUN_GENOMAD=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "--threads" "$TMP/genomad_calls.log" || { echo "FAIL: expected genomad end-to-end to be called with --threads" >&2; cat "$TMP/genomad_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_genomad.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_genomad.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_genomad.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
echo "RUN_GENOMAD=1 invokes genomad end-to-end and records a completed prediction with scores/candidates -> PASS"

# Missing binary skips cleanly, not a stage failure.
run_stage env RUN_GENOMAD=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when genomad is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when genomad is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_GENOMAD=1 with genomad missing skips cleanly (not a stage failure) -> PASS"

echo "ALL GENOMAD STAGE TESTS PASSED"
