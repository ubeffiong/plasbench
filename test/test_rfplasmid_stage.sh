#!/usr/bin/env bash
# Regression for run_rfplasmid() in scripts/04_run_tools.sh: RUN_RFPLASMID=1
# actually invokes `rfplasmid` with a per-sample staged *.fasta directory
# (RFPlasmid's --input is a directory, not a single file, unlike
# geNomad/PLASMe), records a completed status with a real prediction, and
# skips cleanly (not a stage failure) when the binary is missing. Also
# asserts run_rfplasmid() never pre-creates its --out directory itself,
# since RFPlasmid silently appends a timestamp to --out when that path
# already exists. Adapter correctness itself is covered separately by
# test_rfplasmid_adapter.sh; this test is about the stage-4 wiring
# (tool_enabled gate, per-sample input staging, ADAPT invocation,
# tool_status.tsv, hardcoded merge list) around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/rfplasmid" <<'EOS'
#!/usr/bin/env bash
echo "rfplasmid $*" >> "$RFPLASMID_CALLS_LOG"
species="" input="" out="" threads="" jelly=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --species) species="$2"; shift 2 ;;
        --input) input="$2"; shift 2 ;;
        --out) out="$2"; shift 2 ;;
        --threads) threads="$2"; shift 2 ;;
        --jelly) jelly=1; shift ;;
        *) shift ;;
    esac
done
if [[ -d "$out" ]]; then
    echo "rfplasmid: refusing to run -- $out already exists (real RFPlasmid would silently timestamp-suffix it instead)" >&2
    exit 1
fi
fasta_count="$(find "$input" -maxdepth 1 -name '*.fasta' | wc -l | tr -d ' ')"
if [[ "$fasta_count" -ne 1 ]]; then
    echo "rfplasmid: expected exactly 1 staged *.fasta in --input, found $fasta_count" >&2
    exit 1
fi
mkdir -p "$out"
{
    printf '"","prediction","votes chromosomal","votes plasmid","contigID"\n'
    printf '"g_1","p",0.10,0.90,"c1"\n'
} > "$out/prediction.csv"
EOS
chmod +x "$TMP/bin/rfplasmid"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_PLASGRAPH2=0 \
    RFPLASMID_CALLS_LOG="$TMP/rfplasmid_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="rfplasmid" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/rfplasmid_calls.log"
run_stage env RUN_RFPLASMID=1 RFPLASMID_SPECIES=Generic || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "--species Generic" "$TMP/rfplasmid_calls.log" || { echo "FAIL: expected rfplasmid to be called with --species Generic" >&2; cat "$TMP/rfplasmid_calls.log" >&2; exit 1; }
grep -q -- "--input" "$TMP/rfplasmid_calls.log" || { echo "FAIL: expected rfplasmid to be called with --input" >&2; cat "$TMP/rfplasmid_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_rfplasmid.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_rfplasmid.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_rfplasmid.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
[[ ! -d "$TMP/results/s1/rfplasmid_input" ]] || { echo "FAIL: expected the per-sample staging directory to be cleaned up" >&2; exit 1; }
echo "RUN_RFPLASMID=1 stages a per-sample *.fasta dir, invokes rfplasmid, and records a completed prediction with scores/candidates -> PASS"

# Missing binary skips cleanly, not a stage failure.
run_stage env RUN_RFPLASMID=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when rfplasmid is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when rfplasmid is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_RFPLASMID=1 with rfplasmid missing skips cleanly (not a stage failure) -> PASS"

echo "ALL RFPLASMID STAGE TESTS PASSED"
