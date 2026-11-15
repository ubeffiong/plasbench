#!/usr/bin/env bash
# A run never stops silently: every way a stage can end badly is reported on the console (and in logs/run_errors.log)
#   - a command fails under set -e without a die/warn of its own -> ERROR naming the script, command and exit code
#   - a stage is killed (SIGKILL, as the out-of-memory killer does) -> run_all.sh reports the stage and the reason
#   - a stage is stopped by SIGTERM (Cancel, the system) -> the stage itself says so
#   - a run cut off without any chance to report (WSL or the computer stopped) -> the next run says so
#   - handled failures (if !, ||) stay quiet
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; cat "$TMP/run.log" >&2 2>/dev/null || true; exit 1; }

cp -r "$ROOT/scripts" "$TMP/scripts"
cp -r "$ROOT/config" "$TMP/config"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"
stage() {   # stage NAME BODY: a stand-in stage script that uses the real lib.sh
    printf '#!/usr/bin/env bash\nset -euo pipefail\nHERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\nsource "$HERE/../config/config.sh"\nsource "$HERE/lib.sh"\n%s\n' "$2" > "$TMP/scripts/$1.sh"
}
run() {
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" PLASBENCH_COLOR=never \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 bash "$TMP/scripts/run_all.sh" "$@" > "$TMP/run.log" 2>&1
}

# 1. an unexpected failure under set -e names the script, the command and the reason
stage 03_assemble 'log "assembling"; cp /nonexistent/reads.fq "$TMP_DIR/x"; log "not reached"'
if run 3; then fail "a failing stage must fail the run"; fi
grep -q "ERROR: 03_assemble.sh stopped: \`cp /nonexistent/reads.fq" "$TMP/run.log" || fail "the failed command should be named"
grep -q "ERROR: the run stopped in stage 3 (03_assemble.sh)" "$TMP/run.log" || fail "run_all.sh should name the stage"
grep -q "03_assemble.sh stopped" "$TMP/logs/run_errors.log" || fail "the error should also be in logs/run_errors.log"
[[ ! -e "$TMP/results/.run_in_progress" ]] || fail "a reported failure should not look like a cut-off run"
echo "an unexpected failure is reported with the script, command and exit code -> PASS"

# 2. a stage killed with SIGKILL (as the out-of-memory killer does): reported from outside
stage 03_assemble 'log "assembling"; kill -9 $$'
if run 3; then fail "a killed stage must fail the run"; fi
grep -q "ERROR: the run stopped in stage 3 (03_assemble.sh): killed (SIGKILL): usually out of memory" "$TMP/run.log" \
    || fail "a killed stage should be reported as killed, usually out of memory"
echo "a stage killed by SIGKILL is reported (usually out of memory) -> PASS"

# 3. SIGTERM (Cancel in the window, the system) is reported by the stage itself
stage 03_assemble 'log "assembling"; kill -TERM $$; sleep 2'
if run 3; then fail "a terminated stage must fail the run"; fi
grep -q "ERROR: 03_assemble.sh stopped (SIGTERM)" "$TMP/run.log" || fail "SIGTERM should be reported by the stage"
echo "a stage stopped by SIGTERM says so -> PASS"

# 4. a run cut off without any chance to report: the next run says so
stage 03_assemble 'log "fine"'
printf 'started 2026-11-14 21:40:20, stage 3 (03_assemble.sh), pid 1\n' > "$TMP/results/.run_in_progress"
run 3 || fail "a normal run should succeed"
grep -q "WARNING: the previous run stopped before it finished, without a chance to report why (started 2026-11-14 21:40:20, stage 3" "$TMP/run.log" \
    || fail "the next run should report the cut-off one"
[[ ! -e "$TMP/results/.run_in_progress" ]] || fail "a finished run should remove the marker"
run 3 && ! grep -q "previous run stopped" "$TMP/run.log" || fail "a clean previous run should not be reported"
echo "a run cut off by WSL or the computer is reported by the next run -> PASS"

# 5. handled failures stay quiet
stage 03_assemble 'if ! false; then log "handled"; fi; false || log "also handled"; [[ -e /nonexistent ]] && log x; log done'
run 3 || fail "handled failures must not stop the run"
! grep -q "ERROR" "$TMP/run.log" || fail "handled failures must not print ERROR"
echo "handled failures stay quiet -> PASS"
# 6. the plasbench command and the window explain an exit code in the same words (Python: -9 = shell: 137)
python3 - "$ROOT" <<'PY' || fail "plasbench/exitcodes.py should explain signals and exit codes"
import sys; sys.path.insert(0, sys.argv[1])
from plasbench.exitcodes import explain
assert explain(-9) == explain(137) and "out of memory" in explain(137), explain(-9)
assert explain(-15) == explain(143) and "SIGTERM" in explain(143)
assert "not found" in explain(127) and explain(0) == "finished" and "signal" in explain(-7)
PY
grep -q 'the command stopped: {reason}' "$ROOT/plasbench/webui.py" || fail "the window should append the reason to the job's console"
echo "the plasbench command and the window explain exit codes -> PASS"
echo "ALL NEVER-SILENT TESTS PASSED"
