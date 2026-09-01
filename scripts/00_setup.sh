#!/usr/bin/env bash
# Stage 0 — create directories and check that required tools are installed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

log "Project root: $PROJECT_ROOT"
mkdir -p "$DATA_DIR" "$RESULTS_DIR" "$LOG_DIR" "$TMP_DIR"

log "Checking core dependencies..."
CORE_OK=1
for c in datasets prefetch fasterq-dump fastp minimap2 python3; do
    if have "$c"; then
        log "  [ok]   $c"
    else
        warn "  [MISS] $c"
        CORE_OK=0
    fi
done

# spades.py / plasmidspades.py
if [[ "${RUN_PLASMIDSPADES:-0}" -eq 1 ]]; then
    have plasmidspades.py && log "  [ok]   plasmidspades.py" || { warn "  [MISS] plasmidspades.py"; CORE_OK=0; }
fi
if [[ "$ASSEMBLER" == "spades" ]]; then
    have spades.py && log "  [ok]   spades.py" || { warn "  [MISS] spades.py"; CORE_OK=0; }
elif [[ "$ASSEMBLER" == "unicycler" ]]; then
    have unicycler && log "  [ok]   unicycler" || { warn "  [MISS] unicycler"; CORE_OK=0; }
fi

log "Checking optional plasmid tools (only those switched on in config)..."
[[ "${RUN_MOB_RECON:-0}" -eq 1 ]]     && { have mob_recon && log "  [ok]   mob_recon" || warn "  [MISS] mob_recon (RUN_MOB_RECON=1)"; }
[[ "${RUN_PLATON:-0}" -eq 1 ]]        && { have platon && log "  [ok]   platon" || warn "  [MISS] platon (RUN_PLATON=1)"; }
[[ "${RUN_GPLAS2_MOB:-0}" -eq 1 ]]    && { have gplas && log "  [ok]   gplas (gplas2_mob)" || { warn "  [MISS] gplas (RUN_GPLAS2_MOB=1)"; CORE_OK=0; }; }
[[ "${RUN_GPLAS2_EXTERNAL:-0}" -eq 1 ]] && { have gplas && log "  [ok]   gplas (gplas2_external)" || { warn "  [MISS] gplas (RUN_GPLAS2_EXTERNAL=1)"; CORE_OK=0; }; }

if [[ "${RUN_PLATON:-0}" -eq 1 ]]; then
    if [[ -d "$PLATON_DB" ]]; then log "  [ok]   Platon DB at $PLATON_DB"
    else warn "  [MISS] Platon DB not found at $PLATON_DB (see INSTALL.md)"; CORE_OK=0; fi
fi

if [[ "$CORE_OK" -eq 1 ]]; then
    log "Core dependency check PASSED."
else
    warn "Some core dependencies are missing. Install them (see INSTALL.md) before running the full pipeline."
    exit 1
fi
