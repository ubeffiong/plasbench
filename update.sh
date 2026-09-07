#!/usr/bin/env bash
# One command to upgrade an existing PlasBench install to the latest release.
#
# Run this from INSIDE your current install directory (the one containing
# this file, e.g. ~/plasbench-0.1.9):
#
#   ./update.sh
#
# It finds the latest release, downloads and verifies it, migrates your
# existing databases (Platon, and anything else under data/db/) and any
# config/local.tsv or .ncbi.env you added, into a new sibling directory
# (e.g. ~/plasbench-0.2.1), then runs that new version's own installer --
# which updates the shared 'plasbench' conda environment in place rather
# than recreating it (see env/setup_conda.sh). Nothing in the current
# directory is deleted; it is left exactly as it is.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

REPO="ubeffiong/plasbench"
ASSUME_YES=""
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES="--yes" ;;
        -h|--help)
            sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say() { printf '[plasbench-update] %s\n' "$*"; }

CURRENT_VERSION="$(python3 -c "import re; print(re.search(r'__version__ = \"([^\"]+)\"', open('plasbench/__init__.py').read()).group(1))" 2>/dev/null || echo unknown)"
say "current version: $CURRENT_VERSION"

say "checking the latest release on GitHub..."
LATEST_JSON="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")" || {
    echo "ERROR: could not reach GitHub's API. Check your network and try again," >&2
    echo "or find the latest version yourself at: https://github.com/$REPO/releases" >&2
    exit 1
}
LATEST_TAG="$(printf '%s' "$LATEST_JSON" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
LATEST_VERSION="${LATEST_TAG#v}"
if [[ -z "$LATEST_VERSION" ]]; then
    echo "ERROR: could not parse the latest version from GitHub's response." >&2
    exit 1
fi
say "latest version: $LATEST_VERSION"

if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" ]]; then
    say "already up to date -- nothing to do."
    exit 0
fi

PARENT_DIR="$(dirname "$HERE")"
NEW_DIR="$PARENT_DIR/plasbench-$LATEST_VERSION"
if [[ -e "$NEW_DIR" ]]; then
    echo "ERROR: $NEW_DIR already exists. Remove it, or move it aside, and re-run." >&2
    exit 1
fi

TARBALL="plasbench-$LATEST_VERSION.tar.gz"
DOWNLOAD_DIR="$(mktemp -d)"
trap 'rm -rf "$DOWNLOAD_DIR"' EXIT

say "downloading $TARBALL ..."
curl -fL -o "$DOWNLOAD_DIR/$TARBALL" \
    "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL"
curl -fL -o "$DOWNLOAD_DIR/$TARBALL.sha256" \
    "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL.sha256"
say "verifying checksum..."
( cd "$DOWNLOAD_DIR" && sha256sum -c "$TARBALL.sha256" )

say "unpacking to $NEW_DIR ..."
mkdir -p "$PARENT_DIR"
tar -xzf "$DOWNLOAD_DIR/$TARBALL" -C "$PARENT_DIR"

# Migrate large, slow-to-redownload databases and anything you added yourself
# -- never anything the release itself ships, so a stale copy can never mask
# a real update to a shipped file.
if [[ -d "$HERE/data/db" ]]; then
    say "copying data/db/ (Platon and friends) from the current install..."
    mkdir -p "$NEW_DIR/data"
    cp -r "$HERE/data/db" "$NEW_DIR/data/"
fi
for extra in .ncbi.env config/local.tsv; do
    if [[ -f "$HERE/$extra" && ! -f "$NEW_DIR/$extra" ]]; then
        say "copying $extra from the current install..."
        mkdir -p "$(dirname "$NEW_DIR/$extra")"
        cp "$HERE/$extra" "$NEW_DIR/$extra"
    fi
done

say "installing $LATEST_VERSION (this updates the shared 'plasbench' conda environment in place)..."
( cd "$NEW_DIR" && ./install.sh --tools $ASSUME_YES )

say "done."
say "Your new install is at: $NEW_DIR"
say "Next:"
say "  cd $NEW_DIR"
say "  conda activate plasbench"
say "  plasbench --version   # should print $LATEST_VERSION"
