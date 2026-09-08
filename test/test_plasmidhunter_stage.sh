#!/usr/bin/env bash
# Regression for run_plasmidhunter() in scripts/04_run_tools.sh:
# RUN_PLASMIDHUNTER=1 actually invokes `plasmidhunter -i <fasta> -o <dir>
# -c <cpu>` (a single-file input, like PLASMe -- simpler than RFPlasmid's
# directory-of-fasta requirement), records a completed status with a real
# prediction, and skips cleanly (not a stage failure) when the binary is
# missing. Also asserts run_plasmidhunter() never pre-creates its -o
# directory itself, since real PlasmidHunter errors if it already exists.
# Adapter correctness itself is covered separately by
# test_plasmidhunter_adapter.sh; this test is about the stage-4 wiring
# (tool_enabled gate, ADAPT invocation, tool_status.tsv, hardcoded merge
# list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/plasmidhunter" <<'EOS'
#!/usr/bin/env bash
echo "plasmidhunter $*" >> "$PLASMIDHUNTER_CALLS_LOG"
infile="" outdir="" cpu=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i) infile="$2"; shift 2 ;;
        -o) outdir="$2"; shift 2 ;;
        -c) cpu="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [[ -d "$outdir" ]]; then
    echo "plasmidhunter: refusing to run -- $outdir already exists" >&2
    exit 1
fi
[[ -s "$infile" ]] || { echo "plasmidhunter: input fasta missing: $infile" >&2; exit 1; }
mkdir -p "$outdir"
{
    printf '\tPrediction (0: chromosome, 1: plasmid)\tProbability of 0\tProbability of 1\n'
    printf 'c1\t1.0\t0.10\t0.90\n'
} > "$outdir/predictions.tsv"
EOS
chmod +x "$TMP/bin/plasmidhunter"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_RFPLASMID=0 RUN_PLASCOPE=0 RUN_PLASGRAPH2=0 \
    PLASMIDHUNTER_CALLS_LOG="$TMP/plasmidhunter_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="plasmidhunter" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/plasmidhunter_calls.log"
run_stage env RUN_PLASMIDHUNTER=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "-i " "$TMP/plasmidhunter_calls.log" || { echo "FAIL: expected plasmidhunter to be called with -i" >&2; cat "$TMP/plasmidhunter_calls.log" >&2; exit 1; }
grep -q -- "-c " "$TMP/plasmidhunter_calls.log" || { echo "FAIL: expected plasmidhunter to be called with -c" >&2; cat "$TMP/plasmidhunter_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmidhunter.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmidhunter.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasmidhunter.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
echo "RUN_PLASMIDHUNTER=1 invokes plasmidhunter and records a completed prediction with scores/candidates -> PASS"

# Missing binary skips cleanly, not a stage failure.
run_stage env RUN_PLASMIDHUNTER=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when plasmidhunter is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when plasmidhunter is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_PLASMIDHUNTER=1 with plasmidhunter missing skips cleanly (not a stage failure) -> PASS"

echo "ALL PLASMIDHUNTER STAGE TESTS PASSED"
