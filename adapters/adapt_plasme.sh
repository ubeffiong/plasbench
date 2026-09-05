#!/usr/bin/env bash
# Adapter: PLASMe -> standardized predicted-plasmid FASTA, plus the optional
# scores contract (adapters/SCORES.md).
#
# `PLASMe.py INPUT_CONTIG OUTPUT_PLASMIDS [options]` writes:
#   OUTPUT_PLASMIDS          -- FASTA of contigs PLASMe's own -p/--probability
#                                threshold (default 0.5) calls plasmid. This
#                                is the tool's real hard call, taken unchanged.
#   OUTPUT_PLASMIDS_report.csv -- one row per contig PLASMe's alignment+
#                                transformer pipeline actually scored (not
#                                just the ones passing the threshold), with
#                                columns contig,length,reference,order,
#                                evidence,score,amb_region. This is the wider
#                                candidates universe the PR-curve sweep needs
#                                -- PLASMe's own docs describe this score
#                                column as meant for exactly that ("can be
#                                set as a threshold to draw PR curves").
# PLASMe is a per-contig classifier with no grouping/bin output, so (like
# Platon and geNomad) bins.tsv is written header-only.
#
# Usage: adapt_plasme.sh <plasme_out_dir> <base_assembly_fasta> <out_fasta>
#
# Unlike geNomad's directory-based output, PLASMe writes to an explicit file
# path (not a directory). scripts/04_run_tools.sh's run_plasme() therefore
# invokes PLASMe with a FIXED, adapter-known output filename inside its own
# per-tool output directory (plasme_output.fasta), so this adapter can find
# both it and its "<name>_report.csv" sibling reliably.
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

PLASME_FASTA="$OUT_DIR/plasme_output.fasta"
PLASME_REPORT="$OUT_DIR/plasme_output.fasta_report.csv"

if [[ -s "$PLASME_FASTA" ]]; then
    cat "$PLASME_FASTA" >> "$OUT_FASTA"
    echo "[adapt_plasme] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s))" >&2
else
    echo "[adapt_plasme] no plasme_output.fasta content in $OUT_DIR (predicted none)" >&2
fi

if [[ ! -s "$PLASME_REPORT" ]]; then
    echo "[adapt_plasme] no plasme_output.fasta_report.csv found in $OUT_DIR; scores/candidates omitted (point score unaffected)" >&2
    exit 0
fi

# Column position is looked up by header name, not assumed fixed. PLASMe's
# report is CSV (comma-separated), unlike geNomad's TSV.
awk -F',' -v base_asm="$BASE_ASM" -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" '
    NR == FNR {
        if (FNR == 1) {
            for (i = 1; i <= NF; i++) { if ($i == "contig") id_col = i; if ($i == "score") score_col = i }
            next
        }
        if (!id_col || !score_col) next
        id = $id_col
        wanted[id] = 1
        print id "\t" $score_col >> scores_out
        next
    }
    /^>/ {
        header = substr($0, 2); split(header, parts, " "); id = parts[1]
        keep = (id in wanted)
    }
    keep { print > candidates_out }
' "$PLASME_REPORT" "$BASE_ASM"

echo "[adapt_plasme] wrote $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
