#!/usr/bin/env bash
# User-added tools in stage 4 (offline): one generic runner for any tool a plasbench-tool.ini manifest declares.
#   command mode, contig->bin TSV       -> completed; pred FASTA + bins.tsv from the mapping; reused on a re-run
#   import mode, labels + scores         -> completed; candidates.fasta + scores.tsv for the PR curve; no bins (classifier)
#   a command that exits non-zero        -> failed, with the exit code, like a built-in tool
#   a required input the sample lacks    -> skipped with the reason
#   an output naming foreign contig ids  -> skipped (does not fit this assembly), never failed
#   USER_TOOLS naming an unknown tool    -> stage 4 stops with the reason (a typo must not silently run nothing)
#   USER_TOOLS unset                     -> no user-tool rows
#   the capability registry (scripts/lib.sh) sees each tool's task and track
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/data/s1" "$TMP/config" "$TMP/tools" "$TMP/imported"
printf '>c1 len=10\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

# A binning tool PlasBench runs: it writes "contig<TAB>bin" with ids carrying a suffix the manifest strips.
mkdir -p "$TMP/tools/ut_binner"
cat > "$TMP/tools/ut_binner/fake_binner.py" <<'EOF'
import sys
contigs, out = sys.argv[1], sys.argv[2]
names = [l[1:].split()[0] for l in open(contigs) if l.startswith(">")]
with open(out, "w") as fh:
    fh.write("contig\tbin\n")
    fh.write(f"{names[0]}_x\tB1\n{names[1]}_x\tB1\n")
EOF
cat > "$TMP/tools/ut_binner/plasbench-tool.ini" <<'EOF'
[tool]
name = ut_binner
display_name = UT Binner
task = reconstruction
analysis_track = short_read
version_command = echo ut_binner 1.0
[install]
method = none
[run]
mode = command
command = python3 {tool_dir}/fake_binner.py {contigs} {outdir}/bins.tsv
requires = contigs
[output]
format = contig_bins
path = bins.tsv
contig_column = contig
bin_column = bin
contig_id_strip_regex = _x$
EOF

# A classifier whose outputs the user produced beforehand (import mode), with a probability column. A path written
# inside a manifest is read by Python as-is, so on Windows (Git Bash) it must be the native spelling.
NATIVE_TMP="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")"
mkdir -p "$TMP/tools/ut_labels"
cat > "$TMP/tools/ut_labels/plasbench-tool.ini" <<EOF
[tool]
name = ut_labels
task = classification
analysis_track = short_read
[run]
mode = import
dir = $NATIVE_TMP/imported
pattern = {sample}.csv
[output]
format = contig_labels
delimiter = comma
contig_column = 1
label_column = 2
plasmid_values = plasmid
score_column = 3
EOF
printf 'id,call,p\nc1,plasmid,0.9\nc2,chromosome,0.2\nc3,plasmid,0.7\n' > "$TMP/imported/s1.csv"

# A tool that fails, and one that needs an input the sample does not have.
mkdir -p "$TMP/tools/ut_broken" "$TMP/tools/ut_graph"
printf '[tool]\nname = ut_broken\ntask = reconstruction\nanalysis_track = short_read\n[run]\nmode = command\ncommand = exit 3\n[output]\nformat = contig_bins\npath = x.tsv\n' \
    > "$TMP/tools/ut_broken/plasbench-tool.ini"
printf '[tool]\nname = ut_graph\ntask = reconstruction\nanalysis_track = short_read\n[run]\nmode = command\ncommand = cat {graph}\nrequires = graph\n[output]\nformat = contig_bins\npath = x.tsv\n' \
    > "$TMP/tools/ut_graph/plasbench-tool.ini"

run_stage() {
    rm -rf "$TMP/logs"
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        PLASBENCH_TOOLS_PATH="$TMP/tools" REQUIRE_CURATED_METADATA=0 RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 \
        RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 RUN_PLSMD=0 TOOL_RETRIES=0 "$@" \
        bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}
