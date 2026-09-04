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

# Prefer `git archive`: it exports the COMMITTED tree, honouring the
# export-ignore attributes that keep audit output and CI config out of a user
# download. Fall back to the working tree only when this is not a git checkout,
# for example when rebuilding from an already-unpacked release archive.
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

# Normalise line endings, then assert. A CR makes a shell script die on Linux
# with "set: pipefail: invalid option name", and changes the SHA-256 that
# `validate-cohort --verify-lock` checks for a cohort TSV. `git archive` run on
# Windows emits CRLF for text files regardless of .gitattributes eol=lf, so the
# build has to normalise rather than merely refuse -- otherwise no release could
# ever be cut from a Windows checkout. CRLF in .md/.py is harmless and is left
# alone deliberately.
normalise_line_endings() {
    find "$STAGE/$PKG" -type f \
        \( -name '*.sh' -o -name '*.tsv' -o -name '*.json' \) -print0 |
    while IFS= read -r -d '' file; do
        tr -d '\015' < "$file" > "$file.norm" && mv "$file.norm" "$file"
    done
}

find_cr_offenders() {
    local cr
    cr="$(printf '\015')"
    find "$STAGE/$PKG" -type f \
        \( -name '*.sh' -o -name '*.tsv' -o -name '*.json' \) \
        -exec grep -l -- "$cr" {} + 2>/dev/null || true
}

normalise_line_endings
offenders="$(find_cr_offenders)"
if [[ -n "$offenders" ]]; then
    echo "[make_release] ERROR: CRLF survived normalisation in:" >&2
    echo "$offenders" | sed 's/^/    /' >&2
    exit 1
fi
echo "[make_release] line endings verified: no CR in .sh, .tsv or .json"

chmod +x "$STAGE/$PKG/install.sh" 2>/dev/null || true
find "$STAGE/$PKG/scripts" "$STAGE/$PKG/adapters" "$STAGE/$PKG/env" \
     -name '*.sh' -exec chmod +x {} + 2>/dev/null || true

mkdir -p dist
tar -czf "dist/$PKG.tar.gz" -C "$STAGE" "$PKG"
( cd dist && sha256sum "$PKG.tar.gz" > "$PKG.tar.gz.sha256" )

printf 'wrote dist/%s.tar.gz (%s)\n' "$PKG" "$(du -h "dist/$PKG.tar.gz" | cut -f1)"
cat "dist/$PKG.tar.gz.sha256"
