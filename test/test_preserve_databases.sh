#!/usr/bin/env bash
# Tool databases are kept once per machine ($PLASBENCH_DB_DIR):
#   * config defaults point at the store; a database still at the old
#     $DATA_DIR/db location is used until the store has it;
#   * env/preserve_databases.sh moves it into the store and leaves a link, so the
#     old path keeps working; a second run changes nothing; nothing is deleted;
#   * MOB-suite's in-environment database moves to the store and the environment
#     folder becomes a link; a rebuilt (empty) environment is linked again rather
#     than needing a new download.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export DATA_DIR="$TMP/data" PLASBENCH_DB_DIR="$TMP/store" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp"
export SAMPLE_SHEET="$TMP/sheet.tsv"; : > "$SAMPLE_SHEET"

cfg() { bash -c "source '$ROOT/config/config.sh' >/dev/null 2>&1; printf '%s' \"\$$1\""; }

[[ "$(cfg PLATON_DB)" == "$TMP/store/platon/db" ]] || { echo "FAIL: PLATON_DB default is not the store: $(cfg PLATON_DB)" >&2; exit 1; }
mkdir -p "$DATA_DIR/db/platon/db" "$DATA_DIR/db/genomad"
echo data > "$DATA_DIR/db/platon/db/refs.fna"; echo data > "$DATA_DIR/db/genomad/genomad_db"
[[ "$(cfg PLATON_DB)" == "$DATA_DIR/db/platon/db" ]] || { echo "FAIL: an existing old-location database was not used" >&2; exit 1; }
echo "defaults point at the machine store; an old-location database is still used -> PASS"

# MOB-suite: a wrapper pointing at a separate environment that holds the database.
MOBENV="$TMP/mobenv"; DBD="$MOBENV/lib/python3.10/site-packages/mob_suite/databases"
mkdir -p "$TMP/bin" "$MOBENV/bin" "$DBD"
for f in status.txt ncbi_plasmid_full_seqs.fas ncbi_plasmid_full_seqs.fas.msh repetitive.dna.fas; do echo x > "$DBD/$f"; done
printf '#!/bin/sh\necho mob_recon 3.1.9\n' > "$MOBENV/bin/mob_recon"; chmod +x "$MOBENV/bin/mob_recon"
printf '#!/bin/sh\nexec "%s/bin/mob_recon" "$@"\n' "$MOBENV" > "$TMP/bin/mob_recon"; chmod +x "$TMP/bin/mob_recon"

PATH="$TMP/bin:$PATH" bash "$ROOT/env/preserve_databases.sh" > "$TMP/run1.log" 2>&1 || { cat "$TMP/run1.log" >&2; exit 1; }
[[ -f "$TMP/store/platon/db/refs.fna" && -L "$DATA_DIR/db/platon/db" ]] || { echo "FAIL: platon not moved+linked" >&2; cat "$TMP/run1.log" >&2; exit 1; }
[[ -f "$DATA_DIR/db/platon/db/refs.fna" ]] || { echo "FAIL: the old path no longer reaches the database" >&2; exit 1; }
[[ "$(cfg PLATON_DB)" == "$TMP/store/platon/db" ]] || { echo "FAIL: PLATON_DB does not use the store after adoption" >&2; exit 1; }
[[ -L "$DBD" && -s "$TMP/store/mob_suite/databases/status.txt" ]] || { echo "FAIL: MOB-suite database not moved to the store" >&2; cat "$TMP/run1.log" >&2; exit 1; }
echo "databases moved into the store with links at the old paths; MOB-suite's env folder is a link -> PASS"

PATH="$TMP/bin:$PATH" bash "$ROOT/env/preserve_databases.sh" > "$TMP/run2.log" 2>&1
grep -q "(0 database(s) adopted this run)" "$TMP/run2.log" || { echo "FAIL: second run changed something" >&2; cat "$TMP/run2.log" >&2; exit 1; }
echo "a second run changes nothing -> PASS"

# A rebuilt MOB-suite environment: the database folder is fresh and empty.
mv "$DBD" "$TMP/old-link"; mkdir -p "$DBD"; echo "" > "$DBD/__init__.py"
PATH="$TMP/bin:$PATH" bash -c "source '$ROOT/config/config.sh' >/dev/null 2>&1; source '$ROOT/scripts/lib.sh'; mobsuite_db_preserve" > "$TMP/run3.log" 2>&1
[[ -L "$DBD" && -s "$DBD/status.txt" ]] || { echo "FAIL: rebuilt environment not linked to the stored database" >&2; cat "$TMP/run3.log" >&2; exit 1; }
ls -d "$MOBENV"/lib/python3.10/site-packages/mob_suite/databases.pre-store.* >/dev/null || { echo "FAIL: the fresh folder was not kept aside" >&2; exit 1; }
echo "a rebuilt MOB-suite environment is linked to the stored database, nothing deleted -> PASS"

# A copy elsewhere when the store already has it: left in place, reported.
mkdir -p "$TMP/old/db/platon/db"; echo other > "$TMP/old/db/platon/db/refs.fna"
PATH="$TMP/bin:$PATH" bash "$ROOT/env/preserve_databases.sh" --from "$TMP/old/db" > "$TMP/run4.log" 2>&1
grep -q "\[dup\]" "$TMP/run4.log" && [[ -f "$TMP/old/db/platon/db/refs.fna" && ! -L "$TMP/old/db/platon/db" ]] \
    || { echo "FAIL: a duplicate copy should be left in place and reported" >&2; cat "$TMP/run4.log" >&2; exit 1; }
echo "a duplicate copy elsewhere is reported, never deleted -> PASS"
echo "ALL PRESERVE-DATABASES TESTS PASSED"
