#!/usr/bin/env bash
# One command to update PlasBench to the latest release. Run it from INSIDE your PlasBench folder:
#
#   ./update.sh               (plasbench upgrade does the same)
#   ./update.sh --yes         no questions
#   ./update.sh --keep-old    when moving from an older plasbench-<version> folder, keep that folder
#   ./update.sh --check-only  only say whether a newer release exists (nothing is downloaded or changed)
#   ./update.sh --version 0.5.6   install that exact release (an older one is a deliberate downgrade, with a warning)
#   ./update.sh --archive plasbench-0.5.6.tar.gz   install a release file you already downloaded (no internet needed;
#                             checks plasbench-0.5.6.tar.gz.sha256 beside it)
#   ./update.sh --rollback    go back to the release this folder had before the last update (saved in .plasbench-rollback/)
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
CHECK_ONLY=0
ROLLBACK=0
WANT_VERSION=""
LOCAL_ARCHIVE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES="--yes" ;;
        --refresh-tools) REFRESH_TOOLS=1 ;;
        --keep-old) KEEP_OLD=1 ;;
        --check-only) CHECK_ONLY=1 ;;
        --rollback) ROLLBACK=1 ;;
        --version)
            [[ $# -ge 2 ]] || { echo "--version needs a release number such as 0.5.6" >&2; exit 2; }
            WANT_VERSION="${2#v}"; shift ;;
        --archive)
            [[ $# -ge 2 ]] || { echo "--archive needs the path of a plasbench-<version>.tar.gz file" >&2; exit 2; }
            LOCAL_ARCHIVE="$2"; shift ;;
        -h|--help)
            sed -n '2,17p' "$PLASBENCH_UPDATE_SELF" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done
if [[ -n "$WANT_VERSION" && ! "$WANT_VERSION" =~ ^[0-9][0-9A-Za-z.+-]*$ ]]; then
    echo "ERROR[name]: '$WANT_VERSION' is not a release number (expected something like 0.5.6)." >&2; exit 2
fi
chosen=0
[[ -n "$WANT_VERSION" ]] && chosen=$((chosen + 1))
[[ -n "$LOCAL_ARCHIVE" ]] && chosen=$((chosen + 1))
[[ "$ROLLBACK" -eq 1 ]] && chosen=$((chosen + 1))
if [[ "$chosen" -gt 1 ]]; then
    echo "ERROR: choose one of --version, --archive or --rollback." >&2; exit 2
fi
if [[ "$CHECK_ONLY" -eq 1 && ( -n "$LOCAL_ARCHIVE" || "$ROLLBACK" -eq 1 ) ]]; then
    echo "ERROR: --check-only asks GitHub for the latest release; it cannot be combined with --archive or --rollback." >&2; exit 2
fi

say() { printf '[plasbench-update] %s\n' "$*"; }
phase() { printf '[plasbench-update] PHASE %s\n' "$*"; }
# A failure the window can name: ERROR[reason]: ... (reasons: offline, checksum, disk, permission, name, lock, notfound, extract).
fail() { local reason="$1"; shift; echo "ERROR[$reason]: $*" >&2; exit 1; }
# True when the first version is older than the second (GNU sort -V).
version_older() { [[ "$1" != "$2" && "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" == "$1" ]]; }
MAX_DOWNLOAD_MB="${PLASBENCH_UPDATE_MAX_MB:-1024}"

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

# Updating downloads from GitHub: say so plainly, before any work, when there is no internet (scripts/lib.sh require_internet).
if [[ -f "$HERE/scripts/lib.sh" ]]; then
    # shellcheck source=scripts/lib.sh
    source "$HERE/scripts/lib.sh"
fi
needs_internet() {
    if declare -F require_internet >/dev/null 2>&1; then
        require_internet --action "plasbench upgrade" --hint "Your current install keeps working. Download the release archive on a computer with internet and run scripts/install_latest.sh --archive FILE (or plasbench upgrade --archive FILE)." github
    fi
}

# Every curl in this script fetches only https URLs from GitHub (the API and the release assets), with a size limit.
fetch_json() {
    curl --proto '=https' --tlsv1.2 -fsSL "https://api.github.com/repos/$REPO/releases/latest"
}
download() {   # download URL DEST
    curl --proto '=https' --tlsv1.2 -fL --max-filesize "$((MAX_DOWNLOAD_MB * 1024 * 1024))" -o "$2" "$1"
}

# --- the release to install: the latest (asks GitHub), a named version, a file already downloaded, or the saved previous release ---
ROLLBACK_DIR="$TARGET/.plasbench-rollback"
LATEST_TAG=""
LATEST_VERSION=""
phase "1/6 check: which release"
if [[ "$ROLLBACK" -eq 1 ]]; then
    LOCAL_ARCHIVE="$(ls -1 "$ROLLBACK_DIR"/plasbench-*.tar.gz 2>/dev/null | head -n1 || true)"
    [[ -n "$LOCAL_ARCHIVE" ]] || fail notfound "there is no saved previous release in $ROLLBACK_DIR (the next update creates it). To go back anyway, download the older plasbench-<version>.tar.gz and run: plasbench upgrade --archive FILE"
    say "rolling back with the saved copy: $LOCAL_ARCHIVE"
fi
if [[ -n "$LOCAL_ARCHIVE" ]]; then
    [[ -f "$LOCAL_ARCHIVE" ]] || fail notfound "--archive file not found: $LOCAL_ARCHIVE"
    base="$(basename "$LOCAL_ARCHIVE")"
    LATEST_VERSION="$(printf '%s' "$base" | sed -nE 's/^plasbench-([0-9][0-9A-Za-z.+-]*)\.tar\.gz$/\1/p')"
    [[ -n "$LATEST_VERSION" ]] || fail name "--archive must be named plasbench-<version>.tar.gz (got $base). Use the file exactly as downloaded from the release page."
    LATEST_TAG="v$LATEST_VERSION"
    say "installing from the file $LOCAL_ARCHIVE (no download)"
elif [[ -n "$WANT_VERSION" ]]; then
    LATEST_VERSION="$WANT_VERSION"
    LATEST_TAG="v$WANT_VERSION"
    needs_internet
    say "requested version: $LATEST_VERSION"
else
    needs_internet
    say "checking the latest release on GitHub..."
    LATEST_JSON="$(fetch_json)" || {
        echo "ERROR[offline]: could not reach GitHub's API. Check your network and try again," >&2
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
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
    if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" ]]; then say "RESULT current: PlasBench $CURRENT_VERSION is the latest release."
    elif version_older "$CURRENT_VERSION" "$LATEST_VERSION"; then say "RESULT available: $CURRENT_VERSION -> $LATEST_VERSION (run: plasbench upgrade)"
    else say "RESULT newer: this folder ($CURRENT_VERSION) is newer than the latest release ($LATEST_VERSION); nothing to do."; fi
    exit 0
fi

if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" && -z "$LOCAL_ARCHIVE" ]]; then
    say "already up to date -- nothing to do."
    say "(plasbench upgrade also checks that the installed program matches this folder and repairs it; to see the evidence yourself: plasbench ui-state)"
    exit 0
fi
if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" ]]; then
    say "this folder already has $LATEST_VERSION; installing it again from the file (repairs missing or changed release files)."
elif [[ "$CURRENT_VERSION" != "unknown" ]] && version_older "$LATEST_VERSION" "$CURRENT_VERSION"; then
    say "WARNING: $LATEST_VERSION is OLDER than the installed $CURRENT_VERSION: a downgrade, because you asked for it (--version, --archive or --rollback). Studies and settings are kept, but a study written by a newer release may use features the older one lacks."
fi

if [[ "$MIGRATE" -eq 1 && -e "$TARGET" && ! -f "$TARGET/.plasbench-release-files" && -n "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
    echo "ERROR: $TARGET already exists and is not a PlasBench install folder. Move it aside, or set PLASBENCH_INSTALL_DIR, and re-run." >&2
    exit 1
fi

# Only one update at a time in this folder (a second window, a terminal, a double click): mkdir is atomic, the pid tells a live holder from a dead one.
LOCK="$HERE/.plasbench-upgrade.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    holder="$(cat "$LOCK/pid" 2>/dev/null || true)"
    if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
        fail lock "another PlasBench update is already running here (pid $holder). Wait for it to finish."
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || fail lock "could not take the update lock $LOCK"
fi
echo "$$" > "$LOCK/pid"

TARBALL="plasbench-$LATEST_VERSION.tar.gz"
DOWNLOAD_DIR="$(mktemp -d)"
trap 'rm -rf "$DOWNLOAD_DIR" "$PLASBENCH_UPDATE_SELF" "$LOCK"' EXIT

free_mb() {   # free MB where DIR is (or where it would be created); empty when it cannot be told
    local dir="$1"
    while [[ ! -d "$dir" && "$dir" != "/" && "$dir" != "." ]]; do dir="$(dirname "$dir")"; done
    df -Pk "$dir" 2>/dev/null | awk 'NR==2 {print int($4/1024)}' || true
}
require_space() {   # require_space DIR NEEDED_MB WHAT: stop before anything is changed when the disk cannot hold it
    local free; free="$(free_mb "$1")"
    if [[ -n "$free" && "$free" -lt "$2" ]]; then
        fail disk "not enough free disk space for $3: $free MB free where $1 is, about $2 MB needed. Free some space and try again; nothing was changed."
    fi
}

if [[ -n "$LOCAL_ARCHIVE" ]]; then
    phase "2/6 download: not needed (using the file)"
    size_mb=$(( $(wc -c < "$LOCAL_ARCHIVE") / 1048576 ))
    [[ "$size_mb" -le "$MAX_DOWNLOAD_MB" ]] || fail extract "$base is $size_mb MB, over the $MAX_DOWNLOAD_MB MB limit for a release file; this is not a PlasBench release."
    require_space "$DOWNLOAD_DIR" "$((size_mb * 3 + 50))" "unpacking the release"
    cp "$LOCAL_ARCHIVE" "$DOWNLOAD_DIR/$TARBALL"
    if [[ -f "$LOCAL_ARCHIVE.sha256" ]]; then
        cp "$LOCAL_ARCHIVE.sha256" "$DOWNLOAD_DIR/$TARBALL.sha256"
    else
        say "no $base.sha256 beside the file, so it cannot be checked against the published checksum."
        say "its SHA-256 is $(sha256sum "$DOWNLOAD_DIR/$TARBALL" | cut -d' ' -f1); compare it with the release page before trusting it."
        ( cd "$DOWNLOAD_DIR" && sha256sum "$TARBALL" > "$TARBALL.sha256" )
    fi
else
    phase "2/6 download: $TARBALL"
    require_space "$DOWNLOAD_DIR" 400 "the download"
    say "downloading https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL (at most $MAX_DOWNLOAD_MB MB) ..."
    dl_status=0
    download "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL" "$DOWNLOAD_DIR/$TARBALL" || dl_status=$?
    [[ "$dl_status" -eq 0 ]] || fail offline "could not download $TARBALL (curl exit status $dl_status; 22 means GitHub has no such release file, 63 means it is larger than $MAX_DOWNLOAD_MB MB, others a network problem). Nothing was changed."
    download "https://github.com/$REPO/releases/download/$LATEST_TAG/$TARBALL.sha256" "$DOWNLOAD_DIR/$TARBALL.sha256" \
        || fail offline "could not download the checksum file $TARBALL.sha256, so the release cannot be verified. Nothing was changed."
fi

phase "3/6 verify: checksum and contents"
say "verifying checksum..."
if ! ( cd "$DOWNLOAD_DIR" && sha256sum -c "$TARBALL.sha256" ); then
    fail checksum "the checksum of $TARBALL does not match $TARBALL.sha256: the file is damaged or was changed. Download it again. Nothing was changed."
fi
# The listing is read before anything is unpacked: only plasbench-<version>/..., never an absolute or ../ path.
if ! entries="$(tar -tzf "$DOWNLOAD_DIR/$TARBALL" 2>/dev/null)"; then
    fail extract "$TARBALL is not a readable .tar.gz archive. Nothing was changed."
fi
if grep -qE '^/|(^|/)\.\.(/|$)' <<< "$entries" || grep -qvE "^(\./)?plasbench-$LATEST_VERSION(/|$)" <<< "$entries"; then
    fail extract "$TARBALL does not look like a PlasBench release (it has files outside plasbench-$LATEST_VERSION/). Nothing was changed."
fi
mkdir -p "$DOWNLOAD_DIR/stage"
tar -xzf "$DOWNLOAD_DIR/$TARBALL" -C "$DOWNLOAD_DIR/stage" || fail extract "could not unpack $TARBALL. Nothing was changed."
RELEASE="$DOWNLOAD_DIR/stage/plasbench-$LATEST_VERSION"
[[ -f "$RELEASE/scripts/release_sync.sh" ]] || fail extract "the release has no scripts/release_sync.sh, so it is not a PlasBench release. Nothing was changed."
INSIDE_VERSION="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$RELEASE/plasbench/__init__.py" 2>/dev/null)"
if [[ "$INSIDE_VERSION" != "$LATEST_VERSION" ]]; then
    fail name "the file is named for $LATEST_VERSION but contains PlasBench ${INSIDE_VERSION:-of an unknown version}. Use the release file exactly as downloaded. Nothing was changed."
fi
release_mb=$(( $(du -sk "$RELEASE" | cut -f1) / 1024 ))
require_space "$TARGET" "$(( release_mb * 2 + 100 ))" "installing $LATEST_VERSION"

# The release about to be replaced is kept as a rollback copy (this folder's release files only, as plasbench-<version>.tar.gz) so that
# `plasbench upgrade --rollback` can go back. Failing to save it only warns: the new release was already verified complete.
save_rollback() {
    [[ "$MIGRATE" -eq 0 && "$CURRENT_VERSION" != "unknown" && -f "$TARGET/.plasbench-release-files" ]] || return 0
    local stage="$DOWNLOAD_DIR/rollback/plasbench-$CURRENT_VERSION" sum path archive
    mkdir -p "$stage"
    while IFS=$'\t' read -r sum path; do
        [[ -z "$sum" || "$sum" == \#* || ! -f "$TARGET/$path" ]] && continue
        mkdir -p "$stage/$(dirname "$path")"
        cp -p "$TARGET/$path" "$stage/$path"
    done < "$TARGET/.plasbench-release-files"
    if [[ ! -f "$stage/plasbench/__init__.py" || ! -f "$stage/scripts/release_sync.sh" ]]; then
        say "WARNING: could not save a rollback copy of $CURRENT_VERSION (its release files were not found); updating anyway."
        return 0
    fi
    archive="$DOWNLOAD_DIR/rollback/plasbench-$CURRENT_VERSION.tar.gz"
    if ! { tar -czf "$archive" -C "$DOWNLOAD_DIR/rollback" "plasbench-$CURRENT_VERSION" \
            && ( cd "$DOWNLOAD_DIR/rollback" && sha256sum "plasbench-$CURRENT_VERSION.tar.gz" > "plasbench-$CURRENT_VERSION.tar.gz.sha256" ); } 2>/dev/null; then
        say "WARNING: could not save a rollback copy of $CURRENT_VERSION; updating anyway."
        return 0
    fi
    mkdir -p "$ROLLBACK_DIR" 2>/dev/null || { say "WARNING: could not create $ROLLBACK_DIR; updating anyway."; return 0; }
    find "$ROLLBACK_DIR" -maxdepth 1 -type f -name 'plasbench-*.tar.gz*' -exec rm -f {} + 2>/dev/null || true
    if cp "$archive" "$archive.sha256" "$ROLLBACK_DIR/" 2>/dev/null; then
        say "saved $CURRENT_VERSION as a rollback copy: $ROLLBACK_DIR/plasbench-$CURRENT_VERSION.tar.gz"
    else
        say "WARNING: could not save a rollback copy of $CURRENT_VERSION; updating anyway."
    fi
}

# Reads and databases stay in one shared place; an old real data/ directory is moved there once.
phase "4/6 install: replacing the program files"
save_rollback
share_existing_data "$(default_data_dir)"
say "installing $LATEST_VERSION into $TARGET ..."
if ! bash "$RELEASE/scripts/release_sync.sh" sync "$RELEASE" "$TARGET" "$LATEST_VERSION"; then
    fail permission "could not write the release files into $TARGET (is the folder yours and writable?). If the program no longer starts, run: plasbench upgrade --rollback"
fi
if [[ "$MIGRATE" -eq 1 ]]; then
    bash "$RELEASE/scripts/release_sync.sh" migrate "$HERE" "$TARGET"
fi
write_data_setting "$TARGET" "$SHARED_DATA_DIR"

phase "5/6 environment: the installer"
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

phase "6/6 done"
say "done."
say "PlasBench $LATEST_VERSION is in: $TARGET"
say "Reusable reads and databases: $SHARED_DATA_DIR"
say "Next:"
say "  cd $TARGET"
say "  conda activate plasbench"
say "  plasbench --version   # should print $LATEST_VERSION"
