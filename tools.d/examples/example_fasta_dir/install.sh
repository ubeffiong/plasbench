#!/usr/bin/env bash
# Called by `plasbench install-tools example_fasta_dir` with the environment name to create.
set -euo pipefail
ENV_NAME="$1"
conda create -y -n "$ENV_NAME" -c conda-forge -c bioconda python=3.11 minimap2
conda run -n "$ENV_NAME" pip install "git+https://example.org/examplelr.git@v2.0.0"
