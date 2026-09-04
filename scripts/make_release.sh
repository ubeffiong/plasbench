#!/usr/bin/env bash
# Build the self-contained release tarball that users download instead of
# cloning the repository: the whole runnable tree plus install.sh, versioned
# from pyproject.toml and accompanied by a SHA-256 checksum.
#
#   bash scripts/make_release.sh            # -> dist/plasbench-<version>.tar.gz
#
# Kept as a script rather than a Makefile recipe so the quoting stays readable.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 - <<'PYEOF'
import re, pathlib, sys
text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    sys.exit("could not read version from pyproject.toml")
print(match.group(1))
PYEOF
)"

PKG="plasbench-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$PKG"

# Ship the working tree minus everything a user must not receive: git history,
# downloaded data, run outputs, build residue and local credentials.
tar -cf - \
    --exclude=./.git \
    --exclude=./.github \
    --exclude=./.pytest_cache \
    --exclude=./data \
    --exclude=./results \
    --exclude=./results_demo \
    --exclude=./results_audit \
    --exclude=./logs \
    --exclude=./tmp \
    --exclude=./build \
    --exclude=./dist \
    --exclude=./plasbench.egg-info \
    --exclude=./.ncbi.env \
    --exclude='*.pyc' \
    --exclude=__pycache__ \
    . | (cd "$STAGE/$PKG" && tar -xf -)

chmod +x "$STAGE/$PKG/install.sh" 2>/dev/null || true
find "$STAGE/$PKG/scripts" "$STAGE/$PKG/adapters" "$STAGE/$PKG/env" \
     -name '*.sh' -exec chmod +x {} + 2>/dev/null || true

mkdir -p dist
tar -czf "dist/$PKG.tar.gz" -C "$STAGE" "$PKG"
( cd dist && sha256sum "$PKG.tar.gz" > "$PKG.tar.gz.sha256" )

printf 'wrote dist/%s.tar.gz (%s)\n' "$PKG" "$(du -h "dist/$PKG.tar.gz" | cut -f1)"
cat "dist/$PKG.tar.gz.sha256"
