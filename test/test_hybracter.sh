#!/usr/bin/env bash
# Regression for both Hybracter modes (long-single, hybrid-single): the
# circularity guard applies to each independently, each mode is independently
# opt-in (enabling one must never run the other), an empty result is a valid
# "no plasmids" prediction, and each missing-precondition path records a
# specific reason. Runs fully offline against a stub `hybracter` binary; no
# real Hybracter required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data" "$TMP/results" "$TMP/logs" "$TMP/db"
touch "$TMP/db/plsdb.msh"

# Stub hybracter: writes one plasmid record under FINAL_OUTPUT/complete/,
# in the real output shape, for either subcommand.
cat > "$TMP/bin/hybracter" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out/FINAL_OUTPUT/complete"
if [[ "${HYBRACTER_STUB_EMPTY:-0}" == "1" ]]; then
    : > "$out/FINAL_OUTPUT/complete/sample_plasmid.fasta"
else
    printf '>1 len=2000 copy_number_short_read=2.5\nACGT\n' > "$out/FINAL_OUTPUT/complete/sample_plasmid.fasta"
fi
exit 0
EOS
chmod +x "$TMP/bin/hybracter"

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

# stage7 VAR=val VAR2=val2 ... -- any number of extra env vars, always via env.
stage7() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_FLYE_MOB_RECON=0 RUN_PLASSEMBLER=0 PLASSEMBLER_DB="$TMP/db" \
    env "$@" bash "$ROOT/scripts/07_long_read_reconstruct.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <tool> <column-index>
    awk -F'\t' -v t="$1" -v c="$2" '$1=="s1" && $2==t {print $c; exit}' "$TMP/results/tool_status.tsv"
}

mkdir -p "$TMP/data/s1"
printf 'x' | gzip > "$TMP/data/s1/long_reads.fastq.gz"
printf 'x' | gzip > "$TMP/data/s1/SRR1_1.fastq.gz"
printf 'x' | gzip > "$TMP/data/s1/SRR1_2.fastq.gz"

# --- 1. Circular truth is refused by default, for BOTH modes. --------------
sheet
stage7 RUN_HYBRACTER_LONG=1 RUN_HYBRACTER_HYBRID=1 || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
for tool in hybracter_long hybracter_hybrid; do
    [[ "$(status_field "$tool" 3)" == "skipped" ]] || { echo "FAIL: $tool should be skipped, got: $(status_field "$tool" 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
    status_field "$tool" 5 | grep -qi "circular" || { echo "FAIL: $tool reason should mention circular truth" >&2; exit 1; }
done
echo "circular truth is refused by default for both hybracter_long and hybracter_hybrid -> PASS"

# --- 2. Only the enabled mode runs; the other is never invoked. ------------
sheet truth_independent_of_long_reads yes
stage7 RUN_HYBRACTER_LONG=1 RUN_HYBRACTER_HYBRID=0 || { echo "FAIL: hybracter_long should run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field hybracter_long 3)" == "completed" ]] || { echo "FAIL: hybracter_long should complete, got: $(status_field hybracter_long 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -z "$(status_field hybracter_hybrid 3)" ]] || { echo "FAIL: hybracter_hybrid should never have run" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_hybracter_long.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
echo "enabling one mode runs only that mode, never the other -> PASS"

stage7 RUN_HYBRACTER_LONG=0 RUN_HYBRACTER_HYBRID=1 || { echo "FAIL: hybracter_hybrid should run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field hybracter_hybrid 3)" == "completed" ]] || { echo "FAIL: hybracter_hybrid should complete, got: $(status_field hybracter_hybrid 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -z "$(status_field hybracter_long 3)" ]] || { echo "FAIL: hybracter_long should never have run" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
echo "the reverse toggle also runs only its own mode -> PASS"

# --- 3. Per-mode override runs it and visibly notes the compromise. --------
sheet
stage7 RUN_HYBRACTER_LONG=1 HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH=1 || { echo "FAIL: override should let it run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field hybracter_long 3)" == "completed" ]] || { echo "FAIL: override should complete, got: $(status_field hybracter_long 3)" >&2; exit 1; }
status_field hybracter_long 5 | grep -qi "ALLOW_CIRCULAR_TRUTH" || { echo "FAIL: override must stay visible in the reason" >&2; exit 1; }
echo "HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH=1 runs it and records the compromise -> PASS"

# --- 4. An empty result is scored as 'no plasmids', not a failure. ---------
sheet truth_independent_of_long_reads yes
stage7 RUN_HYBRACTER_LONG=1 HYBRACTER_STUB_EMPTY=1 || { echo "FAIL: empty result should still complete" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field hybracter_long 3)" == "completed" ]] || { echo "FAIL: expected completed for an empty (valid) result, got: $(status_field hybracter_long 3)" >&2; exit 1; }
[[ ! -s "$TMP/results/s1/pred_hybracter_long.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction file" >&2; exit 1; }
echo "an empty result is scored as 'no plasmids', not treated as a failure -> PASS"

# --- 5. Missing preconditions each skip with a specific reason. ------------
rm -f "$TMP/data/s1/long_reads.fastq.gz"
stage7 RUN_HYBRACTER_LONG=1 || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field hybracter_long 5 | grep -qi "long-read" || { echo "FAIL: expected a missing-long-reads reason" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
printf 'x' | gzip > "$TMP/data/s1/long_reads.fastq.gz"

rm -f "$TMP/data/s1/SRR1_1.fastq.gz"
stage7 RUN_HYBRACTER_HYBRID=1 || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field hybracter_hybrid 5 | grep -qi "short reads" || { echo "FAIL: expected a missing-short-reads reason" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
printf 'x' | gzip > "$TMP/data/s1/SRR1_1.fastq.gz"

stage7 RUN_HYBRACTER_LONG=1 PLASSEMBLER_DB="$TMP/does-not-exist" || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
status_field hybracter_long 5 | grep -qi "database missing" || { echo "FAIL: expected a missing-database reason" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
echo "missing long reads / short reads / database each skip with a specific reason -> PASS"

echo "ALL HYBRACTER TESTS PASSED"
