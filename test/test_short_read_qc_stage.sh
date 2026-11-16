#!/usr/bin/env bash
# The short-read QC gate inside stage 3 (and its effect on stage 4): a deliberately bad sample is rejected with a documented reason and
# does not reach the assembler or any tool; a warning-level sample proceeds, flagged; report-only mode never excludes on quality but
# still rejects an unreadable file; mode off changes nothing. Assembler and trimmer are stubs; the reads are real FASTQ.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/logs" "$TMP/results" "$TMP/tmp"
cat > "$TMP/bin/fastp" <<'EOF'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOF
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
echo "\$(basename "\$(dirname "\$outdir")")" >> "$TMP/spades_calls.log"
mkdir -p "\$outdir"; printf '>contig1\nACGTACGTACGT\n' > "\$outdir/contigs.fasta"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py"

# small-data copy of the shipped thresholds (the shipped read-count minimum is for real sequencing runs)
python3 - "$ROOT/config/short_read_qc_thresholds.tsv" "$TMP/thresholds.tsv" <<'PY'
import sys
out = []
for line in open(sys.argv[1]):
    f = line.rstrip("\n").split("\t")
    if line.startswith("#") or f[0] == "metric" or not line.strip():
        out.append(line.rstrip("\n")); continue
    if f[0] == "read_pairs": f[2], f[3] = "500", "100"
    if f[0] in ("estimated_depth_x", "median_read_length"): f[2], f[3] = "", ""
    out.append("\t".join(f))
open(sys.argv[2], "w").write("\n".join(out) + "\n")
PY

