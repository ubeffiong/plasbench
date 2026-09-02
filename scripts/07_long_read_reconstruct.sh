#!/usr/bin/env bash
# Stage 7 -- optional native ONT/PacBio reconstruction.
# Flye produces a long-read assembly; MOB-Recon then emits standardized plasmid
# bins. Flye alone is not treated as a plasmid caller because that would label
# chromosome sequence as plasmid without evidence.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

[[ "${RUN_FLYE_MOB_RECON:-0}" -eq 1 ]] || { log "Stage 7 disabled (RUN_FLYE_MOB_RECON=0)."; exit 0; }
case "$FLYE_READ_TYPE" in nano-raw|nano-hq|pacbio-raw|pacbio-hifi) ;; *) die "invalid FLYE_READ_TYPE: $FLYE_READ_TYPE";; esac
need flye
need mob_recon
ADAPT="$HERE/../adapters/adapt_mob_recon.sh"
STATUS="$RESULTS_DIR/tool_status.tsv"
[[ -s "$STATUS" ]] || printf 'sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n' > "$STATUS"

profile_run() {
    local rss="$1"; shift
    if [[ -x /usr/bin/time ]]; then
        /usr/bin/time -f '%M' -o "$rss" "$@"
    else
        "$@"
    fi
}

for_sample() {
    local sample="$1" rdir="$RESULTS_DIR/$1" reads="$DATA_DIR/$1/$LONG_READS_FILE"
    local tool="flye_mob_recon" flye_dir="$rdir/flye" mob_dir="$rdir/$tool" pred="$rdir/pred_$tool.plasmid.fasta" done_file="$rdir/.$tool.complete"
    mkdir -p "$rdir"
    if [[ ! -s "$reads" ]]; then
        warn "$tool: no long reads for $sample at $reads; skipped"
        printf '%s\t%s\tskipped\t\tlong-read FASTQ unavailable\t\t\n' "$sample" "$tool" >> "$STATUS"; return
    fi
    if [[ -e "$done_file" && -s "$pred" && "${FORCE_RERUN_TOOLS:-0}" -ne 1 ]]; then
        log "  $tool: reusing completed result for $sample"
        printf '%s\t%s\treused\t%s\tcompleted result reused\t\t\n' "$sample" "$tool" "$pred" >> "$STATUS"; return
    fi
    rm -rf "$flye_dir" "$mob_dir" "$pred" "$done_file"
    local start rss="$LOG_DIR/$sample.$tool.rss"; start=$(date +%s); rm -f "$rss"
    log "  $tool: Flye ($FLYE_READ_TYPE) then MOB-Recon for $sample"
    if profile_run "$rss" flye "--$FLYE_READ_TYPE" "$reads" --out-dir "$flye_dir" --threads "$THREADS" > "$LOG_DIR/$sample.$tool.log" 2>&1 && \
       profile_run "$rss" mob_recon --infile "$flye_dir/assembly.fasta" --outdir "$mob_dir" --num_threads "$THREADS" --force >> "$LOG_DIR/$sample.$tool.log" 2>&1 && \
       bash "$ADAPT" "$mob_dir" "$flye_dir/assembly.fasta" "$pred" >> "$LOG_DIR/$sample.$tool.log" 2>&1; then
        touch "$done_file"
        printf '%s\t%s\tcompleted\t%s\tFlye %s plus MOB-Recon\t%s\t%s\n' "$sample" "$tool" "$pred" "$FLYE_READ_TYPE" "$(( $(date +%s) - start ))" "$(tr -d '[:space:]' < "$rss" 2>/dev/null || true)" >> "$STATUS"
    else
        rm -f "$pred" "$done_file"
        warn "$tool failed for $sample; see $LOG_DIR/$sample.$tool.log"
        printf '%s\t%s\tfailed\t\tsee log\t%s\t%s\n' "$sample" "$tool" "$(( $(date +%s) - start ))" "$(tr -d '[:space:]' < "$rss" 2>/dev/null || true)" >> "$STATUS"
    fi
}

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -n "${SAMPLE:-}" ]] && for_sample "$SAMPLE"
done < <(read_samples "$SAMPLE_SHEET")
log "Stage 7 complete. Run stages 5 and 6 with ANALYSIS_TRACK=long_read to score and report this track."
