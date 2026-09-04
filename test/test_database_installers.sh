#!/usr/bin/env bash
# Regression for env/download_mobsuite_db.sh and env/download_bakta_db.sh:
# each must detect a missing tool binary and refuse cleanly, ask before
# downloading (unless --yes), never re-download when already present, and
# actually invoke the right underlying command with the right arguments.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- MOB-suite ---
mkdir -p "$TMP/bin_mob"
cat > "$TMP/bin_mob/mob_init" <<EOF
#!/usr/bin/env bash
echo "mob_init ran" >> "$TMP/mob_calls.log"
EOF
chmod +x "$TMP/bin_mob/mob_init"

if PATH="/usr/bin:/bin" bash "$ROOT/env/download_mobsuite_db.sh" --yes 2>"$TMP/err.log"; then
    echo "FAIL: missing mob_init should be refused" >&2; exit 1
fi
grep -qi "mob_init not found" "$TMP/err.log" || { echo "FAIL: expected a clear mob_init-missing error" >&2; cat "$TMP/err.log" >&2; exit 1; }
echo "download_mobsuite_db.sh refuses cleanly when mob_init is missing -> PASS"

: > "$TMP/mob_calls.log"
PATH="$TMP/bin_mob:$PATH" bash "$ROOT/env/download_mobsuite_db.sh" --yes
[[ -s "$TMP/mob_calls.log" ]] || { echo "FAIL: --yes should have run mob_init" >&2; exit 1; }
echo "download_mobsuite_db.sh --yes actually runs mob_init -> PASS"

: > "$TMP/mob_calls.log"
if PATH="$TMP/bin_mob:$PATH" bash "$ROOT/env/download_mobsuite_db.sh" < /dev/null; then
    echo "FAIL: declining should exit non-zero" >&2; exit 1
fi
[[ ! -s "$TMP/mob_calls.log" ]] || { echo "FAIL: declining must not run mob_init" >&2; exit 1; }
echo "download_mobsuite_db.sh declines cleanly without running mob_init -> PASS"

# --- Bakta ---
mkdir -p "$TMP/bin_bakta" "$TMP/data"
cat > "$TMP/bin_bakta/bakta_db" <<EOF
#!/usr/bin/env bash
echo "bakta_db \$*" >> "$TMP/bakta_calls.log"
out="" type=""
while [[ \$# -gt 0 ]]; do case "\$1" in --output) out="\$2"; shift 2;; --type) type="\$2"; shift 2;; *) shift;; esac; done
dir="\$out/db"; [[ "\$type" == light ]] && dir="\$out/db-light"
mkdir -p "\$dir"
printf '{"major":6,"minor":0}' > "\$dir/version.json"
EOF
chmod +x "$TMP/bin_bakta/bakta_db"

if PATH="/usr/bin:/bin" bash "$ROOT/env/download_bakta_db.sh" --yes 2>"$TMP/err.log"; then
    echo "FAIL: missing bakta_db should be refused" >&2; exit 1
fi
grep -qi "bakta_db not found" "$TMP/err.log" || { echo "FAIL: expected a clear bakta_db-missing error" >&2; cat "$TMP/err.log" >&2; exit 1; }
echo "download_bakta_db.sh refuses cleanly when bakta_db is missing -> PASS"

: > "$TMP/bakta_calls.log"
DATA_DIR="$TMP/data" PATH="$TMP/bin_bakta:$PATH" bash "$ROOT/env/download_bakta_db.sh" --yes
grep -q -- "--type light" "$TMP/bakta_calls.log" || { echo "FAIL: expected the default 'light' database type" >&2; cat "$TMP/bakta_calls.log" >&2; exit 1; }
[[ -s "$TMP/data/db/bakta/db-light/version.json" ]] || { echo "FAIL: expected a populated db-light directory" >&2; exit 1; }
echo "download_bakta_db.sh --yes defaults to the light database -> PASS"

: > "$TMP/bakta_calls.log"
DATA_DIR="$TMP/data" PATH="$TMP/bin_bakta:$PATH" bash "$ROOT/env/download_bakta_db.sh" --yes
[[ ! -s "$TMP/bakta_calls.log" ]] || { echo "FAIL: an already-present database must not be re-downloaded" >&2; cat "$TMP/bakta_calls.log" >&2; exit 1; }
echo "download_bakta_db.sh does not re-download an already-present database -> PASS"

: > "$TMP/bakta_calls.log"
DATA_DIR="$TMP/data" PATH="$TMP/bin_bakta:$PATH" bash "$ROOT/env/download_bakta_db.sh" --yes --full --output "$TMP/data/custom"
grep -q -- "--type full" "$TMP/bakta_calls.log" || { echo "FAIL: --full should request the full database type" >&2; cat "$TMP/bakta_calls.log" >&2; exit 1; }
[[ -s "$TMP/data/custom/db/version.json" ]] || { echo "FAIL: --output should control the destination directory" >&2; exit 1; }
echo "download_bakta_db.sh --full and --output are honored -> PASS"

echo "ALL DATABASE INSTALLER TESTS PASSED"
