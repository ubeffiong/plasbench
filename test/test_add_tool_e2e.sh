#!/usr/bin/env bash
# Add your own tool, end to end (offline, fake tools). Two parts:
#   1. test/test_add_tool_e2e.py: the user path up to the run (manifests, conversions, every install source and its refusals, the command
#      line, the window routes).
#   2. stage 4, 5 and 6 on a small cohort with the real scripts:
#        a multi-task manifest (binning + classification)    -> the command runs ONCE; tool_status has one row per task id
#        scoring                                             -> scores.tsv has a row per task id, under the tool's own track
#        the leaderboard                                     -> both rows, each under its task
#        a second run, an edited manifest, a changed source  -> reused, re-run, re-run
#        ONLY_TOOL / USER_TOOLS with a per-task id           -> that tool, the other task rows are produced too (one command)
#        a failing user tool                                 -> failed with the exit code; the rest of the run continues
#        a user tool whose source is not installed           -> skipped with the install command; stage 0 names it before any work
#        the report labels                                   -> "<name> (<task>)"
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
NATIVE_TMP="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")"

[[ -n "${E2E_SKIP_PY:-}" ]] || python3 "$HERE/test_add_tool_e2e.py"

# ---- a small cohort: one isolate with a 600 bp plasmid and a 1500 bp chromosome ---------------------------------------------
mkdir -p "$TMP/data/s1" "$TMP/config" "$TMP/tools" "$TMP/bin"
python3 - "$TMP/data/s1" <<'EOF'
import random, sys
random.seed(7)
folder = sys.argv[1]
rnd = lambda n: "".join(random.choice("ACGT") for _ in range(n))
plasmid, chrom = rnd(600), rnd(1500)
open(folder + "/reference.fna", "w").write(f">P1\n{plasmid}\n>C1\n{chrom}\n")
open(folder + "/contigs.fasta", "w").write(f">c1\n{plasmid}\n>c2\n{plasmid[:300]}\n>c3\n{chrom[:900]}\n")
open(folder + "/truth.tsv", "w").write("sequence_id\tmolecule_type\tlength\nP1\tPLASMID\t600\nC1\tCHROMOSOME\t1500\n")
EOF
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"
# Stage 5 aligns with minimap2: the real one when it is installed (CI), else a stand-in that reports the whole query on the plasmid.
if ! command -v minimap2 >/dev/null 2>&1; then
    printf '#!/usr/bin/env bash\nprintf "q1\\t100\\t0\\t100\\t+\\tP1\\t600\\t0\\t100\\t100\\t100\\t60\\n"\n' > "$TMP/bin/minimap2"
    chmod +x "$TMP/bin/minimap2"
fi

# One command that writes both a contig->bin table and a label table; it counts its runs.
mkdir -p "$TMP/tools/ut_multi"
cat > "$TMP/tools/ut_multi/fake.py" <<'EOF'
import sys
counter, outdir = sys.argv[1], sys.argv[2]
open(counter, "a").write("run\n")
open(outdir + "/bins.tsv", "w").write("contig\tbin\nc1\tB1\nc2\tB1\n")
open(outdir + "/labels.csv", "w").write("contig,call,p\nc1,plasmid,0.9\nc2,plasmid,0.8\nc3,chromosome,0.1\n")
EOF
cat > "$TMP/tools/ut_multi/plasbench-tool.ini" <<EOF
[tool]
name = ut_multi
display_name = UT Multi
task = binning_reconstruction, classification
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
# A tool that fails, and one whose source was never installed ({src} comes from a local folder that has not been fetched).
mkdir -p "$TMP/tools/ut_fail" "$TMP/tools/ut_noinst" "$TMP/noinst_src"
printf '[tool]\nname = ut_fail\ntask = binning_reconstruction\nanalysis_track = short_read\n[run]\nmode = command\ncommand = echo "ut_fail is broken" >&2; exit 3\n[output]\nformat = contig_bins\npath = x.tsv\n' > "$TMP/tools/ut_fail/plasbench-tool.ini"
printf 'print(1)\n' > "$TMP/noinst_src/run.py"
cat > "$TMP/tools/ut_noinst/plasbench-tool.ini" <<EOF
[tool]
name = ut_noinst
task = classification
analysis_track = short_read
[install]
method = local
path = $NATIVE_TMP/noinst_src
mode = copy
[run]
mode = command
command = python3 {src}/run.py {outdir}
requires = contigs
[output]
format = contig_labels
path = x.csv
label_column = 2
EOF

