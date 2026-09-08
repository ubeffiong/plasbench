#!/usr/bin/env python3
"""Optional QUAST supplementary diagnostics for ONE tool's predicted-plasmid
FASTA on ONE sample, gated behind RUN_QUAST_DIAGNOSTICS (config/config.sh),
off by default -- exactly like RUN_REFERENCE_ANNOTATION/RUN_DIFFICULTY_FEATURES.

Runs QUAST three ways per C-Connor/PlasmidToolBenchMarking's own verified
pattern (a sibling plasmid-tool benchmarking pipeline; see docs/METHODS.md),
against the SAME query FASTA (this tool's own pred_<tool>.plasmid.fasta):

  combined   -- one QUAST run against ALL truth plasmids as a single
                multi-FASTA reference (QUAST's own documented support for a
                multi-sequence reference in one -r file).
  individual -- one QUAST run PER truth plasmid, its own single-sequence
                reference -- shows whether a tool's overall recall is spread
                evenly across plasmids or concentrated in one.
  chromosome -- one QUAST run against the truth CHROMOSOME as reference --
                a high genome-fraction here means the tool's "plasmid"
                prediction actually contains substantial chromosome
                sequence, a different failure mode from simply missing
                plasmid content, and one PlasBench's own base-level
                precision/recall already counts but does not explain.

Never replaces score_plasmids.py's own base-level precision/recall/F1 (the
ranking metric) -- purely a supplementary "why did this happen" diagnostic,
surfaced in its own HTML report section.

Parses report.tsv by ROW-LABEL string match, never fixed row position
(confirmed from QUAST's own source, quast_libs/reporting.py: only fields
applicable to a given run are emitted, in a documented but non-fixed
order): "Genome fraction (%)", "# misassemblies", "Duplication ratio".
--min-contig 0 is passed explicitly -- QUAST's own default (500 bp,
quast_libs/qconfig.py) would silently drop short plasmid contigs from the
analysis, exactly the kind of guessed/hidden filtering this project avoids.

Writes one row per (reference_type, reference_id) comparison:
  sample, tool, reference_type, reference_id, genome_fraction_pct,
  misassembly_count, duplication_ratio
A tool with an empty prediction, or QUAST unavailable, writes NO rows for
this tool -- never a fabricated 0% genome fraction.

Usage:
  run_quast_diagnostics.py --query pred_platon.plasmid.fasta \\
      --reference reference.fna --truth truth.tsv \\
      --sample s1 --tool platon --out s1.platon.quast_diagnostics.tsv \\
      --threads 4
"""

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_difficulty_features import read_truth, split_reference_by_label  # noqa: E402


def split_individual_plasmids(fasta_path, labels, out_dir):
    """Write one single-sequence FASTA per truth PLASMID under out_dir,
    named <seq_id>.fasta. Returns the list of (seq_id, path) written, in
    the reference's own record order."""
    written = []
    current_id = None
    current_handle = None
    out_dir = Path(out_dir)
    try:
        with open(fasta_path) as handle:
            for line in handle:
                if line.startswith(">"):
                    if current_handle is not None:
                        current_handle.close()
                    current_handle = None
                    seq_id = line[1:].strip().split()[0]
                    if labels.get(seq_id) == "PLASMID":
                        current_id = seq_id
                        path = out_dir / f"{seq_id}.fasta"
                        current_handle = open(path, "w")
                        written.append((seq_id, path))
                    else:
                        current_id = None
                if current_handle is not None:
                    current_handle.write(line)
    finally:
        if current_handle is not None:
            current_handle.close()
    return written


def parse_report(report_path):
    """{row_label: value} from a QUAST report.tsv -- by label, never fixed
    row position (see module docstring). Only one data column is ever
    present here (a single query FASTA per QUAST invocation)."""
    values = {}
    with open(report_path, newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) >= 2 and row[0] != "Assembly":
                values[row[0]] = row[1]
    return values


def run_quast(quast_path, query, reference, out_dir, threads, min_contig):
    command = [quast_path, str(query), "-r", str(reference), "-o", str(out_dir),
               "--min-contig", str(min_contig), "--fast", "--no-icarus", "--silent",
               "-t", str(threads)]
    result = subprocess.run(command, capture_output=True, text=True)
    report = Path(out_dir) / "report.tsv"
    if result.returncode != 0 or not report.is_file():
        sys.stderr.write(f"[run_quast_diagnostics] QUAST failed for {query} vs {reference} "
                          f"(exit {result.returncode}):\n{result.stderr[-2000:]}\n")
        return None
    return parse_report(report)


def diagnostic_row(sample, tool, reference_type, reference_id, values):
    if values is None:
        return None
    genome_fraction = values.get("Genome fraction (%)", "")
    misassemblies = values.get("# misassemblies", "")
    duplication = values.get("Duplication ratio", "")
    return [sample, tool, reference_type, reference_id, genome_fraction, misassemblies, duplication]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--min-contig", type=int, default=0)
    args = ap.parse_args()

    header = ["sample", "tool", "reference_type", "reference_id",
              "genome_fraction_pct", "misassembly_count", "duplication_ratio"]
    if not Path(args.query).is_file() or Path(args.query).stat().st_size == 0:
        sys.stderr.write(f"[run_quast_diagnostics] {args.query} is empty (tool predicted nothing); no rows written\n")
        Path(args.out).write_text("\t".join(header) + "\n")
        return

    quast_path = shutil.which("quast.py")
    if not quast_path:
        sys.stderr.write("[run_quast_diagnostics] quast.py is not installed (or not on PATH)\n")
        Path(args.out).write_text("\t".join(header) + "\n")
        return

    labels = read_truth(args.truth)
    rows = []
    with tempfile.TemporaryDirectory(prefix="quast_diagnostics_") as tmp:
        tmp = Path(tmp)
        chrom_path, plasmid_path = split_reference_by_label(args.reference, labels, tmp)

        if plasmid_path is not None:
            values = run_quast(quast_path, args.query, plasmid_path, tmp / "combined", args.threads, args.min_contig)
            row = diagnostic_row(args.sample, args.tool, "combined", "all_plasmids", values)
            if row:
                rows.append(row)

            for seq_id, path in split_individual_plasmids(args.reference, labels, tmp):
                values = run_quast(quast_path, args.query, path, tmp / f"individual_{seq_id}", args.threads, args.min_contig)
                row = diagnostic_row(args.sample, args.tool, "individual", seq_id, values)
                if row:
                    rows.append(row)

        if chrom_path is not None:
            values = run_quast(quast_path, args.query, chrom_path, tmp / "chromosome", args.threads, args.min_contig)
            row = diagnostic_row(args.sample, args.tool, "chromosome", "chromosome", values)
            if row:
                rows.append(row)

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)

    sys.stderr.write(f"[run_quast_diagnostics] wrote {args.out} ({len(rows)} comparison(s)) for {args.sample}/{args.tool}\n")


if __name__ == "__main__":
    main()
