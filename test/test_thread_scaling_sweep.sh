#!/usr/bin/env bash
# Regression for scripts/thread_scaling_sweep.sh: re-runs ONE tool across
# several thread counts via scripts/04_run_tools.sh's own ONLY_TOOL
# restriction, reusing its existing profile_exec/RSS-capture instrumentation
# (tool_status.tsv's own runtime_seconds/peak_rss_kb columns) rather than a
# new profiling mechanism. Confirms: (1) the tool actually receives each
# sweep point's own <TOOL>_THREADS value, not a shared/stale one; (2) every
# sweep point is force-rerun, never reusing a prior point's cached result;
# (3) an unknown --tool name fails clearly before touching stage 4 at all;
# (4) a sample with no assembled contigs fails clearly, never silently
# skipped as if it were a real sweep data point.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs" "$TMP/tmp" "$TMP/db"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
touch "$TMP/db/marker"

cat > "$TMP/bin/platon" <<'EOF'
#!/usr/bin/env bash
threads=""
args=("$@")
for ((i=0;i<${#args[@]};i++)); do [[ "${args[$i]}" == "--threads" ]] && threads="${args[$((i+1))]}"; done
echo "platon called with --threads $threads" >> "$PLATON_CALLS_LOG"
outdir="" prefix=""
for ((i=0;i<${#args[@]};i++)); do
    case "${args[$i]}" in
        --output) outdir="${args[$((i+1))]}" ;;
        --prefix) prefix="${args[$((i+1))]}" ;;
    esac
done
mkdir -p "$outdir"
printf '>c1\nACGTACGT\n' > "$outdir/${prefix}.plasmid.fasta"
printf 'ID\tType\n' > "$outdir/${prefix}.tsv"
EOF
chmod +x "$TMP/bin/platon"

run_sweep() {
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 PLATON_DB="$TMP/db" \
    PLATON_CALLS_LOG="$TMP/platon_calls.log" \
    "$@" bash "$ROOT/scripts/thread_scaling_sweep.sh" "${SWEEP_ARGS[@]}" > "$TMP/sweep.log" 2>&1
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/platon_calls.log"
SWEEP_ARGS=(--tool platon --samples s1 --threads 1,4,8)
run_sweep || { echo "FAIL: sweep should succeed" >&2; cat "$TMP/sweep.log" >&2; exit 1; }

OUT="$TMP/results/thread_scaling_sweep.platon.tsv"
[[ -s "$OUT" ]] || { echo "FAIL: expected a thread_scaling_sweep.platon.tsv output" >&2; exit 1; }
[[ "$(tail -n +2 "$OUT" | wc -l)" -eq 3 ]] || { echo "FAIL: expected exactly 3 sweep rows (1/4/8 threads)" >&2; cat "$OUT" >&2; exit 1; }
for t in 1 4 8; do
    awk -F'\t' -v t="$t" '$1=="platon" && $2=="s1" && $3==t && $4 ~ /^[0-9]+$/ {found=1} END {exit !found}' "$OUT" \
        || { echo "FAIL: expected a row for $t thread(s) with a real runtime" >&2; cat "$OUT" >&2; exit 1; }
done
echo "sweep produces exactly one row per thread count, each with a real runtime -> PASS"

grep -q -- "--threads 1$" "$TMP/platon_calls.log" || { echo "FAIL: expected platon to actually be invoked with --threads 1" >&2; cat "$TMP/platon_calls.log" >&2; exit 1; }
grep -q -- "--threads 4$" "$TMP/platon_calls.log" || { echo "FAIL: expected platon to actually be invoked with --threads 4" >&2; cat "$TMP/platon_calls.log" >&2; exit 1; }
grep -q -- "--threads 8$" "$TMP/platon_calls.log" || { echo "FAIL: expected platon to actually be invoked with --threads 8" >&2; cat "$TMP/platon_calls.log" >&2; exit 1; }
echo "each sweep point actually passes its OWN thread count to the tool, not a shared/stale one -> PASS"

[[ "$(grep -c 'called with' "$TMP/platon_calls.log")" -eq 3 ]] || { echo "FAIL: expected exactly 3 real invocations (no cached reuse across sweep points)" >&2; cat "$TMP/platon_calls.log" >&2; exit 1; }
echo "every sweep point is force-rerun, never reusing a prior point's cached result -> PASS"

# An unknown tool name fails clearly, before touching stage 4 at all.
: > "$TMP/platon_calls.log"
SWEEP_ARGS=(--tool not_a_real_tool --samples s1)
if run_sweep; then echo "FAIL: sweep should fail for an unregistered tool" >&2; cat "$TMP/sweep.log" >&2; exit 1; fi
grep -qi "unknown tool" "$TMP/sweep.log" || { echo "FAIL: expected a clear 'unknown tool' error" >&2; cat "$TMP/sweep.log" >&2; exit 1; }
[[ ! -s "$TMP/platon_calls.log" ]] || { echo "FAIL: an unknown tool must never reach stage 4 at all" >&2; exit 1; }
echo "an unregistered --tool name fails clearly before touching stage 4 -> PASS"

# A sample with no assembled contigs fails clearly, never silently skipped.
SWEEP_ARGS=(--tool platon --samples s1,s_missing)
if run_sweep; then echo "FAIL: sweep should fail when a named sample has no assembled contigs" >&2; cat "$TMP/sweep.log" >&2; exit 1; fi
grep -qi "no assembled contigs" "$TMP/sweep.log" || { echo "FAIL: expected a clear 'no assembled contigs' error" >&2; cat "$TMP/sweep.log" >&2; exit 1; }
echo "a sample with no assembled contigs fails clearly, not silently skipped -> PASS"

echo "ALL THREAD SCALING SWEEP TESTS PASSED"
