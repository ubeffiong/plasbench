#!/usr/bin/env bash
# Stage 0 — create directories, check that required tools and databases are
# installed, and (interactively, or with --yes) offer to install whatever is
# missing: a conda-family manager if none exists, the install-tools profile
# that provides a missing binary, and any missing tool database (Platon,
# MOB-suite, Bakta).
#
# Usage: bash scripts/00_setup.sh [-y|--yes]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

ASSUME_YES=0
[[ "${1:-}" == "-y" || "${1:-}" == "--yes" ]] && ASSUME_YES=1

log "Project root: $PROJECT_ROOT"
mkdir -p "$DATA_DIR" "$RESULTS_DIR" "$LOG_DIR" "$TMP_DIR"

CORE_OK=1
declare -A NEEDED_PROFILES=()      # install-tools profile -> 1, for every gap it would fix
UNFIXABLE=()                       # human-readable notes for gaps install-tools cannot fix
NEED_CONDA=0
NEED_PLATON_DB=0
NEED_MOBSUITE_DB=0
NEED_BAKTA_DB=0

for candidate in micromamba mamba conda; do
    have "$candidate" && { CONDA_TOOL="$candidate"; break; }
done
if [[ -n "${CONDA_TOOL:-}" ]]; then
    log "Checking for a conda-family package manager... [ok] $CONDA_TOOL"
else
    warn "Checking for a conda-family package manager... [MISS] none of micromamba/mamba/conda found"
    NEED_CONDA=1
    CORE_OK=0
fi

# check_tool BINARY PROFILE_OR_EMPTY [REQUIRED=1]
# Always returns 0: every call site below is a bare top-level statement (not
# guarded by if/&&/||), and this function's job is purely to log and record
# the gap via NEEDED_PROFILES/UNFIXABLE/CORE_OK -- a nonzero return here
# would make set -e treat "tool is missing" as a script-aborting error.
check_tool() {
    local binary="$1" profile="$2" required="${3:-1}"
    if have "$binary"; then
        log "  [ok]   $binary"
        return 0
    fi
    if [[ "$required" -eq 1 ]]; then
        warn "  [MISS] $binary"
        CORE_OK=0
    else
        warn "  [MISS] $binary (optional)"
    fi
    if [[ -n "$profile" ]]; then
        NEEDED_PROFILES["$profile"]=1
    else
        UNFIXABLE+=("$binary: not installable via 'plasbench install-tools'; see INSTALL.md")
    fi
    return 0
}

log "Checking core dependencies..."
check_tool datasets core
check_tool prefetch core
check_tool fasterq-dump core
check_tool fastp core
check_tool minimap2 core
# unzip/python3 ship with the base plasbench env (env/environment.yml), not a
# separate install-tools profile: the fix is re-running env/setup_conda.sh.
check_tool unzip "" 1
check_tool python3 "" 1

if [[ "${RUN_PLASMIDSPADES:-0}" -eq 1 ]]; then
    check_tool plasmidspades.py assembly
fi
if [[ "$ASSEMBLER" == "spades" ]]; then
    check_tool spades.py assembly
elif [[ "$ASSEMBLER" == "unicycler" ]]; then
    check_tool unicycler assembly
fi

log "Checking optional plasmid reconstruction tools (only those switched on in config)..."
if [[ "${RUN_MOB_RECON:-0}" -eq 1 ]]; then
    have mob_recon && log "  [ok]   mob_recon" || { warn "  [MISS] mob_recon (RUN_MOB_RECON=1)"; NEEDED_PROFILES["reconstruction"]=1; }
fi
if [[ "${RUN_PLATON:-0}" -eq 1 ]]; then
    have platon && log "  [ok]   platon" || { warn "  [MISS] platon (RUN_PLATON=1)"; NEEDED_PROFILES["reconstruction"]=1; }
fi
if [[ "${RUN_GPLAS2_MOB:-0}" -eq 1 ]]; then
    have gplas && log "  [ok]   gplas (gplas2_mob)" || { warn "  [MISS] gplas (RUN_GPLAS2_MOB=1)"; NEEDED_PROFILES["gplas"]=1; }
fi
if [[ "${RUN_GPLAS2_EXTERNAL:-0}" -eq 1 ]]; then
    have gplas && log "  [ok]   gplas (gplas2_external)" || { warn "  [MISS] gplas (RUN_GPLAS2_EXTERNAL=1)"; NEEDED_PROFILES["gplas"]=1; }
fi
if [[ "${RUN_FLYE_MOB_RECON:-0}" -eq 1 ]]; then
    check_tool flye long-read
fi
if [[ "${RUN_PROTEIN_ANNOTATION:-0}" -eq 1 ]]; then
    if [[ "$PROTEIN_ANNOTATION_ENGINE" == "bakta" ]]; then
        check_tool bakta annotation
    elif [[ "$PROTEIN_ANNOTATION_ENGINE" == "prokka" ]]; then
        check_tool prokka annotation-prokka
    fi
fi

if [[ "${RUN_PLATON:-0}" -eq 1 ]]; then
    if [[ -d "$PLATON_DB" ]] && [[ -n "$(ls -A "$PLATON_DB" 2>/dev/null)" ]]; then
        log "  [ok]   Platon DB at $PLATON_DB"
    else
        warn "  [MISS] Platon DB not found at $PLATON_DB"
        NEED_PLATON_DB=1; CORE_OK=0
    fi
