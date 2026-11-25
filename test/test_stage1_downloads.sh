#!/usr/bin/env bash
# Stage 1 (scripts/01_download.sh) against the fake ENA (test/ena_fake_server.py), for the download-robustness behaviour:
#   1. every ENA attempt is APPENDED to logs/<sample>.ena.log under a numbered header (an earlier failure is never overwritten)
#   2. READ_SOURCE=auto: ENA failing after its retries falls back to the SRA Toolkit and says so; READ_SOURCE=ena uses ENA only (no prefetch, the isolate fails with the log named)
#   3. MAX_PARALLEL_DOWNLOADS: default 1; 2 downloads two isolates at once and splits ENA_MAX_CONNECTIONS between them
#   4. the stage prints one summary line (bytes, time, MB/s, ENA/SRA counts, retries, resumes) and writes results/download_progress.json
#   6. state across runs (READ_DEPTH_CAP_X): reads that are a capped prefix are fetched again when the cap is now off, with one plain line; whole files are kept when a cap is set
#   5. the final read files are read-only and NOT executable (0444), the downloaded files carry no .part leftovers
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() { [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }

rm -f "$TMP/port"
python3 "$HERE/ena_fake_server.py" "$TMP/port" 0 &
SERVER_PID=$!
for _ in $(seq 1 100); do [[ -s "$TMP/port" ]] && break; sleep 0.1; done
[[ -s "$TMP/port" ]] || { echo "FAIL: the fake ENA server did not start" >&2; exit 1; }
PORT="$(cat "$TMP/port")"

mkdir -p "$TMP/bin"
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
[[ "\$1" == "--version" ]] && { echo "prefetch : 3.0.0"; exit 0; }   # the history keys on the toolkit version: asking is not a download
run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) shift 2;; *) run="\$1"; shift;; esac; done
echo "\$run" >> "$TMP/prefetch_calls.log"
echo "sys: connection failed while opening file within cryptographic module - Failed to create TLS stream for www.ncbi.nlm.nih.gov" >&2
exit 1
EOF
cat > "$TMP/bin/fasterq-dump" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump"

