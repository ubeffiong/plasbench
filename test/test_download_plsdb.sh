#!/usr/bin/env bash
# env/download_plsdb.sh without the network: file:// URLs stand in for the download.
#   a FASTA file                      -> accepted, provenance records url, sha256, bytes, record count
#   the same file with a wrong sha256 -> refused, nothing installed
#   an HTML page (what the plsMD Dockerfile URL returns) -> refused, nothing installed
#   no PLSDB_URL                      -> refused
#   a second run                      -> a no-op while the file is present
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v curl >/dev/null 2>&1 || { echo "SKIP: curl not available"; exit 0; }

printf '>NZ_A plasmid one\nACGTACGTAC\n>NZ_B plasmid two\nGGGGCCCCAA\n' > "$TMP/good.fasta"
printf '<!doctype html><html><body>PLSDB download page</body></html>\n' > "$TMP/page.html"
GOOD_SHA="$(sha256sum "$TMP/good.fasta" | awk '{print $1}')"
# curl on Windows wants a drive-letter path in a file URL; elsewhere the plain path works.
if command -v cygpath >/dev/null 2>&1; then BASE="file:///$(cygpath -m "$TMP")"; else BASE="file://$TMP"; fi
URL_GOOD="$BASE/good.fasta"
URL_PAGE="$BASE/page.html"

run() { env DATA_DIR="$TMP/data" "$@" bash "$ROOT/env/download_plsdb.sh" > "$TMP/out.log" 2>&1; }

if run PLSDB_URL="$URL_PAGE"; then echo "FAIL: an HTML page must be refused" >&2; cat "$TMP/out.log" >&2; exit 1; fi
[[ ! -e "$TMP/data/db/plsdb/sequences.fasta" ]] || { echo "FAIL: nothing may be installed from a web page" >&2; exit 1; }
grep -q "not FASTA" "$TMP/out.log" || { echo "FAIL: the refusal should say it is not FASTA" >&2; exit 1; }
echo "an HTML page is refused and nothing is installed -> PASS"

if run PLSDB_URL="$URL_GOOD" PLSDB_SHA256="$(printf 0%.0s $(seq 64))"; then echo "FAIL: a wrong sha256 must be refused" >&2; exit 1; fi
[[ ! -e "$TMP/data/db/plsdb/sequences.fasta" ]] || { echo "FAIL: nothing may be installed on a checksum mismatch" >&2; exit 1; }
echo "a checksum mismatch is refused -> PASS"

if env DATA_DIR="$TMP/data" bash "$ROOT/env/download_plsdb.sh" > "$TMP/out.log" 2>&1; then echo "FAIL: no URL must be refused" >&2; exit 1; fi
echo "no PLSDB_URL is refused -> PASS"

run PLSDB_URL="$URL_GOOD" PLSDB_SHA256="$GOOD_SHA" || { echo "FAIL: a verified FASTA should install" >&2; cat "$TMP/out.log" >&2; exit 1; }
PROV="$TMP/data/db/plsdb/sequences.provenance.json"
grep -q "\"records\": 2" "$PROV" && grep -q "\"sha256\": \"$GOOD_SHA\"" "$PROV" && grep -q "\"sha256_verified\": true" "$PROV" \
    || { echo "FAIL: provenance incomplete" >&2; cat "$PROV" >&2; exit 1; }
echo "a verified FASTA installs with provenance (2 records, sha256, verified) -> PASS"

run PLSDB_URL="$URL_PAGE" || { echo "FAIL: a second run must be a no-op while the file exists" >&2; exit 1; }
grep -q "already present" "$TMP/out.log" || { echo "FAIL: expected the already-present message" >&2; exit 1; }
echo "a second run is a no-op -> PASS"
echo "ALL DOWNLOAD PLSDB TESTS PASSED"
