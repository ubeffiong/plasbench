#!/usr/bin/env bash
# Stage 2 speed and resumability:
#   - samples run in parallel with MAX_PARALLEL_SAMPLES (same results as one at a time)
#   - every sample's steps are timed into data/<sample>/stage2_timing.tsv
#   - a re-run reuses repeat content instead of recomputing it
#   - one unusable truth table still stops the stage, also in parallel
#   - measure_depth.py counts read bases exactly (also uncompressed and CRLF FASTQ)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; cat "$TMP/stage.log" >&2 2>/dev/null || true; exit 1; }

make_sample() {
    local s="$1" d="$TMP/data/$1"
    mkdir -p "$d"
    { printf '>chr1 chromosome\n'; for _ in $(seq 1 30); do printf 'GGGCCCATATACGTTGCAAC\n'; done
      printf '>p1 plasmid\n'; for _ in $(seq 1 6); do printf 'TTGACCAGTAGCTAGGATCC\n'; done; } > "$d/reference.fna"
    printf 'sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t600\np1\tPLASMID\t120\n' > "$d/truth.tsv"
    printf '@r\nACGTACGTAC\n+\nIIIIIIIIII\n@r2\nACGT\n+\nIIII\n' | gzip > "$d/SRR_1.fastq.gz"
    printf '@r\nACGTACGTAC\n+\nIIIIIIIIII\n' | gzip > "$d/SRR_2.fastq.gz"
}
mkdir -p "$TMP/results" "$TMP/logs" "$TMP/tmp"
for s in s1 s2 s3; do make_sample "$s"; done
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\ns3\tNA\tSRR\n' > "$TMP/sheet.tsv"
truth_stage() {
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 RUN_REFERENCE_ANNOTATION=0 \
        RUN_DIMER_DETECTION=0 "$@" bash "$ROOT/scripts/02_truth.sh" > "$TMP/stage.log" 2>&1
}

# 1. parallel: every sample processed, timed, same depth as a sequential run
truth_stage env MAX_PARALLEL_SAMPLES=3 || fail "stage 2 with 3 samples in parallel should succeed"
for s in s1 s2 s3; do
    [[ -s "$TMP/data/$s/stage2_timing.tsv" ]] || fail "$s has no stage2_timing.tsv"
    grep -q "^repeat_content	" "$TMP/data/$s/stage2_timing.tsv" && grep -q "^total	" "$TMP/data/$s/stage2_timing.tsv" \
        || fail "$s timing should list the steps and a total"
    [[ -s "$TMP/data/$s/truth_repeat_content.tsv" && -s "$TMP/data/$s/observed_depth.tsv" ]] || fail "$s outputs missing"
done
grep -q "	24	" "$TMP/data/s2/observed_depth.tsv" || fail "read bases should be 10+4+10=24: $(cat "$TMP/data/s2/observed_depth.tsv")"
grep -q "Stage 2 (truth) complete" "$TMP/stage.log" || fail "the stage should complete"
cp "$TMP/data/s1/truth_repeat_content.tsv" "$TMP/parallel_repeat.tsv"
echo "samples run in parallel, each step timed -> PASS"

# 2. a re-run reuses repeat content (its inputs did not change)
before="$(stat -c %Y "$TMP/data/s1/truth_repeat_content.tsv" 2>/dev/null || stat -f %m "$TMP/data/s1/truth_repeat_content.tsv")"
sleep 1
truth_stage env MAX_PARALLEL_SAMPLES=1 || fail "a sequential re-run should succeed"
after="$(stat -c %Y "$TMP/data/s1/truth_repeat_content.tsv" 2>/dev/null || stat -f %m "$TMP/data/s1/truth_repeat_content.tsv")"
[[ "$before" == "$after" ]] || fail "repeat content should be reused on a re-run"
cmp -s "$TMP/parallel_repeat.tsv" "$TMP/data/s1/truth_repeat_content.tsv" || fail "parallel and sequential results should match"
echo "a re-run reuses repeat content -> PASS"

# 3. an unusable truth table stops the stage, also when samples run in parallel
printf 'sequence_id\tmolecule_type\tlength\nchr1\tREVIEW\t600\np1\tPLASMID\t120\n' > "$TMP/data/s2/truth.tsv"
if truth_stage env MAX_PARALLEL_SAMPLES=3; then fail "an unusable truth table must stop stage 2"; fi
grep -q "stage 2 stopped for: s2\|not usable" "$TMP/stage.log" || fail "the stop should name the sample"
echo "an unusable truth table still stops the stage in parallel -> PASS"

# 4. measure_depth counts exactly: gzip, plain and CRLF files
printf '@a\r\nACGTA\r\n+\r\nIIIII\r\n@b\r\nAC\r\n+\r\nII\r\n' > "$TMP/crlf.fq"
printf '@a\nACGTAC\n+\nIIIIII' > "$TMP/plain.fq"            # no final newline
python3 "$ROOT/python/measure_depth.py" --truth "$TMP/data/s1/truth.tsv" --r1 "$TMP/crlf.fq" --r2 "$TMP/plain.fq" --out "$TMP/d.tsv"
grep -q "	13	" "$TMP/d.tsv" || fail "CRLF and unterminated FASTQ should count 5+2+6=13 bases: $(cat "$TMP/d.tsv")"
echo "measure_depth counts bases exactly -> PASS"
echo "ALL STAGE-2 SPEED TESTS PASSED"
