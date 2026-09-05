#!/usr/bin/env bash
# Regression: scripts/05_score.sh must never let a PREVIOUS run's
# <tool>.pr_curve.tsv/<tool>.pr_summary.tsv survive a pass that does not
# itself produce fresh ones (no pred_<tool>.candidates.fasta/.scores.tsv this
# time, or the candidate-vs-reference mapping fails). Unlike scores.tsv
# (rebuilt fully from `: > "$SCORES"` each run) and $PAF (truncated via `>`
# redirection each run), these two files are only written when
# score_plasmids.py is actually given --pr-curve-out/--pr-summary-out this
# pass -- so a stale pair left on disk from an earlier successful pass would
# otherwise be silently re-merged into the CURRENT run's scores.tsv row by
# merge_pr_metrics.py's unconditional glob, misrepresenting stale data as
# fresh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat > "$TMP/bin/minimap2" <<'EOF'
#!/usr/bin/env bash
printf 'q1\t100\t0\t100\t+\tplasmidA\t100\t0\t100\t100\t100\t60\n'
EOF
chmod +x "$TMP/bin/minimap2"

SDIR="$TMP/data/s1"; RDIR="$TMP/results/s1"
mkdir -p "$SDIR" "$RDIR/visualization" "$TMP/logs"
printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n' > "$SDIR/truth.tsv"
printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$SDIR/reference.fna"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"

seq_a="$(printf 'A%.0s' $(seq 1 100))"
printf '>q1\n%s\n' "$seq_a" > "$RDIR/pred_genomad.plasmid.fasta"
touch "$RDIR/.genomad.complete"

run_stage5() {
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
    bash "$ROOT/scripts/05_score.sh" > "$TMP/stage.log" 2>&1
}

pr_auc_field() {
    awk -F'\t' -v c="$1" '$1=="s1" && $2=="genomad" {print $c; exit}' "$TMP/results/scores.tsv"
}

# Pass 1: genomad has real candidates/scores -> a genuine PR curve is written.
printf '>q1\n%s\n' "$seq_a" > "$RDIR/pred_genomad.candidates.fasta"
printf 'record_id\tprobability\nq1\t0.9000\n' > "$RDIR/pred_genomad.scores.tsv"
run_stage5 || { echo "FAIL: stage 5 pass 1 should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$RDIR/genomad.pr_summary.tsv" ]] || { echo "FAIL: expected a real pr_summary.tsv after pass 1" >&2; exit 1; }
pr_auc_header_index="$(awk -F'\t' '{for(i=1;i<=NF;i++) if($i=="pr_auc") print i; exit}' "$TMP/results/scores.tsv")"
first_auc="$(pr_auc_field "$pr_auc_header_index")"
[[ -n "$first_auc" ]] || { echo "FAIL: expected a non-empty pr_auc after pass 1" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
echo "pass 1 (real candidates/scores present): pr_auc is populated -> PASS"

# Pass 2: genomad no longer produces candidates/scores this run (adapter
# changed, or a partial rerun) -- but the OLD pr_curve.tsv/pr_summary.tsv
# from pass 1 are still sitting on disk untouched.
rm -f "$RDIR/pred_genomad.candidates.fasta" "$RDIR/pred_genomad.scores.tsv"
[[ -s "$RDIR/genomad.pr_summary.tsv" ]] || { echo "test setup error: pr_summary.tsv missing before pass 2" >&2; exit 1; }
run_stage5 || { echo "FAIL: stage 5 pass 2 should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }

[[ -s "$RDIR/genomad.pr_curve.tsv" ]] && { echo "FAIL: stale genomad.pr_curve.tsv from pass 1 survived pass 2" >&2; exit 1; }
[[ -s "$RDIR/genomad.pr_summary.tsv" ]] && { echo "FAIL: stale genomad.pr_summary.tsv from pass 1 survived pass 2" >&2; exit 1; }
echo "pass 2 (no candidates/scores this run): stale pr_curve.tsv/pr_summary.tsv are removed, not left behind -> PASS"

second_auc="$(pr_auc_field "$pr_auc_header_index")"
[[ -z "$second_auc" ]] || { echo "FAIL: expected pr_auc to be empty in pass 2 (no probability data this run), got stale value '$second_auc'" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
echo "pass 2's scores.tsv row has an empty pr_auc, not pass 1's stale value re-merged as if fresh -> PASS"

echo "ALL PR CURVE STALE CLEANUP TESTS PASSED"
