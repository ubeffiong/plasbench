#!/usr/bin/env bash
# One command to update PlasBench to the latest release. Run it from INSIDE your PlasBench folder:
#
#   ./update.sh               (plasbench upgrade does the same)
#   ./update.sh --yes         no questions
#   ./update.sh --keep-old    when moving from an older plasbench-<version> folder, keep that folder
#
# PlasBench lives in one folder, PlasBench, updated in place: only the files the previous release installed are
# replaced (scripts/release_sync.sh), so your studies, settings (config/local.env), own tools, downloads, tool
# environments and databases stay as they are and are reused. Run from an older versioned folder (plasbench-0.x.y),
# it installs the new release into PlasBench beside it, moves that folder's runs into PlasBench/studies/, copies its
# settings, and asks before deleting the old folder. Tools are reused unless --refresh-tools is given.
set -euo pipefail

# This file is replaced by the update it runs; bash reads a script as it executes, so run from a private copy.
if [[ -z "${PLASBENCH_UPDATE_SELF:-}" ]]; then
    copy="$(mktemp)"
    cp "${BASH_SOURCE[0]}" "$copy"
    PLASBENCH_UPDATE_SELF="$copy" PLASBENCH_UPDATE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" exec bash "$copy" "$@"
fi
HERE="$PLASBENCH_UPDATE_HOME"
trap 'rm -f "$PLASBENCH_UPDATE_SELF"' EXIT
cd "$HERE"

REPO="ubeffiong/plasbench"
ASSUME_YES=""
REFRESH_TOOLS=0
KEEP_OLD=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES="--yes" ;;
        --refresh-tools) REFRESH_TOOLS=1 ;;
        --keep-old) KEEP_OLD=1 ;;
        -h|--help)
            sed -n '2,12p' "$PLASBENCH_UPDATE_SELF" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say() { printf '[plasbench-update] %s\n' "$*"; }

# Carry forward an existing shared location if an earlier install already configured one.
if [[ -f "$HERE/config/local.env" ]]; then
    # shellcheck disable=SC1090,SC1091
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
    # An earlier upgrade may already have replaced data/ with a symlink: use its target.
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
    # Two independent data locations can legitimately exist: never merge or delete either; keep using this one.
    if [[ "$(cd "$old_data" && pwd -P)" != "$(cd "$requested" && pwd -P)" ]]; then
        SHARED_DATA_DIR="$old_data"
        say "existing data directory differs from $requested; reusing $old_data without copying it."
    fi
}

CURRENT_VERSION="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' plasbench/__init__.py 2>/dev/null)"
CURRENT_VERSION="${CURRENT_VERSION:-unknown}"
say "current version: $CURRENT_VERSION"

# In place when this is already the PlasBench folder; otherwise this is an older versioned install to carry over.
if [[ -f "$HERE/.plasbench-release-files" ]]; then
    TARGET="$HERE"
    MIGRATE=0
else
    TARGET="${PLASBENCH_INSTALL_DIR:-$(dirname "$HERE")}/PlasBench"
    MIGRATE=1
fi

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

if [[ "$MIGRATE" -eq 1 && -e "$TARGET" && ! -f "$TARGET/.plasbench-release-files" && -n "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
    echo "ERROR: $TARGET already exists and is not a PlasBench install folder. Move it aside, or set PLASBENCH_INSTALL_DIR, and re-run." >&2
    exit 1
fi

TARBALL="plasbench-$LATEST_VERSION.tar.gz"
DOWNLOAD_DIR="$(mktemp -d)"
trap 'rm -rf "$DOWNLOAD_DIR" "$PLASBENCH_UPDATE_SELF"' EXIT

say "downloading $TARBALL ..."
curl -fL -o "$DOWNLOAD_DIR/$TARBALL" \
    "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL"
curl -fL -o "$DOWNLOAD_DIR/$TARBALL.sha256" \
    "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL.sha256"
say "verifying checksum..."
( cd "$DOWNLOAD_DIR" && sha256sum -c "$TARBALL.sha256" )
mkdir -p "$DOWNLOAD_DIR/stage"
tar -xzf "$DOWNLOAD_DIR/$TARBALL" -C "$DOWNLOAD_DIR/stage"
RELEASE="$DOWNLOAD_DIR/stage/plasbench-$LATEST_VERSION"

# Reads and databases stay in one shared place; an old real data/ directory is moved there once.
share_existing_data "$(default_data_dir)"
say "installing $LATEST_VERSION into $TARGET ..."
bash "$RELEASE/scripts/release_sync.sh" sync "$RELEASE" "$TARGET" "$LATEST_VERSION"
if [[ "$MIGRATE" -eq 1 ]]; then
    bash "$RELEASE/scripts/release_sync.sh" migrate "$HERE" "$TARGET"
fi
write_data_setting "$TARGET" "$SHARED_DATA_DIR"

INSTALL_ARGS=()
[[ "$REFRESH_TOOLS" -eq 1 ]] && INSTALL_ARGS+=(--tools --refresh-env)
[[ -n "$ASSUME_YES" ]] && INSTALL_ARGS+=("$ASSUME_YES")
say "running the installer (reusing $SHARED_DATA_DIR and the existing conda environment)..."
( cd "$TARGET" && PLASBENCH_DATA_DIR="$SHARED_DATA_DIR" ./install.sh "${INSTALL_ARGS[@]}" )
[[ "$REFRESH_TOOLS" -eq 1 ]] || say "tools and databases were reused. Run './update.sh --refresh-tools' only if release notes require new dependencies."

if [[ "$MIGRATE" -eq 1 ]]; then
    if [[ "$KEEP_OLD" -eq 1 ]]; then
        say "kept $HERE (--keep-old); its runs are now in $TARGET/studies"
    elif ! why="$(bash "$TARGET/scripts/release_sync.sh" removable "$HERE")"; then
        say "kept $HERE: $why"
    else
        reply=""
        if [[ -n "$ASSUME_YES" ]]; then
            reply="y"
        else
            printf '%s' "Delete the old folder $HERE? Its runs are in $TARGET/studies and downloads are shared. [y/N] " >&2
            read -r reply || true
        fi
        case "$reply" in
            y|Y|yes|YES|Yes) cd "$TARGET"; rm -rf "$HERE"; say "removed $HERE" ;;
            *) say "kept $HERE (delete it yourself when you no longer need it)" ;;
        esac
    fi
fi

say "done."
say "PlasBench $LATEST_VERSION is in: $TARGET"
say "Reusable reads and databases: $SHARED_DATA_DIR"
say "Next:"
say "  cd $TARGET"
say "  conda activate plasbench"
say "  plasbench --version   # should print $LATEST_VERSION"
