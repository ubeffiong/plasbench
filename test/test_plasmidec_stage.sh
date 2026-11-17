#!/usr/bin/env bash
# Regression for run_plasmidec() in scripts/04_run_tools.sh: RUN_PLASMIDEC=1 invokes plasmidEC.sh -i <x>.fasta -o <dir> -s "<species>" ...,
# records a completed prediction for a supported species, skips (recorded, not failed) an unsupported organism and a missing launcher,
# and records FAILED (not completed with an empty prediction) when the run writes no ensemble_output.csv.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/plasmidEC.sh" <<'EOS'
#!/usr/bin/env bash
echo "plasmidEC.sh $*" >> "$PLASMIDEC_CALLS_LOG"
input="" out="" species=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i) input="$2"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        -s) species="$2"; shift 2 ;;
        -t|-l|-c) shift 2 ;;
        *) shift ;;
    esac
done
[[ "$input" == *.fasta && -s "$input" ]] || { echo "plasmidEC: need a .fasta input" >&2; exit 1; }
[[ -n "$species" ]] || { echo "plasmidEC: species missing" >&2; exit 1; }
[[ "${PLASMIDEC_FAKE_CRASH:-0}" == 1 ]] && exit 0
mkdir -p "$out"
printf 'Contig_name,Genome_id,RFPlasmid,PlaScope,Platon,Plasmid_count,Combined_prediction\nc1,s,plasmid,plasmid,plasmid,3,plasmid\n' > "$out/ensemble_output.csv"
printf '>c1\nACGTACGT\n' > "$out/plasmid_contigs.fasta"
EOS
chmod +x "$TMP/bin/plasmidEC.sh"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_RFPLASMID=0 RUN_PLASMIDHUNTER=0 RUN_PLASCOPE=0 RUN_PLASGRAPH2=0 RUN_PLASMER=0 \
    PLASMIDEC_CALLS_LOG="$TMP/calls.log" "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}
status_field() { awk -F'\t' -v c="$1" '$1=="s1" && $2=="plasmidec" {print $c; exit}' "$TMP/results/tool_status.tsv"; }

printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tGCF_1\tSRR1\tKlebsiella pneumoniae subsp. pneumoniae\n' > "$TMP/sheet.tsv"
: > "$TMP/calls.log"
run_stage env RUN_PLASMIDEC=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- '-s Klebsiella pneumoniae' "$TMP/calls.log" || { echo "FAIL: expected -s Klebsiella pneumoniae" >&2; cat "$TMP/calls.log" >&2; exit 1; }
grep -q -- '-i .*s1.fasta' "$TMP/calls.log" || { echo "FAIL: expected a <sample>.fasta input" >&2; cat "$TMP/calls.log" >&2; exit 1; }
if [[ "$(status_field 3)" != "completed" || ! -s "$TMP/results/s1/pred_plasmidec.plasmid.fasta" ]]; then
    echo "FAIL: expected a completed prediction" >&2; cat "$TMP/results/tool_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
echo "RUN_PLASMIDEC=1 on a supported species invokes plasmidEC.sh and records a completed prediction -> PASS"

printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tGCF_1\tSRR1\tCitrobacter freundii\n' > "$TMP/sheet.tsv"
run_stage env RUN_PLASMIDEC=1 || { echo "FAIL: stage must not abort for an unsupported organism" >&2; exit 1; }
if [[ "$(status_field 3)" != "skipped" ]] || ! status_field 5 | grep -qi "no PlasmidEC model"; then
    echo "FAIL: expected a skipped status naming the missing model" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1
fi
echo "an organism PlasmidEC has no model for is skipped with a recorded reason -> PASS"

printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tGCF_1\tSRR1\tEscherichia coli\n' > "$TMP/sheet.tsv"
run_stage env RUN_PLASMIDEC=1 PLASMIDEC_FAKE_CRASH=1 || { echo "FAIL: stage must not abort when the tool produces nothing" >&2; exit 1; }
if [[ "$(status_field 3)" != "failed" || -e "$TMP/results/s1/pred_plasmidec.plasmid.fasta" ]]; then
    echo "FAIL: a run with no ensemble_output.csv must be failed, not completed" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1
fi
echo "a run that writes no ensemble_output.csv is recorded as failed, not as 'no plasmids' -> PASS"

run_stage env RUN_PLASMIDEC=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage must not abort when plasmidEC.sh is missing" >&2; exit 1; }
if [[ "$(status_field 3)" != "skipped" ]] || ! status_field 5 | grep -qi "command unavailable"; then
    echo "FAIL: expected skipped, command unavailable" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1
fi
echo "a missing plasmidEC.sh skips cleanly -> PASS"
echo "ALL PLASMIDEC STAGE TESTS PASSED"