stage() {   # stage SCRIPT [VAR=value ...]: a real stage on the cohort; the log goes to $TMP/<script>.log
    local script="$1"; shift
    rm -rf "$TMP/logs"
    env PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        PLASBENCH_TOOLS_PATH="$TMP/tools" REQUIRE_CURATED_METADATA=0 RUN_MOB_RECON=0 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_PROTEIN_ANNOTATION=0 \
        RUN_BASELINE_COVERAGE=0 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 RUN_PLSMD=0 TOOL_RETRIES=0 "$@" \
        bash "$ROOT/scripts/$script" > "$TMP/$script.log" 2>&1
}
STATUS="$TMP/results/tool_status.tsv"
col() { awk -F'\t' -v t="$1" -v c="$2" '$2==t {print $c}' "$STATUS" | tail -1; }
fail() { echo "FAIL: $*" >&2; cat "$STATUS" >&2 2>/dev/null || true; for f in "$TMP"/*.sh.log; do echo "--- $f" >&2; tail -25 "$f" >&2; done; exit 1; }
runs() { if [[ -f "$TMP/counter" ]]; then wc -l < "$TMP/counter" | tr -d ' '; else echo 0; fi; }
R="$TMP/results/s1"

# ---- one run of stage 4 over three user tools -----------------------------------------------------------------------------------
stage 04_run_tools.sh USER_TOOLS=ut_multi,ut_fail,ut_noinst || fail "stage 4 must finish: a failing user tool does not stop the run"
[[ "$(col ut_multi 3)" == "completed" && "$(col ut_multi__classification 3)" == "completed" ]] || fail "both task rows of ut_multi complete"
[[ "$(runs)" == "1" ]] || fail "the multi-task command runs exactly once (ran $(runs) times)"
echo "multi-task manifest: one command run, two tool_status rows (ut_multi, ut_multi__classification) -> PASS"
[[ "$(col ut_fail 3)" == "failed" && "$(col ut_fail 5)" == *"exit_code=3"* ]] || fail "ut_fail is failed with its exit code: '$(col ut_fail 3)' '$(col ut_fail 5)'"
echo "a failing user tool is 'failed' with the reason and the run continues -> PASS"
[[ "$(col ut_noinst 3)" == "skipped" && "$(col ut_noinst 5)" == *"not installed"* && "$(col ut_noinst 5)" == *"install-tools ut_noinst"* ]] \
    || fail "a tool whose source is not installed is skipped with the install command: '$(col ut_noinst 3)' '$(col ut_noinst 5)'"
echo "a missing install is an honest not-run reason that names the install command -> PASS"
[[ -s "$R/pred_ut_multi__classification.plasmid.fasta" && -s "$R/pred_ut_multi.bins.tsv" && ! -e "$R/pred_ut_multi__classification.bins.tsv" ]] \
    || fail "each task row has its own prediction files (bins for binning, none for classification)"

# the pre-flight message from the install-missing logic: stage 0 lists the missing user tool and the command
if grep -q "ut_noinst" "$TMP/04_run_tools.sh.log" && grep -qi "install-tools ut_noinst" "$TMP/04_run_tools.sh.log"; then
    echo "stage 4 names the missing user tool and its install command -> PASS"
else
    fail "the stage log must name ut_noinst and 'plasbench install-tools ut_noinst'"
fi

# stage 0 (scripts/00_setup.sh) asks the same question before any sample work: a url/local tool whose source was never fetched is MISSING, not "ok"
rc=0; note="$(PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/user_tools.py" source-status ut_noinst 2>&1)" || rc=$?
[[ "$rc" == "3" && "$note" == *"install-tools ut_noinst"* ]] || fail "source-status must exit 3 and name the install command for an unfetched source (exit $rc: $note)"
PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/user_tools.py" source-status ut_multi >/dev/null || fail "a tool with nothing to fetch is not missing"
grep -q 'user_tools.py" source-status' "$ROOT/scripts/00_setup.sh" || fail "scripts/00_setup.sh must use source-status for user tools"
echo "stage 0 treats an unfetched url/local source as missing (exit 3 with the install command) -> PASS"

# ---- stage 5 and 6: each task row is scored and ranked on its own ---------------------------------------------------------------
stage 05_score.sh USER_TOOLS=ut_multi,ut_fail,ut_noinst || fail "stage 5 must finish"
SCORES="$TMP/results/scores.tsv"
[[ -s "$SCORES" ]] || fail "scores.tsv was not written"
for id in ut_multi ut_multi__classification; do
    [[ "$(awk -F'\t' -v t="$id" '$2==t' "$SCORES" | wc -l | tr -d ' ')" -ge 1 ]] || fail "scores.tsv has no row for $id"
    [[ "$(awk -F'\t' -v t="$id" '$2==t {print $3}' "$SCORES" | head -1)" == "short_read" ]] || fail "$id is scored under its own track (short_read)"
done
echo "scoring: a row per task id, each under the tool's own track -> PASS"
if awk -F'\t' '$2=="ut_fail" || $2=="ut_noinst"' "$SCORES" | grep -q .; then
    awk -F'\t' '$2=="ut_noinst"' "$SCORES" | grep -q . && fail "a tool that did not run has no score row (it must not be scored as 0 silently)"
fi
stage 06_aggregate.sh || fail "stage 6 must finish"
LB="$(ls "$TMP"/results/*leaderboard*.tsv 2>/dev/null | head -1 || true)"
[[ -n "$LB" ]] || fail "stage 6 wrote no leaderboard"
grep -q "ut_multi__classification" "$LB" && grep -qw "ut_multi" "$LB" || fail "the leaderboard has both task rows of ut_multi ($LB)"
echo "leaderboard: both rows present -> PASS"

# ---- reuse and invalidation -----------------------------------------------------------------------------------------------------
stage 04_run_tools.sh USER_TOOLS=ut_multi || fail "re-run"
[[ "$(col ut_multi 3)" == "reused" && "$(col ut_multi__classification 3)" == "reused" && "$(runs)" == "1" ]] || fail "an unchanged tool is reused and does not run again"
echo "second run: both rows reused, the command did not run again -> PASS"
echo "# edited" >> "$TMP/tools/ut_multi/plasbench-tool.ini"
stage 04_run_tools.sh USER_TOOLS=ut_multi || fail "re-run after a manifest edit"
[[ "$(col ut_multi 3)" == "completed" && "$(runs)" == "2" ]] || fail "an edited manifest re-runs the command"
echo "an edited manifest re-runs the tool (fingerprint) -> PASS"
echo "# edited script" >> "$TMP/tools/ut_multi/fake.py"
stage 04_run_tools.sh USER_TOOLS=ut_multi || fail "re-run after a script edit"
[[ "$(col ut_multi 3)" == "completed" && "$(runs)" == "3" ]] || fail "an edited script ({tool_dir} file) re-runs the command (ran $(runs))"
echo "an edited tool script re-runs the tool (fingerprint) -> PASS"
PLASBENCH_TOOLS_PATH="$TMP/tools" python3 "$ROOT/python/user_tools.py" fetch ut_noinst >/dev/null 2>&1 || fail "fetching ut_noinst's local source"
stage 04_run_tools.sh USER_TOOLS=ut_noinst || fail "stage 4 after the install"
[[ "$(col ut_noinst 3)" != "skipped" ]] || fail "after the install the tool is no longer skipped as not installed: $(col ut_noinst 5)"
echo "after install-tools the tool runs (no longer 'not installed') -> PASS"

# ---- selection by a per-task id ---------------------------------------------------------------------------------------------------
rm -f "$TMP/counter"
stage 04_run_tools.sh ONLY_TOOL=ut_multi__classification FORCE_RERUN_TOOLS=1 || fail "ONLY_TOOL with a task id"
[[ "$(runs)" == "1" && "$(col ut_multi__classification 3)" == "completed" ]] || fail "ONLY_TOOL=<name>__<task> selects the tool (ran $(runs))"
! grep -q "ut_fail" "$STATUS" || fail "ONLY_TOOL runs only the named tool"
echo "ONLY_TOOL with a per-task id selects that tool's command, and only it -> PASS"
if stage 04_run_tools.sh USER_TOOLS=ut_multi__nonsense; then fail "an unknown task id must stop stage 4"; fi
grep -q "unknown user tool" "$TMP/04_run_tools.sh.log" || fail "the reason must name the unknown tool"
echo "an unknown id is a named error, not an empty run -> PASS"

# ---- the report labels -------------------------------------------------------------------------------------------------------------
label_of() { PLASBENCH_TOOLS_PATH="$TMP/tools" python3 -c "import sys; sys.path.insert(0,'$ROOT/python'); from plasbench_common import display_tool_name as d; print(d('$1'))" | tr -d '\r'; }
[[ "$(label_of ut_multi)" == "UT Multi (binning)" && "$(label_of ut_multi__classification)" == "UT Multi (classification)" ]] || fail "labels: $(label_of ut_multi) / $(label_of ut_multi__classification)"
echo "the report labels carry the task: '$(label_of ut_multi)', '$(label_of ut_multi__classification)' -> PASS"

echo "ALL ADD-TOOL END-TO-END TESTS PASSED"
