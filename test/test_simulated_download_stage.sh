#!/usr/bin/env bash
# Regression for scripts/01_download.sh's new truth_source=simulated branch:
# the OPPOSITE shape from self_assembled_hybrid -- assembly_accession is a
# REAL reference (pre-staged here, exactly as a normal datasets download
# would have left it, so this test focuses on the new branch, not the
# already-covered reference-download path itself), but sra_run is not a
# real SRA accession -- reads are generated locally by the REAL
# python/simulate_reads.py (only its iss/badread dependencies are faked,
# matching test_build_hybrid_truth_stage.sh's own "fake the lowest-level
# binary, run the real orchestration script" convention), landing short
# reads at the normal ${SRA}_1/_2.fastq.gz location and long reads at the
# same $LONG_READS_FILE location stage 7's tools already read. A row with no
# reference at all must fail with a specific reason, never proceed as if it
# had something to simulate from.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/logs"
printf '>chr1\nACGTACGTACGT\n>plas1\nACGTACGT\n' > "$TMP/data/s1/reference.fna"
printf '{"genbank_accession":"chr1","assigned_molecule_location_type":"Chromosome"}\n' > "$TMP/data/s1/sequence_report.jsonl"

# Fake iss/badread are written in Python, with BOTH a bare Unix script and a
# .bat sibling -- matching test_build_hybrid_truth_stage.sh's own
# unicycler_fake.py precedent for the exact same reason: simulate_reads.py
# resolves these via shutil.which() (not a bare subprocess.run name, which is
# not PATHEXT-aware on native Windows), and on a native-Windows Python,
# shutil.which() does NOT match an extensionless shell script at all -- only
# a name that already has a recognized extension (or none, on a real POSIX
# host). A plain POSIX $TMP/bin:$PATH prepend covers both: Windows's own
# automatic PATH conversion when spawning a native child handles the rest.
cat > "$TMP/bin/iss_fake.py" <<'EOF'
import os, sys, gzip, shutil
with open(os.environ["ISS_CALLS_LOG"], "a") as f:
    f.write("iss " + " ".join(sys.argv[1:]) + "\n")
assert sys.argv[1] == "generate"
prefix = sys.argv[sys.argv.index("--output") + 1]
coverage_file = sys.argv[sys.argv.index("--coverage_file") + 1]
shutil.copyfile(coverage_file, os.environ["ISS_COVERAGE_CAPTURE"])
for mate in ("R1", "R2"):
    with gzip.open(f"{prefix}_{mate}.fastq.gz", "wt") as out:
        out.write("@r\nACGT\n+\nIIII\n")
EOF
cat > "$TMP/bin/badread_fake.py" <<'EOF'
import os, sys
with open(os.environ["BADREAD_CALLS_LOG"], "a") as f:
    f.write("badread " + " ".join(sys.argv[1:]) + "\n")
assert sys.argv[1] == "simulate"
sys.stdout.write("@r\nACGTACGTACGT\n+\nIIIIIIIIIIII\n")
EOF
cat > "$TMP/bin/iss" <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/iss_fake.py" "$@"
EOF
cat > "$TMP/bin/iss.bat" <<'EOF'
@echo off
python3 "%~dp0iss_fake.py" %*
EOF
cat > "$TMP/bin/badread" <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/badread_fake.py" "$@"
EOF
cat > "$TMP/bin/badread.bat" <<'EOF'
@echo off
python3 "%~dp0badread_fake.py" %*
EOF
chmod +x "$TMP/bin/iss" "$TMP/bin/badread" "$TMP/bin/iss_fake.py" "$TMP/bin/badread_fake.py"

# datasets is only actually INVOKED when no reference is staged yet (never
# true in the happy-path cases below, since reference.fna/sequence_report
# are pre-staged), but 01_download.sh's `need datasets` gate still requires
# the binary to exist on PATH for any sample with a real assembly_accession.
# (needed via lib.sh's `have`, which -- unlike shutil.which() -- is a plain
# `command -v`, so no .bat sibling is required for this one.)
cat > "$TMP/bin/datasets" <<'EOF'
#!/usr/bin/env bash
echo "datasets should not be invoked when a reference is already staged" >&2
exit 1
EOF
chmod +x "$TMP/bin/datasets"

