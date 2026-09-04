#!/usr/bin/env bash
# Create -- or safely update -- the 'plasbench' conda environment.
# Auto-detects mamba (faster) and falls back to conda.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${PLASBENCH_ENV_NAME:-plasbench}"

if command -v mamba >/dev/null 2>&1; then
    SOLVER=mamba
elif command -v conda >/dev/null 2>&1; then
    SOLVER=conda
else
    echo "ERROR: neither mamba nor conda found. Install Miniforge first:" >&2
    echo "    bash env/bootstrap_conda.sh      # detects, offers to install it for you" >&2
    echo "  (or plasbench install-conda, or see INSTALL.md for a manual install)" >&2
    exit 1
fi

# Does the environment already exist? Ask the solver rather than guessing at
# paths, so this works for miniforge, miniconda, mambaforge and a custom root.
env_prefix() {
    if command -v conda >/dev/null 2>&1; then
        local base; base="$(conda info --base 2>/dev/null || true)"
        [[ -n "$base" && -d "$base/envs/$ENV_NAME" ]] && { printf '%s' "$base/envs/$ENV_NAME"; return 0; }
    fi
    local root
    for root in "${MAMBA_ROOT_PREFIX:-}" "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3"; do
        [[ -n "$root" && -d "$root/envs/$ENV_NAME" ]] && { printf '%s' "$root/envs/$ENV_NAME"; return 0; }
    done
    return 1
}

echo "[setup_conda] using $SOLVER"

if PREFIX_PATH="$(env_prefix)"; then
    # NEVER run `env create` against an existing environment. It does not fail
    # -- it prompts "Found conda-prefix ... Overwrite?", and answering yes
    # deletes the environment and everything installed into it, including
    # MOB-suite's 450MB database, which then has to be downloaded again.
    # Updating is non-destructive and converges to the same specification.
    echo "[setup_conda] environment '$ENV_NAME' already exists at:"
    echo "[setup_conda]   $PREFIX_PATH"
    echo "[setup_conda] updating it in place (nothing is deleted) ..."
    "$SOLVER" env update --prefix "$PREFIX_PATH" --file "$HERE/environment.yml" --prune=false 2>/dev/null \
        || "$SOLVER" env update --prefix "$PREFIX_PATH" --file "$HERE/environment.yml"
    echo "[setup_conda] update complete."
    echo
    echo "[setup_conda] To rebuild it from scratch instead, remove it first -- deliberately:"
    echo "    conda env remove -n $ENV_NAME"
    echo "    bash env/setup_conda.sh"
else
    echo "[setup_conda] creating environment '$ENV_NAME' (this can take a few minutes)..."
    "$SOLVER" env create -f "$HERE/environment.yml"
fi

echo
echo "[setup_conda] done. Activate it with:"
echo "    conda activate $ENV_NAME"
echo "Then verify with:"
echo "    bash scripts/00_setup.sh"
