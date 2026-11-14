#!/usr/bin/env bash
# The first-install helper must verify a release, install it into the one PlasBench folder, then discard its
# transport archive. Regression-test it entirely offline with a fake GitHub endpoint.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/release/plasbench-9.9.9/scripts" "$TMP/bin" "$TMP/install"
cat > "$TMP/release/plasbench-9.9.9/install.sh" <<EOF
#!/usr/bin/env bash
echo "install called: \$*" > "$TMP/install/called"
EOF
chmod +x "$TMP/release/plasbench-9.9.9/install.sh"
# a release carries scripts/release_sync.sh, which installs it into PlasBench/ (and updates it in place later)
cp "$ROOT/scripts/release_sync.sh" "$TMP/release/plasbench-9.9.9/scripts/"
tar -czf "$TMP/release/plasbench-9.9.9.tar.gz" -C "$TMP/release" plasbench-9.9.9
(cd "$TMP/release" && sha256sum plasbench-9.9.9.tar.gz > plasbench-9.9.9.tar.gz.sha256)

cat > "$TMP/bin/curl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
dest=""
while [[ \$# -gt 0 ]]; do
    case "\$1" in
        -o) dest="\$2"; shift 2 ;;
        -*) shift ;;
        *) url="\$1"; shift ;;
    esac
done
if [[ -z "\$dest" ]]; then
    printf '{"tag_name":"v9.9.9"}\n'
elif [[ "\$url" == *.sha256 ]]; then
    cp "$TMP/release/plasbench-9.9.9.tar.gz.sha256" "\$dest"
else
    cp "$TMP/release/plasbench-9.9.9.tar.gz" "\$dest"
fi
EOF
chmod +x "$TMP/bin/curl"

if ! PATH="$TMP/bin:/usr/bin:/bin" PLASBENCH_INSTALL_DIR="$TMP/install" \
    bash "$ROOT/scripts/install_latest.sh" --tools --yes > "$TMP/out" 2>&1; then
    echo "FAIL: install_latest.sh exited non-zero" >&2; cat "$TMP/out" >&2; exit 1
fi

[[ -f "$TMP/install/PlasBench/install.sh" ]] || { echo "FAIL: the release was not installed into PlasBench/" >&2; cat "$TMP/out" >&2; exit 1; }
[[ -f "$TMP/install/called" ]] || { echo "FAIL: installer was not called" >&2; cat "$TMP/out" >&2; exit 1; }
grep -q -- '--tools --yes' "$TMP/install/called" || { echo "FAIL: install options were not forwarded" >&2; cat "$TMP/install/called" >&2; exit 1; }
for left in "$TMP/install/plasbench-9.9.9.tar.gz" "$TMP/install/plasbench-9.9.9.tar.gz.sha256" "$TMP/install/PlasBench/plasbench-9.9.9.tar.gz"; do
    [[ ! -e "$left" ]] || { echo "FAIL: release transport archive was retained: $left" >&2; exit 1; }
done
echo "install_latest verifies, installs into PlasBench/, forwards options, and cleans its transport archive -> PASS"
echo "ALL INSTALL-LATEST TESTS PASSED"
