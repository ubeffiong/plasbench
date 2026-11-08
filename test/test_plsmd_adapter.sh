#!/usr/bin/env bash
# Regression: the plsMD adapter concatenates reconstructed plasmids, treats an
# empty or absent result as a valid empty prediction, and rejects uninterpretable output.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. two records across two files, plus a report
mkdir -p "$TMP/a/plasmid_files"
printf '>s1_plsMD1 extra words\nACGTACGT\nACGT\n' > "$TMP/a/plasmid_files/s1_plasmid_contigs.fasta"
printf '>s2_plsMD1\nGGGGCCCCNN\n' > "$TMP/a/plasmid_files/s2_plasmid_contigs.fasta"
printf 'reconstructed\trep_type\tPCN\ns1_plsMD1\tIncFII\t2.5\n' > "$TMP/a/s1_report.tsv"
bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/a" /dev/null "$TMP/a.plasmid.fasta"
[[ "$(grep -c '^>' "$TMP/a.plasmid.fasta")" -eq 2 ]]
[[ "$(head -n 1 "$TMP/a.bins.tsv")" == $'bin_id\tsequence_id' ]]
[[ "$(grep -c $'^s1_plsMD1\ts1_plsMD1$' "$TMP/a.bins.tsv")" -eq 1 ]]
[[ "$(grep -c $'^s2_plsMD1\ts2_plsMD1$' "$TMP/a.bins.tsv")" -eq 1 ]]
[[ "$(wc -l < "$TMP/a.bins.tsv" | tr -d ' ')" -eq 3 ]]
grep -q 'IncFII' "$TMP/a.plsmd_report.tsv"

# 2. empty tree: directory exists, no records
mkdir -p "$TMP/b/plasmid_files"
: > "$TMP/b/plasmid_files/s1_plasmid_contigs.fasta"
bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/b" /dev/null "$TMP/b.plasmid.fasta"
[[ ! -s "$TMP/b.plasmid.fasta" ]]
[[ "$(cat "$TMP/b.bins.tsv")" == $'bin_id\tsequence_id' ]]

# 3. duplicate ids across files must fail
mkdir -p "$TMP/c/plasmid_files"
printf '>dup\nACGT\n' > "$TMP/c/plasmid_files/x_plasmid_contigs.fasta"
printf '>dup\nTTTT\n' > "$TMP/c/plasmid_files/y_plasmid_contigs.fasta"
if bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/c" /dev/null "$TMP/c.plasmid.fasta" 2>/dev/null; then
    echo "FAIL: duplicate ids were accepted" >&2; exit 1
fi

# 4. no plasmid_files directory: empty and valid
mkdir -p "$TMP/d"
bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/d" /dev/null "$TMP/d.plasmid.fasta"
[[ ! -s "$TMP/d.plasmid.fasta" ]]
[[ "$(cat "$TMP/d.bins.tsv")" == $'bin_id\tsequence_id' ]]

# 5. bad character and missing id must fail
mkdir -p "$TMP/e/plasmid_files" "$TMP/f/plasmid_files"
printf '>bad\nACGTXX\n' > "$TMP/e/plasmid_files/x_plasmid_contigs.fasta"
if bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/e" /dev/null "$TMP/e.plasmid.fasta" 2>/dev/null; then
    echo "FAIL: non-ACGTN accepted" >&2; exit 1
fi
printf '>\nACGT\n' > "$TMP/f/plasmid_files/x_plasmid_contigs.fasta"
if bash "$ROOT/adapters/adapt_plsmd.sh" "$TMP/f" /dev/null "$TMP/f.plasmid.fasta" 2>/dev/null; then
    echo "FAIL: headerless id accepted" >&2; exit 1
fi
echo "PLSMD ADAPTER TEST PASSED"
