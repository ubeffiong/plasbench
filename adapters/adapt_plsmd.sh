#!/usr/bin/env bash
# Adapter: plsMD (--processing) -> standardized predicted-plasmid FASTA.
#
# plsMD --processing writes <out>/plasmid_files/<sample>_plasmid_contigs.fasta.
# Each record (<sample>_plsMD<N>) is one reconstructed plasmid: the assembly
# contigs that matched one reference plasmid, concatenated in reference order
# with assembly overlaps trimmed. The output is therefore already plasmid-level,
# so every record is its own bin (like Plassembler).
#
# An absent or empty plasmid_files directory is a legitimate prediction ("no
# plasmid reconstructed") and yields an empty FASTA and a header-only bins
# file. The adapter fails only when the output cannot be interpreted: a record
# without a header id, an id repeated across files, or a sequence character
# outside A/C/G/T/N.
#
# The plsMD report (<sample>_report.tsv: reconstructed, rep_type, sseqid,
# coverage_percentage, bases, type, PCN, mob_typer columns) is copied to
# <stem>.plsmd_report.tsv so copy number and replicon evidence stay available
# as tool evidence. It is never used for scoring.
#
# Usage: adapt_plsmd.sh <plsmd_processing_output_dir> <base_assembly_fasta> <out_fasta>
# The base assembly is unused here; kept for the one adapter calling convention.
set -euo pipefail
OUT_DIR="$1"
# shellcheck disable=SC2034  # BASE_ASM: positional adapter contract, unused here
BASE_ASM="${2:-}"
OUT_FASTA="$3"

STEM="${OUT_FASTA%.plasmid.fasta}"
[[ "$STEM" == "$OUT_FASTA" ]] && STEM="${OUT_FASTA%.*}"
BINS="${STEM}.bins.tsv"
REPORT_OUT="${STEM}.plsmd_report.tsv"

: > "$OUT_FASTA"
printf 'bin_id\tsequence_id\n' > "$BINS"

shopt -s nullglob
fastas=("$OUT_DIR"/plasmid_files/*_plasmid_contigs.fasta)
reports=("$OUT_DIR"/*_report.tsv "$OUT_DIR"/plasmid_files/*_report.tsv)
shopt -u nullglob

# Optional evidence file: first file keeps its header, later files add rows only.
if [[ "${#reports[@]}" -gt 0 ]]; then
    : > "$REPORT_OUT"
    first=1
    for r in "${reports[@]}"; do
        if [[ "$first" -eq 1 ]]; then
            tr -d '\r' < "$r" >> "$REPORT_OUT"
            first=0
        else
            tr -d '\r' < "$r" | awk 'NR > 1' >> "$REPORT_OUT"
        fi
    done
fi

if [[ "${#fastas[@]}" -eq 0 ]]; then
    echo "[adapt_plsmd] no plasmid_files/*_plasmid_contigs.fasta in $OUT_DIR (empty prediction, scored as such)" >&2
    exit 0
fi

TMP_BINS="$(mktemp)"
trap 'rm -f "$TMP_BINS"' EXIT

# Validate every record and emit "id<TAB>id" rows. Exit 1 on any defect.
if ! awk -v bins="$TMP_BINS" '
    function fail(msg) { print "[adapt_plsmd] ERROR: " msg > "/dev/stderr"; bad = 1; exit 1 }
    { sub(/\r$/, "") }
    /^>/ {
        id = substr($1, 2)
        if (id == "") fail(FILENAME ":" FNR ": record without a header id")
        if (id in seen) fail("duplicate record id \"" id "\" (" FILENAME ":" FNR ")")
        seen[id] = 1
        print id "\t" id >> bins
        n++
        next
    }
    /^[ \t]*$/ { next }
    {
        if (n == 0) fail(FILENAME ":" FNR ": sequence before any header")
        if ($0 ~ /[^ACGTNacgtn]/) fail(FILENAME ":" FNR ": non-ACGTN character in record \"" id "\"")
    }
    END { if (!bad) print n + 0 > "/dev/stderr" }
' "${fastas[@]}" 2> "$TMP_BINS.err"; then
    cat "$TMP_BINS.err" >&2
    rm -f "$TMP_BINS.err"
    : > "$OUT_FASTA"
    exit 1
fi
RECORDS="$(tail -n 1 "$TMP_BINS.err")"
rm -f "$TMP_BINS.err"

for f in "${fastas[@]}"; do
    tr -d '\r' < "$f" >> "$OUT_FASTA"
done
[[ -s "$TMP_BINS" ]] && cat "$TMP_BINS" >> "$BINS"

if [[ "${RECORDS:-0}" -eq 0 ]]; then
    echo "[adapt_plsmd] plsMD reconstructed no plasmids for this isolate (empty prediction, scored as such)" >&2
else
    echo "[adapt_plsmd] wrote $OUT_FASTA ($RECORDS reconstructed plasmid record(s))" >&2
fi
