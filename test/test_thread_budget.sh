#!/usr/bin/env bash
# Regression: when THREADS is not set, config/config.sh divides the detected cores
# across the concurrent job slots (MAX_PARALLEL_SAMPLES x MAX_PARALLEL_TOOLS), so
# raising the slots never asks for slots x cores threads at once. An explicit
# THREADS is kept, and the default single slot still gets every core.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

threads_for() {
    env -u THREADS "$@" bash -c 'source "$0/config/config.sh" >/dev/null 2>&1; echo "$THREADS $MOB_RECON_THREADS $(plasbench_detect_cores)"' "$ROOT"
}

read -r t tool cores <<< "$(threads_for)"
[[ "$t" -eq "$cores" && "$tool" -eq "$cores" ]] || { echo "FAIL: one slot must get all $cores cores, got $t" >&2; exit 1; }
echo "a single slot gets every core ($cores) -> PASS"

read -r t tool cores <<< "$(threads_for MAX_PARALLEL_SAMPLES=2 MAX_PARALLEL_TOOLS=3)"
expected=$(( cores / 6 )); [[ "$expected" -ge 1 ]] || expected=1
[[ "$t" -eq "$expected" && "$tool" -eq "$expected" ]] || { echo "FAIL: 6 slots on $cores cores should get $expected each, got $t" >&2; exit 1; }
echo "6 slots share the cores: $expected thread(s) each, per-tool defaults follow -> PASS"

read -r t _ cores <<< "$(threads_for MAX_PARALLEL_SAMPLES=$(( cores * 4 )))"
[[ "$t" -eq 1 ]] || { echo "FAIL: more slots than cores must floor at 1 thread, got $t" >&2; exit 1; }
echo "more slots than cores floors at 1 thread -> PASS"

read -r t _ _ <<< "$(threads_for THREADS=5 MAX_PARALLEL_SAMPLES=4)"
[[ "$t" -eq 5 ]] || { echo "FAIL: an explicit THREADS must be kept, got $t" >&2; exit 1; }
echo "an explicit THREADS is kept -> PASS"

echo "ALL THREAD BUDGET TESTS PASSED"
