#!/usr/bin/env bash
# Stage 3 says WHY an assembly failed, retries once where that can help, and stops early when the cause is the computer's. Fake fastp and spades.py; offline.
#
# The fake spades.py prints message formats SAMPLED FROM KNOWLEDGE of SPAdes and the C library (no real SPAdes failure was reproduced for this test).
#   disk full (ENOSPC)      -> diagnosed, NOT retried, the stage stops at the first sample (exit 5), the others are recorded as not attempted
#   out of memory           -> ONE retry with fewer threads and a budget that fits the available memory; success is recorded with what changed
#   out of memory twice     -> stops (exit 5), exactly two attempts
#   Python/distutils error  -> environmental: stops at the first sample
#   empty reads             -> per sample, not environmental: every sample is tried, then 'All 3 samples failed for the same reason'
#   stale output directory  -> the isolate's own folder is removed and it is retried once
#   truncated reads         -> the reads are re-verified; a damaged download gets the exact re-download command; no retry
#   ASSEMBLER_AUTO_RETRY=0  -> no retry
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LAST_LOG=""
fail() { echo "FAIL: $*" >&2; [[ -f "$LAST_LOG" ]] && tail -25 "$LAST_LOG" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat > "$TMP/bin/fastp" <<'EOF'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOF
cat > "$TMP/bin/spades.py" <<'EOF'
#!/usr/bin/env bash
outdir="" threads="" mem=""
while [[ $# -gt 0 ]]; do case "$1" in -o) outdir="$2"; shift 2;; --threads) threads="$2"; shift 2;; --memory) mem="$2"; shift 2;; *) shift;; esac; done
sample="$(basename "$(dirname "$outdir")")"
echo "$sample $threads $mem" >> "$CALLS"
n="$(grep -c "^$sample " "$CALLS")"
if [[ "$n" -le "${FAIL_TIMES:-99}" ]]; then
    case "$SPADES_MODE" in
        enospc) echo "  0:00:03.412    94M / 94M   ERROR   General  (kmer_index_builder.hpp : 88)   Failed to write: No space left on device"; exit 1 ;;
        oom) echo "terminate called after throwing an instance of 'std::bad_alloc'"; echo "  what():  std::bad_alloc"; exit 134 ;;
        oomkill) exit 137 ;;
        pyerr) printf 'Traceback (most recent call last):\n  File "/opt/conda/bin/spades.py", line 31, in <module>\n    from distutils import dir_util\nModuleNotFoundError: No module named %s\n' "'distutils'"; exit 1 ;;
        empty) echo "== Error ==  no reads were found: the input file is empty"; exit 1 ;;
        stale) echo "== Error ==  the output_dir is not empty and --continue was not given; cannot be continued with different options"; exit 1 ;;
        truncated) echo "gzip: reads.fastq.gz: unexpected end of file"; exit 1 ;;
        *) echo "something unrecognised happened"; exit 1 ;;
    esac
fi
mkdir -p "$outdir"; printf '>contig1\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py"

N=0
new_case() {   # a fresh project with samples s1 s2 s3
    N=$((N + 1)); P="$TMP/case$N"; mkdir -p "$P/logs" "$P/results" "$P/tmp"
    local s
    for s in s1 s2 s3; do
        mkdir -p "$P/data/$s"
        printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/$s/SRR_1.fastq.gz"
        printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/$s/SRR_2.fastq.gz"
    done
    printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\ns3\tNA\tSRR\n' > "$P/sheet.tsv"
    CALLS="$P/calls.log"; export CALLS; : > "$CALLS"
    LAST_LOG="$P/stage.log"
}
run_stage() {   # run_stage ENV=VALUE... ; prints the exit code
    local rc=0
    ( PATH="$TMP/bin:$PATH" DATA_DIR="$P/data" RESULTS_DIR="$P/results" LOG_DIR="$P/logs" TMP_DIR="$P/tmp" SAMPLE_SHEET="$P/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
      THREADS=4 ASSEMBLY_MEMORY_GB=4 CAP_THREADS_TO_CPUS=0 PLASBENCH_SKIP_RESOURCE_CHECK=1 SHORT_READ_QC_MODE=off NO_COLOR=1 \
      env "$@" bash "$ROOT/scripts/03_assemble.sh" > "$P/stage.log" 2>&1 ) || rc=$?
    echo "$rc"
}
col() { awk -F'\t' -v s="$1" -v c="$2" 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == c) k = i } $1 == s { print $k }' "$P/results/assembly_status.tsv"; }
calls_for() { grep -c "^$1 " "$CALLS" || true; }

