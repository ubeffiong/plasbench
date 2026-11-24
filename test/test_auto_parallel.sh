#!/usr/bin/env bash
# AUTO_PARALLEL (config/config.sh, scripts/lib.sh auto_parallel_apply, python/parallel_plan.py): stage 5 on a 4-isolate fixture.
#   1. AUTO_PARALLEL=0 is the sequential baseline (one aligner at a time)
#   2. AUTO_PARALLEL=1 on a pretend 6-CPU, 8 GB machine scores 3 isolates at a time, divides the threads (2 each: minimap2 -t 2), says so in the log and in a
#      parallel_plan event, and every results table is byte-identical to the baseline
#   3. an explicit MAX_PARALLEL_SAMPLES wins over the plan; an explicit THREADS is not divided
# Real score_plasmids.py, a fake minimap2 (offline).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
command -v python3 >/dev/null || { echo "SKIP: python3 not found"; exit 0; }
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat > "$TMP/bin/minimap2" <<EOF
#!/usr/bin/env bash
t=""; prev=""; for a in "\$@"; do [[ "\$prev" == "-t" ]] && t="\$a"; prev="\$a"; done
echo "START \$\$ t=\$t" >> "$TMP/align_events.log"
sleep 0.4
echo "END \$\$" >> "$TMP/align_events.log"
printf 'q1\t100\t0\t100\t+\tplasmidA\t100\t0\t100\t100\t100\t60\n'
EOF
chmod +x "$TMP/bin/minimap2"

fresh() {   # fresh DIR: a 4-isolate fixture
    local base="$1" s
    rm -rf "$base"; mkdir -p "$base/logs"
    for s in s1 s2 s3 s4; do
        mkdir -p "$base/data/$s" "$base/results/$s/visualization"
        printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n' > "$base/data/$s/truth.tsv"
        printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$base/data/$s/reference.fna"
        printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$base/results/$s/pred_toolx.plasmid.fasta"
        touch "$base/results/$s/.toolx.complete"
    done
    printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\ns2\tNA\tSRR\ns3\tNA\tSRR\ns4\tNA\tSRR\n' > "$base/sheet.tsv"
}

run_stage() {   # run_stage DIR VAR=VALUE...
    local base="$1"; shift
    : > "$TMP/align_events.log"
    env -u MAX_PARALLEL_SAMPLES -u THREADS -u PLASBENCH_SAMPLES_EXPLICIT -u PLASBENCH_THREADS_EXPLICIT \
        PATH="$TMP/bin:$PATH" DATA_DIR="$base/data" RESULTS_DIR="$base/results" LOG_DIR="$base/logs" TMP_DIR="$base/tmp" \
        SAMPLE_SHEET="$base/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 PLASBENCH_TEST_CPUS=6 PLASBENCH_TEST_AVAILABLE_MB=8192 "$@" \
        bash "$ROOT/scripts/05_score.sh" > "$base/stage.log" 2>&1 || { cat "$base/stage.log" >&2; fail "stage 5 failed ($*)"; }
}
peak() { awk '$1 == "START" { n++; if (n > m) m = n } $1 == "END" { n-- } END { print m + 0 }' "$TMP/align_events.log"; }
tables() {   # every results file except logs, events and stage_timing.tsv (wall-clock times), as "path sha256"
    (cd "$1/results" && find . -type f ! -name 'run_events.jsonl' ! -name 'stage_timing.tsv' ! -name '*.log' ! -name '.*' ! -path './.*' -print0 | sort -z | xargs -0 sha256sum)
}

# 1
fresh "$TMP/seq"; run_stage "$TMP/seq" AUTO_PARALLEL=0
[[ "$(peak)" == 1 ]] || fail "AUTO_PARALLEL=0 must score one isolate at a time (peak $(peak))"
grep -q "AUTO_PARALLEL" "$TMP/seq/stage.log" && fail "AUTO_PARALLEL=0 prints no plan"
echo "  ok    AUTO_PARALLEL=0: one isolate at a time"

# 2
fresh "$TMP/par"; run_stage "$TMP/par" AUTO_PARALLEL=1
p="$(peak)"
[[ "$p" -ge 2 && "$p" -le 3 ]] || { cat "$TMP/align_events.log"; fail "AUTO_PARALLEL=1 on 6 CPUs must score 2-3 isolates at once (peak $p)"; }
grep -q "AUTO_PARALLEL: stage 5 is running 3 isolates at a time: 6 CPUs, 8.0 GB free (2 threads each" "$TMP/par/stage.log" || { cat "$TMP/par/stage.log"; fail "the plan line"; }
grep -q '"event":"parallel_plan".*"slots":"3".*"threads":"2"' "$TMP/par/results/run_events.jsonl" || fail "a parallel_plan event with slots and threads"
! grep -E "^START [0-9]+ t=[0-9]+$" "$TMP/align_events.log" | grep -vq " t=2$" || { cat "$TMP/align_events.log"; fail "the threads are divided: every minimap2 gets -t 2 (3 x 2 = 6 CPUs, never more)"; }
echo "  ok    AUTO_PARALLEL=1: 3 isolates at a time, 2 threads each, said in the log and an event"
diff <(tables "$TMP/seq") <(tables "$TMP/par") || fail "parallel results differ from the sequential ones"
[[ "$(tables "$TMP/par" | wc -l)" -ge 4 ]] || fail "the comparison saw too few files to mean anything"
echo "  ok    every results table of the parallel run is byte-identical to the sequential run ($(tables "$TMP/par" | wc -l) files)"

# 3
fresh "$TMP/exp"; run_stage "$TMP/exp" AUTO_PARALLEL=1 MAX_PARALLEL_SAMPLES=1
[[ "$(peak)" == 1 ]] || fail "an explicit MAX_PARALLEL_SAMPLES=1 wins over AUTO_PARALLEL"
fresh "$TMP/thr"; run_stage "$TMP/thr" AUTO_PARALLEL=1 THREADS=5
grep -q "START .* t=5$" "$TMP/align_events.log" || { cat "$TMP/align_events.log"; fail "an explicit THREADS is not divided"; }
echo "  ok    an explicit MAX_PARALLEL_SAMPLES or THREADS is used as set"
echo "auto-parallel checks passed"
