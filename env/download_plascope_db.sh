#!/usr/bin/env bash
# One-time download of PlaScope's Centrifuge databases into
# data/db/plascope/{ecoli,klebsiella}, matching PLASCOPE_ECOLI_DB and
# PLASCOPE_KLEBSIELLA_DB in config/config.sh. Only two pre-built databases
# exist; every other organism is a structural gap run_plascope() skips with
# its own distinct reason, not something this script can fix.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

fetch_one() {
    local label="$1" prefix="$2" url_var="$3" sha_var="$4" archive_name="$5" doi="$6"
    local dest_parent; dest_parent="$(dirname "$prefix")"
    mkdir -p "$dest_parent"

    if [[ -s "${prefix}.1.cf" ]]; then
        echo "[plascope_db] $label already present at $prefix — nothing to do."
        return 0
    fi

    echo "[plascope_db] PlaScope's $label database is hosted on Zenodo (DOI $doi)."
    echo
    echo "Option A (recommended) — download + unpack manually, then point config to it:"
    echo "    cd $dest_parent"
    echo "    wget -O $archive_name https://zenodo.org/record/${doi##*.}/files/$archive_name"
    echo "    tar -xzf $archive_name        # extracts the .1.cf/.2.cf/.3.cf index files here"
    echo "    # ensure the result is at: ${prefix}.1.cf (etc.)"
    echo
    echo "Option B — if you know the URL, set it here and re-run this script:"
    echo "    ${url_var}=<url> bash env/download_plascope_db.sh"
    echo "    # Recommended: also pin ${sha_var}=<sha256 of $archive_name> so a"
    echo "    # truncated download, a stale mirror, or a tampered transfer is"
    echo "    # detected instead of silently becoming ground truth."

    local url="${!url_var:-}" sha="${!sha_var:-}"
    if [[ -n "$url" ]]; then
        echo "[plascope_db] downloading $label from provided ${url_var} ..."
        (cd "$dest_parent" && wget -O "$archive_name" "$url")
        if [[ -n "$sha" ]]; then
            echo "[plascope_db] verifying checksum ..."
            (cd "$dest_parent" && echo "${sha}  $archive_name" | sha256sum -c -) || {
                rm -f "$dest_parent/$archive_name"
                die "downloaded $archive_name did not match ${sha_var}; refusing to use it"
            }
        else
            warn "${sha_var} not set; skipping checksum verification of the downloaded database"
        fi
        (cd "$dest_parent" && tar -xzf "$archive_name" && rm -f "$archive_name")
        echo "[plascope_db] done. $label DB should be at $prefix"
    fi
}

fetch_one "E. coli" "$PLASCOPE_ECOLI_DB" PLASCOPE_ECOLI_DB_URL PLASCOPE_ECOLI_DB_SHA256 \
    chromosome_plasmid_db.tar.gz 10.5281/zenodo.1311641
fetch_one "Klebsiella" "$PLASCOPE_KLEBSIELLA_DB" PLASCOPE_KLEBSIELLA_DB_URL PLASCOPE_KLEBSIELLA_DB_SHA256 \
    Klebsiella_PlaScope.tar.gz 10.5281/zenodo.1311647
