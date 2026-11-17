#!/usr/bin/env bash
# Regression (audit AU-001, AU-009 shell side): two runs must not corrupt each other, and a killed run must not be silently duplicated.
#   1. two stage-4 runs on ONE results folder: the second refuses (a lock holds the pid), the first still writes a complete tool_status.tsv;
#   2. two stage-4 runs on different results folders that share TMP_DIR (the old default): each keeps its own shards, both tables are complete
#      (before, the second run wiped the first's shards and the first exited 0 with a header-only table);
#   3. a stale lock (its pid is gone) is removed with a message;
#   4. kill -9 of a run that leads its process group leaves its tool running: the next start refuses while a member of the group is alive,
#      then recovers (the killed run's temp area is kept and reported) once the group is gone;
#   5. status shards that vanish mid-run (another process wiped them) make stage 4 FAIL, not report "complete" with an empty table;
#   6. run_all.sh refuses to start over a live run (its .run_in_progress marker names a live pid).
# Uses fake binaries; runs offline. Needs GNU timeout, setsid and ps (Linux or WSL).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
if ! command -v setsid >/dev/null 2>&1 || ! command -v timeout >/dev/null 2>&1 || ! command -v ps >/dev/null 2>&1; then
    echo "SKIP: needs setsid, GNU timeout and ps (Linux or WSL)"; exit 0
