#!/usr/bin/env bash
# Install an optional PlasBench dependency profile into an existing conda env.
set -euo pipefail
ENV_NAME="plasbench"; PROFILE="core"
[[ "${1:-}" == "--env" ]] && { ENV_NAME="$2"; shift 2; }
[[ $# -gt 0 ]] && PROFILE="$1"
if command -v micromamba >/dev/null 2>&1; then SOLVER=(micromamba install -y -n "$ENV_NAME" -c conda-forge -c bioconda)
elif command -v mamba >/dev/null 2>&1; then SOLVER=(mamba install -y -n "$ENV_NAME" -c conda-forge -c bioconda)
elif command -v conda >/dev/null 2>&1; then SOLVER=(conda install -y -n "$ENV_NAME" -c conda-forge -c bioconda)
else echo "ERROR: install micromamba, mamba, or conda first." >&2; exit 1; fi
case "$PROFILE" in
 core) PKGS=(ncbi-datasets-cli sra-tools fastp minimap2);;
 assembly) PKGS=(spades unicycler);;
 reconstruction) PKGS=(mob_suite platon);;
 all) PKGS=(ncbi-datasets-cli sra-tools fastp minimap2 spades unicycler mob_suite platon);;
 *) PKGS=("$PROFILE");;
esac
echo "[plasbench] installing into $ENV_NAME: ${PKGS[*]}"
"${SOLVER[@]}" "${PKGS[@]}"
