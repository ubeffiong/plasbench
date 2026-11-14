#!/usr/bin/env bash
# Stage 3 is crash-safe: a run cut off mid-trim or mid-assembly (a full disk, WSL or the machine stopping) never
# leaves files that a re-run mistakes for finished work, and finished work is still reused.
#   - fastp writes *.partial.fastq.gz and renames them only on success; .fastp.complete marks a finished pair
#   - trimmed reads without the marker and without an assembly (cut off by an earlier PlasBench) are trimmed again
#   - an interrupted assembly folder is cleared before reassembling; contigs are copied to a .partial name first
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $*" >&2; echo "--- stage log:" >&2; cat "$TMP/stage.log" >&2 2>/dev/null || true; exit 1; }

mkdir -p "$TMP/bin" "$TMP/logs" "$TMP/results" "$TMP/tmp" "$TMP/data/s1"
# fastp stub: writes a complete pair ("@full"), or with KILL_FASTP=1 a partial one and dies like a killed process
cat > "$TMP/bin/fastp" <<EOF
#!/usr/bin/env bash
o1="" o2=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) o1="\$2"; shift 2;; -O) o2="\$2"; shift 2;; *) shift;; esac; done
echo call >> "$TMP/fastp_calls.log"
if [[ "\${KILL_FASTP:-0}" == "1" ]]; then printf '@half' > "\$o1"; exit 137; fi
printf '@full\nACGT\n+\nIIII\n' | gzip > "\$o1"; printf '@full\nACGT\n+\nIIII\n' | gzip > "\$o2"
EOF
# spades stub: refuses a folder holding junk from an interrupted run (as a real resumed half-run would misbehave)
cat > "$TMP/bin/spades.py" <<EOF
#!/usr/bin/env bash
outdir=""
while [[ \$# -gt 0 ]]; do case "\$1" in -o) outdir="\$2"; shift 2;; *) shift;; esac; done
echo call >> "$TMP/spades_calls.log"
[[ -e "\$outdir/JUNK_FROM_A_CRASH" ]] && { echo "stale output folder" >&2; exit 1; }
mkdir -p "\$outdir"; printf '>contig1\nACGTACGTACGT\n' > "\$outdir/contigs.fasta"; printf 'S\t1\tACGT\n' > "\$outdir/assembly_graph_with_scaffolds.gfa"
EOF
chmod +x "$TMP/bin/fastp" "$TMP/bin/spades.py"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_1.fastq.gz"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_2.fastq.gz"
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n' > "$TMP/sheet.tsv"
S="$TMP/data/s1"
run_stage() {
    : > "$TMP/fastp_calls.log"; : > "$TMP/spades_calls.log"
    PATH="$TMP/bin:$PATH" DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
        SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 MAX_PARALLEL_SAMPLES=1 \
        "$@" bash "$ROOT/scripts/03_assemble.sh" > "$TMP/stage.log" 2>&1
}
calls() { wc -l < "$TMP/$1_calls.log" | tr -d ' '; }
full() { gzip -dc "$1" 2>/dev/null | head -1 | grep -q '^@full'; }
reset() { rm -rf "$S"/*.trim*.fastq.gz "$S/.fastp.complete" "$S/contigs.fasta"* "$S/assembly_graph.gfa"* "$S/assembly"; }

# 1. fastp killed mid-trim: nothing is left that looks finished
run_stage env KILL_FASTP=1 || true      # the only sample failing aborts the stage; that is expected here
[[ ! -e "$S/SRR_1.trim.fastq.gz" && ! -e "$S/SRR_2.trim.fastq.gz" ]] || fail "a killed fastp left trimmed reads behind"
compgen -G "$S/*.partial.fastq.gz" > /dev/null && fail "a killed fastp left .partial files behind"
[[ ! -e "$S/.fastp.complete" ]] || fail "a killed fastp was marked complete"
echo "fastp killed mid-trim leaves nothing a re-run could mistake for finished reads -> PASS"

# 2. truncated trims from an earlier PlasBench (no marker, no assembly) are trimmed again, then assembled
reset
printf '@half' > "$S/SRR_1.trim.fastq.gz"; printf '@half' > "$S/SRR_2.trim.fastq.gz"
printf 'junk' > "$S/SRR_1.trim.partial.fastq.gz"
mkdir -p "$S/assembly"; : > "$S/assembly/JUNK_FROM_A_CRASH"
run_stage || fail "stage 3 should succeed after an interrupted earlier run"
[[ "$(calls fastp)" == 1 ]] || fail "unfinished trims should be trimmed again (fastp calls: $(calls fastp))"
grep -q "unfinished run found: trimming again" "$TMP/stage.log" || fail "the re-trim should be explained in the log"
full "$S/SRR_1.trim.fastq.gz" && full "$S/SRR_2.trim.fastq.gz" || fail "the trimmed reads should be the complete pair"
[[ -f "$S/.fastp.complete" ]] || fail "a finished trim should be marked complete"
[[ ! -e "$S/SRR_1.trim.partial.fastq.gz" ]] || fail "leftover .partial files should be removed"
[[ -s "$S/contigs.fasta" && -s "$S/assembly_graph.gfa" ]] || fail "the sample should assemble from a cleared folder"
[[ ! -e "$S/contigs.fasta.partial" && ! -e "$S/assembly/JUNK_FROM_A_CRASH" ]] || fail "half-written assembly files should be gone"
echo "trims and an assembly folder cut off by an earlier run are redone, not reused -> PASS"

# 3. finished work is reused: marked trims and an assembly are skipped
run_stage || fail "a re-run of a finished sample should succeed"
[[ "$(calls fastp)" == 0 && "$(calls spades)" == 0 ]] || fail "finished trims/assembly should be reused (fastp $(calls fastp), spades $(calls spades))"
echo "finished trims and assembly are reused -> PASS"

# 4. data from an earlier PlasBench with an assembly (no marker) is still reused
rm -f "$S/.fastp.complete"
run_stage || fail "legacy finished data should be reused"
[[ "$(calls fastp)" == 0 && "$(calls spades)" == 0 ]] || fail "an assembled sample from an earlier PlasBench should not be redone"
echo "an assembled sample from an earlier PlasBench is reused (no marker needed) -> PASS"

# 5. a contigs copy cut off midway is not taken for an assembly
reset
printf '@full\nACGT\n+\nIIII\n' | gzip > "$S/SRR_1.trim.fastq.gz"; printf '@full\nACGT\n+\nIIII\n' | gzip > "$S/SRR_2.trim.fastq.gz"; : > "$S/.fastp.complete"
printf '>contig1\nAC' > "$S/contigs.fasta.partial"
run_stage || fail "stage 3 should reassemble after an interrupted copy"
[[ "$(calls spades)" == 1 ]] || fail "an interrupted contigs copy must not count as an assembly"
[[ ! -e "$S/contigs.fasta.partial" ]] && grep -q ACGTACGTACGT "$S/contigs.fasta" || fail "the contigs should be the finished copy"
echo "an interrupted contigs copy is redone -> PASS"

echo "ALL STAGE-3 CRASH-SAFETY TESTS PASSED"
