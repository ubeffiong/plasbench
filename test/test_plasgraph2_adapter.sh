#!/usr/bin/env bash
# Regression for adapters/adapt_plasgraph2.sh, against plASgraph2's real
# (verified) output structure: a single CSV
# (sample,contig,length,plasmid_score,chrom_score,label). Unlike geNomad/
# PLASMe, plASgraph2 writes no separate hard-call FASTA of its own, so the
# adapter must derive the hard call itself from label=="plasmid" rows. It is
# a per-node classifier with no grouping output, so bins.tsv must always be
# header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The base assembly given as input (3 contigs: c1, c2, c3).
base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

csv="$TMP/sample_output.csv"
{
    printf 'sample,contig,length,plasmid_score,chrom_score,label\n'
    printf 'sample,c1,8,0.95,0.05,plasmid\n'
    printf 'sample,c2,8,0.30,0.70,chromosome\n'
    printf 'sample,c3,8,0.55,0.45,ambiguous\n'
} > "$csv"

bash "$ROOT/adapters/adapt_plasgraph2.sh" "$csv" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "label==plasmid rows, extracted from the base assembly, become the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 3 ]] || { echo "FAIL: expected all 3 scored contigs in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2 c3; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
echo "candidates.fasta includes every scored contig, not just the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 3 ]] || { echo "FAIL: expected 3 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.30" || { echo "FAIL: expected c2's plasmid_score=0.30 to round-trip" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every contig's real plasmid_score, not just the hard call's -> PASS"

# No label==plasmid rows at all is a valid "predicted none", not a failure.
csv2="$TMP/sample2_output.csv"
{
    printf 'sample,contig,length,plasmid_score,chrom_score,label\n'
    printf 'sample,c1,8,0.10,0.90,chromosome\n'
    printf 'sample,c2,8,0.20,0.80,chromosome\n'
} > "$csv2"
bash "$ROOT/adapters/adapt_plasgraph2.sh" "$csv2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no row is labelled plasmid" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/pred2.scores.tsv" | wc -l)" -eq 2 ]] || { echo "FAIL: expected 2 score rows even with no plasmid hard call" >&2; exit 1; }
echo "no label==plasmid rows is scored as 'no plasmids', not a failure -> PASS"

# No CSV at all: unlike geNomad/PLASMe (which still have a real hard-call
# FASTA of their own), plASgraph2's CSV is the ONLY output -- its absence is
# a genuine adapter failure, not a degraded-but-valid "predicted none".
rm -f "$TMP/missing.csv"
if bash "$ROOT/adapters/adapt_plasgraph2.sh" "$TMP/missing.csv" "$base_asm" "$TMP/pred3.plasmid.fasta" 2>/dev/null; then
    echo "FAIL: expected adapter failure when the output CSV is entirely absent" >&2
    exit 1
fi
echo "a missing output CSV is a genuine adapter failure (no separate hard-call FASTA exists to fall back on) -> PASS"

echo "ALL PLASGRAPH2 ADAPTER TESTS PASSED"
