#!/usr/bin/env bash
# require_internet (scripts/lib.sh) and stage 1's early refusal: no internet is one plain sentence before any work; nothing is demanded
# when every file is already on disk; PLASBENCH_ASSUME_ONLINE and PLASBENCH_OFFLINE are honoured. No real network is used.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# --- the function ---
out="$(PLASBENCH_ASSUME_ONLINE=1 bash -c "source '$ROOT/config/config.sh'; source '$ROOT/scripts/lib.sh'; require_internet github && echo reached" 2>&1)"
[[ "$out" == *reached* ]] || fail "ASSUME_ONLINE should pass: $out"
if out="$(env -u PLASBENCH_ASSUME_ONLINE PLASBENCH_OFFLINE=1 bash -c "source '$ROOT/config/config.sh'; source '$ROOT/scripts/lib.sh'; require_internet --action 'Upgrading' github; echo reached" 2>&1)"; then fail "PLASBENCH_OFFLINE=1 should stop"; fi
[[ "$out" == *"Upgrading needs the internet"* && "$out" != *reached* ]] || fail "forced-offline message: $out"
out="$(env -u PLASBENCH_ASSUME_ONLINE PLASBENCH_OFFLINE=1 bash -c "source '$ROOT/config/config.sh'; source '$ROOT/scripts/lib.sh'; require_internet --warn github; echo rc=\$?" 2>&1)"
[[ "$out" == *"rc=1"* ]] || fail "--warn should return 1: $out"
echo "require_internet passes with ASSUME_ONLINE, refuses with PLASBENCH_OFFLINE, --warn does not stop -> PASS"

# --- stage 1 ---
mkdir -p "$TMP/bin" "$TMP/data" "$TMP/logs"
for t in datasets prefetch fasterq-dump; do printf '#!/usr/bin/env bash\necho "$0 must not run" >> "%s/ran.log"; exit 1\n' "$TMP" > "$TMP/bin/$t"; chmod +x "$TMP/bin/$t"; done
printf 'sample_id\tassembly_accession\tsra_run\ns1\tGCA_000000001.1\tSRR1\n' > "$TMP/sheet.tsv"
stage1() {
    env -u PLASBENCH_ASSUME_ONLINE PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}
if stage1 PLASBENCH_OFFLINE=1; then fail "stage 1 must refuse offline when data is missing"; fi
grep -q "needs the internet" "$TMP/stage.log" || fail "stage 1 should say it needs the internet: $(cat "$TMP/stage.log")"
grep -q "local-inputs" "$TMP/stage.log" || fail "stage 1 should say what to do instead (--local-inputs)"
[[ ! -e "$TMP/ran.log" ]] || fail "no download tool may run before the refusal"
echo "stage 1 offline with data missing refuses early, names what to do, runs nothing -> PASS"

mkdir -p "$TMP/data/s1"
printf '>c\nACGT\n' > "$TMP/data/s1/reference.fna"; echo '{}' > "$TMP/data/s1/sequence_report.jsonl"
for m in 1 2; do echo x | gzip > "$TMP/data/s1/SRR1_$m.fastq.gz"; done
stage1 PLASBENCH_OFFLINE=1 || { cat "$TMP/stage.log" >&2; fail "stage 1 must not demand the internet when everything is on disk"; }
! grep -q "needs the internet" "$TMP/stage.log" || fail "no internet message expected when all data is on disk"
echo "stage 1 offline with everything on disk goes ahead -> PASS"

# estimate_download: offline is a note, never an error
printf 'sample_id\tassembly_accession\tsra_run\ns9\tGCA_000000009.1\tSRR9\n' > "$TMP/sheet2.tsv"
out="$(env -u PLASBENCH_ASSUME_ONLINE PLASBENCH_OFFLINE=1 python3 "$ROOT/python/estimate_download.py" --samples "$TMP/sheet2.tsv" --data-dir "$TMP/data2" 2>&1)" || fail "estimate must not fail offline: $out"
[[ "$out" == *"ENA read sizes were not looked up"* ]] || fail "estimate should note the skipped ENA lookup: $out"
echo "estimate_download offline skips the ENA lookup with a note -> PASS"
echo "ALL REQUIRE_INTERNET TESTS PASSED"
