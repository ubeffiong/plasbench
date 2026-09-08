#!/usr/bin/env python3
"""Compute per-isolate DIFFICULTY features from the truth reference (and,
where available, the assembly graph and short reads) -- how intrinsically
hard THIS isolate is to correctly separate into plasmid vs. chromosome,
independent of any tool's own performance on it.

Every field here is truth-derived (built from the reference PlasBench
already treats as ground truth, or from the isolate's own reads/graph), so
these are BENCHMARK-ONLY descriptors/stratifiers -- like plasmid_count in
compute_assembly_stats.py, they are deliberately EXCLUDED from
recommendation_model.py's ASSEMBLY_STAT_FIELDS and must stay that way: a
genuinely unknown operational isolate has no truth reference to compute
these from, so feeding them to a live recommendation model would be
leakage, not a real feature.

Kept separate from compute_assembly_stats.py (stdlib-only, always computed
unconditionally) because these three genuinely need external tools
(deadends, minimap2+samtools, mash) and a real per-isolate compute cost --
gated behind RUN_DIFFICULTY_FEATURES (config/config.sh), off by default,
the same convention as RUN_REFERENCE_ANNOTATION.

Each of the three features is independently optional: a missing
prerequisite (no assembly graph, no reads, the tool not installed) leaves
that field empty, never a guessed or zero value.

  gfa_dead_end_count                -- rrwick/GFA-dead-end-counter's own
                                        count of dead ends in the assembly
                                        graph, a direct fragmentation
                                        signal. Needs --graph and `deadends`
                                        on PATH (no bioconda package; a
                                        prebuilt binary from the tool's own
                                        GitHub releases page).
  plasmid_chromosome_depth_ratio    -- median plasmid-contig depth divided
                                        by median chromosome-contig depth,
                                        from aligning this isolate's own
                                        short reads back to its truth
                                        reference (minimap2 + samtools
                                        coverage). Needs --r1/--r2.
  plasmid_chromosome_mash_distance  -- minimum Mash distance between this
                                        isolate's own truth plasmid
                                        sequence(s) and its own truth
                                        chromosome -- a sequence-similarity
                                        difficulty signal (shared IS
                                        elements etc. make correct
                                        separation intrinsically harder for
                                        every tool, not just a weak one).
                                        Needs `mash` on PATH; computable
                                        from --fasta/--truth alone.

Usage:
  compute_difficulty_features.py --fasta reference.fna --truth truth.tsv \\
      --out difficulty_features.tsv --graph assembly_graph.gfa \\
      --r1 R1.fastq.gz --r2 R2.fastq.gz --threads 4
"""

import argparse
import csv
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


def read_truth(path):
    """sequence_id -> molecule_type ("CHROMOSOME"/"PLASMID"), from truth.tsv."""
    labels = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            labels[row["sequence_id"]] = row["molecule_type"]
    return labels


def split_reference_by_label(fasta_path, labels, out_dir):
    """Write <out_dir>/chromosome.fasta and <out_dir>/plasmid.fasta from the
    reference FASTA, using truth.tsv's own labels -- never a guess.

    Returns (chromosome_path_or_None, plasmid_path_or_None); a path is None
    when the isolate's truth has no sequence of that class at all (e.g. a
    plasmid-free isolate), not when the file is merely empty.
    """
    chrom_path, plasmid_path = Path(out_dir) / "chromosome.fasta", Path(out_dir) / "plasmid.fasta"
    wrote = {"CHROMOSOME": False, "PLASMID": False}
    current = None
    with open(chrom_path, "w") as chrom_handle, open(plasmid_path, "w") as plasmid_handle:
        targets = {"CHROMOSOME": chrom_handle, "PLASMID": plasmid_handle}
        with open(fasta_path) as handle:
            for line in handle:
                if line.startswith(">"):
                    seq_id = line[1:].strip().split()[0]
                    label = labels.get(seq_id)
                    current = targets.get(label)
                    if current is not None:
                        wrote[label] = True
                if current is not None:
                    current.write(line)
    return (chrom_path if wrote["CHROMOSOME"] else None,
            plasmid_path if wrote["PLASMID"] else None)


