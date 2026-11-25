#!/usr/bin/env bash
# The incident behind this test (a real run): three isolates were selected, SPAdes failed on the first with "You need approx. 5.24277GB of free RAM" under a 4 GB budget,
# and the run ended with 'no sample produced an assembly' after attempting only ONE isolate, the other two never recorded. Two defects: (1) the loop over the sample
# sheet let a command in its body read the loop's own input (stdin), so the remaining isolates vanished; (2) the memory message was not understood.
# Here: a fake fastp and spades.py, offline. Checks: every isolate is attempted even when a command in the loop reads stdin; the memory retry uses the size SPAdes asked
# for, once; a refusal names the need and the free memory; one isolate's failure never stops the others; a machine-level cause stops and records the rest as not attempted;
# the default budget is computed from MB, not from a floored GB figure.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LAST_LOG=""
fail() { echo "FAIL: $*" >&2; [[ -f "$LAST_LOG" ]] && tail -25 "$LAST_LOG" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat > "$TMP/bin/fastp" <<'EOS'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOS
# A df that reads standard input first, like powershell.exe does when a helper starts it: it used to swallow the rest of the sample list.
cat > "$TMP/bin/df" <<'EOS'
#!/usr/bin/env bash
if [[ "${STDIN_EATER:-0}" == "1" ]]; then cat > /dev/null; fi
exec /bin/df "$@"
EOS
cat > "$TMP/bin/spades.py" <<'EOS'
#!/usr/bin/env bash
outdir="" mem="" oa=""
while [[ $# -gt 0 ]]; do case "$1" in -o) outdir="$2"; shift 2;; --memory) mem="$2"; shift 2;; --only-assembler) oa=1; shift;; *) shift;; esac; done
sample="$(basename "$(dirname "$outdir")")"
echo "$sample $mem${oa:+ oa}" >> "$CALLS"
if [[ "$sample" == "$HUNGRY" && -z "$oa" && "$mem" -lt "${NEED_GB:-6}" ]]; then
    echo "  0:02:11.534   14G / 14G   ERROR   K-mer Counting          (kmer_data.cpp             : 350)   The reads contain too many k-mers to fit into available memory. You need approx. 5.24277GB of free RAM."
    printf '\n== Error ==  system call for: "[spades-hammer]" finished abnormally, OS return value: 255\nIn case you have troubles running SPAdes, you can write to spades.support@cab.spbu.ru\n\nThank you for using SPAdes! If you use it in your research, please cite:\n  doi.org/10.1002/cpbi.102\n'
    exit 255
fi
if [[ "${DISK_FULL:-0}" == "1" && "$sample" == "$HUNGRY" ]]; then echo "ERROR Failed to write: No space left on device"; exit 1; fi
mkdir -p "$outdir"; printf '>contig1\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
EOS
chmod +x "$TMP/bin/"*

N=0
new_case() {
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
      THREADS=4 ASSEMBLY_MEMORY_GB=4 CAP_THREADS_TO_CPUS=0 PLASBENCH_SKIP_RESOURCE_CHECK=1 SHORT_READ_QC_MODE=off NO_COLOR=1 HUNGRY=s1 \
      env "$@" bash "$ROOT/scripts/03_assemble.sh" > "$P/stage.log" 2>&1 < /dev/null ) || rc=$?   # stdin at EOF: the stdin-eating fake df must not wait on a terminal or an open pipe
    echo "$rc"
}
col() { awk -F'\t' -v s="$1" -v c="$2" 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == c) k = i } $1 == s { print $k }' "$P/results/assembly_status.tsv"; }
rows() { awk 'END { print NR - 1 }' "$P/results/assembly_status.tsv"; }

# 1. the real message, 6.9 GB available: need + 15% (7) does not fit in 85% of 6.9 (5.87); the need rounded up (6) fits within 92%: -m 6, once
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066)"
[[ "$rc" == "0" ]] || fail "exit $rc"
[[ "$(grep -c '^s1 ' "$CALLS")" == "2" ]] || fail "s1 must be tried exactly twice: $(tr '\n' ';' < "$CALLS")"
{ grep -q '^s1 4$' "$CALLS" && grep -q '^s1 6$' "$CALLS"; } || fail "the retry must raise -m from 4 to 6: $(tr '\n' ';' < "$CALLS")"
[[ "$(col s1 status)" == "completed" && "$(col s2 status)" == "completed" && "$(col s3 status)" == "completed" ]] || fail "all three must assemble"
grep -q "memory budget 4 -> 6 GB" "$P/results/assembly_status.tsv" || fail "the status must say what changed"
[[ -s "$P/logs/s1.spades.attempt1.log" ]] || fail "the first attempt's log is kept"
echo "SPAdes 'You need approx. 5.24 GB': -m raised 4 -> 6 once (6.9 GB available), all 3 isolates assembled -> PASS"

