#!/usr/bin/env bash
# End-to-end regression for scripts/08_operational_reconstruct.sh: a brand-new
# operational sample (no complete-reference truth) must go from raw reads to
# a selected candidate FASTA using only ONE reconstruction tool, via fake
# tool binaries so it runs offline without any real bioinformatics tool.
#
# Covers both ways the tool can be chosen (an explicit --tool override, and
# the benchmark-recommendation lookup this feature depends on), and that the
# stage never touches DATA_DIR/RESULTS_DIR/LOG_DIR before they exist.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
echo prefetch >> "$TMP/calls.log"
outdir="" run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) outdir="\$2"; shift 2;; *) run="\$1"; shift;; esac; done
mkdir -p "\$outdir/\$run"; touch "\$outdir/\$run/\$run.sra"
EOF
cat > "$TMP/bin/fasterq-dump" <<EOF
#!/usr/bin/env bash
echo fasterq-dump >> "$TMP/calls.log"
outdir=""
args=("\$@")
for ((i=0;i<\${#args[@]};i++)); do case "\${args[\$i]}" in -O) outdir="\${args[\$((i+1))]}";; esac; done
sra="\$(basename "\${args[-1]}")"; sra="\${sra%.sra}"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_1.fastq"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_2.fastq"
EOF
cat > "$TMP/bin/fastp" <<EOF
#!/usr/bin/env bash
echo fastp >> "$TMP/calls.log"
i1="" i2="" o1="" o2=""
while [[ \$# -gt 0 ]]; do case "\$1" in -i) i1="\$2"; shift 2;; -I) i2="\$2"; shift 2;; -o) o1="\$2"; shift 2;; -O) o2="\$2"; shift 2;; *) shift;; esac; done
cp "\$i1" "\$o1"; cp "\$i2" "\$o2"
EOF
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
echo spades >> "$TMP/calls.log"
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>contig1\nACGTACGTACGT\n' > "\$outdir/contigs.fasta"
EOF
cat > "$TMP/bin/mob_recon" <<EOF
#!/usr/bin/env bash
echo mob_recon >> "$TMP/calls.log"
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in --outdir) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>p1\nACGT\n' > "\$outdir/plasmid_1.fasta"
EOF
cat > "$TMP/bin/platon" <<EOF
#!/usr/bin/env bash
echo platon >> "$TMP/calls.log"
outdir="" prefix=""
while [[ \$# -gt 0 ]]; do case "\$1" in --output) outdir="\$2"; shift 2;; --prefix) prefix="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>c1\nACGT\n' > "\$outdir/\$prefix.plasmid.fasta"
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump" "$TMP/bin/fastp" "$TMP/bin/spades.py" "$TMP/bin/mob_recon" "$TMP/bin/platon"

reconstruct() {
    PATH="$TMP/bin:$PATH" \
        DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        bash "$ROOT/scripts/08_operational_reconstruct.sh" "$@"
}

# --- explicit --tool override: deliberately never populate DATA_DIR/
# RESULTS_DIR/LOG_DIR beforehand, since a brand-new deployment may call this
# as its very first command. ---
: > "$TMP/calls.log"
reconstruct --sample opA --sra SRR1 --tool platon > "$TMP/stage.log" 2>&1
called="$(sort "$TMP/calls.log" | tr '\n' ' ')"
[[ "$called" == "fasterq-dump fastp platon prefetch spades " ]] || {
    echo "FAIL: expected only platon's toolchain, got: $called" >&2; cat "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/opA/selected_candidate/candidate.plasmid.fasta" ]] || {
    echo "FAIL: no candidate FASTA for explicit-tool run" >&2; exit 1; }
report="$TMP/results/opA/selection_report.json"
grep -q '"selected_tool": "platon"' "$report" || { echo "FAIL: report did not select platon" >&2; cat "$report" >&2; exit 1; }
grep -q '"selection_type": "explicit_tool_override"' "$report" || { echo "FAIL: report is not marked as an explicit override" >&2; exit 1; }
grep -q '"truth_available": false' "$report" || { echo "FAIL: report must record truth_available: false" >&2; exit 1; }
echo "explicit --tool override reconstructs with only that tool -> PASS"

# --- recommendation-driven: no --tool given, must be read from
# benchmark.recommendations.tsv (this is the path that was silently
# non-functional before the select_unknown_sample.py field-name fix). ---
mkdir -p "$TMP/results"
cat > "$TMP/results/benchmark.recommendations.tsv" <<'EOF'
scope	group	tool	eligible	recommendation	reason	n_scored	coverage	mean_f1	mean_precision	mean_recall	mean_plasmid_recall	mean_bin_f1	failure_rate	median_runtime_seconds	median_peak_rss_kb	decision_score
overall	all	mob_recon	true	primary	coverage-gated multi-objective recommendation	10	1.0000	0.9500	0.9600	0.9400		0.0000	120.00	500000	0.9200
overall	all	platon	true	none	insufficient coverage or not the highest eligible decision score	10	1.0000	0.9000	0.9100	0.8900		0.1000	80.00	400000	0.8500
EOF
: > "$TMP/calls.log"
reconstruct --sample opB --sra SRR2 > "$TMP/stage.log" 2>&1
called="$(sort "$TMP/calls.log" | tr '\n' ' ')"
[[ "$called" == "fasterq-dump fastp mob_recon prefetch spades " ]] || {
    echo "FAIL: recommendation lookup should have chosen mob_recon, got: $called" >&2; cat "$TMP/stage.log" >&2; exit 1; }
report="$TMP/results/opB/selection_report.json"
grep -q '"selected_tool": "mob_recon"' "$report" || { echo "FAIL: report did not select mob_recon" >&2; cat "$report" >&2; exit 1; }
grep -q '"selection_type": "operational_method_recommendation_only"' "$report" || {
    echo "FAIL: report is not marked as recommendation-driven" >&2; exit 1; }
echo "no --tool given follows the benchmark recommendation (mob_recon) -> PASS"

# --- a prior benchmark sample's own results must be untouched: this stage
# only ever builds its own one-row sample sheet for the new sample, so it
# cannot rerun or overwrite an existing benchmark sample's output. ---
mkdir -p "$TMP/results/benched_sample"
printf '>already there\nACGT\n' > "$TMP/results/benched_sample/pred_mob_recon.plasmid.fasta"
before="$(md5sum "$TMP/results/benched_sample/pred_mob_recon.plasmid.fasta")"
reconstruct --sample opC --sra SRR3 --tool platon > "$TMP/stage.log" 2>&1
after="$(md5sum "$TMP/results/benched_sample/pred_mob_recon.plasmid.fasta")"
[[ "$before" == "$after" ]] || { echo "FAIL: an unrelated benchmark sample's output was modified" >&2; exit 1; }
echo "an existing benchmark sample's output is left untouched -> PASS"

echo "ALL OPERATIONAL RECONSTRUCT TESTS PASSED"
