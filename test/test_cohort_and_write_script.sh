#!/usr/bin/env bash
# Regression for 'plasbench run --cohort NAME' and '--write-script PATH':
# --cohort must resolve to cohorts/<NAME>.tsv (or fail clearly, listing what
# is available), --cohort/--samples must stay mutually exclusive, and
# --write-script must produce a standalone bash script that -- when actually
# executed -- resolves to the exact same cwd/env/command as a direct
# (non-write-script) invocation would have used. Windows drive-letter paths
# are exercised deliberately: a prior bug wrote 'F:\foo' (backslashes) into
# the generated script's cd/export lines, which bash reads as escapes rather
# than separators and silently breaks. Runs fully offline against a fake
# project root, no real bioinformatics tool required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PROJECT="$TMP/project"
mkdir -p "$PROJECT/scripts" "$PROJECT/cohorts"
cat > "$PROJECT/scripts/run_all.sh" <<'EOF'
#!/usr/bin/env bash
{
    echo "PWD=$(pwd)"
    echo "SAMPLE_SHEET=${SAMPLE_SHEET:-}"
    echo "THREADS=${THREADS:-}"
    echo "MAX_PARALLEL_SAMPLES=${MAX_PARALLEL_SAMPLES:-}"
    echo "ARGS=$*"
} >> "$RUN_LOG"
EOF
chmod +x "$PROJECT/scripts/run_all.sh"
printf 'sample_id\tassembly_accession\n' > "$PROJECT/cohorts/demo-cohort.tsv"
printf 's1\tGCF_000000000.1\n' >> "$PROJECT/cohorts/demo-cohort.tsv"

PY() { python3 -m plasbench --project-root "$PROJECT" "$@"; }

# --- --cohort resolves to cohorts/<NAME>.tsv, exercised via --write-script ---
SCRIPT="$TMP/generated.sh"
PY run --cohort demo-cohort --threads 4 --parallel-samples 2 --write-script "$SCRIPT" > "$TMP/write.log" 2>&1
[[ -f "$SCRIPT" ]] || { echo "FAIL: --write-script did not create the script file" >&2; cat "$TMP/write.log" >&2; exit 1; }
grep -q "cohorts/demo-cohort.tsv" "$SCRIPT" || { echo "FAIL: generated script does not reference the resolved cohort path" >&2; cat "$SCRIPT" >&2; exit 1; }
grep -q "THREADS=4" "$SCRIPT" || { echo "FAIL: generated script missing THREADS export" >&2; cat "$SCRIPT" >&2; exit 1; }
grep -q "MAX_PARALLEL_SAMPLES=2" "$SCRIPT" || { echo "FAIL: generated script missing MAX_PARALLEL_SAMPLES export" >&2; cat "$SCRIPT" >&2; exit 1; }
echo "--cohort resolves and --write-script writes the resolved command -> PASS"

# --- the generated script must not contain raw Windows backslash paths ---
if grep -qE "cd '[A-Za-z]:\\\\" "$SCRIPT"; then
    echo "FAIL: generated script contains a raw Windows backslash path bash cannot cd into" >&2
    cat "$SCRIPT" >&2; exit 1
fi
echo "generated script uses bash-safe (forward-slash) paths -> PASS"

# --- the file is executable ---
[[ -x "$SCRIPT" ]] || { echo "FAIL: generated script should be executable" >&2; exit 1; }
echo "generated script is marked executable -> PASS"