# 2. plenty of memory: the margin applies (-m ceil(5.24*1.15) = 7 when 16 GB is available)
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=16384 NEED_GB=7)"
grep -q '^s1 7$' "$CALLS" || fail "with 16 GB free the retry is -m 7 (need + 15%): $(tr '\n' ';' < "$CALLS")"
echo "with 16 GB available the retry is need + 15% (-m 7) -> PASS"

# 3. a refusal: 5 GB available, the need is 5.24: no retry for s1, exact numbers in the message, the other isolates are still assembled, exit 0 (completed with warnings)
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=5120)"
[[ "$rc" == "0" ]] || fail "one failed isolate out of three must not fail the stage (exit $rc)"
[[ "$(grep -c '^s1 ' "$CALLS")" == "1" ]] || fail "no retry when the need does not fit"
[[ "$(col s1 status)" == "skipped" && "$(col s1 cause)" == "needs_more_memory" ]] || fail "s1 is skipped with needs_more_memory: $(col s1 status) $(col s1 cause)"
[[ "$(col s2 status)" == "completed" && "$(col s3 status)" == "completed" && "$(rows)" == "3" ]] || fail "s2 and s3 assemble and all three are recorded"
grep -q "needs 5.2 GB, 5.0 GB are free; close programs or raise WSL memory in C:.Users..you...wslconfig (memory=8GB) then .wsl --shutdown" "$P/results/assembly_status.tsv" || fail "the refusal must give the need and what is free"
grep -q "raise MEMORY_GB" "$P/results/assembly_status.tsv" || fail "the options must be listed"
grep -q "complete WITH WARNINGS: 2 of 3 assembled" "$P/stage.log" || fail "the stage must say 2 of 3 assembled"
if grep -q "doi.org" "$P/results/assembly_status.tsv"; then fail "the citation line must never be the evidence"; fi
echo "refusal: exact need vs available, other isolates continue, '2 of 3 assembled' (exit 0) -> PASS"

# 4. a command inside the loop that reads stdin (powershell.exe in a helper) must not make the loop lose isolates
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=5120 STDIN_EATER=1)"
[[ "$(rows)" == "3" && "$(col s3 status)" == "completed" ]] || fail "a stdin-reading helper swallowed the sample list: rows $(rows)"
echo "a helper that reads stdin cannot swallow the rest of the sample list -> PASS"

# 7. the learned need is remembered: a second run of the same isolate (assembly removed) starts at the right -m, with no failing attempt
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066)"
[[ -s "$P/results/resource_profile.tsv" ]] && grep -q "^spades	s1	" "$P/results/resource_profile.tsv" || fail "the learned need must be written to results/resource_profile.tsv"
rm -rf "$P/data/s1/contigs.fasta" "$P/data/s1/assembly_graph.gfa" "$P/data/s1/assembly" "$P/data/s1/assemblies"
: > "$CALLS"
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066)"
[[ "$(grep -c '^s1 ' "$CALLS")" == "1" ]] && grep -q '^s1 6$' "$CALLS" || fail "a resumed isolate must start at -m 6 with one attempt: $(tr '
' ';' < "$CALLS")"
grep -q "remembered from an earlier attempt" "$P/stage.log" || fail "the log must say the need was remembered"
echo "learned need remembered: the second run starts at -m 6 with no failing attempt -> PASS"
# ... and a changed read set invalidates it
printf '@r2
ACGTACGTAC
+
IIIIIIIIII
' | gzip > "$P/data/s1/SRR_1.fastq.gz"
rm -rf "$P/data/s1/contigs.fasta" "$P/data/s1/assembly_graph.gfa" "$P/data/s1/assembly" "$P/data/s1/assemblies" "$P/data/s1/SRR_1.trim.fastq.gz" "$P/data/s1/.fastp.complete"
: > "$CALLS"
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066)"
[[ "$(grep -c '^s1 ' "$CALLS")" == "2" ]] || fail "changed reads must invalidate the remembered need (the failing attempt happens again): $(tr '
' ';' < "$CALLS")"
echo "changed reads invalidate the remembered need -> PASS"

