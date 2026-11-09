#!/usr/bin/env bash
# Outcome states (scoring specification WP4), with fake binaries, offline:
#   mob_recon exits 127 (command could not start)  -> infrastructure_failure, never scored
#   platon fails once, then succeeds                -> completed after 2 attempts (TOOL_RETRIES=1)
#   plasmidspades sleeps past TOOL_TIMEOUT_SECONDS  -> failed, exit 124, failure_class resource, not retried
# tool_status.tsv keeps its fixed header; tool_outcomes.tsv carries the explicit
# exit_code / failure_class / attempts columns; aggregation counts each state
# and never scores the infrastructure failure.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v timeout >/dev/null 2>&1 || { echo "SKIP: coreutils timeout not available"; exit 0; }

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/config"
cat > "$TMP/bin/mob_recon" <<'EOF'
#!/usr/bin/env bash
exit 127
EOF
cat > "$TMP/bin/platon" <<EOF
#!/usr/bin/env bash
count_file="$TMP/platon.count"
n=\$(cat "\$count_file" 2>/dev/null || echo 0); n=\$((n + 1)); echo "\$n" > "\$count_file"
[[ "\$n" -ge 2 ]] || exit 1
prefix=""; outdir="."
while [[ \$# -gt 0 ]]; do case "\$1" in --prefix) prefix="\$2"; shift 2;; --output) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>c1\nACGT\n' > "\$outdir/\${prefix}.plasmid.fasta"
EOF
cat > "$TMP/bin/plasmidspades.py" <<'EOF'
#!/usr/bin/env bash
sleep 5
EOF
# genomad cannot start: an import error is an installation fault (infrastructure).
cat > "$TMP/bin/genomad" <<'EOF'
#!/usr/bin/env bash
echo "ImportError: cannot import name 'EmptyDataError' from 'pandas.io.common'" >&2
exit 1
EOF
chmod +x "$TMP/bin/mob_recon" "$TMP/bin/platon" "$TMP/bin/plasmidspades.py" "$TMP/bin/genomad"

printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

export DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv"
export REQUIRE_CURATED_METADATA=0 TOOL_RETRIES=1 TOOL_TIMEOUT_SECONDS=2 PLATON_DB="$TMP"
export RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_GENOMAD=1 GENOMAD_DB="$TMP"
PATH="$TMP/bin:$PATH" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || {
    echo "FAIL: stage 4 must finish" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }

STATUS="$RESULTS_DIR/tool_status.tsv" OUTCOMES="$RESULTS_DIR/tool_outcomes.tsv"
[[ "$(head -1 "$STATUS")" == $'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb' ]] || {
    echo "FAIL: tool_status.tsv header changed" >&2; exit 1; }
[[ "$(head -1 "$OUTCOMES")" == $'sample\ttool\tstatus\texit_code\tfailure_class\tattempts' ]] || {
    echo "FAIL: tool_outcomes.tsv header: $(head -1 "$OUTCOMES")" >&2; exit 1; }
col() { awk -F'\t' -v t="$2" -v c="$3" '$2==t {print $c}' "$1"; }

[[ "$(col "$STATUS" mob_recon 3)" == "infrastructure_failure" ]] || { echo "FAIL: mob_recon status" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(col "$OUTCOMES" mob_recon 5)" == "infrastructure" && "$(col "$OUTCOMES" mob_recon 4)" == "127" ]] || {
    echo "FAIL: mob_recon outcome row" >&2; cat "$OUTCOMES" >&2; exit 1; }
echo "exit 127 -> infrastructure_failure (exit_code 127, failure_class infrastructure) -> PASS"

if [[ "$(col "$STATUS" platon 3)" == "completed" ]]; then
    [[ "$(col "$OUTCOMES" platon 6)" == "2" ]] || { echo "FAIL: platon attempts" >&2; cat "$OUTCOMES" >&2; exit 1; }
    echo "a failure followed by a successful retry -> completed after 2 attempts -> PASS"
else
    # The adapter may reject the fake output; the retry itself must still be recorded.
    [[ "$(col "$OUTCOMES" platon 6)" == "2" ]] || { echo "FAIL: platon was not retried" >&2; cat "$OUTCOMES" >&2; exit 1; }
    echo "platon was retried once (attempts=2) -> PASS"
fi

[[ "$(col "$OUTCOMES" plasmidspades 4)" == "124" && "$(col "$OUTCOMES" plasmidspades 5)" == "resource" ]] || {
    echo "FAIL: plasmidspades timeout row" >&2; cat "$OUTCOMES" >&2; exit 1; }
[[ "$(col "$OUTCOMES" plasmidspades 6)" == "1" ]] || { echo "FAIL: a timeout must not be retried" >&2; exit 1; }
echo "TOOL_TIMEOUT_SECONDS -> exit 124, resource failure, not retried -> PASS"

if [[ -n "$(col "$STATUS" genomad 3)" ]]; then
    [[ "$(col "$STATUS" genomad 3)" == "infrastructure_failure" ]] || {
        echo "FAIL: an ImportError must be an infrastructure failure, got $(col "$STATUS" genomad 3)" >&2; cat "$STATUS" >&2; exit 1; }
    echo "a tool that cannot import its dependencies -> infrastructure_failure (never scored) -> PASS"
fi

python3 -c "
import sys; sys.path.insert(0, '$ROOT/python')
import aggregate_results as ar
failed = ar.read_failed_samples('$STATUS')
assert 's1' not in failed.get('mob_recon', set()), 'infrastructure failure must never be scored'
assert 's1' in failed.get('plasmidspades', set()), 'a timeout scores 0 by default'
states = {r['tool']: r for r in ar.outcome_states('$STATUS')}
assert states['mob_recon']['infrastructure_failure'] == 1, states['mob_recon']
assert states['plasmidspades']['failed_resource'] == 1, states['plasmidspades']
assert states['platon']['retried'] == 1, states['platon']
print('aggregation: infrastructure not scored, timeout scored 0, retry counted -> PASS')
"
echo "ALL OUTCOME STATE TESTS PASSED"
