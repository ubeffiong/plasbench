#!/usr/bin/env bash
# PIPELINE_OVERLAP (python/pipeline_overlap.py, scripts/run_all.sh). Offline; fake stage-2 script except in part 4, which runs the real scripts/02_truth.sh.
#   1. ready = this run's download_end ok events, in sheet order; an earlier run's event, a failed download or a later failed retry is not ready
#   2. the follower runs stage 2 one isolate at a time as they become ready, with private results/events folders; a failing isolate does not stop the others; it ends after stage 1
#   3. stopping the follower stops the stage-2 process it started
#   4. stage 2 after an early (overlapped) stage 2 gives byte-identical per-isolate files to stage 2 alone
#   5. off by default
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
FOLLOWER=""
trap '[[ -n "$FOLLOWER" ]] && kill "$FOLLOWER" 2>/dev/null; rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; exit 1; }
PO="$ROOT/python/pipeline_overlap.py"
ev() { printf '{"ts":"x","epoch":%s,"pid":1,"event":"download_end","sample":"%s","status":"%s","reason":""}\n' "$1" "$2" "$3" >> "$TMP/events.jsonl"; }

printf '# a comment\nsample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\nbad\tNA\tSRR\ns3\tNA\tSRR\n' > "$TMP/sheet.tsv"
NOW="$(date +%s)"

# 1
: > "$TMP/events.jsonl"
ev $((NOW - 1000)) s1 ok          # an earlier run: not ready
ev "$NOW" s3 ok
ev "$NOW" s2 failed
ev "$NOW" bad ok
[[ "$(python3 -I "$PO" ready --events "$TMP/events.jsonl" --since "$NOW" --sheet "$TMP/sheet.tsv" | tr '\n' ' ')" == "bad s3 " ]] || fail "ready must be this run's ok downloads in sheet order"
ev "$NOW" s3 failed
[[ "$(python3 -I "$PO" ready --events "$TMP/events.jsonl" --since "$NOW" --sheet "$TMP/sheet.tsv" | tr '\n' ' ')" == "bad " ]] || fail "a later failed event wins"
echo "  ok    ready = this run's downloaded isolates, in sheet order (earlier runs and failed downloads are not)"

# 2
cat > "$TMP/fake02.sh" <<'EOF'
#!/usr/bin/env bash
s="$(awk 'NR == 2 {print $1}' "$SAMPLE_SHEET")"
echo "$s $RESULTS_DIR $RUN_EVENTS_FILE $MAX_PARALLEL_SAMPLES" >> "$CALLS"
[[ "$s" == "bad" ]] && exit 1
sleep "${FAKE_SLEEP:-0}"
exit 0
EOF
export CALLS="$TMP/calls.log"; : > "$CALLS"
: > "$TMP/events.jsonl"
mkdir -p "$TMP/work"
python3 -I "$PO" follow --events "$TMP/events.jsonl" --since "$NOW" --sheet "$TMP/sheet.tsv" --work "$TMP/work" --stop "$TMP/stop" --script "$TMP/fake02.sh" --poll 0.3 > "$TMP/follow.out" 2>&1 &
FOLLOWER=$!
sleep 1; [[ ! -s "$CALLS" ]] || fail "nothing is ready yet, nothing may run"
ev "$NOW" s2 ok; sleep 1.5
ev "$NOW" bad ok; ev "$NOW" s1 ok; sleep 2
: > "$TMP/stop"
for _ in $(seq 1 40); do kill -0 "$FOLLOWER" 2>/dev/null || break; sleep 0.25; done
kill -0 "$FOLLOWER" 2>/dev/null && fail "the follower must end once stage 1 is done and nothing is ready"
wait "$FOLLOWER" || fail "the follower ends cleanly"; FOLLOWER=""
[[ "$(awk '{print $1}' "$CALLS" | tr '\n' ' ')" == "s2 s1 bad " ]] || { cat "$CALLS"; fail "isolates run as they become ready, in sheet order within a batch, each once"; }
grep -q "^s2 $TMP/work/results $TMP/work/events.jsonl 1$" "$CALLS" || { cat "$CALLS"; fail "private results and events folders, one isolate at a time"; }
grep -q $'^bad\tfailed' "$TMP/work/done.tsv" && grep -q $'^s1\tok' "$TMP/work/done.tsv" || fail "a failing isolate is recorded and the others go on"
grep -q '"event":"overlap_stage2","sample":"s1","status":"ok"' "$TMP/events.jsonl" || fail "an overlap_stage2 event per isolate"
grep -q "stage 2 does it again and reports it" "$TMP/follow.out" || fail "the failure says stage 2 will do it again"
echo "  ok    the follower runs isolates as they become ready, privately, one at a time; a failure does not stop the others; it ends after stage 1"

