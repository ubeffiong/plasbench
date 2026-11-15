#!/usr/bin/env bash
# One-time download of the MOB-suite reference database, needed by mob_recon
# and mob_typer.
#
# mob_init is NOT idempotent. It calls download_to_file() unconditionally on
# every invocation: there is no skip-if-present and no resume, so a re-run
# re-fetches the whole ~450MB archive from Zenodo and starts again from zero if
# the connection drops. This script therefore (1) does the presence check that
# mob_init does not, and (2) downloads the archive itself with
# scripts/lib.sh resumable_download -- kept across attempts, paused while the
# internet is down -- and hands mob_init the finished file as a file:// mirror,
# so mob_init only unpacks and builds.
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
source "$HERE/../config/config.sh"
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
# scripts/lib.sh's mobsuite_db_dir (sourced above) follows the mob_recon wrapper
# to MOB-suite's own environment, so the database checked here is the one the
# running tool reads, not an unused copy importable from this interpreter.

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

# A database kept in the machine store is linked in instead of downloaded again.
if [[ "$FORCE" -ne 1 ]]; then
    mobsuite_db_preserve
    DB_DIR="$(mobsuite_db_dir)"
fi
if [[ -n "$DB_DIR" ]] && database_present "$DB_DIR"; then
    log "  [ok]   MOB-suite DB already present at $DB_DIR"
    if [[ "$FORCE" -ne 1 ]]; then
        log "Nothing to do. Re-download and overwrite it with:"
        log "    bash env/download_mobsuite_db.sh --force"
        exit 0
    fi
    warn "--force given: re-downloading over the existing database."
    warn "This discards the working copy and fetches ~450MB again (the download resumes if interrupted)."
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        printf '%s' "Overwrite the existing MOB-suite database? [y/N] " >&2; read -r REPLY || true
        case "$REPLY" in
            y|Y|yes|YES|Yes) : ;;
            *) log "Kept the existing database."; exit 0 ;;
        esac
    fi
else
    if [[ -n "$DB_DIR" && -d "$DB_DIR" ]]; then
        warn "MOB-suite DB at $DB_DIR is incomplete (an interrupted download leaves a partial tree)."
    fi
    log "MOB-suite's reference database (~450MB) will be downloaded and built into"
    log "mob_suite's own package directory${DB_DIR:+: $DB_DIR}."
    log "The download resumes: if the connection drops or you stop it, running this again"
    log "continues from where it stopped. While the internet is down it waits rather than failing."
    echo
    if [[ "$ASSUME_YES" -ne 1 ]]; then
        REPLY=""
        printf '%s' "Download the MOB-suite database now? [y/N] " >&2; read -r REPLY || true
        case "$REPLY" in
            y|Y|yes|YES|Yes) : ;;
            *) log "Skipped. Re-run with --yes to skip this prompt, or run 'mob_init' directly later."; exit 1 ;;
        esac
    fi
fi

# mob_init cannot resume: it opens data.tar.gz for writing on every attempt. So
# PlasBench downloads the archive itself, resumably, into the machine store
# (kept across attempts and re-runs), and then hands mob_init the finished file
# as a file:// mirror. mob_init then only unpacks and builds, as it normally does.
MOB_ROOT="$(mobsuite_env_root)"
MOB_PY="${MOB_ROOT:+$MOB_ROOT/bin/python}"
STAGE="${PLASBENCH_DB_DIR:-$HOME/.plasbench/databases}/mob_suite/download"
ARCHIVE="$STAGE/data.tar.gz"
if [[ -n "$MOB_PY" && -x "$MOB_PY" ]]; then
    MIRROR="$("$MOB_PY" -c 'import json, os, mob_suite.mob_init as m; print(m.config["db_mirrors"][0])' 2>/dev/null || true)"
    MIRROR="${MIRROR:-https://zenodo.org/records/10304948/files/data.tar.gz?download=1}"
    log "Downloading the MOB-suite archive (resumable) to $ARCHIVE"
    resumable_download "$MIRROR" "$ARCHIVE" \
        || die "the MOB-suite download did not finish; run 'bash env/download_mobsuite_db.sh --yes' again to continue it"
    log "Building the MOB-suite database from the downloaded archive (a status line appears every minute after 3 quiet minutes) ..."
    run_with_heartbeat "MOB-suite database index build" env PATH="$MOB_ROOT/bin:$PATH" PLASBENCH_MOB_ARCHIVE="$ARCHIVE" \
        "$MOB_PY" -c '
import os, sys
import mob_suite.mob_init as m
m.config["db_mirrors"] = ["file://" + os.environ["PLASBENCH_MOB_ARCHIVE"]]
sys.argv = ["mob_init"]
sys.exit(m.main())
' || die "building the MOB-suite database failed; see its output above. The downloaded archive is kept at $ARCHIVE, so a re-run does not download it again."
    rm -f "$ARCHIVE"
else
    # MOB-suite's environment could not be located: fall back to mob_init's own (non-resumable) download.
    warn "could not locate MOB-suite's Python; using mob_init's own download, which cannot resume"
    run_with_heartbeat "MOB-suite database download/index build" mob_init || die "mob_init failed; check network access and see its output above.
If your connection keeps dropping, a prebuilt database directory can be copied
into $DB_DIR instead -- every file in it is plain data with no absolute paths."
fi
mobsuite_db_preserve
log "MOB-suite database ready (kept in ${PLASBENCH_DB_DIR:-$HOME/.plasbench/databases}/mob_suite)."
