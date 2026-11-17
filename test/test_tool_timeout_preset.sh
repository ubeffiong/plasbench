#!/usr/bin/env bash
# Audit AU-010: no default tool timeout (a limit changes scores), but an opt-in preset and a start-of-run notice.
#   default: TOOL_TIMEOUT_SECONDS stays blank and stage 4 says so; generous preset: 172800 and no notice; explicit value wins over the preset; unknown preset is an error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
val() { env -u TOOL_TIMEOUT_SECONDS "$@" bash -c 'source "$1/config/config.sh"; printf "[%s]" "$TOOL_TIMEOUT_SECONDS"' _ "$ROOT" 2>/dev/null; }
[[ "$(val PLASBENCH_X=1)" == "[]" ]] || { echo "FAIL: default must stay blank (no limit)" >&2; exit 1; }
[[ "$(val PLASBENCH_TOOL_TIMEOUT_PRESET=generous)" == "[172800]" ]] || { echo "FAIL: generous preset must set 172800" >&2; exit 1; }
[[ "$(PLASBENCH_TOOL_TIMEOUT_PRESET=generous TOOL_TIMEOUT_SECONDS=90 bash -c 'source "$1/config/config.sh"; printf "[%s]" "$TOOL_TIMEOUT_SECONDS"' _ "$ROOT")" == "[90]" ]] || { echo "FAIL: an explicit value must win" >&2; exit 1; }
if PLASBENCH_TOOL_TIMEOUT_PRESET=nonsense bash -c 'source "$1/config/config.sh"' _ "$ROOT" >/dev/null 2>&1; then echo "FAIL: an unknown preset must be an error" >&2; exit 1; fi
echo "default blank, generous = 172800, explicit wins, unknown refused -> PASS"
out="$(env -u TOOL_TIMEOUT_SECONDS bash -c 'source "$1/config/config.sh"; source "$1/scripts/lib.sh"; tool_timeout_notice' _ "$ROOT" 2>&1)"
grep -q "no tool time limit is set" <<<"$out" && grep -q "PLASBENCH_TOOL_TIMEOUT_PRESET=generous" <<<"$out" || { echo "FAIL: the notice must appear and name the preset" >&2; echo "$out" >&2; exit 1; }
out="$(PLASBENCH_TOOL_TIMEOUT_PRESET=generous bash -c 'source "$1/config/config.sh"; source "$1/scripts/lib.sh"; tool_timeout_notice' _ "$ROOT" 2>&1)"
[[ -z "$out" ]] || { echo "FAIL: no notice when a limit is set" >&2; echo "$out" >&2; exit 1; }
grep -q '^tool_timeout_notice$' "$ROOT/scripts/04_run_tools.sh" || { echo "FAIL: stage 4 must call the notice" >&2; exit 1; }
echo "notice shown when unset, silent when set, called by stage 4 -> PASS"
echo "ALL TOOL TIMEOUT PRESET TESTS PASSED"
