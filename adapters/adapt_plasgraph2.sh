#!/usr/bin/env bash
# Adapter: plASgraph2 -> standardized predicted-plasmid FASTA, plus the
# optional scores contract (adapters/SCORES.md).
#
# `plASgraph2_classify.py gfa <graph.gfa.gz> <model_dir> <output.csv>` writes
# a single CSV, one row per contig above the tool's own 100bp length cutoff,
# with columns: sample,contig,length,plasmid_score,chrom_score,label (label
# in {plasmid, chromosome, ambiguous, unlabeled}).
#
# Unlike geNomad/PLASMe, plASgraph2 does NOT write a separate hard-call
# FASTA of its own -- the CSV is the only output. So this adapter derives the
# hard call itself (label == "plasmid" rows, sequences extracted from the
# base assembly FASTA by contig id) rather than taking a tool-written FASTA
# unchanged. Every scored row (regardless of label) is the candidates
# universe the PR-curve sweep needs.
#
# plASgraph2 is a per-node classifier with no derived multi-contig grouping
# in its own output (verified: no bins/clusters/connected-components output
# exists) -- so, like Platon/geNomad/PLASMe, bins.tsv is written header-only;
# config/tool_capabilities.tsv's binning_capable=no is what actually decides
# "not applicable", not this adapter.
#
# Usage: adapt_plasgraph2.sh <plasgraph2_output_csv> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_CSV="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

if [[ ! -s "$OUT_CSV" ]]; then
    echo "[adapt_plasgraph2] $OUT_CSV missing or empty (adapter failure)" >&2
    exit 1
fi

# Column position is looked up by header name, not assumed fixed. plASgraph2's
# output is CSV (comma-separated), like PLASMe's report.
awk -F',' -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" -v plasmid_out="$OUT_FASTA" '
    NR == FNR {
        if (FNR == 1) {
            for (i = 1; i <= NF; i++) {
                if ($i == "contig") contig_col = i
                if ($i == "plasmid_score") score_col = i
                if ($i == "label") label_col = i
            }
            next
        }
        if (!contig_col || !score_col || !label_col) next
        id = $contig_col
        wanted[id] = 1
        print id "\t" $score_col >> scores_out
        if ($label_col == "plasmid") plasmid_id[id] = 1
        next
    }
    /^>/ {
        header = substr($0, 2); split(header, parts, " "); id = parts[1]
        keep_candidate = (id in wanted)
        keep_plasmid = (id in plasmid_id)
    }
    keep_candidate { print > candidates_out }
    keep_plasmid { print > plasmid_out }
' "$OUT_CSV" "$BASE_ASM"

echo "[adapt_plasgraph2] wrote $OUT_FASTA ($(awk '/^>/{n++} END{print n+0}' "$OUT_FASTA") plasmid record(s))" >&2
echo "[adapt_plasgraph2] wrote $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
