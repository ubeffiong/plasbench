#!/usr/bin/env bash
# Stage 7 -- optional native long-read and hybrid reconstruction.
#
#   flye_mob_recon (RUN_FLYE_MOB_RECON) -- long-read only. Flye assembles, then
#       MOB-Recon emits standardized plasmid bins. Flye alone is not treated as
#       a plasmid caller, because that would label chromosome sequence as
#       plasmid without evidence. Score with ANALYSIS_TRACK=long_read.
#   plassembler (RUN_PLASSEMBLER) -- hybrid: long reads plus the short reads
#       stage 1 already downloaded. Score with ANALYSIS_TRACK=hybrid.
#
# Both are off by default, and neither is ever ranked against a short-read-only
# tool: aggregation writes one leaderboard per analysis track and never mixes
# track claims (python/aggregate_results.py: write_track_leaderboards).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"

if [[ "${RUN_FLYE_MOB_RECON:-0}" -ne 1 && "${RUN_PLASSEMBLER:-0}" -ne 1 ]]; then
    log "Stage 7 disabled (RUN_FLYE_MOB_RECON=0, RUN_PLASSEMBLER=0)."; exit 0
fi
if [[ "${RUN_FLYE_MOB_RECON:-0}" -eq 1 ]]; then
    case "$FLYE_READ_TYPE" in nano-raw|nano-hq|pacbio-raw|pacbio-hifi) ;; *) die "invalid FLYE_READ_TYPE: $FLYE_READ_TYPE";; esac
    need flye
    need mob_recon
fi
[[ "${RUN_PLASSEMBLER:-0}" -eq 1 ]] && need plassembler
true
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

# --- Plassembler (hybrid: long reads + the short reads stage 1 downloaded) ----
#
# CIRCULARITY. PlasBench's truth labels come from a complete long-read or hybrid
# assembly. Handing Plassembler the same long reads that produced that assembly
# scores the tool against its own input: it would look near-perfect for reasons
# that say nothing about the tool. Short-read tools have no such problem, which
# is why the short-read track never needed this check.
#
# A sample is therefore only eligible when the cohort explicitly declares that
# its long reads are independent of its truth, via a
# truth_independent_of_long_reads column set to yes/true/1. Anything else --
# absent column, empty value, no -- is treated as circular and skipped, with the
# reason recorded. PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 overrides this globally
# and stamps every affected row so the compromise stays visible in the results.
plassembler_eligible() {
    local sample="$1"
    local declared truth
    declared="$(sample_column "$SAMPLE_SHEET" "$sample" truth_independent_of_long_reads)"
    case "$(printf '%s' "${declared:-}" | tr '[:upper:]' '[:lower:]')" in
        yes|true|1) printf 'independent'; return 0 ;;
    esac
    truth="$(sample_column "$SAMPLE_SHEET" "$sample" truth_technology)"
    if [[ "${PLASSEMBLER_ALLOW_CIRCULAR_TRUTH:-0}" -eq 1 ]]; then
        printf 'override'; return 0
    fi
    printf '%s' "${truth:-unknown}"
    return 1
}

