#!/usr/bin/env bash
# Stage 1 against a fake ENA (test/ena_fake_server.py) and a SRA Toolkit whose prefetch always fails with the TLS error from a real run:
#   1. READ_SOURCE=auto goes to ENA FIRST: the SRA Toolkit is not touched while ENA works. When ENA has no FASTQ for a run, prefetch is the fallback; after PREFETCH_FAIL_LIMIT failures it is
#      not tried again (the history is kept in ~/.plasbench across runs, here PLASBENCH_STATE_DIR); PREFETCH_FAIL_LIMIT=0 keeps trying it; READ_SOURCE=sra never skips it;
#      the failure is explained in plain words once per run
#   2. a big read set is NEVER skipped unless the person set MAX_RUN_DOWNLOAD_GB (then it is skipped and recorded with the reason); above WARN_RUN_DOWNLOAD_GB it only warns
#   3. a download that lasts longer than DOWNLOAD_PROGRESS_SECONDS puts a progress line in the run log
# (Changed deliberately with the ENA-first change: this test used to expect prefetch to be tried first for the first two isolates.)
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
echo "2026-11-21T17:46:40 sys: connection failed while opening file within cryptographic module - Failed to create TLS stream for www.ncbi.nlm.nih.gov" >&2
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
        NETWORK_RETRIES=1 NETWORK_RETRY_DELAY_SECONDS=0 PLASBENCH_RETRY_SLEEP=0 ENA_RETRY_DELAY_SECONDS=0 ENA_CHUNK_BACKOFF_SECONDS=0 ENA_SIZE_TIMEOUT=10 PLASBENCH_STATE_DIR="$TMP/state" DOWNLOAD_TMP_DIR=data "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}

printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\ns3\tNA\tSRR3\ns4\tNA\tSRR4\n' > "$TMP/sheet.tsv"

# --- 1. ENA first; the SRA Toolkit as the fallback, with a history that survives runs ---
start_server 0
rm -rf "$TMP/state"
run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=2 || { echo "FAIL: stage 1 against the fake ENA" >&2; cat "$TMP/stage.log" >&2; exit 1; }
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "0" ]] || { echo "FAIL: with ENA working, READ_SOURCE=auto must not touch the SRA Toolkit, prefetch ran $calls time(s)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
for s in s1 s2 s3 s4; do
    run="SRR${s#s}"
    [[ -s "$TMP/data/$s/${run}_1.fastq.gz" && -s "$TMP/data/$s/${run}_2.fastq.gz" ]] || { echo "FAIL: $s has no reads" >&2; cat "$TMP/stage.log" >&2; exit 1; }
done
echo "READ_SOURCE=auto fetches from ENA first and never calls prefetch while ENA works -> PASS"

printf 'sample_id\tassembly_accession\tsra_run\nn1\tNA\tSRRNOFQ1\nn2\tNA\tSRRNOFQ2\nn3\tNA\tSRRNOFQ3\nn4\tNA\tSRRNOFQ4\n' > "$TMP/sheet.tsv"
rm -rf "$TMP/state"
run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=2 || true      # ENA has no FASTQ for these runs and prefetch fails: every isolate fails, the stage ends with an error
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "2" ]] || { echo "FAIL: prefetch should be tried for the first two isolates only, it ran $calls time(s)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "ENA has no paired FASTQ for SRRNOFQ1: using the SRA Toolkit" "$TMP/stage.log" || { echo "FAIL: the log should say why the SRA Toolkit is used" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "not trying the SRA Toolkit for SRRNOFQ3" "$TMP/stage.log" || { echo "FAIL: the log should say the toolkit is not tried again after two failures" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "Failed to create TLS stream" "$TMP/stage.log" || { echo "FAIL: the log should carry the reason prefetch failed (its last output line)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(grep -c "could not open a TLS" "$TMP/stage.log")" == "1" ]] || { echo "FAIL: the TLS failure must be explained exactly once per run" >&2; cat "$TMP/stage.log" >&2; exit 1; }
{ grep -q "proxy" "$TMP/stage.log" && grep -q "vdb-config" "$TMP/stage.log"; } || { echo "FAIL: the explanation should say what to check (proxy, CA certificates, vdb-config)" >&2; exit 1; }
[[ -s "$TMP/state/prefetch_history.json" ]] || { echo "FAIL: the prefetch history should be kept under PLASBENCH_STATE_DIR (~/.plasbench)" >&2; exit 1; }
echo "ENA without FASTQ falls back to prefetch; after two failures it is skipped; the TLS failure is explained once; the history is stored -> PASS"

run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=2 || true      # a LATER run: the history is still there
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "0" ]] || { echo "FAIL: a later run must not retry a known-broken SRA Toolkit, prefetch ran $calls time(s)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "a later run does not retry a toolkit known to be broken (history persisted) -> PASS"

run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=0 || true
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "4" ]] || { echo "FAIL: PREFETCH_FAIL_LIMIT=0 should try prefetch for every isolate, it ran $calls time(s)" >&2; exit 1; }
echo "PREFETCH_FAIL_LIMIT=0 still tries prefetch for every isolate that needs it -> PASS"

