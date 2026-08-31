#!/usr/bin/env bash
# run_demo.sh — exercise the SCORING + AGGREGATION path end-to-end on tiny
# synthetic data, with NO downloads and NO bioinformatics tools installed.
#
# It fabricates 2 samples and 3 "tools" with known behaviour, writes fake PAFs
# (as if minimap2 had run), scores them, and builds the leaderboard. Use this to
# confirm the Python engine works before you invest in the full install.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEMO="$ROOT/results_demo"
rm -rf "$DEMO"; mkdir -p "$DEMO"

PY="$ROOT/python"
SCORES="$DEMO/scores.tsv"; rm -f "$SCORES"

make_pred_fasta() {
    local paf="$1" fasta="$2"
    awk '!seen[$1]++ { printf ">%s\n", $1; for (i = 0; i < $2; i++) printf "A"; printf "\n" }' "$paf" > "$fasta"
}

# ---- Sample 1: chromosome 8000, plasmidA 2000, plasmidB 1500 (plasmid=3500) --
S1="$DEMO/sample1"; mkdir -p "$S1"
cat > "$S1/truth.tsv" <<'EOF'
sequence_id	molecule_type	length
chr1	CHROMOSOME	8000
pA	PLASMID	2000
pB	PLASMID	1500
EOF

# tool "goodtool": recovers both plasmids fully, no contamination -> perfect
cat > "$S1/good.paf" <<'EOF'
q1	2000	0	2000	+	pA	2000	0	2000	2000	2000	60
q2	1500	0	1500	+	pB	1500	0	1500	1500	1500	60
EOF
# tool "leaky": recovers pA fully but grabs 400 bp of chromosome -> lower precision
cat > "$S1/leaky.paf" <<'EOF'
q1	2000	0	2000	+	pA	2000	0	2000	2000	2000	60
q2	1500	0	1500	+	pB	1500	0	1500	1500	1500	60
q3	400	0	400	+	chr1	8000	0	400	400	400	60
EOF
# tool "shy": only finds pA, misses pB entirely -> lower recall
cat > "$S1/shy.paf" <<'EOF'
q1	2000	0	2000	+	pA	2000	0	2000	2000	2000	60
EOF

for t in good leaky shy; do
    make_pred_fasta "$S1/$t.paf" "$S1/$t.fasta"
    python3 "$PY/score_plasmids.py" --truth "$S1/truth.tsv" --paf "$S1/$t.paf" \
        --pred-fasta "$S1/$t.fasta" --sample sample1 --tool "$t" --out "$SCORES"
done

# ---- Sample 2: chromosome 9000, plasmidC 1000 (plasmid=1000) ----------------
S2="$DEMO/sample2"; mkdir -p "$S2"
cat > "$S2/truth.tsv" <<'EOF'
sequence_id	molecule_type	length
chr2	CHROMOSOME	9000
pC	PLASMID	1000
EOF
# good: full recovery
cat > "$S2/good.paf" <<'EOF'
q1	1000	0	1000	+	pC	1000	0	1000	1000	1000	60
EOF
# leaky: full recovery + 200 bp chromosome
cat > "$S2/leaky.paf" <<'EOF'
q1	1000	0	1000	+	pC	1000	0	1000	1000	1000	60
q2	200	0	200	+	chr2	9000	0	200	200	200	60
EOF
# shy: recovers half of pC
cat > "$S2/shy.paf" <<'EOF'
q1	500	0	500	+	pC	1000	0	500	500	500	60
EOF
for t in good leaky shy; do
    make_pred_fasta "$S2/$t.paf" "$S2/$t.fasta"
    python3 "$PY/score_plasmids.py" --truth "$S2/truth.tsv" --paf "$S2/$t.paf" \
        --pred-fasta "$S2/$t.fasta" --sample sample2 --tool "$t" --out "$SCORES"
done

echo
echo "===== per-sample scores ($SCORES) ====="
if command -v column >/dev/null 2>&1; then column -t -s$'\t' "$SCORES"; else cat "$SCORES"; fi

STATUS="$DEMO/tool_status.tsv"
{
    printf 'sample\ttool\tstatus\tprediction_fasta\treason\n'
    for sample in sample1 sample2; do
        for tool in good leaky shy; do
            printf '%s\t%s\tcompleted\t\t\n' "$sample" "$tool"
        done
    done
} > "$STATUS"

python3 "$PY/aggregate_results.py" --scores "$SCORES" --tool-status "$STATUS" --out-prefix "$DEMO/benchmark"

python3 "$PY/build_html_report.py" \
    --project-root "$ROOT" \
    --scores "$SCORES" \
    --tool-status "$STATUS" \
    --leaderboard "$DEMO/benchmark.leaderboard.tsv" \
    --out "$DEMO/benchmark.report.html"

echo
echo "===== leaderboard markdown ====="
cat "$DEMO/benchmark.leaderboard.md"
echo
echo "===== interactive HTML report ====="
echo "$DEMO/benchmark.report.html"
echo
echo "Demo outputs are in: $DEMO"
