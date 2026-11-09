#!/usr/bin/env bash
# Regression: stage 4 reuses a finished tool result only when its fingerprint
# (installed executable, adapter, database row, <TOOL>_* settings, inputs) is unchanged.
# Before, any existing .complete marker was reused, so an upgraded tool or a changed
# parameter silently kept its old predictions. Uses a fake binary; runs offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/config"
echo "SPAdes genome assembler v3.15.5" > "$TMP/version"
cat > "$TMP/bin/plasmidspades.py" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "--version" ]]; then touch "$TMP/probed"; cat "$TMP/version"; exit 0; fi
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"
printf '>NODE_1\nACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/plasmidspades.py"

printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

export DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv"
export REQUIRE_CURATED_METADATA=0 ONLY_TOOL=plasmidspades
MARKER="$RESULTS_DIR/s1/.plasmidspades.complete"

run_stage() {
    PATH="$TMP/bin:$PATH" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || {
        echo "FAIL: stage 4 failed" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }
    awk -F'\t' '$1=="s1" && $2=="plasmidspades" {s=$3} END {print s}' "$RESULTS_DIR/tool_status.tsv"
}
expect() {   # expect <status> <what>
    local got; got="$(run_stage)"
    [[ "$got" == "$1" ]] || { echo "FAIL: $2: expected '$1', got '$got'" >&2; tail -20 "$TMP/stage.log" >&2; exit 1; }
    echo "$2 -> PASS"
}

expect completed "first run executes the tool"
grep -q '^plasbench_fingerprint=1$' "$MARKER" || { echo "FAIL: marker holds no fingerprint" >&2; cat "$MARKER" >&2; exit 1; }
grep -q '^executable=plasmidspades.py .*plasmidspades.py [0-9]*:[0-9]*$' "$MARKER" || {
    echo "FAIL: fingerprint lacks the executable's identity" >&2; cat "$MARKER" >&2; exit 1; }
[[ ! -e "$TMP/probed" ]] || { echo "FAIL: the tool was executed just to fingerprint it" >&2; exit 1; }
echo "marker records the fingerprint and executable identity, without running the tool -> PASS"

expect reused "unchanged inputs reuse the result"

# An upgrade rewrites the executable (a new console-script shim or binary).
echo '# upgraded to v4.0.0' >> "$TMP/bin/plasmidspades.py"
expect completed "an upgraded executable re-runs the tool"
expect reused "and is reused once recorded"

export PLASMIDSPADES_THREADS=3
expect reused "a thread-count change alone still reuses the result"

export PLASMIDSPADES_EXTRA_PARAMETER=strict
expect completed "a changed PLASMIDSPADES_* setting re-runs the tool"
expect reused "and is reused once recorded"

printf '>contig1\nACGTACGTACGTTTTT\n' > "$TMP/data/s1/contigs.fasta"
expect completed "changed input contigs re-run the tool"

: > "$MARKER"
expect completed "a marker from before fingerprints re-runs the tool"
: > "$MARKER"
REUSE_UNFINGERPRINTED=1 expect reused "REUSE_UNFINGERPRINTED=1 reuses an unfingerprinted result"

FORCE_RERUN_TOOLS=1 expect completed "FORCE_RERUN_TOOLS=1 still forces a re-run"

echo "ALL TOOL RESULT FINGERPRINT TESTS PASSED"
