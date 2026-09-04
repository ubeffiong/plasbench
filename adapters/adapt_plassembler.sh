#!/usr/bin/env bash
# Adapter: Plassembler -> standardized predicted-plasmid FASTA.
#
# Plassembler writes <prefix>_plasmids.fasta holding one contig per assembled
# plasmid, so unlike a contig classifier its output is already plasmid-level:
# each record is a distinct reconstructed plasmid and therefore its own bin.
#
# Plassembler deliberately writes an EMPTY _plasmids.fasta when it finds no
# plasmids, so that workflow managers see a file either way. An empty result is
# a real prediction ("this isolate has no plasmids"), not a failure, and must be
# scored as such -- treating it as an error would quietly drop the isolate and
# flatter the tool. This adapter therefore succeeds on an empty input and emits
# an empty prediction.
#
# Usage: adapt_plassembler.sh <plassembler_out_dir> <unused_base_asm> <out_fasta>
#
# The second argument is the base assembly, unused here but kept so every
# adapter in adapters/ has one calling convention (see adapters/REGISTRY.md).
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="${2:-}"; OUT_FASTA="$3"

: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"
printf 'bin_id\tsequence_id\n' > "$BINS"

shopt -s nullglob
candidates=("$OUT_DIR"/*_plasmids.fasta)
shopt -u nullglob

if [[ "${#candidates[@]}" -eq 0 ]]; then
    echo "[adapt_plassembler] no *_plasmids.fasta in $OUT_DIR" >&2
    exit 1
fi

records=0
for f in "${candidates[@]}"; do
    [[ -s "$f" ]] || continue
    cat "$f" >> "$OUT_FASTA"
    # Plassembler headers carry copy-number fields after the id, e.g.
    #   >1 len=4242 copy_number_short_read=2.5 ...
    # Take the first whitespace-delimited token as the sequence id, and make
    # each assembled plasmid its own bin.
    awk '/^>/ {id=substr($1,2); print id "\t" id}' "$f" >> "$BINS"
    records=$((records + $(grep -c '^>' "$f" || true)))
done

if [[ "$records" -eq 0 ]]; then
    echo "[adapt_plassembler] Plassembler reported no plasmids for this isolate (empty prediction, scored as such)" >&2
else
    echo "[adapt_plassembler] wrote $OUT_FASTA ($records plasmid record(s))" >&2
fi
