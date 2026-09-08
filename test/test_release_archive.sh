#!/usr/bin/env bash
# Release archives are a supported installation path. Verify the archive is
# runnable, contains the workflow assets the thin Python CLI delegates to, and
# never leaks local data, credentials, or generated reports.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

version="$(python3 - <<'PY'
import pathlib
import re

text = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    raise SystemExit("could not read project version")
print(match.group(1))
PY
)"
archive="$ROOT/dist/plasbench-$version.tar.gz"

rm -f "$archive" "$archive.sha256"
(cd "$ROOT" && bash scripts/make_release.sh >/dev/null)
[[ -s "$archive" && -s "$archive.sha256" ]] || { echo "FAIL: release archive/checksum missing" >&2; exit 1; }
(cd "$ROOT/dist" && sha256sum -c "plasbench-$version.tar.gz.sha256" >/dev/null)

tar -xzf "$archive" -C "$TMP"
release="$TMP/plasbench-$version"
for required in install.sh update.sh scripts/run_all.sh python/score_plasmids.py adapters/adapt_mob_recon.sh config/config.sh env/environment.lock.yml assets/enterprise/template.html docs/USER_GUIDE.md; do
    [[ -f "$release/$required" ]] || { echo "FAIL: release archive omitted $required" >&2; exit 1; }
done
for forbidden in .git .ncbi.env config/local.env data results results_demo results_audit logs tmp fasterq.tmp.Ub-Effiong.494; do
    [[ ! -e "$release/$forbidden" ]] || { echo "FAIL: release archive leaked local artifact $forbidden" >&2; exit 1; }
done

(cd "$release" && python3 -m plasbench --help >/dev/null)
echo "release archive is complete, checksum-valid, runnable, and free of local artifacts -> PASS"
echo "ALL RELEASE ARCHIVE TESTS PASSED"
