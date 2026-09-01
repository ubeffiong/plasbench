#!/usr/bin/env bash
# Regression: a gplas release can emit one contig in more than one FASTA.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/output"
printf '>shared description\nAAAA\n>unique\nCCCC\n' > "$TMP/output/run_plasmids.fasta"
printf '>shared alternative\nTTTT\n>other\nGGGG\n' > "$TMP/output/run_bin_1.fasta"
bash "$ROOT/adapters/adapt_gplas.sh" "$TMP/output" /dev/null "$TMP/pred.plasmid.fasta"
[[ "$(grep -c '^>shared' "$TMP/pred.plasmid.fasta")" -eq 1 ]]
[[ "$(grep -c $'\tshared$' "$TMP/pred.bins.tsv")" -eq 1 ]]
[[ "$(grep -c '^>' "$TMP/pred.plasmid.fasta")" -eq 3 ]]
echo "GPLAS ADAPTER DEDUPLICATION TEST PASSED"
