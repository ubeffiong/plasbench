#!/usr/bin/env bash
# Regression: same fail-fast-by-default / real-overlap-when-parallel contract
# as stage 1's download, applied to stage 3's assembly. Also checks the
# oversubscription advisory fires (never blocks) when the configured
# concurrency clearly exceeds the host, using a fake `nproc`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DELAY=0.4
mkdir -p "$TMP/bin"
cat > "$TMP/bin/fastp" <<EOF
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ \$# -gt 0 ]]; do case "\$1" in -i) i1="\$2"; shift 2;; -I) i2="\$2"; shift 2;; -o) o1="\$2"; shift 2;; -O) o2="\$2"; shift 2;; *) shift;; esac; done
cp "\$i1" "\$o1"; cp "\$i2" "\$o2"
EOF
# FAIL_SAMPLE (an env var) names one sample whose spades.py should fail.
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
sleep $DELAY
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
sample="\$(basename "\$(dirname "\$outdir")")"
echo "\$sample" >> "$TMP/spades_calls.log"
if [[ "\$sample" == "\${FAIL_SAMPLE:-__none__}" ]]; then echo "simulated SPAdes failure" >&2; exit 1; fi
mkdir -p "\$outdir"; printf '>contig1\nACGTACGTACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py"

setup_sample() {
    local sample="$1"
    mkdir -p "$TMP/data/$sample"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/$sample/SRR_1.fastq.gz"
    printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/$sample/SRR_2.fastq.gz"
}
run_stage() {
    PATH="$TMP/bin:$PATH" \
        DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
        "$@" bash "$ROOT/scripts/03_assemble.sh" > "$TMP/stage.log" 2>&1
}
now_ms() { date +%s%N | cut -c1-13; }

mkdir -p "$TMP/logs" "$TMP/results" "$TMP/tmp"  # stage 0 normally creates these
setup_sample s1; setup_sample s2; setup_sample s3
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\ns3\tNA\tSRR\n' > "$TMP/sheet.tsv"

# --- default (MAX_PARALLEL_SAMPLES=1): fail-fast, one sample at a time. ---
: > "$TMP/spades_calls.log"
if run_stage env FAIL_SAMPLE=s1 MAX_PARALLEL_SAMPLES=1; then
    echo "FAIL: stage should exit non-zero on an assembly failure" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
called="$(cat "$TMP/spades_calls.log" | tr '\n' ' ')"
[[ "$called" == "s1 " ]] || { echo "FAIL: default mode should stop after the first failure, spades called for: $called" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "MAX_PARALLEL_SAMPLES=1 (default) still fails fast on assembly failure -> PASS"

for s in s1 s2 s3; do rm -f "$TMP/data/$s/${s}_1.trim.fastq.gz" "$TMP/data/$s/SRR_1.trim.fastq.gz" "$TMP/data/$s/SRR_2.trim.fastq.gz" "$TMP/data/$s/contigs.fasta"; rm -rf "$TMP/data/$s/assembly"; done

# --- parallel overlap: three samples must assemble concurrently. ---
start=$(now_ms)
run_stage env MAX_PARALLEL_SAMPLES=1 || { echo "FAIL: sequential baseline should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
end=$(now_ms)
sequential_ms=$(( end - start ))

for s in s1 s2 s3; do rm -f "$TMP/data/$s/SRR_1.trim.fastq.gz" "$TMP/data/$s/SRR_2.trim.fastq.gz" "$TMP/data/$s/contigs.fasta"; rm -rf "$TMP/data/$s/assembly"; done

start=$(now_ms)
run_stage env MAX_PARALLEL_SAMPLES=3 || { echo "FAIL: parallel run should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
end=$(now_ms)
parallel_ms=$(( end - start ))
for s in s1 s2 s3; do [[ -s "$TMP/data/$s/contigs.fasta" ]] || { echo "FAIL: sample $s missing contigs" >&2; exit 1; }; done
[[ "$parallel_ms" -lt "$(( sequential_ms * 3 / 4 ))" ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=3 (${parallel_ms}ms) was not clearly faster than sequential (${sequential_ms}ms)" >&2
    exit 1; }
echo "MAX_PARALLEL_SAMPLES=3 overlaps independent assemblies (${parallel_ms}ms vs ${sequential_ms}ms sequential) -> PASS"

for s in s1 s2 s3; do rm -f "$TMP/data/$s/SRR_1.trim.fastq.gz" "$TMP/data/$s/SRR_2.trim.fastq.gz" "$TMP/data/$s/contigs.fasta"; rm -rf "$TMP/data/$s/assembly"; done

# --- one sample failing under concurrency must not lose its siblings. ---
: > "$TMP/spades_calls.log"
if run_stage env FAIL_SAMPLE=s2 MAX_PARALLEL_SAMPLES=3; then
    echo "FAIL: stage should exit non-zero when one sample's assembly fails" >&2; cat "$TMP/stage.log" >&2; exit 1
fi
grep -q "s2" "$TMP/stage.log" || { echo "FAIL: failure report did not name sample s2" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/contigs.fasta" ]] || { echo "FAIL: sibling sample s1 should still have assembled" >&2; exit 1; }
[[ -s "$TMP/data/s3/contigs.fasta" ]] || { echo "FAIL: sibling sample s3 should still have assembled" >&2; exit 1; }
echo "one sample's assembly failure under concurrency does not lose its siblings -> PASS"

# --- resource-oversubscription advisory: warns, never blocks. ---
mkdir -p "$TMP/bin2"
printf '#!/usr/bin/env bash\necho 2\n' > "$TMP/bin2/nproc"; chmod +x "$TMP/bin2/nproc"
for s in s1 s2 s3; do rm -f "$TMP/data/$s/SRR_1.trim.fastq.gz" "$TMP/data/$s/SRR_2.trim.fastq.gz" "$TMP/data/$s/contigs.fasta"; rm -rf "$TMP/data/$s/assembly"; done
PATH="$TMP/bin2:$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 THREADS=8 MAX_PARALLEL_SAMPLES=3 \
    bash "$ROOT/scripts/03_assemble.sh" > "$TMP/stage2.log" 2>&1
grep -qi "oversubscription\|only 2 CPU core" "$TMP/stage2.log" || {
    echo "FAIL: expected an oversubscription warning with 3x8=24 threads requested against 2 fake cores" >&2
    cat "$TMP/stage2.log" >&2; exit 1; }
for s in s1 s2 s3; do [[ -s "$TMP/data/$s/contigs.fasta" ]] || { echo "FAIL: the advisory must not have blocked assembly" >&2; exit 1; }; done
echo "oversubscription advisory warns without blocking assembly -> PASS"

echo "ALL ASSEMBLE PARALLEL TESTS PASSED"
