#!/usr/bin/env bash
# After the computer wakes, connections made before the sleep are dead and wall-clock limits have run on:
#   1. retry_network: a call that failed while the computer was asleep does not use up an attempt (NETWORK_RETRIES=1 would otherwise stop after it); a failure with no sleep still does
#   2. awake_timeout (stage 4's TOOL_TIMEOUT_SECONDS): the limit counts awake time: a tool that straddled a recorded sleep is not killed, one that really ran long still gets exit 124
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; exit 1; }
RES="$TMP/results"; mkdir -p "$RES"
run() { RESULTS_DIR="$RES" PROJECT_ROOT="$ROOT" NETWORK_RETRY_DELAY_SECONDS=0 NETWORK_RESUME_WAIT_SECONDS=0 NETWORK_SUSPEND_CHECK_DELAY=0 bash -c 'source "'"$ROOT"'/scripts/lib.sh"; '"$1" 2>"$TMP/err.txt"; }

# --- 1. retry_network ---
rm -f "$TMP/n"; : > "$RES/.suspend_gaps"
# the first call fails and a sleep is recorded over it (the gap file says the computer slept during that time)
if run 'cnt=0; flaky() { cnt=$((cnt+1)); if [ $cnt -eq 1 ]; then sleep 2; now=$(date +%s); echo "$((now-5)) $((now+30)) test" >> "$RESULTS_DIR/.suspend_gaps"; return 1; fi; return 0; }; NETWORK_RETRIES=1 retry_network "fake download" flaky'; then
    grep -q "was interrupted: the computer was asleep" "$TMP/err.txt" || fail "the interrupted call should be explained: $(cat "$TMP/err.txt")"
else fail "a call that failed during a sleep must be retried without using up the only attempt: $(cat "$TMP/err.txt")"; fi
: > "$RES/.suspend_gaps"
if run 'bad() { return 1; }; NETWORK_RETRIES=1 retry_network "fake download" bad'; then fail "a failure with no sleep still uses the attempt"; fi
grep -q "failed after 1 attempt" "$TMP/err.txt" || fail "an ordinary failure still says so: $(cat "$TMP/err.txt")"
echo "retry_network: a failure during a sleep is not counted, an ordinary one is -> PASS"

# --- 2. awake_timeout ---
: > "$RES/.suspend_gaps"
rc=0; run 'awake_timeout 2 sleep 5' || rc=$?
[[ "$rc" == "124" ]] || fail "a command that runs past the limit awake gets exit 124 (got $rc)"
rc=0; run 'awake_timeout 5 bash -c "exit 7"' || rc=$?
[[ "$rc" == "7" ]] || fail "the command's own exit code is passed through (got $rc)"
rc=0; run 'awake_timeout 5 true' || rc=$?
[[ "$rc" == "0" ]] || fail "success is success (got $rc)"
rc=0; run 's0=$(date +%s); ( sleep 3; echo "$s0 $((s0+3)) test" >> "$RESULTS_DIR/.suspend_gaps" ) & awake_timeout 2 sleep 4; wait' || rc=$?
[[ "$rc" == "0" ]] || fail "a command that straddled a sleep (recorded while it ran) is not killed for it (got $rc)"
grep -q "awake_timeout" "$ROOT/scripts/04_run_tools.sh" || fail "stage 4's with_budget should use awake_timeout"
echo "awake_timeout: the limit counts awake time only -> PASS"
echo "resume retry checks passed"
