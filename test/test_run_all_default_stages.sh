#!/usr/bin/env bash
# Regression: scripts/run_all.sh's default (no-args) stage list must now
# include stage 7, positioned BEFORE scoring/aggregation (5, 6) so long-read/
# hybrid predictions get scored and aggregated in the same pass -- not after,
# which would silently exclude them until a separate follow-up invocation.
# Stage 7 must also still no-op cleanly (no failure, no unexpected output)
# when no long-read RUN_* flag is enabled, since this is what makes including
# it by default safe without forcing any tool to run. Uses the REAL
# run_all.sh/lib.sh/config.sh and the REAL 07_long_read_reconstruct.sh (which
# no-ops offline with no long-read tool installed), with trivial stand-in
# stage 0-6 scripts so this runs fully offline without any bioinformatics
# tool or network access.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp -r "$ROOT/scripts" "$TMP/scripts"
cp -r "$ROOT/config" "$TMP/config"
for n in 00_setup 01_download 02_truth 03_assemble 04_run_tools 05_score 06_aggregate; do
    cat > "$TMP/scripts/${n}.sh" <<EOF
#!/usr/bin/env bash
echo "RAN ${n}" >> "$TMP/order.log"
EOF
    chmod +x "$TMP/scripts/${n}.sh"
done

printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"
DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    bash "$TMP/scripts/run_all.sh" > "$TMP/run.log" 2>&1 || { echo "FAIL: default run_all.sh invocation should succeed" >&2; cat "$TMP/run.log" >&2; exit 1; }

grep -q "RAN 06_aggregate" "$TMP/order.log" || { echo "FAIL: stage 6 (aggregate) never ran" >&2; cat "$TMP/run.log" >&2; exit 1; }
grep -q "Stage 7 disabled" "$TMP/run.log" || { echo "FAIL: stage 7 did not run/no-op as part of the default stage list" >&2; cat "$TMP/run.log" >&2; exit 1; }
echo "stage 7 runs as part of the default (no-args) stage list and no-ops with nothing enabled -> PASS"

stage7_line="$(grep -n "STAGE 7" "$TMP/run.log" | head -1 | cut -d: -f1)"
stage5_line="$(grep -n "STAGE 5" "$TMP/run.log" | head -1 | cut -d: -f1)"
[[ -n "$stage7_line" && -n "$stage5_line" && "$stage7_line" -lt "$stage5_line" ]] || {
    echo "FAIL: stage 7 must run before stage 5, so long-read predictions are scored in the same pass" >&2
    cat "$TMP/run.log" >&2; exit 1; }
echo "stage 7 runs before stage 5/6, not after -> PASS"

echo "ALL RUN_ALL DEFAULT STAGES TESTS PASSED"
