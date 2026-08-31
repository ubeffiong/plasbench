#!/usr/bin/env bash
# Stage 3 — per sample: quality-trim reads (fastp) and assemble them
# (SPAdes/Unicycler) into the base contig set that the classification tools use.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../config/config.sh"
source "$HERE/lib.sh"
need fastp

while IFS=$'\t' read -r SAMPLE ASM SRA; do
    [[ -z "${SAMPLE:-}" ]] && continue
    SDIR="$DATA_DIR/$SAMPLE"
    R1="$SDIR/${SRA}_1.fastq.gz"; R2="$SDIR/${SRA}_2.fastq.gz"
    [[ -s "$R1" && -s "$R2" ]] || { warn "no reads for $SAMPLE; run 01_download.sh"; continue; }

    log "=== Assemble $SAMPLE ==="
    # --- fastp trim ---
    T1="$SDIR/${SRA}_1.trim.fastq.gz"; T2="$SDIR/${SRA}_2.trim.fastq.gz"
    if [[ -s "$T1" && -s "$T2" ]]; then
        log "  trimmed reads present, skipping fastp"
    else
        log "  fastp trimming ..."
        fastp -i "$R1" -I "$R2" -o "$T1" -O "$T2" \
            --length_required "$MIN_READ_LEN" --thread "$THREADS" \
            --json "$SDIR/fastp.json" --html "$SDIR/fastp.html" $FASTP_EXTRA \
            > "$LOG_DIR/${SAMPLE}.fastp.log" 2>&1 || die "fastp failed for $SAMPLE"
    fi

    # --- assemble ---
    ASMDIR="$SDIR/assembly"
    CONTIGS="$SDIR/contigs.fasta"
    GRAPH="$SDIR/assembly_graph.gfa"
    if [[ -s "$CONTIGS" ]]; then
        log "  base assembly present, skipping"
    else
        if [[ "$ASSEMBLER" == "spades" ]]; then
            need spades.py
            log "  SPAdes assembling ..."
            spades.py -1 "$T1" -2 "$T2" -o "$ASMDIR" \
                --threads "$THREADS" --memory "$MEMORY_GB" \
                > "$LOG_DIR/${SAMPLE}.spades.log" 2>&1 || die "SPAdes failed for $SAMPLE"
            cp "$ASMDIR/contigs.fasta" "$CONTIGS"
            [[ -f "$ASMDIR/assembly_graph_with_scaffolds.gfa" ]] && \
                cp "$ASMDIR/assembly_graph_with_scaffolds.gfa" "$GRAPH" || true
        elif [[ "$ASSEMBLER" == "unicycler" ]]; then
            need unicycler
            log "  Unicycler assembling ..."
            unicycler -1 "$T1" -2 "$T2" -o "$ASMDIR" -t "$THREADS" \
                > "$LOG_DIR/${SAMPLE}.unicycler.log" 2>&1 || die "Unicycler failed for $SAMPLE"
            cp "$ASMDIR/assembly.fasta" "$CONTIGS"
            [[ -f "$ASMDIR/assembly.gfa" ]] && cp "$ASMDIR/assembly.gfa" "$GRAPH" || true
        else
            die "unknown ASSEMBLER='$ASSEMBLER' (use spades or unicycler)"
        fi
        log "  contigs -> $CONTIGS"
    fi
done < <(read_samples "$SAMPLE_SHEET")

log "Stage 3 (assembly) complete."
