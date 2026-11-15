#!/usr/bin/env bash
# One-time download of the Platon database, matching PLATON_DB in config/config.sh.
#
# By default it fetches Platon's published database archive from Zenodo
# (record 4066768, db.tar.gz, 1690687855 bytes -- the same file README step 7a
# documents), resumes an interrupted download, and refuses to unpack a file of
# the wrong size. To use a different release, set PLATON_DB_URL (and, for a file
# of another size, PLATON_DB_SIZE or PLATON_DB_SHA256).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

DEFAULT_URL="https://zenodo.org/records/4066768/files/db.tar.gz"
DEFAULT_SIZE=1690687855

DEST_PARENT="$(dirname "$PLATON_DB")"
mkdir -p "$DEST_PARENT"

if [[ -d "$PLATON_DB" ]] && [[ -n "$(ls -A "$PLATON_DB" 2>/dev/null)" ]]; then
    echo "[platon_db] already present at $PLATON_DB — nothing to do."
    exit 0
fi

URL="${PLATON_DB_URL:-$DEFAULT_URL}"
if [[ -n "${PLATON_DB_SIZE:-}" ]]; then
    SIZE="$PLATON_DB_SIZE"
elif [[ "$URL" == "$DEFAULT_URL" ]]; then
    SIZE="$DEFAULT_SIZE"
else
    SIZE=""
fi

echo "[platon_db] downloading Platon's database (~1.7 GB) into $DEST_PARENT"
echo "[platon_db] from $URL"
echo "[platon_db] it resumes: a dropped connection or a re-run continues where it stopped,"
echo "[platon_db] and while the internet is down it waits instead of failing."
cd "$DEST_PARENT"
resumable_download "$URL" "$DEST_PARENT/db.tar.gz" "$SIZE" \
    || die "Platon database download did not finish (expected ${SIZE:-unknown} bytes); run 'bash env/download_platon_db.sh' again to continue it"
[[ -n "$SIZE" ]] && echo "[platon_db] size verified ($SIZE bytes)"
if [[ -n "${PLATON_DB_SHA256:-}" ]]; then
    echo "[platon_db] verifying checksum ..."
    echo "${PLATON_DB_SHA256}  db.tar.gz" | sha256sum -c - || {
        rm -f db.tar.gz
        die "downloaded db.tar.gz did not match PLATON_DB_SHA256; refusing to use it"
    }
fi

echo "[platon_db] unpacking ..."
tar -xzf db.tar.gz
rm -f db.tar.gz
if [[ -d "$PLATON_DB" ]] && [[ -n "$(ls -A "$PLATON_DB" 2>/dev/null)" ]]; then
    echo "[platon_db] done: $PLATON_DB ($(ls "$PLATON_DB" | wc -l) files)"
else
    die "the archive did not unpack to $PLATON_DB; check the archive layout"
fi