make_reads() {   # make_reads SAMPLE KIND
    python3 - "$TMP/data/$1" "$2" <<'PY'
import gzip, os, random, sys
folder, kind = sys.argv[1], sys.argv[2]
os.makedirs(folder, exist_ok=True)
rng = random.Random(3)
def write(path, mate, qual):
    with gzip.open(path, "wt") as h:
        for i in range(2000):
            s = "".join(rng.choice("ACGT") for _ in range(100))
            h.write(f"@r{i}/{mate}\n{s}\n+\n{qual * 100}\n")
q = {"good": "I", "lowq": "0", "mixed": None}[kind] if kind != "trunc" else "I"
for mate in (1, 2):
    path = f"{folder}/SRR_{mate}.fastq.gz"
    if kind == "mixed":
        with gzip.open(path, "wt") as h:
            for i in range(2000):
                s = "".join(rng.choice("ACGT") for _ in range(100))
                h.write(f"@r{i}/{mate}\n{s}\n+\n{('I' if i % 10 < 7 else '0') * 100}\n")
    else:
        write(path, mate, q)
if kind == "trunc":
    blob = open(f"{folder}/SRR_1.fastq.gz", "rb").read()
    open(f"{folder}/SRR_1.fastq.gz", "wb").write(blob[: len(blob) // 2])
PY
}
for pair in "good good" "lowq lowq" "mixed mixed" "trunc trunc"; do set -- $pair; make_reads "$1" "$2"; done
printf 'sample_id\tassembly_accession\tsra_run\ngood\tNA\tSRR\nlowq\tNA\tSRR\nmixed\tNA\tSRR\ntrunc\tNA\tSRR\n' > "$TMP/sheet.tsv"

run_stage() {   # run_stage SCRIPT [VAR=value ...]
    local script="$1"; shift
    env PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 SHORT_READ_QC_THRESHOLDS="$TMP/thresholds.tsv" "$@" \
        bash "$ROOT/scripts/$script" > "$TMP/stage.log" 2>&1
}
status_of() { awk -F'\t' -v s="$1" '$1 == s {print $2}' "$TMP/results/assembly_status.tsv"; }
qc_of() { awk -F'\t' -v s="$1" '$1 == s {print $2}' "$TMP/results/short_read_qc_status.tsv"; }
fail() { echo "FAIL: $1" >&2; cat "$TMP/stage.log" >&2; exit 1; }

# --- enforce ---
: > "$TMP/spades_calls.log"
run_stage 03_assemble.sh SHORT_READ_QC_MODE=enforce || fail "stage 3 (enforce) should finish when at least one sample assembles"
[[ "$(qc_of good)" == "PASS" ]] || fail "good reads should PASS (got '$(qc_of good)')"
[[ "$(qc_of mixed)" == "WARN" ]] || fail "mixed-quality reads should WARN (got '$(qc_of mixed)')"
[[ "$(qc_of lowq)" == "REJECT" ]] || fail "low-quality reads should REJECT (got '$(qc_of lowq)')"
[[ "$(qc_of trunc)" == "REJECT" ]] || fail "a truncated file should REJECT (got '$(qc_of trunc)')"
[[ "$(status_of good)" == "completed" && "$(status_of mixed)" == "completed" ]] || fail "PASS and WARN samples should assemble"
[[ "$(status_of lowq)" == "rejected" && "$(status_of trunc)" == "rejected" ]] || fail "rejected samples should be recorded as rejected, not failed"
grep -q "mean_quality" "$TMP/results/assembly_status.tsv" || fail "the rejection reason (the metric) should be in assembly_status.tsv"
grep -q "integrity: truncated" "$TMP/results/assembly_status.tsv" || fail "the integrity reason should be in assembly_status.tsv"
! grep -qx "lowq" "$TMP/spades_calls.log" && ! grep -qx "trunc" "$TMP/spades_calls.log" || fail "a rejected sample must not reach the assembler"
grep -qx "good" "$TMP/spades_calls.log" && grep -qx "mixed" "$TMP/spades_calls.log" || fail "PASS and WARN samples must reach the assembler"
[[ -f "$TMP/data/lowq/.qc_rejected" && ! -f "$TMP/data/good/.qc_rejected" ]] || fail "only the rejected sample gets the .qc_rejected marker"
grep -q "excluded from the primary benchmark" "$TMP/results/short_read_qc_status.tsv" || fail "the QC status table should say the REJECT was excluded"
grep -q "proceeded (flagged)" "$TMP/results/short_read_qc_status.tsv" || fail "the WARN sample should be marked as proceeded (flagged)"
[[ "$(awk 'END {print NR - 1}' "$TMP/results/short_read_qc.tsv")" == "4" ]] || fail "short_read_qc.tsv should have one row per sample"
echo "enforce: PASS and WARN assemble; a quality REJECT and a truncated file are excluded with their reasons, never reaching the assembler -> PASS"

# --- stage 4 skips the rejected sample with its own reason ---
run_stage 04_run_tools.sh RUN_MOB_RECON=1 RUN_PLATON=0 RUN_PLASMIDSPADES=0 || true
if [[ -s "$TMP/results/tool_status.tsv" ]]; then
    awk -F'\t' '$1 == "lowq" && $3 == "skipped"' "$TMP/results/tool_status.tsv" | grep -q "short-read QC rejected" \
        || fail "stage 4 should skip the rejected sample with the reason 'short-read QC rejected'"
    echo "stage 4: the rejected sample's tools are skipped as 'short-read QC rejected', not failed -> PASS"
else
    echo "stage 4: not exercised here (no tool_status.tsv written without the tool binaries)"
fi

# --- report-only: a quality REJECT proceeds flagged, an integrity failure is still excluded ---
rm -rf "$TMP/results" "$TMP/data"/*/contigs.fasta "$TMP/data"/*/.fastp.complete "$TMP/data"/*/.qc_rejected; mkdir -p "$TMP/results"
: > "$TMP/spades_calls.log"
run_stage 03_assemble.sh SHORT_READ_QC_MODE=report || fail "stage 3 (report) should finish"
[[ "$(status_of lowq)" == "completed" ]] || fail "report mode: a low-quality sample proceeds (got '$(status_of lowq)')"
[[ "$(qc_of lowq)" == "REJECT" ]] || fail "report mode still records the REJECT"
[[ "$(status_of trunc)" == "rejected" ]] || fail "report mode: an unreadable file is still excluded (got '$(status_of trunc)')"
grep -q "proceeded (flagged)" "$TMP/results/short_read_qc_status.tsv" || fail "report mode: the REJECT should read 'proceeded (flagged)'"
echo "report: a quality REJECT proceeds, flagged; a truncated file is still excluded -> PASS"

# --- off: no gate, no tables ---
rm -rf "$TMP/results" "$TMP/data"/*/contigs.fasta "$TMP/data"/*/.fastp.complete "$TMP/data"/*/.qc_rejected; mkdir -p "$TMP/results"
run_stage 03_assemble.sh SHORT_READ_QC_MODE=off || true
[[ ! -e "$TMP/results/short_read_qc.tsv" ]] || fail "mode off must not write QC tables"
echo "off: no QC tables, behaviour as before -> PASS"
echo "ALL SHORT-READ QC STAGE TESTS PASSED"
