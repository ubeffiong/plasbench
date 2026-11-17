#!/usr/bin/env bash
# Adapter: PlasmidEC -> standardized predicted-plasmid FASTA.
#
# `plasmidEC.sh -i <assembly.fasta> -o <out> -s "<species>" -t <threads> -l <min_length>` (Paganini et al.; MIT; the
# maintained version is gitlab.com/mmb-umcu/plasmidec, an earlier copy is github.com/lisavader/plasmidEC) runs an ensemble of
# classifiers (RFPlasmid, PlaScope, Platon, and with -c also mlplasmids) and calls a contig plasmid by majority vote
# (-m: minority vote). It writes, in <out>:
#   ensemble_output.csv      per contig: each classifier's call, Plasmid_count (votes) and Combined_prediction
#   plasmid_contigs.fasta    the contigs whose Combined_prediction is plasmid (its own hard call, taken unchanged)
#   all_predictions.csv      the individual classifiers' calls (intermediate)
# plasmid_contigs.fasta may be absent or empty when no contig is called plasmid. That is "predicted none" ONLY when
# ensemble_output.csv exists, because that file is written for every classified contig. If ensemble_output.csv is missing the
# run did not finish, and this adapter fails instead of reporting an empty prediction (a crashed run must not look like
# "no plasmids found").
#
# PlasmidEC has no continuous per-contig score (a vote count), so, like Platon and PlaScope, there is no candidates/scores
# contract here, and bins.tsv is header-only (it classifies contigs; binning_capable=no in config/tool_capabilities.tsv).
# Contigs shorter than its -l (default 1000) are not classified by it and are therefore not called plasmid.
#
# Usage: adapt_plasmidec.sh <plasmidec_out_dir> <unused_base_asm> <out_fasta>
set -euo pipefail
OUT_DIR="$1"
# shellcheck disable=SC2034  # BASE_ASM: positional adapter contract, unused here
BASE_ASM="${2:-}"
OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
if [[ ! -s "$OUT_DIR/ensemble_output.csv" ]]; then
    echo "[adapt_plasmidec] ERROR: $OUT_DIR/ensemble_output.csv is missing or empty: PlasmidEC did not finish (not reporting an empty prediction)" >&2
    exit 1
fi
if [[ -s "$OUT_DIR/plasmid_contigs.fasta" ]]; then
    cat "$OUT_DIR/plasmid_contigs.fasta" >> "$OUT_FASTA"
else
    echo "[adapt_plasmidec] no plasmid_contigs.fasta in $OUT_DIR (predicted none; ensemble_output.csv present)" >&2
fi
echo "[adapt_plasmidec] wrote $OUT_FASTA" >&2
