#!/usr/bin/env bash
# One-time download of PLASMe's reference database, needed for RUN_PLASME=1.
# PLASMe bundles its own downloader script (PLASMe_db.py, ~12.4 GB) rather
# than a conda-packaged subcommand -- like PLASMe.py itself, it is expected
# on PATH after PLASMe's manual git-clone install (see env/install_tools.sh's
# plasme case).
#
# Usage:
#   bash env/download_plasme_db.sh              # asks first
#   bash env/download_plasme_db.sh --yes        # no prompt
#   bash env/download_plasme_db.sh --output DIR # default: $PLASME_DB
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
OUTPUT_DIR="$PLASME_DB"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1; shift ;;
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        *) die "unknown argument: $1 (usage: download_plasme_db.sh [-y|--yes] [--output DIR])" ;;
    esac
done

have PLASMe_db.py || die "PLASMe_db.py not found; install PLASMe first (see INSTALL.md: git clone + conda env create -f plasme.yaml)"

# database_present checks for any file at all, rather than one named marker,
# since PLASMe_db.py's exact extracted-file layout is not relied on here --
# only that the directory was actually populated, not left empty by a
# partial or failed download.
if [[ -d "$OUTPUT_DIR" ]] && [[ -n "$(ls -A "$OUTPUT_DIR" 2>/dev/null)" ]]; then
    log "PLASMe database already present at $OUTPUT_DIR — nothing to do."
    log "Point PlasBench at it with: export PLASME_DB=$OUTPUT_DIR"
    exit 0
fi

log "PLASMe needs its reference database before it can classify contigs (~12.4 GB)."
log "  Install to : $OUTPUT_DIR"
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    REPLY=""
    read -r -p "Download the PLASMe database now? [y/N] " REPLY || true
    case "$REPLY" in
        y|Y|yes|YES|Yes) : ;;
        *) log "Skipped. Re-run with --yes to skip this prompt."; exit 1 ;;
    esac
fi

mkdir -p "$OUTPUT_DIR"
log "Running PLASMe_db.py (this can take a while for a ~12.4 GB database)..."
# PLASMe_db.py's exact flag for a custom destination is not independently
# confirmed (its README documents the script's existence and default
# in-place download, not every flag) -- verify against the installed
# version's --help at first real use and adjust if it differs.
PLASMe_db.py --database "$OUTPUT_DIR" || die "PLASMe_db.py failed"

log "PLASMe database ready at $OUTPUT_DIR."
log "Point PlasBench at it with: export PLASME_DB=$OUTPUT_DIR"
