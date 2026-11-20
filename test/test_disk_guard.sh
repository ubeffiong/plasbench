#!/usr/bin/env bash
# The rolling disk guard: before each isolate's assembly (stage 3) and download (stage 1) the free space is checked against that isolate's estimate plus a reserve, and the stage
# stops CLEANLY (exit 6, finished isolates kept, the resume advice printed) instead of failing in the middle of SPAdes. Fake fastp and spades.py; offline.
# The python3 on PATH is a shim that passes everything through, except that from the Nth `guard` call on it sets PLASBENCH_DISK_RESERVE_GB so large that the REAL guard code stops.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LAST_LOG=""
fail() { echo "FAIL: $*" >&2; [[ -f "$LAST_LOG" ]] && tail -25 "$LAST_LOG" >&2; exit 1; }

REAL_PY=""
for c in python3 python; do
    if command -v "$c" > /dev/null 2>&1 && "$c" -c 'import sys' > /dev/null 2>&1; then REAL_PY="$(command -v "$c")"; break; fi
done
[[ -n "$REAL_PY" ]] || fail "no working python"
export REAL_PY

mkdir -p "$TMP/bin"
cat > "$TMP/bin/fastp" <<'EOF'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOF
cat > "$TMP/bin/spades.py" <<'EOF'
#!/usr/bin/env bash
outdir=""
while [[ $# -gt 0 ]]; do case "$1" in -o) outdir="$2"; shift 2;; *) shift;; esac; done
echo "$(basename "$(dirname "$outdir")")" >> "$CALLS"
mkdir -p "$outdir"; printf '>contig1\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
EOF
cat > "$TMP/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [[ " $* " == *" guard "* ]]; then
    n=$(( $(cat "$GUARD_COUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$GUARD_COUNT"
    [[ "$n" -ge "${STOP_AT:-99999}" ]] && export PLASBENCH_DISK_RESERVE_GB=99999999
fi
exec "$REAL_PY" "$@"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py" "$TMP/bin/python3"

N=0
new_case() {   # a fresh project with samples s1..s4
    N=$((N + 1)); P="$TMP/case$N"; mkdir -p "$P/logs" "$P/results" "$P/tmp"
    local s
    printf 'sample_id\tassembly_accession\tsra_run\n' > "$P/sheet.tsv"
    for s in s1 s2 s3 s4; do
        mkdir -p "$P/data/$s"
        printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/$s/SRR_1.fastq.gz"
        printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/$s/SRR_2.fastq.gz"
        printf '%s\tNA\tSRR\n' "$s" >> "$P/sheet.tsv"
    done
    CALLS="$P/calls.log"; export CALLS; : > "$CALLS"
    GUARD_COUNT="$P/guard.count"; export GUARD_COUNT; rm -f "$GUARD_COUNT"
    LAST_LOG="$P/stage.log"
}
run_stage3() {   # run_stage3 ENV=VALUE... ; prints the exit code
    local rc=0
    ( PATH="$TMP/bin:$PATH" DATA_DIR="$P/data" RESULTS_DIR="$P/results" LOG_DIR="$P/logs" TMP_DIR="$P/tmp" TMPDIR="$P/tmp" SAMPLE_SHEET="$P/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
      THREADS=4 ASSEMBLY_MEMORY_GB=4 CAP_THREADS_TO_CPUS=0 SHORT_READ_QC_MODE=off NO_COLOR=1 \
      env "$@" bash "$ROOT/scripts/03_assemble.sh" > "$P/stage.log" 2>&1 ) || rc=$?
    echo "$rc"
}

# ---- 1. stops cleanly before the third isolate ----------------------------------------------------------------------------------------
new_case
rc="$(run_stage3 STOP_AT=3)"
[[ "$rc" == "6" ]] || fail "the guard must stop stage 3 with exit 6 (exit $rc)"
echo "stage 3: the guard stops the run with exit 6 -> PASS"
[[ -s "$P/data/s1/contigs.fasta" && -s "$P/data/s2/contigs.fasta" ]] || fail "the finished isolates must be kept"
[[ ! -e "$P/data/s3/contigs.fasta" && ! -d "$P/data/s3/assembly" ]] || fail "the third isolate must not have been started (no SPAdes run in the middle)"
[[ "$(grep -c . "$CALLS")" == "2" ]] || fail "SPAdes must have run exactly twice ($(tr '\n' ' ' < "$CALLS"))"
echo "stage 3: two isolates finished and kept, the third never started -> PASS"
grep -q "Stopping before s3: only .* GB is free .* needs about .* GB (estimate) plus a .* GB reserve (PLASBENCH_DISK_RESERVE_GB)" "$P/stage.log" || fail "the guard's explanation is missing"
grep -q "Stage 3 stopped cleanly before s3 because the disk is nearly full (2 isolate(s) not attempted).*run the same plasbench run command again to continue" "$P/stage.log" || fail "the resume advice is missing"
echo "stage 3: the explanation and the resume advice are printed -> PASS"
grep -q "not attempted: stage 3 stopped early (disk_space)" "$P/results/assembly_status.tsv" || fail "the isolates not attempted must be recorded"
echo "stage 3: the isolates not attempted are recorded in assembly_status.tsv -> PASS"
grep -q '"cause":"disk_space"' "$P/results/run_events.jsonl" 2> /dev/null || fail "a stage_stopped event with cause disk_space is expected"
echo "stage 3: a stage_stopped event records the cause -> PASS"

# ---- 2. the same command resumes ------------------------------------------------------------------------------------------------------
: > "$CALLS"
rc="$(run_stage3)"
[[ "$rc" == "0" ]] || fail "after freeing space the same command must complete (exit $rc)"
[[ "$(sort "$CALLS" | tr '\n' ' ')" == "s3 s4 " ]] || fail "only the isolates not finished are assembled ($(tr '\n' ' ' < "$CALLS"))"
echo "stage 3: the same command resumes with s3 and s4 only -> PASS"

# ---- 3. the overrides -----------------------------------------------------------------------------------------------------------------
new_case
rc="$(run_stage3 STOP_AT=1 PLASBENCH_SKIP_DISK_CHECK=1)"
[[ "$rc" == "0" ]] || fail "PLASBENCH_SKIP_DISK_CHECK=1 must turn the guard off (exit $rc)"
echo "PLASBENCH_SKIP_DISK_CHECK=1 turns the guard off -> PASS"
new_case
rc="$(run_stage3 STOP_AT=1 PLASBENCH_SKIP_RESOURCE_CHECK=1)"
[[ "$rc" == "0" ]] || fail "PLASBENCH_SKIP_RESOURCE_CHECK=1 must turn the guard off (exit $rc)"
echo "PLASBENCH_SKIP_RESOURCE_CHECK=1 turns the guard off -> PASS"
new_case
rc="$(run_stage3 PLASBENCH_DISK_RESERVE_GB=99999999)"
[[ "$rc" == "6" && ! -s "$P/data/s1/contigs.fasta" ]] || fail "PLASBENCH_DISK_RESERVE_GB must be honoured: nothing fits, stop before the first isolate (exit $rc)"
echo "PLASBENCH_DISK_RESERVE_GB is honoured (stops before the first isolate, nothing half-done) -> PASS"

# ---- 4. the shell hook returns 6 with the message (the stage 1 hook is this function) -----------------------------------------------------
new_case
out="$( cd "$P" && PATH="$TMP/bin:$PATH" PROJECT_ROOT="$ROOT" RESULTS_DIR="$P/results" DATA_DIR="$P/data" TMPDIR="$P/tmp" PLASBENCH_DISK_RESERVE_GB=99999999 NO_COLOR=1 \
    bash -c 'source "$PROJECT_ROOT/scripts/lib.sh"; disk_guard 1 s1 SRR; echo "rc=$?"' 2>&1 )" || true
grep -q "rc=6" <<< "$out" || fail "disk_guard must return 6 when the isolate does not fit ($out)"
grep -q "Stopping before s1" <<< "$out" || fail "disk_guard must print the reason ($out)"
out="$( cd "$P" && PATH="$TMP/bin:$PATH" PROJECT_ROOT="$ROOT" RESULTS_DIR="$P/results" DATA_DIR="$P/data" TMPDIR="$P/tmp" NO_COLOR=1 \
    bash -c 'source "$PROJECT_ROOT/scripts/lib.sh"; disk_guard 1 s1 SRR; echo "rc=$?"' 2>&1 )" || true
grep -q "rc=0" <<< "$out" || fail "disk_guard must return 0 when there is room ($out)"
echo "disk_guard (the stage 1 hook): 6 with the reason when it does not fit, 0 when it does -> PASS"
grep -q 'disk_guard 1 "\$SAMPLE" "\$SRA"' "$ROOT/scripts/01_download.sh" || fail "stage 1 must call disk_guard before each isolate"
grep -q 'exit 6' "$ROOT/scripts/01_download.sh" || fail "stage 1 must exit 6 when the guard stops it"
grep -q 'disk_guard 3 "\$SAMPLE" "\$SRA"' "$ROOT/scripts/03_assemble.sh" || fail "stage 3 must call disk_guard before each isolate"
echo "stages 1 and 3 call the guard before each isolate and exit 6 -> PASS"
echo "ALL DISK GUARD CHECKS PASSED"
