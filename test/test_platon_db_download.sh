#!/usr/bin/env bash
# env/download_platon_db.sh downloads Platon's published Zenodo archive by default
# (no URL to supply), resumes with curl -C -, refuses a file of the wrong size,
# unpacks into PLATON_DB, and does nothing when the database is already present.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/src/db" "$TMP/bin"
for i in 1 2 3; do echo "data $i" > "$TMP/src/db/file$i"; done
( cd "$TMP/src" && tar -czf "$TMP/db.tar.gz" db )
SIZE="$(stat -c %s "$TMP/db.tar.gz")"

cat > "$TMP/bin/curl" <<EOF
#!/usr/bin/env bash
echo "curl \$*" >> "$TMP/curl.log"
out=""; while [[ \$# -gt 0 ]]; do [[ "\$1" == "-o" ]] && out="\$2"; shift; done
cp "\$FAKE_ARCHIVE" "\$out"
EOF
chmod +x "$TMP/bin/curl"

run() { PATH="$TMP/bin:$PATH" PLASBENCH_DB_DIR="$TMP/store" DATA_DIR="$TMP/data" PLASBENCH_LOCAL_SETTINGS=/dev/null \
    PLASBENCH_ASSUME_ONLINE=1 PLASBENCH_DOWNLOAD_ATTEMPTS=2 PLASBENCH_RETRY_SLEEP=0 \
    FAKE_ARCHIVE="$TMP/db.tar.gz" bash "$ROOT/env/download_platon_db.sh"; }

# Wrong size for the default URL: refused, nothing unpacked, partial file kept for a resume.
if run > "$TMP/wrong.log" 2>&1; then echo "FAIL: a wrong-size archive was accepted" >&2; cat "$TMP/wrong.log" >&2; exit 1; fi
grep -q "expected 1690687855" "$TMP/wrong.log" || { echo "FAIL: no size message" >&2; cat "$TMP/wrong.log" >&2; exit 1; }
[[ -f "$TMP/store/platon/db.tar.gz.part" ]] || { echo "FAIL: the partial download was not kept" >&2; ls -la "$TMP/store/platon" >&2; exit 1; }
rm -f "$TMP/store/platon/db.tar.gz.part"
[[ ! -d "$TMP/store/platon/db" ]] || { echo "FAIL: a wrong-size archive was unpacked" >&2; exit 1; }
grep -q -- "-C - .*https://zenodo.org/records/4066768/files/db.tar.gz" "$TMP/curl.log" \
    || { echo "FAIL: did not resume-download the documented Zenodo file" >&2; cat "$TMP/curl.log" >&2; exit 1; }
echo "default URL is Platon's Zenodo archive, downloaded with resume; a wrong size is refused -> PASS"

# Right size: unpacked into the store.
PLATON_DB_SIZE="$SIZE" run > "$TMP/ok.log" 2>&1 || { echo "FAIL: correct archive rejected" >&2; cat "$TMP/ok.log" >&2; exit 1; }
[[ "$(ls "$TMP/store/platon/db" | wc -l)" -eq 3 ]] || { echo "FAIL: database not unpacked into the store" >&2; cat "$TMP/ok.log" >&2; exit 1; }
[[ ! -e "$TMP/store/platon/db.tar.gz" ]] || { echo "FAIL: archive left behind" >&2; exit 1; }
echo "a verified archive is unpacked into the machine store -> PASS"

# Already present: no download.
: > "$TMP/curl.log"
run > "$TMP/again.log" 2>&1
grep -q "already present" "$TMP/again.log" && [[ ! -s "$TMP/curl.log" ]] \
    || { echo "FAIL: an existing database was downloaded again" >&2; exit 1; }
echo "an existing database is left alone -> PASS"
echo "ALL PLATON DATABASE DOWNLOAD TESTS PASSED"
