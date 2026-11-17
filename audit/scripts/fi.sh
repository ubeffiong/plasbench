#!/usr/bin/env bash
# Failure injection against stage 4 of the main export (WSL, fake binaries, offline).
# Does not touch the project: uses ~/pb_main (a copy) and a temp dir per case.
set -u
ROOT=~/pb_main
mk() {  # mk <dir> : sample s1 with contigs and trimmed reads, fresh results
  local T="$1"; rm -rf "$T"; mkdir -p "$T/bin" "$T/data/s1" "$T/config"
  printf '>contig1\nACGTACGTACGT\n' > "$T/data/s1/contigs.fasta"
  printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/s1/SRR1_1.trim.fastq.gz"
  printf '@r1\nACGT\n+\nIIII\n' | gzip > "$T/data/s1/SRR1_2.trim.fastq.gz"
  printf 'sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR1\n' > "$T/config/accessions.tsv"
}
envs() { export DATA_DIR="$1/data" RESULTS_DIR="$1/results" LOG_DIR="$1/logs" SAMPLE_SHEET="$1/config/accessions.tsv" REQUIRE_CURATED_METADATA=0; }
# Only run mob_recon so timing is predictable.
only() { export RUN_MOB_RECON=1 RUN_PLATON=0 RUN_PLASMIDSPADES=0 RUN_GENOMAD=0 RUN_PLASME=0 RUN_PLASMIDHUNTER=0 RUN_PLASMER=0 RUN_PLASGRAPH2=0 RUN_PLSMD=0 RUN_PLASSEMBLER=0 RUN_PLASCOPE=0 RUN_RFPLASMID=0 RUN_GPLAS=0 RUN_PLASBIN_FLOW=0 RUN_BASELINES=0; export ONLY_TOOL=mob_recon; }

echo "=== FI-A: tool exits 0 and writes NO output (silent failure)"
T=$(mktemp -d); mk "$T"; envs "$T"
printf '#!/usr/bin/env bash\nexit 0\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
( only; PATH="$T/bin:$PATH" timeout 120 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo "stage exit=$?" )
echo "tool_status rows:"; cat "$T/results/tool_status.tsv" 2>/dev/null | cut -f1-5
ls "$T/results/s1" 2>/dev/null | head

echo; echo "=== FI-B: tool hangs, no TOOL_TIMEOUT_SECONDS (outer timeout 25 s)"
T=$(mktemp -d); mk "$T"; envs "$T"
printf '#!/usr/bin/env bash\nsleep 300\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
( only; export TOOL_TIMEOUT_SECONDS=; PATH="$T/bin:$PATH" timeout 25 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo "stage exit=$? (124 = still hanging when the outer timeout fired)" )
echo "leftover 'sleep 300' processes:"; pgrep -af "sleep 300" | head -3; pkill -f "sleep 300" 2>/dev/null

echo; echo "=== FI-C: SIGINT to the stage while a tool runs"
T=$(mktemp -d); mk "$T"; envs "$T"
printf '#!/usr/bin/env bash\nsleep 301\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
( only; PATH="$T/bin:$PATH" bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1 & echo $! > "$T/pid"; wait ) &
sleep 8; P=$(cat "$T/pid"); kill -INT "$P" 2>/dev/null; sleep 5
echo "stage still alive after SIGINT? $(kill -0 "$P" 2>/dev/null && echo yes || echo no)"
echo "leftover 'sleep 301' processes:"; pgrep -af "sleep 301" | head -3
echo "status file:"; cat "$T/results/tool_status.tsv" 2>/dev/null | cut -f1-5
pkill -f "sleep 301" 2>/dev/null; wait 2>/dev/null

echo; echo "=== FI-D: a sample whose job dies (contigs.fasta is a directory)"
T=$(mktemp -d); mk "$T"; envs "$T"
rm "$T/data/s1/contigs.fasta"; mkdir "$T/data/s1/contigs.fasta"
printf '#!/usr/bin/env bash\nmkdir -p "$2" 2>/dev/null; exit 0\n' > "$T/bin/mob_recon"; chmod +x "$T/bin/mob_recon"
( only; PATH="$T/bin:$PATH" timeout 120 bash "$ROOT/scripts/04_run_tools.sh" > "$T/stage.log" 2>&1; echo "stage exit=$?" )
echo "tool_status rows:"; cat "$T/results/tool_status.tsv" 2>/dev/null | cut -f1-5; echo "(end)"
tail -4 "$T/stage.log"
