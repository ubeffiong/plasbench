#!/usr/bin/env bash
# Stage 3 with a scratch work folder (WORK_DIR, python/work_dir.py): a fake spades.py that writes fixed files, offline.
#   data folder on a slow mount (forced with PLASBENCH_FORCE_FS_TYPE=9p) -> SPAdes runs in ~/.plasbench/scratch/<study>/<sample>.<pid>, the results are moved back, the scratch folder is gone
#   WORK_DIR=data                                                         -> SPAdes runs in the data folder, as before
#   the outputs (contigs, graph) are byte-identical either way; intermediate K* folders are not copied back
#   a crash leftover (a dead pid) is removed by the next run with a log line; a failed assembly leaves its spades.log in the isolate folder and no scratch folder
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
cat > "$TMP/bin/spades.py" <<'EOS'
#!/usr/bin/env bash
outdir=""
while [[ $# -gt 0 ]]; do case "$1" in -o) outdir="$2"; shift 2;; *) shift;; esac; done
echo "$outdir" >> "$CALLS"
mkdir -p "$outdir/K21" "$outdir/corrected"
echo intermediate > "$outdir/K21/big.bin"; echo reads > "$outdir/corrected/r.fastq"
echo "SPAdes log line" > "$outdir/spades.log"
if [[ "${FAIL:-0}" == "1" ]]; then echo "ERROR something odd"; exit 1; fi
printf '>NODE_1_length_12\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
printf 'S\t1\tACGTACGTACGT\n' > "$outdir/assembly_graph_with_scaffolds.gfa"
EOS
chmod +x "$TMP/bin/"*

N=0
new_case() {
    N=$((N + 1)); P="$TMP/case$N"; mkdir -p "$P/study/logs" "$P/study/results" "$P/study/tmp" "$P/home"
    mkdir -p "$P/data/s1"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/s1/SRR_1.fastq.gz"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$P/data/s1/SRR_2.fastq.gz"
    printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$P/sheet.tsv"
    CALLS="$P/calls.log"; export CALLS; : > "$CALLS"
    LAST_LOG="$P/stage.log"
}
run_stage() {
    local rc=0
    ( PATH="$TMP/bin:$PATH" HOME="$P/home" DATA_DIR="$P/data" RESULTS_DIR="$P/study/results" LOG_DIR="$P/study/logs" TMP_DIR="$P/study/tmp" SAMPLE_SHEET="$P/sheet.tsv" \
      REQUIRE_CURATED_METADATA=0 THREADS=2 ASSEMBLY_MEMORY_GB=4 CAP_THREADS_TO_CPUS=0 PLASBENCH_SKIP_RESOURCE_CHECK=1 SHORT_READ_QC_MODE=off NO_COLOR=1 PLASBENCH_DB_DIR="$P/home/db" \
      env "$@" bash "$ROOT/scripts/03_assemble.sh" > "$P/stage.log" 2>&1 ) || rc=$?
    echo "$rc"
}

# 1. WORK_DIR=data: SPAdes works in the data folder
new_case
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=9p WORK_DIR=data)"
[[ "$rc" == "0" ]] || fail "exit $rc"
[[ "$(cat "$CALLS")" == "$P/data/s1/assembly" ]] || fail "WORK_DIR=data must assemble in the data folder: $(cat "$CALLS")"
grep -q "assembly work folder: $P/data/s1 (WORK_DIR=data" "$P/stage.log" || fail "the log must say where the assembly runs"
cp "$P/data/s1/contigs.fasta" "$TMP/contigs.data"; cp "$P/data/s1/assembly_graph.gfa" "$TMP/graph.data"
echo "WORK_DIR=data: assembled in the data folder, logged -> PASS"

# 2. a slow data folder: scratch, moved back, removed
new_case
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=9p)"
[[ "$rc" == "0" ]] || fail "exit $rc"
used="$(cat "$CALLS")"
[[ "$used" == "$P/home/.plasbench/scratch/study/s1."*"/asm" ]] || fail "SPAdes must run in the scratch folder: $used"
grep -q "assembly work folder: .*(fast local disk" "$P/stage.log" || fail "the log must say 'assembly work folder: <path> (fast local disk ...'"
[[ ! -e "$(dirname "$used")" ]] || fail "the scratch folder must be removed afterwards"
cmp "$P/data/s1/contigs.fasta" "$TMP/contigs.data" && cmp "$P/data/s1/assembly_graph.gfa" "$TMP/graph.data" || fail "the outputs must be byte-identical to a run in the data folder"
[[ -s "$P/data/s1/assembly/contigs.fasta" && -s "$P/data/s1/assembly/spades.log" && ! -e "$P/data/s1/assembly/K21" ]] || fail "results (contigs, log) are moved back, intermediate K21 is not"
grep -q "completed" "$P/study/results/assembly_status.tsv" || fail "status must be completed"
echo "slow data folder: assembled in scratch, results byte-identical, scratch removed, intermediates left behind -> PASS"

# 3. a fast data folder: no scratch (auto)
new_case
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=ext4)"
[[ "$(cat "$CALLS")" == "$P/data/s1/assembly" ]] || fail "a fast data folder needs no scratch: $(cat "$CALLS")"
echo "fast data folder (ext4): no scratch folder -> PASS"

# 4. crash leftover cleaned with a log line
new_case
mkdir -p "$P/home/.plasbench/scratch/study/s9.99999999/asm"; echo x > "$P/home/.plasbench/scratch/study/s9.99999999/asm/big"
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=9p)"
[[ ! -e "$P/home/.plasbench/scratch/study/s9.99999999" ]] || fail "the leftover of a dead run must be removed"
grep -q "removed a leftover scratch folder from an earlier run" "$P/stage.log" || fail "removal must be logged"
echo "crash leftover (dead pid) removed by the next run, logged -> PASS"

# 5. resume: contigs exist -> reused, no assembly, no scratch
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=9p)"
[[ "$(wc -l < "$CALLS" | tr -d ' ')" == "1" ]] || fail "a finished assembly must be reused, not repeated: $(cat "$CALLS")"
echo "resume: the finished assembly is reused -> PASS"

# 6. a failed assembly: its log is kept in the isolate folder, no scratch left, the failure recorded
new_case
rc="$(run_stage PLASBENCH_FORCE_FS_TYPE=9p FAIL=1)"
[[ -s "$P/data/s1/assembly/spades.log" ]] || fail "the failed attempt's spades.log must be kept for inspection"
[[ -z "$(ls -A "$P/home/.plasbench/scratch/study" 2>/dev/null)" ]] || fail "no scratch folder may be left after a failure"
grep -q "failed" "$P/study/results/assembly_status.tsv" || fail "the failure must be recorded"
echo "failed assembly: log kept, scratch removed, failure recorded -> PASS"
echo "ALL STAGE 3 SCRATCH TESTS PASSED"
