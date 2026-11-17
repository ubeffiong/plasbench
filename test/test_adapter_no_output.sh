#!/usr/bin/env bash
# Regression (audit AU-008): an adapter must exit non-zero with "no output from <tool>" when the tool produced none of its real result files,
# whether the folder is empty or holds only a log (run.log). Before, 10 of the 16 adapters exited 0 with an EMPTY prediction, which stage 4 then recorded
# as a completed run with recall 0. A tool that ran and found no plasmids still writes a result file, and that stays a completed run with an empty prediction.
# Also: scripts/lib.sh tool_output_present no longer accepts a lone log, and PlaScope goes through run_adapter like the other tools.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '>c1\nACGTACGT\n' > "$TMP/asm.fasta"

# adapter | a result file a tool writes even when it finds no plasmid (relative to the folder the adapter is given), with its content
declare -A MARKER=(
    [genomad]='s_summary/s_plasmid_summary.tsv'
    [mob_recon]='contig_report.txt'
    [platon]='s.tsv'
    [plascope]='PlaScope_predictions/s_chromosome.fasta'
    [plasme]='plasme_output.fasta'
    [plasmer]='results/s.plasmer.predPlasmids.fa'
    [plasmidhunter]='predictions.tsv'
    [plasmidspades]='contigs.fasta'
    [rfplasmid]='prediction.csv'
    [plsmd]='s_report.tsv'
)
content_of() {
    case "$1" in
        plasmidhunter) printf 'Prediction\tProbability of 1\n' ;;
        rfplasmid) printf 'contigID\tprediction\n' ;;
        *) : ;;
    esac
}

for tool in "${!MARKER[@]}"; do
    # empty folder, then a folder holding only a log: both must fail with the reason
    for shape in empty logonly; do
        d="$TMP/$tool.$shape"; mkdir -p "$d"
        [[ "$shape" == "logonly" ]] && printf 'it ran\n' > "$d/run.log"
        rc=0; bash "$ROOT/adapters/adapt_$tool.sh" "$d" "$TMP/asm.fasta" "$TMP/$tool.$shape.plasmid.fasta" > /dev/null 2> "$TMP/$tool.$shape.err" || rc=$?
        [[ "$rc" != "0" ]] || { echo "FAIL: adapt_$tool.sh exited 0 on a $shape folder" >&2; exit 1; }
        grep -q "no output from $tool" "$TMP/$tool.$shape.err" || { echo "FAIL: adapt_$tool.sh must say 'no output from $tool' ($shape)" >&2; cat "$TMP/$tool.$shape.err" >&2; exit 1; }
    done
    # the tool ran and found nothing: its result file exists, so the run is complete with an empty prediction
    d="$TMP/$tool.ran"; mkdir -p "$(dirname "$d/${MARKER[$tool]}")"
    content_of "$tool" > "$d/${MARKER[$tool]}"
    printf 'it ran\n' > "$d/run.log"
    rc=0; bash "$ROOT/adapters/adapt_$tool.sh" "$d" "$TMP/asm.fasta" "$TMP/$tool.ran.plasmid.fasta" > /dev/null 2> "$TMP/$tool.ran.err" || rc=$?
    [[ "$rc" == "0" && ! -s "$TMP/$tool.ran.plasmid.fasta" && -f "$TMP/$tool.ran.plasmid.fasta" ]] || { echo "FAIL: adapt_$tool.sh must accept a tool that ran and found no plasmid (exit $rc)" >&2; cat "$TMP/$tool.ran.err" >&2; exit 1; }
done
echo "10 adapters: an empty or log-only folder fails with 'no output from <tool>'; a tool that ran and found nothing stays a completed empty prediction -> PASS"

# the six adapters that already failed on a missing output still do (the control)
for tool in gplas hybracter plassembler plasmidec; do
    d="$TMP/$tool.logonly"; mkdir -p "$d"; printf 'it ran\n' > "$d/run.log"
    if bash "$ROOT/adapters/adapt_$tool.sh" "$d" "$TMP/asm.fasta" "$TMP/$tool.plasmid.fasta" > /dev/null 2>&1; then
        echo "FAIL: adapt_$tool.sh must fail on a log-only folder" >&2; exit 1
    fi
done
echo "the other adapters still fail on a log-only folder -> PASS"

# lib.sh: a lone log is not tool output
out="$(bash -c "source '$ROOT/scripts/lib.sh'
d='$TMP/lib_logonly'; mkdir -p \"\$d\"; printf x > \"\$d/run.log\"; printf x > \"\$d/tool.err\"
tool_output_present \"\$d\" && echo present-logonly
printf x > \"\$d/result.tsv\"
tool_output_present \"\$d\" && echo present-real
true")"
[[ "$out" == "present-real" ]] || { echo "FAIL: tool_output_present must ignore logs and accept a real file (got: $out)" >&2; exit 1; }
echo "tool_output_present ignores logs -> PASS"

# stage 4: PlaScope that writes only a log is FAILED (it used to bypass run_adapter and be completed with an empty prediction)
mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/db"
printf '>c1\nACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tGCF_1\tSRR1\tEscherichia coli\n' > "$TMP/sheet.tsv"
cat > "$TMP/bin/plaScope.sh" <<'EOS'
#!/usr/bin/env bash
out="" sample=""
while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2;; --sample) sample="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out/${sample}_PlaScope"; echo "started" > "$out/${sample}_PlaScope/run.log"
EOS
chmod +x "$TMP/bin/plaScope.sh"
rc=0
PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    ONLY_TOOL=plascope PLASCOPE_ECOLI_DB="$TMP/db/chromosome_plasmid_db" ALLOW_ALL_TOOLS_FAILED=1 TOOL_RETRIES=0 \
    bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1 || rc=$?
[[ "$rc" == "0" ]] || { echo "FAIL: stage 4 (exit $rc)" >&2; tail -5 "$TMP/stage.log" >&2; exit 1; }
status="$(awk -F'\t' '$2 == "plascope" {print $3 "|" $5}' "$TMP/results/tool_status.tsv")"
[[ "$status" == failed\|*"no output from plascope"* ]] || { echo "FAIL: a log-only PlaScope run must be failed with 'no output from plascope' (got: $status)" >&2; exit 1; }
[[ ! -e "$TMP/results/s1/pred_plascope.plasmid.fasta" ]] || { echo "FAIL: no prediction may be left for a failed run" >&2; exit 1; }
echo "stage 4: a PlaScope run that left only a log is failed with the reason, no empty prediction -> PASS"

echo "ALL ADAPTER NO-OUTPUT TESTS PASSED"
