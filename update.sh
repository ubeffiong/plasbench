#!/usr/bin/env bash
# One command to upgrade an existing PlasBench install to the latest release.
#
# Run this from INSIDE your current install directory (the one containing
# this file, e.g. ~/plasbench-0.1.9):
#
#   ./update.sh
#
# It finds the latest release, downloads and verifies it, migrates your
# existing downloaded inputs and databases into one stable user data location,
# then runs the new version's own installer. Code remains versioned, but data
# is shared; the existing checkout receives a compatibility symlink so it
# continues to work. The shared 'plasbench' conda environment is updated in
# place rather than recreated (see env/setup_conda.sh).
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

# Carry forward an existing shared location if an earlier install already
# configured one. This file is user-owned and created by install.sh.
if [[ -f "$HERE/config/local.env" ]]; then
    # shellcheck disable=SC1090
    source "$HERE/config/local.env"
fi

default_data_dir() {
    printf '%s\n' "${PLASBENCH_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/plasbench/data}"
}

write_data_setting() {
    local install_dir data_dir settings
    install_dir="$1"
    data_dir="$2"
    settings="$install_dir/config/local.env"
    mkdir -p "$(dirname "$settings")" "$data_dir"
    if [[ ! -f "$settings" ]] || ! grep -q '^export PLASBENCH_DATA_DIR=' "$settings"; then
        {
            echo '# Created by PlasBench update; reusable inputs and databases are shared.'
            printf 'export PLASBENCH_DATA_DIR=%q\n' "$data_dir"
        } >> "$settings"
        chmod 600 "$settings" 2>/dev/null || true
    fi
}

share_existing_data() {
    local old_data="$HERE/data" requested="$1" parent
    SHARED_DATA_DIR="$requested"
    [[ -d "$old_data" ]] || return 0

    # An earlier upgrade may already have replaced data/ with a symlink. If
    # no explicit setting exists, use its resolved target instead of guessing
    # a new default directory.
    if [[ -L "$old_data" ]]; then
        if [[ -z "${PLASBENCH_DATA_DIR:-}" ]]; then
            SHARED_DATA_DIR="$(cd "$old_data" && pwd -P)"
        fi
        return 0
    fi

    if [[ ! -e "$requested" ]]; then
        parent="$(dirname "$requested")"
        mkdir -p "$parent"
        say "moving reusable data to $requested (no copy and no re-download)..."
        mv "$old_data" "$requested"
        ln -s "$requested" "$old_data"
        return 0
    fi

    # Two independent data locations can legitimately exist (for example a
    # user explicitly set PLASBENCH_DATA_DIR before upgrading). Never merge or
    # delete either automatically; keep using the current one safely.
    if [[ "$(cd "$old_data" && pwd -P)" != "$(cd "$requested" && pwd -P)" ]]; then
        SHARED_DATA_DIR="$old_data"
        say "existing data directory differs from $requested; reusing $old_data without copying it."
    fi
}

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

# Make old and new code use one physical directory for reads and databases.
# This first upgrade moves old data once, then leaves a compatibility symlink;
# later upgrades only reuse the existing shared path.
share_existing_data "$(default_data_dir)"
write_data_setting "$HERE" "$SHARED_DATA_DIR"
write_data_setting "$NEW_DIR" "$SHARED_DATA_DIR"
for extra in .ncbi.env config/local.tsv; do
    if [[ -f "$HERE/$extra" && ! -f "$NEW_DIR/$extra" ]]; then
        say "copying $extra from the current install..."
        mkdir -p "$(dirname "$NEW_DIR/$extra")"
        cp "$HERE/$extra" "$NEW_DIR/$extra"
    fi
done

say "installing $LATEST_VERSION (reusing $SHARED_DATA_DIR and the shared 'plasbench' conda environment)..."
( cd "$NEW_DIR" && PLASBENCH_DATA_DIR="$SHARED_DATA_DIR" ./install.sh --tools $ASSUME_YES )

say "done."
say "Your new install is at: $NEW_DIR"
say "Reusable reads and databases: $SHARED_DATA_DIR"
say "Next:"
say "  cd $NEW_DIR"
say "  conda activate plasbench"
say "  plasbench --version   # should print $LATEST_VERSION"
