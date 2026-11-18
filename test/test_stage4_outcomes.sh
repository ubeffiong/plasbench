#!/usr/bin/env bash
# Regression for the stage-4 outcome and instrumentation fixes (audit AU-011, AU-031, AU-033, AU-035):
#   1. every tool failed -> stage 4 exits 4 with a message and the table is still written; ALLOW_ALL_TOOLS_FAILED=1 continues; one failure among
#      successes stays a warning (exit 0), and run_all.sh then ends "completed with warnings" and leaves .completed_with_warnings;
#   2. a retry starts from a clean output folder (a tool that refuses the leftovers of the first attempt succeeds on the retry);
#   3. tool_run_resources.tsv records each run's own thread count, the seconds of every attempt, and why memory is blank when it is;
#   4. a tool whose database is missing is not launched at all (no sample x retry launches), recorded as an infrastructure failure;
#   5. stage 4 and stage 5 on an empty cohort fail with a clear message; stage 6 names the stage that is really missing;
#   6. stage_timing.tsv records every stage's elapsed time, including a stage that failed; check_free_disk warns below a threshold.
# Uses fake binaries; runs offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/config" "$TMP/data/s1"
printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"
printf 'sample_id\tassembly_accession\tsra_run\n' > "$TMP/config/empty.tsv"

