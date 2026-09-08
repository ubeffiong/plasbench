#!/usr/bin/env bash
# Install an optional PlasBench dependency profile into an existing conda env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../scripts/lib.sh"
ENV_NAME="plasbench"; PROFILE="core"; ASSUME_YES=0
[[ "${1:-}" == "--env" ]] && { ENV_NAME="$2"; shift 2; }
[[ "${1:-}" == "--yes" ]] && { ASSUME_YES=1; shift; }
[[ $# -gt 0 ]] && PROFILE="$1"

# These inspection actions share the machine-readable registry with CI. They
# do not touch an environment, which makes them safe before any download.
case "$PROFILE" in
  list|plan|validate)
    exec python3 "$HERE/../python/tool_installer_registry.py" "$PROFILE"
    ;;
esac

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
 # The executable metagenomic scorer consumes graph/bin tables produced by
 # adapters. SPAdes supplies metaSPAdes and geNomad supplies a transparent
 # contig-classification baseline. Graph deconvolution tools with unpinned
 # upstream runtimes are intentionally not claimed as installed here.
 metagenomics) PKGS=(spades genomad);;
 ppr-meta)
    cat >&2 <<'EOF'
PPR-Meta is a legacy Python 2/TensorFlow 1/MATLAB-runtime application. To avoid
an unpinned and unsafe install, PlasBench does not install it automatically.
Use a locally validated, digest-pinned container, retain the image digest in
your community manifest, then normalize its CSV with:
    plasbench normalize-meta-classifier --tool ppr_meta --input result.csv --out tool/community.classification.tsv
EOF
    exit 2
    ;;
 plsmd)
    cat >&2 <<'EOF'
plsMD is distributed as a Docker workflow with a PLSDB-dependent database.
It is registered as an isolate short-read reconstruction candidate, but no
floating image or database is installed automatically. Pin and validate the
image digest and PLSDB release before using it in a benchmark.
EOF
    exit 2
    ;;
 mobilome-map)
    cat >&2 <<'EOF'
The EBI Mobilome Annotation Pipeline is a Nextflow/container evidence workflow.
It is intentionally not installed into the PlasBench conda environment. Run a
pinned upstream release, then import its GFF3 as non-scoring evidence with:
    plasbench import-mobilome-evidence --gff sample_mobilome.gff.gz --community ID --sample ID --out results/metagenomics.mobilome_evidence.tsv
EOF
    exit 2
    ;;
 reconstruction) PKGS=(mob_suite platon);;
 # filtlong is not needed to RUN flye_mob_recon -- it is what
 # `plasbench read-quality-ladder` filters long reads with, the long-read
 # analog of the depth ladder's seqtk (which ships in 'core' for the same
 # reason). Bundled here so a user who has set themselves up for long reads
 # already has it, rather than discovering a missing binary later.
 # insilicoseq (short-read simulation) and badread (long-read simulation),
 # both real bioconda packages, for python/simulate_reads.py's simulated
 # ground-truth track (truth_source=simulated) -- see docs/COHORTS.md.
 simulate) PKGS=(insilicoseq badread);;
 long-read) PKGS=(flye mob_suite filtlong);;
 plassembler) PKGS=(plassembler);;
 hybracter) PKGS=(hybracter);;
 trycycler) PKGS=(trycycler flye medaka);;
 genomad) PKGS=(genomad);;
 rfplasmid)
    # rfplasmid is a real bioconda package (unlike plasme/plasgraph2 below),
    # and it pulls in CheckM and Jellyfish as transitive dependencies -- so
    # the package install itself is a normal one-liner. CheckM, however,
    # always needs its own ~1.4GB reference data directory configured once
    # after install, regardless of how it was installed -- this is a CheckM
    # prerequisite, not a PlasBench-managed database, so there is no
    # env/download_rfplasmid_db.sh here.
    PKGS=(rfplasmid)
    cat >&2 <<'EOF'