run_stage env READ_SOURCE=sra PREFETCH_FAIL_LIMIT=2 || true
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "4" ]] || { echo "FAIL: READ_SOURCE=sra must try prefetch for every isolate, it ran $calls time(s)" >&2; exit 1; }
echo "READ_SOURCE=sra never skips prefetch -> PASS"

# the history is ignored when it was written by another PlasBench or sra-tools version
python3 - "$TMP/state/prefetch_history.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["version"] = "0.0.0|other"; json.dump(d, open(sys.argv[1], "w"))
PY
run_stage env READ_SOURCE=auto PREFETCH_FAIL_LIMIT=2 || true
calls="$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')"
[[ "$calls" == "2" ]] || { echo "FAIL: history from another version must be ignored (prefetch should run twice again), it ran $calls time(s)" >&2; exit 1; }
echo "history written by another PlasBench/sra-tools version is ignored -> PASS"

# --- 2. the size gate ---
printf 'sample_id\tassembly_accession\tsra_run\nbig\tNA\tSRRBIG\nsmall\tNA\tSRR1\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=auto MAX_RUN_DOWNLOAD_GB=5 || { echo "FAIL: stage 1 must go on when one isolate is over the limit" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "reads SRRBIG: 24.0 GB compressed" "$TMP/stage.log" || { echo "FAIL: the log should state the isolate's read size" >&2; cat "$TMP/stage.log" >&2; exit 1; }
awk -F'\t' '$1=="big" && $2=="failed" && $3 ~ /above MAX_RUN_DOWNLOAD_GB=5/' "$TMP/results/download_status.tsv" | grep -q . || { echo "FAIL: the oversized isolate should be recorded with the reason" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
awk -F'\t' '$1=="small" && $2=="ok"' "$TMP/results/download_status.tsv" | grep -q . || { echo "FAIL: the small isolate should still download" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
[[ ! -e "$TMP/data/big/SRRBIG_1.fastq.gz.part" ]] || { echo "FAIL: nothing should be downloaded for the skipped isolate" >&2; exit 1; }
echo "an isolate above MAX_RUN_DOWNLOAD_GB is skipped with a recorded reason and the rest downloads -> PASS"

run_stage env READ_SOURCE=auto || true     # no limit: it warns, then TRIES (and fails here, the fake serves no real files for SRRBIG)
grep -q "SRRBIG is a large read set (24.0 GB to download)" "$TMP/stage.log" || { echo "FAIL: a read set above WARN_RUN_DOWNLOAD_GB should warn" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "this isolate is not skipped" "$TMP/stage.log" || { echo "FAIL: the warning should say the isolate is not skipped" >&2; exit 1; }
! grep -q "skipped by choice" "$TMP/results/download_status.tsv" || { echo "FAIL: nothing may be skipped for size when MAX_RUN_DOWNLOAD_GB is not set" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
! grep -qi "removing this isolate from the sheet\|MAX_RUN_DOWNLOAD_GB skips" "$TMP/stage.log" || { echo "FAIL: the log must not push the person to skip or remove the isolate" >&2; exit 1; }
[[ -s "$TMP/logs/big.ena.log" ]] || { echo "FAIL: the big isolate should have been attempted from ENA (its log exists)" >&2; exit 1; }
echo "a large read set warns (default 5 GB), is attempted, and is never skipped when no limit is set -> PASS"

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