# --- running the generated script resolves to the same cwd/env/command as a
# direct invocation would (the whole point of the feature: what you see is
# what actually runs). Compare via "-ef" (same underlying file/dir), not
# string equality: Git Bash on Windows can alias the same directory under
# more than one path spelling (e.g. mktemp's /tmp/xxx vs the drive-letter
# path Python resolves), so a string mismatch there is not a real bug.
RUN_LOG="$TMP/direct.log" bash "$SCRIPT"
[[ -s "$TMP/direct.log" ]] || { echo "FAIL: executing the generated script did not run scripts/run_all.sh at all" >&2; exit 1; }
pwd_seen="$(grep '^PWD=' "$TMP/direct.log" | head -1 | cut -d= -f2-)"
[[ -n "$pwd_seen" && "$pwd_seen" -ef "$PROJECT" ]] || { echo "FAIL: generated script did not cd into the project root" >&2; cat "$TMP/direct.log" >&2; exit 1; }
sheet_seen="$(grep '^SAMPLE_SHEET=' "$TMP/direct.log" | head -1 | cut -d= -f2-)"
[[ -n "$sheet_seen" && "$sheet_seen" -ef "$PROJECT/cohorts/demo-cohort.tsv" ]] || { echo "FAIL: generated script did not export the resolved cohort sample sheet" >&2; cat "$TMP/direct.log" >&2; exit 1; }
grep -q "^THREADS=4$" "$TMP/direct.log" || { echo "FAIL: generated script did not export THREADS" >&2; cat "$TMP/direct.log" >&2; exit 1; }
grep -q "^MAX_PARALLEL_SAMPLES=2$" "$TMP/direct.log" || { echo "FAIL: generated script did not export MAX_PARALLEL_SAMPLES" >&2; cat "$TMP/direct.log" >&2; exit 1; }
echo "executing the generated script cds/exports/runs exactly as a direct run would -> PASS"

# --- a direct (non-write-script) run must produce the identical resolved
# environment as the script it would have written. ---
RUN_LOG="$TMP/live.log" PY run --cohort demo-cohort --threads 4 --parallel-samples 2 > "$TMP/run.log" 2>&1
[[ -s "$TMP/live.log" ]] || { echo "FAIL: a direct run did not invoke scripts/run_all.sh at all" >&2; cat "$TMP/run.log" >&2; exit 1; }
live_pwd="$(grep '^PWD=' "$TMP/live.log" | head -1 | cut -d= -f2-)"
live_sheet="$(grep '^SAMPLE_SHEET=' "$TMP/live.log" | head -1 | cut -d= -f2-)"
[[ -n "$live_pwd" && "$live_pwd" -ef "$pwd_seen" ]] || { echo "FAIL: direct run's cwd diverges from the generated script's cwd" >&2; cat "$TMP/live.log" >&2; exit 1; }
[[ -n "$live_sheet" && "$live_sheet" -ef "$sheet_seen" ]] || { echo "FAIL: direct run's SAMPLE_SHEET diverges from the generated script's" >&2; cat "$TMP/live.log" >&2; exit 1; }
diff <(grep -E '^(THREADS|MAX_PARALLEL_SAMPLES|ARGS)=' "$TMP/direct.log") <(grep -E '^(THREADS|MAX_PARALLEL_SAMPLES|ARGS)=' "$TMP/live.log") \
    || { echo "FAIL: --write-script output diverges from a direct run's actual environment" >&2; exit 1; }
echo "--write-script output matches a direct run's actual resolved environment -> PASS"

# --- unknown cohort name fails clearly and lists what is available ---
if PY run --cohort nonexistent-cohort > "$TMP/err.log" 2>&1; then
    echo "FAIL: an unknown cohort name should be rejected" >&2; cat "$TMP/err.log" >&2; exit 1
fi
grep -qi "no such cohort" "$TMP/err.log" || { echo "FAIL: expected a clear 'no such cohort' error" >&2; cat "$TMP/err.log" >&2; exit 1; }
grep -q "demo-cohort" "$TMP/err.log" || { echo "FAIL: error should list the available cohort(s)" >&2; cat "$TMP/err.log" >&2; exit 1; }
echo "an unknown --cohort name fails clearly and lists available cohorts -> PASS"

# --- --samples and --cohort together are rejected ---
if PY run --samples "$PROJECT/cohorts/demo-cohort.tsv" --cohort demo-cohort > "$TMP/err.log" 2>&1; then
    echo "FAIL: --samples and --cohort together should be rejected" >&2; cat "$TMP/err.log" >&2; exit 1
fi
grep -qi "not allowed with argument" "$TMP/err.log" || { echo "FAIL: expected argparse's mutual-exclusion error" >&2; cat "$TMP/err.log" >&2; exit 1; }
echo "--samples and --cohort together are rejected -> PASS"

echo "ALL COHORT/WRITE-SCRIPT TESTS PASSED"
