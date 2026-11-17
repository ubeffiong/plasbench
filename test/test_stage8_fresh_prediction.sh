#!/usr/bin/env bash
# Regression (audit AU-030): stage 8 must not accept a stale prediction. An uninstalled (skipped) or failed tool leaves any earlier
# results/<sample>/pred_<tool>.plasmid.fasta in place; stage 8 used to check only that the file was non-empty and carry on with it.
# It now requires this run's stage 4 to have recorded the tool as completed (or reused) and its .complete marker to exist.
# Fake SRA / fastp / SPAdes binaries, offline.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
export READ_SOURCE=sra
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat > "$TMP/bin/prefetch" <<EOF
#!/usr/bin/env bash
outdir="" run=""
while [[ \$# -gt 0 ]]; do case "\$1" in -O) outdir="\$2"; shift 2;; *) run="\$1"; shift;; esac; done
mkdir -p "\$outdir/\$run"; touch "\$outdir/\$run/\$run.sra"
EOF
cat > "$TMP/bin/fasterq-dump" <<EOF
#!/usr/bin/env bash
outdir=""
args=("\$@")
for ((i=0;i<\${#args[@]};i++)); do case "\${args[\$i]}" in -O) outdir="\${args[\$((i+1))]}";; esac; done
sra="\$(basename "\${args[-1]}")"; sra="\${sra%.sra}"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_1.fastq"
printf '@r\nACGT\n+\nIIII\n' > "\$outdir/\${sra}_2.fastq"
EOF
cat > "$TMP/bin/fastp" <<EOF
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ \$# -gt 0 ]]; do case "\$1" in -i) i1="\$2"; shift 2;; -I) i2="\$2"; shift 2;; -o) o1="\$2"; shift 2;; -O) o2="\$2"; shift 2;; *) shift;; esac; done
cp "\$i1" "\$o1"; cp "\$i2" "\$o2"
EOF
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>contig1\nACGTACGTACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/prefetch" "$TMP/bin/fasterq-dump" "$TMP/bin/fastp" "$TMP/bin/spades.py"

reconstruct() {
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        bash "$ROOT/scripts/08_operational_reconstruct.sh" "$@"
}

# a prediction and marker left by an earlier run; platon is NOT installed now
mkdir -p "$TMP/results/opS"
printf '>stale\nACGTACGTACGT\n' > "$TMP/results/opS/pred_platon.plasmid.fasta"
printf 'old fingerprint\n' > "$TMP/results/opS/.platon.complete"
rc=0
reconstruct --sample opS --sra SRR9 --tool platon > "$TMP/stage.log" 2>&1 || rc=$?
[[ "$rc" != "0" ]] || { echo "FAIL: a stale prediction of an uninstalled tool must not be accepted" >&2; tail -5 "$TMP/stage.log" >&2; exit 1; }
grep -q "did not run for opS in this run" "$TMP/stage.log" || { echo "FAIL: the message must say the tool did not run in this run" >&2; tail -5 "$TMP/stage.log" >&2; exit 1; }
[[ ! -e "$TMP/results/opS/selected_candidate/candidate.plasmid.fasta" ]] || { echo "FAIL: no candidate may be built from a stale prediction" >&2; exit 1; }
echo "a stale prediction of an uninstalled tool is refused -> PASS"

# the control: with the tool installed the run goes through
cat > "$TMP/bin/platon" <<EOF
#!/usr/bin/env bash
outdir="" prefix=""
while [[ \$# -gt 0 ]]; do case "\$1" in --output) outdir="\$2"; shift 2;; --prefix) prefix="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; printf '>c1\n%s\n' "\$(printf 'ACGT%.0s' \$(seq 1 500))" > "\$outdir/\$prefix.plasmid.fasta"
EOF
chmod +x "$TMP/bin/platon"
rm -rf "$TMP/results/opS"
reconstruct --sample opS --sra SRR9 --tool platon > "$TMP/stage.log" 2>&1 || { echo "FAIL: control run" >&2; tail -8 "$TMP/stage.log" >&2; exit 1; }
[[ -s "$TMP/results/opS/selected_candidate/candidate.plasmid.fasta" ]] || { echo "FAIL: control must produce a candidate" >&2; exit 1; }
echo "with the tool installed this run's prediction is used (control) -> PASS"
echo "ALL STAGE 8 FRESH PREDICTION TESTS PASSED"
