#!/usr/bin/env bash
# Regression for the Plassembler hybrid track.
#
# The point of these tests is the CIRCULARITY GUARD. PlasBench's truth labels
# come from a complete long-read or hybrid assembly; handing Plassembler the
# same long reads that produced that assembly scores the tool against its own
# input. A benchmark that does that silently is worse than one that omits the
# tool, so the default must be to refuse, the opt-in must be explicit, and an
# override must stay visible in the results.
#
# Runs fully offline against stub binaries; no real Plassembler required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data" "$TMP/results" "$TMP/logs" "$TMP/db"
touch "$TMP/db/plsdb.msh"

# Stub plassembler: writes the two records it "assembled", in the real output
# shape (<prefix>_plasmids.fasta with copy-number fields in the header).
cat > "$TMP/bin/plassembler" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out"
if [[ "${PLASSEMBLER_STUB_EMPTY:-0}" == "1" ]]; then
    : > "$out/plassembler_plasmids.fasta"
else
    printf '>1 len=2000 copy_number_short_read=2.5\nACGT\n>2 len=900 copy_number_short_read=8.1\nTTGA\n' \
        > "$out/plassembler_plasmids.fasta"
fi
exit 0
EOS
chmod +x "$TMP/bin/plassembler"

# sheet [COLUMN_NAME VALUE] -- write a one-sample sheet, optionally with one
# extra curation column. The tabs must come from the format string: a tab
# passed through %s stays a literal backslash-t and the column never parses.
sheet() {
    local extra_h="${1:-}" extra_v="${2:-}"
    if [[ -n "$extra_h" ]]; then
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\t%s\n' "$extra_h" > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\thybrid\t%s\n' "$extra_v" >> "$TMP/sheet.tsv"
    else
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\n' > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\thybrid\n' >> "$TMP/sheet.tsv"
    fi
}

stage7() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_PLASSEMBLER=1 RUN_FLYE_MOB_RECON=0 PLASSEMBLER_DB="$TMP/db" \
    "$@" bash "$ROOT/scripts/07_long_read_reconstruct.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$2" '$1=="s1" && $2=="plassembler" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

# Inputs a real run would have: long reads plus the short pair from stage 1.
mkdir -p "$TMP/data/s1"
printf 'x' | gzip > "$TMP/data/s1/long_reads.fastq.gz"
printf 'x' | gzip > "$TMP/data/s1/SRR1_1.fastq.gz"
printf 'x' | gzip > "$TMP/data/s1/SRR1_2.fastq.gz"

# --- 1. Circular truth is refused by default -------------------------------
sheet
stage7 || { echo "FAIL: stage should not abort when a sample is skipped" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field _ 3)" == "skipped" ]] || {
    echo "FAIL: a sample whose truth derives from its long reads must be skipped, got: $(status_field _ 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field _ 5 | grep -qi "circular" || {
    echo "FAIL: the recorded reason should say the truth is circular, got: $(status_field _ 5)" >&2; exit 1; }
[[ ! -s "$TMP/results/s1/pred_plassembler.plasmid.fasta" ]] || {
    echo "FAIL: no prediction should be produced for a circular sample" >&2; exit 1; }
echo "circular truth (truth_technology=hybrid) is refused by default -> PASS"

# --- 2. An explicit per-sample declaration allows it ------------------------
sheet truth_independent_of_long_reads yes
stage7 || { echo "FAIL: declared-independent sample should run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field _ 3)" == "completed" ]] || {
    echo "FAIL: declared-independent sample should complete, got: $(status_field _ 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
grep -c '^>' "$TMP/results/s1/pred_plassembler.plasmid.fasta" | grep -qx 2 || {
    echo "FAIL: expected 2 plasmid records in the prediction" >&2; exit 1; }
echo "truth_independent_of_long_reads=yes lets the sample run -> PASS"

# --- 3. Each assembled plasmid becomes its own bin --------------------------
bins="$TMP/results/s1/pred_plassembler.bins.tsv"
[[ -s "$bins" ]] || { echo "FAIL: no bins table written" >&2; exit 1; }
[[ "$(tail -n +2 "$bins" | wc -l)" -eq 2 ]] || {
    echo "FAIL: expected one bin per assembled plasmid" >&2; cat "$bins" >&2; exit 1; }
awk -F'\t' '$1=="1" && $2=="1" {found=1} END{exit !found}' "$bins" || {
    echo "FAIL: bin id should be the contig id, header copy-number fields stripped" >&2; cat "$bins" >&2; exit 1; }
echo "each assembled plasmid is its own bin, headers parsed correctly -> PASS"

# --- 4. The global override runs it, and stays visible in the results -------
sheet
stage7 env PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 || {
    echo "FAIL: override should let the sample run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field _ 3)" == "completed" ]] || {
    echo "FAIL: override should complete, got: $(status_field _ 3)" >&2; exit 1; }
status_field _ 5 | grep -qi "ALLOW_CIRCULAR_TRUTH" || {
    echo "FAIL: an overridden run must say so in tool_status.tsv, got: $(status_field _ 5)" >&2; exit 1; }
echo "PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 runs it and records the compromise -> PASS"

# --- 5. "No plasmids" is a prediction, not a failure ------------------------
sheet truth_independent_of_long_reads yes
stage7 env PLASSEMBLER_STUB_EMPTY=1 || { echo "FAIL: empty result should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field _ 3)" == "completed" ]] || {
    echo "FAIL: an empty Plassembler result is a real prediction and must be scored, got: $(status_field _ 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
echo "an empty result is scored as 'no plasmids', not treated as a failure -> PASS"

# --- 6. Missing inputs are skipped with a specific reason -------------------
sheet truth_independent_of_long_reads yes
mv "$TMP/data/s1/long_reads.fastq.gz" "$TMP/data/s1/held.gz"
stage7 || { echo "FAIL: missing long reads should skip, not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field _ 5 | grep -qi "long-read" || {
    echo "FAIL: reason should name the missing long reads, got: $(status_field _ 5)" >&2; exit 1; }
mv "$TMP/data/s1/held.gz" "$TMP/data/s1/long_reads.fastq.gz"

mv "$TMP/data/s1/SRR1_2.fastq.gz" "$TMP/data/s1/held2.gz"
stage7 || { echo "FAIL: missing short reads should skip, not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field _ 5 | grep -qi "short reads" || {
    echo "FAIL: reason should name the missing short reads, got: $(status_field _ 5)" >&2; exit 1; }
mv "$TMP/data/s1/held2.gz" "$TMP/data/s1/SRR1_2.fastq.gz"

PLASSEMBLER_DB_MISSING="$TMP/nope"
sheet truth_independent_of_long_reads yes
rm -rf "$TMP/results"; mkdir -p "$TMP/results"
PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PLASSEMBLER=1 RUN_FLYE_MOB_RECON=0 \
    PLASSEMBLER_DB="$PLASSEMBLER_DB_MISSING" \
    bash "$ROOT/scripts/07_long_read_reconstruct.sh" > "$TMP/stage.log" 2>&1 || {
        echo "FAIL: missing database should skip, not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field _ 5 | grep -qi "database missing" || {
    echo "FAIL: reason should name the missing database, got: $(status_field _ 5)" >&2; exit 1; }
echo "missing long reads / short reads / database each skip with a specific reason -> PASS"

echo "ALL PLASSEMBLER TESTS PASSED"
