#!/usr/bin/env bash
# Adapter: plasmidSPAdes -> standardized predicted-plasmid FASTA.
#
# plasmidSPAdes writes contigs.fasta in its output dir; ALL of these contigs
# are its plasmid predictions. We copy that file.
#
# Usage: adapt_plasmidspades.sh <plasmidspades_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
if [[ -s "$OUT_DIR/contigs.fasta" ]]; then
    cat "$OUT_DIR/contigs.fasta" >> "$OUT_FASTA"
else
    echo "[adapt_plasmidspades] no contigs.fasta in $OUT_DIR (predicted none)" >&2
fi
echo "[adapt_plasmidspades] wrote $OUT_FASTA" >&2
