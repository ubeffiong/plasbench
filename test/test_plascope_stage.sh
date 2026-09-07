#!/usr/bin/env bash
# Regression for run_plascope() in scripts/04_run_tools.sh: RUN_PLASCOPE=1
# actually invokes `plaScope.sh` with the right arguments for a supported
# organism (E. coli/Klebsiella), records a completed status with a real
# prediction, skips cleanly with a DISTINCT "no PlaScope database for
# organism <X>" reason for every other organism (the tool's defining
# constraint -- never conflated with a generic "command unavailable" skip),
# and skips cleanly (not a stage failure) when the binary itself is missing.
# Adapter correctness itself is covered separately by
# test_plascope_adapter.sh; this test is about the stage-4 wiring
# (tool_enabled gate, species gate via sample_column(), ADAPT invocation,
# tool_status.tsv, hardcoded merge list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/data/s2" "$TMP/results" "$TMP/logs"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '>c1\nACGTACGT\n' > "$TMP/data/s2/contigs.fasta"

cat > "$TMP/bin/plaScope.sh" <<'EOS'
#!/usr/bin/env bash
echo "plaScope.sh $*" >> "$PLASCOPE_CALLS_LOG"
fasta="" out="" sample="" db_dir="" db_name="" assembler=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fasta) fasta="$2"; shift 2 ;;
        -a) assembler="$2"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        --sample) sample="$2"; shift 2 ;;
        --db_dir) db_dir="$2"; shift 2 ;;
        --db_name) db_name="$2"; shift 2 ;;
        -t) shift 2 ;;
        *) shift ;;
    esac
done
pred_dir="$out/${sample}_PlaScope/PlaScope_predictions"
if [[ -d "$out/${sample}_PlaScope" ]]; then
    echo "plaScope.sh: refusing to run -- ${sample}_PlaScope already exists" >&2
    exit 1
fi
mkdir -p "$pred_dir" "$out/${sample}_PlaScope/Centrifuge_results"
printf '>c1\nACGTACGT\n' > "$pred_dir/${sample}_plasmid.fasta"
EOS
chmod +x "$TMP/bin/plaScope.sh"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_RFPLASMID=0 RUN_PLASGRAPH2=0 \
    PLASCOPE_CALLS_LOG="$TMP/plascope_calls.log" \
    PLASCOPE_ECOLI_DB="$TMP/db/ecoli/chromosome_plasmid_db" PLASCOPE_KLEBSIELLA_DB="$TMP/db/klebsiella/Klebsiella_PlaScope" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <sample> <column-index>
    awk -F'\t' -v s="$1" -v c="$2" '$1==s && $2=="plascope" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tGCF_1\tSRR1\tEscherichia coli\ns2\tGCF_2\tSRR2\tStaphylococcus aureus\n' > "$TMP/sheet.tsv"

: > "$TMP/plascope_calls.log"
run_stage env RUN_PLASCOPE=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }

grep -q -- "--db_name chromosome_plasmid_db" "$TMP/plascope_calls.log" || { echo "FAIL: expected s1's E. coli DB name to be passed" >&2; cat "$TMP/plascope_calls.log" >&2; exit 1; }
[[ "$(status_field s1 3)" == "completed" ]] || { echo "FAIL: expected s1 (E. coli) completed, got: $(status_field s1 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plascope.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file for s1" >&2; exit 1; }
echo "RUN_PLASCOPE=1 with organism=Escherichia coli invokes plaScope.sh with the E. coli DB and records a completed prediction -> PASS"

[[ "$(status_field s2 3)" == "skipped" ]] || { echo "FAIL: expected s2 (Staphylococcus aureus) skipped, got: $(status_field s2 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field s2 5 | grep -qi "no PlaScope database for organism Staphylococcus aureus" || { echo "FAIL: expected a distinct 'no PlaScope database for organism' reason for s2, got: $(status_field s2 5)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
echo "an unsupported organism skips with a distinct 'no PlaScope database for organism <X>' reason (not 'command unavailable') -> PASS"

# Missing binary skips cleanly, not a stage failure -- distinct from the
# species-gate skip reason above.
run_stage env RUN_PLASCOPE=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when plaScope.sh is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field s1 3)" == "skipped" ]] || { echo "FAIL: expected skipped when plaScope.sh is missing, got: $(status_field s1 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field s1 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_PLASCOPE=1 with plaScope.sh missing skips cleanly (not a stage failure) -> PASS"

echo "ALL PLASCOPE STAGE TESTS PASSED"
