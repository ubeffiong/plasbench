#!/usr/bin/env bash
# Audit AU-033 and AU-035 (second part):
#   1. with no GNU time (PLASBENCH_TIME_BIN points at nothing) stage 4 warns, peak_rss_kb stays blank and tool_run_resources.tsv says
#      "/usr/bin/time not installed" for the run (this was the untested "blank-memory note");
#   2. a tool whose prediction is not valid FASTA is marked failed AT STAGE 4 (reason names the problem), loses its completion marker and
#      has no prediction path in tool_status.tsv; an empty prediction and a good one still complete;
#   3. database pre-flight for PlaScope (species database), plsMD (BLAST index prefix) and MOB-recon (an incomplete MOB-suite database): the tool is
#      never launched and the row is failed with the path in the reason.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/config" "$TMP/data/s1"
printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\torganism\ns1\tNA\tSRR1\tEscherichia coli\n' > "$TMP/config/accessions.tsv"

# a fake platon whose prediction content comes from $PRED_KIND
cat > "$TMP/bin/platon" <<'EOF'
#!/usr/bin/env bash
outdir="" prefix=""; while [[ $# -gt 0 ]]; do case "$1" in --output) outdir="$2"; shift 2;; --prefix) prefix="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$outdir"
case "${PRED_KIND:-good}" in
    good)  printf '>c1\nACGT\n' > "$outdir/$prefix.plasmid.fasta" ;;
    empty) : > "$outdir/$prefix.plasmid.fasta" ;;
    bad)   printf 'ACGT not a header\n>c1\nAC GT!!\n' > "$outdir/$prefix.plasmid.fasta" ;;
esac
printf 'ID\n' > "$outdir/$prefix.tsv"
EOF
chmod +x "$TMP/bin/platon"
mkdir -p "$TMP/platon_db"

run() {
    local name="$1" script="$2"; shift 2
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/res_$name" LOG_DIR="$TMP/logs_$name" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 PATH="$TMP/bin:$PATH" "$@" \
        timeout 120 bash "$ROOT/scripts/$script" > "$TMP/$name.log" 2>&1
}
field() { awk -F'\t' -v t="$2" -v c="$3" '$2 == t {print $c}' "$TMP/res_$1/tool_status.tsv"; }

# ---- 1. blank memory note without GNU time ----------------------------------------------------------------------------------
rc=0; run notime 04_run_tools.sh ONLY_TOOL=platon PLATON_DB="$TMP/platon_db" PLASBENCH_TIME_BIN="$TMP/no_such_time" || rc=$?
[[ "$rc" == "0" ]] || { echo "FAIL: stage 4 without GNU time must still run (exit $rc)" >&2; tail -5 "$TMP/notime.log" >&2; exit 1; }
grep -q "is not installed: peak memory" "$TMP/notime.log" || { echo "FAIL: a warning that memory cannot be measured is expected" >&2; head -8 "$TMP/notime.log" >&2; exit 1; }
RES="$TMP/res_notime/tool_run_resources.tsv"
[[ -z "$(awk -F'\t' '$2 == "platon" {print $5}' "$RES")" ]] || { echo "FAIL: peak_rss_kb must be blank without GNU time" >&2; cat "$RES" >&2; exit 1; }
[[ "$(awk -F'\t' '$2 == "platon" {print $6}' "$RES")" == "/usr/bin/time not installed" ]] || { echo "FAIL: rss_note must say /usr/bin/time is not installed" >&2; cat "$RES" >&2; exit 1; }
[[ "$(field notime platon 3)" == "completed" ]] || { echo "FAIL: the run must still complete" >&2; exit 1; }
echo "no GNU time: warning, blank peak_rss_kb and the note in tool_run_resources.tsv -> PASS"

# ---- 2. malformed prediction FASTA at stage 4 ------------------------------------------------------------------------------------
rc=0; run bad 04_run_tools.sh ONLY_TOOL=platon PLATON_DB="$TMP/platon_db" PRED_KIND=bad TOOL_RETRIES=0 ALLOW_ALL_TOOLS_FAILED=1 || rc=$?
[[ "$(field bad platon 3)" == "failed" && "$(field bad platon 5)" == *"malformed prediction FASTA"* ]] || { echo "FAIL: a malformed prediction must be failed at stage 4 with the reason" >&2; cat "$TMP/res_bad/tool_status.tsv" >&2; exit 1; }
[[ -z "$(field bad platon 4)" ]] || { echo "FAIL: a malformed prediction must not be listed as the tool's prediction" >&2; exit 1; }
[[ ! -e "$TMP/res_bad/s1/.platon.complete" ]] || { echo "FAIL: the completion marker of a malformed prediction must be removed" >&2; exit 1; }
rc=0; run good 04_run_tools.sh ONLY_TOOL=platon PLATON_DB="$TMP/platon_db" PRED_KIND=good || rc=$?
[[ "$(field good platon 3)" == "completed" ]] || { echo "FAIL: a well-formed prediction must complete" >&2; cat "$TMP/res_good/tool_status.tsv" >&2; exit 1; }
rc=0; run empty 04_run_tools.sh ONLY_TOOL=platon PLATON_DB="$TMP/platon_db" PRED_KIND=empty || rc=$?
[[ "$(field empty platon 3)" == "completed" ]] || { echo "FAIL: an empty prediction (no plasmid found) must still complete" >&2; cat "$TMP/res_empty/tool_status.tsv" >&2; exit 1; }
echo "malformed prediction FASTA is failed at stage 4; good and empty predictions complete -> PASS"
printf '>a\nACGT\n' > "$TMP/ok.fa"
python3 "$ROOT/python/check_prediction_fasta.py" "$TMP/ok.fa" || { echo "FAIL: checker rejects a good file" >&2; exit 1; }
printf '>a\nACGT\n' | gzip > "$TMP/ok.fa.gz"; head -c 20 "$TMP/ok.fa.gz" > "$TMP/trunc.fa.gz"
python3 "$ROOT/python/check_prediction_fasta.py" "$TMP/ok.fa.gz" || { echo "FAIL: checker rejects good gzip" >&2; exit 1; }
if python3 "$ROOT/python/check_prediction_fasta.py" "$TMP/trunc.fa.gz" > /dev/null; then echo "FAIL: truncated gzip must be rejected" >&2; exit 1; fi
echo "checker: good, gzip and truncated-gzip cases -> PASS"