NOTE: rfplasmid also requires CheckM's own reference data to be set up once
      (a one-time step independent of this install, per CheckM's own docs):
          checkm data setRoot /path/to/checkm_data
      (downloading/extracting that data first if you have not already; see
      https://github.com/Ecogenomics/CheckM/wiki for the current download
      link). RFPlasmid will fail with a clear CheckM error if this is not
      done. See INSTALL.md for the full walkthrough.
EOF
    ;;
 plascope)
    # plascope is a real bioconda package -- the species-specific Centrifuge
    # database is a separate download (env/download_plascope_db.sh), not
    # something this profile installs.
    PKGS=(plascope)
    ;;
 plasmidhunter)
    # PlasmidHunter's classifier itself is a PyPI package (`pip install
    # plasmidhunter`), not a bioconda package -- only its diamond/prodigal
    # dependencies are conda packages, both already available via existing
    # profiles. Install those through the normal conda solver first, then
    # pip-install the tool itself into the SAME resolved environment prefix
    # (never a bare `pip install` on whatever's first on PATH), and exit here
    # rather than falling through to the single bottom-of-file conda install,
    # which only ever runs one solver command.
    PKGS=(diamond prodigal)
    echo "[plasbench] installing into $TARGET_LABEL: ${PKGS[*]}"
    run_with_heartbeat "Conda is solving/linking dependency tools: ${PKGS[*]}" "${SOLVER[@]}" "${PKGS[@]}"
    if [[ -n "${TARGET_PREFIX:-}" && -x "$TARGET_PREFIX/bin/pip" ]]; then
        PIP_BIN="$TARGET_PREFIX/bin/pip"
    else
        PIP_BIN="pip"
        echo "WARNING: could not resolve an existing $ENV_NAME prefix's own pip; falling back to 'pip' on PATH -- re-run this profile after the conda env above is created if that installs plasmidhunter into the wrong environment." >&2
    fi
    echo "[plasbench] installing plasmidhunter via pip ($PIP_BIN)"
    run_with_heartbeat "pip is installing plasmidhunter" "$PIP_BIN" install plasmidhunter
    exit 0
    ;;
 plasmer)
    # Plasmer is a real conda package, but published under its own custom
    # channel (not plain bioconda) -- its own README's exact install
    # command is `conda install -c iskoldt -c bioconda -c conda-forge
    # -c defaults plasmer`. This profile's own CHANNELS array (conda-forge,
    # bioconda) is not enough on its own, so -c iskoldt is prepended here
    # rather than reused from the shared SOLVER array.
    if TARGET_PREFIX="$(resolve_prefix)"; then
        SOLVER=("$SOLVER_BIN" install -y -p "$TARGET_PREFIX" -c iskoldt "${CHANNELS[@]}" -c defaults)
    else
        SOLVER=("$SOLVER_BIN" install -y -n "$ENV_NAME" -c iskoldt "${CHANNELS[@]}" -c defaults)
    fi
    PKGS=(plasmer)
    cat >&2 <<'EOF'
NOTE: Plasmer's own README states "A minimum of 32GB system memory is
      required for kmer-db to load the databases" -- this is a real,
      documented requirement, not a PlasBench-imposed default (see
      PLASMER_MEMORY_GB in config/config.sh). It also requires a pre-built
      database, downloaded separately (Zenodo/Google Drive, not bundled by
      the package) -- point PLASMER_DB at it after downloading. See
      INSTALL.md for the full walkthrough.
EOF
    ;;
 # QUAST is a real bioconda package, for the optional RUN_QUAST_DIAGNOSTICS
 # supplementary diagnostics stage (see docs/METHODS.md). `deadends`
 # (rrwick/GFA-dead-end-counter, for the separate optional
 # RUN_DIFFICULTY_FEATURES) has no bioconda package at all -- there is no
 # profile for it here; see INSTALL.md for its manual-binary install steps.
 quast) PKGS=(quast);;
 plasme)
    # PLASMe is distributed as a git checkout with its own conda env file,
    # not a bioconda package -- there is no package for this profile to
    # install, so give clear manual instructions instead (same idea as the
    # gplas case above, but there is no installable-but-wrong fallback
    # package here, so this exits rather than attempting a doomed install).
    cat >&2 <<'EOF'
