#!/usr/bin/env bash
# Adapter: PlasmidHunter -> standardized predicted-plasmid FASTA, plus the
# optional scores contract (adapters/SCORES.md).
#
# `plasmidhunter -i <assembly.fasta> -o <out_dir> -c <threads>` writes:
#   <out_dir>/predictions.tsv
#       -- a tab-separated pandas table, one row per contig PlasmidHunter
#          actually scored (its own README: contigs <=1kb are excluded by
#          the tool itself, never re-added here). The row's INDEX (an
#          unnamed first column -- pandas' own to_csv() convention when no
#          index_label is given) is the original contig id; the real
#          columns are "Prediction (0: chromosome, 1: plasmid)" (a FLOAT,
#          0.0 or 1.0 -- never the string "plasmid"/"chromosome") and
#          "Probability of 1" (the plasmid-class probability, in [0,1] --
#          the continuous score the PR-curve sweep needs). Confirmed
#          directly from PlasmidHunter's own source (functions.py's
#          predict()), since its README does not spell out these exact
#          header strings.
# PlasmidHunter is a per-contig classifier with no grouping/bin output, so
# (like Platon/geNomad/PLASMe/RFPlasmid) bins.tsv is written header-only.
#
# Usage: adapt_plasmidhunter.sh <plasmidhunter_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

PREDICTIONS="$OUT_DIR/predictions.tsv"
if [[ ! -s "$PREDICTIONS" ]]; then
    echo "[adapt_plasmidhunter] no predictions.tsv found in $OUT_DIR (predicted none)" >&2
    exit 0
fi

# The contig-id column is PlasmidHunter's own unnamed pandas row index --
# always column 1 by pandas' own to_csv() convention, never looked up by
# name (it has none). The prediction/probability columns ARE looked up by
# header name, never assumed fixed position, in case a future
# PlasmidHunter version reorders them.
awk -F'\t' -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" -v plasmid_out="$OUT_FASTA" '
    NR == FNR {
        if (FNR == 1) {
            for (i = 2; i <= NF; i++) {
                if ($i == "Prediction (0: chromosome, 1: plasmid)") pred_col = i
                if ($i == "Probability of 1") score_col = i
            }
            next
        }
        if (!pred_col || !score_col) next
        id = $1
        wanted[id] = 1
        print id "\t" $score_col >> scores_out
        if ($pred_col + 0 >= 0.5) plasmid_call[id] = 1
        next
    }
    /^>/ {
        header = substr($0, 2); split(header, parts, " "); id = parts[1]
        keep_candidate = (id in wanted)
        keep_plasmid = (id in plasmid_call)
    }
    keep_candidate { print > candidates_out }
    keep_plasmid { print >> plasmid_out }
' "$PREDICTIONS" "$BASE_ASM"

echo "[adapt_plasmidhunter] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s)), $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
