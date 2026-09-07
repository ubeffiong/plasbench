#!/usr/bin/env bash
# Regression for update.sh: must detect "already up to date" without any
# network call beyond the version check, must download/verify/unpack a newer
# release into a sibling directory, must migrate data/db and any
# .ncbi.env/config/local.tsv the user added, must never overwrite an
# existing destination directory, and must actually invoke the new version's
# own install.sh. Fakes `curl` (GitHub API + release asset downloads) so this
# runs fully offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null || true; rm -rf "$TMP"' EXIT

# --- a minimal fake install directory, mirroring a real release's layout ---
make_install_dir() {
    local dir="$1" version="$2"
    mkdir -p "$dir/plasbench" "$dir/config"
    printf '__version__ = "%s"\n' "$version" > "$dir/plasbench/__init__.py"
    cp "$ROOT/update.sh" "$dir/update.sh"
    chmod +x "$dir/update.sh"
}

# --- already up to date: no download, no new directory, exit 0 ---
OLD="$TMP/plasbench-0.2.1"
make_install_dir "$OLD" "0.2.1"
mkdir -p "$TMP/bin_uptodate"
cat > "$TMP/bin_uptodate/curl" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do
    if [[ "\$a" == *"/releases/latest" ]]; then
        echo '{"tag_name": "v0.2.1"}'
        exit 0
    fi
done
echo "FAKE CURL: unexpected call: \$*" >&2
exit 1
EOF
chmod +x "$TMP/bin_uptodate/curl"
out="$(PATH="$TMP/bin_uptodate:$PATH" bash "$OLD/update.sh" 2>&1)"
echo "$out" | grep -q "already up to date" || { echo "FAIL: expected an already-up-to-date message" >&2; echo "$out" >&2; exit 1; }
[[ ! -d "$TMP/plasbench-0.2.1-new" ]]
echo "already on the latest version -> no download, clean exit -> PASS"

# --- a real upgrade: new version downloaded, verified, unpacked; databases
# and user config migrated; the new version's own install.sh is invoked. ---
OLD2="$TMP/plasbench-0.1.0"
make_install_dir "$OLD2" "0.1.0"
mkdir -p "$OLD2/data/db/platon/db"
echo "fake platon db file" > "$OLD2/data/db/platon/db/marker"
echo "NCBI_API_KEY=secret123" > "$OLD2/.ncbi.env"
printf 'sample_id\tassembly_accession\ns1\tGCF_1\n' > "$OLD2/config/local.tsv"

# The fake release tarball: a real tar.gz whose top-level dir IS the new
# version, containing a stand-in install.sh that just logs its own
# invocation instead of touching a real conda environment.
STAGE="$TMP/stage/plasbench-0.2.0"
mkdir -p "$STAGE"
printf '__version__ = "0.2.0"\n' > /dev/null  # placeholder, real file below
mkdir -p "$STAGE/plasbench"
printf '__version__ = "0.2.0"\n' > "$STAGE/plasbench/__init__.py"
cat > "$STAGE/install.sh" <<EOF
#!/usr/bin/env bash
echo "install.sh invoked with: \$*" >> "$TMP/install_invocations.log"
EOF
chmod +x "$STAGE/install.sh"
( cd "$TMP/stage" && tar -czf "$TMP/plasbench-0.2.0.tar.gz" plasbench-0.2.0 )
sha256sum "$TMP/plasbench-0.2.0.tar.gz" | awk '{print $1"  plasbench-0.2.0.tar.gz"}' > "$TMP/plasbench-0.2.0.tar.gz.sha256"

mkdir -p "$TMP/bin_upgrade"
cat > "$TMP/bin_upgrade/curl" <<EOF
#!/usr/bin/env bash
dest="" url=""
args=("\$@")
for ((i=0; i<\${#args[@]}; i++)); do
    case "\${args[i]}" in
        -o) dest="\${args[i+1]}" ;;
        http*) url="\${args[i]}" ;;
    esac
done
if [[ "\$url" == *"/releases/latest" ]]; then
    echo '{"tag_name": "v0.2.0"}'
elif [[ "\$url" == *.sha256 ]]; then
    cp "$TMP/plasbench-0.2.0.tar.gz.sha256" "\$dest"
elif [[ "\$url" == *.tar.gz ]]; then
    cp "$TMP/plasbench-0.2.0.tar.gz" "\$dest"
else
    echo "FAKE CURL: unexpected URL: \$url" >&2
    exit 1
fi
EOF
chmod +x "$TMP/bin_upgrade/curl"

: > "$TMP/install_invocations.log"
PATH="$TMP/bin_upgrade:$PATH" bash "$OLD2/update.sh" --yes > "$TMP/update.log" 2>&1 \
    || { echo "FAIL: upgrade run should succeed" >&2; cat "$TMP/update.log" >&2; exit 1; }

NEW2="$TMP/plasbench-0.2.0"
[[ -d "$NEW2" ]] || { echo "FAIL: new version directory was not created" >&2; cat "$TMP/update.log" >&2; exit 1; }
[[ -f "$NEW2/data/db/platon/db/marker" ]] || { echo "FAIL: data/db was not migrated" >&2; exit 1; }
[[ -f "$NEW2/.ncbi.env" ]] || { echo "FAIL: .ncbi.env was not migrated" >&2; exit 1; }
[[ -f "$NEW2/config/local.tsv" ]] || { echo "FAIL: config/local.tsv was not migrated" >&2; exit 1; }
grep -q -- "--yes" "$TMP/install_invocations.log" || { echo "FAIL: the new install.sh was not invoked with --yes" >&2; cat "$TMP/install_invocations.log" >&2; exit 1; }
echo "a real upgrade downloads, verifies, unpacks, and migrates databases/config -> PASS"

# --- an existing destination directory is never overwritten ---
OLD3="$TMP/plasbench-0.1.1"
make_install_dir "$OLD3" "0.1.1"
mkdir -p "$TMP/plasbench-0.2.0/pretend-i-was-already-here"
if PATH="$TMP/bin_upgrade:$PATH" bash "$OLD3/update.sh" > "$TMP/update2.log" 2>&1; then
    echo "FAIL: update.sh must refuse to overwrite an existing destination directory" >&2
    cat "$TMP/update2.log" >&2; exit 1
fi
grep -qi "already exists" "$TMP/update2.log" || { echo "FAIL: expected an 'already exists' error" >&2; cat "$TMP/update2.log" >&2; exit 1; }
[[ -d "$TMP/plasbench-0.2.0/pretend-i-was-already-here" ]] || { echo "FAIL: existing destination contents were removed" >&2; exit 1; }
echo "an existing destination directory is never overwritten -> PASS"

echo "ALL UPDATE SCRIPT TESTS PASSED"
