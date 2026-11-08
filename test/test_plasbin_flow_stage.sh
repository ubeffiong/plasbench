#!/usr/bin/env bash
# PlasBin-flow in stage 4 (offline): PlasBench adapts the tool's own output file.
#   RUN_PLASBIN_FLOW=1, output present, ids from this assembly -> completed; one bin per PlasBin-flow plasmid
#   PLASBIN_FLOW_OUTPUTS_DIR unset                               -> skipped with the reason
#   output file missing for the sample                           -> skipped with the reason
#   output naming a contig this assembly does not have           -> skipped (an incompatible input, not a tool failure)
#   an empty output (PlasBin-flow found no plasmid)              -> completed with an empty prediction
#   RUN_PLASBIN_FLOW=0 (default)                                 -> no plasbin_flow row
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/data/s1" "$TMP/config" "$TMP/pbf"
printf '>c1\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"
printf '#Pls_ID\tFlow\tGC_bin\tContigs\nP1\t2.5\t3\tc1:2,c2:1\nP2\t1.0\t2\tc3:1\n' > "$TMP/pbf/s1.tsv"

run_stage() {
    rm -rf "$TMP/results" "$TMP/logs"
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_BASELINE_COVERAGE=0 \
        RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 RUN_PLSMD=0 "$@" \
        bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || {
        echo "FAIL: stage 4 must finish" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }
}
STATUS="$TMP/results/tool_status.tsv"
col() { awk -F'\t' -v c="$1" '$2=="plasbin_flow" {print $c}' "$STATUS"; }

run_stage RUN_PLASBIN_FLOW=1 PLASBIN_FLOW_OUTPUTS_DIR="$TMP/pbf"
[[ "$(col 3)" == "completed" ]] || { echo "FAIL: should have completed" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(grep -c '^>' "$TMP/results/s1/pred_plasbin_flow.plasmid.fasta")" == "3" ]] || { echo "FAIL: three contigs expected" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/results/s1/pred_plasbin_flow.bins.tsv" | cut -f1 | sort -u | tr '\n' ' ')" == "P1 P2 " ]] || { echo "FAIL: bins P1 and P2 expected" >&2; exit 1; }
echo "PlasBin-flow output is adapted into bins P1 and P2 -> PASS"

run_stage RUN_PLASBIN_FLOW=1
[[ "$(col 3)" == "skipped" && "$(col 5)" == *"PLASBIN_FLOW_OUTPUTS_DIR"* ]] || { echo "FAIL: unset directory should skip" >&2; cat "$STATUS" >&2; exit 1; }
echo "an unset outputs directory is a skip with the reason -> PASS"

mkdir -p "$TMP/empty"
run_stage RUN_PLASBIN_FLOW=1 PLASBIN_FLOW_OUTPUTS_DIR="$TMP/empty"
[[ "$(col 3)" == "skipped" && "$(col 5)" == *"not found"* ]] || { echo "FAIL: missing file should skip" >&2; cat "$STATUS" >&2; exit 1; }
echo "a missing output file is a skip with the reason -> PASS"

mkdir -p "$TMP/other"
printf '#Pls_ID\tFlow\tGC_bin\tContigs\nP1\t2.5\t3\tnode_99:1\n' > "$TMP/other/s1.tsv"
run_stage RUN_PLASBIN_FLOW=1 PLASBIN_FLOW_OUTPUTS_DIR="$TMP/other"
[[ "$(col 3)" == "skipped" && "$(col 5)" == *"unusable"* ]] || { echo "FAIL: foreign ids should skip" >&2; cat "$STATUS" >&2; exit 1; }
echo "an output from another assembly is a skip, not a failure -> PASS"

mkdir -p "$TMP/none"
printf '#Pls_ID\tFlow\tGC_bin\tContigs\n' > "$TMP/none/s1.tsv"
run_stage RUN_PLASBIN_FLOW=1 PLASBIN_FLOW_OUTPUTS_DIR="$TMP/none"
[[ "$(col 3)" == "completed" ]] || { echo "FAIL: an empty prediction is a completed run" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(grep -c '^>' "$TMP/results/s1/pred_plasbin_flow.plasmid.fasta" || true)" == "0" ]] || { echo "FAIL: empty FASTA expected" >&2; exit 1; }
echo "PlasBin-flow finding no plasmid is a completed empty prediction -> PASS"

run_stage RUN_PLASBIN_FLOW=0 PLASBIN_FLOW_OUTPUTS_DIR="$TMP/pbf"
[[ -z "$(col 3)" ]] || { echo "FAIL: RUN_PLASBIN_FLOW=0 must record nothing" >&2; cat "$STATUS" >&2; exit 1; }
echo "RUN_PLASBIN_FLOW=0 records nothing -> PASS"
echo "ALL PLASBIN-FLOW STAGE TESTS PASSED"
