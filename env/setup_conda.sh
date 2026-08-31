#!/usr/bin/env bash
# Create the 'plasbench' conda environment from environment.yml.
# Auto-detects mamba (faster) and falls back to conda.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v mamba >/dev/null 2>&1; then
    SOLVER=mamba
elif command -v conda >/dev/null 2>&1; then
    SOLVER=conda
else
    echo "ERROR: neither mamba nor conda found. Install Miniforge first (see INSTALL.md)." >&2
    exit 1
fi

echo "[setup_conda] using $SOLVER"
echo "[setup_conda] creating environment 'plasbench' (this can take a few minutes)..."
"$SOLVER" env create -f "$HERE/environment.yml" || {
    echo "[setup_conda] env may already exist; trying update..."
    "$SOLVER" env update -f "$HERE/environment.yml"
}

echo
echo "[setup_conda] done. Activate it with:"
echo "    conda activate plasbench"
echo "Then verify with:"
echo "    bash scripts/00_setup.sh"
