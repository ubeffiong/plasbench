#!/usr/bin/env bash
# PlasBench offline installer.
#
# This ships inside the release tarball so a user never needs git or a source
# checkout: download one file, extract it, run this. It delegates to the same
# scripts a developer would call, so there is exactly one install path to
# maintain.
#
#   tar -xzf plasbench-<version>.tar.gz
#   cd plasbench-<version>
#   ./install.sh            # env + CLI
#   ./install.sh --tools    # env + CLI + every tool the RUN_* flags need
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

WITH_TOOLS=0
ASSUME_YES=""
for arg in "$@"; do
    case "$arg" in
        --tools) WITH_TOOLS=1 ;;
        -y|--yes) ASSUME_YES="--yes" ;;
        -h|--help)
            sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say() { printf '[plasbench-install] %s\n' "$*"; }

# 1. A conda-family manager is the one thing this cannot install for you
#    portably; env/setup_conda.sh reports precisely what is missing.
if ! command -v conda >/dev/null 2>&1 && ! command -v mamba >/dev/null 2>&1 \
   && ! command -v micromamba >/dev/null 2>&1; then
    cat >&2 <<'EOF'
ERROR: no conda/mamba/micromamba found on PATH.

PlasBench's tools (SPAdes, MOB-suite, Platon, minimap2) are conda packages, so a
conda-family manager is required. Miniforge is the recommended one:

    https://github.com/conda-forge/miniforge#install

Install it, open a new shell, and run this script again. If you would rather not
install conda at all, use the container instead -- it needs nothing but Docker:

    docker run --rm ghcr.io/ubeffiong/plasbench:latest plasbench demo
EOF
    exit 1
fi

# 2. Reproducible environment.
say "creating the 'plasbench' conda environment (this is the slow step) ..."
bash env/setup_conda.sh

# 3. The CLI itself. --no-deps because every dependency is a conda package.
say "installing the plasbench command ..."
if command -v conda >/dev/null 2>&1; then
    conda run -n plasbench python -m pip install --no-deps .
else
    micromamba run -n plasbench python -m pip install --no-deps .
fi

# 4. Optional: the bioinformatics tools themselves.
if [[ "$WITH_TOOLS" -eq 1 ]]; then
    say "installing the tools the RUN_* flags in config/config.sh call for ..."
    if command -v conda >/dev/null 2>&1; then
        conda run -n plasbench plasbench install-tools all $ASSUME_YES
    else
        micromamba run -n plasbench plasbench install-tools all $ASSUME_YES
    fi
fi

cat <<EOF

[plasbench-install] done.

Next:
    conda activate plasbench
    plasbench test        # offline check of the scoring engine
    plasbench demo        # offline end-to-end demo, no downloads

$( [[ "$WITH_TOOLS" -eq 1 ]] || echo "Then install the tools when you need them:
    plasbench install-tools all
" )
Run a benchmark on a shipped cohort:
    plasbench run --samples cohorts/public-v2.tsv

EOF
