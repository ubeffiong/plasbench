#!/usr/bin/env bash
# retry_network after the computer slept (scripts/lib.sh). After a suspend the command's connections are dead ("Connection reset by peer") and Wi-Fi may take a minute to
# return; that attempt must not use up NETWORK_RETRIES and fail the isolate. Fake commands only, offline, a test clock instead of real sleeps.
#   1. an attempt that overlapped a recorded sleep (RESULTS_DIR/.suspend_gaps) is retried and not counted: NETWORK_RETRIES=1 still succeeds
#   2. without a sleep, NETWORK_RETRIES=1 fails after one attempt (unchanged behaviour)
#   3. a back-off wait that took far longer on the wall clock than asked (the computer slept in it) is recorded as a sleep and the next attempt is not counted
#   4. the extra retries are bounded (NETWORK_SUSPEND_RETRIES)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; exit 1; }

run_case() {   # run_case NAME SCRIPT: runs SCRIPT after sourcing lib.sh with a fake clock and a no-op sleep; prints the exit status
    local name="$1" body="$2" res="$TMP/$1"
    mkdir -p "$res"; echo 1000000 > "$res/clock"
    RESULTS_DIR="$res" PROJECT_ROOT="$ROOT" LOG_DIR="$res" NETWORK_RETRY_DELAY_SECONDS=15 NETWORK_WAKE_GRACE_SECONDS=1 SUSPEND_MIN_SECONDS=60 bash -c '
        source "'"$ROOT"'/scripts/lib.sh"
        CLOCK="'"$res"'/clock"
        _pb_now() { cat "$CLOCK"; }
        sleep() { echo $(( $(cat "$CLOCK") + ${1%.*} )) > "$CLOCK"; }      # the test clock: a wait moves it forward by what was asked
        '"$body"'
    ' > "$res/out.txt" 2>&1 && echo 0 || echo $?
}

# a fake download that dies with a reset the first time, while the computer "sleeps" 2 h inside the attempt (the sentinel records the gap)
FIRST_FAILS='
    fetch() {
        if [[ ! -e "$RESULTS_DIR/ran" ]]; then
            : > "$RESULTS_DIR/ran"; local a; a=$(_pb_now); echo $(( a + 7200 )) > "$CLOCK"
            printf "%s %s sentinel\n" "$(( a + 1 ))" "$(( a + 7199 ))" >> "$RESULTS_DIR/.suspend_gaps"
            echo "curl: (56) Recv failure: Connection reset by peer" >&2; return 56
        fi
        echo "downloaded"
    }'

# 1
rc="$(run_case slept "$FIRST_FAILS"'
    NETWORK_RETRIES=1 retry_network "prefetch SRR1" fetch')"
[[ "$rc" == 0 ]] || { cat "$TMP/slept/out.txt"; fail "an attempt lost to a sleep must be retried, not fail the isolate (rc=$rc)"; }
grep -q "asleep for about 120 min" "$TMP/slept/out.txt" || { cat "$TMP/slept/out.txt"; fail "the warning must say the computer was asleep"; }
grep -q "not counted" "$TMP/slept/out.txt" || fail "the log must say the attempt was not counted"
grep -q '"event":"network_retry_after_sleep"' "$TMP/slept/run_events.jsonl" || fail "a network_retry_after_sleep event is recorded"
echo "  ok    a reset during a sleep is retried without using up NETWORK_RETRIES"

# 2
rc="$(run_case awake '
    fetch() { echo "curl: (56) Recv failure: Connection reset by peer" >&2; return 56; }
    NETWORK_RETRIES=1 retry_network "prefetch SRR2" fetch')"
[[ "$rc" != 0 ]] || fail "without a sleep one failed attempt with NETWORK_RETRIES=1 must fail"
grep -q "failed after 1 attempt(s)" "$TMP/awake/out.txt" || { cat "$TMP/awake/out.txt"; fail "the usual failure line"; }
echo "  ok    without a sleep the retry budget is unchanged"

# 3: the computer sleeps during the back-off wait (the wall clock jumps by 1 h while the wait asked for 15 s)
rc="$(run_case wait '
    calls=0      # not "n": retry_network has a local n, and bash scoping is dynamic
    fetch() { calls=$((calls + 1)); [[ $calls -ge 3 ]] && { echo ok; return 0; }; echo "Connection timed out" >&2; return 1; }
    sleep() { local now; now=$(cat "$CLOCK"); if [[ ! -e "$RESULTS_DIR/jumped" ]]; then : > "$RESULTS_DIR/jumped"; echo $(( now + ${1%.*} + 3600 )) > "$CLOCK"; else echo $(( now + ${1%.*} )) > "$CLOCK"; fi; }
    NETWORK_RETRIES=2 retry_network "datasets download" fetch')"
[[ "$rc" == 0 ]] || { cat "$TMP/wait/out.txt"; fail "a sleep during the back-off wait must not use up an attempt (rc=$rc)"; }
grep -q "asleep during the wait" "$TMP/wait/out.txt" || { cat "$TMP/wait/out.txt"; fail "the log says the computer slept during the wait"; }
[[ -s "$TMP/wait/.suspend_gaps" ]] || fail "the sleep seen in the wait is recorded, so elapsed times leave it out"
echo "  ok    a sleep inside the back-off wait is noticed, recorded and not counted"

# 4: a sleep on every attempt cannot loop forever
rc="$(run_case bounded '
    fetch() { local a; a=$(_pb_now); echo $(( a + 600 )) > "$CLOCK"; printf "%s %s sentinel\n" "$(( a + 1 ))" "$(( a + 599 ))" >> "$RESULTS_DIR/.suspend_gaps"; return 56; }
    NETWORK_RETRIES=1 NETWORK_SUSPEND_RETRIES=2 retry_network "prefetch SRR3" fetch')"
[[ "$rc" != 0 ]] || fail "the extra retries after a sleep are bounded"
[[ "$(grep -c "not counted" "$TMP/bounded/out.txt")" == 2 ]] || { cat "$TMP/bounded/out.txt"; fail "exactly NETWORK_SUSPEND_RETRIES extra retries"; }
echo "  ok    the extra retries after a sleep are bounded by NETWORK_SUSPEND_RETRIES"
echo "retry_network sleep checks passed"
