#!/usr/bin/env bash
# One-time download of the Platon database into data/db/platon/db,
# matching PLATON_DB in config/config.sh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

DEST_PARENT="$(dirname "$PLATON_DB")"      # .../data/db/platon
mkdir -p "$DEST_PARENT"

if [[ -d "$PLATON_DB" ]] && [[ -n "$(ls -A "$PLATON_DB" 2>/dev/null)" ]]; then
    echo "[platon_db] already present at $PLATON_DB — nothing to do."
    exit 0
fi

echo "[platon_db] Platon's DB is hosted on Zenodo (~1.4 GB)."
echo "[platon_db] Fetching the current release link from the Platon docs is recommended,"
echo "[platon_db] because the Zenodo version is periodically updated."
echo
echo "Option A (recommended) — download + unpack manually, then point config to it:"
echo "    # find the current 'db.tar.gz' link at: https://github.com/oschwengers/platon"
echo "    cd $DEST_PARENT"
echo "    wget -O db.tar.gz <CURRENT_PLATON_DB_URL>"
echo "    tar -xzf db.tar.gz         # creates a 'db/' folder"
echo "    # ensure the result is at: $PLATON_DB"
echo
echo "Option B — if you know the URL, set it here and re-run this script:"
echo "    PLATON_DB_URL=<url> bash env/download_platon_db.sh"
echo "    # Recommended: also pin PLATON_DB_SHA256=<sha256 of db.tar.gz> so a"
echo "    # truncated download, a stale mirror, or a tampered transfer is"
echo "    # detected instead of silently becoming ground truth."

if [[ -n "${PLATON_DB_URL:-}" ]]; then
    echo "[platon_db] downloading from provided PLATON_DB_URL ..."
    cd "$DEST_PARENT"
    wget -O db.tar.gz "$PLATON_DB_URL"
    if [[ -n "${PLATON_DB_SHA256:-}" ]]; then
        echo "[platon_db] verifying checksum ..."
        echo "${PLATON_DB_SHA256}  db.tar.gz" | sha256sum -c - || {
            rm -f db.tar.gz
            die "downloaded db.tar.gz did not match PLATON_DB_SHA256; refusing to use it"
        }
    else
        warn "PLATON_DB_SHA256 not set; skipping checksum verification of the downloaded database"
    fi
    tar -xzf db.tar.gz
    rm -f db.tar.gz
    echo "[platon_db] done. DB should be at $PLATON_DB"
fi
