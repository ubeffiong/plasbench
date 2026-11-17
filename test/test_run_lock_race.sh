#!/usr/bin/env bash
# Audit AU-009 (stale-lock race): when several starters meet the same stale lock at the same moment exactly one may win.
# Before, each starter checked the lock, removed it and re-created it without any mutual exclusion, so the second starter's remove could delete
# the first starter's fresh lock and both ran on one results folder. The stale-lock handling now runs under a mkdir guard.
# The test widens the window on purpose (warn() sleeps 0.25-0.55 s, staggered per starter, between the check and the removal) so that, without the guard, the second starter always deletes the first one's fresh lock.
# Also checks: a guard left by a dead starter is reclaimed, and the lock and guard are gone after a normal run.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
if ! command -v ps >/dev/null 2>&1; then echo "SKIP: needs ps (Linux or WSL)"; exit 0; fi
TMP="$(mktemp -d)"
trap 'pkill -f "run_lock_race_starter_$$" 2>/dev/null || true; rm -rf "$TMP"' EXIT

starter() {   # starter RESULTS HOLD_SECONDS OUTFILE INDEX
    RESULTS_DIR="$1" HOLD="$2" OUT="$3" IDX="$4" ROOT="$ROOT" bash -c '
        : run_lock_race_starter_'"$$"'
        source "$ROOT/scripts/lib.sh"
        warn() { sleep "0.$((20 + IDX * 5))"; }   # widen the window between "the lock is stale" and "remove it", staggered so the old code fails every time
        acquire_run_lock "race test" > /dev/null 2>&1
        echo won >> "$OUT"
        sleep "$HOLD"
    ' > /dev/null 2>&1
}

for round in 1 2 3; do
    res="$TMP/res$round"; mkdir -p "$res"
    printf 'pid=999999\npgid=\nstarted=2020-01-01 00:00:00\nwhat=dead run\n' > "$res/.run.lock"
    : > "$TMP/wins$round"
    for n in 1 2 3 4 5 6 7 8; do starter "$res" 3 "$TMP/wins$round" "$n" & done
    sleep 2
    wins="$(wc -l < "$TMP/wins$round" | tr -d ' ')"
    wait || true
    [[ "$wins" == "1" ]] || { echo "FAIL: round $round: $wins starters won the same stale lock (exactly 1 expected)" >&2; exit 1; }
done
echo "8 simultaneous starters over a stale lock: exactly one wins, in 3 rounds -> PASS"

# a guard left behind by a starter that died is reclaimed, and lock and guard are gone after a normal run
res="$TMP/res_guard"; mkdir -p "$res/.run.lock.guard"; printf '999999\n' > "$res/.run.lock.guard/pid"
RESULTS_DIR="$res" ROOT="$ROOT" timeout 30 bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "guard test"; [[ -s "$RESULTS_DIR/.run.lock" ]]' > "$TMP/guard.log" 2>&1 \
    || { echo "FAIL: a guard left by a dead starter must be reclaimed" >&2; cat "$TMP/guard.log" >&2; exit 1; }
[[ ! -e "$res/.run.lock" && ! -e "$res/.run.lock.guard" ]] || { echo "FAIL: the lock and the guard must be gone after the run" >&2; ls -a "$res" >&2; exit 1; }
echo "a dead starter's guard is reclaimed; nothing is left behind -> PASS"
echo "ALL RUN LOCK RACE TESTS PASSED"
