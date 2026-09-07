#!/usr/bin/env bash
# Regression for adapters/adapt_plascope.sh, against PlaScope's real
# (verified from its own source, plaScope.sh) output structure:
# <out>/<prefix>_PlaScope/PlaScope_predictions/<prefix>_plasmid.fasta (the
# tool's own hard call, written lazily -- absent entirely when zero contigs
# were classified plasmid) and .../Centrifuge_results/ (not used by this
# adapter, since PlaScope has no continuous score). PlaScope is a hard
# classifier with no grouping output, so bins.tsv must always be
# header-only, and there is no candidates.fasta/scores.tsv contract (unlike
# geNomad/PLASMe/RFPlasmid).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/out/sample_PlaScope/PlaScope_predictions" "$TMP/out/sample_PlaScope/Centrifuge_results"
printf '>c1\nACGTACGT\n' > "$TMP/out/sample_PlaScope/PlaScope_predictions/sample_plasmid.fasta"
printf '>c2\nTTGGTTGG\n' > "$TMP/out/sample_PlaScope/PlaScope_predictions/sample_chromosome.fasta"

bash "$ROOT/adapters/adapt_plascope.sh" "$TMP/out/sample_PlaScope" "$TMP/unused_assembly.fasta" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "*_plasmid.fasta becomes pred_plascope.plasmid.fasta unchanged, chromosome call ignored -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

[[ ! -e "$TMP/pred.candidates.fasta" ]] || { echo "FAIL: PlaScope has no continuous score; candidates.fasta should not be produced" >&2; exit 1; }
[[ ! -e "$TMP/pred.scores.tsv" ]] || { echo "FAIL: PlaScope has no continuous score; scores.tsv should not be produced" >&2; exit 1; }
echo "no candidates.fasta/scores.tsv (PlaScope has no continuous score, unlike the ml_classification tools) -> PASS"

# A completely missing *_plasmid.fasta (zero plasmid-classified contigs) is a
# valid "predicted none", not a hard adapter failure -- PlaScope writes that
# file lazily and it simply does not exist in this case.
rm -rf "$TMP/out2/sample_PlaScope"; mkdir -p "$TMP/out2/sample_PlaScope/PlaScope_predictions"
printf '>c1\nACGTACGT\n' > "$TMP/out2/sample_PlaScope/PlaScope_predictions/sample_chromosome.fasta"
bash "$ROOT/adapters/adapt_plascope.sh" "$TMP/out2/sample_PlaScope" "$TMP/unused_assembly.fasta" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no *_plasmid.fasta exists" >&2; exit 1; }
echo "a missing *_plasmid.fasta is scored as 'no plasmids', not a failure -> PASS"

echo "ALL PLASCOPE ADAPTER TESTS PASSED"
