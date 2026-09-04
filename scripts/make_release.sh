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

# Prefer `git archive`: it exports the COMMITTED tree with .gitattributes
# line-ending normalisation applied. Tarring the working tree instead is how a
# Windows checkout shipped test/run_tests.sh with CRLF, which made `plasbench
# test` die with "set: pipefail: invalid option name" on Linux. Fall back to the
# working tree only when this is not a git checkout -- for example when
# rebuilding from an already-unpacked release archive.
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    echo "[make_release] exporting committed tree via git archive"
    git -C "$ROOT" archive --format=tar HEAD | (cd "$STAGE/$PKG" && tar -xf -)
else
    echo "[make_release] not a git checkout; packaging the working tree"
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
fi

# Refuse to ship CRLF rather than silently repairing it. A CR breaks a shell
# script on Linux, and breaks the SHA-256 that `validate-cohort --verify-lock`
# checks for a cohort TSV. If this fires, the fix belongs in .gitattributes
# plus `git add --renormalize .`, not in the release build.
CR="$(printf '\r')"
OFFENDERS="$(grep -rlI -- "$CR" "$STAGE/$PKG" 2>/dev/null || true)"
if [[ -n "$OFFENDERS" ]]; then
    echo "[make_release] ERROR: CRLF line endings found in files that must be LF:" >&2
    printf '    %s\n' $OFFENDERS >&2
    echo "[make_release] fix with: git add --renormalize . && git commit" >&2
    exit 1
fi

chmod +x "$STAGE/$PKG/install.sh" 2>/dev/null || true
find "$STAGE/$PKG/scripts" "$STAGE/$PKG/adapters" "$STAGE/$PKG/env" \
     -name '*.sh' -exec chmod +x {} + 2>/dev/null || true

mkdir -p dist
tar -czf "dist/$PKG.tar.gz" -C "$STAGE" "$PKG"
( cd dist && sha256sum "$PKG.tar.gz" > "$PKG.tar.gz.sha256" )

printf 'wrote dist/%s.tar.gz (%s)\n' "$PKG" "$(du -h "dist/$PKG.tar.gz" | cut -f1)"
cat "dist/$PKG.tar.gz.sha256"