cat > "$TMP/bin/good_mob_recon" <<'EOF'
#!/usr/bin/env bash
outdir=""; while [[ $# -gt 0 ]]; do case "$1" in --outdir) outdir="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$outdir"; printf 'contig_id\tmolecule_type\ncontig1\tchromosome\n' > "$outdir/contig_report.txt"
EOF
cat > "$TMP/bin/platon_ok" <<'EOF'
#!/usr/bin/env bash
outdir="" prefix=""; while [[ $# -gt 0 ]]; do case "$1" in --output) outdir="$2"; shift 2;; --prefix) prefix="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$outdir"; printf '>c1\nACGT\n' > "$outdir/$prefix.plasmid.fasta"; printf 'ID\n' > "$outdir/$prefix.tsv"
EOF
chmod +x "$TMP/bin/good_mob_recon" "$TMP/bin/platon_ok"
use() { cp "$TMP/bin/$2" "$TMP/bin/$1"; chmod +x "$TMP/bin/$1"; }    # use mob_recon good_mob_recon
fail_tool() { printf '#!/usr/bin/env bash\nexit 1\n' > "$TMP/bin/$1"; chmod +x "$TMP/bin/$1"; }

# run NAME SCRIPT [env...]: runs scripts/SCRIPT with a fresh results/logs for NAME; log in $TMP/NAME.log; returns the exit code
run() {
    local name="$1" script="$2"; shift 2
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/res_$name" LOG_DIR="$TMP/logs_$name" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 PATH="$TMP/bin:$PATH" "$@" \
        timeout 120 bash "$ROOT/scripts/$script" "${RUN_ARGS[@]}" > "$TMP/$name.log" 2>&1
}
RUN_ARGS=()
col() { awk -F'\t' -v t="$2" -v c="$3" '$2 == t {print $c}' "$TMP/res_$1/tool_status.tsv"; }

# ---- 1. all failed / some failed ---------------------------------------------------------------------------------------
fail_tool mob_recon
rc=0; run allfail 04_run_tools.sh ONLY_TOOL=mob_recon TOOL_RETRIES=0 || rc=$?
[[ "$rc" == "4" ]] || { echo "FAIL: every tool failed: stage 4 must exit 4 (exit $rc)" >&2; tail -5 "$TMP/allfail.log" >&2; exit 1; }
grep -q "all 1 tool run(s) failed" "$TMP/allfail.log" || { echo "FAIL: the message must say all tool runs failed" >&2; exit 1; }
[[ "$(col allfail mob_recon 3)" == "failed" ]] || { echo "FAIL: the table must still be written with the failed row" >&2; exit 1; }
echo "all tools failed: exit 4 with a message, the table is kept -> PASS"
rc=0; run allow 04_run_tools.sh ONLY_TOOL=mob_recon TOOL_RETRIES=0 ALLOW_ALL_TOOLS_FAILED=1 || rc=$?
[[ "$rc" == "0" ]] || { echo "FAIL: ALLOW_ALL_TOOLS_FAILED=1 must continue (exit $rc)" >&2; exit 1; }
echo "ALLOW_ALL_TOOLS_FAILED=1 continues with a warning -> PASS"
rc=0; RUN_ARGS=(4); run allfail_ra run_all.sh ONLY_TOOL=mob_recon TOOL_RETRIES=0 || rc=$?
[[ "$rc" == "4" ]] && grep -q "every tool run of stage 4 failed" "$TMP/allfail_ra.log" || { echo "FAIL: run_all.sh must stop with exit 4 and say why (exit $rc)" >&2; tail -4 "$TMP/allfail_ra.log" >&2; exit 1; }
echo "run_all.sh reports the all-failed stage -> PASS"

use mob_recon good_mob_recon; use platon platon_ok
fail_tool plasmidspades.py
rc=0; RUN_ARGS=(4); run partial run_all.sh RUN_MOB_RECON=1 RUN_PLATON=1 RUN_PLASMIDSPADES=1 PLATON_DB="$TMP" TOOL_RETRIES=0 || rc=$?
[[ "$rc" == "0" ]] || { echo "FAIL: some failures among successes stay a warning (exit $rc)" >&2; tail -5 "$TMP/partial.log" >&2; exit 1; }
grep -q "1 of 3 tool run(s) failed" "$TMP/partial.log" && grep -q "completed with warnings" "$TMP/partial.log" || { echo "FAIL: partial failure must be a visible warning" >&2; tail -6 "$TMP/partial.log" >&2; exit 1; }
[[ -s "$TMP/res_partial/.completed_with_warnings" ]] || { echo "FAIL: run_all.sh must leave .completed_with_warnings" >&2; exit 1; }
echo "partial failure: exit 0, a warning, and 'completed with warnings' -> PASS"
rm -f "$TMP/bin/plasmidspades.py"; RUN_ARGS=()

# ---- 2. retry starts clean ----------------------------------------------------------------------------------------------
cat > "$TMP/bin/mob_recon" <<'EOF'
#!/usr/bin/env bash
outdir=""; while [[ $# -gt 0 ]]; do case "$1" in --outdir) outdir="$2"; shift 2;; *) shift;; esac; done
# refuses what a half-finished earlier attempt left behind; the first attempt leaves it and fails
if [[ -e "$outdir/partial" ]]; then echo "output folder is not clean" >&2; exit 9; fi
mkdir -p "$outdir"
if [[ ! -e "$MOB_STATE" ]]; then : > "$MOB_STATE"; : > "$outdir/partial"; sleep 1; exit 1; fi
printf 'contig_id\tmolecule_type\ncontig1\tchromosome\n' > "$outdir/contig_report.txt"
EOF
chmod +x "$TMP/bin/mob_recon"
rc=0; run retry 04_run_tools.sh ONLY_TOOL=mob_recon TOOL_RETRIES=1 MOB_STATE="$TMP/mob.state" MOB_RECON_THREADS=3 || rc=$?
[[ "$rc" == "0" && "$(col retry mob_recon 3)" == "completed" ]] || { echo "FAIL: a retry must start from a clean output folder (exit $rc)" >&2; cat "$TMP/res_retry/tool_status.tsv" >&2; tail -4 "$TMP/retry.log" >&2; exit 1; }
echo "the retry cleans the first attempt's leftovers and completes -> PASS"

# ---- 3. resources side table -----------------------------------------------------------------------------------------------
RES="$TMP/res_retry/tool_run_resources.tsv"
[[ "$(head -1 "$RES")" == $'sample\ttool\tthreads\tattempt_seconds\tpeak_rss_kb\trss_note' ]] || { echo "FAIL: resources header" >&2; head -1 "$RES" >&2; exit 1; }
[[ "$(awk -F'\t' '$2 == "mob_recon" {print $3}' "$RES")" == "3" ]] || { echo "FAIL: the run's own thread count (3) must be recorded" >&2; cat "$RES" >&2; exit 1; }
[[ "$(awk -F'\t' '$2 == "mob_recon" {print $4}' "$RES")" =~ ^1:[0-9]+,2:[0-9]+$ ]] || { echo "FAIL: the seconds of both attempts must be recorded" >&2; cat "$RES" >&2; exit 1; }
if [[ -x /usr/bin/time ]]; then
    [[ -n "$(awk -F'\t' '$2 == "mob_recon" {print $5}' "$RES")" ]] || { echo "FAIL: peak memory over the attempts must be recorded" >&2; cat "$RES" >&2; exit 1; }
fi
echo "threads per run, seconds per attempt and peak memory are recorded -> PASS"
use mob_recon good_mob_recon
rc=0; run nort 04_run_tools.sh ONLY_TOOL=mob_recon || rc=$?
[[ -z "$(awk -F'\t' '$2 == "mob_recon" {print $5}' "$TMP/res_nort/tool_run_resources.tsv")" && -n "$(awk -F'\t' '$2 == "mob_recon" {print $6}' "$TMP/res_nort/tool_run_resources.tsv")" || -x /usr/bin/time ]] || {
    echo "FAIL: a blank memory figure must carry a reason" >&2; cat "$TMP/res_nort/tool_run_resources.tsv" >&2; exit 1; }
echo "blank memory is explained in rss_note -> PASS"

# ---- 4. database pre-flight --------------------------------------------------------------------------------------------------
printf '#!/usr/bin/env bash\necho launched >> "%s/platon.launched"\nexit 1\n' "$TMP" > "$TMP/bin/platon"; chmod +x "$TMP/bin/platon"
rc=0; run nodb 04_run_tools.sh ONLY_TOOL=platon PLATON_DB="$TMP/no_such_db" TOOL_RETRIES=2 ALLOW_ALL_TOOLS_FAILED=1 || rc=$?
[[ ! -e "$TMP/platon.launched" ]] || { echo "FAIL: a tool whose database is missing must not be launched" >&2; exit 1; }
[[ "$(col nodb platon 3)" == "infrastructure_failure" && "$(col nodb platon 5)" == *"database not found"* ]] || { echo "FAIL: the missing database must be recorded as an infrastructure failure with the path" >&2; cat "$TMP/res_nodb/tool_status.tsv" >&2; exit 1; }
echo "a missing database is caught before any launch, with the path in the reason -> PASS"

# ---- 5. empty cohort ------------------------------------------------------------------------------------------------------------
rc=0; run empty4 04_run_tools.sh SAMPLE_SHEET="$TMP/config/empty.tsv" || rc=$?
[[ "$rc" != "0" ]] && grep -q "lists no samples" "$TMP/empty4.log" || { echo "FAIL: stage 4 on an empty cohort must fail with a clear message (exit $rc)" >&2; tail -3 "$TMP/empty4.log" >&2; exit 1; }
printf '#!/usr/bin/env bash
exit 0
' > "$TMP/bin/minimap2"; chmod +x "$TMP/bin/minimap2"   # only so stage 5's prerequisite check passes
rc=0; run empty5 05_score.sh SAMPLE_SHEET="$TMP/config/empty.tsv" || rc=$?
[[ "$rc" != "0" ]] && grep -q "lists no samples" "$TMP/empty5.log" || { echo "FAIL: stage 5 on an empty cohort must fail with a clear message (exit $rc)" >&2; tail -3 "$TMP/empty5.log" >&2; exit 1; }
mkdir -p "$TMP/res_six"; printf 'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\ns1\tmob_recon\tfailed\t\tx\t\t\n' > "$TMP/res_six/tool_status.tsv"
rc=0; run six 06_aggregate.sh || rc=$?
[[ "$rc" != "0" ]] && grep -q "no tool run completed in stage 4" "$TMP/six.log" && ! grep -q "run 05_score.sh first" "$TMP/six.log" || { echo "FAIL: stage 6 must blame stage 4 when no tool completed (exit $rc)" >&2; tail -3 "$TMP/six.log" >&2; exit 1; }
echo "empty cohorts fail clearly; stage 6 names the stage that is really missing -> PASS"

# ---- 6. stage timing and free-disk warning ------------------------------------------------------------------------------------------
T="$TMP/res_retry/stage_timing.tsv"
[[ "$(head -1 "$T")" == $'stage\tstarted\tended\telapsed_seconds\texit_code' && "$(awk -F'\t' '$1 == 4 {print $5}' "$T")" == "0" ]] || { echo "FAIL: stage 4 must record its timing" >&2; cat "$T" >&2; exit 1; }
[[ "$(awk -F'\t' '$1 == 4 {print $5}' "$TMP/res_allfail/stage_timing.tsv")" == "4" ]] || { echo "FAIL: a failed stage must record its timing with its exit code" >&2; exit 1; }
mkdir -p "$TMP/res_timing"
for st in 1 5 6 7 8; do
    RESULTS_DIR="$TMP/res_timing" bash -c "source '$ROOT/scripts/lib.sh'; stage_timing_begin $st; [[ $st != 8 ]] || exit 3" || true
done
[[ "$(awk -F'\t' '$1 == 8 {print $5}' "$TMP/res_timing/stage_timing.tsv")" == "3" ]] || { echo "FAIL: a stage that exits 3 must record exit_code 3" >&2; cat "$TMP/res_timing/stage_timing.tsv" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/res_timing/stage_timing.tsv" | cut -f1 | sort | tr '\n' ' ')" == "1 5 6 7 8 " ]] || { echo "FAIL: stage timing rows for stages 1, 5, 6, 7 and 8 expected" >&2; cat "$TMP/res_timing/stage_timing.tsv" >&2; exit 1; }
echo "stage_timing.tsv has a row per stage, failures included -> PASS"
out="$(MIN_FREE_DISK_GB=999999999 bash -c "source '$ROOT/scripts/lib.sh'; check_free_disk '$TMP'" 2>&1)"
[[ "$out" == *"GB is free"* ]] || { echo "FAIL: check_free_disk must warn below the threshold" >&2; echo "$out" >&2; exit 1; }
out="$(MIN_FREE_DISK_GB=1 bash -c "source '$ROOT/scripts/lib.sh'; check_free_disk '$TMP'" 2>&1)"
[[ -z "$out" ]] || { echo "FAIL: no warning when there is enough space" >&2; echo "$out" >&2; exit 1; }
echo "check_free_disk warns only below the threshold -> PASS"

echo "ALL STAGE 4 OUTCOME TESTS PASSED"
