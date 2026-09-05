#!/usr/bin/env bash
# Regression for adapters/adapt_plasme.sh, against PLASMe's real (verified)
# output shape: an explicit output FASTA file (not a directory) plus a
# sibling "<output>_report.csv" (contig,length,reference,order,evidence,
# score,amb_region) covering every contig PLASMe's alignment+transformer
# pipeline scored -- not just the ones passing its -p/--probability
# threshold. PLASMe is a per-contig classifier with no grouping output, so
# bins.tsv must always be header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

mkdir -p "$TMP/out"
# Hard call: only c1 crosses PLASMe's own -p/--probability threshold.
printf '>c1\nACGTACGT\n' > "$TMP/out/plasme_output.fasta"
# Report covers every contig PLASMe actually scored, including sub-threshold ones.
printf 'contig,length,reference,order,evidence,score,amb_region\n' > "$TMP/out/plasme_output.fasta_report.csv"
printf 'c1,8,ref1,1,blastn+transformer,0.92,no\n' >> "$TMP/out/plasme_output.fasta_report.csv"
printf 'c2,8,ref1,2,transformer,0.40,no\n' >> "$TMP/out/plasme_output.fasta_report.csv"
printf 'c3,8,ref2,3,transformer,0.10,no\n' >> "$TMP/out/plasme_output.fasta_report.csv"

bash "$ROOT/adapters/adapt_plasme.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
echo "the tool's own hard call (plasme_output.fasta) becomes pred_plasme.plasmid.fasta unchanged -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 3 ]] || { echo "FAIL: expected all 3 scored contigs in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2 c3; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
echo "candidates.fasta includes every scored contig, not just the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 3 ]] || { echo "FAIL: expected 3 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.40" || { echo "FAIL: expected c2's score=0.40 to round-trip" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every contig's real score, not just the hard call's -> PASS"

# An empty PLASMe output (no plasmids found) is a valid prediction, not a failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2"
: > "$TMP/out2/plasme_output.fasta"
cp "$TMP/out/plasme_output.fasta_report.csv" "$TMP/out2/plasme_output.fasta_report.csv"
bash "$ROOT/adapters/adapt_plasme.sh" "$TMP/out2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction" >&2; exit 1; }
echo "an empty plasme_output.fasta is scored as 'no plasmids', not a failure -> PASS"

echo "ALL PLASME ADAPTER TESTS PASSED"
