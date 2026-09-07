#!/usr/bin/env bash
# Regression for scripts/02_truth.sh's new truth_source=self_assembled_hybrid
# branch: build_hybrid_truth.py is invoked instead of make_truth.py when no
# pre-existing reference/sequence_report exists, and the result (reference.fna
# + truth.tsv + truth_provenance.json) flows into the SAME downstream
# validate_truth_table.py/compute_assembly_stats.py steps unchanged -- their
# job is agnostic to how truth.tsv was produced. Also confirms a plain
# ncbi_deposited row (no truth_source, today's default) is completely
# unaffected by this branch.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/data/s1" "$TMP/data/s2" "$TMP/logs" "$TMP/results"

# --- s1: self_assembled_hybrid -- stage the long+short reads a real
# 01_download.sh run would have fetched (test_self_assembled_hybrid_download.sh
# covers that step itself); no reference.fna/sequence_report.jsonl at all. ---
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/long_reads.fastq.gz"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_SHORT_1.fastq.gz"
printf '@r\nACGT\n+\nIIII\n' | gzip > "$TMP/data/s1/SRR_SHORT_2.fastq.gz"

# --- s2: plain ncbi_deposited (today's default, no truth_source column
# value) -- a real reference + sequence report, exactly like every existing
# cohort row, to confirm this branch is completely unaffected. ---
printf '>CP000001.1\nACGTACGTACGT\n' > "$TMP/data/s2/reference.fna"
printf '{"genbank_accession":"CP000001.1","assigned_molecule_location_type":"Chromosome"}\n' > "$TMP/data/s2/sequence_report.jsonl"

# Fake unicycler: parses -1/-2/-l/-o, writes a circular chromosome + circular
# plasmid assembly.fasta into the requested output directory. build_hybrid_truth.py
# resolves it via shutil.which() (not a bare subprocess.run name -- that lookup
# is not PATHEXT-aware on native Windows), which correctly finds a .bat sibling
# for a bare "unicycler" on PATH there; plain `unicycler` covers a real POSIX
# host. A plain POSIX $TMP/bin:$PATH prepend below is enough for both --
# Windows's own automatic PATH conversion when spawning a native child handles
# the rest; do not "help" it with a manual cygpath conversion, which produces a
# mixed-separator PATH string that breaks the lookup instead of fixing it.
cat > "$TMP/bin/unicycler_fake.py" <<'EOF'
import os, sys
log = os.environ["UNICYCLER_CALLS_LOG"]
with open(log, "a") as f:
    f.write("unicycler " + " ".join(sys.argv[1:]) + "\n")
out = sys.argv[sys.argv.index("-o") + 1]
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "assembly.fasta"), "w") as f:
    f.write(">1 length=2000000 depth=1.00x circular=true\n")
    f.write("A" * 2000000 + "\n")
    f.write(">2 length=30000 depth=2.00x circular=true\n")
    f.write("C" * 30000 + "\n")
EOF
cat > "$TMP/bin/unicycler" <<'EOF'
#!/usr/bin/env bash
exec python3 "$(dirname "${BASH_SOURCE[0]}")/unicycler_fake.py" "$@"
EOF
cat > "$TMP/bin/unicycler.bat" <<'EOF'
@echo off
python3 "%~dp0unicycler_fake.py" %*
EOF
chmod +x "$TMP/bin/unicycler" "$TMP/bin/unicycler_fake.py"

run_stage() {
    PATH="$TMP/bin:$PATH" \
    DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp" \
    SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_REFERENCE_ANNOTATION=0 \
    HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH=1500000 \
    UNICYCLER_CALLS_LOG="$TMP/unicycler_calls.log" \
    "$@" bash "$ROOT/scripts/02_truth.sh" > "$TMP/stage.log" 2>&1
}

printf 'sample_id\tassembly_accession\tsra_run\ttruth_source\tlong_read_sra_run\ns1\tNA\tSRR_SHORT\tself_assembled_hybrid\tSRR_LONG\ns2\tGCF_1.1\tSRR_S2\t\t\n' > "$TMP/sheet.tsv"

: > "$TMP/unicycler_calls.log"
run_stage || { echo "FAIL: stage should succeed" >&2; cat "$TMP/stage.log" >&2; exit 1; }

[[ -s "$TMP/unicycler_calls.log" ]] || { echo "FAIL: expected unicycler to be invoked for s1" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q -- "-1 .*SRR_SHORT_1.fastq.gz" "$TMP/unicycler_calls.log" || { echo "FAIL: expected -1 short read arg" >&2; cat "$TMP/unicycler_calls.log" >&2; exit 1; }
grep -q -- "-l .*long_reads.fastq.gz" "$TMP/unicycler_calls.log" || { echo "FAIL: expected -l long read arg" >&2; cat "$TMP/unicycler_calls.log" >&2; exit 1; }
[[ -s "$TMP/data/s1/reference.fna" ]] || { echo "FAIL: expected s1 reference.fna to be built" >&2; exit 1; }
[[ -s "$TMP/data/s1/truth.tsv" ]] || { echo "FAIL: expected s1 truth.tsv to be built" >&2; exit 1; }
[[ -s "$TMP/data/s1/truth_provenance.json" ]] || { echo "FAIL: expected s1 truth_provenance.json to be written" >&2; exit 1; }
grep -q "^1	CHROMOSOME	2000000$" "$TMP/data/s1/truth.tsv" || { echo "FAIL: expected contig 1 labeled CHROMOSOME" >&2; cat "$TMP/data/s1/truth.tsv" >&2; exit 1; }
grep -q "^2	PLASMID	30000$" "$TMP/data/s1/truth.tsv" || { echo "FAIL: expected contig 2 labeled PLASMID" >&2; cat "$TMP/data/s1/truth.tsv" >&2; exit 1; }
grep -q '"method": "self_assembled_hybrid"' "$TMP/data/s1/truth_provenance.json" || { echo "FAIL: expected provenance to record the method" >&2; cat "$TMP/data/s1/truth_provenance.json" >&2; exit 1; }
echo "truth_source=self_assembled_hybrid builds reference.fna/truth.tsv/truth_provenance.json via build_hybrid_truth.py -> PASS"

[[ ! -e "$TMP/data/s1/sequence_report.jsonl" ]] || { echo "FAIL: no sequence_report.jsonl should exist for a self-built truth" >&2; exit 1; }
echo "no sequence_report.jsonl is fetched or required for a self-built truth sample -> PASS"

[[ -s "$TMP/data/s2/truth.tsv" ]] || { echo "FAIL: expected s2 (plain ncbi_deposited) truth.tsv to still be built normally" >&2; cat "$TMP/stage.log" >&2; exit 1; }
grep -q "^CP000001.1	CHROMOSOME	12$" "$TMP/data/s2/truth.tsv" || { echo "FAIL: s2's truth.tsv should come from make_truth.py unchanged" >&2; cat "$TMP/data/s2/truth.tsv" >&2; exit 1; }
[[ ! -e "$TMP/data/s2/truth_provenance.json" ]] || { echo "FAIL: a plain ncbi_deposited row should never get a truth_provenance.json" >&2; exit 1; }
echo "a plain ncbi_deposited row (no truth_source) is completely unaffected -> PASS"

echo "ALL BUILD HYBRID TRUTH STAGE TESTS PASSED"
