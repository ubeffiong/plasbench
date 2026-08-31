#!/usr/bin/env bash
# Adapter: gplas (EXPERIMENTAL / optional) -> predicted-plasmid FASTA.
#
# gplas output layout varies by version. It generally writes, under results/:
#   <prefix>_results.tab      (node -> bin, with a "Prob_Chromosome"/"Bin" call)
#   <prefix>_bins.tab
# and can output plasmid node sequences. Because the format is version-specific,
# this adapter tries, in order:
#   1) a ready-made *plasmid*.fasta anywhere in the output dir
#   2) otherwise it exits non-zero so the pipeline SKIPS gplas for this sample
#      (rather than silently producing wrong truth).
#
# Usage: adapt_gplas.sh <gplas_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
shopt -s nullglob
found=0
while IFS= read -r -d '' f; do
    [[ -s "$f" ]] || continue
    cat "$f" >> "$OUT_FASTA"; found=1
    bin=$(basename "$f" .fasta)
    awk -v bin="$bin" '/^>/ {sub(/^>/,"",$1); print bin "\t" $1}' "$f" >> "$BINS"
done < <(find "$OUT_DIR" -type f -iname '*plasmid*.fasta' -print0)
shopt -u nullglob
if [[ "$found" -eq 0 ]]; then
    echo "[adapt_gplas] could not find a plasmid FASTA in $OUT_DIR." >&2
    echo "[adapt_gplas] gplas output is version-specific; edit this adapter for your version." >&2
    exit 3
fi
echo "[adapt_gplas] wrote $OUT_FASTA" >&2
