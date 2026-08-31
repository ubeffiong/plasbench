#!/usr/bin/env bash
# Adapter: Platon -> standardized predicted-plasmid FASTA.
#
# Platon writes <prefix>.plasmid.fasta (contigs classified as plasmid).
# It may also write <prefix>.chromosome.fasta. We take the plasmid one.
#
# Usage: adapt_platon.sh <platon_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
shopt -s nullglob
found=0
for f in "$OUT_DIR"/*.plasmid.fasta; do
    cat "$f" >> "$OUT_FASTA"; found=1
    awk '/^>/ {sub(/^>/,"",$1); print $1 "\t" $1}' "$f" >> "$BINS"
done
shopt -u nullglob
[[ "$found" -eq 0 ]] && echo "[adapt_platon] no *.plasmid.fasta in $OUT_DIR (predicted none)" >&2
echo "[adapt_platon] wrote $OUT_FASTA" >&2