fi
TMP="$(mktemp -d)"
cleanup() { pkill -f "$TMP/bin/" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

mkdir -p "$TMP/bin" "$TMP/config" "$TMP/data/s1" "$TMP/shared_tmp"
printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

# A mob_recon that takes MOB_SLEEP seconds, then writes a real-looking output. MOB_WIPE=1 removes every run's temp area first (a concurrent wiper).
cat > "$TMP/bin/mob_recon" <<'EOF'
#!/usr/bin/env bash
outdir=""; while [[ $# -gt 0 ]]; do case "$1" in --outdir) outdir="$2"; shift 2;; *) shift;; esac; done
echo "$$" > "${MOB_PIDFILE:-/dev/null}"
[[ "${MOB_WIPE:-0}" == "1" ]] && rm -rf "$TMP_DIR"/.run.*/.shards.* 2>/dev/null
sleep "${MOB_SLEEP:-0}"
mkdir -p "$outdir"; printf 'contig_id\tmolecule_type\ncontig1\tchromosome\n' > "$outdir/contig_report.txt"
EOF
chmod +x "$TMP/bin/mob_recon"

# stage4 NAME [env...] : run stage 4 (mob_recon only) for results folder $TMP/res_NAME, shared TMP_DIR; prints nothing, log in $TMP/NAME.log; returns its exit code
stage4() {
    local name="$1"; shift
    env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/res_$name" LOG_DIR="$TMP/logs_$name" TMP_DIR="$TMP/shared_tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 ONLY_TOOL=mob_recon PATH="$TMP/bin:$PATH" "$@" \
        timeout 120 bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/$name.log" 2>&1
}
status_of() { awk -F'\t' '$1=="s1" && $2=="mob_recon" {print $3}' "$TMP/res_$1/tool_status.tsv" 2>/dev/null || true; }
wait_for() { local n=0; while (( n < 100 )); do eval "$1" && return 0; sleep 0.2; n=$(( n + 1 )); done; return 1; }

# ---- 1. two runs, one results folder -------------------------------------------------------------------------------
stage4 one MOB_SLEEP=4 & p1=$!
wait_for "[[ -s '$TMP/res_one/.run.lock' ]]" || { echo "FAIL: the first run never wrote its lock" >&2; cat "$TMP/one.log" >&2; exit 1; }
rc2=0; stage4 one MOB_SLEEP=0 || rc2=$?
rc1=0; wait "$p1" || rc1=$?
[[ "$rc2" != "0" ]] || { echo "FAIL: a second run on a results folder in use must refuse" >&2; exit 1; }
grep -q "another PlasBench run is already using" "$TMP/one.log" || { echo "FAIL: the refusal must say why" >&2; cat "$TMP/one.log" >&2; exit 1; }
[[ "$rc1" == "0" && "$(status_of one)" == "completed" ]] || { echo "FAIL: the first run must still finish with a full table (exit $rc1)" >&2; cat "$TMP/res_one/tool_status.tsv" >&2; exit 1; }
[[ ! -e "$TMP/res_one/.run.lock" ]] || { echo "FAIL: the lock must be removed when the run ends" >&2; exit 1; }
echo "two runs on one results folder: the second refuses, the first keeps a complete table, the lock is released -> PASS"

# ---- 2. two runs, different results folders, one TMP_DIR ---------------------------------------------------------------
stage4 a MOB_SLEEP=3 & pa=$!
stage4 b MOB_SLEEP=3 & pb=$!
rca=0; rcb=0; wait "$pa" || rca=$?; wait "$pb" || rcb=$?
[[ "$rca" == "0" && "$rcb" == "0" ]] || { echo "FAIL: concurrent runs with their own results folders must both finish ($rca, $rcb)" >&2; tail -5 "$TMP/a.log" "$TMP/b.log" >&2; exit 1; }
[[ "$(status_of a)" == "completed" && "$(status_of b)" == "completed" ]] || { echo "FAIL: both tables must be complete (a=$(status_of a) b=$(status_of b))" >&2; exit 1; }
[[ -z "$(find "$TMP/shared_tmp" -maxdepth 1 -name '.run.*' 2>/dev/null)" ]] || { echo "FAIL: each run must remove its own temp area" >&2; ls -a "$TMP/shared_tmp" >&2; exit 1; }
echo "concurrent runs sharing TMP_DIR each keep their own shards and finish complete -> PASS"

# ---- 3. a stale lock ------------------------------------------------------------------------------------------------
mkdir -p "$TMP/res_stale"
printf 'pid=999999\npgid=\nstarted=2020-01-01 00:00:00\nwhat=old run\n' > "$TMP/res_stale/.run.lock"
stage4 stale || { echo "FAIL: a stale lock must not block a run" >&2; tail -5 "$TMP/stale.log" >&2; exit 1; }
grep -q "stale run lock" "$TMP/stale.log" || { echo "FAIL: removing a stale lock must be said" >&2; exit 1; }
[[ "$(status_of stale)" == "completed" ]] || { echo "FAIL: the run after a stale lock must complete" >&2; exit 1; }
echo "a stale lock is removed with a message and the run proceeds -> PASS"

# ---- 4. kill -9 of a group leader: refuse while any member is alive, recover after ----------------------------------------
rm -rf "$TMP/shared_tmp"; mkdir -p "$TMP/shared_tmp"
setsid env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/res_kill" LOG_DIR="$TMP/logs_kill" TMP_DIR="$TMP/shared_tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" \
    REQUIRE_CURATED_METADATA=0 ONLY_TOOL=mob_recon PATH="$TMP/bin:$PATH" MOB_SLEEP=60 MOB_PIDFILE="$TMP/mob.pid" \
    bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/kill.log" 2>&1 &
wait_for "[[ -s '$TMP/mob.pid' && -s '$TMP/res_kill/.run.lock' ]]" || { echo "FAIL: the run to be killed never started its tool" >&2; cat "$TMP/kill.log" >&2; exit 1; }
leader="$(sed -n 's/^pid=//p' "$TMP/res_kill/.run.lock")"
group="$(sed -n 's/^pgid=//p' "$TMP/res_kill/.run.lock")"
[[ -n "$group" ]] || { echo "FAIL: a run that leads its process group must record it in the lock" >&2; cat "$TMP/res_kill/.run.lock" >&2; exit 1; }
kill -9 "$leader"
sleep 1
tool_pid="$(cat "$TMP/mob.pid")"
kill -0 "$tool_pid" 2>/dev/null || { echo "FAIL: setup: the tool should have been orphaned and still be running" >&2; exit 1; }
rc=0; stage4 kill MOB_SLEEP=0 || rc=$?
[[ "$rc" != "0" ]] || { echo "FAIL: start/resume must refuse while a member of the killed run's group is alive" >&2; exit 1; }
grep -q "process group $group are still running" "$TMP/kill.log" || { echo "FAIL: the refusal must name the group" >&2; cat "$TMP/kill.log" >&2; exit 1; }
echo "kill -9 leaves an orphan; the next start refuses while the group is alive -> PASS"
kill -9 -- "-$group" 2>/dev/null || true
sleep 1
stage4 kill MOB_SLEEP=0 || { echo "FAIL: once the group is gone the run must start and complete" >&2; tail -8 "$TMP/kill.log" >&2; exit 1; }
[[ "$(status_of kill)" == "completed" ]] || { echo "FAIL: resumed run must complete" >&2; exit 1; }
grep -q "run that was killed" "$TMP/kill.log" || { echo "FAIL: the killed run's leftover shards must be reported, not silently lost" >&2; tail -8 "$TMP/kill.log" >&2; exit 1; }
[[ -n "$(find "$TMP/logs_kill/recovered_shards" -maxdepth 1 -name '.run.*' 2>/dev/null)" ]] || { echo "FAIL: the killed run's temp area must be kept under logs/recovered_shards" >&2; exit 1; }
echo "after the group is gone the run resumes; the killed run's leftovers are kept and reported -> PASS"

# ---- 5. shards wiped mid-run ----------------------------------------------------------------------------------------------
rc=0; stage4 wipe MOB_WIPE=1 TMP_DIR="$TMP/shared_tmp" || rc=$?
[[ "$rc" != "0" ]] || { echo "FAIL: stage 4 must fail when its shards were wiped, not exit 0" >&2; tail -5 "$TMP/wipe.log" >&2; exit 1; }
! grep -q "Stage 4 (run tools) complete" "$TMP/wipe.log" || { echo "FAIL: it must not claim completion" >&2; exit 1; }
echo "wiped shards make stage 4 fail instead of 'complete' with an empty table -> PASS"

# ---- 6. run_all.sh refuses over a live run ----------------------------------------------------------------------------------
mkdir -p "$TMP/res_ra"
sleep 30 & live=$!
printf 'started now, stage 4 (04_run_tools.sh), pid %s\n' "$live" > "$TMP/res_ra/.run_in_progress"
rc=0
env DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/res_ra" LOG_DIR="$TMP/logs_ra" TMP_DIR="$TMP/shared_tmp" SAMPLE_SHEET="$TMP/config/accessions.tsv" REQUIRE_CURATED_METADATA=0 \
    timeout 60 bash "$ROOT/scripts/run_all.sh" 4 > "$TMP/ra.log" 2>&1 || rc=$?
kill "$live" 2>/dev/null || true
[[ "$rc" != "0" ]] && grep -q "run is in progress" "$TMP/ra.log" || { echo "FAIL: run_all.sh must refuse over a marker whose pid is alive (exit $rc)" >&2; tail -5 "$TMP/ra.log" >&2; exit 1; }
echo "run_all.sh checks the liveness of the pid in .run_in_progress -> PASS"

echo "ALL RUN ISOLATION AND LOCK TESTS PASSED"
