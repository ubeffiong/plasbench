#!/usr/bin/env bash
# Stage 5 labels assembly contigs against truth and scores each tool on them; stage 6 carries the
# contig-level, ARI, assembly-aware and micro-average columns into the leaderboard and the report.
# Uses the real minimap2 when installed; otherwise stubs it (contig labelling and the scorer's PAF
# both come from minimap2, so the stub answers each by its query).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$TMP" <<'PYEOF'
import os, random, sys
tmp = sys.argv[1]
rng = random.Random(11)
seq = lambda n: "".join(rng.choice("ACGT") for _ in range(n))
chrom, plasmid = seq(30000), seq(6000)
sdir, rdir = f"{tmp}/data/s1", f"{tmp}/results/s1"
os.makedirs(sdir); os.makedirs(rdir)
open(f"{sdir}/reference.fna", "w").write(f">chr\n{chrom}\n>p1\n{plasmid}\n")
open(f"{sdir}/truth.tsv", "w").write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t30000\np1\tPLASMID\t6000\n")
# Assembly contigs: a plasmid contig covering the first 5000 bp of the plasmid (with 3 substitutions),
# two chromosome contigs, and a contig too short to be labelled.
plasmid_contig = list(plasmid[:5000])
for position in (700, 2100, 4300):
    plasmid_contig[position] = "A" if plasmid_contig[position] != "A" else "C"
plasmid_contig = "".join(plasmid_contig)
contigs = {"contig_p": plasmid_contig, "contig_c1": chrom[:9000], "contig_c2": chrom[12000:15000], "contig_tiny": chrom[20000:20400]}
open(f"{sdir}/contigs.fasta", "w").write("".join(f">{k}\n{v}\n" for k, v in contigs.items()))
# The tool calls the plasmid contig only, as one bin.
open(f"{rdir}/pred_mob_recon.plasmid.fasta", "w").write(f">contig_p\n{plasmid_contig}\n")
open(f"{rdir}/pred_mob_recon.bins.tsv", "w").write("bin_id\tsequence_id\nB1\tcontig_p\n")
open(f"{rdir}/.mob_recon.complete", "w").close()
os.makedirs(f"{tmp}/logs")
open(f"{tmp}/sheet.tsv", "w").write("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n")
open(f"{tmp}/results/tool_status.tsv", "w").write(
    "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n"
    f"s1\tmob_recon\tcompleted\t{rdir}/pred_mob_recon.plasmid.fasta\t\t60\t1048576\n")
PYEOF

mkdir -p "$TMP/bin"
if ! command -v minimap2 >/dev/null 2>&1; then
    echo "  (no minimap2 on PATH: using a stub)"
    cat > "$TMP/bin/minimap2" <<'EOF'
#!/usr/bin/env bash
# Last two arguments are REF and QUERY. Answer by the query's record names.
q="${@: -1}"
if grep -q '^>contig_c1' "$q"; then
    printf 'contig_p\t5000\t0\t5000\t+\tp1\t6000\t0\t5000\t4997\t5000\t60\tNM:i:3\tcg:Z:5000M\n'
    printf 'contig_c1\t9000\t0\t9000\t+\tchr\t30000\t0\t9000\t9000\t9000\t60\tNM:i:0\tcg:Z:9000M\n'
    printf 'contig_c2\t3000\t0\t3000\t+\tchr\t30000\t12000\t15000\t3000\t3000\t60\tNM:i:0\tcg:Z:3000M\n'
else
    printf 'contig_p\t5000\t0\t5000\t+\tp1\t6000\t0\t5000\t4997\t5000\t60\tNM:i:3\tcg:Z:5000M\n'
fi
EOF
    chmod +x "$TMP/bin/minimap2"
fi

ENVS=(DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp"
      SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0)
env PATH="$TMP/bin:$PATH" "${ENVS[@]}" bash "$ROOT/scripts/05_score.sh" > "$TMP/stage5.log" 2>&1 \
    || { echo "FAIL: stage 5" >&2; cat "$TMP/stage5.log" >&2; exit 1; }

python3 - "$TMP" <<'PYEOF'
import csv, sys
tmp = sys.argv[1]
read = lambda p: list(csv.DictReader(open(p, newline=""), delimiter="\t"))
labels = {r["contig"]: r["label"] for r in read(f"{tmp}/data/s1/contig_labels.tsv")}
assert labels == {"contig_p": "PLASMID", "contig_c1": "CHROMOSOME", "contig_c2": "CHROMOSOME", "contig_tiny": "SHORT"}, labels
cov = read(f"{tmp}/data/s1/plasmid_assembly_coverage.tsv")[0]
assert cov["assembly_covered_bp"] == "5000", cov
print("stage 5 labels the contigs and measures how much of the plasmid the assembly covers -> PASS")
row = read(f"{tmp}/results/scores.tsv")[0]
assert (row["contig_tp"], row["contig_fp"], row["contig_fn"], row["contig_tn"]) == ("1", "0", "0", "2"), row
assert row["contig_f1_count"] == "1.0000" and row["contig_mcc_count"] == "1.0000", row
assert row["contig_f1_bp"] == "1.0000" and row["contigs_short"] == "1", row
print("the tool's contig-level counts and F1/MCC reach scores.tsv (TP 1, TN 2, F1 1, MCC 1) -> PASS")
# Binning: the bin covers 5000 of the plasmid's 6000 bp; against what the assembly covers it recovers all of it.
assert abs(float(row["lw_bin_recall"]) - 5000 / 6000) < 1e-3, row["lw_bin_recall"]
assert row["lw_bin_recall_assembly_aware"] == "1.0000", row["lw_bin_recall_assembly_aware"]
assert row["bin_ari"] != "", row
print("binning recall is 0.833 of the plasmid but 1.0 of what the assembly covers; ARI is reported -> PASS")
PYEOF

env PATH="$TMP/bin:$PATH" "${ENVS[@]}" bash "$ROOT/scripts/06_aggregate.sh" > "$TMP/stage6.log" 2>&1 \
    || { echo "FAIL: stage 6" >&2; tail -30 "$TMP/stage6.log" >&2; exit 1; }
python3 - "$TMP" <<'PYEOF'
import csv, sys
tmp = sys.argv[1]
board = list(csv.DictReader(open(f"{tmp}/results/benchmark.leaderboard.tsv", newline=""), delimiter="\t"))[0]
for column in ("micro_f1", "mean_contig_f1_count", "mean_contig_mcc_bp", "mean_bin_ari", "mean_lw_bin_f1_assembly_aware"):
    assert board[column] != "", (column, board)
assert board["mean_contig_f1_count"] == "1.0000" and board["mean_lw_bin_f1_assembly_aware"] != "", board
html = open(f"{tmp}/results/benchmark.report.html", encoding="utf-8").read()
assert "id='metric-framework'" in html and "href='#metric-framework'" in html
assert "PLASMID 1" in html and "CHROMOSOME 2" in html and "SHORT 1" in html, "report must show the contig label counts"
assert "id='database-membership'" in html
print("stage 6 puts the contig, ARI, assembly-aware and micro columns in the leaderboard and the report -> PASS")
PYEOF
echo "ALL STAGE CONTIG METRIC TESTS PASSED"
