#!/usr/bin/env bash
# One-time download of the Bakta reference database, needed for
# RUN_PROTEIN_ANNOTATION=1 with PROTEIN_ANNOTATION_ENGINE=bakta.
#
# Usage:
#   bash env/download_bakta_db.sh              # "light" DB, asks first
#   bash env/download_bakta_db.sh --yes        # no prompt
#   bash env/download_bakta_db.sh --full       # the large DB instead of light
#   bash env/download_bakta_db.sh --output DIR # default: $DATA_DIR/db/bakta
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
DB_TYPE="light"
OUTPUT_DIR="$DATA_DIR/db/bakta"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1; shift ;;
        --full) DB_TYPE="full"; shift ;;
        --light) DB_TYPE="light"; shift ;;
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        *) die "unknown argument: $1 (usage: download_bakta_db.sh [-y|--yes] [--full|--light] [--output DIR])" ;;
    esac
done

have bakta_db || die "bakta_db not found; install Bakta first: plasbench install-tools annotation"

DB_PATH="$OUTPUT_DIR/db"
[[ "$DB_TYPE" == "light" ]] && DB_PATH="$OUTPUT_DIR/db-light"

# bakta_db writes a version.json into the extracted database on a successful
# download; its presence is what the real `bakta` command's own database
# check also relies on, so it is a reasonable "already present" signal here.
if [[ -s "$DB_PATH/version.json" ]]; then
    log "Bakta $DB_TYPE database already present at $DB_PATH (version.json found)."
    log "Point PlasBench at it with: export PROTEIN_ANNOTATION_DATABASE=$DB_PATH"
    exit 0
fi

if [[ "$DB_TYPE" == "light" ]]; then
    SIZE_NOTE="~1.3 GB compressed, ~3.9 GB extracted"
else
    SIZE_NOTE="~30 GB compressed, ~84 GB extracted"
fi
log "Bakta needs a reference database before it can annotate predicted proteins."
log "  Type       : $DB_TYPE ($SIZE_NOTE)"
log "  Install to : $DB_PATH"
[[ "$DB_TYPE" == "full" ]] && warn "the 'full' database is large; 'light' (this script's default) is sufficient for standard bacterial annotation -- pass --light to switch back"
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    REPLY=""
    read -r -p "Download the Bakta $DB_TYPE database now? [y/N] " REPLY || true
    case "$REPLY" in
        y|Y|yes|YES|Yes) : ;;
        *) log "Skipped. Re-run with --yes to skip this prompt."; exit 1 ;;
    esac
fi

mkdir -p "$OUTPUT_DIR"
log "Running bakta_db download (this can take a while for a large database)..."
bakta_db download --output "$OUTPUT_DIR" --type "$DB_TYPE" || die "bakta_db download failed"

log "Bakta $DB_TYPE database ready at $DB_PATH."
log "Point PlasBench at it with: export PROTEIN_ANNOTATION_DATABASE=$DB_PATH"
