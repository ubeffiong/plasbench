#!/usr/bin/env bash
# Adapter: Hybracter (long-single or hybrid-single) -> standardized
# predicted-plasmid FASTA.
#
# Hybracter writes a per-sample <prefix>_plasmid.fasta (singular, unlike
# Plassembler's *_plasmids.fasta) holding one contig per assembled plasmid,
# under a FINAL_OUTPUT/ directory whose exact subdirectory (complete/ or
# incomplete/, depending on whether the assembly reached full circularity)
# varies by sample -- this adapter searches recursively under the given
# output directory rather than assuming one fixed path, and should be
# re-verified against a real installed Hybracter's actual output tree the
# first time it runs for real.
#
# Like Plassembler, an empty *_plasmid.fasta is a valid "no plasmids found"
# prediction, not a failure, and is scored as such.
#
# Usage: adapt_hybracter.sh <hybracter_out_dir> <unused_base_asm> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="${2:-}"; OUT_FASTA="$3"

: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"
printf 'bin_id\tsequence_id\n' > "$BINS"

mapfile -t candidates < <(find "$OUT_DIR" -type f -name '*_plasmid.fasta' 2>/dev/null | sort)

if [[ "${#candidates[@]}" -eq 0 ]]; then
    echo "[adapt_hybracter] no *_plasmid.fasta found under $OUT_DIR" >&2
    exit 1
fi

records=0
for f in "${candidates[@]}"; do
    [[ -s "$f" ]] || continue
    cat "$f" >> "$OUT_FASTA"
    # Hybracter's plasmid headers carry length/copy-number fields after the
    # id, matching Plassembler's convention (it uses Plassembler internally
    # for plasmid recovery) -- take the first whitespace-delimited token as
    # the sequence id, and make each assembled plasmid its own bin.
    awk '/^>/ {id=substr($1,2); print id "\t" id}' "$f" >> "$BINS"
    records=$((records + $(grep -c '^>' "$f" || true)))
done

if [[ "$records" -eq 0 ]]; then
    echo "[adapt_hybracter] Hybracter reported no plasmids for this isolate (empty prediction, scored as such)" >&2
else
    echo "[adapt_hybracter] wrote $OUT_FASTA ($records plasmid record(s))" >&2
fi
