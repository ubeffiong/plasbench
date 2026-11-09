#!/usr/bin/env bash
# Keep every downloaded tool database once per machine, in $PLASBENCH_DB_DIR
# (default ~/.plasbench/databases), so new checkouts, new DATA_DIRs and rebuilt
# conda environments reuse them instead of downloading them again.
#
#   bash env/preserve_databases.sh                  # adopt databases under $DATA_DIR/db
#   bash env/preserve_databases.sh --from DIR ...   # also adopt from other data/db folders
#   bash env/preserve_databases.sh --list           # show what the store holds
#
# A database found at an old location is MOVED into the store (a rename on the
# same disk) and a symbolic link is left where it was, so anything pointing at the
# old path keeps working. If the store already has that database, the old copy is
# left untouched and reported as a duplicate you may remove yourself. MOB-suite's
# database, which lives inside its conda environment, is moved to the store and the
# environment's folder linked to it. Nothing is ever deleted by this script.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/../scripts/lib.sh"

# Database locations relative to a data/db folder (and to the store).
DATABASES=(platon/db genomad plasme plassembler plasmer plascope/ecoli/chromosome_plasmid_db
           plascope/klebsiella/Klebsiella_PlaScope bakta plsdb plasmid_reference)

SOURCES=("$DATA_DIR/db")
LIST_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) SOURCES+=("$2"); shift 2 ;;
        --list) LIST_ONLY=1; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) die "unknown argument: $1 (usage: preserve_databases.sh [--from DIR]... [--list])" ;;
    esac
done

mkdir -p "$PLASBENCH_DB_DIR"
if [[ "$LIST_ONLY" -eq 1 ]]; then
    log "database store: $PLASBENCH_DB_DIR"
    for rel in "${DATABASES[@]}" mob_suite/databases; do
        [[ -e "$PLASBENCH_DB_DIR/$rel" ]] && log "  [kept] $rel ($(du -sh "$PLASBENCH_DB_DIR/$rel" 2>/dev/null | cut -f1))"
    done
    exit 0
fi

adopted=0
for src_root in "${SOURCES[@]}"; do
    [[ -d "$src_root" ]] || { warn "not a folder: $src_root"; continue; }
    src_root="$(cd "$src_root" && pwd)"
    for rel in "${DATABASES[@]}"; do
        src="$src_root/$rel"; dst="$PLASBENCH_DB_DIR/$rel"
        [[ -e "$src" && ! -L "$src" ]] || continue
        if [[ -z "$(ls -A "$src" 2>/dev/null)" && -d "$src" ]]; then
            continue  # an empty folder is not a database
        fi
        if [[ -e "$dst" ]]; then
            log "  [dup]  $src (the store already has $rel; this copy was left in place)"
            continue
        fi
        mkdir -p "$(dirname "$dst")"
        mv "$src" "$dst"
        ln -s "$dst" "$src"
        log "  [kept] $rel <- $src (a link now stands at the old path)"
        adopted=$((adopted + 1))
    done
done

# MOB-suite keeps its database inside the environment that runs it.
if command -v mob_recon >/dev/null 2>&1; then
    mobsuite_db_preserve
fi

log "database store: $PLASBENCH_DB_DIR ($adopted database(s) adopted this run)"
log "every config default now points there; set PLASBENCH_DB_DIR to move the store."
