#!/usr/bin/env bash
# Install an optional PlasBench dependency profile into an existing conda env.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../scripts/lib.sh"
ENV_NAME="plasbench"; PROFILE="core"; ASSUME_YES=0
[[ "${1:-}" == "--env" ]] && { ENV_NAME="$2"; shift 2; }
[[ "${1:-}" == "--yes" ]] && { ASSUME_YES=1; shift; }
[[ $# -gt 0 ]] && PROFILE="$1"

# Helpers shared by the profile loops (a comma list, `all`, plasbench check): an install that cannot write to its environment records why in PLASBENCH_INSTALL_STOP_FILE, and the
# loop stops instead of trying the next profile against the same prefix. Other failures (network, a solver conflict) do not stop it.
new_stop_file() {
    if [[ -z "${PLASBENCH_INSTALL_STOP_FILE:-}" ]]; then
        PLASBENCH_INSTALL_STOP_FILE="$(mktemp "${TMPDIR:-/tmp}/plasbench-stop.XXXXXX" 2>/dev/null || true)"
        [[ -n "$PLASBENCH_INSTALL_STOP_FILE" ]] && : > "$PLASBENCH_INSTALL_STOP_FILE"
        export PLASBENCH_INSTALL_STOP_FILE
    fi
}
stop_requested() { [[ -n "${PLASBENCH_INSTALL_STOP_FILE:-}" && -s "$PLASBENCH_INSTALL_STOP_FILE" ]]; }

# These inspection actions share the machine-readable registry with CI. They
# do not touch an environment, which makes them safe before any download.
case "$PROFILE" in
  list|plan|validate)
    exec python3 "$HERE/../python/tool_installer_registry.py" "$PROFILE"
    ;;
esac

# A comma-separated list (what the window's "Install all enabled tools" sends): each profile through this same script, one summary at the end. A manual step (20) and
# a wait for consent (21) are information, not failures; the exit code is 1 only when an install really failed, else 21 when something still needs consent, else 20 when
# something needs a manual step, else 0.
if [[ "$PROFILE" == *,* ]]; then
    list_failed=() list_manual=() list_consent=()
    list_yes=(); [[ "$ASSUME_YES" -eq 1 ]] && list_yes=(--yes)
    IFS=',' read -r -a LIST_PROFILES <<< "$PROFILE"
    new_stop_file
    for listed in "${LIST_PROFILES[@]}"; do
        [[ -n "$listed" ]] || continue
        # A read-only environment fails every profile the same way: say it once and never try the next one against the same prefix.
        if stop_requested; then list_failed+=("$listed"); continue; fi
        echo "[plasbench] ===== install-tools $listed ====="
        listed_status=0
        "$0" --env "$ENV_NAME" "${list_yes[@]}" "$listed" || listed_status=$?
        case "$listed_status" in
            0) ;;
            20) list_manual+=("$listed");;
            21) list_consent+=("$listed");;
            *) list_failed+=("$listed");;
        esac
    done
    [[ ${#list_manual[@]} -gt 0 ]] && echo "[plasbench] Manual step needed (nothing failed; the notices above list the steps): ${list_manual[*]}"
    [[ ${#list_consent[@]} -gt 0 ]] && echo "[plasbench] Not installed, consent needed: ${list_consent[*]}. Run again with --yes."
    if [[ ${#list_failed[@]} -gt 0 ]]; then
        echo "ERROR: these did not install: ${list_failed[*]}. The messages above say why; retry one with: plasbench install-tools <name> --yes" >&2
        exit 1
    fi
    [[ ${#list_consent[@]} -gt 0 ]] && exit 21
    [[ ${#list_manual[@]} -gt 0 ]] && exit 20
    exit 0
fi

# Docker is a container engine, not a conda package: python/docker_setup.py detects the computer (Windows, WSL2, macOS, Linux, inside a container) and the Docker state,
# then installs only where a user-level process may (winget / Homebrew: the operating system shows its own approval prompt) and prints the exact steps and scripts for the rest
# (a copyable sudo script is never run for you). It needs --yes before it starts an installer. Exit 0 = Docker verified working, 20 = steps handed to you (information),
# 21 = consent needed, 1 = failed. PLASBENCH_INSTALL_DRY_RUN=1 prints the plan; PLASBENCH_DOCKER_HELLO=1 also runs `docker run --rm hello-world` (needs the internet).
if [[ "$PROFILE" == "docker" ]]; then
    DOCKER_ARGS=(install)
    [[ "$ASSUME_YES" -eq 1 ]] && DOCKER_ARGS+=(--yes)
    [[ "${PLASBENCH_INSTALL_DRY_RUN:-0}" == "1" ]] && DOCKER_ARGS+=(--dry-run)
    [[ "${PLASBENCH_DOCKER_HELLO:-0}" == "1" ]] && DOCKER_ARGS+=(--hello-world)
    [[ "${PLASBENCH_DOCKER_START:-0}" == "1" ]] && DOCKER_ARGS+=(--start)
    [[ "${PLASBENCH_DOCKER_OPEN_INTEGRATION:-0}" == "1" ]] && DOCKER_ARGS+=(--open-integration)
    [[ -n "${PLASBENCH_DOCKER_WAIT:-}" ]] && DOCKER_ARGS+=(--wait "$PLASBENCH_DOCKER_WAIT")
    if [[ "$ASSUME_YES" -eq 1 && "${PLASBENCH_INSTALL_DRY_RUN:-0}" != "1" ]]; then
        # Only the winget / Homebrew routes go online; the services are the ones the plan says (config/network_services.tsv: winget, brew, docker).
        read -r -a DOCKER_SERVICES <<< "$(python3 "$HERE/../python/docker_setup.py" services 2>/dev/null || true)"
        [[ "${PLASBENCH_DOCKER_HELLO:-0}" == "1" ]] && DOCKER_SERVICES+=(docker)
        if [[ ${#DOCKER_SERVICES[@]} -gt 0 ]]; then
            require_internet --action "Installing Docker" --hint "Docker is installed through winget (Windows) or Homebrew (macOS), which download from the internet. Nothing was changed." "${DOCKER_SERVICES[@]}"
        fi
    fi
    exec python3 "$HERE/../python/docker_setup.py" "${DOCKER_ARGS[@]}"
fi

# What kind of profile is this? A built-in one has nothing to install (exit 0); a manual one (source checkout, container, workflow) is never
# installed for the user and is not a failure: it prints the exact steps and exits 20; an unknown name close to a real one is a usage error (exit 2)
# with the nearest names. PLASBENCH_INSTALL_DRY_RUN=1 stops here, before any solver or network, for tests and for `plasbench install-tools --dry-run`.
RESOLVE_STATUS=0
RESOLVE_TEXT="$(python3 "$HERE/../python/tool_installer_registry.py" resolve "$PROFILE" 2>&1)" || RESOLVE_STATUS=$?
case "$RESOLVE_STATUS" in
  20) echo "$RESOLVE_TEXT"; exit 20;;
  10) echo "$RESOLVE_TEXT"; exit 0;;
  0)  ;;
  *)  echo "$RESOLVE_TEXT" >&2; exit "$RESOLVE_STATUS";;
esac
if [[ "${PLASBENCH_INSTALL_DRY_RUN:-0}" == "1" ]]; then
    echo "[plasbench] dry run: '$PROFILE' would be installed by an automatic profile (no solver was started, nothing was downloaded)."
    exit 0
fi

# Source-built tools (config/source_tools.json) are installed by python/source_install.py: it shows the plan (repository, pinned commit, size, licence), asks for
# consent (--yes), checks the internet only when something must be fetched, and cleans up after a failure. Exit 20 = manual step (information), 21 = consent needed.
SOURCE_KIND="$(python3 "$HERE/../python/source_install.py" kind "$PROFILE" 2>/dev/null || true)"

# Everything below installs packages (conda channels, PyPI, GitHub): stop here, before touching the environment, when there is no internet.
[[ "$SOURCE_KIND" == "source" ]] || require_internet --action "Installing the '$PROFILE' tools" --hint "Tools that are already installed keep working offline. Install on a computer with internet, or use --local-inputs runs with the tools you have." conda pypi github

# Resolve the environment to an absolute PREFIX and install with -p, never -n.
#
# `-n NAME` means "look under this solver's own root prefix", and the solvers
# disagree about where that is: micromamba defaults to $MAMBA_ROOT_PREFIX
# (~/.local/share/mamba), while a Miniforge conda keeps envs in ~/miniforge3.
# On a machine with both -- which is exactly what env/bootstrap_conda.sh plus a
# system micromamba produces -- `micromamba install -n plasbench` aborts with
# "No prefix found at: ~/.local/share/mamba/envs/plasbench" even though the
# environment exists. An absolute prefix is unambiguous for all three solvers.
# Inside the PlasBench container the image's conda environments (/opt/conda/envs/*) belong to the image's own user and are read-only for the user the container runs as
# (the host user). Every install goes to the persistent extras folder the runtime mounts instead (PLASBENCH_EXTRA_HOME): ONE overlay environment, <extras>/envs/extras, created
# fresh with its own solve, so it neither inherits the image environment's pins nor changes its packages. The runtime puts its bin/ on PATH AFTER the image's, so the
# image's pinned tools always win and the extras only add what the image does not have.
in_container() {
    [[ "${PLASBENCH_IN_DOCKER:-}" == "1" || -f /.dockerenv || -f /run/.containerenv ]]
}
docker_mode() { in_container && [[ -n "${PLASBENCH_EXTRA_HOME:-}" ]]; }

# A failed install step names the profile and the cause, once (the ERR trap's "`return "$rc"` failed" line says nothing a person can act on).
install_step() {
    local rc=0
    run_with_heartbeat "$@" || rc=$?
    if [[ "$rc" -ne 0 ]]; then
        _PLASBENCH_ERR_REPORTED=1
        echo "ERROR: install-tools $PROFILE failed: $1 ($(explain_exit "$rc"), exit $rc). The solver's own messages are above; retry with: plasbench install-tools $PROFILE --yes" >&2
        exit "$rc"
    fi
}

# Stop BEFORE any solver runs when a prefix (or the package cache) cannot be written, instead of letting it solve for minutes and sleep-retry on "Permission denied".
# A failure of this kind also tells the profile loops to stop (see new_stop_file).
guard_writable() {
    local prefix="$1" bad="" cache d
    if [[ -d "$prefix" ]]; then
        [[ -w "$prefix" && ( ! -d "$prefix/conda-meta" || -w "$prefix/conda-meta" ) ]] || bad="$prefix"
    else
        d="$(dirname "$prefix")"; [[ -d "$d" ]] || d="$(dirname "$d")"
        [[ -w "$d" ]] || bad="$prefix"
    fi
    if [[ -z "$bad" && -n "${CONDA_PKGS_DIRS:-}" ]]; then
        cache="${CONDA_PKGS_DIRS%%:*}"
        if [[ -d "$cache" ]]; then [[ -w "$cache" ]] || bad="$cache"; else mkdir -p "$cache" 2>/dev/null || bad="$cache"; fi
    fi
    [[ -z "$bad" ]] && return 0
    if in_container; then
        echo "ERROR: this environment is read-only for your user ($bad). The image's conda environments cannot be changed from a container; in Docker mode PlasBench installs into ${PLASBENCH_EXTRA_HOME:-the extras folder (~/.plasbench/docker/<version>/extras)} instead." >&2
        echo "       This install tried to write to $bad. Nothing was changed. Update PlasBench to a version that installs extras there, and see INSTALL.md (Docker mode: where extras live)." >&2
    else
        echo "ERROR: this environment is read-only for your user ($bad), so nothing can be installed into it. Use an environment you own (bash env/setup_conda.sh) or ask whoever owns it." >&2
    fi
    [[ -n "${PLASBENCH_INSTALL_STOP_FILE:-}" ]] && printf 'read-only %s\n' "$bad" >> "$PLASBENCH_INSTALL_STOP_FILE" 2>/dev/null || true
    return 1
}

if docker_mode; then
    # The solver's own root, package cache, environment list and lock files all live in the extras folder (HOME is a writable scratch folder in the container).
    export MAMBA_ROOT_PREFIX="$PLASBENCH_EXTRA_HOME/mamba" CONDA_PKGS_DIRS="$PLASBENCH_EXTRA_HOME/pkgs" CONDA_ENVS_PATH="$PLASBENCH_EXTRA_HOME/envs"
    mkdir -p "$MAMBA_ROOT_PREFIX" "$CONDA_PKGS_DIRS" "$PLASBENCH_EXTRA_HOME/envs" "$PLASBENCH_EXTRA_HOME/bin" 2>/dev/null || true
    [[ -n "${HOME:-}" && -w "${HOME:-/nonexistent}" ]] || { export HOME="$PLASBENCH_EXTRA_HOME/home"; mkdir -p "$HOME" 2>/dev/null || true; }
fi

resolve_prefix() {
    if docker_mode; then
        printf '%s' "$PLASBENCH_EXTRA_HOME/envs/extras"; return 0
    fi
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

# A user-declared tool (python/user_tools.py; docs/ADDING_TOOLS.md) installs into its own environment from its
# manifest's [install] section, then runs its verify_command there. Built-in profile names never reach this branch:
# a manifest may not reuse one.
# A user tool's plan always starts with an "ENV<TAB>name" line; anything else (an error, no output) means the profile
# is not a user tool and falls through to the built-in profiles below.
USER_PLAN="$(python3 "$HERE/../python/user_tools.py" install-plan "$PROFILE" 2>/dev/null || true)"
if [[ "$USER_PLAN" == ENV$'\t'* ]]; then
    echo "Installing user tool '$PROFILE' (manifest: $(python3 "$HERE/../python/user_tools.py" list | awk -F'\t' -v t="$PROFILE" '$1 == t {print $8}'))"
    USER_ENV=""
    while IFS=$'\t' read -r -a STEP; do
        [[ ${#STEP[@]} -gt 0 ]] || continue
        STEP=("${STEP[@]%$'\r'}")
        # ENV names the tool's own environment ([install] env_name); VERIFY runs there, or on PATH for method = none.
        if [[ "${STEP[0]}" == "ENV" ]]; then USER_ENV="${STEP[1]}"; continue; fi
        if [[ "${STEP[0]}" == "VERIFY" ]]; then
            echo "  verify: ${STEP[1]}"
            "$SOLVER_BIN" run -n "$USER_ENV" bash -c "${STEP[1]}" >/dev/null 2>&1 || bash -c "${STEP[1]}" >/dev/null 2>&1 \
                || { echo "ERROR: '${STEP[1]}' failed after installing $PROFILE" >&2; exit 1; }
            continue
        fi
        # BUILD runs a url/local tool's build_command inside its source folder (STEP[2]), in the tool's environment when it has one.
        if [[ "${STEP[0]}" == "BUILD" ]]; then
            echo "  build in ${STEP[2]}: ${STEP[1]}"
            BUILD_RUN=(bash -c "${STEP[1]}")
            "$SOLVER_BIN" env list 2>/dev/null | awk '{print $1}' | grep -qx "$USER_ENV" && BUILD_RUN=("$SOLVER_BIN" run -n "$USER_ENV" bash -c "${STEP[1]}")
            ( cd "${STEP[2]}" && "${BUILD_RUN[@]}" ) || { echo "ERROR: build_command failed in ${STEP[2]}" >&2; exit 1; }
            continue
        fi
        [[ "${STEP[0]}" == "{CONDA}" ]] && STEP[0]="$SOLVER_BIN"
        echo "  + ${STEP[*]}"
        "${STEP[@]}"
    done <<< "$USER_PLAN"
    echo "Installed user tool '$PROFILE'. Run it with: plasbench run --tool $PROFILE"
    exit 0
fi

CHANNELS=(-c conda-forge -c bioconda)
if docker_mode && TARGET_PREFIX="$(resolve_prefix)"; then
    # Own, fresh solve (never the image environment's pins). An empty environment is made once; a pinned-packages file of the image is not copied.
    guard_writable "$TARGET_PREFIX" || exit 1
    if [[ ! -d "$TARGET_PREFIX/conda-meta" ]]; then
        echo "[plasbench] creating the extras environment: $TARGET_PREFIX (the image's environments are read-only and are not changed)"
        "$SOLVER_BIN" create -y -p "$TARGET_PREFIX" "${CHANNELS[@]}" || { echo "ERROR: could not create the extras environment $TARGET_PREFIX" >&2; exit 1; }
    fi
fi
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

if [[ "$SOURCE_KIND" == "source" ]]; then
    SOURCE_ARGS=(--env-name "$ENV_NAME" --solver "$SOLVER_BIN")
    [[ -n "${TARGET_PREFIX:-}" ]] && SOURCE_ARGS+=(--main-prefix "$TARGET_PREFIX")
    [[ "$ASSUME_YES" -eq 1 ]] && SOURCE_ARGS+=(--yes)
    SOURCE_STATUS=0
    python3 "$HERE/../python/source_install.py" install "$PROFILE" "${SOURCE_ARGS[@]}" || SOURCE_STATUS=$?
    exit "$SOURCE_STATUS"
fi

# MOB-suite pins pandas<=1.5.3 and numpy<1.23.5, which cannot co-exist with the
# modern pandas of the main environment. Solved into it, mob_recon installs but
# crashes at start ("cannot import name 'EmptyDataError' from
# 'pandas.io.common'", or later "unexpected keyword argument 'line_terminator'"),
# and every run then scores 0. So mob_suite is always installed into its own
# environment, <env>-mobsuite, with the same pins as the Dockerfile, and exposed
# in the main environment's bin/ through thin wrappers. scripts/lib.sh's
# mobsuite_db_dir follows a wrapper to the real installation's database.
MOBSUITE_SPEC=("mob_suite=3.1.9" "python=3.10" "pandas<=1.5.3" "numpy<1.23.5" "blast>=2.9.0,<2.16.0" "mash>=2.0")
MOBSUITE_COMMANDS=(mob_recon mob_typer mob_cluster mob_init)

# write_wrappers MAIN_PREFIX TOOL_PREFIX LABEL CMD...: thin scripts in the main
# environment's bin/ that run CMD from TOOL_PREFIX, with that environment's bin/
# first on PATH so the tool finds its own helpers (blast, centrifuge, diamond...).
write_wrappers() {
    local main_prefix="$1" tool_prefix="$2" label="$3" cmd; shift 3
    mkdir -p "$main_prefix/bin"
    for cmd in "$@"; do
        rm -f "$main_prefix/bin/$cmd"
        { echo '#!/bin/sh'
          echo "# PlasBench wrapper: $label runs from its own pinned environment (env/install_tools.sh)."
          echo "PATH=\"$tool_prefix/bin:\$PATH\""
          echo 'export PATH'
          echo "exec \"$tool_prefix/bin/$cmd\" \"\$@\""; } > "$main_prefix/bin/$cmd"
        chmod 0755 "$main_prefix/bin/$cmd"
    done
    echo "[plasbench] $label wrappers installed in $main_prefix/bin ($*)"
}

# Tools whose Python cannot share the main environment's (python 3.12) get their
# own environment, <env>-<suffix>, exposed through wrappers like MOB-suite:
#   plascope       needs centrifuge 1.0.3, built only for python <= 3.6
#   plasmer        published for python 3.10 only (channel iskoldt)
#   plasmidhunter  its PyPI releases require python ==3.10.*
# Each was a hard solver/pip failure inside the main environment.
# install_isolated SUFFIX LABEL "COMMANDS" "PIP_PKG" "PROBE" CHANNEL_ARGS... -- SPEC...
# PROBE (optional) is a command line run inside the environment to prove the tool
# starts, not merely that its file exists. The environment is reused when every
# command is present and the probe passes; otherwise it is (re)created.
# Gigabytes of memory (free RAM plus free swap) this computer has for a large solve, or empty when unknown.
available_memory_gb() {
    awk '/^(MemAvailable|SwapFree):/ {kb += $2} END {if (kb > 0) printf "%d", kb / 1048576}' /proc/meminfo 2>/dev/null || true
}

# Say how to give WSL more memory; a solve killed by the kernel (exit 137) is almost always this.
memory_advice() {
    cat >&2 <<'EOF'
  What to do: the machine ran out of memory while Conda solved this environment. Close other programs and retry,
  or give more memory to WSL. In Windows, create or edit  C:\Users\<you>\.wslconfig  with
      [wsl2]
      memory=8GB
      swap=8GB
  then run  wsl --shutdown  in PowerShell, reopen Ubuntu, and run the same install-tools command again.
EOF
}

install_isolated() {
    local suffix="$1" label="$2" cmds="$3" pip_pkg="$4" probe="$5" main_prefix iso_prefix cmd ok=1
    shift 5
    local channels=() spec=()
    while [[ $# -gt 0 && "$1" != "--" ]]; do channels+=("$1"); shift; done
    [[ $# -gt 0 ]] && shift
    spec=("$@")
    main_prefix="${TARGET_PREFIX:-}"
    if [[ -z "$main_prefix" ]]; then
        echo "ERROR: main environment '$ENV_NAME' not found; create it first (bash env/setup_conda.sh), then re-run: bash env/install_tools.sh $PROFILE" >&2
        return 1
    fi
    iso_prefix="$(dirname "$main_prefix")/${ENV_NAME}-$suffix"
    for cmd in $cmds; do [[ -x "$iso_prefix/bin/$cmd" ]] || ok=0; done
    if [[ "$ok" -eq 1 && -n "$probe" ]]; then
        PATH="$iso_prefix/bin:$PATH" bash -c "$probe" >/dev/null 2>&1 || ok=0
    fi
    if [[ "$ok" -eq 1 ]]; then
        echo "[plasbench] $label environment already present: $iso_prefix"
    else
        echo "[plasbench] creating the $label environment (separate from the main one): $iso_prefix"
        local need="${ISOLATED_MIN_GB:-0}" have
        have="$(available_memory_gb)"
        if [[ -n "$have" && "$need" -gt 0 && "$have" -lt "$need" ]]; then
            echo "[plasbench] WARNING: only about ${have} GB of memory (RAM plus swap) is free and solving $label needs about ${need} GB;" >&2
            echo "[plasbench]          it may be killed. If it is, the rest of PlasBench is unaffected." >&2
            memory_advice
        fi
        guard_writable "$iso_prefix" && guard_writable "$main_prefix" || return 1
        install_step "Conda is solving/linking $label's own environment" \
            "$SOLVER_BIN" create -y -p "$iso_prefix" "${channels[@]}" "${spec[@]}"
        if [[ -n "$pip_pkg" ]]; then
            install_step "pip is installing $pip_pkg into $iso_prefix" "$iso_prefix/bin/pip" install "$pip_pkg"
        fi
    fi
    for cmd in $cmds; do
        [[ -x "$iso_prefix/bin/$cmd" ]] || { echo "ERROR: $cmd is missing from $iso_prefix after install" >&2; return 1; }
    done
    if [[ -n "$probe" ]] && ! PATH="$iso_prefix/bin:$PATH" bash -c "$probe" >/dev/null 2>&1; then
        echo "ERROR: $label does not start in $iso_prefix ($probe):" >&2
        PATH="$iso_prefix/bin:$PATH" bash -c "$probe" 2>&1 | tail -5 >&2
        return 1
    fi
    # shellcheck disable=SC2086
    write_wrappers "$main_prefix" "$iso_prefix" "$label" $cmds
}

install_mobsuite() {
    local main_prefix="$1" mob_prefix cmd
    mob_prefix="$(dirname "$main_prefix")/${ENV_NAME}-mobsuite"
    if [[ -x "$mob_prefix/bin/mob_recon" ]] && "$mob_prefix/bin/mob_recon" --version >/dev/null 2>&1; then
        echo "[plasbench] MOB-suite environment already works: $mob_prefix"
    else
        echo "[plasbench] creating the MOB-suite environment (pinned, separate from the main one): $mob_prefix"
        guard_writable "$mob_prefix" && guard_writable "$main_prefix" || return 1
        install_step "Conda is solving/linking MOB-suite's own environment" \
            "$SOLVER_BIN" create -y -p "$mob_prefix" "${CHANNELS[@]}" "${MOBSUITE_SPEC[@]}"
    fi
    "$mob_prefix/bin/mob_recon" --version >/dev/null 2>&1 \
        || { echo "ERROR: mob_recon in $mob_prefix does not start" >&2; return 1; }
    write_wrappers "$main_prefix" "$mob_prefix" MOB-suite "${MOBSUITE_COMMANDS[@]}"
    # Reuse a database kept in the machine store (env/preserve_databases.sh) rather than downloading it.
    PATH="$main_prefix/bin:$PATH" bash -c 'source "$0/../config/config.sh"; source "$0/../scripts/lib.sh"; mobsuite_db_preserve' "$HERE" || true
    echo "[plasbench] its database is fetched by: bash env/download_mobsuite_db.sh"
}

case "$PROFILE" in
 mobsuite) PKGS=(mob_suite);;
 locked) LOCK="$HERE/environment.lock.yml"; grep -q '^@EXPLICIT$' "$LOCK" || { echo "ERROR: $LOCK is not a Conda @EXPLICIT lock. Regenerate with: bash env/lock_environment.sh" >&2; exit 2; }; mapfile -t LOCKED_PKGS < <(awk '!/^(@|#|$)/ {print}' "$LOCK"); "${CREATE[@]}" "${LOCKED_PKGS[@]}"; exit;;
 core) PKGS=(ncbi-datasets-cli sra-tools fastp minimap2 seqtk unzip);;
 assembly) PKGS=(spades unicycler);;
 # The executable metagenomic scorer consumes graph/bin tables produced by
 # adapters. SPAdes supplies metaSPAdes and geNomad supplies a transparent
 # contig-classification baseline. Graph deconvolution tools with unpinned
 # upstream runtimes are intentionally not claimed as installed here.
 metagenomics) PKGS=(spades genomad);;
# Profiles whose runtime is built from a pinned source checkout (gplas2, plasme, plasgraph2, plasmidec, plasbin_flow, mobilome-map) are installed by the source-install
# branch above (python/source_install.py, config/source_tools.json); the ones no pinned source can supply (plsmd, ppr-meta) print their verified recipe and exit 20.
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
 trycycler)
    # Medaka brings a PyTorch stack. Solved into the large main environment,
    # conda searched for 45+ minutes without finishing; in a fresh environment
    # the same three packages solve in seconds. So Trycycler and Medaka get
    # their own environment. Flye is included there for Trycycler's own use,
    # but is not wrapped: the long-read profile installs flye into the main
    # environment and that copy is left alone.
    ISOLATED_MIN_GB=8 install_isolated trycycler Trycycler "trycycler medaka medaka_consensus" "" "trycycler --version" \
        -c conda-forge -c bioconda -- trycycler flye medaka
    exit $?
    ;;
 genomad) PKGS=(genomad);;
 rfplasmid)
    # rfplasmid is a real bioconda package (unlike plasme/plasgraph2 below),
    # and it pulls in CheckM and Jellyfish as transitive dependencies -- so
    # the package install itself is a normal one-liner. CheckM, however,
    # always needs its own ~1.4GB reference data directory configured once
    # after install, regardless of how it was installed -- this is a CheckM
    # prerequisite, not a PlasBench-managed database, so there is no
    # env/download_rfplasmid_db.sh here.
    # CheckM imports pkg_resources, which setuptools 81 removed: without the
    # pin every `checkm` (and so every RFPlasmid run) dies at import.
    PKGS=(rfplasmid "setuptools<81")
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
    # something this profile installs. Its pinned centrifuge 1.0.3 exists only
    # for python <= 3.6, so it gets its own environment (see install_isolated).
    install_isolated plascope PlaScope "plaScope.sh centrifuge" "" "centrifuge --version" \
        -c conda-forge -c bioconda -- "plascope=1.3.1" "python=3.6"
    exit $?
    ;;
 plasmidhunter)
    # PlasmidHunter's classifier is a PyPI package; its diamond/prodigal
    # dependencies are conda packages. Every PyPI release requires python
    # ==3.10.*, so pip cannot install it into the python 3.12 main environment
    # ("No matching distribution found"). It gets its own python 3.10
    # environment: conda solves the dependencies, then that environment's own
    # pip installs the pinned release. PlasmidHunter 1.4 imports pkg_resources,
    # which setuptools 81 removed, so setuptools is held below 81 and the
    # install is proven by actually starting the program.
    install_isolated plasmidhunter PlasmidHunter "plasmidhunter" "plasmidhunter==1.4" "plasmidhunter --help" \
        -c conda-forge -c bioconda -- "python=3.10" diamond prodigal pip "setuptools<81"
    exit $?
    ;;
 plasmer)
    # Plasmer is a real conda package, but published under its own custom
    # channel (not plain bioconda) -- its own README's exact install
    # command is `conda install -c iskoldt -c bioconda -c conda-forge
    # -c defaults plasmer`. Its only build is for python 3.10, which conflicts
    # with the main environment's python 3.12, so it gets its own environment.
    # The commercial 'defaults' channel is not needed to solve it (iskoldt,
    # bioconda and conda-forge suffice), so it is left out.
    cat >&2 <<'EOF'
NOTE: Plasmer's own README states "A minimum of 32GB system memory is
      required for kmer-db to load the databases" -- this is a real,
      documented requirement, not a PlasBench-imposed default (see
      PLASMER_MEMORY_GB in config/config.sh). It also requires a pre-built
      database, downloaded separately (Zenodo/Google Drive, not bundled by
      the package) -- point PLASMER_DB at it after downloading. See
      INSTALL.md for the full walkthrough.
EOF
    install_isolated plasmer Plasmer "Plasmer" "" "" \
        -c iskoldt -c bioconda -c conda-forge -- plasmer "python=3.10"
    exit $?
    ;;
 # QUAST is a real bioconda package, for the optional RUN_QUAST_DIAGNOSTICS
 # supplementary diagnostics stage (see docs/METHODS.md). `deadends`
 # (rrwick/GFA-dead-end-counter, for the separate optional
 # RUN_DIFFICULTY_FEATURES) has no bioconda package at all -- there is no
 # profile for it here; see INSTALL.md for its manual-binary install steps.
 quast) PKGS=(quast);;
 multiqc)
    # Optional companion to the report's own QC panel (MULTIQC_REPORT, python/run_multiqc.py). Own environment, like the other tools with their own
    # dependency set, so its Python and plotting libraries never touch the main one; pinned so the report it draws does not drift between installs.
    install_isolated multiqc MultiQC "multiqc" "" "multiqc --version"         -c conda-forge -c bioconda -- "multiqc=1.25.2" "python=3.11"
    exit $?
    ;;
 # Shared utilities used by default or opt-in stages, which no profile installed before:
 #   mash     clonal grouping (stage 6), the truth-evidence plasmid sketch, difficulty
 #            features and the reference-set build
 #   samtools difficulty features (RUN_DIFFICULTY_FEATURES)
 #   barrnap  rRNA genes, the chromosomal evidence used to label truth replicons
 # They are all in env/environment.yml too; this profile is for an environment built another way.
 utilities) PKGS=(mash samtools barrnap);;
 # Callers of the default reference-annotation stage (python/annotate_reference.py). An absent
 # caller is recorded as not_evaluated for its feature class and never as "no such feature", so
 # these are advisory, but without them replicon, AMR and insertion-sequence context is empty.
 # mob_suite supplies mob_typer; barrnap is in the 'utilities' profile above.
 reference-annotation)
    # fastcluster is pinned below 1.3: 1.3.0 is built for NumPy 2 and breaks ISEScan's clustering step ("NoneType copy mode not allowed") beside NumPy 1.x, after minutes of work.
    PKGS=(abricate ncbi-amrfinderplus isescan "fastcluster<1.3" mob_suite)
    AMRFINDER_DB_AFTER=1
    cat >&2 <<'EOF'
NOTE: ncbi-amrfinderplus needs its reference database fetched once after install:
          amrfinder -u
      abricate ships its own databases. See INSTALL.md section 8.
EOF
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
         For RUN_GPLAS2_MOB / RUN_GPLAS2_EXTERNAL use the gplas2 profile
         instead (plasbench install-tools gplas2 --yes): a pinned gplas2
         checkout whose `gplas --help` is verified to list -P. gplas2 also requires ASSEMBLER=unicycler, because
         SPAdes contig ids never match its GFA segment ids.
EOF
    PKGS=(gplas);;
 # `all` is intentionally an orchestrator rather than a second, drifting
 # package list. Every verified automatic profile is invoked through its own
 # existing code path. Isolated-source runtimes remain visible in `plan` as
 # planned until their pin, checksum, and smoke test have been validated.
 all)
    failures=0
    # The profiles every benchmark needs. Every other profile is an optional tool: if it cannot install (a large
    # solve killed for memory, a tool whose channel is unavailable) it is reported with how to retry, and the rest
    # of PlasBench is still installed and usable.
    required_profiles=" core assembly mobsuite reconstruction "
    failed_optional=() manual_profiles=() consent_profiles=() oom=0
    ALL_YES=(); [[ "$ASSUME_YES" -eq 1 ]] && ALL_YES=(--yes)
    # `metagenomics` is deliberately absent: its two baseline dependencies are
    # already covered by `assembly` and `genomad` below. Keeping it out avoids
    # a redundant second solver transaction during install-tools all.
    ALL_PROFILES="core assembly mobsuite reconstruction simulate long-read plassembler hybracter trycycler genomad rfplasmid plasmidhunter plasmer plascope quast utilities reference-annotation annotation annotation-prokka gplas2 plasme plasgraph2 plasmidec plasbin_flow mobilome-map"
    # shellcheck disable=SC2086
    new_stop_file
    for installed_profile in ${PLASBENCH_ALL_PROFILES:-$ALL_PROFILES}; do
        if stop_requested; then
            [[ "$required_profiles" == *" $installed_profile "* ]] && failures=1
            failed_optional+=("$installed_profile"); continue
        fi
        echo "[plasbench] ===== install-tools $installed_profile ====="
        profile_status=0
        "$0" --env "$ENV_NAME" "${ALL_YES[@]}" "$installed_profile" || profile_status=$?
        if [[ "$profile_status" -eq 20 ]]; then
            manual_profiles+=("$installed_profile")      # information, not a failure: the notice above says what to do by hand
        elif [[ "$profile_status" -eq 21 ]]; then
            consent_profiles+=("$installed_profile")     # a source-built tool is only installed with your consent (--yes)
        elif [[ "$profile_status" -ne 0 ]]; then
            if [[ "$required_profiles" == *" $installed_profile "* ]]; then
                failures=1
            else
                failed_optional+=("$installed_profile")
                [[ "$profile_status" -eq 137 ]] && oom=1
            fi
        fi
    done
    if [[ ${#failed_optional[@]} -gt 0 ]]; then
        echo "[plasbench] WARNING: these optional tools were not installed: ${failed_optional[*]}" >&2
        echo "[plasbench] The rest of PlasBench is installed and works. Retry one with:  plasbench install-tools <name>" >&2
        [[ "$oom" -eq 1 ]] && memory_advice
    fi
    [[ ${#manual_profiles[@]} -gt 0 ]] && echo "[plasbench] These need a manual step (nothing failed; the notices above list the steps): ${manual_profiles[*]}"
    [[ ${#consent_profiles[@]} -gt 0 ]] && echo "[plasbench] These were not installed because they build from a pinned source checkout and need your consent: ${consent_profiles[*]}. Run:  plasbench install-tools all --yes"
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
# mob_suite never goes into the main environment (see install_mobsuite above).
NEEDS_MOBSUITE=0 OTHER_PKGS=()
for pkg in "${PKGS[@]}"; do
    if [[ "$pkg" == "mob_suite" ]]; then NEEDS_MOBSUITE=1; else OTHER_PKGS+=("$pkg"); fi
done
if [[ ${#OTHER_PKGS[@]} -gt 0 ]]; then
    echo "[plasbench] installing into $TARGET_LABEL: ${OTHER_PKGS[*]}"
    [[ -z "${TARGET_PREFIX:-}" ]] || guard_writable "$TARGET_PREFIX" || exit 1
    install_step "Conda is solving/linking dependency tools: ${OTHER_PKGS[*]}" "${SOLVER[@]}" "${OTHER_PKGS[@]}"
fi
if [[ "$NEEDS_MOBSUITE" -eq 1 ]]; then
    TARGET_PREFIX="${TARGET_PREFIX:-$(resolve_prefix || true)}"
    if [[ -n "$TARGET_PREFIX" ]]; then
        install_mobsuite "$TARGET_PREFIX"
    else
        # No main environment to put wrappers in: still create MOB-suite's own
        # environment by name, and say how to finish once the main one exists.
        echo "[plasbench] main environment '$ENV_NAME' not found; creating ${ENV_NAME}-mobsuite on its own"
        install_step "Conda is solving/linking MOB-suite's own environment" \
            "$SOLVER_BIN" create -y -n "${ENV_NAME}-mobsuite" "${CHANNELS[@]}" "${MOBSUITE_SPEC[@]}"
        echo "[plasbench] after creating '$ENV_NAME' (bash env/setup_conda.sh), run: bash env/install_tools.sh mobsuite" >&2
        exit 1
    fi
fi

# AMRFinderPlus needs its reference database once per machine (about 100 MB, from the internet). Without it every annotation fails in 0 s. Fetched here, after the
# package install the user already agreed to, never in Docker mode's image: there it goes to the persistent databases folder (PLASBENCH_DB_DIR/amrfinder), which
# annotate_reference.py then passes to amrfinder with -d. PLASBENCH_SKIP_AMRFINDER_DB=1 skips it (an offline machine).
if [[ "${AMRFINDER_DB_AFTER:-0}" -eq 1 ]]; then
    ENVBIN=""
    [[ -n "${TARGET_PREFIX:-}" ]] && ENVBIN="$TARGET_PREFIX/bin"
    AMR_EXE="$(PATH="${ENVBIN:+$ENVBIN:}$PATH" command -v amrfinder || true)"
    if [[ -z "$AMR_EXE" ]]; then
        echo "[plasbench] amrfinder is not on PATH after the install; fetch its database later with: amrfinder -u" >&2
    elif [[ "${PLASBENCH_SKIP_AMRFINDER_DB:-0}" == "1" ]]; then
        echo "[plasbench] skipping the AMRFinderPlus database (PLASBENCH_SKIP_AMRFINDER_DB=1); fetch it later with: amrfinder -u" >&2
    elif PATH="${ENVBIN:+$ENVBIN:}$PATH" python3 -I "$HERE/../python/tool_readiness.py" amrfinder > /dev/null 2>&1; then
        echo "[plasbench] the AMRFinderPlus database is already installed"
    else
        echo "[plasbench] fetching the AMRFinderPlus database (about 100 MB, needs the internet) ..."
        AMR_UPDATE=("$AMR_EXE" -u)
        if [[ "${PLASBENCH_IN_DOCKER:-0}" == "1" ]]; then
            AMR_DB_HOME="${PLASBENCH_DB_DIR:-$HOME/.plasbench/databases}/amrfinder"
            mkdir -p "$AMR_DB_HOME" && AMR_UPDATE=("$AMR_EXE" -u -d "$AMR_DB_HOME")
        fi
        if PATH="${ENVBIN:+$ENVBIN:}$PATH" "${AMR_UPDATE[@]}"; then
            echo "[plasbench] AMRFinderPlus database installed"
        else
            echo "[plasbench] WARNING: the AMRFinderPlus database could not be fetched (network?). Annotation will skip AMRFinder (recorded as not evaluated) until you run: amrfinder -u" >&2
        fi
    fi
fi
