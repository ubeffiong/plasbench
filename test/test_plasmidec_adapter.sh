#!/usr/bin/env bash
# Regression for adapters/adapt_plasmidec.sh against PlasmidEC's documented output: <out>/ensemble_output.csv (every classified
# contig, each classifier's call, Plasmid_count votes, Combined_prediction) and <out>/plasmid_contigs.fasta (its own hard call).
# A finished run with no plasmid contigs is "predicted none"; a run without ensemble_output.csv did not finish and must FAIL, not
# look like "no plasmids found". PlasmidEC classifies contigs only, so bins.tsv is always header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n' > "$base_asm"

mkdir -p "$TMP/out"
{
    printf 'Contig_name,Genome_id,RFPlasmid,PlaScope,Platon,Plasmid_count,Combined_prediction\n'
    printf 'c1,s,plasmid,plasmid,chromosome,2,plasmid\n'
    printf 'c2,s,chromosome,chromosome,chromosome,0,chromosome\n'
} > "$TMP/out/ensemble_output.csv"
printf '>c1\nACGTACGT\n' > "$TMP/out/plasmid_contigs.fasta"
bash "$ROOT/adapters/adapt_plasmidec.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"
if [[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -ne 1 ]] || ! grep -q '^>c1$' "$TMP/pred.plasmid.fasta"; then
    echo "FAIL: expected exactly c1" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1
fi
echo "PlasmidEC's own plasmid_contigs.fasta is taken unchanged as the hard call -> PASS"
[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

# finished, nothing called plasmid: no plasmid_contigs.fasta -> predicted none, success
rm -f "$TMP/out/plasmid_contigs.fasta"
bash "$ROOT/adapters/adapt_plasmidec.sh" "$TMP/out" "$base_asm" "$TMP/none.plasmid.fasta" 2> "$TMP/none.err"
if [[ -s "$TMP/none.plasmid.fasta" ]] || ! grep -q "predicted none" "$TMP/none.err"; then
    echo "FAIL: expected an empty prediction, reported as predicted none" >&2; cat "$TMP/none.err" >&2; exit 1
fi
echo "a finished run with no plasmid contigs is predicted none -> PASS"

# an empty plasmid_contigs.fasta behaves the same
: > "$TMP/out/plasmid_contigs.fasta"
bash "$ROOT/adapters/adapt_plasmidec.sh" "$TMP/out" "$base_asm" "$TMP/none2.plasmid.fasta" 2>/dev/null
[[ ! -s "$TMP/none2.plasmid.fasta" ]] || { echo "FAIL: an empty plasmid_contigs.fasta must give an empty prediction" >&2; exit 1; }
echo "an empty plasmid_contigs.fasta is predicted none -> PASS"

# a crashed run (no ensemble_output.csv) must fail, never look like 'no plasmids'
rm -f "$TMP/out/ensemble_output.csv" "$TMP/out/plasmid_contigs.fasta"
if bash "$ROOT/adapters/adapt_plasmidec.sh" "$TMP/out" "$base_asm" "$TMP/crash.plasmid.fasta" 2> "$TMP/crash.err"; then
    echo "FAIL: a run with no ensemble_output.csv must fail" >&2; exit 1
fi
grep -q "did not finish" "$TMP/crash.err" || { echo "FAIL: expected a 'did not finish' message" >&2; cat "$TMP/crash.err" >&2; exit 1; }
echo "a run without ensemble_output.csv fails instead of reporting an empty prediction -> PASS"

echo "ALL PLASMIDEC ADAPTER TESTS PASSED"
