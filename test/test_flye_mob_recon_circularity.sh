#!/usr/bin/env bash
# Regression for the flye_mob_recon circularity guard -- a retroactive fix,
# not a new-tool test: before this fix, flye_mob_recon had NO guard at all,
# even though its truth is built the exact same way Plassembler's is (a
# complete long-read or hybrid assembly), so scoring it against a
# non-independent-declared sample was just as circular as it would be for
# Plassembler. This test must FAIL against the pre-fix code (flye_mob_recon
# would complete for a circular sample) and PASS against the generalized
# long_read_truth_eligible guard in scripts/lib.sh.
#
# Runs fully offline against stub binaries; no real Flye/MOB-suite required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs"
printf 'x' | gzip > "$TMP/data/s1/long_reads.fastq.gz"

cat > "$TMP/bin/flye" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in --out-dir) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out"
printf '>contig_1\nACGTACGT\n' > "$out/assembly.fasta"
EOS
cat > "$TMP/bin/mob_recon" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in --outdir) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out"
printf '>plasmid_contig\nACGT\n' > "$out/plasmid_1.fasta"
EOS
chmod +x "$TMP/bin/flye" "$TMP/bin/mob_recon"

sheet() {
    local extra_h="${1:-}" extra_v="${2:-}"
    if [[ -n "$extra_h" ]]; then
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\t%s\n' "$extra_h" > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\tlong_read\t%s\n' "$extra_v" >> "$TMP/sheet.tsv"
    else
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\n' > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\tlong_read\n' >> "$TMP/sheet.tsv"
    fi
}

stage7() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_FLYE_MOB_RECON=1 RUN_PLASSEMBLER=0 \
    "$@" bash "$ROOT/scripts/07_long_read_reconstruct.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="flye_mob_recon" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

# --- 1. Circular truth is refused by default (the retroactive fix). --------
sheet
stage7 || { echo "FAIL: stage should not abort when a sample is skipped" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || {
    echo "FAIL: a sample whose truth derives from its long reads must be skipped, got: $(status_field 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "circular" || {
    echo "FAIL: the recorded reason should say the truth is circular, got: $(status_field 5)" >&2; exit 1; }
[[ ! -s "$TMP/results/s1/pred_flye_mob_recon.plasmid.fasta" ]] || {
    echo "FAIL: no prediction should be produced for a circular sample" >&2; exit 1; }
echo "circular truth (truth_technology=long_read) is refused by default -> PASS"

# --- 2. An explicit per-sample declaration allows it. -----------------------
sheet truth_independent_of_long_reads yes
stage7 || { echo "FAIL: declared-independent sample should run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || {
    echo "FAIL: declared-independent sample should complete, got: $(status_field 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_flye_mob_recon.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
echo "truth_independent_of_long_reads=yes lets the sample run -> PASS"

# --- 3. The global override runs it and visibly notes the compromise. ------
sheet
stage7 env FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH=1 || { echo "FAIL: override should let it run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || {
    echo "FAIL: override should complete the sample, got: $(status_field 3)" >&2
    cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "ALLOW_CIRCULAR_TRUTH" || {
    echo "FAIL: the override must stay visible in the recorded reason, got: $(status_field 5)" >&2; exit 1; }
echo "FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH=1 runs it and records the compromise -> PASS"

echo "ALL FLYE_MOB_RECON CIRCULARITY TESTS PASSED"
