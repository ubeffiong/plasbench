#!/usr/bin/env bash
# Regression: MAX_PARALLEL_TOOLS and MAX_PARALLEL_SAMPLES must produce actual
# overlap (not just correct output), and gplas2_mob must still wait for that
# sample's own mob_recon even when tools run concurrently.
#
# Overlap is asserted from the stub tools' own START/END logs, not from elapsed
# wall-clock time. On a loaded machine a genuinely parallel run can take as long
# as a sequential one, so a stopwatch measures the machine rather than the code,
# and the test fails for reasons that are not defects. Counting how many tools
# were running at once answers the question the test is actually asking.
#
# The gplas2_mob ordering check further down stays timestamp-based on purpose:
# it is a causal assertion (did gplas start only after mob_recon finished?),
# not a speed one, so a clock is the right instrument there.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DELAY=0.4
mkdir -p "$TMP/bin"
cat > "$TMP/bin/mob_recon" <<EOF
#!/usr/bin/env bash
echo "START mob_recon" >> "$TMP/tool_events.log"
date +%s.%N >> "$TMP/mob_recon_end.log.tmp"
sleep $DELAY
date +%s.%N >> "$TMP/mob_recon_end.log"
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in --outdir) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>p1\nACGT\n' > "\$outdir/plasmid_1.fasta"
echo "END mob_recon" >> "$TMP/tool_events.log"
EOF
cat > "$TMP/bin/platon" <<EOF
#!/usr/bin/env bash
echo "START platon" >> "$TMP/tool_events.log"
sleep $DELAY
outdir="" prefix=""
while [[ \$# -gt 0 ]]; do case "\$1" in --output) outdir="\$2"; shift 2;; --prefix) prefix="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>c1\nACGT\n' > "\$outdir/\$prefix.plasmid.fasta"
echo "END platon" >> "$TMP/tool_events.log"
EOF
cat > "$TMP/bin/plasmidspades.py" <<EOF
#!/usr/bin/env bash
echo "START plasmidspades" >> "$TMP/tool_events.log"
sleep $DELAY
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>NODE_1\nACGT\n' > "\$outdir/contigs.fasta"
echo "END plasmidspades" >> "$TMP/tool_events.log"
EOF
cat > "$TMP/bin/gplas" <<EOF
#!/usr/bin/env bash
echo "START gplas" >> "$TMP/tool_events.log"
date +%s.%N >> "$TMP/gplas_start.log"
sleep $DELAY
mkdir -p results
printf '>bin1\nACGT\n' > results/plasmids.fasta
echo "END gplas" >> "$TMP/tool_events.log"
EOF
chmod +x "$TMP/bin/mob_recon" "$TMP/bin/platon" "$TMP/bin/plasmidspades.py" "$TMP/bin/gplas"

setup_sample() {
    local sample="$1"
    mkdir -p "$TMP/data/$sample"
    printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/$sample/contigs.fasta"
    # Segment name matches the fake mob_recon's plasmid_1.fasta record id
    # (">p1"), since mob_to_gplas_classifier.py requires the two to overlap.
    printf 'S\tp1\tACGT\n' > "$TMP/data/$sample/assembly_graph.gfa"
}

run_stage() {
    PATH="$TMP/bin:$PATH" \
        DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
        "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

# Highest number of stub tools running simultaneously, from their own logs.
peak_concurrent() {
    awk '$1 == "START" { n++; if (n > max) max = n }
         $1 == "END"   { n-- }
         END           { print max + 0 }' "$TMP/tool_events.log"
}

# --- tool-level parallelism: mob_recon, platon, plasmidspades must overlap ---
setup_sample s1
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/sheet.tsv"

: > "$TMP/tool_events.log"
run_stage env RUN_GPLAS2_MOB=0 MAX_PARALLEL_TOOLS=1
sequential_peak="$(peak_concurrent)"
[[ -s "$TMP/results/s1/pred_mob_recon.plasmid.fasta" && -s "$TMP/results/s1/pred_platon.plasmid.fasta" \
    && -s "$TMP/results/s1/pred_plasmidspades.plasmid.fasta" ]] || {
    echo "FAIL: not all three tools produced predictions (sequential baseline)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$sequential_peak" -ge 1 ]] || {
    echo "FAIL: the stub tools never ran, so this test proves nothing" >&2
    cat "$TMP/stage.log" >&2; exit 1; }
[[ "$sequential_peak" -eq 1 ]] || {
    echo "FAIL: MAX_PARALLEL_TOOLS=1 ran $sequential_peak tools at once; it must serialise" >&2
    cat "$TMP/tool_events.log" >&2; exit 1; }
echo "MAX_PARALLEL_TOOLS=1 serialises tools (peak 1 concurrent tool) -> PASS"
rm -rf "$TMP/results"

: > "$TMP/tool_events.log"
run_stage env RUN_GPLAS2_MOB=0 MAX_PARALLEL_TOOLS=3
parallel_peak="$(peak_concurrent)"
[[ -s "$TMP/results/s1/pred_mob_recon.plasmid.fasta" && -s "$TMP/results/s1/pred_platon.plasmid.fasta" \
    && -s "$TMP/results/s1/pred_plasmidspades.plasmid.fasta" ]] || {
    echo "FAIL: not all three tools produced predictions (parallel run)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$parallel_peak" -ge 2 ]] || {
    echo "FAIL: MAX_PARALLEL_TOOLS=3 never had two tools running at once (peak $parallel_peak)" >&2
    cat "$TMP/tool_events.log" >&2; exit 1; }
echo "MAX_PARALLEL_TOOLS=3 overlaps independent tools (peak $parallel_peak concurrent tools) -> PASS"

rm -rf "$TMP/results" "$TMP/mob_recon_end.log" "$TMP/mob_recon_end.log.tmp" "$TMP/gplas_start.log"

# --- dependency ordering under concurrency: gplas2_mob must still wait for
# mob_recon, even with tool-level parallelism turned all the way up. ---
run_stage env RUN_GPLAS2_MOB=1 GPLAS2_MIN_CONTIG_LENGTH=1 MAX_PARALLEL_TOOLS=4
[[ -s "$TMP/results/s1/pred_gplas2_mob.plasmid.fasta" ]] || {
    echo "FAIL: gplas2_mob did not produce a prediction" >&2; cat "$TMP/stage.log" >&2; exit 1; }
mob_recon_end="$(cat "$TMP/mob_recon_end.log")"
gplas_start="$(cat "$TMP/gplas_start.log")"
python3 -c "
mob_end, gplas_start = float('$mob_recon_end'), float('$gplas_start')
assert gplas_start >= mob_end, f'gplas started ({gplas_start}) before mob_recon finished ({mob_end})'
" || { echo "FAIL: gplas2_mob started before mob_recon finished" >&2; exit 1; }
echo "gplas2_mob still waits for mob_recon even at MAX_PARALLEL_TOOLS=4 -> PASS"

rm -rf "$TMP/results"

# --- sample-level parallelism: three samples, one tool each, must overlap ---
setup_sample s2; setup_sample s3
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\ns3\tNA\tSRR3\n' > "$TMP/sheet.tsv"

: > "$TMP/tool_events.log"
run_stage env RUN_MOB_RECON=1 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 MAX_PARALLEL_SAMPLES=1
sequential_peak="$(peak_concurrent)"
for s in s1 s2 s3; do
    [[ -s "$TMP/results/$s/pred_mob_recon.plasmid.fasta" ]] || {
        echo "FAIL: sample $s has no mob_recon prediction (sequential baseline)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
done
[[ "$sequential_peak" -eq 1 ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=1 ran $sequential_peak samples at once; it must serialise" >&2
    cat "$TMP/tool_events.log" >&2; exit 1; }
echo "MAX_PARALLEL_SAMPLES=1 serialises samples (peak 1 concurrent sample) -> PASS"
rm -rf "$TMP/results"

: > "$TMP/tool_events.log"
run_stage env RUN_MOB_RECON=1 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GPLAS2_MOB=0 MAX_PARALLEL_SAMPLES=3
parallel_peak="$(peak_concurrent)"
for s in s1 s2 s3; do
    [[ -s "$TMP/results/$s/pred_mob_recon.plasmid.fasta" ]] || {
        echo "FAIL: sample $s has no mob_recon prediction (parallel run)" >&2; cat "$TMP/stage.log" >&2; exit 1; }
done
[[ "$parallel_peak" -ge 2 ]] || {
    echo "FAIL: MAX_PARALLEL_SAMPLES=3 never had two samples running at once (peak $parallel_peak)" >&2
    cat "$TMP/tool_events.log" >&2; exit 1; }
echo "MAX_PARALLEL_SAMPLES=3 overlaps independent samples (peak $parallel_peak concurrent samples) -> PASS"

# tool_status.tsv row order must stay in sample-sheet order regardless of
# which sample's job actually finished first.
sample_order="$(tail -n +2 "$TMP/results/tool_status.tsv" | cut -f1 | tr '\n' ' ')"
[[ "$sample_order" == "s1 s2 s3 " ]] || {
    echo "FAIL: tool_status.tsv sample order was '$sample_order', expected 's1 s2 s3 '" >&2; exit 1; }
echo "tool_status.tsv keeps deterministic sample order after parallel execution -> PASS"

echo "ALL PARALLEL EXECUTION TESTS PASSED"
