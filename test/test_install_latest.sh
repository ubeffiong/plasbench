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
# --- no network: the failure says why (DNS) and names the offline route, and never leaves an install behind ---
mkdir -p "$TMP/dnsbin"
printf '#!/usr/bin/env bash\nexit 6\n' > "$TMP/dnsbin/curl"
chmod +x "$TMP/dnsbin/curl"
if PATH="$TMP/dnsbin:/usr/bin:/bin" PLASBENCH_INSTALL_DIR="$TMP/install_dns" bash "$ROOT/scripts/install_latest.sh" --tools > "$TMP/out_dns" 2>&1; then
    echo "FAIL: a DNS failure must exit non-zero" >&2; exit 1
fi
grep -q "could not be resolved" "$TMP/out_dns" || { echo "FAIL: a DNS failure was not explained" >&2; cat "$TMP/out_dns" >&2; exit 1; }
grep -q -- "--archive" "$TMP/out_dns" || { echo "FAIL: the offline route was not named" >&2; cat "$TMP/out_dns" >&2; exit 1; }
[[ ! -e "$TMP/install_dns/PlasBench" ]] || { echo "FAIL: a failed download left an install" >&2; exit 1; }
echo "a DNS failure is explained and names the offline --archive route -> PASS"

# --- --archive installs a release file already on disk, with no network at all ---
mkdir -p "$TMP/offline"
cp "$TMP/release/plasbench-9.9.9.tar.gz" "$TMP/release/plasbench-9.9.9.tar.gz.sha256" "$TMP/offline/"
if ! PATH="$TMP/dnsbin:/usr/bin:/bin" PLASBENCH_INSTALL_DIR="$TMP/install_off" \
    bash "$ROOT/scripts/install_latest.sh" --archive "$TMP/offline/plasbench-9.9.9.tar.gz" --yes > "$TMP/out_off" 2>&1; then
    echo "FAIL: --archive install failed" >&2; cat "$TMP/out_off" >&2; exit 1
fi
[[ -f "$TMP/install_off/PlasBench/install.sh" ]] || { echo "FAIL: --archive did not install" >&2; cat "$TMP/out_off" >&2; exit 1; }
echo "--archive installs from a downloaded release with no network -> PASS"

# --- a tampered archive is refused ---
printf 'tampered' >> "$TMP/offline/plasbench-9.9.9.tar.gz"
if PATH="$TMP/dnsbin:/usr/bin:/bin" PLASBENCH_INSTALL_DIR="$TMP/install_bad" \
    bash "$ROOT/scripts/install_latest.sh" --archive "$TMP/offline/plasbench-9.9.9.tar.gz" --yes > "$TMP/out_bad" 2>&1; then
    echo "FAIL: an archive that fails its checksum was installed" >&2; exit 1
fi
[[ ! -e "$TMP/install_bad/PlasBench" ]] || { echo "FAIL: a bad archive left an install" >&2; exit 1; }
echo "an --archive that fails its checksum is refused -> PASS"
echo "ALL INSTALL-LATEST TESTS PASSED"