run_stage() {
    rm -f "$TMP/data/s1"/*.fastq.gz "$TMP/data/s1/long_reads.fastq.gz" "$TMP/data/s1/simulation_provenance.json"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 \
    ISS_CALLS_LOG="$TMP/iss_calls.log" BADREAD_CALLS_LOG="$TMP/badread_calls.log" \
    ISS_COVERAGE_CAPTURE="$TMP/coverage_capture.tsv" \
    "$@" bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <sample> <column-index>
    awk -F'\t' -v s="$1" -v c="$2" '$1==s {print $c; exit}' "$TMP/results/download_status.tsv"
}

printf 'sample_id\tassembly_accession\tsra_run\ttruth_source\tsimulation_seed\tsimulation_short_depth_x\tsimulation_long_depth_x\ns1\tGCF_1.1\tSIMULATED\tsimulated\t42\t60\t40\n' > "$TMP/sheet.tsv"

: > "$TMP/iss_calls.log"; : > "$TMP/badread_calls.log"
run_stage || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field s1 2)" == "ok" ]] || { echo "FAIL: expected ok, got: $(status_field s1 2)" >&2; cat "$TMP/results/download_status.tsv" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/SIMULATED_1.fastq.gz" && -s "$TMP/data/s1/SIMULATED_2.fastq.gz" ]] || { echo "FAIL: expected simulated paired short reads at the sra_run-prefixed path" >&2; ls "$TMP/data/s1" >&2; exit 1; }
[[ -s "$TMP/data/s1/long_reads.fastq.gz" ]] || { echo "FAIL: expected long_reads.fastq.gz to be simulated" >&2; ls "$TMP/data/s1" >&2; exit 1; }
[[ -s "$TMP/data/s1/simulation_provenance.json" ]] || { echo "FAIL: expected simulation_provenance.json to be written" >&2; exit 1; }
grep -q -- "--seed 42" "$TMP/iss_calls.log" || { echo "FAIL: expected iss generate to be called with the cohort sheet's seed" >&2; cat "$TMP/iss_calls.log" >&2; exit 1; }
grep -q -- "--quantity 40x" "$TMP/badread_calls.log" || { echo "FAIL: expected badread simulate to be called with the long-read depth" >&2; cat "$TMP/badread_calls.log" >&2; exit 1; }
grep -qv -- "--length" "$TMP/badread_calls.log" || { echo "FAIL: badread must NOT be forced to a fixed --length" >&2; cat "$TMP/badread_calls.log" >&2; exit 1; }
[[ "$(cut -f2 "$TMP/coverage_capture.tsv" | sort -u)" == "60" ]] || { echo "FAIL: expected every reference contig to get the SAME uniform short-read depth" >&2; cat "$TMP/coverage_capture.tsv" >&2; exit 1; }
echo "truth_source=simulated generates short+long reads via the real simulate_reads.py, using the cohort sheet's seed/depths -> PASS"

# --- Already-simulated reads are reused, not regenerated (mirrors the
# existing "reads already present" convention for real downloads). ---
: > "$TMP/iss_calls.log"; : > "$TMP/badread_calls.log"
PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 \
ISS_CALLS_LOG="$TMP/iss_calls.log" BADREAD_CALLS_LOG="$TMP/badread_calls.log" \
bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1 || { echo "FAIL: re-run should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ ! -s "$TMP/iss_calls.log" && ! -s "$TMP/badread_calls.log" ]] || { echo "FAIL: expected no re-simulation when reads already exist" >&2; exit 1; }
echo "already-simulated reads are reused on a re-run, not regenerated -> PASS"

# --- Partial state from a mid-simulation failure (short reads written, then
# badread died before long_reads.fastq.gz existed) must NOT be treated as
# "already simulated" -- the skip check requires ALL THREE outputs, so a
# missing long_reads.fastq.gz alone must trigger a full re-simulation of all
# three files, never a silent "close enough" reuse of the stale short reads. ---
rm -f "$TMP/data/s1/long_reads.fastq.gz"
: > "$TMP/iss_calls.log"; : > "$TMP/badread_calls.log"
PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 LOCAL_INPUTS_ONLY=0 DOWNLOAD_CONFIRM=0 \
ISS_CALLS_LOG="$TMP/iss_calls.log" BADREAD_CALLS_LOG="$TMP/badread_calls.log" \
ISS_COVERAGE_CAPTURE="$TMP/coverage_capture.tsv" \
bash "$ROOT/scripts/01_download.sh" > "$TMP/stage.log" 2>&1 || { echo "FAIL: re-run after a partial (long-reads-missing) state should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field s1 2)" == "ok" ]] || { echo "FAIL: expected ok after re-simulating from a partial state, got: $(status_field s1 2)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/iss_calls.log" && -s "$TMP/badread_calls.log" ]] || { echo "FAIL: a missing long_reads.fastq.gz alone must trigger full re-simulation (iss AND badread), not a skip" >&2; exit 1; }
[[ -s "$TMP/data/s1/SIMULATED_1.fastq.gz" && -s "$TMP/data/s1/SIMULATED_2.fastq.gz" && -s "$TMP/data/s1/long_reads.fastq.gz" ]] || { echo "FAIL: expected all three simulated outputs present after recovering from the partial state" >&2; ls "$TMP/data/s1" >&2; exit 1; }
echo "a partial state (short reads present, long reads missing after a mid-simulation failure) triggers a full re-simulation, not a silent skip -> PASS"

# --- No reference downloaded at all -> a specific failure, never a silent
# "nothing to simulate from" proceed. ---
rm -rf "$TMP/data"; mkdir -p "$TMP/data/s1"
printf 'sample_id\tassembly_accession\tsra_run\ttruth_source\tsimulation_seed\tsimulation_short_depth_x\tsimulation_long_depth_x\ns1\tGCF_DOES_NOT_EXIST.1\tSIMULATED\tsimulated\t42\t60\t40\n' > "$TMP/sheet.tsv"
cat > "$TMP/bin/datasets" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP/bin/datasets"
if run_stage; then echo "FAIL: stage should abort (the only sample fails)" >&2; cat "$TMP/stage.log" >&2; exit 1; fi
[[ "$(status_field s1 2)" == "failed" ]] || { echo "FAIL: expected failed, got: $(status_field s1 2)" >&2; cat "$TMP/results/download_status.tsv" >&2; exit 1; }
echo "truth_source=simulated with a reference download failure fails cleanly, not a silent proceed -> PASS"

echo "ALL SIMULATED DOWNLOAD STAGE TESTS PASSED"
