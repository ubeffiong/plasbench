#!/usr/bin/env bash
# Adapter: PlasBin-flow (pre-computed output) -> standardized predicted-plasmid FASTA.
#
# PlasBin-flow needs a Gurobi licence, so PlasBench does not run it; this takes
# the tool's own output TSV (#Pls_ID Flow GC_bin Contigs) and the assembly the
# contig ids refer to.
#
# Usage: adapt_plasbin_flow.sh <plasbin_output_tsv> <base_assembly_fasta> <out_fasta>
set -euo pipefail
PB_OUT="$1"
BASE_ASM="$2"
OUT_FASTA="$3"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$HERE/../python/plasbin_flow_adapter.py"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
if [[ ! -f "$PB_OUT" ]]; then
    echo "[adapt_plasbin_flow] PlasBin-flow output not found: $PB_OUT" >&2
    exit 1
fi
PROV="${OUT_FASTA%.plasmid.fasta}.plasbin_flow.provenance.json"
"$PY" "$HELPER" --plasbin-output "$PB_OUT" --contigs "$BASE_ASM" \
    --out-fasta "$OUT_FASTA" --provenance "$PROV"
echo "[adapt_plasbin_flow] wrote $OUT_FASTA" >&2
