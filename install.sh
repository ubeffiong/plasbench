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

# Long steps are silent for many minutes -- conda solving, a 450MB database
# download -- and silence reads as a hang. Announce each phase, how many there
# are, and what "slow" means for it, so a user can tell waiting from stuck.
TOTAL_STEPS=4
STEP_START=0
step() {
    STEP_START=$(date +%s)
    printf '\n[plasbench-install] ===== step %s/%s: %s =====\n' "$1" "$TOTAL_STEPS" "$2"
    [[ -n "${3:-}" ]] && printf '[plasbench-install] %s\n' "$3"
    printf '[plasbench-install] started %s\n' "$(date +%H:%M:%S)"
    return 0
}
step_done() {
    local elapsed=$(( $(date +%s) - STEP_START ))
    printf '[plasbench-install] done in %dm %02ds\n' $((elapsed / 60)) $((elapsed % 60))
}

# 1. A conda-family manager. env/bootstrap_conda.sh detects one and, if none is
#    present, offers to install Miniforge -- so a user does not have to install
#    conda separately before running this script.
if ! command -v conda >/dev/null 2>&1 && ! command -v mamba >/dev/null 2>&1    && ! command -v micromamba >/dev/null 2>&1; then
    step 1 "conda-family package manager" "downloading and installing Miniforge (~120 MB)"
    bash env/bootstrap_conda.sh $ASSUME_YES || {
        cat >&2 <<'EOF'
ERROR: no conda-family package manager is available.

PlasBench's tools (SPAdes, MOB-suite, Platon, minimap2) are conda packages, so
one is required. Install Miniforge yourself and re-run this script:

    https://github.com/conda-forge/miniforge#install

Or skip conda entirely and use the container, which needs only Docker:

    docker run --rm ghcr.io/ubeffiong/plasbench:latest plasbench demo
EOF
        exit 1
    }
    # bootstrap_conda.sh installs into $HOME/miniforge3 by default; pick it up
    # in this shell so the rest of the script can use it without a re-login.
    for candidate in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/mambaforge"; do
        if [[ -x "$candidate/bin/conda" ]]; then
            # shellcheck disable=SC1091
            . "$candidate/etc/profile.d/conda.sh"
            export PATH="$candidate/bin:$PATH"
            break
        fi
    done
    command -v conda >/dev/null 2>&1 || command -v micromamba >/dev/null 2>&1 || {
        say "conda was installed but is not on PATH in this shell."
        say "Open a new terminal (or run: exec bash) and re-run ./install.sh"
        exit 1
    }
fi

# 2. Reproducible environment.
step 2 "conda environment 'plasbench'"      "solving and downloading packages. Typically 5-20 minutes; conda prints its own progress below, and long pauses while it solves are normal."
bash env/setup_conda.sh
step_done

# 3. The CLI itself. --no-deps because every dependency is a conda package.
step 3 "the plasbench command" "quick -- a few seconds."
if command -v conda >/dev/null 2>&1; then
    conda run -n plasbench python -m pip install --no-deps .
else
    micromamba run -n plasbench python -m pip install --no-deps .
fi

step_done

# 4. Optional: the bioinformatics tools themselves.
if [[ "$WITH_TOOLS" -eq 1 ]]; then
    step 4 "bioinformatics tools and databases"          "the long one: SPAdes, Unicycler, MOB-suite, Platon and friends, then MOB-suite builds a 450 MB reference database from Zenodo. Expect 30-90 minutes on a slow link. The database download shows a percentage; the taxonomy build afterwards prints counters rather than a percentage and can sit for several minutes -- that is normal, not a hang."
    if command -v conda >/dev/null 2>&1; then
        conda run -n plasbench plasbench install-tools all $ASSUME_YES
    else
        micromamba run -n plasbench plasbench install-tools all $ASSUME_YES
    fi
    step_done
else
    printf '
[plasbench-install] step 4/%s: bioinformatics tools SKIPPED (re-run with --tools)
' "$TOTAL_STEPS"
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
