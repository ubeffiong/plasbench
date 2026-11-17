#!/usr/bin/env bash
set -u
ROOT=~/pb_main
mk() {  # two samples s1, s2
  local T="$1"; rm -rf "$T"; mkdir -p "$T/bin" "$T/config"
  for s in s1 s2; do mkdir -p "$T/data/$s"
    printf '>contig1\nACGTACGTACGT\n' > "$T/data/$s/contigs.fasta"
    printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/$s/SRR${s#s}_1.trim.fastq.gz"
    printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/$s/SRR${s#s}_2.trim.fastq.gz"; done
  printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\ns2\tNA\tSRR2\n' > "$T/config/accessions.tsv"
}
envs() { export DATA_DIR="$1/data" RESULTS_DIR="$1/results" LOG_DIR="$1/logs" SAMPLE_SHEET="$1/config/accessions.tsv" REQUIRE_CURATED_METADATA=0 ONLY_TOOL=mob_recon; }

echo "=== FI-C2: SIGINT (foreground, to the stage only) while a tool runs"
T=$(mktemp -d); mk "$T"; envs "$T"
printf '#!/usr/bin/env bash\nsleep 311\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
PATH="$T/bin:$PATH" timeout --foreground -s INT 8 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo "stage exit=$? (130 = died on SIGINT)"
sleep 2
echo "orphaned 'sleep 311' processes after the stage died:"; pgrep -af "sleep 311" | head -3; echo "(none above = no orphan)"
echo "tool_status after interrupt:"; cat "$T/results/tool_status.tsv" 2>/dev/null | cut -f1-5 || echo "(no status file)"
ls -a "$T/results" 2>/dev/null | head; tail -3 "$T/stage.log"
pkill -f "sleep 311" 2>/dev/null

echo; echo "=== FI-D2: one sample's job dies (results/s2 is a regular file so mkdir fails for s2 only)"
T=$(mktemp -d); mk "$T"; envs "$T"
mkdir -p "$T/results"; : > "$T/results/s2"
printf '#!/usr/bin/env bash\nmkdir -p "$2" 2>/dev/null; printf ">p\\nACGT\\n" > "$2/plasmid_1.fasta" 2>/dev/null; exit 0\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
PATH="$T/bin:$PATH" timeout 120 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo "stage exit=$?"
echo "tool_status rows:"; cut -f1-5 "$T/results/tool_status.tsv" 2>/dev/null; echo "(end)"
grep -in "error\|fail\|s2" "$T/stage.log" | head -6; tail -3 "$T/stage.log"
