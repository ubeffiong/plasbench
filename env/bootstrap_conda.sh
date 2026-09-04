#!/usr/bin/env bash
# Check for a conda-family package manager (micromamba/mamba/conda); if none
# is on PATH, offer to download and install Miniforge (conda + mamba,
# conda-forge/bioconda channels preconfigured) -- the same installer
# INSTALL.md already tells users to run by hand, automated and checksummed.
#
# Usage:
#   bash env/bootstrap_conda.sh              # detect; prompt before installing
#   bash env/bootstrap_conda.sh --yes        # detect; install without prompting
#   bash env/bootstrap_conda.sh --prefix DIR # install location (default: $HOME/miniforge3)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../scripts/lib.sh"

ASSUME_YES=0
PREFIX="${PLASBENCH_CONDA_PREFIX:-$HOME/miniforge3}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1; shift ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        *) die "unknown argument: $1 (usage: bootstrap_conda.sh [-y|--yes] [--prefix DIR])" ;;
    esac
done

for candidate in micromamba mamba conda; do
    if have "$candidate"; then
        log "Found '$candidate' already installed at $(command -v "$candidate")."
        log "Nothing to install. Continue with: bash env/setup_conda.sh"
        exit 0
    fi
done

log "No conda-family package manager (conda/mamba/micromamba) found on PATH."

# INSTALL.md's own manual one-liner uses $(uname)-$(uname -m) directly, which
# happens to match the published asset name only on Linux ("Linux" is also
# uname's own output there) -- on macOS uname reports "Darwin" but the asset
# is named "MacOSX", so that shorthand silently breaks there. Mapped
# explicitly here instead of copying the shorthand.
OS_NAME="$(uname -s)"
ARCH="$(uname -m)"
case "$OS_NAME" in
    Linux) ASSET_OS="Linux" ;;
    Darwin) ASSET_OS="MacOSX" ;;
    *)
        die "No automatic installer for OS '$OS_NAME'. PlasBench targets Ubuntu/WSL2; install Miniforge manually: https://github.com/conda-forge/miniforge"
        ;;
esac
case "$ARCH" in
    x86_64|amd64) ASSET_ARCH="x86_64" ;;
    aarch64|arm64)
        if [[ "$ASSET_OS" == "MacOSX" ]]; then ASSET_ARCH="arm64"; else ASSET_ARCH="aarch64"; fi
        ;;
    *)
        die "No automatic installer for architecture '$ARCH'. Install Miniforge manually: https://github.com/conda-forge/miniforge"
        ;;
esac

INSTALLER="Miniforge3-${ASSET_OS}-${ASSET_ARCH}.sh"
BASE_URL="https://github.com/conda-forge/miniforge/releases/latest/download"
INSTALLER_URL="$BASE_URL/$INSTALLER"
CHECKSUM_URL="$INSTALLER_URL.sha256"

log "PlasBench needs a conda-family package manager to install its bioinformatics tools."
log "Recommended distribution: Miniforge (conda + mamba, conda-forge/bioconda preconfigured)."
log "  Installer    : $INSTALLER"
log "  Download from: $INSTALLER_URL"
log "  Install to   : $PREFIX"
echo

if [[ "$ASSUME_YES" -ne 1 ]]; then
    REPLY=""
    read -r -p "Download and install Miniforge now? [y/N] " REPLY || true
    case "$REPLY" in
        y|Y|yes|YES|Yes) : ;;
        *) log "Skipped. Install manually (see INSTALL.md) and re-run, or pass --yes to skip this prompt."; exit 1 ;;
    esac
fi

have curl || have wget || die "need 'curl' or 'wget' to download the installer"
fetch() {  # fetch URL DEST
    if have curl; then curl -fsSL -o "$2" "$1"; else wget -q -O "$2" "$1"; fi
}

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
INSTALLER_PATH="$WORKDIR/$INSTALLER"

log "Downloading $INSTALLER_URL ..."
fetch "$INSTALLER_URL" "$INSTALLER_PATH" || die "download failed: $INSTALLER_URL"

if fetch "$CHECKSUM_URL" "$INSTALLER_PATH.sha256" 2>/dev/null && [[ -s "$INSTALLER_PATH.sha256" ]]; then
    log "Verifying checksum ..."
    EXPECTED="$(awk '{print $1}' "$INSTALLER_PATH.sha256")"
    OBSERVED="$(sha256sum "$INSTALLER_PATH" | awk '{print $1}')"
    [[ "$EXPECTED" == "$OBSERVED" ]] || die "checksum mismatch for $INSTALLER (expected $EXPECTED, got $OBSERVED); refusing to run an unverified installer"
    log "  checksum OK ($OBSERVED)"
else
    warn "could not fetch $CHECKSUM_URL; proceeding without checksum verification"
fi

log "Installing Miniforge to $PREFIX ..."
bash "$INSTALLER_PATH" -b -p "$PREFIX" || die "Miniforge installation failed"

echo
log "Miniforge installed at $PREFIX."
log "To use it in THIS shell right now:"
log "    source \"$PREFIX/etc/profile.d/conda.sh\""
log "To use it in every new shell, run once:"
log "    \"$PREFIX/bin/conda\" init \"\$(basename \"\$SHELL\")\"   # then restart your shell"
log "Then continue with: bash env/setup_conda.sh"
