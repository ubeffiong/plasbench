#!/usr/bin/env bash
# Adapter: PlaScope -> standardized predicted-plasmid FASTA.
#
# `plaScope.sh --fasta <assembly> -a <spades|unicycler> -o <out> --sample
# <prefix> --db_dir ... --db_name ...` writes, under <out>/<prefix>_PlaScope/:
#   PlaScope_predictions/<prefix>_plasmid.fasta
#       -- PlaScope's own hard call (Centrifuge classification filtered by
#          its own contig coverage/length/hit-length heuristic), taken
#          unchanged. Written lazily (awk's implicit output redirection) and
#          does NOT exist at all when zero contigs were classified plasmid
#          -- a missing file is scored as "predicted none", not a failure,
#          same policy as adapt_platon.sh/adapt_plassembler.sh.
#   PlaScope_predictions/<prefix>_chromosome.fasta,
#   PlaScope_predictions/<prefix>_unclassified.fasta
#       -- the other two hard-call classes; not used here.
#   Centrifuge_results/<prefix>_list
#       -- the underlying (contig_id, label) table the *_plasmid.fasta file
#          above is extracted from; not needed here since PlaScope has no
#          continuous score to recover from it.
# scripts/04_run_tools.sh's run_plascope() passes <out>/<prefix>_PlaScope
# (not the raw -o value) as this adapter's out_dir, so the sample prefix
# does not need to be known here -- the plasmid FASTA is found by glob.
#
# PlaScope produces no continuous per-contig score (a hard classification
# only, unlike geNomad/PLASMe/RFPlasmid), so -- like Platon/MOB-suite --
# there is no candidates.fasta/scores.tsv contract here, and bins.tsv is
# always header-only (PlaScope has no grouping/bin output of its own;
# binning_capable=no in config/tool_capabilities.tsv is what actually
# decides "not applicable").
#
# Usage: adapt_plascope.sh <plascope_prefix_dir> <unused_base_asm> <out_fasta>
#
# The second argument is the base assembly, unused here but kept so every
# adapter in adapters/ has one calling convention (see adapters/REGISTRY.md).
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="${2:-}"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"

shopt -s nullglob
plasmid_fasta=("$OUT_DIR"/PlaScope_predictions/*_plasmid.fasta)
shopt -u nullglob
if [[ "${#plasmid_fasta[@]}" -eq 0 ]]; then
    echo "[adapt_plascope] no *_plasmid.fasta found under $OUT_DIR/PlaScope_predictions (predicted none)" >&2
else
    cat "${plasmid_fasta[@]}" >> "$OUT_FASTA"
    echo "[adapt_plascope] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s))" >&2
fi