fi
if [[ "${RUN_MOB_RECON:-0}" -eq 1 || "${RUN_GPLAS2_MOB:-0}" -eq 1 ]] && have mob_init; then
    # mob_init's database lives inside the installed package with no fixed,
    # externally-predictable path to check for -- mob_init itself is the
    # authoritative, idempotent check (see env/download_mobsuite_db.sh).
    NEED_MOBSUITE_DB=1
fi
if [[ "${RUN_PROTEIN_ANNOTATION:-0}" -eq 1 && "$PROTEIN_ANNOTATION_ENGINE" == "bakta" ]]; then
    if [[ -n "${PROTEIN_ANNOTATION_DATABASE:-}" && -s "$PROTEIN_ANNOTATION_DATABASE/version.json" ]]; then
        log "  [ok]   Bakta DB at $PROTEIN_ANNOTATION_DATABASE"
    elif [[ -n "${PROTEIN_ANNOTATION_DATABASE:-}" ]]; then
        warn "  [MISS] Bakta DB not found at $PROTEIN_ANNOTATION_DATABASE"
        NEED_BAKTA_DB=1
    else
        warn "  [MISS] PROTEIN_ANNOTATION_DATABASE is not set"
        NEED_BAKTA_DB=1
    fi
fi

NOTHING_MISSING=0
[[ "$CORE_OK" -eq 1 && ${#NEEDED_PROFILES[@]} -eq 0 && "$NEED_PLATON_DB" -eq 0 \
    && "$NEED_MOBSUITE_DB" -eq 0 && "$NEED_BAKTA_DB" -eq 0 ]] && NOTHING_MISSING=1

echo
if [[ "$NOTHING_MISSING" -eq 1 ]]; then
    log "Core dependency check PASSED."
    exit 0
fi

warn "Some dependencies are missing."
FIXABLE=0
[[ "$NEED_CONDA" -eq 1 || ${#NEEDED_PROFILES[@]} -gt 0 || "$NEED_PLATON_DB" -eq 1 || "$NEED_MOBSUITE_DB" -eq 1 || "$NEED_BAKTA_DB" -eq 1 ]] && FIXABLE=1

if [[ "$FIXABLE" -eq 0 ]]; then
    for note in "${UNFIXABLE[@]:-}"; do [[ -n "$note" ]] && warn "  $note"; done
    warn "Install the missing item(s) above (see INSTALL.md) before running the full pipeline."
    exit 1
fi

echo "The following can be installed automatically:"
[[ "$NEED_CONDA" -eq 1 ]] && echo "  - a conda-family package manager (Miniforge)"
for profile in "${!NEEDED_PROFILES[@]}"; do echo "  - install-tools profile: $profile"; done
[[ "$NEED_PLATON_DB" -eq 1 ]] && echo "  - the Platon database (needs a URL you provide; see prompt below)"
[[ "$NEED_MOBSUITE_DB" -eq 1 ]] && echo "  - the MOB-suite database"
[[ "$NEED_BAKTA_DB" -eq 1 ]] && echo "  - the Bakta database"
for note in "${UNFIXABLE[@]:-}"; do [[ -n "$note" ]] && echo "  (not automatic) $note"; done
echo

PROCEED=0
if [[ "$ASSUME_YES" -eq 1 ]]; then
    PROCEED=1
else
    REPLY=""
    read -r -p "Install the missing item(s) above now? [y/N] " REPLY || true
    case "$REPLY" in y|Y|yes|YES|Yes) PROCEED=1 ;; esac
fi

if [[ "$PROCEED" -ne 1 ]]; then
    log "Skipped. Re-run with --yes to skip this prompt, or install manually (see INSTALL.md)."
    exit 1
fi

YES_FLAG=(); [[ "$ASSUME_YES" -eq 1 ]] && YES_FLAG=(--yes)

if [[ "$NEED_CONDA" -eq 1 ]]; then
    bash "$HERE/../env/bootstrap_conda.sh" "${YES_FLAG[@]}" || die "conda bootstrap failed; cannot continue without it"
fi
for profile in "${!NEEDED_PROFILES[@]}"; do
    log "Installing 'install-tools $profile' ..."
    bash "$HERE/../env/install_tools.sh" "$profile" || warn "install-tools $profile failed; see output above"
done
if [[ "$NEED_PLATON_DB" -eq 1 ]]; then
    bash "$HERE/../env/download_platon_db.sh" || warn "Platon database step did not complete; see output above"
fi
if [[ "$NEED_MOBSUITE_DB" -eq 1 ]]; then
    bash "$HERE/../env/download_mobsuite_db.sh" "${YES_FLAG[@]}" || warn "MOB-suite database step did not complete; see output above"
fi
if [[ "$NEED_BAKTA_DB" -eq 1 ]]; then
    bash "$HERE/../env/download_bakta_db.sh" "${YES_FLAG[@]}" || warn "Bakta database step did not complete; see output above"
fi

echo
if [[ "$NEED_CONDA" -eq 1 || ${#NEEDED_PROFILES[@]} -gt 0 ]]; then
    log "A tool was just installed into a conda environment that this shell has not"
    log "(re-)activated -- it will not be on PATH yet in THIS session even though the"
    log "install succeeded. Run 'conda activate plasbench' (open a new shell after a"
    log "conda bootstrap), then re-run 'plasbench check' to confirm."
else
    log "Re-run 'plasbench check' (bash scripts/00_setup.sh) to confirm everything now passes."
fi
# Not a success exit: the fixes above are best-effort (each failure was only
# warned about, not fatal, so one bad step does not abort the others), and
# even a fully successful tool install is not yet visible on THIS process's
# PATH. Callers (run_all.sh's stage-0 gate included) must not treat this run
# as a passing dependency check.
exit 1
