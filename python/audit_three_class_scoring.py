#!/usr/bin/env python3
"""One-off three-class scoring audit (Phase E, Part 14 of the sibling-repo
cross-pollination plan) -- NOT part of the ongoing pipeline, never wired
into any stage script, matching parse_teixeira2025_supplement.py's own
"one-time migration/investigation script" precedent.

PlasBench's whole scoring model is binary: every reference base is either
PLASMID or CHROMOSOME (truth.tsv), and a tool's prediction is scored
against that split. RasmussenLab/PlasMAAG (a sibling metagenomic plasmid
binner, see docs/COHORTS.md's cross-pollination notes) uses a real THIRD
class, candidate_virus, alongside plasmid/chromosome. This script audits
whether that gap is actually costing PlasBench anything real: does any
curated isolate's truth reference contain an INTEGRATED PROVIRUS region
embedded inside a truth PLASMID or CHROMOSOME sequence -- sequence that is
neither cleanly "plasmid" nor cleanly "the rest of the chromosome/plasmid",
and could be silently absorbed as a false positive or false negative by
the current binary scorer depending on how a tool happens to handle it.

Runs `genomad end-to-end` (the SAME real invocation
scripts/04_run_tools.sh's own run_genomad() uses, `genomad end-to-end
--threads N <fasta> <outdir> <genomad_db>`) against the TRUTH REFERENCE
itself (not a tool's prediction -- this audits the ground truth, not any
tool's output), then parses geNomad's own provirus-detection output.

geNomad's provirus finding runs by default inside `end-to-end` (confirmed
directly from its own source, genomad/cli.py: gated by
`--disable-find-proviruses`, which this script never passes). Verified
output location and columns (confirmed directly from geNomad's own
documentation, not assumed): `<prefix>_summary/<prefix>_virus_summary.tsv`,
with a `coordinates` column ("1-indexed coordinates of the provirus region
within host sequences... `NA` for viruses that were not predicted to be
integrated") and a `seq_name` column following
`"<sequence_identifier>|provirus_<start>_<end>"` for integrated calls --
coordinates are relative to the ORIGINAL host sequence, exactly what is
needed to cross-reference against truth.tsv's own sequence boundaries.

Writes one row per detected provirus region:
  sample, host_sequence_id, molecule_type, host_length_bp,
  provirus_start, provirus_end, provirus_length_bp, fraction_of_host_sequence
A sample with geNomad unavailable, or with zero provirus regions detected,
writes a header-only file -- never a fabricated "no provirus" claim when
geNomad was never actually run.

This is a RESEARCH script: it reports findings, and does not itself
propose or implement a fix. Per the approved plan, a three-class scoring
change is only worth designing if running this across a real cohort finds
a genuine, non-trivial incidence of truth plasmids/chromosomes carrying
embedded provirus regions -- not a speculative feature built ahead of
evidence.

Usage:
  audit_three_class_scoring.py --reference data/s1/reference.fna \\
      --truth data/s1/truth.tsv --sample s1 \\
      --genomad-db /path/to/genomad_db --out s1.provirus_audit.tsv \\
      --threads 4
"""

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def read_truth(path):
    """sequence_id -> (molecule_type, length)."""
    truth = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            truth[row["sequence_id"]] = (row["molecule_type"].upper(), int(row["length"]))
    return truth


def parse_provirus_calls(virus_summary_path):
    """[(host_sequence_id, start, end)] for every INTEGRATED provirus call
    -- rows whose own `coordinates` column is real (not the documented
    'NA' for a non-integrated virus). start/end are 1-indexed, as geNomad
    itself documents them, relative to the ORIGINAL host sequence."""
    calls = []
    with open(virus_summary_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            coordinates = (row.get("coordinates") or "").strip()
            if not coordinates or coordinates.upper() == "NA":
                continue
            seq_name = row.get("seq_name", "")
            host_id = seq_name.split("|provirus_")[0]
            try:
                start_str, end_str = coordinates.split("-")
                start, end = int(start_str), int(end_str)
            except ValueError:
                continue
            calls.append((host_id, start, end))
    return calls


def run_genomad(genomad_path, fasta, out_dir, genomad_db, threads):
    command = [genomad_path, "end-to-end", "--threads", str(threads), str(fasta), str(out_dir), str(genomad_db)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"[audit_three_class_scoring] genomad failed (exit {result.returncode}):\n{result.stderr[-2000:]}\n")
        return None
    prefix = Path(fasta).stem
    summary = Path(out_dir) / f"{prefix}_summary" / f"{prefix}_virus_summary.tsv"
    if not summary.is_file():
        sys.stderr.write(f"[audit_three_class_scoring] genomad reported success but {summary} is missing\n")
        return None
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--genomad-db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    header = ["sample", "host_sequence_id", "molecule_type", "host_length_bp",
              "provirus_start", "provirus_end", "provirus_length_bp", "fraction_of_host_sequence"]
    rows = []

    genomad_path = shutil.which("genomad")
    if not genomad_path:
        sys.stderr.write("[audit_three_class_scoring] genomad is not installed (or not on PATH); no audit performed\n")
        Path(args.out).write_text("\t".join(header) + "\n")
        return

    truth = read_truth(args.truth)
    with tempfile.TemporaryDirectory(prefix="three_class_audit_") as tmp:
        summary = run_genomad(genomad_path, args.reference, tmp, args.genomad_db, args.threads)
        if summary is not None:
            for host_id, start, end in parse_provirus_calls(summary):
                molecule_type, host_length = truth.get(host_id, (None, 0))
                if molecule_type is None:
                    continue  # a provirus call on a sequence absent from truth.tsv: not this audit's concern
                provirus_length = max(0, end - start + 1)
                fraction = provirus_length / host_length if host_length > 0 else None
                rows.append([args.sample, host_id, molecule_type, host_length, start, end,
                             provirus_length, f"{fraction:.4f}" if fraction is not None else ""])

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)

    sys.stderr.write(f"[audit_three_class_scoring] wrote {args.out} ({len(rows)} provirus call(s)) for {args.sample}\n")


if __name__ == "__main__":
    main()
