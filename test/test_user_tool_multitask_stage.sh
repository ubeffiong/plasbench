#!/usr/bin/env bash
# One command, several task rows (offline): a tool that declares two or three tasks runs ONCE per sample and stage 4 converts
# the same output into one row per task (<name>, <name>__<task>), each reused or reconverted on its own.
#   two tasks, two output types      -> command runs once; both rows completed; classification has scores, binning has bins
#   re-run                           -> both rows reused, the command does not run again
#   one row's marker removed         -> only that row is converted again (no second run)
#   format = auto (contig table + FASTA) -> binning, classification and reassembly rows from one run, choice in tool_status
#   a task the output cannot serve   -> that row is skipped with the reason; the others complete
#   a tool installed from a local folder -> {src} in the command; a changed source changes the fingerprint and re-runs
#   the registry and display names   -> one row and one label per task
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/data/s1" "$TMP/config" "$TMP/tools"
printf '>c1 len=10\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"
NATIVE_TMP="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")"

mkdir -p "$TMP/tools/ut_multi"
cat > "$TMP/tools/ut_multi/fake.py" <<'EOF'
import sys
counter, outdir = sys.argv[1], sys.argv[2]
open(counter, "a").write("run\n")
with open(outdir + "/bins.tsv", "w") as fh:
    fh.write("contig\tbin\nc1\tB1\nc2\tB1\n")
with open(outdir + "/labels.csv", "w") as fh:
    fh.write("contig,call,p\nc1,plasmid,0.9\nc2,plasmid,0.8\nc3,chromosome,0.1\n")
EOF
cat > "$TMP/tools/ut_multi/plasbench-tool.ini" <<EOF
[tool]
name = ut_multi
display_name = UT Multi
task = classification, binning_reconstruction
analysis_track = short_read
[install]
method = none
[run]
mode = command
command = python3 {tool_dir}/fake.py $NATIVE_TMP/counter {outdir}
requires = contigs
[output]
format = contig_bins, contig_labels
[output.contig_bins]
path = bins.tsv
contig_column = contig
bin_column = bin
[output.contig_labels]
path = labels.csv
delimiter = comma
contig_column = contig
label_column = call
score_column = p
EOF

# format = auto over a contig table and plasmid FASTA files; reassembly is declared too.
mkdir -p "$TMP/tools/ut_auto"
cat > "$TMP/tools/ut_auto/fake.py" <<'EOF'
import sys
outdir = sys.argv[1]
with open(outdir + "/contig_report.txt", "w") as fh:
    fh.write("sample_id\tmolecule_type\tprimary_cluster_id\tcontig_id\nS\tplasmid\tAA1\tc1\nS\tplasmid\tAA1\tc2\nS\tchromosome\t-\tc3\n")
open(outdir + "/plasmid_AA1.fasta", "w").write(">c1\nACGTACGTAC\n")
open(outdir + "/plasmid_AA2.fasta", "w").write(">other\nACGT\n")
EOF
cat > "$TMP/tools/ut_auto/plasbench-tool.ini" <<'EOF'
[tool]
name = ut_auto
task = binning_reconstruction, classification, sequence_reassembly
analysis_track = short_read
[install]
method = none
[run]
mode = command
command = python3 {tool_dir}/fake.py {outdir}
requires = contigs
[output]
format = auto
candidates = contig_report.txt, plasmid_*.fasta
EOF

# A tool whose output cannot serve one of its declared tasks (auto): reassembly is skipped, binning completes.
mkdir -p "$TMP/tools/ut_partial"
cat > "$TMP/tools/ut_partial/plasbench-tool.ini" <<'EOF'
[tool]
name = ut_partial
task = binning_reconstruction, sequence_reassembly
analysis_track = short_read
[install]
method = none
[run]
mode = command
command = printf 'contig\tbin\nc1\tB1\n' > {outdir}/b.tsv
requires = contigs
[output]
format = auto
candidates = b.tsv
EOF

# A tool installed from a folder on this computer: {src} is its copy.
mkdir -p "$TMP/local_src/bin" "$TMP/tools/ut_local"
cat > "$TMP/local_src/bin/run.py" <<'EOF'
import sys
open(sys.argv[1] + "/bins.tsv", "w").write("contig\tbin\nc1\tB1\n")
EOF
cat > "$TMP/tools/ut_local/plasbench-tool.ini" <<EOF
[tool]
name = ut_local
task = binning_reconstruction
analysis_track = short_read
[install]
method = local
path = $NATIVE_TMP/local_src
mode = copy
[run]
mode = command
command = python3 {src}/bin/run.py {outdir}
requires = contigs
[output]
format = contig_bins
path = bins.tsv
contig_column = contig
bin_column = bin
EOF

