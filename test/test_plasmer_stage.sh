#!/usr/bin/env bash
# Regression for run_plasmer() in scripts/04_run_tools.sh: RUN_PLASMER=1
# actually invokes `Plasmer -g <fasta> -p <sample> -d <db> -t <threads>
# -m <min_length> -l <length> -o <dir>`, records a completed status with a
# real prediction, skips cleanly (a structural "no database" skip, not a
# stage failure) when PLASMER_DB does not exist, and skips cleanly when the
# binary is missing. Adapter correctness itself is covered separately by
# test_plasmer_adapter.sh; this test is about the stage-4 wiring
# (tool_enabled gate, database gate, ADAPT invocation, tool_status.tsv,
# hardcoded merge list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/db"
touch "$TMP/db/placeholder"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/Plasmer" <<'EOS'
#!/usr/bin/env bash
echo "Plasmer $*" >> "$PLASMER_CALLS_LOG"
genome="" prefix="" db="" outpath=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -g) genome="$2"; shift 2 ;;
        -p) prefix="$2"; shift 2 ;;
        -d) db="$2"; shift 2 ;;
        -o) outpath="$2"; shift 2 ;;
        -t|-m|-l) shift 2 ;;
        *) shift ;;
    esac
done
[[ -s "$genome" ]] || { echo "Plasmer: input fasta missing: $genome" >&2; exit 1; }
[[ -d "$db" ]] || { echo "Plasmer: database missing: $db" >&2; exit 1; }
mkdir -p "$outpath/results"
printf '>c1\nACGTACGT\n' > "$outpath/results/${prefix}.plasmer.predPlasmids.fa"
{
    printf 'Contig\tchromosome\tplasmid\n'
    printf 'c1\t0.10\t0.90\n'
} > "$outpath/results/${prefix}.plasmer.predProb.tsv"
EOS
chmod +x "$TMP/bin/Plasmer"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_RFPLASMID=0 RUN_PLASMIDHUNTER=0 RUN_PLASCOPE=0 RUN_PLASGRAPH2=0 \
    PLASMER_CALLS_LOG="$TMP/plasmer_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="plasmer" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/plasmer_calls.log"
run_stage env RUN_PLASMER=1 PLASMER_DB="$TMP/db" || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "-g " "$TMP/plasmer_calls.log" || { echo "FAIL: expected Plasmer to be called with -g" >&2; cat "$TMP/plasmer_calls.log" >&2; exit 1; }
grep -q -- "-d $TMP/db" "$TMP/plasmer_calls.log" || { echo "FAIL: expected Plasmer to be called with -d pointing at PLASMER_DB" >&2; cat "$TMP/plasmer_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmer.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmer.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmer.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
echo "RUN_PLASMER=1 with a real database invokes Plasmer and records a completed prediction with scores/candidates -> PASS"

# No database configured is a structural skip, distinct from "command unavailable".
run_stage env RUN_PLASMER=1 PLASMER_DB="$TMP/does_not_exist" || { echo "FAIL: stage should not abort when the Plasmer database is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when the database is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "no plasmer database" || { echo "FAIL: expected a 'no Plasmer database' reason" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
echo "RUN_PLASMER=1 with no database configured skips structurally (distinct from 'command unavailable') -> PASS"

# Missing binary skips cleanly, not a stage failure.
run_stage env RUN_PLASMER=1 PLASMER_DB="$TMP/db" PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when Plasmer is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when Plasmer is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_PLASMER=1 with Plasmer missing skips cleanly (not a stage failure) -> PASS"

echo "ALL PLASMER STAGE TESTS PASSED"
