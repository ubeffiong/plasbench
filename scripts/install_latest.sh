#!/usr/bin/env bash
# Download, checksum-verify, and install (or update) the latest published PlasBench release in ONE folder.
#
# Usage:
#   bash install_latest.sh          # latest code + conda environment, in ~/PlasBench
#   bash install_latest.sh --tools  # also install benchmark tools/databases
#   bash install_latest.sh --yes    # no questions: pass consent to install.sh, remove carried-over old folders
#   bash install_latest.sh --keep-old   # keep older plasbench-<version> folders after carrying them over
#   bash install_latest.sh --archive plasbench-0.4.0.tar.gz   # install a release file you already downloaded
#                                   # (no internet needed here; checks plasbench-0.4.0.tar.gz.sha256 beside it)
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
LOCAL_ARCHIVE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tools) WITH_TOOLS=1 ;;
        -y|--yes) ASSUME_YES="--yes" ;;
        --keep-old) KEEP_OLD=1 ;;
        --archive)
            [[ $# -ge 2 ]] || { echo "--archive needs the path of a plasbench-<version>.tar.gz file" >&2; exit 2; }
            LOCAL_ARCHIVE="$2"; shift ;;
        -h|--help)
            sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required." >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "ERROR: sha256sum is required." >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "ERROR: tar is required." >&2; exit 1; }

say() { printf '[plasbench-latest] %s\n' "$*"; }

# Say WHY a download failed and what to do, instead of only that it did. $1 is curl's exit status.
network_help() {
    local code="$1"
    {
        echo "ERROR: could not reach GitHub (curl exit status $code)."
        case "$code" in
            6) echo "  The name github.com could not be resolved: this computer's DNS is not working, so the problem is the"
               echo "  network, not PlasBench. Check, in this terminal:"
               echo "      getent hosts github.com        # prints an address when DNS works"
               echo "      cat /etc/resolv.conf           # should list a 'nameserver' line"
               echo "  On Windows with WSL2 this is usually fixed by one of:"
               echo "      1. In PowerShell:  wsl --shutdown   then open the Ubuntu terminal again."
               echo "      2. Turn a VPN off (or on) and retry; some VPNs break WSL's DNS."
               echo "      3. Set a DNS server by hand, in this terminal:"
               echo "           sudo sh -c 'printf \"[network]\\ngenerateResolvConf = false\\n\" >> /etc/wsl.conf'"
               echo "           sudo rm -f /etc/resolv.conf"
               echo "           sudo sh -c 'printf \"nameserver 1.1.1.1\\nnameserver 8.8.8.8\\n\" > /etc/resolv.conf'"
               echo "         then wsl --shutdown in PowerShell and reopen Ubuntu." ;;
            7|28|35|56) echo "  The connection to github.com failed or timed out. Check the internet connection, any VPN, and a proxy"
               echo "  (if your network needs one, set https_proxy / http_proxy before running this)." ;;
            *) echo "  Check the internet connection, any VPN, and a proxy (https_proxy / http_proxy)." ;;
        esac
        echo "  With no working internet in this terminal you can still install: on any computer that has internet, download"
        echo "  plasbench-<version>.tar.gz and plasbench-<version>.tar.gz.sha256 from"
        echo "      https://github.com/$REPO/releases/latest"
        echo "  copy both beside each other onto this machine (in WSL a Windows folder is under /mnt/c/Users/<you>/Downloads),"
        echo "  then, because this script is inside the archive too:"
        echo "      tar -xzf plasbench-<version>.tar.gz"
        echo "      bash plasbench-<version>/scripts/install_latest.sh --archive \"\$PWD/plasbench-<version>.tar.gz\" --tools"
    } >&2
}

download_dir="$(mktemp -d)"
trap 'rm -rf "$download_dir"' EXIT

if [[ -n "$LOCAL_ARCHIVE" ]]; then
    [[ -f "$LOCAL_ARCHIVE" ]] || { echo "ERROR: --archive file not found: $LOCAL_ARCHIVE" >&2; exit 1; }
    base="$(basename "$LOCAL_ARCHIVE")"
    version="$(printf '%s' "$base" | sed -nE 's/^plasbench-([0-9][0-9A-Za-z.+-]*)\.tar\.gz$/\1/p')"
    [[ -n "$version" ]] || { echo "ERROR: --archive must be named plasbench-<version>.tar.gz (got $base)." >&2; exit 1; }
    tag="v$version"
    archive="$download_dir/$base"
    cp "$LOCAL_ARCHIVE" "$archive"
    if [[ -f "$LOCAL_ARCHIVE.sha256" ]]; then
        cp "$LOCAL_ARCHIVE.sha256" "$archive.sha256"
    else
        say "no $base.sha256 beside the archive, so it cannot be checked against the published checksum."
        say "its SHA-256 is $(sha256sum "$archive" | cut -d' ' -f1); compare it with the release page before trusting it."
        (cd "$download_dir" && sha256sum "$base" > "$base.sha256")
    fi
else
    say "checking the latest GitHub release..."
    api_status=0
    release_json="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest")" || api_status=$?
    if [[ "$api_status" -ne 0 ]]; then
        network_help "$api_status"
        exit 1
    fi
    tag="$(printf '%s' "$release_json" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
    version="${tag#v}"
    [[ -n "$tag" && "$version" != "$tag" ]] || { echo "ERROR: could not read the latest release version." >&2; exit 1; }
fi

destination="${PLASBENCH_INSTALL_DIR:-$HOME}"
target="$destination/PlasBench"
mkdir -p "$destination"
if [[ -f "$target/plasbench/__init__.py" ]]; then
    current="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$target/plasbench/__init__.py")"
    say "PlasBench ${current:-?} is installed in $target; updating it in place to $version"
fi
# The release archive is only an installation transport: download into a private temporary directory, removed on
# every exit path, so no stale archive is left looking like an installed version.
archive="$download_dir/plasbench-$version.tar.gz"
checksum="$archive.sha256"
url="https://github.com/$REPO/releases/download/$tag/plasbench-$version.tar.gz"

if [[ -z "$LOCAL_ARCHIVE" ]]; then
    say "downloading PlasBench $version..."
    for fetch in "$archive|$url" "$checksum|$url.sha256"; do
        fetch_status=0
        curl -fL -o "${fetch%%|*}" "${fetch#*|}" || fetch_status=$?
        if [[ "$fetch_status" -ne 0 ]]; then network_help "$fetch_status"; exit 1; fi
    done
fi
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
