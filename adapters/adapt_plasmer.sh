#!/usr/bin/env bash
# Adapter: Plasmer -> standardized predicted-plasmid FASTA, plus the
# optional scores contract (adapters/SCORES.md).
#
# `Plasmer -g <assembly> -p <prefix> -d <db> -t <threads> -m <min_length>
# -l <length> -o <outpath>` writes, under <outpath>/results/ (confirmed
# directly from Plasmer's own `scripts/Plasmer` driver source, since its
# README does not spell out these exact filenames):
#   <prefix>.plasmer.predPlasmids.fa
#       -- Plasmer's OWN hard-call plasmid-only FASTA, produced by its own
#          extract_predPlasmids_seqs.py filtering predClass.tsv's label
#          column strictly on "plasmid" (no extra length/score cutoff of its
#          own) -- taken unchanged here, like adapt_platon.sh/
#          adapt_plascope.sh, not reconstructed.
#   <prefix>.plasmer.predClass.tsv
#       -- a HEADERLESS 2-column table (contig_id, label), assembled by
#          `cat`-ing three different intermediate sources together. label is
#          one of THREE values, not two: "chromosome"/"plasmid" (from the
#          random-forest model), a hard "chromosome" call for any sequence
#          at or above the -l length threshold (never RF-scored), or
#          "shorter_than_<N>" for any sequence at or below the -m minimum
#          length (also never RF-scored, and has no row at all in
#          predProb.tsv below). Not used directly here -- predProb.tsv
#          already carries every RF-scored contig's id.
#   <prefix>.plasmer.predProb.tsv
#       -- a REAL 3-column table WITH a header (`Contig`, `chromosome`,
#          `plasmid`), covering ONLY the contigs that actually went through
#          the random-forest model (excludes both the length-rule and
#          too-short classes above, which have no probability at all). The
#          `plasmid` column is the continuous score the PR-curve sweep
#          needs. Row ids match the input FASTA header's first
#          whitespace-delimited token exactly (Biopython's own
#          SeqIO record.id convention) -- no Prodigal-style renaming needed,
#          unlike PlasmidHunter.
# Per adapters/SCORES.md, `.candidates.fasta`'s record set must EXACTLY equal
# `.scores.tsv`'s -- so both are built from predProb.tsv's contig set only,
# never predClass.tsv's wider set (which would include un-scored,
# length-filtered contigs that predProb.tsv never mentions).
# `scripts/04_run_tools.sh`'s run_plasmer() passes the raw -o value as this
# adapter's out_dir; results live under out_dir/results/ with a
# ${prefix}.plasmer.* naming convention, found here by glob so the prefix
# does not need to be passed separately (same idea as adapt_plascope.sh).
# Plasmer is a per-contig classifier with no grouping/bin output, so (like
# Platon/geNomad/PLASMe/RFPlasmid/PlasmidHunter) bins.tsv is header-only.
#
# Usage: adapt_plasmer.sh <plasmer_out_dir> <base_assembly_fasta> <out_fasta>
set -euo pipefail
OUT_DIR="$1"; BASE_ASM="$2"; OUT_FASTA="$3"
: > "$OUT_FASTA"
BINS="${OUT_FASTA%.plasmid.fasta}.bins.tsv"; printf 'bin_id\tsequence_id\n' > "$BINS"
CANDIDATES="${OUT_FASTA%.plasmid.fasta}.candidates.fasta"; : > "$CANDIDATES"
SCORES="${OUT_FASTA%.plasmid.fasta}.scores.tsv"; printf 'record_id\tprobability\n' > "$SCORES"

shopt -s nullglob
plasmid_fasta=("$OUT_DIR"/results/*.plasmer.predPlasmids.fa)
prob_tsv=("$OUT_DIR"/results/*.plasmer.predProb.tsv)
shopt -u nullglob

if [[ "${#plasmid_fasta[@]}" -eq 0 ]]; then
    echo "[adapt_plasmer] no *.plasmer.predPlasmids.fa found under $OUT_DIR/results (predicted none)" >&2
else
    if [[ "${#plasmid_fasta[@]}" -gt 1 ]]; then
        echo "[adapt_plasmer] WARNING: ${#plasmid_fasta[@]} *.plasmer.predPlasmids.fa files found under $OUT_DIR/results (expected 1 per sample); concatenating all of them into $OUT_FASTA" >&2
    fi
    cat "${plasmid_fasta[@]}" >> "$OUT_FASTA"
fi

if [[ "${#prob_tsv[@]}" -eq 0 ]]; then
    echo "[adapt_plasmer] no *.plasmer.predProb.tsv found under $OUT_DIR/results (no scores/candidates)" >&2
else
    if [[ "${#prob_tsv[@]}" -gt 1 ]]; then
        echo "[adapt_plasmer] WARNING: ${#prob_tsv[@]} *.plasmer.predProb.tsv files found under $OUT_DIR/results (expected 1 per sample); using only the first (${prob_tsv[0]}) -- the rest are ignored" >&2
    fi
    # The header names the plasmid-probability column, never assumed a fixed
    # position, in case a future Plasmer version reorders it.
    awk -F'\t' -v scores_out="$SCORES" -v candidates_out="$CANDIDATES" '
        NR == FNR {
            if (FNR == 1) {
                for (i = 2; i <= NF; i++) { if ($i == "plasmid") score_col = i }
                next
            }
            if (!score_col) next
            id = $1
            wanted[id] = 1
            print id "\t" $score_col >> scores_out
            next
        }
        /^>/ {
            header = substr($0, 2); split(header, parts, " "); id = parts[1]
            keep = (id in wanted)
        }
        keep { print > candidates_out }
    ' "${prob_tsv[0]}" "$BASE_ASM"
fi

echo "[adapt_plasmer] wrote $OUT_FASTA ($(grep -c '^>' "$OUT_FASTA" 2>/dev/null || echo 0) record(s)), $SCORES and $CANDIDATES ($(tail -n +2 "$SCORES" | wc -l | tr -d ' ') scored record(s))" >&2
