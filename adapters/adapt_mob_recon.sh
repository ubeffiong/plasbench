#!/usr/bin/env bash
# Adapter: MOB-suite mob_recon -> standardized predicted-plasmid FASTA.
#
# mob_recon writes an output directory containing:
#   chromosome.fasta         (contigs it called chromosomal)
#   plasmid_<cluster>.fasta  (one file per reconstructed plasmid bin)
#   contig_report.txt        (per-contig table)
# Predicted plasmid sequence = concatenation of all plasmid_*.fasta files.
#
# Usage: adapt_mob_recon.sh <mob_recon_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"   # start empty (an empty file is a valid "predicted nothing")
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"

shopt -s nullglob
found=0
for f in "$OUT_DIR"/plasmid_*.fasta; do
    cat "$f" >> "$OUT_FASTA"
    bin=$(basename "$f" .fasta)
    awk -v bin="$bin" '/^>/ {sub(/^>/,"",$1); print bin "\t" $1}' "$f" >> "$BINS"
    found=1
done
shopt -u nullglob

if [[ "$found" -eq 0 ]]; then
    echo "[adapt_mob_recon] no plasmid_*.fasta found in $OUT_DIR (tool predicted no plasmids)" >&2
fi
echo "[adapt_mob_recon] wrote $OUT_FASTA" >&2
