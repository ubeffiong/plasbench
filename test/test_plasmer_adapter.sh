#!/usr/bin/env bash
# Regression for adapters/adapt_plasmer.sh, against Plasmer's real (verified
# from its own scripts/Plasmer driver source, not just its README) results/
# shape: <prefix>.plasmer.predPlasmids.fa (Plasmer's own hard-call plasmid
# FASTA, taken unchanged) and <prefix>.plasmer.predProb.tsv (a REAL header
# row "Contig\tchromosome\tplasmid", covering ONLY the contigs that went
# through the random-forest model -- contigs excluded by Plasmer's own
# length rules have no probability row at all). Per adapters/SCORES.md,
# candidates.fasta's record set must exactly equal scores.tsv's, so both
# must be built from predProb.tsv's contig set only, NEVER predClass.tsv's
# wider set (which includes un-scored, length-filtered contigs). Plasmer is
# a per-contig classifier with no grouping output, so bins.tsv must always
# be header-only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The base assembly given as input to Plasmer (4 contigs: c1 plasmid-called,
# c2 chromosome-called (RF), c3 hard chromosome by length rule (no
# probability), c4 too short (also no probability)).
base_asm="$TMP/assembly.fasta"
printf '>c1\nACGTACGT\n>c2\nTTGGTTGG\n>c3\nCCAACCAA\n>c4\nAAAA\n' > "$base_asm"

mkdir -p "$TMP/out/results"
printf '>c1\nACGTACGT\n' > "$TMP/out/results/sample.plasmer.predPlasmids.fa"
{
    printf 'c1\tplasmid\n'
    printf 'c2\tchromosome\n'
    printf 'c3\tchromosome\n'
    printf 'c4\tshorter_than_500\n'
} > "$TMP/out/results/sample.plasmer.predClass.tsv"
{
    printf 'Contig\tchromosome\tplasmid\n'
    printf 'c1\t0.05\t0.95\n'
    printf 'c2\t0.80\t0.20\n'
} > "$TMP/out/results/sample.plasmer.predProb.tsv"

bash "$ROOT/adapters/adapt_plasmer.sh" "$TMP/out" "$base_asm" "$TMP/pred.plasmid.fasta"

[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 1 ]] || { echo "FAIL: expected 1 hard-call record (c1)" >&2; cat "$TMP/pred.plasmid.fasta" >&2; exit 1; }
grep -q '^>c1$' "$TMP/pred.plasmid.fasta" || { echo "FAIL: expected c1 in the hard call" >&2; exit 1; }
echo "Plasmer's own predPlasmids.fa is taken unchanged as the hard call -> PASS"

[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: bins.tsv must be header-only for a classification tool" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "bins.tsv is header-only (classification, not binning) -> PASS"

# candidates.fasta/scores.tsv must come from predProb.tsv's set (c1, c2)
# ONLY -- never predClass.tsv's wider set (c1..c4), since c3/c4 have no
# probability at all and including them would violate the exact-match
# contract in adapters/SCORES.md.
[[ "$(grep -c '^>' "$TMP/pred.candidates.fasta")" -eq 2 ]] || { echo "FAIL: expected exactly 2 scored contigs (c1, c2) in candidates.fasta" >&2; cat "$TMP/pred.candidates.fasta" >&2; exit 1; }
for id in c1 c2; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" || { echo "FAIL: candidates.fasta missing $id" >&2; exit 1; }; done
for id in c3 c4; do grep -q "^>$id\$" "$TMP/pred.candidates.fasta" && { echo "FAIL: candidates.fasta must NOT include un-scored $id" >&2; exit 1; }; done
echo "candidates.fasta is exactly predProb.tsv's contig set, excluding un-scored length-filtered contigs -> PASS"

[[ "$(tail -n +2 "$TMP/pred.scores.tsv" | wc -l)" -eq 2 ]] || { echo "FAIL: expected 2 score rows" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
awk -F'\t' '$1=="c2" {print $2}' "$TMP/pred.scores.tsv" | grep -qx "0.20" || { echo "FAIL: expected c2's plasmid probability 0.20 to round-trip from predProb.tsv's 'plasmid' column" >&2; cat "$TMP/pred.scores.tsv" >&2; exit 1; }
echo "scores.tsv carries every RF-scored contig's real plasmid probability, looked up by header name -> PASS"

# No predProb.tsv/predPlasmids.fa at all is a valid "predicted none", not a
# hard adapter failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2/results"
bash "$ROOT/adapters/adapt_plasmer.sh" "$TMP/out2" "$base_asm" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction when no predPlasmids.fa exists" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/pred2.scores.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: expected no scores when no predProb.tsv exists" >&2; exit 1; }
echo "no results/ output at all is scored as 'no plasmids', not a failure -> PASS"

# Multiple matches of either glob is an unexpected shape (Plasmer normally
# writes exactly one of each per sample) but must not silently misbehave:
# predPlasmids.fa hits are concatenated (with a warning), predProb.tsv uses
# only its first match (with a warning) -- both warnings must actually fire.
rm -rf "$TMP/out3"; mkdir -p "$TMP/out3/results"
printf '>c1\nACGTACGT\n' > "$TMP/out3/results/sampleA.plasmer.predPlasmids.fa"
printf '>c2\nTTGGTTGG\n' > "$TMP/out3/results/sampleB.plasmer.predPlasmids.fa"
{
    printf 'Contig\tchromosome\tplasmid\n'
    printf 'c1\t0.05\t0.95\n'
} > "$TMP/out3/results/sampleA.plasmer.predProb.tsv"
{
    printf 'Contig\tchromosome\tplasmid\n'
    printf 'c2\t0.10\t0.90\n'
} > "$TMP/out3/results/sampleB.plasmer.predProb.tsv"
stderr3="$TMP/adapt3.stderr"
bash "$ROOT/adapters/adapt_plasmer.sh" "$TMP/out3" "$base_asm" "$TMP/pred3.plasmid.fasta" 2> "$stderr3"

grep -q 'WARNING:.*predPlasmids.fa files found' "$stderr3" || { echo "FAIL: expected a multi-match warning for predPlasmids.fa" >&2; cat "$stderr3" >&2; exit 1; }
[[ "$(grep -c '^>' "$TMP/pred3.plasmid.fasta")" -eq 2 ]] || { echo "FAIL: expected both predPlasmids.fa matches concatenated (c1, c2)" >&2; cat "$TMP/pred3.plasmid.fasta" >&2; exit 1; }
for id in c1 c2; do grep -q "^>$id\$" "$TMP/pred3.plasmid.fasta" || { echo "FAIL: pred3.plasmid.fasta missing $id" >&2; exit 1; }; done
echo "multiple predPlasmids.fa matches: warned and concatenated -> PASS"

grep -q 'WARNING:.*predProb.tsv files found' "$stderr3" || { echo "FAIL: expected a multi-match warning for predProb.tsv" >&2; cat "$stderr3" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/pred3.scores.tsv" | wc -l)" -eq 1 ]] || { echo "FAIL: expected only the first predProb.tsv match's row (1)" >&2; cat "$TMP/pred3.scores.tsv" >&2; exit 1; }
grep -q '^c1' "$TMP/pred3.scores.tsv" || { echo "FAIL: expected sampleA's c1 (the first match, alphabetically) to be the one used" >&2; cat "$TMP/pred3.scores.tsv" >&2; exit 1; }
echo "multiple predProb.tsv matches: warned and only the first used -> PASS"

echo "ALL PLASMER ADAPTER TESTS PASSED"
