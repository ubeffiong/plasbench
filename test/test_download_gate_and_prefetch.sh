#!/usr/bin/env bash
# Stage 1 against a fake ENA (test/ena_fake_server.py) and a SRA Toolkit whose prefetch always fails:
#   1. after PREFETCH_FAIL_LIMIT isolates in a row where prefetch failed and ENA worked, later isolates go to ENA first (no more ~1 minute lost per isolate);
#      the log says why prefetch failed; PREFETCH_FAIL_LIMIT=0 keeps trying prefetch first; READ_SOURCE=sra never skips it
#   2. an isolate whose reads are above MAX_RUN_DOWNLOAD_GB is skipped and recorded with the reason; above WARN_RUN_DOWNLOAD_GB it warns
#   3. a download that lasts longer than DOWNLOAD_PROGRESS_SECONDS puts a progress line in the run log
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() { [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }

start_server() {
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
    rm -f "$TMP/port"
    python3 "$HERE/ena_fake_server.py" "$TMP/port" "${1:-0}" &
    SERVER_PID=$!
    for _ in $(seq 1 100); do [[ -s "$TMP/port" ]] && break; sleep 0.1; done
    [[ -s "$TMP/port" ]] || { echo "FAIL: the fake ENA server did not start" >&2; exit 1; }
    PORT="$(cat "$TMP/port")"
}

mkdir -p "$TMP/bin"
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) shift 2;; *) run="\$1"; shift;; esac; done
echo "\$run" >> "$TMP/prefetch_calls.log"
echo "2026-11-18T07:46:40 err: TLS handshake failed while contacting NCBI (simulated)" >&2
exit 1
EOF
cat > "$TMP/bin/fasterq-dump" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump"

run_stage() {   # run_stage ENV=... : one fresh stage-1 run against the fake ENA
    rm -rf "$TMP/data" "$TMP/results" "$TMP/logs"; mkdir -p "$TMP/data" "$TMP/logs"
    : > "$TMP/prefetch_calls.log"
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/sheet.tsv" \
        REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 ENA_USE_ARIA2=0 ENA_PORTAL_URL="http://127.0.0.1:$PORT/filereport" \
        NETWORK_RETRIES=1 NETWORK_RETRY_DELAY_SECONDS=0 PLASBENCH_RETRY_SLEEP=0 ENA_SIZE_TIMEOUT=10 "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\ns3\tNA\tSRR3\ns4\tNA\tSRR4\n' > "$TMP/sheet.tsv"

# --- 1. the circuit breaker ---
start_server 0
run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=2 || { echo "FAIL: stage 1 against the fake ENA" >&2; cat "$TMP/stage.log" >&2; exit 1; }
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "2" ]] || { echo "FAIL: prefetch should be tried for the first two isolates only, it ran $calls time(s)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
for s in s1 s2 s3 s4; do
    run="SRR${s#s}"
    [[ -s "$TMP/data/$s/${run}_1.fastq.gz" && -s "$TMP/data/$s/${run}_2.fastq.gz" ]] || { echo "FAIL: $s has no reads" >&2; cat "$TMP/stage.log" >&2; exit 1; }
done
grep -q "fetching SRR3 from ENA first" "$TMP/stage.log" || grep -q "from ENA first" "$TMP/stage.log" || { echo "FAIL: the log should say later isolates go to ENA first" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "TLS handshake failed" "$TMP/stage.log" || { echo "FAIL: the log should carry the reason prefetch failed (its last output line)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "prefetch is skipped for the rest of the run after two failures in a row, and the log says why it failed -> PASS"

run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=0 || { echo "FAIL: stage 1 with PREFETCH_FAIL_LIMIT=0" >&2; cat "$TMP/stage.log" >&2; exit 1; }
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "4" ]] || { echo "FAIL: PREFETCH_FAIL_LIMIT=0 should try prefetch for every isolate, it ran $calls time(s)" >&2; exit 1; }
echo "PREFETCH_FAIL_LIMIT=0 still tries prefetch first for every isolate -> PASS"

run_stage env READ_SOURCE=sra PREFETCH_FAIL_LIMIT=2 || true
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "4" ]] || { echo "FAIL: READ_SOURCE=sra must try prefetch for every isolate, it ran $calls time(s)" >&2; exit 1; }
echo "READ_SOURCE=sra never skips prefetch -> PASS"

# --- 2. the size gate ---
printf 'sample_id\tassembly_accession\tsra_run\nbig\tNA\tSRRBIG\nsmall\tNA\tSRR1\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=auto MAX_RUN_DOWNLOAD_GB=5 || { echo "FAIL: stage 1 must go on when one isolate is over the limit" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "reads SRRBIG: 24.0 GB compressed" "$TMP/stage.log" || { echo "FAIL: the log should state the isolate's read size" >&2; cat "$TMP/stage.log" >&2; exit 1; }
awk -F'\t' '$1=="big" && $2=="failed" && $3 ~ /above MAX_RUN_DOWNLOAD_GB=5/' "$TMP/results/download_status.tsv" | grep -q . || { echo "FAIL: the oversized isolate should be recorded with the reason" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
awk -F'\t' '$1=="small" && $2=="ok"' "$TMP/results/download_status.tsv" | grep -q . || { echo "FAIL: the small isolate should still download" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
[[ ! -e "$TMP/data/big/SRRBIG_1.fastq.gz.part" ]] || { echo "FAIL: nothing should be downloaded for the skipped isolate" >&2; exit 1; }
echo "an isolate above MAX_RUN_DOWNLOAD_GB is skipped with a recorded reason and the rest downloads -> PASS"

run_stage env READ_SOURCE=auto || true     # no limit: it warns, then tries (and fails here, the fake serves no files for SRRBIG)
grep -q "SRRBIG is a large read set (24.0 GB)" "$TMP/stage.log" || { echo "FAIL: a read set above WARN_RUN_DOWNLOAD_GB should warn" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "a large read set warns (default 5 GB) when no limit is set -> PASS"

# --- 3. progress lines in the run log ---
start_server 3
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=ena DOWNLOAD_PROGRESS_SECONDS=1 || { echo "FAIL: stage 1 with a slow ENA" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -E "^\[[0-9-]+ [0-9:]+\]   SRR1: " "$TMP/stage.log" | grep -qv "reads SRR1" || { echo "FAIL: a download longer than DOWNLOAD_PROGRESS_SECONDS should log a progress line" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "a slow download puts progress lines in the run log -> PASS"

run_stage env READ_SOURCE=ena DOWNLOAD_PROGRESS_SECONDS=0 || { echo "FAIL: stage 1 with progress off" >&2; exit 1; }
! grep -E "^\[[0-9-]+ [0-9:]+\]   SRR1: " "$TMP/stage.log" || { echo "FAIL: DOWNLOAD_PROGRESS_SECONDS=0 should print no progress lines" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "DOWNLOAD_PROGRESS_SECONDS=0 prints none -> PASS"
echo "ALL DOWNLOAD GATE AND PREFETCH TESTS PASSED"