NOTE: PLASMe is distributed as a git checkout with its own conda environment
      file, not a conda/bioconda package -- this profile cannot install it
      automatically. Install it manually:
          git clone https://github.com/HubertTang/PLASMe.git
          cd PLASMe && conda env create -f plasme.yaml
      then make PLASMe.py executable and available as `PLASMe.py` on PATH
      (e.g. symlink it into the plasme conda env's bin/ directory) -- the
      same manual-PATH step this project already documents for gplas2.
      Download its database once with: bash env/download_plasme_db.sh
      See INSTALL.md for the full walkthrough.
EOF
    exit 1
    ;;
 plasgraph2)
    # plASgraph2 is a git checkout with its own dependency set (TensorFlow,
    # Spektral), not a bioconda package -- same treatment as plasme above:
    # clear manual instructions, exit rather than a doomed install attempt.
    cat >&2 <<'EOF'
NOTE: plASgraph2 is distributed as a git checkout, not a conda/bioconda
      package -- this profile cannot install it automatically. Install it
      manually:
          git clone https://github.com/cchauve/plASgraph2.git
          cd plASgraph2
          conda create -n plasgraph2 python=3.8
          conda activate plasgraph2 && pip install -r requirements.txt
      then make src/plASgraph2_classify.py executable and available as
      `plASgraph2_classify.py` on PATH (e.g. symlink it into the plasgraph2
      conda env's bin/ directory) -- the same manual-PATH step this project
      already documents for gplas2/PLASMe. The pretrained model ships inside
      the checkout at model/ESKAPEE_model/ -- point PLASGRAPH2_MODEL_DIR at
      it (or your own trained model directory). No separate database
      download is needed. See INSTALL.md for the full walkthrough.
EOF
    exit 1
    ;;
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
 gplas2)
    # Kept separate from the legacy bioconda gplas package above. Calling it
    # through the registry is useful, but resolving an unpinned package named
    # "gplas2" would be an unsafe and misleading installation attempt.
    cat >&2 <<'EOF'
gplas2 is a source-distributed isolated runtime. It is registered so that
`plasbench install-tools list` and CI cannot forget it, but PlasBench will not
clone a floating branch or install an unreviewed dependency set automatically.
Use `plasbench install-tools plan` to see its verification contract, then
follow INSTALL.md's pinned-source instructions after validating the exact
gplas2 revision and its classifier-table provenance for your study.
EOF
    exit 2
    ;;
 # `all` is intentionally an orchestrator rather than a second, drifting
 # package list. Every verified automatic profile is invoked through its own
 # existing code path. Isolated-source runtimes remain visible in `plan` as
 # planned until their pin, checksum, and smoke test have been validated.
 all)
    failures=0
    # `metagenomics` is deliberately absent: its two baseline dependencies are
    # already covered by `assembly` and `genomad` below. Keeping it out avoids
    # a redundant second solver transaction during install-tools all.
    for installed_profile in core assembly reconstruction simulate long-read plassembler hybracter trycycler genomad rfplasmid plasmidhunter plasmer plascope quast annotation annotation-prokka; do
        echo "[plasbench] ===== install-tools $installed_profile ====="
        "$0" --env "$ENV_NAME" "$installed_profile" || failures=1
    done
    if [[ "$ASSUME_YES" -eq 1 ]]; then
        echo "[plasbench] Automatic package installation complete. Run 'plasbench check --yes' to install and verify databases supported by your enabled tools."
    else
        echo "[plasbench] Package installation complete. Run 'plasbench check' to review and optionally install databases for enabled tools."
    fi
    python3 "$HERE/../python/tool_installer_registry.py" plan
    exit "$failures"
    ;;
 *) PKGS=("$PROFILE");;
esac
echo "[plasbench] installing into $TARGET_LABEL: ${PKGS[*]}"
run_with_heartbeat "Conda is solving/linking dependency tools: ${PKGS[*]}" "${SOLVER[@]}" "${PKGS[@]}"