# ---- 1. disk full: diagnosed, not retried, early stop ---------------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=enospc)"
[[ "$rc" == "5" ]] || fail "disk full must stop stage 3 with exit 5 (exit $rc)"
echo "disk full: stage 3 stops with exit 5 -> PASS"
grep -q "SPAdes failed for s1: the disk is full (.*No space left on device). What to do: .*Log: .*s1.spades.log" "$P/stage.log" || fail "the one-block message is missing or incomplete"
echo "disk full: one block 'SPAdes failed for X: <cause> (<evidence>). What to do: ... Log: <path>' -> PASS"
[[ "$(calls_for s1)" == "1" && "$(calls_for s2)" == "0" && "$(calls_for s3)" == "0" ]] || fail "disk full must try s1 once and not touch s2 or s3: $(tr '\n' ';' < "$CALLS")"
echo "disk full: no retry, the remaining samples are not attempted -> PASS"
[[ "$(col s1 cause)" == "disk_full" && -n "$(col s1 advice)" && "$(col s1 status)" == "failed" ]] || fail "s1 row: $(grep '^s1' "$P/results/assembly_status.tsv")"
[[ "$(col s2 status)" == "skipped" && "$(col s2 cause)" == "disk_full" && "$(col s2 reason)" == *"not attempted"* ]] || fail "s2 should be skipped (not attempted)"
echo "disk full: status columns cause and advice recorded; the others are 'skipped: not attempted' -> PASS"
head -1 "$P/results/assembly_status.tsv" | grep -q "^sample.status.contigs.reason.runtime_seconds.cause.advice$" || fail "the old column order must be kept with cause and advice added at the end"
echo "status header keeps the old columns and adds cause, advice at the end -> PASS"
grep -q '"event":"assembly_failed".*"cause":"disk_full"' "$P/results/run_events.jsonl" && grep -q '"event":"stage_stopped"' "$P/results/run_events.jsonl" || fail "run_events must carry assembly_failed and stage_stopped"
echo "disk full: run_events carry the cause -> PASS"
grep -q "run the same plasbench run command again" "$P/stage.log" && grep -q "no separate --resume" "$P/stage.log" || fail "the stop message must say how to resume"
echo "disk full: the stop message says how to resume -> PASS"

# ---- 2. out of memory: one retry with fewer threads and a budget that fits ------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=oom FAIL_TIMES=1)"
[[ "$rc" == "0" ]] || fail "an out-of-memory failure that succeeds on the retry must not stop the stage (exit $rc)"
[[ "$(calls_for s1)" == "2" && "$(calls_for s2)" == "2" && "$(calls_for s3)" == "2" ]] || fail "each sample should be attempted exactly twice: $(tr '\n' ';' < "$CALLS")"
read -r _ t1 m1 < <(grep '^s1 ' "$CALLS" | sed -n 1p); read -r _ t2 m2 < <(grep '^s1 ' "$CALLS" | sed -n 2p)
[[ "$t1" == "4" && "$t2" -lt "$t1" && "$m2" -le "$m1" ]] || fail "the retry must use fewer threads and no more memory than the first attempt: $t1/$m1 then $t2/$m2"
if [[ -r /proc/meminfo ]]; then
    avail_gb="$(awk '/^MemAvailable:/ { print int($2 / 1024 / 1024) }' /proc/meminfo)"
    [[ "$m2" -le "$(( avail_gb > 2 ? avail_gb : 2 ))" ]] || fail "the retry budget $m2 GB is above the available memory ($avail_gb GB)"
fi
echo "out of memory: one retry, threads $t1 -> $t2, budget $m1 -> $m2 GB, not above what is available -> PASS"
[[ "$(col s1 status)" == "completed" && "$(col s1 reason)" == *"retried once after out_of_memory"* ]] || fail "the completed row must say what changed: $(grep '^s1' "$P/results/assembly_status.tsv")"
grep -q '"event":"assembly_retry"' "$P/results/run_events.jsonl" || fail "run_events must record the retry"
[[ -s "$P/logs/s1.spades.attempt1.log" ]] || fail "the first attempt's log must be kept"
echo "out of memory: success after the retry is recorded with what changed, in the status and run_events; the first log is kept -> PASS"

# ---- 3. out of memory twice: each isolate gets exactly two attempts and the stage CONTINUES with the next one (memory is the isolate's, not the computer's) ----
# (Before the run-stalls fix this stopped the whole stage at the first isolate, exit 5, and left the others unrecorded.)
new_case
rc="$(run_stage SPADES_MODE=oom)"
[[ "$rc" == "1" && "$(calls_for s1)" == "2" && "$(calls_for s2)" == "2" && "$(calls_for s3)" == "2" ]] || fail "each isolate must get exactly 2 attempts and the stage must go on (exit 1 only because NO isolate assembled; exit $rc, calls $(tr '
' ';' < "$CALLS"))"
grep -q "already retried once" "$P/results/assembly_status.tsv" || fail "the status must say the retry was made"
echo "out of memory twice: never more than one retry per isolate, the other isolates are still tried -> PASS"

