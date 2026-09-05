#!/usr/bin/env bash
# Regression for Trycycler -> MOB-Recon: the circularity guard applies (same
# as every other stage-7 tool), and -- the point of this test -- a single
# cluster failing reconciliation is DROPPED and the sample still completes on
# the clusters that survive (the resolved design decision for this tool),
# while every cluster failing, or any other step failing outright, fails the
# whole sample. Runs fully offline against stub `trycycler`/`flye`/
# `mob_recon` binaries; no real Trycycler required.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/results" "$TMP/logs"
printf 'x' | gzip > "$TMP/data/s1/long_reads.fastq.gz"

cat > "$TMP/bin/flye" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in --out-dir) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out"
printf '>contig_1\nACGTACGT\n' > "$out/assembly.fasta"
EOS

# Stub trycycler: branches on its subcommand. Cluster count and which
# cluster's reconcile should fail are controlled by env vars so each test
# scenario can drive the same stub differently.
cat > "$TMP/bin/trycycler" <<'EOS'
#!/usr/bin/env bash
sub="$1"; shift
case "$sub" in
subsample)
    out=""
    while [[ $# -gt 0 ]]; do case "$1" in --out_dir) out="$2"; shift 2;; *) shift;; esac; done
    [[ "${TRYCYCLER_STUB_FAIL_SUBSAMPLE:-0}" == "1" ]] && { echo "simulated subsample failure" >&2; exit 1; }
    mkdir -p "$out"
    n="${TRYCYCLER_STUB_CLUSTER_COUNT:-2}"
    for i in $(seq 1 "$n"); do printf '@r\nACGT\n+\nIIII\n' > "$out/sample_0$i.fastq"; done
    ;;
cluster)
    out=""
    while [[ $# -gt 0 ]]; do case "$1" in --out_dir) out="$2"; shift 2;; *) shift;; esac; done
    [[ "${TRYCYCLER_STUB_FAIL_CLUSTER_CMD:-0}" == "1" ]] && { echo "simulated clustering failure" >&2; exit 1; }
    n="${TRYCYCLER_STUB_CLUSTER_COUNT:-2}"
    for i in $(seq 1 "$n"); do mkdir -p "$out/cluster_00$i/1_contigs"; done
    ;;
reconcile)
    dir=""
    while [[ $# -gt 0 ]]; do case "$1" in --cluster_dir) dir="$2"; shift 2;; *) shift;; esac; done
    base="$(basename "$dir")"
    if [[ "${TRYCYCLER_STUB_FAIL_ALL_RECONCILE:-0}" == "1" || "$base" == "${TRYCYCLER_STUB_FAIL_CLUSTER:-__none__}" ]]; then
        echo "simulated reconcile failure for $base" >&2; exit 1
    fi
    ;;
msa) ;;
partition)
    dirs=()
    while [[ $# -gt 0 ]]; do case "$1" in --cluster_dirs) shift; while [[ $# -gt 0 && "$1" != --* ]]; do dirs+=("$1"); shift; done;; *) shift;; esac; done
    for d in "${dirs[@]}"; do printf '@r\nACGT\n+\nIIII\n' > "$d/4_reads.fastq"; done
    ;;
consensus)
    dir=""
    while [[ $# -gt 0 ]]; do case "$1" in --cluster_dir) dir="$2"; shift 2;; *) shift;; esac; done
    printf '>%s_consensus\nACGTACGTACGT\n' "$(basename "$dir")" > "$dir/7_final_consensus.fasta"
    ;;
*) echo "unknown trycycler subcommand: $sub" >&2; exit 1 ;;
esac
EOS

cat > "$TMP/bin/mob_recon" <<'EOS'
#!/usr/bin/env bash
out=""
while [[ $# -gt 0 ]]; do case "$1" in --outdir) out="$2"; shift 2;; *) shift;; esac; done
mkdir -p "$out"
printf '>plasmid_contig\nACGT\n' > "$out/plasmid_1.fasta"
EOS
chmod +x "$TMP/bin/flye" "$TMP/bin/trycycler" "$TMP/bin/mob_recon"

sheet() {
    local extra_h="${1:-}" extra_v="${2:-}"
    if [[ -n "$extra_h" ]]; then
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\t%s\n' "$extra_h" > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\tlong_read\t%s\n' "$extra_v" >> "$TMP/sheet.tsv"
    else
        printf 'sample_id\tassembly_accession\tsra_run\ttruth_technology\n' > "$TMP/sheet.tsv"
        printf 's1\tGCF_1\tSRR1\tlong_read\n' >> "$TMP/sheet.tsv"
    fi
}

stage7() {
    rm -rf "$TMP/results"; mkdir -p "$TMP/results"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 \
    RUN_FLYE_MOB_RECON=0 RUN_PLASSEMBLER=0 RUN_HYBRACTER_LONG=0 RUN_HYBRACTER_HYBRID=0 \
    RUN_TRYCYCLER_MOB_RECON=1 TRYCYCLER_ASSEMBLY_COUNT=2 TRYCYCLER_STUB_CLUSTER_COUNT=2 \
    env "$@" bash "$ROOT/scripts/07_long_read_reconstruct.sh" > "$TMP/stage.log" 2>&1
}

status_field() {  # status_field <column-index>
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="trycycler_mob_recon" {print $c; exit}' "$TMP/results/tool_status.tsv"
}

# --- 1. Circular truth is refused by default. ------------------------------
sheet
stage7 || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "circular" || { echo "FAIL: expected a circular-truth reason" >&2; exit 1; }
echo "circular truth is refused by default -> PASS"

# --- 2. Normal completion: all clusters reconcile, sample completes. -------
sheet truth_independent_of_long_reads yes
stage7 || { echo "FAIL: normal completion should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed, got: $(status_field 3)" >&2; cat "$TMP/stage.log" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
[[ -s "$TMP/results/s1/pred_trycycler_mob_recon.plasmid.fasta" ]] || { echo "FAIL: expected a prediction file" >&2; exit 1; }
echo "normal completion: all clusters reconcile, sample completes -> PASS"

# --- 3. One cluster fails reconciliation: dropped, sample still completes. -
stage7 env TRYCYCLER_STUB_FAIL_CLUSTER=cluster_002 || { echo "FAIL: one dropped cluster should not abort the stage" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "completed" ]] || { echo "FAIL: expected completed with one cluster dropped, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "dropped 1 of 2 cluster" || { echo "FAIL: expected the reason to note 1 of 2 clusters dropped, got: $(status_field 5)" >&2; exit 1; }
echo "one cluster failing reconciliation is dropped; the sample still completes -> PASS"

# --- 4. Every cluster fails reconciliation: nothing to build a consensus
# from, so the whole sample fails (unlike a single dropped cluster). --------
stage7 env TRYCYCLER_STUB_FAIL_ALL_RECONCILE=1 || { echo "FAIL: stage should not abort even though the sample fails" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "failed" ]] || { echo "FAIL: expected failed when every cluster is unreconcilable, got: $(status_field 3)" >&2; cat "$TMP/results/tool_status.tsv" >&2; exit 1; }
status_field 5 | grep -qi "no cluster reconciled" || { echo "FAIL: expected a 'no cluster reconciled' reason, got: $(status_field 5)" >&2; exit 1; }
echo "every cluster failing reconciliation fails the whole sample -> PASS"

# --- 5. Missing long reads skips with a specific reason. -------------------
rm -f "$TMP/data/s1/long_reads.fastq.gz"
stage7 || { echo "FAIL: stage should not abort" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(status_field 3)" == "skipped" ]] || { echo "FAIL: expected skipped for missing long reads, got: $(status_field 3)" >&2; exit 1; }
status_field 5 | grep -qi "long-read" || { echo "FAIL: expected a missing-long-reads reason" >&2; exit 1; }
echo "missing long reads skips with a specific reason -> PASS"

echo "ALL TRYCYCLER MOB_RECON TESTS PASSED"