run_stage() {
    if [[ "${KEEP_DATA:-0}" != "1" ]]; then rm -rf "$TMP/data"; fi
    rm -rf "$TMP/results" "$TMP/state"; mkdir -p "$TMP/data"
    [[ "${KEEP_LOGS:-0}" == "1" ]] || { rm -rf "$TMP/logs"; mkdir -p "$TMP/logs"; }
    : > "$TMP/prefetch_calls.log"
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/sheet.tsv" \
        REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 ENA_USE_ARIA2=0 ENA_PORTAL_URL="http://127.0.0.1:$PORT/filereport" \
        NETWORK_RETRIES=1 NETWORK_RETRY_DELAY_SECONDS=0 PLASBENCH_RETRY_SLEEP=0 ENA_RETRY_DELAY_SECONDS=0 ENA_CHUNK_BACKOFF_SECONDS=0 ENA_SIZE_TIMEOUT=10 \
        PLASBENCH_STATE_DIR="$TMP/state" DOWNLOAD_TMP_DIR=data "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}
fail() { echo "FAIL: $1" >&2; cat "$TMP/stage.log" >&2; exit 1; }

# --- 1 + 2: ENA fails for the run (HTTP 500 on every file) ---
printf 'sample_id\tassembly_accession\tsra_run\nf1\tNA\tSRRFAIL1\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=auto || true
grep -q "ENA failed for SRRFAIL1 after its retries: trying the SRA Toolkit" "$TMP/stage.log" || fail "an ENA failure should fall back to the SRA Toolkit and say so (READ_SOURCE=auto)"
[[ "$(wc -l < "$TMP/prefetch_calls.log" | tr -d ' ')" == "1" ]] || fail "the SRA Toolkit should have been tried once"
grep -q '^===== attempt 1,' "$TMP/logs/f1.ena.log" || fail "the ENA log should start with a numbered attempt header"
KEEP_LOGS=1 run_stage env READ_SOURCE=auto || true
[[ "$(grep -c '^===== attempt ' "$TMP/logs/f1.ena.log")" == "2" ]] || { cat "$TMP/logs/f1.ena.log" >&2; fail "the second attempt must be appended to the same log, not overwrite it"; }
grep -q '^===== attempt 2,' "$TMP/logs/f1.ena.log" || fail "the second attempt's header should be numbered 2"
echo "ENA failure -> SRA Toolkit fallback is announced; every attempt is kept in logs/<sample>.ena.log with a numbered header -> PASS"

run_stage env READ_SOURCE=ena || true
[[ ! -s "$TMP/prefetch_calls.log" ]] || fail "READ_SOURCE=ena must never call prefetch"
awk -F'\t' '$1=="f1" && $2=="failed" && $3 ~ /ENA download failed for SRRFAIL1/' "$TMP/results/download_status.tsv" | grep -q . || { cat "$TMP/results/download_status.tsv" >&2; fail "READ_SOURCE=ena: the isolate should be recorded as failed with the ENA reason"; }
echo "READ_SOURCE=ena uses ENA only and records the failure -> PASS"

# --- 3 + 4 + 5: two isolates, two downloads at once ---
printf 'sample_id\tassembly_accession\tsra_run\np1\tNA\tSRR1\np2\tNA\tSRR2\np3\tNA\tSRR3\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=auto || fail "stage 1 with three isolates"
grep -q "at most 16 connections in total" "$TMP/logs/p1.ena.log" || fail "the default budget is 16 connections in total when one isolate is downloaded at a time"
run_stage env READ_SOURCE=auto MAX_PARALLEL_DOWNLOADS=2 ENA_MAX_CONNECTIONS=16 || fail "stage 1 with MAX_PARALLEL_DOWNLOADS=2"
grep -q "at most 8 connections in total" "$TMP/logs/p1.ena.log" || fail "MAX_PARALLEL_DOWNLOADS=2 should give each download half of ENA_MAX_CONNECTIONS (8)"
for s in p1 p2 p3; do
    run="SRR${s#p}"
    [[ -s "$TMP/data/$s/${run}_1.fastq.gz" && -s "$TMP/data/$s/${run}_2.fastq.gz" ]] || fail "$s has no reads"
done
echo "MAX_PARALLEL_DOWNLOADS=2 downloads in parallel and splits the connection budget -> PASS"
grep -q "^\[[0-9-]* [0-9:]*\] Download summary: " "$TMP/stage.log" || fail "the stage should print a one-line download summary"
grep -q "isolates via ENA 3, via the SRA Toolkit 0" "$TMP/stage.log" || fail "the summary should count the isolates per source"
python3 - "$TMP/results/download_progress.json" <<'PY' || fail "results/download_progress.json should list every run as done with all bytes counted"
import json, sys
d = json.load(open(sys.argv[1]))["isolates"]
assert sorted(d) == ["SRR1", "SRR2", "SRR3"], sorted(d)
for run, e in d.items():
    assert e["state"] == "done" and e["done_bytes"] == e["total_bytes"] > 0, (run, e)
PY
echo "the stage summary line and results/download_progress.json are written -> PASS"
mode="$(stat -c %a "$TMP/data/p1/SRR1_1.fastq.gz")"
[[ "$mode" == "444" ]] || fail "the final read files should be 0444 (read-only, not executable), they are $mode"
[[ -z "$(find "$TMP/data" -name '*.part*' -print -quit)" ]] || fail "no .part or .part.state leftovers should remain"
echo "final files are 0444 and no .part leftovers remain -> PASS"

# --- 6. state across runs: capped reads on disk, then the cap is switched off; whole reads on disk, then a cap is set ---
printf 'sample_id\tassembly_accession\tsra_run\nc1\tNA\tSRR1\n' > "$TMP/sheet.tsv"
run_stage env READ_SOURCE=auto || fail "stage 1 for the state-change test"
python3 - "$TMP/data/c1/SRR1.ena_provenance.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["read_depth_cap"] = {"applied": True, "cap_x": 100, "estimated_depth": 100, "target_pairs": 10}
json.dump(d, open(p, "w"))
PY
( cd "$TMP/data/c1" && chmod u+w SRR1_1.fastq.gz SRR1_2.fastq.gz && sha256sum SRR1_1.fastq.gz SRR1_2.fastq.gz SRR1.ena_provenance.json > downloads.sha256 )
KEEP_DATA=1 run_stage env READ_SOURCE=auto READ_DEPTH_CAP_X=100 || fail "stage 1 with the same cap again"
grep -q "SRR1: reads on disk are a 100x prefix; READ_DEPTH_CAP_X is 100, so they are deep enough and are kept" "$TMP/stage.log" || fail "capped reads and the same cap: they should be kept, with a line saying so"
! grep -q "fetching SRR1 from ENA" "$TMP/stage.log" || fail "capped reads that are deep enough must not be downloaded again"
KEEP_DATA=1 run_stage env READ_SOURCE=auto READ_DEPTH_CAP_X=off || fail "stage 1 with the cap switched off"
grep -q "SRR1: reads on disk are a 100x prefix; READ_DEPTH_CAP_X is now off, fetching the whole file" "$TMP/stage.log" || fail "capped -> off: the one plain line is missing"
grep -q "fetching SRR1 from ENA" "$TMP/stage.log" || fail "capped -> off: the whole file should be fetched again"
python3 - "$TMP/data/c1/SRR1.ena_provenance.json" <<'PY' || fail "after the refetch the provenance should say whole files"
import json, sys
assert json.load(open(sys.argv[1]))["read_depth_cap"]["applied"] is False
PY
( cd "$TMP/data/c1" && sha256sum --quiet -c downloads.sha256 ) || fail "downloads.sha256 must match the files after the refetch"
echo "capped -> off: the prefix is replaced by the whole file, one plain line says why, downloads.sha256 stays consistent -> PASS"
before="$(sha256sum "$TMP/data/c1/SRR1_1.fastq.gz" | cut -d' ' -f1)"
KEEP_DATA=1 run_stage env READ_SOURCE=auto READ_DEPTH_CAP_X=150 || fail "stage 1 with a cap set over whole files"
grep -q "SRR1: the reads on disk are whole files; READ_DEPTH_CAP_X=150 is not applied" "$TMP/stage.log" || fail "off -> capped: the line saying whole files are kept is missing"
! grep -q "fetching SRR1 from ENA" "$TMP/stage.log" || fail "off -> capped: whole files on disk must not be downloaded again"
[[ "$(sha256sum "$TMP/data/c1/SRR1_1.fastq.gz" | cut -d' ' -f1)" == "$before" ]] || fail "off -> capped: the whole files must not change"
echo "off -> capped: whole files are kept untouched and the log says the full reads are used -> PASS"
echo "ALL STAGE 1 DOWNLOAD TESTS PASSED"
