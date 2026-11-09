#!/usr/bin/env bash
# Regression: the once-per-process capability cache (scripts/lib.sh
# load_capabilities) must answer every registry question exactly as the per-call
# `python3 tool_capabilities.py` lookups it replaced, for every registered tool,
# for an unknown tool, and for a registry that fails validation.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PROJECT_ROOT="$ROOT"
# shellcheck source=/dev/null
source "$ROOT/scripts/lib.sh"

old_binning() { python3 "$ROOT/python/tool_capabilities.py" --registry "$1" --tool "$2" --binning-capable >/dev/null 2>&1 && echo y || echo n; }
old_track() { python3 "$ROOT/python/tool_capabilities.py" --registry "$1" --tool "$2" --analysis-track 2>/dev/null || true; }
old_lr() { python3 "$ROOT/python/tool_capabilities.py" --registry "$1" --tool "$2" --requires-independent-long-read-truth >/dev/null 2>&1 && echo y || echo n; }
new_binning() { capability_binning "$1" "$2" && echo y || echo n; }
new_track() { capability_track "$1" "$2" || true; }
new_lr() { capability_requires_lr_truth "$1" "$2" && echo y || echo n; }

compare_registry() {
    local registry="$1" tool n=0
    for tool in $(cut -f1 "$registry" | tail -n +2) not_a_registered_tool; do
        [[ "$(old_binning "$registry" "$tool")" == "$(new_binning "$registry" "$tool")" ]] || { echo "FAIL: binning_capable differs for $tool" >&2; exit 1; }
        [[ "$(old_track "$registry" "$tool" | tr -d '\r')" == "$(new_track "$registry" "$tool")" ]] || { echo "FAIL: analysis_track differs for $tool" >&2; exit 1; }
        [[ "$(old_lr "$registry" "$tool")" == "$(new_lr "$registry" "$tool")" ]] || { echo "FAIL: long-read-truth requirement differs for $tool" >&2; exit 1; }
        n=$((n + 1))
    done
    echo "$n"
}

n="$(compare_registry "$ROOT/config/tool_capabilities.tsv")"
echo "cache matches per-call lookups for $n tools (including an unknown tool) -> PASS"

# A registry that fails validation (duplicate tool): every answer is negative/empty, as before.
{ cat "$ROOT/config/tool_capabilities.tsv"; sed -n 2p "$ROOT/config/tool_capabilities.tsv"; } > "$TMP/bad.tsv"
compare_registry "$TMP/bad.tsv" > /dev/null
capability_binning "$TMP/bad.tsv" mob_recon && { echo "FAIL: an invalid registry must not answer yes" >&2; exit 1; }
echo "an invalid registry answers exactly as before (no capabilities) -> PASS"

echo "ALL CAPABILITY CACHE TESTS PASSED"
