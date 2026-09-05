#!/usr/bin/env bash
# Regression for run_plasme() in scripts/04_run_tools.sh: RUN_PLASME=1
# actually invokes `PLASMe.py` with the right arguments (note: PLASMe is a
# bare-script tool expected on PATH as `PLASMe.py` after manual setup, the
# same convention this project already uses for gplas2 -- see
# env/install_tools.sh's plasme case), records a completed status with a
# real prediction, and skips cleanly (not a stage failure) when the script
# is missing. Adapter correctness itself is covered by
# test_plasme_adapter.sh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/db"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"

cat > "$TMP/bin/PLASMe.py" <<'EOS'
#!/usr/bin/env bash
echo "PLASMe.py $*" >> "$PLASME_CALLS_LOG"
contig="$1"; out="$2"; shift 2
printf '>c1\nACGTACGT\n' > "$out"
printf 'contig,length,reference,order,evidence,score,amb_region\nc1,8,ref1,1,transformer,0.9,no\n' > "${out}_report.csv"
EOS
chmod +x "$TMP/bin/PLASMe.py"

run_stage() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 RUN_GPLAS2_EXTERNAL=0 RUN_GENOMAD=0 \
    PLASME_DB="$TMP/db" PLASME_CALLS_LOG="$TMP/plasme_calls.log" \
    "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="plasme" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/plasme_calls.log"
run_stage env RUN_PLASME=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "-p " "$TMP/plasme_calls.log" || { echo "FAIL: expected PLASMe.py to be called with -p (probability threshold)" >&2; cat "$TMP/plasme_calls.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasme.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasme.scores.tsv" ]] || { echo "FAIL: expected a scores.tsv file" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_plasme.candidates.fasta" ]] || { echo "FAIL: expected a candidates.fasta file" >&2; exit 1; }
echo "RUN_PLASME=1 invokes PLASMe.py and records a completed prediction with scores/candidates -> PASS"

run_stage env RUN_PLASME=1 PATH="/usr/bin:/bin" || { echo "FAIL: stage should not abort when PLASMe.py is missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped when PLASMe.py is missing, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "command unavailable" || { echo "FAIL: expected a 'command unavailable' reason" >&2; exit 1; }
echo "RUN_PLASME=1 with PLASMe.py missing skips cleanly (not a stage failure) -> PASS"

echo "ALL PLASME STAGE TESTS PASSED"