run_stage() {
    rm -rf "$TMP/logs"
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        PLASBENCH_TOOLS_PATH="$TMP/tools" REQUIRE_CURATED_METADATA=0 RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 \
        RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 RUN_PLSMD=0 TOOL_RETRIES=0 "$@" \
        bash ${STAGE_TRACE:+-x} "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}
STATUS="$TMP/results/tool_status.tsv"
col() { awk -F'\t' -v t="$1" -v c="$2" '$2==t {print $c}' "$STATUS" | tail -1; }
fail() { echo "FAIL: $*" >&2; cat "$STATUS" >&2 2>/dev/null || true; tail -${FAIL_TAIL:-30} "$TMP/stage.log" >&2; tail -n 20 "$TMP"/logs/*.log >&2 2>/dev/null || true; exit 1; }
runs() { wc -l < "$TMP/counter" | tr -d ' '; }
R="$TMP/results/s1"

PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/user_tools.py" fetch ut_local >/dev/null 2>&1 || fail "installing ut_local from a local folder"

run_stage USER_TOOLS=ut_multi || fail "stage 4 must finish"
[[ "$(col ut_multi 3)" == "completed" && "$(col ut_multi__binning_reconstruction 3)" == "completed" ]] || fail "both task rows should complete"
[[ "$(runs)" == "1" ]] || fail "the command must run exactly once for two task rows"
[[ "$(grep '^>' "$R/pred_ut_multi.plasmid.fasta" | tr '\n' ' ')" == ">c1 >c2 " ]] || fail "classification row: c1 and c2 are plasmid"
[[ -s "$R/pred_ut_multi.scores.tsv" && ! -e "$R/pred_ut_multi.bins.tsv" ]] || fail "classification row: scores, no bins"
[[ "$(tail -n +2 "$R/pred_ut_multi__binning_reconstruction.bins.tsv" | tr '\t\n' ': ')" == "B1:c1 B1:c2 " ]] || fail "binning row: the real bins"
[[ "$(col ut_multi__binning_reconstruction 5)" == *"contig_bins"* ]] || fail "tool_status says which output the binning row used"
[[ -s "$R/pred_ut_multi__binning_reconstruction.ut_multi__binning_reconstruction.provenance.json" ]] || fail "per-row provenance"
echo "two tasks: one run, two rows, each from its best output -> PASS"

run_stage USER_TOOLS=ut_multi || fail "re-run must finish"
[[ "$(col ut_multi 3)" == "reused" && "$(col ut_multi__binning_reconstruction 3)" == "reused" ]] || fail "unchanged rows are reused"
[[ "$(runs)" == "1" ]] || fail "a re-run must not run the command again"
echo "unchanged rows are reused, the command does not run again -> PASS"

rm -f "$R/.ut_multi__binning_reconstruction.complete"
run_stage USER_TOOLS=ut_multi || fail "partial re-run must finish"
[[ "$(col ut_multi 3)" == "reused" && "$(col ut_multi__binning_reconstruction 3)" == "completed" ]] || fail "only the missing row is converted again"
[[ "$(runs)" == "1" ]] || fail "converting a row again must not run the command"
echo "one row converted again from the same output, no second run -> PASS"

run_stage USER_TOOLS=ut_multi__binning_reconstruction FORCE_RERUN_TOOLS=1 || fail "selecting by task id must finish"
[[ "$(runs)" == "2" && "$(col ut_multi 3)" == "completed" ]] || fail "a task id selects its tool; forcing re-runs once for all rows"
echo "a per-task id selects its tool -> PASS"

run_stage USER_TOOLS=ut_auto || fail "auto stage must finish"
for id in ut_auto ut_auto__classification ut_auto__sequence_reassembly; do
    [[ "$(col $id 3)" == "completed" ]] || fail "$id should complete"
done
[[ "$(col ut_auto 5)" == *"contig_bins (contig_report.txt)"* ]] || fail "binning row records its choice: $(col ut_auto 5)"
[[ "$(col ut_auto__classification 5)" == *"contig_labels"* && "$(col ut_auto__sequence_reassembly 5)" == *"fasta_dir"* ]] || fail "choices recorded for the other rows"
[[ "$(tail -n +2 "$R/pred_ut_auto.bins.tsv" | tr '\t\n' ': ')" == "AA1:c1 AA1:c2 " ]] || fail "'-' contigs are not binned"
[[ "$(grep -c '^>' "$R/pred_ut_auto__sequence_reassembly.plasmid.fasta")" == "2" ]] || fail "reassembly from the FASTA files"
echo "format = auto: three rows from one contig table plus FASTA files, choices recorded -> PASS"

run_stage USER_TOOLS=ut_partial || fail "partial stage must finish"
[[ "$(col ut_partial 3)" == "completed" && "$(col ut_partial__sequence_reassembly 3)" == "skipped" \
   && "$(col ut_partial__sequence_reassembly 5)" == *"sequence_reassembly"* ]] || fail "unservable task skipped, the other completes"
echo "a task the output cannot serve is skipped with the reason; the others complete -> PASS"

run_stage USER_TOOLS=ut_local || fail "local stage must finish"
[[ "$(col ut_local 3)" == "completed" ]] || fail "a tool run from {src} completes"
run_stage USER_TOOLS=ut_local || fail "re-run"
[[ "$(col ut_local 3)" == "reused" ]] || fail "unchanged source is reused"
echo "# newer" >> "$TMP/local_src/bin/run.py"
PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/user_tools.py" fetch ut_local >/dev/null 2>&1 || fail "reinstall"
run_stage USER_TOOLS=ut_local || fail "re-run after reinstall"
[[ "$(col ut_local 3)" == "completed" ]] || fail "a changed local source must re-run the tool (fingerprint)"
echo "{src} from a local folder; a changed source re-runs -> PASS"

dump="$(PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/tool_capabilities.py" --registry "$ROOT/config/tool_capabilities.tsv" --dump | tr -d '\r')"
grep -qxF "$(printf 'ut_multi\tno\tshort_read\tno\tclassification')" <<< "$dump" || fail "registry: ut_multi classification"
grep -qxF "$(printf 'ut_multi__binning_reconstruction\tyes\tshort_read\tno\tbinning_reconstruction')" <<< "$dump" || fail "registry: binning row"
label="$(PLASBENCH_TOOLS_PATH="$TMP/tools" python3 -c "import sys; sys.path.insert(0,'$ROOT/python'); from plasbench_common import display_tool_name as d; print(d('ut_multi__binning_reconstruction'))" | tr -d '\r')"
[[ "$label" == "UT Multi (binning)" ]] || fail "leaderboard label should carry the task: $label"
echo "the registry has one row per task and the label carries the task -> PASS"
echo "ALL USER TOOL MULTI-TASK STAGE TESTS PASSED"
