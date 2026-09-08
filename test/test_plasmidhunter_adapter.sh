#!/usr/bin/env bash
# Regression for adapters/adapt_plasmidhunter.sh, against PlasmidHunter's real
# (verified from its own source, functions.py's predict(), not just its
# README) predictions.tsv shape: a plain pandas to_csv(sep='\t') table with
# an UNNAMED first column (the row index) and real columns "Prediction (0:
# chromosome, 1: plasmid)" (a float hard call) and "Probability of 1"
# (continuous score in [0,1]). The unnamed index IS the original contig id
# (PlasmidHunter derives it from Prodigal gene names by stripping the
# trailing "_<genenum>" suffix, functions.py's daa_to_hits()) -- confirmed by
# tracing that function, never assumed. PlasmidHunter writes no separate
# hard-call FASTA of its own, so this adapter reconstructs the plasmid FASTA
# itself from rows where the prediction column is >= 0.5. PlasmidHunter is a
# per-contig classifier with no grouping output, so bins.tsv must always be
# header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The base assembly given as input to PlasmidHunter (3 contigs: c1, c2, c3).
base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

mkdir -p "$TMP/out"
{
    printf '\tPrediction (0: chromosome, 1: plasmid)\tProbability of 0\tProbability of 1\n'
    printf 'c1\t1.0\t0.05\t0.95\n'
    printf 'c2\t0.0\t0.70\t0.30\n'
    printf 'c3\t0.0\t0.95\t0.05\n'
} > "$TMP/out/predictions.tsv"

bash "$ROOT/adapters/adapt_plasmidhunter.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "prediction>=0.5 rows are reconstructed into pred_plasmidhunter.plasmid.fasta -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 3 ]] || { echo "FAIL: expected all 3 scored contigs in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2 c3; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
echo "candidates.fasta includes every scored contig, not just the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 3 ]] || { echo "FAIL: expected 3 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.30" || { echo "FAIL: expected c2's 'Probability of 1'=0.30 to round-trip, joined by the unnamed index column" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every contig's real 'Probability of 1' score, joined by the index column -> PASS"

# No predictions.tsv at all is a valid "predicted none", not a hard adapter failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2"
bash "$ROOT/adapters/adapt_plasmidhunter.sh" "$TMP/out2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no predictions.tsv exists" >&2; exit 1; }
echo "no predictions.tsv is scored as 'no plasmids', not a failure -> PASS"

echo "ALL PLASMIDHUNTER ADAPTER TESTS PASSED"
