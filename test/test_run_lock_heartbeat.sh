#!/usr/bin/env bash
# Audit AU-009 (heartbeat): a lock is stale when its heartbeat is older than PLASBENCH_LOCK_STALE_SECONDS even if its pid is alive (pid reuse), and a SIGKILLed holder
# stops heartbeating. Checks:
#   1. a live holder touches RESULTS_DIR/.run.lock.heartbeat repeatedly (its mtime advances);
#   2. kill -9 of the holder: the heartbeat loop ends by itself, and the next start takes over at once (pid dead) and starts its own heartbeat;
#   3. reused-pid stand-in: the lock names a LIVE unrelated process (sleep) with an OLD heartbeat -> the start proceeds and says why;
#   4. controls: the same lock with a FRESH heartbeat refuses, and one with NO heartbeat file (older version) refuses on pid alone;
#   5. the lock and heartbeat are gone after a normal exit; the window's lock_holder() applies the same rule.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
if ! command -v ps >/dev/null 2>&1; then echo "SKIP: needs ps (Linux or WSL)"; exit 0; fi
TMP="$(mktemp -d)"
trap 'kill "${HOLDER:-0}" "${STAND:-0}" 2>/dev/null || true; rm -rf "$TMP"' EXIT
mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }
export PLASBENCH_LOCK_HEARTBEAT_SECONDS=0.3 PLASBENCH_LOCK_STALE_SECONDS=5

holder() {   # holder RESULTS : takes the lock and sleeps
    RESULTS_DIR="$1" ROOT="$ROOT" bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "heartbeat test" >/dev/null 2>&1; sleep 60' >/dev/null 2>&1 &
    HOLDER=$!
}
res="$TMP/res1"; mkdir -p "$res"
holder "$res"
for _ in $(seq 50); do [[ -e "$res/.run.lock.heartbeat" ]] && break; sleep 0.1; done
[[ -e "$res/.run.lock.heartbeat" ]] || { echo "FAIL: no heartbeat file appeared" >&2; exit 1; }
m1="$(mtime "$res/.run.lock.heartbeat")"; sleep 2.2; m2="$(mtime "$res/.run.lock.heartbeat")"
(( m2 > m1 )) || { echo "FAIL: the heartbeat did not advance ($m1 -> $m2)" >&2; exit 1; }
echo "a live holder keeps touching its heartbeat -> PASS"

# 2. SIGKILL: the loop ends, the next start takes over
kill -9 "$HOLDER"; wait "$HOLDER" 2>/dev/null || true
sleep 1.5
m3="$(mtime "$res/.run.lock.heartbeat")"; sleep 1.2; m4="$(mtime "$res/.run.lock.heartbeat")"
[[ "$m3" == "$m4" ]] || { echo "FAIL: the heartbeat kept advancing after the holder was SIGKILLed" >&2; exit 1; }
RESULTS_DIR="$res" ROOT="$ROOT" timeout 30 bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "second"; [[ -e "$RESULTS_DIR/.run.lock.heartbeat" ]]' > "$TMP/second.log" 2>&1 \
    || { echo "FAIL: a start after a SIGKILLed holder must take over" >&2; cat "$TMP/second.log" >&2; exit 1; }
grep -q "stale run lock" "$TMP/second.log" || { echo "FAIL: the takeover must be announced" >&2; cat "$TMP/second.log" >&2; exit 1; }
[[ ! -e "$res/.run.lock" && ! -e "$res/.run.lock.heartbeat" ]] || { echo "FAIL: lock and heartbeat must be gone after a normal exit" >&2; ls -a "$res" >&2; exit 1; }
echo "SIGKILLed holder: heartbeat stops, the next start takes over, nothing is left after a normal exit -> PASS"

# 3. reused pid: a live unrelated process in the lock, old heartbeat
sleep 300 & STAND=$!
res="$TMP/res3"; mkdir -p "$res"
printf 'pid=%s\npgid=\nstarted=2020-01-01 00:00:00\nwhat=killed run\n' "$STAND" > "$res/.run.lock"
: > "$res/.run.lock.heartbeat"; touch -d '10 minutes ago' "$res/.run.lock.heartbeat"
RESULTS_DIR="$res" ROOT="$ROOT" timeout 30 bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "after reuse"; grep -q "^pid=$$" "$RESULTS_DIR/.run.lock"' > "$TMP/reuse.log" 2>&1 \
    || { echo "FAIL: a live pid with an old heartbeat must not block the start" >&2; cat "$TMP/reuse.log" >&2; exit 1; }
grep -q "heartbeat is" "$TMP/reuse.log" || { echo "FAIL: the message must name the heartbeat" >&2; cat "$TMP/reuse.log" >&2; exit 1; }
kill -0 "$STAND" 2>/dev/null || { echo "FAIL: the unrelated process must not be touched" >&2; exit 1; }
echo "reused pid (live unrelated process, old heartbeat): the start proceeds and the process is left alone -> PASS"

# 4. controls
res="$TMP/res4"; mkdir -p "$res"
printf 'pid=%s\npgid=\nstarted=2020-01-01 00:00:00\nwhat=live run\n' "$STAND" > "$res/.run.lock"
: > "$res/.run.lock.heartbeat"
if RESULTS_DIR="$res" ROOT="$ROOT" timeout 30 bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "control"' > "$TMP/fresh.log" 2>&1; then
    echo "FAIL: a live pid with a fresh heartbeat must refuse" >&2; exit 1; fi
grep -q "already using" "$TMP/fresh.log" || { echo "FAIL: refusal text" >&2; cat "$TMP/fresh.log" >&2; exit 1; }
rm -f "$res/.run.lock.heartbeat"
if RESULTS_DIR="$res" ROOT="$ROOT" timeout 30 bash -c 'source "$ROOT/scripts/lib.sh"; acquire_run_lock "legacy"' > "$TMP/legacy.log" 2>&1; then
    echo "FAIL: a live pid with no heartbeat file (older version) must still refuse" >&2; exit 1; fi
echo "controls: fresh heartbeat refuses, no heartbeat file refuses on pid alone -> PASS"

# 5. window side
python3 - "$ROOT" "$TMP" "$STAND" <<'PY'
import os, sys, time
root, tmp, pid = sys.argv[1:4]
sys.path.insert(0, root)
from plasbench import jobrunner
os.environ["PLASBENCH_LOCK_STALE_SECONDS"] = "5"
res = os.path.join(tmp, "res_py"); os.makedirs(res)
open(os.path.join(res, ".run.lock"), "w").write(f"pid={pid}\npgid=\nstarted=x\nwhat=y\n")
if os.name == "nt":
    print("skip: lock_holder is not used on Windows"); sys.exit(0)
assert jobrunner.lock_holder(res), "no heartbeat file: the pid decides"
hb = os.path.join(res, ".run.lock.heartbeat"); open(hb, "w").close()
assert jobrunner.lock_holder(res), "fresh heartbeat: live holder"
old = time.time() - 600; os.utime(hb, (old, old))
assert jobrunner.lock_holder(res) is None, "old heartbeat: stale even though the pid is alive"
print("window lock_holder applies the heartbeat rule")
PY
echo "ALL RUN LOCK HEARTBEAT TESTS PASSED"
