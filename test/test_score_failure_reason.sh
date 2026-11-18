#!/usr/bin/env bash
# Regression (audit AU-035, AU-049 shell side): score_failures.tsv carries the actual failure reason (the last line the scorer wrote), not
# just "see <log>"; and scores.tsv / score_failures.tsv are built beside the final file and renamed over it (no .new/.tmp left behind).
# Uses the real score_plasmids.py with a fake minimap2 whose alignment output is unusable for one sample. Offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/logs"
cat > "$TMP/bin/minimap2" <<EOF
#!/usr/bin/env bash
if [[ "\${FAKE_MINIMAP2_BAD:-0}" == "1" ]]; then printf 'not\ta\tpaf\n'; exit 0; fi
printf 'q1\t100\t0\t100\t+\tplasmidA\t100\t0\t100\t100\t100\t60\n'
EOF
chmod +x "$TMP/bin/minimap2"

setup_sample() {
    local tool="$2" sdir="$TMP/data/$1" rdir="$TMP/results/$1"
    mkdir -p "$sdir" "$rdir" "$rdir/visualization"
    printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n' > "$sdir/truth.tsv"
    printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$sdir/reference.fna"
    printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$rdir/pred_${tool}.plasmid.fasta"
    touch "$rdir/.${tool}.complete"
}
setup_sample s1 toolx
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"
stage5() {
    env PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" SAMPLE_SHEET="$TMP/sheet.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 "$@" bash "$ROOT/scripts/05_score.sh" > "$TMP/stage.log" 2>&1
}

# a good run first: leftover temp files must not exist, and a previous scores.tsv is replaced whole
printf 'PREVIOUS CONTENT\n' > "$TMP/results/scores.tsv"
stage5 || { echo "FAIL: a good run must finish" >&2; tail -8 "$TMP/stage.log" >&2; exit 1; }
[[ "$(head -c 8 "$TMP/results/scores.tsv")" != "PREVIOUS" && "$(wc -l < "$TMP/results/scores.tsv")" -ge 2 ]] || { echo "FAIL: scores.tsv must be the complete new table" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
[[ -z "$(find "$TMP/results" -maxdepth 1 \( -name '*.new' -o -name '*.tmp' \))" ]] || { echo "FAIL: temporary merge files must not be left behind" >&2; ls -a "$TMP/results" >&2; exit 1; }
echo "scores.tsv is replaced whole and no temporary merge file is left -> PASS"

# an unusable alignment: the failure row carries the scorer's own last line
rm -f "$TMP/results/scores.tsv"
stage5 FAKE_MINIMAP2_BAD=1 || { echo "FAIL: a scoring failure is recorded, not fatal" >&2; tail -8 "$TMP/stage.log" >&2; exit 1; }
reason="$(awk -F'\t' '$1 == "s1" && $2 == "toolx" {print $4}' "$TMP/results/score_failures.tsv")"
[[ -n "$reason" ]] || { echo "FAIL: expected a score_failures row for s1/toolx" >&2; cat "$TMP/results/score_failures.tsv" >&2; tail -5 "$TMP/stage.log" >&2; exit 1; }
[[ "$reason" != "see "* ]] || { echo "FAIL: the reason must be the real message, not 'see <log>' (got: $reason)" >&2; exit 1; }
[[ "$reason" == *"(log: "*"s1.toolx.score.log)" ]] || { echo "FAIL: the reason must still say where the log is (got: $reason)" >&2; exit 1; }
echo "score_failures.tsv carries the actual reason: ${reason%% (log:*} -> PASS"

echo "ALL SCORE FAILURE REASON TESTS PASSED"
