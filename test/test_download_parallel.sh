#!/usr/bin/env bash
# Regression: one sample's download failure must NOT abort stage 1. A single
# transient SRA error would otherwise discard hours of successful downloads in
# a large cohort, which is exactly what happened on a 32-sample run. The
# contract now matches stage 3 (see test_assemble_parallel.sh): record the
# failure, carry on with the remaining samples, and abort only when NOTHING
# downloaded, since only then is there nothing to benchmark.
# MAX_PARALLEL_SAMPLES>1 must additionally overlap downloads for real.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DELAY=0.4
mkdir -p "$TMP/bin"
# FAIL_SRA (an env var) names one SRA run whose prefetch should fail;
# FAIL_ALL=1 fails every run regardless. Every other run succeeds after
# sleeping, so timing and failure handling share one fake binary.
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
sleep $DELAY
outdir="" run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) outdir="\$2"; shift 2;; *) run="\$1"; shift;; esac; done
echo "\$run" >> "$TMP/prefetch_calls.log"
if [[ "\${FAIL_ALL:-0}" == "1" || "\$run" == "\${FAIL_SRA:-__none__}" ]]; then echo "simulated prefetch failure" >&2; exit 1; fi
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
        DOWNLOAD_CONFIRM=0 \
        "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}
now_ms() { date +%s%N | cut -c1-13; }

mkdir -p "$TMP/data" "$TMP/logs"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\ns3\tNA\tSRR3\n' > "$TMP/sheet.tsv"

# --- default (MAX_PARALLEL_SAMPLES=1): one failed sample must not abort the
# stage, and its siblings must still be downloaded. ---
: > "$TMP/prefetch_calls.log"
run_stage env FAIL_SRA=SRR1 MAX_PARALLEL_SAMPLES=1 || {
    echo "FAIL: one failed sample among others should not abort the stage" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
# A failing fetch is retried before the sample is given up on, so the call log
# holds repeats. Collapse them to check the order samples were attempted in,
# and separately check the retry actually happened.
called="$(uniq "$TMP/prefetch_calls.log" | tr '\n' ' ')"
[[ "$called" == "SRR1 SRR2 SRR3 " ]] || {
    echo "FAIL: siblings of a failed sample should still be attempted, order was: $called" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
attempts="$(grep -c '^SRR1$' "$TMP/prefetch_calls.log")"
[[ "$attempts" -ge 2 ]] || {
    echo "FAIL: a failing fetch should be retried, SRR1 was attempted $attempts time(s)" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
awk -F'\t' '$1=="s1" && $2=="failed"' "$TMP/results/download_status.tsv" | grep -q . || {
    echo "FAIL: s1 should be recorded as failed in download_status.tsv" >&2
    cat "$TMP/results/download_status.tsv" >&2; exit 1; }
[[ -s "$TMP/data/s2/SRR2_1.fastq.gz" && -s "$TMP/data/s3/SRR3_1.fastq.gz" ]] || {
    echo "FAIL: sibling samples should still have downloaded reads" >&2; exit 1; }
echo "MAX_PARALLEL_SAMPLES=1 (default) tolerates one failed download and still fetches its siblings -> PASS"

# --- every sample failing is the one case that does abort the stage ---
rm -rf "$TMP/data" "$TMP/results"; mkdir -p "$TMP/data"
if run_stage env FAIL_ALL=1 MAX_PARALLEL_SAMPLES=1; then
    echo "FAIL: stage should abort when no sample downloaded at all" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
grep -qi "no sample downloaded successfully" "$TMP/stage.log" || {
    echo "FAIL: expected a clear nothing-to-benchmark error" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "stage aborts only when every download fails -> PASS"

# --- parallel (MAX_PARALLEL_SAMPLES=3): overlap must be real, and a failure
# in one sample must not silently swallow the others or the overall failure. ---
# Wall-clock comparison, so it is measured up to three times: on a loaded
# machine one sample of a 3-4 second run is not reliable evidence either way.
# The claim under test is that concurrency really overlaps the work, not that
# it does so by an exact margin.
speedup_seen=0
for attempt in 1 2 3; do
    rm -rf "$TMP/data"; mkdir -p "$TMP/data"
    : > "$TMP/prefetch_calls.log"
    start=$(now_ms)
    run_stage env MAX_PARALLEL_SAMPLES=1 || { echo "FAIL: sequential baseline (no failures) should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
    end=$(now_ms); sequential_ms=$(( end - start ))

    rm -rf "$TMP/data"; mkdir -p "$TMP/data"
    start=$(now_ms)
    run_stage env MAX_PARALLEL_SAMPLES=3 || { echo "FAIL: parallel run (no failures) should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
    end=$(now_ms); parallel_ms=$(( end - start ))

    for s in s1 s2 s3; do
        [[ -s "$TMP/data/$s/SRR${s#s}_1.fastq.gz" ]] || { echo "FAIL: sample $s missing downloaded reads" >&2; exit 1; }
    done

    if [[ "$parallel_ms" -lt "$(( sequential_ms * 3 / 4 ))" ]]; then
        speedup_seen=1; break
    fi
    echo "  attempt $attempt: ${parallel_ms}ms vs ${sequential_ms}ms sequential -- retrying" >&2
done
[[ "$speedup_seen" -eq 1 ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=3 (${parallel_ms}ms) was not clearly faster than sequential (${sequential_ms}ms) in 3 attempts" >&2
    exit 1
}
echo "MAX_PARALLEL_SAMPLES=3 overlaps independent downloads (${parallel_ms}ms vs ${sequential_ms}ms sequential) -> PASS"

# Now with one sample deliberately failing: the other two must still finish
# (concurrency means their downloads were already in flight), and the stage
# must still exit non-zero and name the failed sample.
rm -rf "$TMP/data"; mkdir -p "$TMP/data"
: > "$TMP/prefetch_calls.log"
run_stage env FAIL_SRA=SRR2 MAX_PARALLEL_SAMPLES=3 || {
    echo "FAIL: one failed sample should not abort a concurrent stage either" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
grep -q "s2" "$TMP/stage.log" || { echo "FAIL: failure report did not name the failed sample (s2)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
awk -F'\t' '$1=="s2" && $2=="failed"' "$TMP/results/download_status.tsv" | grep -q . || {
    echo "FAIL: s2 should be recorded as failed in download_status.tsv" >&2; exit 1; }
[[ -s "$TMP/data/s1/SRR1_1.fastq.gz" ]] || { echo "FAIL: sibling sample s1 should still have completed under concurrency" >&2; exit 1; }
[[ -s "$TMP/data/s3/SRR3_1.fastq.gz" ]] || { echo "FAIL: sibling sample s3 should still have completed under concurrency" >&2; exit 1; }
[[ ! -e "$TMP/data/s2/SRR2_1.fastq.gz" ]] || { echo "FAIL: failed sample s2 should not have produced reads" >&2; exit 1; }
echo "one sample's failure under concurrency is reported clearly without losing its siblings' results -> PASS"

echo "ALL DOWNLOAD PARALLEL TESTS PASSED"
