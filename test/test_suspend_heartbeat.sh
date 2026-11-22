#!/usr/bin/env bash
# Computer sleep and the long-command watcher (scripts/lib.sh run_with_heartbeat, python/awake_clock.py):
#   1. a clock jump the loop did not cause (the computer slept) is recorded once as a system_suspend event and in RESULTS_DIR/.suspend_gaps
#   2. the command's end event carries seconds (clock) AND awake_seconds (without the sleep), so a 3-second step that straddled a 2-hour sleep is a 3-second step
#   3. no slow_step note and no 'still running for N min' line comes from the sleep (fastp's typical time is 120 s, 3x = 360 s; the sleep was 7200 s)
#   4. without any sleep nothing is recorded and awake_seconds equals seconds
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; exit 1; }

RES="$TMP/results"; mkdir -p "$RES"
OFFSET="$TMP/offset"; echo 0 > "$OFFSET"
# --- 1-3: a simulated 2 h sleep half way through a 4 s command ---
( sleep 2; echo 7200 > "$OFFSET" ) &
RESULTS_DIR="$RES" PROJECT_ROOT="$ROOT" HEARTBEAT_DELAY_SECONDS=1 HEARTBEAT_INTERVAL_SECONDS=1 SUSPEND_MIN_SECONDS=60 bash -c '
    source "'"$ROOT"'/scripts/lib.sh"
    _pb_now() { echo $(( $(date +%s) + $(cat "'"$OFFSET"'") )); }       # the test clock: jumps 7200 s once
    run_with_heartbeat "s1 / fastp trimming" bash -c "sleep 4"
' 2> "$TMP/console.txt" || fail "the command should succeed"
wait
python3 - "$RES/run_events.jsonl" "$RES/.suspend_gaps" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
susp = [r for r in rows if r["event"] == "system_suspend"]
assert len(susp) == 1, susp
assert 7000 <= int(susp[0]["gap_seconds"]) <= 7300, susp[0]
assert "asleep" in susp[0]["message"] and "paused, not slow" in susp[0]["message"], susp[0]
end = [r for r in rows if r["event"] == "command_end"][0]
assert 7200 <= int(end["seconds"]) <= 7300, end
assert int(end["awake_seconds"]) <= 8, end                 # 4 s of work, plus a little for polling
assert 7000 <= int(end["suspended_seconds"]) <= 7300, end
assert not [r for r in rows if r["event"] == "slow_step"], "a sleep must not cause a slow_step note"
for r in rows:
    if r["event"] == "heartbeat":
        assert int(r["elapsed"]) < 60, ("heartbeat elapsed must be awake time", r)
assert open(sys.argv[2]).read().count("\n") == 1
PY
grep -q "the computer was asleep" "$TMP/console.txt" || fail "the console should say the computer was asleep"
! grep -q "is still running after" "$TMP/console.txt" || fail "no slow-step line may come from a sleep"
echo "a sleep inside a long command is recorded once and left out of its elapsed time -> PASS"

# --- 4: no sleep, nothing recorded ---
RES2="$TMP/results2"; mkdir -p "$RES2"
RESULTS_DIR="$RES2" PROJECT_ROOT="$ROOT" bash -c '
    source "'"$ROOT"'/scripts/lib.sh"
    run_with_heartbeat "s1 / fastp trimming" bash -c "sleep 2"
' 2>/dev/null
python3 - "$RES2/run_events.jsonl" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
assert not [r for r in rows if r["event"] == "system_suspend"]
end = [r for r in rows if r["event"] == "command_end"][0]
assert end["seconds"] == end["awake_seconds"] and end["suspended_seconds"] == "0", end
PY
[[ ! -s "$RES2/.suspend_gaps" ]] || fail "no gap may be recorded without a sleep"
echo "without a sleep nothing is recorded and awake_seconds equals seconds -> PASS"
echo "suspend heartbeat checks passed"
