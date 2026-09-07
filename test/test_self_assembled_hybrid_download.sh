#!/usr/bin/env bash
# Regression for scripts/01_download.sh's new truth_source=self_assembled_hybrid
# branch: a row with no assembly_accession but a declared long_read_sra_run
# must fetch BOTH the short reads (as always) AND the long reads (new --
# every existing long-read/hybrid cohort row stages long_reads.fastq.gz
# manually; this is the one automated path), landing the long-read FASTQ at
# the SAME $LONG_READS_FILE location stage 7's tools already read. A row
# missing long_read_sra_run despite declaring self_assembled_hybrid must fail
# with a specific reason, not silently proceed as if it were operational.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data" "$TMP/logs"

# Handles both split-file (short, paired) and single-file (long) fetches:
# fasterq-dump's own --split-files flag is what actually decides this in
# real life, so the fake mirrors that rather than guessing from the run name.
cat > "$TMP/bin/prefetch" <<'EOF'
#!/usr/bin/env bash
outdir="" run=""
while [[ $# -gt 0 ]]; do case "$1" in -O) outdir="$2"; shift 2;; *) run="$1"; shift;; esac; done
echo "$run" >> "$PREFETCH_CALLS_LOG"
mkdir -p "$outdir/$run"; touch "$outdir/$run/$run.sra"
EOF
cat > "$TMP/bin/fasterq-dump" <<'EOF'
#!/usr/bin/env bash
outdir="" split=0
args=("$@")
for ((i=0;i<${#args[@]};i++)); do
    case "${args[$i]}" in
        -O) outdir="${args[$((i+1))]}" ;;
        --split-files) split=1 ;;
    esac
done
sra="$(basename "${args[-1]}")"; sra="${sra%.sra}"
echo "$sra split=$split" >> "$FASTERQ_CALLS_LOG"
if [[ "$split" -eq 1 ]]; then
    printf '@r\nACGT\n+\nIIII\n' > "$outdir/${sra}_1.fastq"
    printf '@r\nACGT\n+\nIIII\n' > "$outdir/${sra}_2.fastq"
else
    printf '@r\nACGTACGT\n+\nIIIIIIII\n' > "$outdir/${sra}.fastq"
fi
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump"

run_stage() {
    rm -rf "$TMP/data"; mkdir -p "$TMP/data"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 \
    PREFETCH_CALLS_LOG="$TMP/prefetch_calls.log" FASTERQ_CALLS_LOG="$TMP/fasterq_calls.log" \
    "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <sample> <column-index>
    awk -F'\t' -v s="$1" -v c="$2" '$1==s {print $c; exit}' "$TMP/results/download_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ttruth_source\tlong_read_sra_run\ns1\tNA\tSRR_SHORT\tself_assembled_hybrid\tSRR_LONG\n' > "$TMP/sheet.tsv"

: > "$TMP/prefetch_calls.log"; : > "$TMP/fasterq_calls.log"
run_stage || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field s1 2)" == "ok" ]] || { echo "FAIL: expected ok, got: $(status_field s1 2)" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
[[ -s "$TMP/data/s1/SRR_SHORT_1.fastq.gz" && -s "$TMP/data/s1/SRR_SHORT_2.fastq.gz" ]] || { echo "FAIL: expected paired short reads" >&2; exit 1; }
[[ -s "$TMP/data/s1/long_reads.fastq.gz" ]] || { echo "FAIL: expected long_reads.fastq.gz to be fetched" >&2; ls "$TMP/data/s1" >&2; exit 1; }
grep -q "^SRR_LONG split=0$" "$TMP/fasterq_calls.log" || { echo "FAIL: expected the long-read run fetched WITHOUT --split-files" >&2; cat "$TMP/fasterq_calls.log" >&2; exit 1; }
[[ ! -s "$TMP/data/s1/reference.fna" ]] || { echo "FAIL: no reference should be downloaded for a self_assembled_hybrid row" >&2; exit 1; }
echo "truth_source=self_assembled_hybrid fetches both short AND long reads, no reference download -> PASS"

# --- Missing long_read_sra_run despite declaring self_assembled_hybrid must
# fail with a specific reason, not proceed as if operational. ---
printf 'sample_id\tassembly_accession\tsra_run\ttruth_source\tlong_read_sra_run\ns1\tNA\tSRR_SHORT\tself_assembled_hybrid\t\n' > "$TMP/sheet.tsv"
: > "$TMP/prefetch_calls.log"; : > "$TMP/fasterq_calls.log"
if run_stage; then echo "FAIL: stage should abort (the only sample fails)" >&2; cat "$TMP/stage.log" >&2; exit 1; fi
[[ "$(status_field s1 2)" == "failed" ]] || { echo "FAIL: expected failed, got: $(status_field s1 2)" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
status_field s1 3 | grep -qi "requires long_read_sra_run" || { echo "FAIL: expected a specific long_read_sra_run reason" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
echo "a self_assembled_hybrid row with no long_read_sra_run fails with a specific reason -> PASS"

echo "ALL SELF-ASSEMBLED HYBRID DOWNLOAD TESTS PASSED"
