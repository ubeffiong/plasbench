#!/usr/bin/env bash
# Assembly selection inside stage 3 with stub assemblers: a poor primary (SPAdes: 3 contigs of 20 kb) and a better alternative
# (Unicycler: one contig of 60 kb). Report mode records the policy's choice and changes nothing; enforce makes the choice the assembly
# the tools run on; fixed keeps the configured assembler; an assembly nothing qualifies for is excluded, never silently replaced.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/logs" "$TMP/results" "$TMP/tmp" "$TMP/data/s1"
cat > "$TMP/bin/fastp" <<'EOF'
#!/usr/bin/env bash
i1="" i2="" o1="" o2=""
while [[ $# -gt 0 ]]; do case "$1" in -i) i1="$2"; shift 2;; -I) i2="$2"; shift 2;; -o) o1="$2"; shift 2;; -O) o2="$2"; shift 2;; *) shift;; esac; done
cp "$i1" "$o1"; cp "$i2" "$o2"
EOF
make_fasta() { python3 -c "
import random, sys
rng = random.Random(5)
for i, n in enumerate(int(x) for x in sys.argv[1:]):
    print('>c%d' % i); print(''.join(rng.choice('ACGT') for _ in range(n)))
" "$@"; }
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
outdir=""; while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; python3 -c "
import random
rng = random.Random(5)
for i in range(3):
    print('>c%d' % i); print(''.join(rng.choice('ACGT') for _ in range(20000)))" > "\$outdir/contigs.fasta"
EOF
cat > "$TMP/bin/unicycler" <<EOF
#!/usr/bin/env bash
outdir=""; while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
mkdir -p "\$outdir"; python3 -c "
import random
rng = random.Random(6)
print('>chromosome'); print(''.join(rng.choice('ACGT') for _ in range(60000)))" > "\$outdir/assembly.fasta"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py" "$TMP/bin/unicycler"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_1.fastq.gz"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_2.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"

run_stage() {   # run_stage [VAR=value ...]
    rm -rf "$TMP/results" "$TMP/data/s1/contigs.fasta" "$TMP/data/s1/assemblies" "$TMP/data/s1/assembly" "$TMP/data/s1/.fastp.complete" \
           "$TMP/data/s1/.assembly_ineligible" "$TMP/data/s1/.assembly_selected" "$TMP/data/s1/assembly_graph.gfa"
    mkdir -p "$TMP/results"
    env PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 SHORT_READ_QC_MODE=off ASSEMBLER=spades ASSEMBLY_ALSO=unicycler \
        ASSEMBLY_READ_SUPPORT=0 ASSEMBLY_MIN_TOTAL_MB=0.01 ASSEMBLY_MAX_TOTAL_MB=1 "$@" \
        bash "$ROOT/scripts/03_assemble.sh" > "$TMP/stage.log" 2>&1
}
fail() { echo "FAIL: $1" >&2; cat "$TMP/stage.log" >&2; exit 1; }
contigs_n() { grep -c '>' "$TMP/data/s1/contigs.fasta"; }
status_line() { awk -F'\t' '$1 == "s1"' "$TMP/results/assembly_status.tsv"; }
sel() { awk -F'\t' '$1 == "s1" && $15 == "yes" {print $2}' "$TMP/results/assembly_candidates.tsv"; }

# report + quality: the table says unicycler would be chosen; the primary is still what the tools run on
run_stage ASSEMBLY_SELECTION_MODE=report ASSEMBLY_SELECTION_POLICY=quality || fail "stage 3 (report, quality) should finish"
[[ "$(awk 'END {print NR - 1}' "$TMP/results/assembly_candidates.tsv")" == "2" ]] || fail "both candidates should be in assembly_candidates.tsv"
[[ "$(sel)" == "unicycler" ]] || fail "quality should select the higher-N50 unicycler (got '$(sel)')"
[[ "$(contigs_n)" == "3" ]] || fail "report mode must not change the assembly the tools use (3 SPAdes contigs expected)"
[[ -s "$TMP/data/s1/assemblies/spades/contigs.fasta" && -s "$TMP/data/s1/assemblies/unicycler/contigs.fasta" ]] || fail "every candidate assembly is retained"
echo "report/quality: both candidates measured and kept, unicycler recorded as the choice, the primary still used -> PASS"

# enforce + quality: the chosen assembly replaces the primary
run_stage ASSEMBLY_SELECTION_MODE=enforce ASSEMBLY_SELECTION_POLICY=quality || fail "stage 3 (enforce, quality) should finish"
[[ "$(contigs_n)" == "1" ]] || fail "enforce: the unicycler assembly (1 contig) should be what the tools run on (got $(contigs_n))"
grep -q "assembly selected: unicycler (quality)" "$TMP/results/assembly_status.tsv" || fail "the status should record the selected assembler and policy"
[[ -s "$TMP/data/s1/assemblies/spades/contigs.fasta" ]] || fail "the primary assembly must be retained for a sensitivity analysis"
echo "enforce/quality: the better assembly becomes the input, the alternative is retained, the choice is in the status -> PASS"

# enforce + fixed: the configured assembler stays even though another has a better N50
run_stage ASSEMBLY_SELECTION_MODE=enforce ASSEMBLY_SELECTION_POLICY=fixed || fail "stage 3 (enforce, fixed) should finish"
[[ "$(contigs_n)" == "3" && "$(sel)" == "spades" ]] || fail "fixed keeps the configured SPAdes assembly (got '$(sel)', $(contigs_n) contigs)"
echo "enforce/fixed: the configured assembler is kept regardless of a better alternative -> PASS"

# enforce, nothing eligible: excluded, never substituted
run_stage ASSEMBLY_SELECTION_MODE=enforce ASSEMBLY_SELECTION_POLICY=quality ASSEMBLY_MIN_TOTAL_MB=5 ASSEMBLY_ALSO= || true
status_line | grep -q "rejected" || fail "a sample with no eligible assembly should be recorded as rejected: $(status_line)"
status_line | grep -q "assembly selection: quality: no candidate is eligible" || fail "the reason should be recorded: $(status_line)"
[[ -f "$TMP/data/s1/.assembly_ineligible" ]] || fail "the .assembly_ineligible marker should make stage 4 skip the sample"
echo "enforce, none eligible: the sample is excluded with the reason, nothing substituted -> PASS"

# off: no selection files
run_stage ASSEMBLY_SELECTION_MODE=off || fail "stage 3 (off) should finish"
[[ ! -e "$TMP/results/assembly_candidates.tsv" && ! -d "$TMP/data/s1/assemblies" ]] || fail "off writes no selection files"
echo "off: behaviour as before -> PASS"
echo "ALL ASSEMBLY SELECTION STAGE TESTS PASSED"
