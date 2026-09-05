#!/usr/bin/env bash
# Regression for adapters/adapt_genomad.sh, against geNomad's real (verified)
# output structure: <out>/<prefix>_summary/<prefix>_plasmid.fna (the tool's
# own hard call) and <out>/<prefix>_aggregated_classification/
# <prefix>_aggregated_classification.tsv (seq_name, plasmid_score for every
# INPUT contig, the wider candidates universe). geNomad is a per-contig
# classifier with no grouping output, so bins.tsv must always be header-only
# ("not applicable" is decided by config/tool_capabilities.tsv's
# binning_capable=no, not by this adapter).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The base assembly given as input to geNomad (3 contigs: c1, c2, c3).
base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

mkdir -p "$TMP/out/sample_summary" "$TMP/out/sample_aggregated_classification"
# Hard call: only c1 survives geNomad's own post-classification filtering.
printf '>c1\nACGTACGT\n' > "$TMP/out/sample_summary/sample_plasmid.fna"
# Every input contig was scored, including c2 and c3 which the hard call omitted.
printf 'seq_name\tlength\ttopology\tn_genes\tgenetic_code\tplasmid_score\tfdr\n' \
    > "$TMP/out/sample_aggregated_classification/sample_aggregated_classification.tsv"
printf 'c1\t8\tno_conjugation_genes\t2\t11\t0.95\t0.01\n' >> "$TMP/out/sample_aggregated_classification/sample_aggregated_classification.tsv"
printf 'c2\t8\tno_conjugation_genes\t1\t11\t0.30\t0.20\n' >> "$TMP/out/sample_aggregated_classification/sample_aggregated_classification.tsv"
printf 'c3\t8\tno_conjugation_genes\t1\t11\t0.05\t0.50\n' >> "$TMP/out/sample_aggregated_classification/sample_aggregated_classification.tsv"

bash "$ROOT/adapters/adapt_genomad.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "the tool's own hard call (plasmid_summary's plasmid.fna) becomes pred_genomad.plasmid.fasta unchanged -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 3 ]] || { echo "FAIL: expected all 3 scored contigs in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2 c3; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
echo "candidates.fasta includes every scored contig, not just the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 3 ]] || { echo "FAIL: expected 3 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.30" || { echo "FAIL: expected c2's plasmid_score=0.30 to round-trip" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every contig's real plasmid_score, not just the hard call's -> PASS"

# No plasmid.fna at all is a valid "predicted none", not a hard adapter failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2/sample_summary" "$TMP/out2/sample_aggregated_classification"
cp "$TMP/out/sample_aggregated_classification/sample_aggregated_classification.tsv" "$TMP/out2/sample_aggregated_classification/"
bash "$ROOT/adapters/adapt_genomad.sh" "$TMP/out2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no plasmid.fna exists" >&2; exit 1; }
echo "no *_plasmid.fna is scored as 'no plasmids', not a failure -> PASS"

echo "ALL GENOMAD ADAPTER TESTS PASSED"