# ---- 3b. a bare kill (exit 137, empty log) is read as memory with medium confidence, and retried once ---------------------------------------
new_case
rc="$(run_stage SPADES_MODE=oomkill FAIL_TIMES=1)"
[[ "$rc" == "0" && "$(calls_for s1)" == "2" ]] || fail "exit 137 should be retried once (exit $rc)"
echo "exit 137 with an empty log is retried once as a probable memory kill -> PASS"

# ---- 3c. ASSEMBLER_AUTO_RETRY=0: no retry --------------------------------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=oom ASSEMBLER_AUTO_RETRY=0)"
[[ "$(calls_for s1)" == "1" ]] || fail "ASSEMBLER_AUTO_RETRY=0 must not retry: $(tr '\n' ';' < "$CALLS")"
[[ "$(col s1 cause)" == "out_of_memory" ]] || fail "the failure is still diagnosed"
echo "ASSEMBLER_AUTO_RETRY=0: diagnosed, not retried -> PASS"

# ---- 4. Python environment error: environmental, early stop ---------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=pyerr)"
[[ "$rc" == "5" && "$(calls_for s1)" == "1" && "$(calls_for s2)" == "0" ]] || fail "a broken Python must stop at the first sample (exit $rc)"
[[ "$(col s1 cause)" == "python_environment" ]] && grep -q "distutils" "$P/results/assembly_status.tsv" || fail "the cause and the distutils evidence must be recorded"
echo "Python/distutils error: stops after the first sample, cause python_environment -> PASS"

# ---- 5. empty reads: per sample, all tried, same-reason summary ------------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=empty)"
[[ "$rc" == "1" ]] || fail "all samples failing for a per-sample cause ends with the 'nothing to benchmark' error (exit $rc)"
[[ "$(calls_for s1)" == "1" && "$(calls_for s2)" == "1" && "$(calls_for s3)" == "1" ]] || fail "a per-sample cause must still try every sample once"
grep -q "All 3 samples failed for the same reason: empty_or_too_few_reads" "$P/stage.log" || fail "the same-reason summary is missing"
grep -qi "no sample produced an assembly" "$P/stage.log" || fail "the existing 'nothing to benchmark' message must remain"
echo "empty reads: every sample tried once, 'All 3 samples failed for the same reason' printed -> PASS"

# ---- 6. stale output directory: removed and retried once ------------------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=stale FAIL_TIMES=1)"
[[ "$rc" == "0" && "$(calls_for s1)" == "2" ]] || fail "a stale-directory failure is retried once (exit $rc)"
[[ "$(col s1 reason)" == *"retried once after stale_output_directory"* ]] || fail "the retry must be recorded: $(col s1 reason)"
echo "stale output directory: own folder removed, one retry, recorded -> PASS"

# ---- 7. truncated reads: verified, exact re-download command, no retry ----------------------------------------------------------------------
new_case
head -c 30 "$P/data/s1/SRR_1.fastq.gz" > "$P/data/s1/cut.gz" && mv "$P/data/s1/cut.gz" "$P/data/s1/SRR_1.fastq.gz"
rc="$(run_stage SPADES_MODE=truncated)"
[[ "$(calls_for s1)" == "1" ]] || fail "truncated reads must not be retried"
[[ "$(col s1 cause)" == "truncated_reads" && "$(col s1 advice)" == *"Re-download: rm -f"*"SRR_1.fastq.gz"* ]] || fail "the advice must carry the exact re-download command: $(col s1 advice)"
echo "truncated reads: damaged file found, exact re-download command given, no retry -> PASS"
[[ "$(col s2 advice)" == *"pass the gzip"* ]] || fail "intact reads must be reported as intact: $(col s2 advice)"
echo "truncated message on intact reads: reported as 'the download is not the problem' -> PASS"

# ---- 8. an unrecognised failure ---------------------------------------------------------------------------------------------------------------
new_case
rc="$(run_stage SPADES_MODE=whatever)"
[[ "$(col s1 cause)" == "unknown" ]] && grep -q "SPAdes failed for s1: the cause is not recognised" "$P/stage.log" || fail "an unknown failure must be called unknown"
echo "unrecognised failure: reported as unknown, never guessed -> PASS"

# ---- 9. exit code wording ------------------------------------------------------------------------------------------------------------------------
out="$(bash -c "source '$ROOT/scripts/lib.sh'; explain_exit 5; explain_exit 6")"
[[ "$out" == *"stage 3 stopped early"* && "$out" == *"resource check"* ]] || fail "explain_exit must know codes 5 and 6"
echo "exit codes 5 and 6 are explained -> PASS"

echo "ALL STAGE 3 FAILURE-DIAGNOSIS TESTS PASSED"
