#!/usr/bin/env bash
# One-time download of the Plassembler database (PLSDB mash sketch, ~500MB).
#
# Follows the same contract as the other database installers here: check first,
# do nothing when it is already present, and make re-downloading opt-in with
# --force. plassembler's own downloader has no skip-if-present.
#
# Usage:
#   bash env/download_plassembler_db.sh          # check; download only if missing
#   bash env/download_plassembler_db.sh --yes    # same, no prompt
#   bash env/download_plassembler_db.sh --force  # re-download over an existing copy
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0; FORCE=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -f|--force) FORCE=1 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $arg (usage: download_plassembler_db.sh [-y|--yes] [-f|--force])" ;;
    esac
done

have plassembler || die "plassembler not found; install it first: plasbench install-tools plassembler"

# Present means the files plassembler actually reads are there, not merely that
# the directory exists: an interrupted download leaves a partial tree, and a
# half-built database that looks installed is worse than one obviously missing.
database_present() {
    local dir="$1"
    [[ -n "$dir" && -d "$dir" ]] || return 1
    compgen -G "$dir/*.msh" > /dev/null 2>&1 || return 1
    return 0
}

if database_present "$PLASSEMBLER_DB"; then
    log "  [ok]   Plassembler DB already present at $PLASSEMBLER_DB"
    if [[ "$FORCE" -ne 1 ]]; then
        log "Nothing to do. Re-download and overwrite it with:"
        log "    bash env/download_plassembler_db.sh --force"
        exit 0
    fi
    warn "--force given: re-downloading over the existing database."
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        read -r -p "Overwrite the existing Plassembler database? [y/N] " REPLY || true
        case "$REPLY" in y|Y|yes|YES|Yes) : ;; *) log "Kept the existing database."; exit 0 ;; esac
    fi
else
    [[ -d "$PLASSEMBLER_DB" ]] && warn "Plassembler DB at $PLASSEMBLER_DB is incomplete; re-downloading."
    log "Plassembler's database (PLSDB sketch, ~500MB) will be downloaded to:"
    log "    $PLASSEMBLER_DB"
    echo
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        read -r -p "Download the Plassembler database now? [y/N] " REPLY || true
        case "$REPLY" in
            y|Y|yes|YES|Yes) : ;;
            *) log "Skipped. Re-run with --yes to skip this prompt."; exit 1 ;;
        esac
    fi
fi

mkdir -p "$PLASSEMBLER_DB"
log "Running plassembler download ..."
plassembler download -d "$PLASSEMBLER_DB" || die "plassembler download failed; check network access and see its output above"
database_present "$PLASSEMBLER_DB" || die "plassembler download reported success but $PLASSEMBLER_DB has no .msh sketch"
log "Plassembler database ready at $PLASSEMBLER_DB"
