#!/usr/bin/env bash
# Real run smoke (needs the real tools installed by `plasbench install-tools core assembly utilities mobsuite reconstruction`, and the internet; run by
# .github/workflows/tool-install-proof.yml, never by the ordinary tests).
#
# One isolate is built from a real plasmid (pBR322, NCBI J01749.1): error-free paired reads are simulated from it, the REAL fastp trims them and the REAL SPAdes
# assembles them (stage 3), then the real tools run on that assembly (stage 4: mob_recon, plasmidSPAdes, the coverage baseline), stage 5 scores them against the
# plasmid with the real minimap2, and stage 6 aggregates. Each enabled tool must have a row in tool_status.tsv and, for the tools that completed, a row in scores.tsv.
# Nothing here is a biological result; it proves that the installed tools start, run through PlasBench's own stages and produce files PlasBench can score.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
WORK="${SMOKE_WORK:-$ROOT/smoke_work}"
ENV_PREFIX="${PLASBENCH_ENV_PREFIX:-$HOME/miniforge3/envs/plasbench}"
export PATH="$ENV_PREFIX/bin:$PATH"
rm -rf "$WORK"; mkdir -p "$WORK/data/s1" "$WORK/config" "$WORK/logs" "$WORK/results"

fail() { echo "SMOKE FAIL: $*" >&2; for f in "$WORK"/*.log; do echo "--- $f" >&2; tail -30 "$f" >&2; done; [[ -f "$WORK/results/tool_status.tsv" ]] && cat "$WORK/results/tool_status.tsv" >&2; exit 1; }
for tool in fastp spades.py minimap2 samtools mash mob_recon; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not installed (plasbench install-tools core assembly utilities mobsuite reconstruction)"
done
echo "tools on PATH: fastp $(fastp --version 2>&1 | head -1), $(spades.py --version 2>&1 | head -1), minimap2 $(minimap2 --version), $(samtools --version | head -1), mash $(mash --version), $(mob_recon --version 2>&1 | head -1)"

curl -fsS "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id=J01749.1&rettype=fasta&retmode=text" -o "$WORK/pbr322.fasta"
head -c 1 "$WORK/pbr322.fasta" | grep -q '>' || fail "the fetched pBR322 record is not FASTA"
python3 - "$WORK" <<'EOF'
import gzip, random, sys
work = sys.argv[1]
lines = open(work + "/pbr322.fasta").read().splitlines()
seq = "".join(l.strip() for l in lines[1:]).upper()
random.seed(11)
comp = str.maketrans("ACGT", "TGCA")
rc = lambda s: s.translate(comp)[::-1]
open(work + "/data/s1/reference.fna", "w").write(">pBR322\n" + seq + "\n")
open(work + "/data/s1/truth.tsv", "w").write(f"sequence_id\tmolecule_type\tlength\npBR322\tPLASMID\t{len(seq)}\n")
circ = seq + seq[:200]
with gzip.open(work + "/data/s1/SRR1_1.fastq.gz", "wt") as r1, gzip.open(work + "/data/s1/SRR1_2.fastq.gz", "wt") as r2:
    for i in range(12000):
        start = random.randrange(len(seq))
        frag = circ[start:start + 300]
        a, b = frag[:100], rc(frag)[:100]
        q = "".join(random.choice("5?ABCDEFGHI") for _ in range(100))   # varied qualities: SPAdes cannot tell the Phred offset from a flat string
        qb = "".join(random.choice("5?ABCDEFGHI") for _ in range(100))
        r1.write(f"@r{i}/1\n{a}\n+\n{q}\n")
        r2.write(f"@r{i}/2\n{b}\n+\n{qb}\n")
print("plasmid", len(seq), "bp")
EOF
printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$WORK/config/accessions.tsv"

stage() {
    local script="$1"; shift
    env DATA_DIR="$WORK/data" RESULTS_DIR="$WORK/results" LOG_DIR="$WORK/logs" TMP_DIR="$WORK/tmp" SAMPLE_SHEET="$WORK/config/accessions.tsv" \
        REQUIRE_CURATED_METADATA=0 RUN_PROTEIN_ANNOTATION=0 SHORT_READ_QC_MODE=report ASSEMBLER=spades RUN_PLATON=0 RUN_PLASMIDSPADES=1 RUN_MOB_RECON=1 \
        RUN_BASELINE_COVERAGE=1 RUN_BASELINE_REFERENCE=0 RUN_BASELINE_REPLICON=0 RUN_PLSMD=0 TOOL_RETRIES=0 "$@" \
        bash "$ROOT/scripts/$script" > "$WORK/$script.log" 2>&1 || fail "stage $script exited non-zero"
}

# The MOB-suite reference database (mob_recon will not run without it): the project's own installer, the same one `plasbench check --yes` calls.
bash "$ROOT/env/download_mobsuite_db.sh" --yes > "$WORK/mob_db.log" 2>&1 || fail "the MOB-suite database could not be installed (env/download_mobsuite_db.sh)"

stage 03_assemble.sh
[[ -s "$WORK/data/s1/contigs.fasta" ]] || fail "stage 3 (real fastp + SPAdes) wrote no contigs.fasta"
[[ -s "$WORK/data/s1/SRR1_1.trim.fastq.gz" ]] || fail "stage 3 (real fastp) wrote no trimmed reads"
echo "stage 3: real fastp trimmed the reads and real SPAdes assembled $(grep -c '^>' "$WORK/data/s1/contigs.fasta") contig(s) -> PASS"

stage 04_run_tools.sh
STATUS="$WORK/results/tool_status.tsv"
[[ -s "$STATUS" ]] || fail "stage 4 wrote no tool_status.tsv"
for tool in mob_recon plasmidspades baseline_coverage; do
    row="$(awk -F'\t' -v t="$tool" '$2==t' "$STATUS" | head -1)"
    [[ -n "$row" ]] || fail "stage 4 produced no status row for the enabled tool $tool"
    echo "  $tool: $(echo "$row" | cut -f3,5)"
done
for tool in mob_recon plasmidspades baseline_coverage; do
    [[ "$(awk -F'\t' -v t="$tool" '$2==t {print $3}' "$STATUS" | head -1)" == "completed" ]] || fail "$tool did not complete (the row above says why)"
done
echo "stage 4: every enabled installed tool produced a status row and completed -> PASS"

stage 05_score.sh
[[ -s "$WORK/results/scores.tsv" ]] || fail "stage 5 wrote no scores.tsv"
for tool in mob_recon plasmidspades baseline_coverage; do
    awk -F'\t' -v t="$tool" '$2==t' "$WORK/results/scores.tsv" | grep -q . || fail "scores.tsv has no row for $tool"
done
echo "stage 5: scored with the real minimap2 -> PASS"
stage 06_aggregate.sh
ls "$WORK"/results/*leaderboard* >/dev/null 2>&1 || fail "stage 6 wrote no leaderboard"
echo "stage 6: leaderboard written -> PASS"
echo "REAL RUN SMOKE PASSED"
