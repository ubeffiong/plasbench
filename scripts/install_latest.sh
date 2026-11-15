#!/usr/bin/env bash
# Download, checksum-verify, and install (or update) the latest published PlasBench release in ONE folder.
#
# Usage:
#   bash install_latest.sh          # latest code + conda environment, in ~/PlasBench
#   bash install_latest.sh --tools  # also install benchmark tools/databases
#   bash install_latest.sh --yes    # no questions: pass consent to install.sh, remove carried-over old folders
#   bash install_latest.sh --keep-old   # keep older plasbench-<version> folders after carrying them over
#
# PlasBench always lives in "$PLASBENCH_INSTALL_DIR/PlasBench" (default ~/PlasBench). Running this again updates it in
# place: only the files the previous release installed are replaced (scripts/release_sync.sh); your studies, settings
# (config/local.env), own tools, downloads, tool environments and databases are kept and reused. Older versioned
# installs (~/plasbench-0.x.y) found beside it are carried in: their runs move to PlasBench/studies/ and their
# settings are copied; then you are asked whether to delete the old folder.
set -euo pipefail

REPO="ubeffiong/plasbench"
WITH_TOOLS=0
ASSUME_YES=""
KEEP_OLD=0
for arg in "$@"; do
    case "$arg" in
        --tools) WITH_TOOLS=1 ;;
        -y|--yes) ASSUME_YES="--yes" ;;
        --keep-old) KEEP_OLD=1 ;;
        -h|--help)
            sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
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
target="$destination/PlasBench"
mkdir -p "$destination"
if [[ -f "$target/plasbench/__init__.py" ]]; then
    current="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$target/plasbench/__init__.py")"
    say "PlasBench ${current:-?} is installed in $target; updating it in place to $version"
fi
# The release archive is only an installation transport: download into a private temporary directory, removed on
# every exit path, so no stale archive is left looking like an installed version.
download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT
archive="$download_dir/plasbench-$version.tar.gz"
checksum="$archive.sha256"
url="https://github.com/$REPO/releases/download/$tag/plasbench-$version.tar.gz"

say "downloading PlasBench $version..."
curl -fL -o "$archive" "$url"
curl -fL -o "$checksum" "$url.sha256"
say "verifying the release checksum..."
(cd "$download_dir" && sha256sum -c "$(basename "$checksum")")
mkdir -p "$download_dir/stage"
tar -xzf "$archive" -C "$download_dir/stage"
release="$download_dir/stage/plasbench-$version"
[[ -f "$release/scripts/release_sync.sh" ]] || { echo "ERROR: the release has no scripts/release_sync.sh" >&2; exit 1; }

say "installing into $target..."
bash "$release/scripts/release_sync.sh" sync "$release" "$target" "$version"

# Older versioned installs beside it: carry their runs and settings in.
carried=()
for old in "$destination"/plasbench-[0-9]*/; do
    old="${old%/}"
    [[ -f "$old/plasbench/__init__.py" && ! -f "$old/MOVED_TO_PlasBench.txt" ]] || continue
    bash "$release/scripts/release_sync.sh" migrate "$old" "$target"
    carried+=("$old")
done

install_args=()
[[ "$WITH_TOOLS" -eq 1 ]] && install_args+=(--tools)
[[ -n "$ASSUME_YES" ]] && install_args+=("$ASSUME_YES")
say "starting the normal installer..."
(cd "$target" && ./install.sh "${install_args[@]}")

for old in "${carried[@]}"; do
    if [[ "$KEEP_OLD" -eq 1 ]]; then
        say "kept $old (--keep-old); its runs are now in $target/studies"
        continue
    fi
    if ! why="$(bash "$target/scripts/release_sync.sh" removable "$old")"; then
        say "kept $old: $why"
        continue
    fi
    reply=""
    if [[ -n "$ASSUME_YES" ]]; then
        reply="y"
    else
        printf '%s' "Delete the old folder $old? Its runs are in $target/studies and downloads are shared. [y/N] " >&2
        read -r reply || true
    fi
    case "$reply" in
        y|Y|yes|YES|Yes) rm -rf "$old"; say "removed $old" ;;
        *) say "kept $old (delete it yourself when you no longer need it)" ;;
    esac
done
say "complete: $target"
say "next: cd $target && conda activate plasbench && plasbench --version"
say "update later with: cd $target && ./update.sh   (or run this script again)"
