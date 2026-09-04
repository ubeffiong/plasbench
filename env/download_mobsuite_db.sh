#!/usr/bin/env bash
# One-time download of the MOB-suite reference database, needed by mob_recon
# and mob_typer. Unlike Platon's database (a Zenodo archive whose URL rotates
# on every release, so it cannot be fetched from a fixed link), mob_init
# fetches MOB-suite's database from a location baked into the mob_suite
# package itself, so this step can be fully automatic once mob_suite is
# installed: no URL for the user to go find. mob_init is also idempotent --
# safe to run again if the database is already present, since it checks
# first and skips re-downloading -- so this script does not try to detect
# "already there" itself.
#
# Usage:
#   bash env/download_mobsuite_db.sh          # asks first
#   bash env/download_mobsuite_db.sh --yes    # no prompt
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
[[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]] && ASSUME_YES=1

have mob_init || die "mob_init not found; install MOB-suite first: plasbench install-tools reconstruction"

log "MOB-suite's reference database is fetched by 'mob_init' (~1 GB) into"
log "mob_suite's own package directory. This is safe to re-run: mob_init"
log "checks first and skips re-downloading if it is already present."
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    REPLY=""
    read -r -p "Download/verify the MOB-suite database now? [y/N] " REPLY || true
    case "$REPLY" in
        y|Y|yes|YES|Yes) : ;;
        *) log "Skipped. Re-run with --yes to skip this prompt, or run 'mob_init' directly later."; exit 1 ;;
    esac
fi

log "Running mob_init ..."
mob_init || die "mob_init failed; check network access and see its output above"
log "MOB-suite database ready."