def dead_end_count(graph_path):
    executable = shutil.which("deadends")
    if not executable or not graph_path or not Path(graph_path).is_file():
        return ""
    try:
        result = subprocess.run([executable, str(graph_path)], capture_output=True, text=True, timeout=120)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip().isdigit() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def depth_ratio(fasta_path, truth_path, r1, r2, threads):
    if not (r1 and r2 and Path(r1).is_file() and Path(r2).is_file()):
        return ""
    minimap2, samtools = shutil.which("minimap2"), shutil.which("samtools")
    if not (minimap2 and samtools):
        return ""
    labels = read_truth(truth_path)
    with tempfile.TemporaryDirectory(prefix="difficulty_depth_") as tmp:
        bam = Path(tmp) / "aln.sorted.bam"
        try:
            # Piped via two subprocesses (not shell=True), matching this
            # project's own established pattern for a piped external-tool
            # call (python/make_depth_ladder.py: seqtk | gzip).
            align = subprocess.Popen([minimap2, "-t", str(threads), "-ax", "sr", str(fasta_path), str(r1), str(r2)],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            sort_result = subprocess.run([samtools, "sort", "-@", str(threads), "-o", str(bam), "-"],
                                         stdin=align.stdout, capture_output=True, timeout=1800)
            align.stdout.close()
            align.wait(timeout=1800)
            if align.returncode != 0 or sort_result.returncode != 0 or not bam.is_file():
                return ""
            subprocess.run([samtools, "index", str(bam)], capture_output=True, timeout=120)
            coverage = subprocess.run([samtools, "coverage", str(bam)], capture_output=True, text=True, timeout=120)
            if coverage.returncode != 0:
                return ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    lines = coverage.stdout.strip().splitlines()
    if not lines:
        return ""
    header = lines[0].lstrip("#").split("\t")
    try:
        name_col, depth_col = header.index("rname"), header.index("meandepth")
    except ValueError:
        return ""
    chrom_depths, plasmid_depths = [], []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) <= max(name_col, depth_col):
            continue
        label = labels.get(fields[name_col])
        depth = float(fields[depth_col])
        if label == "CHROMOSOME":
            chrom_depths.append(depth)
        elif label == "PLASMID":
            plasmid_depths.append(depth)
    if not chrom_depths or not plasmid_depths:
        return ""
    chrom_median, plasmid_median = statistics.median(chrom_depths), statistics.median(plasmid_depths)
    if chrom_median <= 0:
        return ""
    return f"{plasmid_median / chrom_median:.4f}"


def mash_distance(fasta_path, truth_path, tmp_dir):
    mash = shutil.which("mash")
    if not mash:
        return ""
    labels = read_truth(truth_path)
    chrom_path, plasmid_path = split_reference_by_label(fasta_path, labels, tmp_dir)
    if not (chrom_path and plasmid_path):
        return ""  # no plasmid, or no chromosome, in this isolate's truth
    try:
        # -i on the plasmid side only: sketch each plasmid sequence
        # individually, so a multi-plasmid isolate reports one distance per
        # plasmid rather than one distance for the concatenated plasmid
        # content -- the MINIMUM across them (the plasmid most similar to
        # the chromosome) is the harder case worth flagging.
        subprocess.run([mash, "sketch", "-s", "10000", str(chrom_path)], capture_output=True, timeout=300)
        subprocess.run([mash, "sketch", "-i", "-s", "10000", str(plasmid_path)], capture_output=True, timeout=300)
        result = subprocess.run([mash, "dist", f"{chrom_path}.msh", f"{plasmid_path}.msh"],
                                capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        distances = [float(line.split("\t")[2]) for line in result.stdout.strip().splitlines()]
        return f"{min(distances):.6f}"
    except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
        return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--graph", default="")
    ap.add_argument("--r1", default="")
    ap.add_argument("--r2", default="")
    ap.add_argument("--sample-id")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    sample_id = args.sample_id or args.fasta.replace("\\", "/").rstrip("/").split("/")[-2]

    dead_ends = dead_end_count(args.graph)
    ratio = depth_ratio(args.fasta, args.truth, args.r1, args.r2, args.threads)
    with tempfile.TemporaryDirectory(prefix="difficulty_mash_") as tmp:
        distance = mash_distance(args.fasta, args.truth, tmp)

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sample_id", "gfa_dead_end_count", "plasmid_chromosome_depth_ratio",
                         "plasmid_chromosome_mash_distance"])
        writer.writerow([sample_id, dead_ends, ratio, distance])
    sys.stderr.write(
        f"[compute_difficulty_features] wrote {args.out} for {sample_id} "
        f"(dead_ends={dead_ends or 'n/a'}, depth_ratio={ratio or 'n/a'}, "
        f"mash_distance={distance or 'n/a'})\n"
    )


if __name__ == "__main__":
    main()
