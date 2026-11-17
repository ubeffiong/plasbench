#!/usr/bin/env bash
# Regression: a stage must not look successful when work was lost, and must not leave a tool running after Ctrl+C. Fake binaries; offline.
#
#   1. A sample whose job crashes (here: results/<sample> is a plain file, so `mkdir -p` fails for that sample only) used to leave no row and
#      the stage still printed "complete" and exited 0. It must now finish the other sample, keep its rows, then fail naming the crashed one
#      (and only warn when ALLOW_CRASHED_SAMPLE_JOBS=1).
#   2. A tool that exits 0 without writing anything into its output directory used to be recorded as "completed" with an empty prediction,
#      indistinguishable from "no plasmids found". It must be "failed". A tool that wrote something is still "completed" (the control).
#   3. SIGINT to the stage while a tool runs used to leave the tool running as an orphan. It must be gone afterwards.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
if ! command -v timeout >/dev/null 2>&1 || ! command -v pgrep >/dev/null 2>&1; then
    echo "SKIP: needs GNU timeout and pgrep (Linux or WSL)"; exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

make_project() {   # make_project DIR : samples s1 and s2, contigs and trimmed reads, a sheet
    local T="$1"; mkdir -p "$T/bin" "$T/config"
    local s
    for s in s1 s2; do
        mkdir -p "$T/data/$s"
        printf '>contig1\nACGTACGTACGT\n' > "$T/data/$s/contigs.fasta"
        printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/$s/SRR${s#s}_1.trim.fastq.gz"
        printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/$s/SRR${s#s}_2.trim.fastq.gz"
    done
    printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\n' > "$T/config/accessions.tsv"
}
stage4() {   # stage4 DIR [env assignments...] : run stage 4 for mob_recon only, print its exit code
    local T="$1"; shift
    ( export DATA_DIR="$T/data" RESULTS_DIR="$T/results" LOG_DIR="$T/logs" SAMPLE_SHEET="$T/config/accessions.tsv" REQUIRE_CURATED_METADATA=0 ONLY_TOOL=mob_recon
      # env sets any extra NAME=value arguments for the stage only (no dynamic export, which shellcheck cannot follow)
      PATH="$T/bin:$PATH" env "$@" timeout 120 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo $? )
}
status_of() { awk -F'\t' -v s="$2" -v t="$3" '$1==s && $2==t {print $3}' "$1/results/tool_status.tsv" 2>/dev/null || true; }

# a mob_recon that writes a real-looking output, for the controls
cat > "$TMP/good_mob_recon" <<'EOF'
#!/usr/bin/env bash
outdir=""; while [[ $# -gt 0 ]]; do case "$1" in --outdir) outdir="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$outdir"; printf 'contig_id\tmolecule_type\ncontig1\tchromosome\n' > "$outdir/contig_report.txt"
EOF

# ---- 1. a crashed sample job ---------------------------------------------------------------------------------------
T1="$TMP/p1"; make_project "$T1"; cp "$TMP/good_mob_recon" "$T1/bin/mob_recon"; chmod +x "$T1/bin/mob_recon"
mkdir -p "$T1/results"; : > "$T1/results/s2"          # mkdir -p results/s2 fails: only s2's job dies
rc="$(stage4 "$T1")"
[[ "$rc" != "0" ]] || { echo "FAIL: stage 4 exited 0 although the job for s2 crashed" >&2; cat "$T1/stage.log" >&2; exit 1; }
echo "a crashed sample job makes stage 4 fail (exit $rc) -> PASS"
grep -q "s2" "$T1/stage.log" && grep -q "MISSING" "$T1/stage.log" || { echo "FAIL: the message must name s2 and say its results are missing" >&2; tail -5 "$T1/stage.log" >&2; exit 1; }
echo "the message names the crashed sample and says its results are missing -> PASS"
[[ "$(status_of "$T1" s1 mob_recon)" == "completed" ]] || { echo "FAIL: the sample that did finish must keep its row" >&2; cat "$T1/results/tool_status.tsv" >&2; exit 1; }
echo "the other sample's row is kept -> PASS"
! grep -q "Stage 4 (run tools) complete" "$T1/stage.log" || { echo "FAIL: it must not claim completion" >&2; exit 1; }
echo "it does not print 'complete' -> PASS"
T1b="$TMP/p1b"; make_project "$T1b"; cp "$TMP/good_mob_recon" "$T1b/bin/mob_recon"; chmod +x "$T1b/bin/mob_recon"
mkdir -p "$T1b/results"; : > "$T1b/results/s2"
rc="$(stage4 "$T1b" ALLOW_CRASHED_SAMPLE_JOBS=1)"
[[ "$rc" == "0" ]] && grep -q "ALLOW_CRASHED_SAMPLE_JOBS=1" "$T1b/stage.log" || { echo "FAIL: ALLOW_CRASHED_SAMPLE_JOBS=1 must continue with a warning (exit $rc)" >&2; tail -5 "$T1b/stage.log" >&2; exit 1; }
echo "ALLOW_CRASHED_SAMPLE_JOBS=1 continues with a warning -> PASS"

# ---- 2. a tool that exits 0 and writes nothing ---------------------------------------------------------------------
T2="$TMP/p2"; make_project "$T2"
printf '#!/usr/bin/env bash\nexit 0\n' > "$T2/bin/mob_recon"; chmod +x "$T2/bin/mob_recon"
rc="$(stage4 "$T2")"
[[ "$rc" == "0" ]] || { echo "FAIL: a tool failure is recorded, it must not stop the stage (exit $rc)" >&2; tail -5 "$T2/stage.log" >&2; exit 1; }
[[ "$(status_of "$T2" s1 mob_recon)" == "failed" ]] || { echo "FAIL: a tool that wrote nothing must be 'failed'" >&2; cat "$T2/results/tool_status.tsv" >&2; exit 1; }
echo "a tool that exits 0 and writes nothing is recorded as failed -> PASS"
[[ ! -e "$T2/results/s1/pred_mob_recon.plasmid.fasta" ]] || { echo "FAIL: no prediction file may be left behind for a failed run" >&2; exit 1; }
echo "no empty prediction is left behind -> PASS"
grep -q "wrote nothing" "$T2/logs/s1.mob_recon.log" || { echo "FAIL: the tool's log must say why" >&2; cat "$T2/logs/s1.mob_recon.log" >&2; exit 1; }
echo "the log says the tool wrote nothing -> PASS"
T2b="$TMP/p2b"; make_project "$T2b"; cp "$TMP/good_mob_recon" "$T2b/bin/mob_recon"; chmod +x "$T2b/bin/mob_recon"
rc="$(stage4 "$T2b")"
[[ "$rc" == "0" && "$(status_of "$T2b" s1 mob_recon)" == "completed" ]] || { echo "FAIL: a tool that wrote output and found no plasmid must still be 'completed' (exit $rc)" >&2; cat "$T2b/results/tool_status.tsv" >&2; exit 1; }
echo "a tool that wrote output but found no plasmid is still completed (control) -> PASS"

# ---- 3. Ctrl+C leaves no orphan ------------------------------------------------------------------------------------
T3="$TMP/p3"; make_project "$T3"
MARK=$(( 40000 + RANDOM % 20000 ))
printf '#!/usr/bin/env bash\nsleep %s\n' "$MARK" > "$T3/bin/mob_recon"; chmod +x "$T3/bin/mob_recon"
( export DATA_DIR="$T3/data" RESULTS_DIR="$T3/results" LOG_DIR="$T3/logs" SAMPLE_SHEET="$T3/config/accessions.tsv" REQUIRE_CURATED_METADATA=0 ONLY_TOOL=mob_recon
  PATH="$T3/bin:$PATH" timeout --foreground -s INT 8 bash "$ROOT/scripts/04_run_tools.sh" > "$T3/stage.log" 2>&1 ) || true
sleep 2
if pgrep -f "sleep $MARK" >/dev/null; then
    pkill -f "sleep $MARK" || true
    echo "FAIL: the tool is still running after the stage was interrupted (orphan)" >&2; exit 1
fi
echo "an interrupted stage leaves no orphaned tool -> PASS"
grep -q "Ctrl+C" "$T3/stage.log" || { echo "FAIL: the interruption must still be reported" >&2; tail -4 "$T3/stage.log" >&2; exit 1; }
echo "the interruption is still reported -> PASS"
echo "ALL STAGE FAILURE VISIBILITY TESTS PASSED"
