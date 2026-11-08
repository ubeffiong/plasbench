#!/usr/bin/env bash
# Regression: a failed tool run must record its exit code in tool_status.tsv's
# reason column (no schema change), so aggregation can tell a timeout/OOM kill
# (124/137) from a tool that simply failed. Uses fake binaries; runs offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/config"

# mob_recon is killed (exit 137, what the kernel OOM killer produces).
cat > "$TMP/bin/mob_recon" <<'EOF'
#!/usr/bin/env bash
exit 137
EOF
# platon fails an ordinary way.
cat > "$TMP/bin/platon" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
# plasmidspades succeeds.
cat > "$TMP/bin/plasmidspades.py" <<EOF
#!/usr/bin/env bash
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"
printf '>NODE_1\nACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/mob_recon" "$TMP/bin/platon" "$TMP/bin/plasmidspades.py"

printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

export DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv"
export REQUIRE_CURATED_METADATA=0
PATH="$TMP/bin:$PATH" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || {
    echo "FAIL: stage 4 must finish even when tools fail" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }

STATUS="$RESULTS_DIR/tool_status.tsv"
reason_of() { awk -F'\t' -v t="$1" '$2==t {print $5}' "$STATUS"; }
status_of() { awk -F'\t' -v t="$1" '$2==t {print $3}' "$STATUS"; }

[[ "$(status_of mob_recon)" == "failed" ]] || { echo "FAIL: mob_recon should be failed" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(reason_of mob_recon)" == *"exit_code=137"* ]] || { echo "FAIL: mob_recon reason lacks exit_code=137: $(reason_of mob_recon)" >&2; exit 1; }
echo "a killed tool records exit_code=137 -> PASS"

[[ "$(status_of platon)" == "failed" ]] || { echo "FAIL: platon should be failed" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(reason_of platon)" == *"exit_code=1"* ]] || { echo "FAIL: platon reason lacks exit_code=1: $(reason_of platon)" >&2; exit 1; }
echo "an ordinarily failing tool records exit_code=1 -> PASS"

[[ "$(status_of plasmidspades)" == "completed" ]] || { echo "FAIL: plasmidspades should have completed" >&2; cat "$STATUS" >&2; exit 1; }
[[ "$(reason_of plasmidspades)" != *"exit_code"* ]] || { echo "FAIL: a completed run must not carry an exit code" >&2; exit 1; }
echo "a completed tool carries no exit code -> PASS"

# The header must be unchanged: other readers depend on it.
header="$(head -1 "$STATUS")"
[[ "$header" == $'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb' ]] || {
    echo "FAIL: tool_status.tsv header changed: $header" >&2; exit 1; }
echo "tool_status.tsv header is unchanged -> PASS"

# And aggregation classifies the recorded reasons correctly.
python3 - "$ROOT/python" "$STATUS" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from aggregate_results import read_failures
kinds = {tool: kind for tool, _, kind in read_failures(sys.argv[2])}
assert kinds == {"mob_recon": "resource", "platon": "tool"}, kinds
PY
echo "aggregation classifies 137 as resource and 1 as tool -> PASS"

echo "ALL FAILED-TOOL EXIT CODE TESTS PASSED"
