#!/usr/bin/env bash
# Regression: MAX_PARALLEL_SAMPLES=1 (default) must keep stage 1's fail-fast
# behavior (one sample's download failure aborts the whole stage before
# later samples are even attempted). MAX_PARALLEL_SAMPLES>1 must actually
# overlap downloads, and must still report every failure clearly rather than
# losing one silently -- concurrency changing "stop at the first failure"
# into "collect every failure" is an accepted, documented tradeoff of
# opting into it, not a silent regression.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DELAY=0.4
mkdir -p "$TMP/bin"
# FAIL_SRA (an env var) names one SRA run whose prefetch should fail; every
# other run succeeds after sleeping, so timing and fail-fast can both be
# tested with the same fake binary.
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
sleep $DELAY
outdir="" run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) outdir="\$2"; shift 2;; *) run="\$1"; shift;; esac; done
echo "\$run" >> "$TMP/prefetch_calls.log"
if [[ "\$run" == "\${FAIL_SRA:-__none__}" ]]; then echo "simulated prefetch failure" >&2; exit 1; fi
mkdir -p "\$outdir/\$run"; touch "\$outdir/\$run/\$run.sra"
EOF
cat > "$TMP/bin/fasterq-dump" <<EOF
#!/usr/bin/env bash
outdir=""
args=("\$@")
for ((i=0;i<\${#args[@]};i++)); do case "\${args[\$i]}" in -O) outdir="\${args[\$((i+1))]}";; esac; done
sra="\$(basename "\${args[-1]}")"; sra="\${sra%.sra}"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_1.fastq"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_2.fastq"
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump"

run_stage() {
    PATH="$TMP/bin:$PATH" \
        DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 \
        "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}
now_ms() { date +%s%N | cut -c1-13; }

mkdir -p "$TMP/data" "$TMP/logs"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\ns3\tNA\tSRR3\n' > "$TMP/sheet.tsv"

# --- default (MAX_PARALLEL_SAMPLES=1): a failure must abort before later
# samples are even attempted -- fail-fast, exactly like before parallelism. ---
: > "$TMP/prefetch_calls.log"
if run_stage env FAIL_SRA=SRR1 MAX_PARALLEL_SAMPLES=1; then
    echo "FAIL: stage should have exited non-zero on a download failure" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
called="$(cat "$TMP/prefetch_calls.log" | tr '\n' ' ')"
[[ "$called" == "SRR1 " ]] || {
    echo "FAIL: default mode should stop after the first failure, prefetch was called for: $called" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
echo "MAX_PARALLEL_SAMPLES=1 (default) still fails fast, stopping before later samples -> PASS"

# --- parallel (MAX_PARALLEL_SAMPLES=3): overlap must be real, and a failure
# in one sample must not silently swallow the others or the overall failure. ---
rm -rf "$TMP/data"; mkdir -p "$TMP/data"
: > "$TMP/prefetch_calls.log"
start=$(now_ms)
if run_stage env MAX_PARALLEL_SAMPLES=1; then :; else echo "FAIL: sequential baseline (no failures) should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; fi
end=$(now_ms)
sequential_ms=$(( end - start ))

rm -rf "$TMP/data"; mkdir -p "$TMP/data"
start=$(now_ms)
if run_stage env MAX_PARALLEL_SAMPLES=3; then :; else echo "FAIL: parallel run (no failures) should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; fi
end=$(now_ms)
parallel_ms=$(( end - start ))
for s in s1 s2 s3; do
    [[ -s "$TMP/data/$s/SRR${s#s}_1.fastq.gz" ]] || { echo "FAIL: sample $s missing downloaded reads" >&2; exit 1; }
done
[[ "$parallel_ms" -lt "$(( sequential_ms * 3 / 4 ))" ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=3 (${parallel_ms}ms) was not clearly faster than sequential (${sequential_ms}ms)" >&2
    exit 1; }
echo "MAX_PARALLEL_SAMPLES=3 overlaps independent downloads (${parallel_ms}ms vs ${sequential_ms}ms sequential) -> PASS"

# Now with one sample deliberately failing: the other two must still finish
# (concurrency means their downloads were already in flight), and the stage
# must still exit non-zero and name the failed sample.
rm -rf "$TMP/data"; mkdir -p "$TMP/data"
: > "$TMP/prefetch_calls.log"
if run_stage env FAIL_SRA=SRR2 MAX_PARALLEL_SAMPLES=3; then
    echo "FAIL: stage should exit non-zero when one sample's download fails" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
grep -q "s2" "$TMP/stage.log" || { echo "FAIL: failure report did not name the failed sample (s2)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/SRR1_1.fastq.gz" ]] || { echo "FAIL: sibling sample s1 should still have completed under concurrency" >&2; exit 1; }
[[ -s "$TMP/data/s3/SRR3_1.fastq.gz" ]] || { echo "FAIL: sibling sample s3 should still have completed under concurrency" >&2; exit 1; }
[[ ! -e "$TMP/data/s2/SRR2_1.fastq.gz" ]] || { echo "FAIL: failed sample s2 should not have produced reads" >&2; exit 1; }
echo "one sample's failure under concurrency is reported clearly without losing its siblings' results -> PASS"

echo "ALL DOWNLOAD PARALLEL TESTS PASSED"