run_plassembler_for_sample() {
    local sample="$1" rdir="$RESULTS_DIR/$1"
    local tool="plassembler"
    local reads="$DATA_DIR/$1/$LONG_READS_FILE"
    local out_dir="$rdir/$tool" pred="$rdir/pred_$tool.plasmid.fasta" done_file="$rdir/.$tool.complete"
    mkdir -p "$rdir"

    # Short reads: whichever pair stage 1 produced for this sample.
    local r1 r2
    r1="$(ls "$DATA_DIR/$1"/*_1.fastq.gz 2>/dev/null | grep -v '\.trim\.' | head -1 || true)"
    r2="$(ls "$DATA_DIR/$1"/*_2.fastq.gz 2>/dev/null | grep -v '\.trim\.' | head -1 || true)"

    local eligibility
    if ! eligibility="$(plassembler_eligible "$sample")"; then
        warn "  $tool: skipping $sample -- its truth assembly derives from these long reads (truth_technology=$eligibility)"
        warn "         Declare truth_independent_of_long_reads=yes for this sample, or set"
        warn "         PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 to score it anyway (recorded in tool_status.tsv)."
        printf '%s\t%s\tskipped\t\tcircular truth: truth_technology=%s derives from the supplied long reads\t\t\n' \
            "$sample" "$tool" "$eligibility" >> "$STATUS"
        return
    fi

    if [[ ! -s "$reads" ]]; then
        warn "  $tool: no long reads for $sample at $reads; skipped"
        printf '%s\t%s\tskipped\t\tlong-read FASTQ unavailable\t\t\n' "$sample" "$tool" >> "$STATUS"; return
    fi
    if [[ -z "$r1" || -z "$r2" ]]; then
        warn "  $tool: no paired short reads for $sample; skipped (Plassembler needs both)"
        printf '%s\t%s\tskipped\t\tpaired short reads unavailable\t\t\n' "$sample" "$tool" >> "$STATUS"; return
    fi
    if [[ ! -d "$PLASSEMBLER_DB" ]]; then
        warn "  $tool: database missing at $PLASSEMBLER_DB; skipped"
        warn "         Install it once with: bash env/download_plassembler_db.sh"
        printf '%s\t%s\tskipped\t\tPlassembler database missing at %s\t\t\n' "$sample" "$tool" "$PLASSEMBLER_DB" >> "$STATUS"; return
    fi
    if [[ -e "$done_file" && -s "$pred" && "${FORCE_RERUN_TOOLS:-0}" -ne 1 ]]; then
        log "  $tool: reusing completed result for $sample"
        printf '%s\t%s\treused\t%s\tcompleted result reused\t\t\n' "$sample" "$tool" "$pred" >> "$STATUS"; return
    fi

    rm -rf "$out_dir" "$pred" "$done_file"
    local start rss="$LOG_DIR/$sample.$tool.rss"; start=$(date +%s); rm -f "$rss"
    local note="hybrid long+short assembly"
    [[ "$eligibility" == "override" ]] && note="hybrid long+short assembly; PLASSEMBLER_ALLOW_CIRCULAR_TRUTH=1 -- truth may derive from these long reads"
    log "  $tool: hybrid assembly for $sample (chromosome length >= $PLASSEMBLER_CHROMOSOME_LENGTH)"

    if profile_run "$rss" plassembler run -d "$PLASSEMBLER_DB" \
            -l "$reads" -1 "$r1" -2 "$r2" -o "$out_dir" \
            -t "$THREADS" -c "$PLASSEMBLER_CHROMOSOME_LENGTH" -f \
            > "$LOG_DIR/$sample.$tool.log" 2>&1 && \
       bash "$HERE/../adapters/adapt_plassembler.sh" "$out_dir" "" "$pred" \
            >> "$LOG_DIR/$sample.$tool.log" 2>&1; then
        touch "$done_file"
        printf '%s\t%s\tcompleted\t%s\t%s\t%s\t%s\n' "$sample" "$tool" "$pred" "$note" \
            "$(( $(date +%s) - start ))" "$(tr -d '[:space:]' < "$rss" 2>/dev/null || true)" >> "$STATUS"
    else
        rm -f "$pred" "$done_file"
        warn "$tool failed for $sample; see $LOG_DIR/$sample.$tool.log"
        printf '%s\t%s\tfailed\t\tsee log\t%s\t%s\n' "$sample" "$tool" \
            "$(( $(date +%s) - start ))" "$(tr -d '[:space:]' < "$rss" 2>/dev/null || true)" >> "$STATUS"
    fi
}

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    [[ "${RUN_FLYE_MOB_RECON:-0}" -eq 1 ]] && for_sample "$SAMPLE"
    [[ "${RUN_PLASSEMBLER:-0}" -eq 1 ]] && run_plassembler_for_sample "$SAMPLE"
    true
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 7 complete."
[[ "${RUN_FLYE_MOB_RECON:-0}" -eq 1 ]] && \
    log "  flye_mob_recon: score with plasbench run 5 6 --analysis-track long_read"
[[ "${RUN_PLASSEMBLER:-0}" -eq 1 ]] && \
    log "  plassembler:    score with plasbench run 5 6 --analysis-track hybrid"
true
