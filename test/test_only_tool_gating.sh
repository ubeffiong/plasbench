#!/usr/bin/env bash
# Regression: ONLY_TOOL must restrict stage 4 to exactly one reconstruction
# tool for an operational sample, without changing the default (ONLY_TOOL
# unset) behavior that a benchmark run depends on. Uses fake tool binaries so
# it runs offline, without any real bioinformatics tool installed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/config"

cat > "$TMP/bin/mob_recon" <<EOF
#!/usr/bin/env bash
echo mob_recon >> "$TMP/calls.log"
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in --outdir) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"
printf '>p1\nACGT\n' > "\$outdir/plasmid_1.fasta"
EOF
cat > "$TMP/bin/platon" <<EOF
#!/usr/bin/env bash
echo platon >> "$TMP/calls.log"
outdir="" prefix=""
while [[ \$# -gt 0 ]]; do case "\$1" in --output) outdir="\$2"; shift 2;; --prefix) prefix="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"
printf '>c1\nACGT\n' > "\$outdir/\$prefix.plasmid.fasta"
EOF
cat > "$TMP/bin/plasmidspades.py" <<EOF
#!/usr/bin/env bash
echo plasmidspades >> "$TMP/calls.log"
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"
printf '>NODE_1\nACGT\n' > "\$outdir/contigs.fasta"
EOF
cat > "$TMP/bin/gplas" <<EOF
#!/usr/bin/env bash
echo gplas >> "$TMP/calls.log"
mkdir -p results
printf '>bin1\nACGT\n' > results/plasmids.fasta
EOF
chmod +x "$TMP/bin/mob_recon" "$TMP/bin/platon" "$TMP/bin/plasmidspades.py" "$TMP/bin/gplas"

printf '>contig1\nACGTACGTACGT\n' > "$TMP/data/s1/contigs.fasta"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_1.trim.fastq.gz"
printf '@r1\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR1_2.trim.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$TMP/config/accessions.tsv"

export DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" SAMPLE_SHEET="$TMP/config/accessions.tsv"
export REQUIRE_CURATED_METADATA=0

run_stage() {
    : > "$TMP/calls.log"
    rm -rf "$TMP/results"
    PATH="$TMP/bin:$PATH" "$@" bash "$ROOT/scripts/04_run_tools.sh" > "$TMP/stage.log" 2>&1
}

# Default (ONLY_TOOL unset): the three tools enabled by config.sh's defaults
# (mob_recon, platon, plasmidspades) must all still run, exactly as before
# this change -- this is the regression guard.
run_stage env
called="$(sort "$TMP/calls.log" | tr '\n' ' ')"
[[ "$called" == "mob_recon plasmidspades platon " ]] || {
    echo "FAIL: default run must call all three enabled tools, got: $called" >&2; exit 1; }
[[ -s "$RESULTS_DIR/s1/pred_mob_recon.plasmid.fasta" ]] || { echo "FAIL: mob_recon prediction missing" >&2; exit 1; }
[[ -s "$RESULTS_DIR/s1/pred_platon.plasmid.fasta" ]] || { echo "FAIL: platon prediction missing" >&2; exit 1; }
[[ -s "$RESULTS_DIR/s1/pred_plasmidspades.plasmid.fasta" ]] || { echo "FAIL: plasmidspades prediction missing" >&2; exit 1; }
echo "default (ONLY_TOOL unset) still runs every RUN_*-enabled tool -> PASS"

# ONLY_TOOL must restrict to exactly one tool, overriding RUN_* flags that are
# still on for the others (mob_recon and plasmidspades default to on).
run_stage env ONLY_TOOL=platon
[[ "$(cat "$TMP/calls.log")" == "platon" ]] || {
    echo "FAIL: ONLY_TOOL=platon must call only platon, got: $(tr '\n' ' ' < "$TMP/calls.log")" >&2; exit 1; }
[[ -s "$RESULTS_DIR/s1/pred_platon.plasmid.fasta" ]] || { echo "FAIL: platon prediction missing" >&2; exit 1; }
[[ ! -e "$RESULTS_DIR/s1/pred_mob_recon.plasmid.fasta" ]] || { echo "FAIL: mob_recon must not have run" >&2; exit 1; }
[[ ! -e "$RESULTS_DIR/s1/pred_plasmidspades.plasmid.fasta" ]] || { echo "FAIL: plasmidspades must not have run" >&2; exit 1; }
echo "ONLY_TOOL=platon restricts stage 4 to just platon -> PASS"

# gplas2_mob cannot run without MOB-recon's membership as its classifier seed
# (see scripts/04_run_tools.sh), so ONLY_TOOL=gplas2_mob must still bring up
# mob_recon as a prerequisite, while platon and plasmidspades stay off even
# though config.sh defaults them on.
run_stage env ONLY_TOOL=gplas2_mob
called="$(sort "$TMP/calls.log" | tr '\n' ' ')"
[[ "$called" == "mob_recon " ]] || {
    echo "FAIL: ONLY_TOOL=gplas2_mob must call mob_recon as a prerequisite and nothing else, got: $called" >&2; exit 1; }
[[ -s "$RESULTS_DIR/s1/pred_mob_recon.plasmid.fasta" ]] || { echo "FAIL: mob_recon prerequisite prediction missing" >&2; exit 1; }
grep -q '^s1	gplas2_mob	' "$RESULTS_DIR/tool_status.tsv" || { echo "FAIL: gplas2_mob has no status row" >&2; exit 1; }
echo "ONLY_TOOL=gplas2_mob brings up mob_recon as a prerequisite, nothing else -> PASS"

echo "ALL ONLY_TOOL GATING TESTS PASSED"
