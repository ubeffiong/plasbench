#!/usr/bin/env bash
# Install an optional PlasBench dependency profile into an existing conda env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="plasbench"; PROFILE="core"
[[ "${1:-}" == "--env" ]] && { ENV_NAME="$2"; shift 2; }
[[ $# -gt 0 ]] && PROFILE="$1"

# Resolve the environment to an absolute PREFIX and install with -p, never -n.
#
# `-n NAME` means "look under this solver's own root prefix", and the solvers
# disagree about where that is: micromamba defaults to $MAMBA_ROOT_PREFIX
# (~/.local/share/mamba), while a Miniforge conda keeps envs in ~/miniforge3.
# On a machine with both -- which is exactly what env/bootstrap_conda.sh plus a
# system micromamba produces -- `micromamba install -n plasbench` aborts with
# "No prefix found at: ~/.local/share/mamba/envs/plasbench" even though the
# environment exists. An absolute prefix is unambiguous for all three solvers.
resolve_prefix() {
    # Already inside the target environment (the usual case: `plasbench
    # install-tools` runs under `conda run -n plasbench`).
    if [[ -n "${CONDA_PREFIX:-}" && "$(basename "$CONDA_PREFIX")" == "$ENV_NAME" ]]; then
        printf '%s' "$CONDA_PREFIX"; return 0
    fi
    # Ask conda where its environments live.
    if command -v conda >/dev/null 2>&1; then
        local base; base="$(conda info --base 2>/dev/null || true)"
        [[ -n "$base" && -d "$base/envs/$ENV_NAME" ]] && { printf '%s' "$base/envs/$ENV_NAME"; return 0; }
    fi
    # Then micromamba's root prefix.
    local root="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}"
    [[ -d "$root/envs/$ENV_NAME" ]] && { printf '%s' "$root/envs/$ENV_NAME"; return 0; }
    for root in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/.local/share/mamba"; do
        [[ -d "$root/envs/$ENV_NAME" ]] && { printf '%s' "$root/envs/$ENV_NAME"; return 0; }
    done
    return 1
}

# mamba and conda are preferred over micromamba: on a Miniforge install they
# already agree with the environment that env/setup_conda.sh created.
if command -v mamba >/dev/null 2>&1; then SOLVER_BIN=mamba
elif command -v conda >/dev/null 2>&1; then SOLVER_BIN=conda
elif command -v micromamba >/dev/null 2>&1; then SOLVER_BIN=micromamba
else
    echo "ERROR: install micromamba, mamba, or conda first:" >&2
    echo "    bash env/bootstrap_conda.sh      # detects, offers to install it for you" >&2
    echo "  (or plasbench install-conda, or see INSTALL.md for a manual install)" >&2
    exit 1
fi

CHANNELS=(-c conda-forge -c bioconda)
if TARGET_PREFIX="$(resolve_prefix)"; then
    SOLVER=("$SOLVER_BIN" install -y -p "$TARGET_PREFIX" "${CHANNELS[@]}")
    CREATE=("$SOLVER_BIN" create -y -p "$TARGET_PREFIX")
    TARGET_LABEL="$TARGET_PREFIX"
else
    # No existing environment: fall back to creating one by name.
    SOLVER=("$SOLVER_BIN" install -y -n "$ENV_NAME" "${CHANNELS[@]}")
    CREATE=("$SOLVER_BIN" create -y -n "$ENV_NAME")
    TARGET_LABEL="$ENV_NAME (not yet created)"
fi

case "$PROFILE" in
 locked) LOCK="$HERE/environment.lock.yml"; grep -q '^@EXPLICIT$' "$LOCK" || { echo "ERROR: $LOCK is not a Conda @EXPLICIT lock. Regenerate with: bash env/lock_environment.sh" >&2; exit 2; }; "${CREATE[@]}" $(awk '!/^(@|#|$)/ {print}' "$LOCK"); exit;;
 core) PKGS=(ncbi-datasets-cli sra-tools fastp minimap2 seqtk unzip);;
 assembly) PKGS=(spades unicycler);;
 reconstruction) PKGS=(mob_suite platon);;
 long-read) PKGS=(flye mob_suite);;
 plassembler) PKGS=(plassembler);;
 annotation) PKGS=(bakta);;
 annotation-prokka) PKGS=(prokka);;
 gplas)
    # Bioconda ships gplas 0.6.1, the older snakemake tool. PlasBench invokes
    # `gplas -i GRAPH -P CLASSIFIER`, and -P/--prediction exists only in gplas2,
    # which is distributed from GitLab. Installing this package alone makes
    # every gplas2_mob run fail rather than be cleanly skipped, so say so.
    cat >&2 <<'EOF'
WARNING: bioconda's 'gplas' is version 0.6.1 and does NOT provide the
         -P/--prediction flag that PlasBench's gplas2 modes require.
         For RUN_GPLAS2_MOB / RUN_GPLAS2_EXTERNAL install gplas2 from
         https://gitlab.com/mmb-umcu/gplas2 and confirm `gplas --help`
         lists -P. gplas2 also requires ASSEMBLER=unicycler, because
         SPAdes contig ids never match its GFA segment ids.
EOF
    PKGS=(gplas);;
 # gplas is deliberately NOT in 'all': see the warning above.
 all) PKGS=(ncbi-datasets-cli sra-tools fastp minimap2 seqtk unzip spades unicycler flye mob_suite platon bakta);;
 *) PKGS=("$PROFILE");;
esac
echo "[plasbench] installing into $TARGET_LABEL: ${PKGS[*]}"
"${SOLVER[@]}" "${PKGS[@]}"
