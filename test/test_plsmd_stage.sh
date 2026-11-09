#!/usr/bin/env bash
# plsMD in stage 4, with a fake `plsMD` binary (offline). The real tool needs Docker and a PLSDB index.
#   enabled, Unicycler assembly, database set  -> completed; pred_plsmd.plasmid.fasta and one bin per record
#   ASSEMBLER=spades                            -> skipped with the reason "not from Unicycler" (not a failure)
#   PLSMD_DB unset                              -> skipped with the reason "PLSMD_DB not set"
#   the fake exits non-zero                     -> failed (a tool failure, scored 0)
#   RUN_PLSMD=0 (default)                       -> no plsmd row at all
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'if [ -n "${KEEP:-}" ]; then echo "kept:$TMP"; else rm -rf "$TMP"; fi' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/config" "$TMP/db"
touch "$TMP/db/plsdb.nhr"

cat > "$TMP/bin/plsMD" <<'EOF'
#!/usr/bin/env bash
mode="$1"; shift
dir=""; out=""
while [[ $# -gt 0 ]]; do case "$1" in --dir) dir="$2"; shift 2;; --output) out="$2"; shift 2;; *) shift;; esac; done
[[ "${FAKE_PLSMD_FAIL:-0}" == "1" ]] && exit 1
mkdir -p "$out"
if [[ "$mode" == "--processing" ]]; then
    mkdir -p "$out/plasmid_files"
    printf '>s1_plsMD1\nACGTACGTACGTACGT\n>s1_plsMD2\nACGTACGTAC\n' > "$out/plasmid_files/s1_plasmid_contigs.fasta"
fi
EOF
chmod +x "$TMP/bin/plsMD"

printf '>NODE_1 length=12 depth=1.0x circular=true\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

run_stage() {   # extra environment assignments as arguments
    rm -rf "$TMP/results" "$TMP/logs"
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_BASELINE_COVERAGE=0 \
        RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 "$@" PATH="$TMP/bin:$PATH" \
        bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || {
        echo "FAIL: stage 4 must finish" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }
}
STATUS="$TMP/results/tool_status.tsv"
col() { awk -F'\t' -v t="plsmd" -v c="$1" '$2==t {print $c}' "$STATUS"; }

run_stage RUN_PLSMD=1 ASSEMBLER=unicycler PLSMD_DB="$TMP/db/plsdb"
[[ "$(col 3)" == "completed" ]] || { echo "FAIL: plsmd should have completed" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(grep -c '^>' "$TMP/results/s1/pred_plsmd.plasmid.fasta")" == "2" ]] || { echo "FAIL: two reconstructed records expected" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/results/s1/pred_plsmd.bins.tsv" | wc -l | tr -d ' ')" == "2" ]] || { echo "FAIL: one bin per record expected" >&2; exit 1; }
echo "plsMD completes and yields one bin per reconstructed plasmid -> PASS"

run_stage RUN_PLSMD=1 ASSEMBLER=spades PLSMD_DB="$TMP/db/plsdb"
[[ "$(col 3)" == "skipped" && "$(col 5)" == *"Unicycler"* ]] || { echo "FAIL: SPAdes assembly should skip with a reason" >&2; cat "$STATUS" >&2; exit 1; }
echo "a SPAdes assembly is a skip with the reason, not a failure -> PASS"

run_stage RUN_PLSMD=1 ASSEMBLER=unicycler PLSMD_DB=
[[ "$(col 3)" == "skipped" && "$(col 5)" == *"PLSMD_DB"* ]] || { echo "FAIL: missing database should skip" >&2; cat "$STATUS" >&2; exit 1; }
echo "a missing PLSDB index is a skip with the reason -> PASS"

run_stage RUN_PLSMD=1 ASSEMBLER=unicycler PLSMD_DB="$TMP/db/plsdb" FAKE_PLSMD_FAIL=1 TOOL_RETRIES=0
[[ "$(col 3)" == "failed" ]] || { echo "FAIL: a crashing plsMD should be failed" >&2; cat "$STATUS" >&2; exit 1; }
echo "a crashing plsMD is a tool failure -> PASS"

run_stage RUN_PLSMD=0
[[ -z "$(col 3)" ]] || { echo "FAIL: RUN_PLSMD=0 must record no plsmd row" >&2; cat "$STATUS" >&2; exit 1; }
echo "RUN_PLSMD=0 records nothing -> PASS"
echo "ALL PLSMD STAGE TESTS PASSED"