# 8. does not fit, with the opt-in: --only-assembler is tried once and recorded as a different mode
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=5120 ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1)"
grep -q '^s1 4 oa$' "$CALLS" || fail "--only-assembler must be tried: $(tr '
' ';' < "$CALLS")"
[[ "$(col s1 status)" == "completed" && "$(col s1 assembly_mode)" == "only-assembler" ]] || fail "the mode change must be recorded: $(col s1 assembly_mode)"
python3 "$ROOT/python/resource_adapt.py" merge --dir "$P/results" --out "$P/results/resource_profile.tsv"
echo '{}' > "$P/results/run_manifest.json"
python3 "$ROOT/python/resource_adapt.py" manifest --table "$P/results/resource_profile.tsv" --manifest "$P/results/run_manifest.json" --events "$P/results/run_events.jsonl"
grep -q '"only-assembler"' "$P/results/run_manifest.json" && grep -q '"resources"' "$P/results/run_manifest.json" || fail "the manifest must carry the resources section and the mode"
echo "opt-in --only-assembler: tried once, recorded as a different mode in the status and run_manifest.json -> PASS"

# 9. AUTO_RESOURCES=0: one attempt with the budget set, no memory retry
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066 AUTO_RESOURCES=0)"
[[ "$(grep -c '^s1 ' "$CALLS")" == "1" && "$(col s1 status)" == "failed" ]] || fail "AUTO_RESOURCES=0 must not adapt: $(tr '
' ';' < "$CALLS")"
[[ "$(col s2 status)" == "completed" ]] || fail "the other isolates still run"
echo "AUTO_RESOURCES=0: one attempt, failure recorded, others continue -> PASS"

# 10. the adjustment is an event the status shows
new_case
rc="$(run_stage PLASBENCH_TEST_AVAILABLE_MB=7066)"
grep -q '"event":"resource_adjust"' "$P/results/run_events.jsonl" || fail "resource_adjust event expected"
python3 "$ROOT/python/run_status.py" --results-dir "$P/results" > "$P/status.txt" 2>&1 || true
grep -q "adjusted:" "$P/status.txt" || fail "plasbench status must show the adjustment: $(cat "$P/status.txt")"
echo "resource_adjust event written and shown by plasbench status -> PASS"

# 5. a cause that belongs to the computer stops the stage, and every isolate not attempted is RECORDED
new_case
rc="$(run_stage DISK_FULL=1 NEED_GB=0)"
[[ "$rc" == "5" ]] || fail "disk full stops with exit 5 (exit $rc)"
[[ "$(rows)" == "3" ]] || fail "the isolates not attempted must be recorded (rows $(rows))"
[[ "$(col s2 status)" == "skipped" ]] || fail "s2 must be skipped"
col s2 reason | grep -q "not attempted (stopped early: disk_full)" || fail "s2 must say: not attempted (stopped early: disk_full): $(col s2 reason)"
echo "machine-level cause: stage stops, the other isolates are recorded as 'not attempted (stopped early: disk_full)' -> PASS"

# 6. the default budget comes from MB: 6.9 GB -> 5, 7.0 -> 5, 7.8 -> 6, 2 GB -> 2, an explicit MEMORY_GB always wins
for pair in 7066:5 7168:5 7987:6 2048:2 1024:2 16384:13 200000:64; do
    mb="${pair%%:*}" want="${pair##*:}"
    got="$(PLASBENCH_TEST_AVAILABLE_MB="$mb" bash -c 'source "$1/config/config.sh" >/dev/null 2>&1; echo "$MEMORY_GB"' _ "$ROOT")"
    [[ "$got" == "$want" ]] || fail "available $mb MB -> budget $got GB, expected $want"
done
got="$(MEMORY_GB=9 PLASBENCH_TEST_AVAILABLE_MB=2048 bash -c 'source "$1/config/config.sh" >/dev/null 2>&1; echo "$MEMORY_GB"' _ "$ROOT")"
[[ "$got" == "9" ]] || fail "an explicit MEMORY_GB must win (got $got)"
echo "default budget: 6.9 GB -> 5, 7.0 -> 5, 7.8 -> 6, 2 GB -> 2, 16 GB -> 13, 200 GB capped at 64, explicit MEMORY_GB wins -> PASS"
echo "ALL STAGE 3 CONTINUATION TESTS PASSED"
