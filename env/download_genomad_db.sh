#!/usr/bin/env bash
# One-time download of the geNomad reference database, needed for
# RUN_GENOMAD=1. geNomad ships its own downloader command, which fetches the
# versioned Zenodo tarball and unpacks it -- much closer to Bakta's DB
# installer pattern than Platon's manual-URL one.
#
# Usage:
#   bash env/download_genomad_db.sh              # asks first
#   bash env/download_genomad_db.sh --yes        # no prompt
#   bash env/download_genomad_db.sh --output DIR # default: $GENOMAD_DB
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
OUTPUT_DIR="$GENOMAD_DB"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1; shift ;;
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        *) die "unknown argument: $1 (usage: download_genomad_db.sh [-y|--yes] [--output DIR])" ;;
    esac
done

have genomad || die "genomad not found; install it first: plasbench install-tools genomad"

# `genomad download-database DIR` creates DIR/genomad_db/. Presence (non-empty)
# is used as the "already downloaded" signal, the same directory-existence
# check env/download_platon_db.sh uses -- geNomad's exact internal marker
# filename is not relied on here, only that the tool populated the directory.
DB_PATH="$OUTPUT_DIR/genomad_db"
if [[ -d "$DB_PATH" ]] && [[ -n "$(ls -A "$DB_PATH" 2>/dev/null)" ]]; then
    log "geNomad database already present at $DB_PATH — nothing to do."
    log "Point PlasBench at it with: export GENOMAD_DB=$OUTPUT_DIR"
    exit 0
fi

log "geNomad needs its reference database before it can classify contigs."
log "  Install to : $DB_PATH"
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    REPLY=""
    read -r -p "Download the geNomad database now? [y/N] " REPLY || true
    case "$REPLY" in
        y|Y|yes|YES|Yes) : ;;
        *) log "Skipped. Re-run with --yes to skip this prompt."; exit 1 ;;
    esac
fi

mkdir -p "$OUTPUT_DIR"
log "Running genomad download-database (this can take a while)..."
genomad download-database "$OUTPUT_DIR" || die "genomad download-database failed"

log "geNomad database ready at $DB_PATH."
log "Point PlasBench at it with: export GENOMAD_DB=$OUTPUT_DIR"
