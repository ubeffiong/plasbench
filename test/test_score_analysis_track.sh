#!/usr/bin/env bash
# Regression for the analysis_track fix: scripts/05_score.sh used to stamp one
# global $ANALYSIS_TRACK value onto every tool's score row for the whole
# invocation, rebuilding scores.tsv from scratch each run. That meant scoring
# a long-read tool by re-running stage 5 with --analysis-track long_read would
# silently relabel every short-read tool's rows too. Each tool's track must
# now come from its own config/tool_capabilities.tsv row, so a single stage-5
# run scores a mix of short_read/long_read/hybrid tools correctly in one pass.
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

# mob_recon (registry: short_read) and flye_mob_recon (registry: long_read)
# both produce a completed prediction for the same sample, as would happen
# once stage 7 runs before stage 5 in a single default pipeline invocation.
SDIR="$TMP/data/s1"; RDIR="$TMP/results/s1"
mkdir -p "$SDIR" "$RDIR/visualization"
printf 'sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n' > "$SDIR/truth.tsv"
printf '>plasmidA\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$SDIR/reference.fna"
for tool in mob_recon flye_mob_recon; do
    printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$RDIR/pred_${tool}.plasmid.fasta"
    touch "$RDIR/.${tool}.complete"
done
mkdir -p "$TMP/logs"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"

PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 \
    bash "$ROOT/scripts/05_score.sh" > "$TMP/stage.log" 2>&1 || { echo "FAIL: stage 5 should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }

SCORES="$TMP/results/scores.tsv"
[[ -s "$SCORES" ]] || { echo "FAIL: scores.tsv was not written" >&2; exit 1; }

mob_track="$(awk -F'\t' '$1=="s1" && $2=="mob_recon" {print $3}' "$SCORES")"
flye_track="$(awk -F'\t' '$1=="s1" && $2=="flye_mob_recon" {print $3}' "$SCORES")"
[[ "$mob_track" == "short_read" ]] || { echo "FAIL: mob_recon's analysis_track was '$mob_track', expected short_read" >&2; cat "$SCORES" >&2; exit 1; }
[[ "$flye_track" == "long_read" ]] || { echo "FAIL: flye_mob_recon's analysis_track was '$flye_track', expected long_read" >&2; cat "$SCORES" >&2; exit 1; }
echo "one stage-5 run scores a short_read and a long_read tool each under their own correct track -> PASS"

# A tool with no registry row must fall back to \$ANALYSIS_TRACK (with a
# warning), not abort the run or silently lose its row.
rm -f "$RDIR"/pred_*.plasmid.fasta "$RDIR"/.*.complete
printf '>q1\n%s\n' "$(printf 'A%.0s' $(seq 1 100))" > "$RDIR/pred_unregistered_tool.plasmid.fasta"
touch "$RDIR/.unregistered_tool.complete"
PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 ANALYSIS_TRACK=hybrid \
    bash "$ROOT/scripts/05_score.sh" > "$TMP/stage2.log" 2>&1 || { echo "FAIL: stage 5 should tolerate an unregistered tool" >&2; cat "$TMP/stage2.log" >&2; exit 1; }
grep -qi "no analysis_track declared" "$TMP/stage2.log" || { echo "FAIL: expected a warning about the missing registry row" >&2; cat "$TMP/stage2.log" >&2; exit 1; }
unreg_track="$(awk -F'\t' '$1=="s1" && $2=="unregistered_tool" {print $3}' "$SCORES")"
[[ "$unreg_track" == "hybrid" ]] || { echo "FAIL: unregistered tool's track was '$unreg_track', expected fallback to \$ANALYSIS_TRACK=hybrid" >&2; cat "$SCORES" >&2; exit 1; }
echo "a tool with no registry row falls back to \$ANALYSIS_TRACK with a warning, not an abort -> PASS"

echo "ALL SCORE ANALYSIS TRACK TESTS PASSED"
