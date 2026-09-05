#!/usr/bin/env bash
# Adapter: geNomad -> standardized predicted-plasmid FASTA, plus the optional
# scores contract (adapters/SCORES.md).
#
# `genomad end-to-end <base_assembly> <out_dir> <db>` writes, among other
# things:
#   <out_dir>/<prefix>_summary/<prefix>_plasmid.fna
#       -- geNomad's own post-classification-filtering hard call: the
#          contigs it actually decided are plasmids. This is the tool's
#          real decision, so it becomes pred_genomad.plasmid.fasta unchanged.
#   <out_dir>/<prefix>_aggregated_classification/<prefix>_aggregated_classification.tsv
#       -- one row per INPUT contig (not just the ones called plasmid), with
#          (among other columns) seq_name and plasmid_score in [0, 1]. This
#          is the wider candidates universe the PR-curve sweep needs.
# geNomad is a per-contig classifier with no grouping/bin output, so (like
# Platon) bins.tsv is written header-only and always "not applicable" per
# config/tool_capabilities.tsv's binning_capable=no for this tool.
#
# Usage: adapt_genomad.sh <genomad_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

shopt -s nullglob
plasmid_fna=("$OUT_DIR"/*_summary/*_plasmid.fna)
shopt -u nullglob
if [[ "${#plasmid_fna[@]}" -eq 0 ]]; then
    echo "[adapt_genomad] no *_plasmid.fna found under $OUT_DIR/*_summary (predicted none)" >&2
else
    cat "${plasmid_fna[@]}" >> "$OUT_FASTA"
    echo "[adapt_genomad] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s))" >&2
fi

shopt -s nullglob
classification_tsv=("$OUT_DIR"/*_aggregated_classification/*_aggregated_classification.tsv)
shopt -u nullglob
if [[ "${#classification_tsv[@]}" -eq 0 ]]; then
    echo "[adapt_genomad] no *_aggregated_classification.tsv found under $OUT_DIR; scores/candidates omitted (point score unaffected)" >&2
    exit 0
fi

# Column position is looked up by header name, not assumed fixed, since
# geNomad's exact column order/count can change between versions.
awk -F'\t' -v base_asm="$BASE_ASM" -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" '
    NR == FNR {
        if (FNR == 1) {
            for (i = 1; i <= NF; i++) { if ($i == "seq_name") seq_col = i; if ($i == "plasmid_score") score_col = i }
            next
        }
        if (!seq_col || !score_col) next
        id = $seq_col
        wanted[id] = 1
        print id "\t" $score_col >> scores_out
        next
    }
    # Second pass: stream the base assembly FASTA, copying only records
    # geNomad actually scored (its own minimum-length cutoff may drop some).
    /^>/ {
        header = substr($0, 2); split(header, parts, " "); id = parts[1]
        keep = (id in wanted)
    }
    keep { print > candidates_out }
' "${classification_tsv[0]}" "$BASE_ASM"

echo "[adapt_genomad] wrote $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
