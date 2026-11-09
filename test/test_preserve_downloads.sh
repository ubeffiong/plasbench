#!/usr/bin/env bash
# Downloads are kept for future runs (PRESERVE_DOWNLOADS=1, default):
#   * after a download, <sample>/downloads.sha256 lists the reads and the read
#     files are read-only;
#   * a second run with the same DATA_DIR downloads nothing (verified, reused);
#   * a read file that no longer matches its checksum is fetched again.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT
export READ_SOURCE=sra

mkdir -p "$TMP/bin" "$TMP/data" "$TMP/logs"
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
outdir="" run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) outdir="\$2"; shift 2;; *) run="\$1"; shift;; esac; done
echo "\$run" >> "$TMP/prefetch_calls.log"
mkdir -p "\$outdir/\$run"; touch "\$outdir/\$run/\$run.sra"
EOF
cat > "$TMP/bin/fasterq-dump" <<'EOF'
#!/usr/bin/env bash
args=("$@"); outdir=""
for ((i=0;i<${#args[@]};i++)); do [[ "${args[$i]}" == "-O" ]] && outdir="${args[$((i+1))]}"; done
sra="$(basename "${args[-1]}")"; sra="${sra%.sra}"
printf '@r\nACGT\n+\nIIII\n' > "$outdir/${sra}_1.fastq"
printf '@r\nTGCA\n+\nIIII\n' > "$outdir/${sra}_2.fastq"
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/sheet.tsv"

run_stage() {
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 \
        bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}

: > "$TMP/prefetch_calls.log"
run_stage || { echo "FAIL: first download" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/downloads.sha256" ]] || { echo "FAIL: no downloads.sha256" >&2; exit 1; }
grep -q "SRR1_1.fastq.gz" "$TMP/data/s1/downloads.sha256" || { echo "FAIL: reads not in the manifest" >&2; exit 1; }
[[ ! -w "$TMP/data/s1/SRR1_1.fastq.gz" || "$(id -u)" == "0" ]] || { echo "FAIL: reads should be read-only" >&2; exit 1; }
echo "first run: downloads.sha256 written, reads read-only -> PASS"

: > "$TMP/prefetch_calls.log"
run_stage || { echo "FAIL: second run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ ! -s "$TMP/prefetch_calls.log" ]] || { echo "FAIL: verified reads were downloaded again" >&2; exit 1; }
grep -q "reads already present" "$TMP/stage.log" || { echo "FAIL: reuse not logged" >&2; exit 1; }
echo "second run with the same DATA_DIR: nothing downloaded, reads reused -> PASS"

chmod u+w "$TMP/data/s1/SRR1_1.fastq.gz"
printf 'corrupted' | gzip > "$TMP/data/s1/SRR1_1.fastq.gz"
: > "$TMP/prefetch_calls.log"
run_stage || { echo "FAIL: third run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "SRR1" "$TMP/prefetch_calls.log" || { echo "FAIL: a corrupted read file was not fetched again" >&2; exit 1; }
(cd "$TMP/data/s1" && sha256sum --quiet -c downloads.sha256) || { echo "FAIL: manifest not refreshed" >&2; exit 1; }
echo "a read file that fails its checksum is fetched again and the manifest refreshed -> PASS"
echo "ALL PRESERVE-DOWNLOADS TESTS PASSED"
