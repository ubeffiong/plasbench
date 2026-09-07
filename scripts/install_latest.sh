#!/usr/bin/env bash
# Download, checksum-verify, and install the latest published PlasBench release.
#
# Usage:
#   bash install_latest.sh          # latest code + conda environment
#   bash install_latest.sh --tools  # also install benchmark tools/databases
#   bash install_latest.sh --yes    # pass non-interactive consent to install.sh
set -euo pipefail

REPO="ubeffiong/plasbench"
WITH_TOOLS=0
ASSUME_YES=""
for arg in "$@"; do
    case "$arg" in
        --tools) WITH_TOOLS=1 ;;
        -y|--yes) ASSUME_YES="--yes" ;;
        -h|--help)
            sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required." >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "ERROR: sha256sum is required." >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "ERROR: tar is required." >&2; exit 1; }

say() { printf '[plasbench-latest] %s\n' "$*"; }
say "checking the latest GitHub release..."
release_json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")" || {
    echo "ERROR: could not reach GitHub's release API." >&2; exit 1;
}
tag="$(printf '%s' "$release_json" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
version="${tag#v}"
[[ -n "$tag" && "$version" != "$tag" ]] || { echo "ERROR: could not read the latest release version." >&2; exit 1; }

destination="${PLASBENCH_INSTALL_DIR:-$HOME}"
target="$destination/plasbench-$version"
[[ ! -e "$target" ]] || { echo "ERROR: $target already exists. Use ./update.sh there, or set PLASBENCH_INSTALL_DIR." >&2; exit 1; }
mkdir -p "$destination"
archive="$destination/plasbench-$version.tar.gz"
checksum="$archive.sha256"
url="https://github.com/$REPO/releases/download/$tag/plasbench-$version.tar.gz"

say "downloading PlasBench $version..."
curl -fL -o "$archive" "$url"
curl -fL -o "$checksum" "$url.sha256"
say "verifying the release checksum..."
(cd "$destination" && sha256sum -c "$(basename "$checksum")")
say "extracting to $target..."
tar -xzf "$archive" -C "$destination"

install_args=()
[[ "$WITH_TOOLS" -eq 1 ]] && install_args+=(--tools)
[[ -n "$ASSUME_YES" ]] && install_args+=("$ASSUME_YES")
say "starting the normal installer..."
(cd "$target" && ./install.sh "${install_args[@]}")
say "complete: $target"
say "next: cd $target && conda activate plasbench && plasbench --version"
