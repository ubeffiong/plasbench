#!/usr/bin/env bash
# The run's logging pipeline (scripts/lib.sh): structured events, live heartbeats, and the persistent console log.
#   1. run_event writes one valid JSON object per line, even for hostile values (quotes, backslashes, newlines, tabs)
#   2. run_with_heartbeat passes the command's exit code through, records command_start / heartbeat / command_end events, and prints its "still working"
#      lines on the CONSOLE, not into the tool's own log file (callers redirect the tool's output around the whole function)
#   3. the heartbeat carries elapsed time, process figures, the machine's memory/disk and the watched log's last line
#   4. start_console_log keeps everything the run printed, including the very last lines, in LOG_DIR/run_<time>.log, points run.latest.log at it, and prunes old ones
#   5. the long commands of stage 3 (fastp, SPAdes, Unicycler) go through run_with_heartbeat
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }

# --- 1. events are valid JSON whatever the values ---
RES="$TMP/results"; mkdir -p "$RES"
RESULTS_DIR="$RES" bash -c '
    source "'"$ROOT"'/scripts/lib.sh"
    _STAGE_TIMING_ID=9
    run_event hostile "what=say \"hi\" and a back\\slash" "multi=line one
line two	tabbed" "empty=" "noequals" "unicode=caf$(printf "\303\251")"
    run_event second "n=2"
' 2>/dev/null
python3 - "$RES/run_events.jsonl" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
assert len(rows) == 2, rows
first = rows[0]
assert first["event"] == "hostile" and first["stage"] == "9", first
assert first["what"] == 'say "hi" and a back\\slash', first["what"]
assert "line one" in first["multi"] and "line two" in first["multi"] and "\n" not in first["multi"], first["multi"]
assert first["empty"] == "" and "noequals" not in first, first
assert first["ts"] and first["epoch"].__class__ is int, first
assert rows[1]["n"] == "2"
PY
echo "run_event writes one valid JSON line per event, whatever the values -> PASS"

# --- 2 and 3. heartbeat: exit code, events, console vs the tool's log ---
CONSOLE="$TMP/console.txt"; TOOLLOG="$TMP/tool.log"
echo "first line from the tool" > "$TOOLLOG"
rc=0
RESULTS_DIR="$RES" HEARTBEAT_DELAY_SECONDS=1 HEARTBEAT_INTERVAL_SECONDS=1 bash -c '
    source "'"$ROOT"'/scripts/lib.sh"
    WATCH_LOG="'"$TOOLLOG"'" run_with_heartbeat "s1 / fake tool" bash -c "echo tool output; sleep 3.5; exit 7" > "'"$TOOLLOG"'" 2>&1
' 2> "$CONSOLE" || rc=$?
[[ "$rc" == "7" ]] || { echo "FAIL: run_with_heartbeat must return the command's exit code (got $rc)" >&2; cat "$CONSOLE" >&2; exit 1; }
grep -q "still working: s1 / fake tool" "$CONSOLE" || { echo "FAIL: the heartbeat should reach the console" >&2; cat "$CONSOLE" >&2; exit 1; }
! grep -q "still working" "$TOOLLOG" || { echo "FAIL: the heartbeat must not be written into the tool's own log" >&2; cat "$TOOLLOG" >&2; exit 1; }
grep -q "tool output" "$TOOLLOG" || { echo "FAIL: the tool's output belongs in its own log" >&2; exit 1; }
grep -Eq "s elapsed;" "$CONSOLE" || { echo "FAIL: the heartbeat should carry the elapsed time" >&2; cat "$CONSOLE" >&2; exit 1; }
grep -Eq "disk_free=[0-9]+GB" "$CONSOLE" || { echo "FAIL: the heartbeat should carry the disk figure" >&2; cat "$CONSOLE" >&2; exit 1; }
grep -q "its log last changed" "$CONSOLE" || { echo "FAIL: the heartbeat should say when the watched log last changed" >&2; cat "$CONSOLE" >&2; exit 1; }
grep -q "tool output" "$CONSOLE" || { echo "FAIL: the heartbeat should quote the watched log's last line" >&2; cat "$CONSOLE" >&2; exit 1; }
python3 - "$RES/run_events.jsonl" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
kinds = [r["event"] for r in rows if r.get("what") == "s1 / fake tool"]
assert kinds[0] == "command_start" and kinds[-1] == "command_end", kinds
assert "heartbeat" in kinds, kinds
end = [r for r in rows if r["event"] == "command_end" and r.get("what") == "s1 / fake tool"][0]
assert end["exit"] == "7" and float(end["seconds"]) >= 3, end
beat = [r for r in rows if r["event"] == "heartbeat"][0]
assert int(beat["elapsed"]) >= 1 and "log_idle" in beat, beat
PY
echo "heartbeats reach the console (not the tool's log), carry figures, pass the exit code on and are logged as events -> PASS"

# --- 4. the persistent console log ---
LOGS="$TMP/study/logs"; mkdir -p "$LOGS"
for i in $(seq 1 24); do : > "$LOGS/run_2026010$((i % 10))-0000$((i % 6))$((i % 9)).log"; touch -d "2026-01-01 00:00:$((i + 10))" "$LOGS/run_2026010$((i % 10))-0000$((i % 6))$((i % 9)).log" 2>/dev/null || true; done
before="$(ls "$LOGS"/run_*.log | wc -l)"
RESULTS_DIR="$RES" LOG_DIR="$LOGS" LOG_RETENTION_RUNS=5 bash -c '
    source "'"$ROOT"'/scripts/lib.sh"
    _STAGE_TIMING_ID=3
    start_console_log
    log "a normal line"
    warn "a warning line"
    heartbeat_log "a heartbeat line"
    on_exit_add last_hook
    last_hook() { log "printed by an exit hook"; }
    exit 0
' > "$TMP/shown.txt" 2>&1
latest="$LOGS/run.latest.log"
[[ -e "$latest" ]] || { echo "FAIL: run.latest.log should exist" >&2; ls "$LOGS" >&2; exit 1; }
for text in "a normal line" "a warning line" "a heartbeat line" "printed by an exit hook"; do
    grep -q "$text" "$latest" || { echo "FAIL: the console log is missing: $text" >&2; cat "$latest" >&2; exit 1; }
    grep -q "$text" "$TMP/shown.txt" || { echo "FAIL: the run should still show: $text" >&2; cat "$TMP/shown.txt" >&2; exit 1; }
done
after="$(ls "$LOGS"/run_*.log | wc -l)"
[[ "$after" -le 6 ]] || { echo "FAIL: old console logs should be pruned to LOG_RETENTION_RUNS (had $before, now $after)" >&2; exit 1; }
echo "the console log keeps every line, the exit hooks' last words too, points run.latest.log at itself and prunes old logs -> PASS"

# --- 5. stage 3 reports progress for its long commands ---
for needle in 'run_with_heartbeat "$SAMPLE / fastp trimming"' 'run_with_heartbeat "$SAMPLE / SPAdes assembly"' 'run_with_heartbeat "$SAMPLE / Unicycler assembly"'; do
    grep -qF "$needle" "$ROOT/scripts/03_assemble.sh" || { echo "FAIL: stage 3 should run it under run_with_heartbeat: $needle" >&2; exit 1; }
done
grep -q "start_console_log" "$ROOT/scripts/run_all.sh" || { echo "FAIL: run_all.sh should start the console log" >&2; exit 1; }
echo "stage 3's fastp, SPAdes and Unicycler run under the heartbeat and run_all.sh keeps a console log -> PASS"
echo "ALL RUN EVENT AND HEARTBEAT TESTS PASSED"
