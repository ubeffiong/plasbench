#!/usr/bin/env bash
# Regression for adapters/adapt_rfplasmid.sh, against RFPlasmid's real
# (verified from its own source, not just its docs) prediction.csv shape:
# an R write.csv table with double-quoted header names and string cells,
# unquoted numeric cells, columns "prediction" ("p"/"c" hard call), "votes
# plasmid" (continuous score in [0,1]), and "contigID" (the ORIGINAL input
# record's description -- never RFPlasmid's own internal row-name join key,
# which this adapter must ignore). RFPlasmid writes no separate hard-call
# FASTA of its own, so this adapter reconstructs the plasmid FASTA itself
# from the "p" rows. RFPlasmid is a per-contig classifier with no grouping
# output, so bins.tsv must always be header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The base assembly given as input to RFPlasmid (3 contigs: c1, c2, c3).
base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

mkdir -p "$TMP/out"
{
    printf '"","prediction","votes chromosomal","votes plasmid","contigID"\n'
    printf '"g_1","p",0.05,0.95,"c1"\n'
    printf '"g_2","c",0.70,0.30,"c2"\n'
    printf '"g_3","c",0.95,0.05,"c3"\n'
} > "$TMP/out/prediction.csv"

bash "$ROOT/adapters/adapt_rfplasmid.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "prediction==\"p\" rows are reconstructed into pred_rfplasmid.plasmid.fasta -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 3 ]] || { echo "FAIL: expected all 3 scored contigs in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2 c3; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
echo "candidates.fasta includes every scored contig, not just the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 3 ]] || { echo "FAIL: expected 3 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.30" || { echo "FAIL: expected c2's 'votes plasmid'=0.30 to round-trip, joined by contigID not the internal row key" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every contig's real 'votes plasmid' score, joined by contigID -> PASS"

# No prediction.csv at all is a valid "predicted none", not a hard adapter failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2"
bash "$ROOT/adapters/adapt_rfplasmid.sh" "$TMP/out2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no prediction.csv exists" >&2; exit 1; }
echo "no prediction.csv is scored as 'no plasmids', not a failure -> PASS"

echo "ALL RFPLASMID ADAPTER TESTS PASSED"
