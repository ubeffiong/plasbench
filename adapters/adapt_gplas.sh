#!/usr/bin/env bash
# Adapter: gplas (EXPERIMENTAL / optional) -> predicted-plasmid FASTA.
#
# gplas output layout varies by version. It generally writes, under results/:
#   <prefix>_results.tab      (node -> bin, with a "Prob_Chromosome"/"Bin" call)
#   <prefix>_bins.tab
# and can output plasmid node sequences. Because the format is version-specific,
# this adapter tries, in order:
#   1) a ready-made *plasmid*.fasta or gplas *_bin_*.fasta anywhere in the output dir
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
# gplas versions can write the same sequence in both a combined plasmid FASTA
# and a per-bin FASTA.  Downstream scoring requires one unambiguous membership.
declare -A seen_sequence_ids
while IFS= read -r -d '' f; do
    [[ -s "$f" ]] || continue
    bin=$(basename "$f" .fasta)
    keep_record=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" == '>'* ]]; then
            sequence_id="${line#>}"
            sequence_id="${sequence_id%%[[:space:]]*}"
            if [[ -z "$sequence_id" || -n "${seen_sequence_ids[$sequence_id]+present}" ]]; then
                keep_record=0
            else
                seen_sequence_ids["$sequence_id"]=1
                keep_record=1
                found=1
                printf '%s\n' "$line" >> "$OUT_FASTA"
                printf '%s\t%s\n' "$bin" "$sequence_id" >> "$BINS"
            fi
        elif [[ "$keep_record" -eq 1 ]]; then
            printf '%s\n' "$line" >> "$OUT_FASTA"
        fi
    done < "$f"
done < <(find "$OUT_DIR" -type f \( -iname '*plasmid*.fasta' -o -iname '*_bin_*.fasta' \) -print0 | sort -z)
shopt -u nullglob
if [[ "$found" -eq 0 ]]; then
    echo "[adapt_gplas] could not find a plasmid FASTA in $OUT_DIR." >&2
    echo "[adapt_gplas] gplas output is version-specific; edit this adapter for your version." >&2
    exit 3
fi
echo "[adapt_gplas] wrote $OUT_FASTA" >&2
