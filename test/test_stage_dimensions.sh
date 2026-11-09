#!/usr/bin/env bash
# Stages 5 and 6 produce, merge and report the further dimensions (accuracy, missing regions,
# feature preservation, NGOC, performance, power, scenarios, composite) from real stage scripts.
#
# Uses the real minimap2 when it is installed (so the CIGAR path is the pipeline's own); otherwise
# a stub that emits one PAF row with the same NM and cg tags minimap2 -c writes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$TMP" <<'PYEOF'
import os, random, sys
tmp = sys.argv[1]
rng = random.Random(7)
seq = lambda n: "".join(rng.choice("ACGT") for _ in range(n))
chrom, plasmid = seq(20000), seq(6000)
sdir, rdir = f"{tmp}/data/s1", f"{tmp}/results/s1"
os.makedirs(sdir); os.makedirs(rdir)
open(f"{sdir}/reference.fna", "w").write(f">chr\n{chrom}\n>p1\n{plasmid}\n")
open(f"{sdir}/truth.tsv", "w").write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t20000\np1\tPLASMID\t6000\n")
open(f"{sdir}/truth_proteins.tsv", "w").write(
    "sequence_id\tstart\tend\tstrand\tfeature_id\tgene\tproduct\tcategory\tsource\tversion\tconfidence\n"
    "p1\t300\t900\t+\tg1\trepA\trep\treplicon\tx\t1\tx\n"
    "p1\t2000\t2800\t+\tg2\tbla\tbeta-lactamase\tamr\tx\t1\tx\n"
    "p1\t4000\t4600\t+\tg3\ttraA\ttransfer\tmobility\tx\t1\tx\n")
# Prediction: the first 5000 bp of the plasmid with five point substitutions (identity just under 1).
pred = list(plasmid[:5000])
for position in (500, 1500, 2500, 3500, 4500):
    pred[position] = "A" if pred[position] != "A" else "C"
open(f"{rdir}/pred_mob_recon.plasmid.fasta", "w").write(">q1\n" + "".join(pred) + "\n")
open(f"{rdir}/.mob_recon.complete", "w").close()
os.makedirs(f"{tmp}/logs")
open(f"{tmp}/sheet.tsv", "w").write("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n")
open(f"{rdir}/../tool_status.tsv", "w").write(
    "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n"
    f"s1\tmob_recon\tcompleted\t{rdir}/pred_mob_recon.plasmid.fasta\t\t60\t1048576\n")
PYEOF

mkdir -p "$TMP/bin"
if ! command -v minimap2 >/dev/null 2>&1; then
    echo "  (no minimap2 on PATH: using a stub that writes the same NM and cg tags)"
    cat > "$TMP/bin/minimap2" <<'EOF'
#!/usr/bin/env bash
printf 'q1\t5000\t0\t5000\t+\tp1\t6000\t0\t5000\t4995\t5000\t60\tNM:i:5\tcg:Z:5000M\n'
EOF
    chmod +x "$TMP/bin/minimap2"
fi

ENVS=(DATA_DIR="$TMP/data" RESULTS_DIR="$TMP/results" LOG_DIR="$TMP/logs" TMP_DIR="$TMP/tmp"
      SAMPLE_SHEET="$TMP/sheet.tsv" REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0)
env PATH="$TMP/bin:$PATH" "${ENVS[@]}" bash "$ROOT/scripts/05_score.sh" > "$TMP/stage5.log" 2>&1 \
    || { echo "FAIL: stage 5" >&2; cat "$TMP/stage5.log" >&2; exit 1; }

R="$TMP/results/s1"
for shard in accuracy missing_regions feature_preservation ngoc; do
    [[ -s "$R/mob_recon.${shard}.tsv" ]] || { echo "FAIL: stage 5 wrote no ${shard} shard" >&2; cat "$TMP/stage5.log" >&2; exit 1; }
done
echo "stage 5 writes the accuracy, missing-region, feature-preservation and NGOC shards -> PASS"

python3 - "$R" <<'PYEOF'
import csv, sys
r = sys.argv[1]
acc = list(csv.DictReader(open(f"{r}/mob_recon.accuracy.tsv"), delimiter="\t"))[0]
assert 0.998 <= float(acc["identity"]) < 1.0, acc          # five substitutions in ~5000 columns
assert int(acc["mismatch_bp"]) == 5 and int(acc["inserted_bp"]) == 0, acc
reg = list(csv.DictReader(open(f"{r}/mob_recon.missing_regions.tsv"), delimiter="\t"))[0]
assert reg["missing_regions"] == "1" and reg["missing_bp"] == "1000", reg   # the 1000 bp tail was not predicted
feat = {x["feature_kind"]: x for x in csv.DictReader(open(f"{r}/mob_recon.feature_preservation.tsv"), delimiter="\t")}
assert feat["all"]["n_expected"] == "3" and feat["all"]["n_full_length"] == "3", feat   # all three genes lie in the first 5 kb
ngoc = list(csv.DictReader(open(f"{r}/mob_recon.ngoc.tsv"), delimiter="\t"))[0]
assert float(ngoc["ngoc"]) == 1.0, ngoc
print("the shards hold the right numbers (5 mismatches, a 1000 bp gap, 3 of 3 genes, NGOC 1) -> PASS")
PYEOF

env PATH="$TMP/bin:$PATH" "${ENVS[@]}" bash "$ROOT/scripts/06_aggregate.sh" > "$TMP/stage6.log" 2>&1 \
    || { echo "FAIL: stage 6" >&2; tail -30 "$TMP/stage6.log" >&2; exit 1; }
for table in accuracy missing_regions feature_preservation ngoc performance power scenarios scenario_performance \
             composite composite_sensitivity; do
    [[ -e "$TMP/results/benchmark.${table}.tsv" ]] || { echo "FAIL: stage 6 wrote no benchmark.${table}.tsv" >&2; tail -30 "$TMP/stage6.log" >&2; exit 1; }
done
echo "stage 6 merges the shards and writes every dimension table -> PASS"
HTML="$TMP/results/benchmark.report.html"
for section in accuracy-dimension feature-preservation bin-quality performance power scenarios composite reproducibility; do
    # Most of these are tabs of a merged container now: the old id is the panel id, so the old link still lands on it.
    grep -q "id='${section}'" "$HTML" || { echo "FAIL: report has no #${section} section" >&2; exit 1; }
done
grep -q "Sequence accuracy and missing regions" "$HTML" && ! sed -n "/id='accuracy-dimension'/,/<\/section>/p" "$HTML" | grep -q "No accuracy table was available" \
    || { echo "FAIL: the accuracy section is empty although its table exists" >&2; exit 1; }
echo "the report shows every new section, populated where its table exists -> PASS"
echo "ALL STAGE DIMENSION TESTS PASSED"
