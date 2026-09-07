#!/usr/bin/env bash
# Adapter: RFPlasmid -> standardized predicted-plasmid FASTA, plus the
# optional scores contract (adapters/SCORES.md).
#
# `rfplasmid --species SPECIES --input <dir-of-fasta> --out OUT_DIR [--jelly]`
# renumbers every input contig internally (genome basename + a 1-based
# index) and writes, inside OUT_DIR:
#   prediction.csv
#       -- one row per contig RFPlasmid actually scored: an R write.csv
#          table (comma-separated; header names AND string-typed cells are
#          double-quoted, numeric cells are not). An unnamed first column
#          holds RFPlasmid's own internal "<genome>_<index>" join key (NOT
#          the original assembly header) -- never used here. The columns
#          this adapter actually reads are "prediction" (single-letter "p"
#          or "c" hard call), "votes plasmid" (the underlying random
#          forest's plasmid vote fraction, in [0,1] -- the continuous score
#          the PR-curve sweep needs), and "contigID", which is the ORIGINAL
#          input FASTA record's description and is what this adapter joins
#          back to the base assembly on. Confirmed directly from RFPlasmid's
#          own source (classification.R's `colnames(combined1) <- c(...)`
#          and rfplasmid.py's contigID.out/outputdataframe.csv pipeline),
#          since RFPlasmid's own docs do not spell out prediction.csv's
#          exact header names.
# Unlike geNomad/PLASMe, RFPlasmid writes no separate hard-call FASTA of its
# own -- prediction.csv's "prediction" column is the only hard call -- so
# this adapter reconstructs pred_rfplasmid.plasmid.fasta itself ("p" rows)
# rather than taking a tool-written FASTA unchanged. RFPlasmid is a
# per-contig classifier with no grouping/bin output, so (like
# Platon/geNomad/PLASMe) bins.tsv is written header-only.
#
# Usage: adapt_rfplasmid.sh <rfplasmid_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

PREDICTION_CSV="$OUT_DIR/prediction.csv"
if [[ ! -s "$PREDICTION_CSV" ]]; then
    echo "[adapt_rfplasmid] no prediction.csv found in $OUT_DIR (predicted none)" >&2
    exit 0
fi

# Column position is looked up by header name (quotes stripped first), never
# assumed fixed. Single pass builds scores.tsv and the plasmid/candidate id
# sets; a second pass streams the base assembly, writing each record into
# candidates.fasta (every scored contig) and/or pred_rfplasmid.plasmid.fasta
# ("p" calls only).
awk -F',' -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" -v plasmid_out="$OUT_FASTA" '
    function unquote(s) { gsub(/^"|"$/, "", s); return s }
    NR == FNR {
        if (FNR == 1) {
            for (i = 1; i <= NF; i++) {
                h = unquote($i)
                if (h == "prediction") pred_col = i
                if (h == "votes plasmid") score_col = i
                if (h == "contigID") id_col = i
            }
            next
        }
        if (!pred_col || !score_col || !id_col) next
        id = unquote($id_col)
        wanted[id] = 1
        print id "\t" $score_col >> scores_out
        if (unquote($pred_col) == "p") plasmid_call[id] = 1
        next
    }
    /^>/ {
        header = substr($0, 2); split(header, parts, " "); id = parts[1]
        keep_candidate = (id in wanted)
        keep_plasmid = (id in plasmid_call)
    }
    keep_candidate { print > candidates_out }
    keep_plasmid { print >> plasmid_out }
' "$PREDICTION_CSV" "$BASE_ASM"

echo "[adapt_rfplasmid] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s)), $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
