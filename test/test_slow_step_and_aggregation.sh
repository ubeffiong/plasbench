#!/usr/bin/env bash
# (1) The slow-step watchdog: a long command that runs STEP_SLOW_FACTOR times its typical time (config/step_typical.tsv) gets ONE note and ONE slow_step event; nothing is stopped.
# (2) One aggregated warning instead of one per isolate: a 300-row sheet with 3 isolates downloaded gives no warning for the other 297 and ONE summary line; every row is still recorded.
# (3) Every stage script marks its start and end (stage_start/stage_end events), so `plasbench status` can name the stage.
# Fakes only; offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# ---- 1. the watchdog ---------------------------------------------------------------------------------------------------------------
mkdir -p "$TMP/proj/config" "$TMP/res"
printf 'pattern\ttypical_seconds\tbasis\tnote\nfake step\t1\tassumed\t\n' > "$TMP/proj/config/step_typical.tsv"
run_watched() {   # run_watched FACTOR -> console output
    ( export PROJECT_ROOT="$TMP/proj" RESULTS_DIR="$TMP/res" STEP_SLOW_FACTOR="$1" HEARTBEAT_DELAY_SECONDS=1000 NO_COLOR=1
      : > "$TMP/res/run_events.jsonl"
      source "$ROOT/scripts/lib.sh"
      run_with_heartbeat "s1 / fake step" sleep 4 ) 2>&1
}
out="$(run_watched 2)"
[[ "$(grep -c "is still running after" <<< "$out")" == "1" ]] || fail "exactly one slow-step note expected: $out"
grep -q "typical about 0 min" <<< "$out" || grep -q "typical" <<< "$out" || fail "the note must name the typical time"
grep -q "plasbench diagnose" <<< "$out" || fail "the note must say how to tell stuck from slow"
[[ "$(grep -c '"event":"slow_step"' "$TMP/res/run_events.jsonl")" == "1" ]] || fail "one slow_step event expected"
grep -q '"factor":"2"' "$TMP/res/run_events.jsonl" || fail "the event records the factor"
grep -q '"typical":"1"' "$TMP/res/run_events.jsonl" || fail "command_start records the typical time"
echo "slow-step watchdog: one note, one slow_step event, nothing stopped -> PASS"
out="$(run_watched 0)"
[[ "$(grep -c "is still running after" <<< "$out")" == "0" && "$(grep -c slow_step "$TMP/res/run_events.jsonl")" == "0" ]] || fail "STEP_SLOW_FACTOR=0 must turn the watchdog off"
out="$(run_watched 100)"
[[ "$(grep -c "is still running after" <<< "$out")" == "0" ]] || fail "a command within its limit gets no note"
echo "STEP_SLOW_FACTOR=0 or a command within its limit: silent -> PASS"

# ---- 2. one aggregated warning --------------------------------------------------------------------------------------------------------
mkdir -p "$TMP/bin" "$TMP/p/logs" "$TMP/p/results" "$TMP/p/tmp"
cat > "$TMP/bin/fastp" <<'EOS'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOS
cat > "$TMP/bin/spades.py" <<'EOS'
#!/usr/bin/env bash
outdir=""
while [[ $# -gt 0 ]]; do case "$1" in -o) outdir="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$outdir"; printf '>c\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
EOS
chmod +x "$TMP/bin/"*
{ printf 'sample_id\tassembly_accession\tsra_run\n'; for i in $(seq 1 300); do printf 'iso%03d\tNA\tSRR%d\n' "$i" "$i"; done; } > "$TMP/p/sheet.tsv"
for i in 001 002 003; do
    mkdir -p "$TMP/p/data/iso$i"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/p/data/iso$i/SRR${i#00}_1.fastq.gz"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/p/data/iso$i/SRR${i#00}_2.fastq.gz"
done
rc=0
( PATH="$TMP/bin:$PATH" HOME="$TMP/home" DATA_DIR="$TMP/p/data" RESULTS_DIR="$TMP/p/results" LOG_DIR="$TMP/p/logs" TMP_DIR="$TMP/p/tmp" SAMPLE_SHEET="$TMP/p/sheet.tsv" \
  REQUIRE_CURATED_METADATA=0 THREADS=2 ASSEMBLY_MEMORY_GB=4 CAP_THREADS_TO_CPUS=0 PLASBENCH_SKIP_RESOURCE_CHECK=1 SHORT_READ_QC_MODE=off NO_COLOR=1 WORK_DIR=data \
  bash "$ROOT/scripts/03_assemble.sh" > "$TMP/p/stage.log" 2>&1 ) || rc=$?
[[ "$rc" == "0" ]] || { tail -20 "$TMP/p/stage.log" >&2; fail "stage 3 exit $rc"; }
[[ "$(grep -c "WARNING: no reads for" "$TMP/p/stage.log")" == "0" ]] || fail "no per-isolate 'no reads' warning may be printed"
[[ "$(grep -c "297 of 300 isolates in the sheet have no downloaded reads yet" "$TMP/p/stage.log")" == "1" ]] || { grep -i "isolates in the sheet" "$TMP/p/stage.log" >&2 || true; fail "ONE aggregated warning expected"; }
grep -q "for example iso004, iso005, iso006, and 294 more" "$TMP/p/stage.log" || fail "the warning names the first few and counts the rest"
[[ "$(awk 'END { print NR - 1 }' "$TMP/p/results/assembly_status.tsv")" == "300" ]] || fail "every row is still recorded"
[[ "$(awk -F'\t' '$2 == "completed"' "$TMP/p/results/assembly_status.tsv" | wc -l | tr -d ' ')" == "3" ]] || fail "the 3 selected assemble"
echo "300-row sheet, 3 downloaded: 0 per-row warnings, one aggregated line, 300 rows recorded, 3 assembled -> PASS"

# ---- 3. every stage marks its start --------------------------------------------------------------------------------------------------------
for n in 1 2 3 4 5 6 7 8; do
    script="$(ls "$ROOT"/scripts/0${n}_*.sh)"
    grep -q "^stage_timing_begin $n" "$script" || fail "stage $n ($(basename "$script")) does not call stage_timing_begin $n"
done
grep -q '"event":"stage_start"' "$TMP/p/results/run_events.jsonl" && grep -q '"event":"stage_end"' "$TMP/p/results/run_events.jsonl" || fail "stage 3 must write stage_start and stage_end"
grep -q '"event":"sample_end"' "$TMP/p/results/run_events.jsonl" || fail "stage 3 must write sample_end"
grep -q '"stage":"3"' "$TMP/p/results/run_events.jsonl" || fail "stage 3 events carry the stage number"
echo "every stage script calls stage_timing_begin; stage 3 writes stage_start, sample_end, stage_end -> PASS"
echo "ALL SLOW-STEP AND AGGREGATION TESTS PASSED"
