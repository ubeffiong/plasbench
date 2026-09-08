#!/usr/bin/env bash
# Regression for scripts/05_score.sh's new RUN_QUAST_DIAGNOSTICS wiring
# (python/run_quast_diagnostics.py): off by default (no quast_diagnostics.tsv
# at all, run_quast_diagnostics.py never even invoked); on, it IS invoked
# per tool with --min-contig always passed, its own per-tool output is
# merged into a combined results/quast_diagnostics.tsv, and its own
# graceful "quast.py not installed" skip (already unit-tested directly in
# test_run_quast_diagnostics.py) never aborts the whole stage or drops the
# tool's own base-level score. The 3-way comparison logic itself and
# report.tsv parsing are covered separately by test_run_quast_diagnostics.py
# (with quast.py fully monkeypatched, avoiding a real binary and the
# accompanying Windows PATHEXT quirks of directly subprocess-launching a
# .py-suffixed script from Python -- irrelevant to a real deployment, where
# QUAST always runs on Linux/WSL); this test is about the stage-5 wiring
# around it, using a real (but always-graceful) "not installed" path.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat > "$TMP/bin/minimap2" <<'EOF'
#!/usr/bin/env bash
printf 'q1\t300\t0\t300\t+\tplasmidA\t300\t0\t300\t300\t300\t60\n'
EOF
chmod +x "$TMP/bin/minimap2"

SDIR="$TMP/data/s1"; RDIR="$TMP/results/s1"
mkdir -p "$SDIR" "$RDIR/visualization" "$TMP/logs"
printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t300\n' > "$SDIR/truth.tsv"
printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 300))" > "$SDIR/reference.fna"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"
printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 300))" > "$RDIR/pred_genomad.plasmid.fasta"
touch "$RDIR/.genomad.complete"

run_stage5() {
    rm -rf "$TMP/results/quast_diagnostics.tsv" "$RDIR/genomad.quast_diagnostics.tsv"
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
    "$@" bash "$ROOT/scripts/05_score.sh" > "$TMP/stage.log" 2>&1
}

# --- Off by default: run_quast_diagnostics.py is never even invoked, no
# output of any kind. ---
run_stage5 || { echo "FAIL: stage 5 should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ ! -e "$TMP/results/quast_diagnostics.tsv" ]] || { echo "FAIL: RUN_QUAST_DIAGNOSTICS=0 (default) should write no combined output" >&2; exit 1; }
[[ ! -e "$RDIR/genomad.quast_diagnostics.tsv" ]] || { echo "FAIL: RUN_QUAST_DIAGNOSTICS=0 (default) should write no per-tool output" >&2; exit 1; }
grep -qi "quast" "$TMP/stage.log" && { echo "FAIL: expected no mention of QUAST at all when RUN_QUAST_DIAGNOSTICS=0" >&2; cat "$TMP/stage.log" >&2; exit 1; }
echo "RUN_QUAST_DIAGNOSTICS=0 (default) computes nothing, never even invoked -> PASS"

# --- On, but quast.py is not installed (the real, common case on a fresh
# machine): the stage must still complete successfully, the tool's own
# base-level score must be retained, and a per-tool quast_diagnostics.tsv
# (header-only, run_quast_diagnostics.py's own graceful-skip contract) is
# still produced and merged, never a hard stage failure. ---
run_stage5 env RUN_QUAST_DIAGNOSTICS=1 || { echo "FAIL: stage 5 must not abort when quast.py is not installed" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$RDIR/genomad.quast_diagnostics.tsv" ]] || { echo "FAIL: expected a (header-only) per-tool quast_diagnostics.tsv even with quast.py missing" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ "$(tail -n +2 "$RDIR/genomad.quast_diagnostics.tsv" | wc -l)" -eq 0 ]] || { echo "FAIL: expected zero data rows when quast.py is not installed" >&2; cat "$RDIR/genomad.quast_diagnostics.tsv" >&2; exit 1; }
[[ -s "$TMP/results/quast_diagnostics.tsv" ]] || { echo "FAIL: expected a combined results/quast_diagnostics.tsv (header-only is still a real file)" >&2; exit 1; }
grep -q "^sample" "$TMP/results/quast_diagnostics.tsv" || { echo "FAIL: expected a real header row in the combined output" >&2; cat "$TMP/results/quast_diagnostics.tsv" >&2; exit 1; }
f1_col="$(awk -F'\t' '{for(i=1;i<=NF;i++) if($i=="f1") print i; exit}' "$TMP/results/scores.tsv")"
awk -F'\t' -v c="$f1_col" '$1=="s1" && $2=="genomad" {print $c; exit}' "$TMP/results/scores.tsv" | grep -q . \
    || { echo "FAIL: expected genomad's base-level f1 score to still be present" >&2; cat "$TMP/results/scores.tsv" >&2; exit 1; }
echo "RUN_QUAST_DIAGNOSTICS=1 with quast.py missing completes gracefully, retaining the base-level score -> PASS"

echo "ALL QUAST DIAGNOSTICS STAGE TESTS PASSED"
