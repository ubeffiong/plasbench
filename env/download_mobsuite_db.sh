#!/usr/bin/env bash
# One-time download of the MOB-suite reference database, needed by mob_recon
# and mob_typer.
#
# mob_init is NOT idempotent. It calls download_to_file() unconditionally on
# every invocation: there is no skip-if-present and no resume, so a re-run
# re-fetches the whole ~450MB archive from Zenodo and starts again from zero if
# the connection drops. On a slow or unreliable link that can mean it never
# completes. This script therefore does the presence check that mob_init does
# not, and only calls it when the database is genuinely absent.
#
# The database lives inside the installed mob_suite package. That path is not
# fixed across machines, but it is derivable -- ask Python where the package is.
#
# Usage:
#   bash env/download_mobsuite_db.sh           # check; download only if missing
#   bash env/download_mobsuite_db.sh --yes     # same, no prompt
#   bash env/download_mobsuite_db.sh --force   # re-download even if present
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -f|--force) FORCE=1 ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown argument: $arg (usage: download_mobsuite_db.sh [-y|--yes] [-f|--force])" ;;
    esac
done

have mob_init || die "mob_init not found; install MOB-suite first: plasbench install-tools reconstruction"

# Where does the installed mob_suite keep its databases?
mobsuite_db_dir() {
    python3 - <<'PYEOF' 2>/dev/null || true
import os
try:
    import mob_suite
except Exception:
    raise SystemExit(0)
print(os.path.join(os.path.dirname(os.path.abspath(mob_suite.__file__)), "databases"))
PYEOF
}

DB_DIR="$(mobsuite_db_dir)"

# A directory is only "present" if the files mob_recon actually reads are there.
# status.txt alone is not enough: an interrupted mob_init can leave a partial
# tree behind, and a half-built database that looks installed is worse than one
# that is obviously missing.
database_present() {
    local dir="$1"
    [[ -n "$dir" && -d "$dir" ]] || return 1
    local required=(
        "status.txt"
        "ncbi_plasmid_full_seqs.fas"
        "ncbi_plasmid_full_seqs.fas.msh"
        "repetitive.dna.fas"
    )
    local f
    for f in "${required[@]}"; do
        [[ -s "$dir/$f" ]] || return 1
    done
    return 0
}

if [[ -n "$DB_DIR" ]] && database_present "$DB_DIR"; then
    log "  [ok]   MOB-suite DB already present at $DB_DIR"
    if [[ "$FORCE" -ne 1 ]]; then
        log "Nothing to do. Re-download and overwrite it with:"
        log "    bash env/download_mobsuite_db.sh --force"
        exit 0
    fi
    warn "--force given: re-downloading over the existing database."
    warn "This discards the working copy and fetches ~450MB again with no resume."
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        read -r -p "Overwrite the existing MOB-suite database? [y/N] " REPLY || true
        case "$REPLY" in
            y|Y|yes|YES|Yes) : ;;
            *) log "Kept the existing database."; exit 0 ;;
        esac
    fi
else
    if [[ -n "$DB_DIR" && -d "$DB_DIR" ]]; then
        warn "MOB-suite DB at $DB_DIR is incomplete (an interrupted download leaves a partial tree)."
    fi
    log "MOB-suite's reference database (~450MB) will be fetched by 'mob_init' into"
    log "mob_suite's own package directory${DB_DIR:+: $DB_DIR}."
    log "Note: mob_init cannot resume. If the connection drops it restarts from zero."
    echo
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        read -r -p "Download the MOB-suite database now? [y/N] " REPLY || true
        case "$REPLY" in
            y|Y|yes|YES|Yes) : ;;
            *) log "Skipped. Re-run with --yes to skip this prompt, or run 'mob_init' directly later."; exit 1 ;;
        esac
    fi
fi

log "Running mob_init ..."
mob_init || die "mob_init failed; check network access and see its output above.
If your connection keeps dropping, a prebuilt database directory can be copied
into $DB_DIR instead -- every file in it is plain data with no absolute paths."
log "MOB-suite database ready."
