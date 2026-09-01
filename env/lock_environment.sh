#!/usr/bin/env bash
# Resolve env/environment.yml in the pinned micromamba image and write an
# explicit, platform-specific lock. Run this deliberately when updating deps.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
IMAGE="${PLASBENCH_LOCK_IMAGE:-mambaorg/micromamba:1.5.10}"
OUT="${1:-$HERE/environment.lock.yml}"
OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
case "$OUT_ABS" in
  "$ROOT"/*) CONTAINER_OUT="/workspace/${OUT_ABS#"$ROOT"/}" ;;
  *) echo "lock output must be inside the project root: $OUT_ABS" >&2; exit 2 ;;
esac

docker run --rm --user root -v "$ROOT:/workspace" -w /workspace "$IMAGE" \
  /bin/sh -c "micromamba create -q -y -n plasbench -f env/environment.yml && micromamba env export -n plasbench --explicit > '$CONTAINER_OUT'"
grep -q '^@EXPLICIT$' "$OUT_ABS" || { rm -f "$OUT_ABS"; echo "lock generation failed" >&2; exit 1; }
echo "Wrote explicit environment lock: $OUT_ABS"
