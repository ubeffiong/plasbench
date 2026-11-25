#!/usr/bin/env bash
# Stage 4 with a local working copy (WORK_DIR, scripts/04_run_tools.sh tool_local_out / stage4_local_reads, python/work_dir.py). Fake plasmidSPAdes; offline.
#   results and data folders on a slow mount (forced with PLASBENCH_FORCE_FS_TYPE=9p):
#     - the tool writes its folder in ~/.plasbench/scratch/<study>/<sample>.tools.<pid>/<tool> and reads a local copy of the trimmed reads
#     - its folder is copied back whole; the results folder is byte-identical to a WORK_DIR=data run; no work folder is left
#     - the second run REUSES the result (the fingerprint reads the reads' size:mtime, kept by the copy), and THREADS/MEMORY still do not matter
#   WORK_DIR=data: the tool works in the results folder and reads the data folder's reads, as before
#   a failed tool: its folder is still copied back for inspection, the failure is recorded
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; [[ -n "${LAST:-}" && -f "$LAST" ]] && tail -25 "$LAST" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat > "$TMP/bin/plasmidspades.py" <<EOF
#!/usr/bin/env bash
outdir="" r1=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; -1) r1="\$2"; shift 2;; *) shift;; esac; done
echo "out=\$outdir reads=\$r1" >> "$TMP/calls.log"
[[ -s "\$r1" ]] || { echo "no reads at \$r1" >&2; exit 1; }
mkdir -p "\$outdir/K21" "\$outdir/misc"
for i in 1 2 3 4 5; do echo "small file \$i" > "\$outdir/K21/f\$i"; done
echo "params" > "\$outdir/params.txt"
[[ "\${FAKE_FAIL:-0}" == "1" ]] && { echo "boom" >&2; exit 1; }
printf '>NODE_1_length_4_cov_9_component_0\nACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/plasmidspades.py"

new_case() {   # new_case NAME
    P="$TMP/$1"; mkdir -p "$P/home" "$P/study/results" "$P/study/logs" "$P/data/s1"
    printf '>contig1\nACGTACGTACGT\n' > "$P/data/s1/contigs.fasta"
    printf '@r1\nACGT\n+\nIIII\n' | gzip > "$P/data/s1/SRR1_1.trim.fastq.gz"
    printf '@r1\nACGT\n+\nIIII\n' | gzip > "$P/data/s1/SRR1_2.trim.fastq.gz"
    touch -d '2026-01-02 03:04:05' "$P/data/s1/SRR1_1.trim.fastq.gz" "$P/data/s1/SRR1_2.trim.fastq.gz"
    printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$P/sheet.tsv"
    : > "$TMP/calls.log"; LAST="$P/stage.log"
}
run_stage() {   # run_stage VAR=VALUE... -> prints the tool status
    PATH="$TMP/bin:$PATH" HOME="$P/home" DATA_DIR="$P/data" RESULTS_DIR="$P/study/results" LOG_DIR="$P/study/logs" SAMPLE_SHEET="$P/sheet.tsv" \
        REQUIRE_CURATED_METADATA=0 ONLY_TOOL=plasmidspades NO_COLOR=1 env "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$P/stage.log" 2>&1 || true
    awk -F'\t' '$1=="s1" && $2=="plasmidspades" {s=$3} END {print s}' "$P/study/results/tool_status.tsv" 2>/dev/null
}
tree_sums() { (cd "$1" && find . -type f ! -name '*.log' -print0 | sort -z | xargs -0 sha256sum); }

# 1. WORK_DIR=data: in place
new_case inplace
[[ "$(run_stage PLASBENCH_FORCE_FS_TYPE=9p WORK_DIR=data)" == completed ]] || fail "WORK_DIR=data run"
grep -q "out=$P/study/results/s1/plasmidspades reads=$P/data/s1/SRR1_1.trim.fastq.gz" "$TMP/calls.log" || { cat "$TMP/calls.log"; fail "WORK_DIR=data works in place"; }
echo "  ok    WORK_DIR=data: the tool works in the results folder and reads the data folder's reads"

# 2. slow folders: local work folder, copied back, identical
new_case local
[[ "$(run_stage PLASBENCH_FORCE_FS_TYPE=9p)" == completed ]] || fail "local run"
grep -q "out=$P/home/.plasbench/scratch/study/s1.tools.[0-9]*/plasmidspades reads=$P/home/.plasbench/scratch/study/s1.tools.[0-9]*/reads/SRR1_1.trim.fastq.gz" "$TMP/calls.log" \
    || { cat "$TMP/calls.log"; fail "the tool must work in the local folder and read the local reads"; }
grep -q "tool work folders: local" "$P/stage.log" || fail "the log says the tool folders are local"
[[ -z "$(ls -A "$P/home/.plasbench/scratch/study" 2>/dev/null)" ]] || fail "no work folder is left: $(ls "$P/home/.plasbench/scratch/study")"
[[ -f "$P/study/results/s1/plasmidspades/K21/f5" && -s "$P/study/results/s1/plasmidspades/contigs.fasta" ]] || fail "the whole tool folder is copied back"
diff <(tree_sums "$TMP/inplace/study/results/s1") <(tree_sums "$P/study/results/s1") || fail "the results folder differs from the in-place run"
echo "  ok    slow folders: the tool works locally on local reads, its folder is copied back, the results are byte-identical to the in-place run, nothing is left"

# 3. resume: reused, also with other THREADS / MEMORY
[[ "$(run_stage PLASBENCH_FORCE_FS_TYPE=9p PLASMIDSPADES_THREADS=3 PLASMIDSPADES_MEMORY_GB=7)" == reused ]] || fail "a second run must reuse the result (the reads' size:mtime are kept by the copy)"
[[ "$(wc -l < "$TMP/calls.log" | tr -d ' ')" == 1 ]] || fail "the tool must not run again"
echo "  ok    the second run reuses the result (fingerprint unchanged by the local copy; threads and memory ignored)"

# 4. a failure: the folder is still copied back, the failure recorded, nothing left
new_case failed
[[ "$(run_stage PLASBENCH_FORCE_FS_TYPE=9p FAKE_FAIL=1 TOOL_RETRIES=0)" == failed ]] || fail "the failure must be recorded"
[[ -f "$P/study/results/s1/plasmidspades/params.txt" ]] || fail "the failed tool's folder is copied back for inspection"
[[ -z "$(ls -A "$P/home/.plasbench/scratch/study" 2>/dev/null)" ]] || fail "no work folder is left after a failure"
echo "  ok    a failed tool: folder copied back for inspection, failure recorded, nothing left"

# 5. a leftover of a dead run is removed with a log line
new_case leftover
mkdir -p "$P/home/.plasbench/scratch/study/s1.tools.99999999/plasmidspades"
run_stage PLASBENCH_FORCE_FS_TYPE=9p > /dev/null
[[ ! -e "$P/home/.plasbench/scratch/study/s1.tools.99999999" ]] || fail "a dead run's work folder must be removed"
grep -q "removed a leftover work folder from an earlier run" "$P/stage.log" || fail "the removal is logged"
echo "  ok    a dead run's leftover is removed, logged"
echo "stage 4 local work folder checks passed"
