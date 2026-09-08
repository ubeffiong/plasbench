#!/usr/bin/env bash
# Regression for scripts/03_assemble.sh's new RUN_DIFFICULTY_FEATURES wiring
# (python/compute_difficulty_features.py): computed here, not in
# 02_truth.sh, because assembly_graph.gfa does not exist until this stage
# produces it. Confirms: (1) off by default, no file written at all; (2) on,
# and truth.tsv already exists (stage 2 ran first) -> the file IS written,
# on both a freshly-completed AND a reused assembly (a real bug this test
# specifically pins: the reused-assembly early-return must not skip this);
# (3) on, but truth.tsv does NOT exist yet -> warns and skips, never a hard
# stage failure. compute_difficulty_features.py's own external-tool logic
# (mash/minimap2/deadends) is unit-tested separately
# (test_compute_difficulty_features.py); this test is about the stage-3
# wiring around it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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
mkdir -p "$outdir"
printf '>contig1\nACGTACGTACGT\n' > "$outdir/contigs.fasta"
printf 'H\tVN:Z:1.0\nS\t1\tACGTACGTACGT\n' > "$outdir/assembly_graph_with_scaffolds.gfa"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py"

setup_sample() {
    local sample="$1"
    mkdir -p "$TMP/data/$sample"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/$sample/SRR_1.fastq.gz"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/$sample/SRR_2.fastq.gz"
}
write_truth() {
    local sample="$1"
    printf '>chr1\nACGTACGTACGT\n' > "$TMP/data/$sample/reference.fna"
    printf 'sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t12\n' > "$TMP/data/$sample/truth.tsv"
}

run_stage() {
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 ASSEMBLER=spades \
    "$@" bash "$ROOT/scripts/03_assemble.sh" > "$TMP/stage.log" 2>&1
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCF_1\tSRR\n' > "$TMP/sheet.tsv"

# --- Off by default: no difficulty_features.tsv at all. ---
rm -rf "$TMP/data" "$TMP/results"; setup_sample s1; write_truth s1
run_stage || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ ! -e "$TMP/data/s1/difficulty_features.tsv" ]] || { echo "FAIL: RUN_DIFFICULTY_FEATURES=0 (default) should write nothing" >&2; exit 1; }
echo "RUN_DIFFICULTY_FEATURES=0 (default) computes nothing -> PASS"

# --- On, truth.tsv already present -> written on a FRESH assembly. ---
rm -rf "$TMP/data" "$TMP/results"; setup_sample s1; write_truth s1
run_stage env RUN_DIFFICULTY_FEATURES=1 || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/difficulty_features.tsv" ]] || { echo "FAIL: expected difficulty_features.tsv on a fresh assembly" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "^sample_id" "$TMP/data/s1/difficulty_features.tsv" || { echo "FAIL: expected a real header row" >&2; cat "$TMP/data/s1/difficulty_features.tsv" >&2; exit 1; }
echo "RUN_DIFFICULTY_FEATURES=1 writes difficulty_features.tsv on a fresh assembly -> PASS"

# --- On, assembly already REUSED (contigs.fasta present from a prior run)
# -- the file must still get written, not skipped because assembly itself
# short-circuited via its own "reused" early return. ---
rm -f "$TMP/data/s1/difficulty_features.tsv"
run_stage env RUN_DIFFICULTY_FEATURES=1 || { echo "FAIL: stage should succeed on a reused assembly" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "reused" "$TMP/results/assembly_status.tsv" || { echo "FAIL: expected s1's assembly to be recorded as reused" >&2; cat "$TMP/results/assembly_status.tsv" >&2; exit 1; }
[[ -s "$TMP/data/s1/difficulty_features.tsv" ]] || { echo "FAIL: expected difficulty_features.tsv even though assembly itself was reused" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "difficulty features are still computed on a REUSED assembly, not silently skipped -> PASS"

# --- On, but no truth.tsv yet (stage 2 never ran) -> warns and skips,
# never a hard stage failure. ---
rm -rf "$TMP/data" "$TMP/results"; setup_sample s1  # no write_truth this time
run_stage env RUN_DIFFICULTY_FEATURES=1 || { echo "FAIL: missing truth.tsv should not abort the whole stage" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ ! -e "$TMP/data/s1/difficulty_features.tsv" ]] || { echo "FAIL: expected no difficulty_features.tsv without a truth reference" >&2; exit 1; }
grep -qi "no truth reference yet" "$TMP/stage.log" || { echo "FAIL: expected a clear warning naming the missing truth reference" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "RUN_DIFFICULTY_FEATURES=1 with no truth.tsv yet warns and skips, not a hard failure -> PASS"

echo "ALL DIFFICULTY FEATURES STAGE TESTS PASSED"