# 3
: > "$CALLS"; : > "$TMP/events.jsonl"; rm -rf "$TMP/work" "$TMP/stop"; mkdir -p "$TMP/work"
cat > "$TMP/slow02.sh" <<EOF
#!/usr/bin/env bash
echo \$\$ > "$TMP/child.pid"; sleep 60
EOF
python3 -I "$PO" follow --events "$TMP/events.jsonl" --since "$NOW" --sheet "$TMP/sheet.tsv" --work "$TMP/work" --stop "$TMP/stop" --script "$TMP/slow02.sh" --poll 0.3 > /dev/null 2>&1 &
FOLLOWER=$!
ev "$NOW" s1 ok
for _ in $(seq 1 40); do [[ -s "$TMP/child.pid" ]] && break; sleep 0.25; done
child="$(cat "$TMP/child.pid")"
kill -0 "$child" 2>/dev/null || fail "the stage-2 child should be running"
kill "$FOLLOWER"; wait "$FOLLOWER" 2>/dev/null || true; FOLLOWER=""
for _ in $(seq 1 40); do kill -0 "$child" 2>/dev/null || break; sleep 0.25; done
kill -0 "$child" 2>/dev/null && { kill "$child"; fail "stopping the follower must stop its stage-2 process"; }
echo "  ok    stopping the run stops the early stage 2 too"

# 4: equality with the real stage 2
make_sample() {
    local d="$1/$2"; mkdir -p "$d"
    { printf '>chr1 chromosome\n'; for _ in $(seq 1 30); do printf 'GGGCCCATATACGTTGCAAC\n'; done
      printf '>p1 plasmid\n'; for _ in $(seq 1 6); do printf 'TTGACCAGTAGCTAGGATCC\n'; done; } > "$d/reference.fna"
    printf 'sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t600\np1\tPLASMID\t120\n' > "$d/truth.tsv"
    printf '@r\nACGTACGTAC\n+\nIIIIIIIIII\n' | gzip > "$d/SRR_1.fastq.gz"
    printf '@r\nACGTACGTAC\n+\nIIIIIIIIII\n' | gzip > "$d/SRR_2.fastq.gz"
}
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\n' > "$TMP/sheet2.tsv"
for side in alone overlap; do
    mkdir -p "$TMP/$side/results" "$TMP/$side/logs" "$TMP/$side/tmp"
    make_sample "$TMP/$side/data" s1; make_sample "$TMP/$side/data" s2
done
stage2() {   # stage2 SIDE
    DATA_DIR="$TMP/$1/data" RESULTS_DIR="$TMP/$1/results" LOG_DIR="$TMP/$1/logs" TMP_DIR="$TMP/$1/tmp" SAMPLE_SHEET="$TMP/sheet2.tsv" REQUIRE_CURATED_METADATA=0 \
        RUN_PROTEIN_ANNOTATION=0 RUN_REFERENCE_ANNOTATION=0 RUN_DIMER_DETECTION=0 MAX_PARALLEL_SAMPLES=1 bash "$ROOT/scripts/02_truth.sh" > "$TMP/$1/stage.log" 2>&1 \
        || { tail -20 "$TMP/$1/stage.log"; fail "stage 2 ($1)"; }
}
stage2 alone
: > "$TMP/events2.jsonl"; : > "$TMP/stop2"
printf '{"epoch":%s,"event":"download_end","sample":"s1","status":"ok"}\n{"epoch":%s,"event":"download_end","sample":"s2","status":"ok"}\n' "$NOW" "$NOW" > "$TMP/events2.jsonl"
DATA_DIR="$TMP/overlap/data" LOG_DIR="$TMP/overlap/logs" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 RUN_REFERENCE_ANNOTATION=0 RUN_DIMER_DETECTION=0 \
    python3 -I "$PO" follow --events "$TMP/events2.jsonl" --since "$NOW" --sheet "$TMP/sheet2.tsv" --work "$TMP/overlap/work" --stop "$TMP/stop2" --poll 0.2 > "$TMP/follow2.out" 2>&1 \
    || { cat "$TMP/follow2.out"; fail "the follower with the real stage 2"; }
[[ "$(grep -c $'\tok\t' "$TMP/overlap/work/done.tsv")" == 2 ]] || { cat "$TMP/overlap/work/done.tsv" "$TMP/follow2.out"; fail "the early stage 2 finished both isolates"; }
stage2 overlap
sums() { (cd "$TMP/$1/data" && find . -type f ! -name 'stage2_timing.tsv' -print0 | sort -z | xargs -0 sha256sum); }
diff <(sums alone) <(sums overlap) || fail "per-isolate files differ between stage 2 alone and stage 2 after an early stage 2"
[[ "$(sums overlap | wc -l)" -ge 8 ]] || fail "too few files compared"
[[ ! -e "$TMP/overlap/results/run_events.jsonl" ]] || ! grep -q overlap "$TMP/overlap/results/run_events.jsonl" || true
echo "  ok    stage 2 after an early stage 2 is byte-identical to stage 2 alone ($(sums overlap | wc -l) files)"

# 5
grep -q '^export PIPELINE_OVERLAP="${PIPELINE_OVERLAP:-0}"' "$ROOT/config/config.sh" || fail "PIPELINE_OVERLAP must default to 0"
echo "  ok    PIPELINE_OVERLAP is off by default"
echo "pipeline overlap checks passed"