# ---- 3. database pre-flight ------------------------------------------------------------------------------------------------------
for t in plaScope.sh plsmd mob_recon; do printf '#!/usr/bin/env bash\necho launched >> "%s/%s.launched"\nexit 1\n' "$TMP" "$t" > "$TMP/bin/$t"; chmod +x "$TMP/bin/$t"; done
rc=0; run pscope 04_run_tools.sh ONLY_TOOL=plascope PLASCOPE_ECOLI_DB="$TMP/missing/ecoli_db" RUN_PLASCOPE=1 TOOL_RETRIES=2 ALLOW_ALL_TOOLS_FAILED=1 || rc=$?
[[ ! -e "$TMP/plaScope.sh.launched" ]] || { echo "FAIL: PlaScope must not launch without its species database" >&2; exit 1; }
[[ "$(field pscope plascope 3)" == "infrastructure_failure" && "$(field pscope plascope 5)" == *"missing/ecoli_db"* ]] || { echo "FAIL: PlaScope pre-flight row" >&2; cat "$TMP/res_pscope/tool_status.tsv" >&2; tail -3 "$TMP/pscope.log" >&2; exit 1; }
rc=0; run plsmd 04_run_tools.sh RUN_PLSMD=1 ASSEMBLER=unicycler PLSMD_DB="$TMP/missing/plsdb" PLSMD_CMD=plsmd TOOL_RETRIES=2 ALLOW_ALL_TOOLS_FAILED=1 ONLY_TOOL=plsmd || rc=$?
[[ ! -e "$TMP/plsmd.launched" ]] || { echo "FAIL: plsMD must not launch without its BLAST index" >&2; exit 1; }
[[ "$(field plsmd plsmd 3)" == "infrastructure_failure" && "$(field plsmd plsmd 5)" == *"missing/plsdb"* ]] || { echo "FAIL: plsMD pre-flight row" >&2; cat "$TMP/res_plsmd/tool_status.tsv" >&2; tail -3 "$TMP/plsmd.log" >&2; exit 1; }
echo "missing PlaScope and plsMD databases are caught before any launch, with the path in the reason -> PASS"
# MOB-suite: mobsuite_db_dir follows the mob_recon wrapper; a wrapper whose database folder is incomplete is refused before launch
mkdir -p "$TMP/mobenv/bin" "$TMP/mobenv/lib/python3.10/site-packages/mob_suite/databases"
printf '#!/usr/bin/env bash\necho launched >> "%s/mob_recon.launched"\nexit 1\n' "$TMP" > "$TMP/mobenv/bin/mob_recon"; chmod +x "$TMP/mobenv/bin/mob_recon"
touch "$TMP/mobenv/lib/python3.10/site-packages/mob_suite/__init__.py"
printf '#!/usr/bin/env bash
exec "%s/mobenv/bin/mob_recon" "$@"
' "$TMP" > "$TMP/bin/mob_recon"; chmod +x "$TMP/bin/mob_recon"   # a shim that names the real path, like the container's
if [[ -n "$(env PATH="$TMP/bin:$PATH" bash -c "source '$ROOT/scripts/lib.sh'; mobsuite_db_dir" 2>/dev/null)" ]]; then
    rm -f "$TMP/mob_recon.launched"
    rc=0; run mob 04_run_tools.sh ONLY_TOOL=mob_recon TOOL_RETRIES=2 ALLOW_ALL_TOOLS_FAILED=1 || rc=$?
    [[ ! -e "$TMP/mob_recon.launched" && "$(field mob mob_recon 3)" == "infrastructure_failure" ]] || { echo "FAIL: MOB-recon with an incomplete database must not launch" >&2; cat "$TMP/res_mob/tool_status.tsv" >&2; exit 1; }
    echo "an incomplete MOB-suite database is caught before any launch -> PASS"
else
    echo "FAIL: mobsuite_db_dir did not resolve the fake MOB-suite environment" >&2; exit 1
fi
echo "ALL STAGE 4 PREFLIGHT AND FASTA TESTS PASSED"
