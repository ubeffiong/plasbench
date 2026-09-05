#!/usr/bin/env bash
# Regression for adapters/adapt_hybracter.sh: it must find *_plasmid.fasta
# recursively under the Hybracter output directory (its FINAL_OUTPUT/complete
# vs incomplete/ nesting varies by sample), concatenate every record it finds
# into one prediction FASTA, and give each record its own bin -- and it must
# succeed (not fail) on an empty *_plasmid.fasta, since "no plasmids found" is
# a real prediction, not an adapter error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Simulate the nested FINAL_OUTPUT/complete/ layout the real tool produces.
mkdir -p "$TMP/out/FINAL_OUTPUT/complete"
printf '>1 len=2000 copy_number_short_read=2.5\nACGT\n>2 len=900 copy_number_short_read=8.1\nTTGA\n' \
    > "$TMP/out/FINAL_OUTPUT/complete/sample_plasmid.fasta"

bash "$ROOT/adapters/adapt_hybracter.sh" "$TMP/out" "" "$TMP/pred.plasmid.fasta"
[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 2 ]] || { echo "FAIL: expected 2 plasmid records" >&2; exit 1; }
[[ "$(tail -n +2 "$TMP/pred.bins.tsv" | wc -l)" -eq 2 ]] || { echo "FAIL: expected 2 bin rows" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
grep -qx $'1\t1' "$TMP/pred.bins.tsv" || { echo "FAIL: expected bin '1' mapped to sequence '1'" >&2; cat "$TMP/pred.bins.tsv" >&2; exit 1; }
echo "recursively finds *_plasmid.fasta and gives each record its own bin -> PASS"

# An empty result (found under FINAL_OUTPUT/incomplete/ this time, a
# different subdirectory) is a valid "no plasmids" prediction, not a failure.
rm -rf "$TMP/out2"; mkdir -p "$TMP/out2/FINAL_OUTPUT/incomplete"
: > "$TMP/out2/FINAL_OUTPUT/incomplete/sample_plasmid.fasta"
bash "$ROOT/adapters/adapt_hybracter.sh" "$TMP/out2" "" "$TMP/pred2.plasmid.fasta"
[[ ! -s "$TMP/pred2.plasmid.fasta" ]] || { echo "FAIL: expected an empty prediction" >&2; exit 1; }
echo "an empty *_plasmid.fasta under incomplete/ is scored as 'no plasmids', not a failure -> PASS"

# No *_plasmid.fasta anywhere is a genuine adapter failure.
rm -rf "$TMP/out3"; mkdir -p "$TMP/out3/FINAL_OUTPUT"
if bash "$ROOT/adapters/adapt_hybracter.sh" "$TMP/out3" "" "$TMP/pred3.plasmid.fasta" 2>/dev/null; then
    echo "FAIL: adapter should fail when no *_plasmid.fasta exists at all" >&2; exit 1
fi
echo "no *_plasmid.fasta anywhere is a genuine adapter failure -> PASS"

echo "ALL HYBRACTER ADAPTER TESTS PASSED"