STATUS="$TMP/results/tool_status.tsv"
col() { awk -F'\t' -v t="$1" -v c="$2" '$2==t {print $c}' "$STATUS"; }
fail() { echo "FAIL: $*" >&2; cat "$STATUS" >&2 2>/dev/null || true; tail -30 "$TMP/stage.log" >&2; exit 1; }

run_stage USER_TOOLS=all || fail "stage 4 must finish"
[[ "$(col ut_binner 3)" == "completed" ]] || fail "ut_binner should complete"
[[ "$(grep -c '^>' "$TMP/results/s1/pred_ut_binner.plasmid.fasta")" == "2" ]] || fail "two binned contigs expected"
[[ "$(tail -n +2 "$TMP/results/s1/pred_ut_binner.bins.tsv" | tr '\t\n' ': ')" == "B1:c1 B1:c2 " ]] || fail "bins B1 = c1, c2 expected"
echo "command mode: the tool runs, its contig->bin table is mapped (ids stripped) into bins -> PASS"

[[ "$(col ut_labels 3)" == "completed" ]] || fail "ut_labels should complete"
[[ "$(grep '^>' "$TMP/results/s1/pred_ut_labels.plasmid.fasta" | tr '\n' ' ')" == ">c1 >c3 " ]] || fail "c1 and c3 called plasmid"
[[ "$(tail -n +2 "$TMP/results/s1/pred_ut_labels.scores.tsv" | wc -l | tr -d ' ')" == "3" ]] || fail "three scored candidates"
[[ ! -e "$TMP/results/s1/pred_ut_labels.bins.tsv" ]] || fail "a classifier writes no bins"
echo "import mode: precomputed labels and probabilities become the hard call plus the PR-curve candidates -> PASS"

[[ "$(col ut_broken 3)" == "failed" && "$(col ut_broken 5)" == *"exit_code=3"* ]] || fail "ut_broken should fail with exit_code=3"
echo "a failing command is failed with its exit code -> PASS"
[[ "$(col ut_graph 3)" == "skipped" && "$(col ut_graph 5)" == *"input graph unavailable"* ]] || fail "ut_graph should skip"
echo "a missing required input is a skip with the reason -> PASS"

run_stage USER_TOOLS=ut_binner || fail "re-run must finish"
[[ "$(col ut_binner 3)" == "reused" ]] || fail "unchanged inputs and manifest should reuse the result"
echo "an unchanged tool, manifest and input reuse the earlier result -> PASS"
echo "# changed" >> "$TMP/tools/ut_binner/plasbench-tool.ini"
run_stage USER_TOOLS=ut_binner || fail "re-run must finish"
[[ "$(col ut_binner 3)" == "completed" ]] || fail "an edited manifest must re-run the tool"
echo "editing the manifest re-runs the tool (fingerprint) -> PASS"

printf 'id,call,p\nnode_9,plasmid,0.9\n' > "$TMP/imported/s1.csv"
run_stage USER_TOOLS=ut_labels || fail "stage 4 must finish"
[[ "$(col ut_labels 3)" == "skipped" && "$(col ut_labels 5)" == *"unusable"* ]] || fail "foreign ids should skip"
echo "an output from another assembly is a skip, not a failure -> PASS"

if run_stage USER_TOOLS=ut_nosuch; then fail "an unknown tool name must stop stage 4"; fi
grep -q "unknown user tool" "$TMP/stage.log" || fail "the reason must name the unknown tool"
echo "an unknown USER_TOOLS name stops the stage with the reason -> PASS"

run_stage || fail "stage 4 must finish"
! grep -q "ut_" "$STATUS" || fail "no user-tool rows without USER_TOOLS"
echo "without USER_TOOLS no user tool runs -> PASS"

dump="$(PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/tool_capabilities.py" --registry "$ROOT/config/tool_capabilities.tsv" --dump | tr -d '\r')"
grep -qxF "$(printf 'ut_binner\tyes\tshort_read\tno')" <<< "$dump" || fail "registry: ut_binner reconstruction, short_read"
grep -qxF "$(printf 'ut_labels\tno\tshort_read\tno')" <<< "$dump" || fail "registry: ut_labels classification"
echo "the capability registry carries each user tool's task and track -> PASS"
echo "ALL USER TOOL STAGE TESTS PASSED"
