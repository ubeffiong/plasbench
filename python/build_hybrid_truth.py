#!/usr/bin/env python3
"""Build a truth reference in-house via hybrid (long+short read) assembly,
for cohort sources that deposit raw reads but never formally submitted a
Complete Genome assembly (see docs/FINDING_DATA.md's Route C).

Runs `unicycler -1 R1 -2 R2 -l LONG -o <workdir>` and labels chromosome vs
plasmid from Unicycler's OWN topology output alone (`circular=true`/`false`
and each contig's length, straight from its FASTA headers) -- never a
gene-content classifier (MOB-typer, PlasmidFinder, ...), since several of
those ARE benchmarked prediction tools in this project; using one to build
"truth" would make that tool trivially perfect against itself. Unicycler
itself is not a benchmarked plasmid caller here -- only an assembler,
matching its existing use for short-read ASSEMBLER=unicycler assemblies
(already a direct env dependency; no new install).

Acceptance is strict, never a guess: at least one circular contig at or
above --min-chromosome-length must exist (the presumed chromosome); every
other circular contig becomes a plasmid; ANY non-circular contig, or more
than one contig clearing the chromosome-length bar, means the assembly is
not a trustworthy complete reference (or ambiguous) -- the whole sample is
REJECTED (non-zero exit, specific reason), never a partial/uncertain truth.
This mirrors the same "Complete Genome" bar every NCBI-downloaded truth
assembly must already clear (validate_cohort.py's ACCESSION check).

Writes:
  --out-reference   reference.fna, Unicycler's own assembly FASTA, unchanged.
  --out-truth       truth.tsv, in make_truth.py's exact 3-column shape
                     (sequence_id, molecule_type, length) -- 02_truth.sh's
                     downstream validate_truth_table.py needs no changes,
                     since its job is agnostic to how the table was built.
  --out-provenance  truth_provenance.json: Unicycler version, exact command
                     line, per-contig length/circular flags, and a
                     write_manifest.py-style content fingerprint of the
                     input read files -- read by write_manifest.py exactly
                     like annotation_provenance.json already is.

Usage:
  build_hybrid_truth.py --long-reads long_reads.fastq.gz \
      --r1 SRR1_1.fastq.gz --r2 SRR1_2.fastq.gz \
      --out-reference reference.fna --out-truth truth.tsv \
      --out-provenance truth_provenance.json \
      --min-chromosome-length 1500000 --threads 4
"""

import argparse
import hashlib
import json
import re
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path

CIRCULAR = re.compile(r"\bcircular=true\b", re.IGNORECASE)


def unicycler_version(unicycler_path):
    try:
        result = subprocess.run([unicycler_path, "--version"], capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip()
    except Exception as exc:
        return f"unknown ({exc})"


def read_fasta_records(path):
    """Return [(header, seq_id, length)] preserving file order. seq_id is
    the first whitespace-delimited header token, matching every other
    adapter/scorer's convention in this project."""
    records = []
    header = seq_id = None
    length = 0
    with open(path) as handle:
        for line in handle:
            if line.startswith(">"):
                if seq_id is not None:
                    records.append((header, seq_id, length))
                header = line[1:].strip()
                seq_id = header.split()[0]
                length = 0
            else:
                length += len(line.strip())
        if seq_id is not None:
            records.append((header, seq_id, length))
    return records


def classify_contigs(records, min_chromosome_length):
    """Return (labels, chromosome_id, reason). labels/chromosome_id are None
    (with a reason) when the assembly fails the acceptance bar. Pure
    topology/length, never gene content -- see the module docstring."""
    circular_ids = {seq_id for header, seq_id, _ in records if CIRCULAR.search(header)}
    non_circular = [seq_id for _, seq_id, _ in records if seq_id not in circular_ids]
    if non_circular:
        shown = ", ".join(non_circular[:5]) + (", ..." if len(non_circular) > 5 else "")
        return None, None, (
            f"assembly has {len(non_circular)} non-circular contig(s) ({shown}); "
            "not a trustworthy complete reference"
        )
    chromosome_candidates = sorted(
        ((seq_id, length) for _, seq_id, length in records if length >= min_chromosome_length),
        key=lambda pair: pair[1], reverse=True,
    )
    if not chromosome_candidates:
        largest = max((length for _, _, length in records), default=0)
        return None, None, (
            f"no circular contig reaches --min-chromosome-length ({min_chromosome_length} bp); "
            f"largest circular contig is {largest} bp"
        )
    if len(chromosome_candidates) > 1:
        names = ", ".join(seq_id for seq_id, _ in chromosome_candidates)
        return None, None, (
            f"ambiguous: {len(chromosome_candidates)} circular contigs are each >= "
            f"--min-chromosome-length ({names}); needs manual review, not a guess"
        )
    chromosome_id = chromosome_candidates[0][0]
    labels = {seq_id: ("CHROMOSOME" if seq_id == chromosome_id else "PLASMID") for seq_id in circular_ids}
    return labels, chromosome_id, None


def file_fingerprint(paths):
    """Cheap identity for the input read files, matching write_manifest.py's
    directory_identity() -- size+mtime, never hashing full read-file
    contents (these can be many GB)."""
    digest = hashlib.sha256()
    entries = []
    for path in paths:
        candidate = Path(path)
        if not candidate.is_file():
            continue
        stat = candidate.stat()
        entry = f"{candidate.name}\t{stat.st_size}\t{stat.st_mtime_ns}"
        entries.append(entry)
        digest.update((entry + "\n").encode())
    return {"input_files": entries, "identity_sha256": digest.hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--long-reads", required=True)
    ap.add_argument("--r1", required=True)
    ap.add_argument("--r2", required=True)
    ap.add_argument("--out-reference", required=True)
    ap.add_argument("--out-truth", required=True)
    ap.add_argument("--out-provenance", required=True)
    ap.add_argument("--min-chromosome-length", type=int, default=1_500_000)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    # Resolved explicitly (not left to subprocess.run's own bare-name lookup,
    # which -- unlike shutil.which() -- does not do a PATHEXT-style search on
    # Windows) -- matches annotate_reference.py's own shutil.which()-first
    # convention for locating an external tool before calling it.
    unicycler_path = shutil.which("unicycler")
    if not unicycler_path:
        sys.stderr.write("[build_hybrid_truth] unicycler is not installed (or not on PATH)\n")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="build_hybrid_truth_") as tmp:
        out_dir = Path(tmp) / "unicycler"
        command = [unicycler_path, "-1", args.r1, "-2", args.r2, "-l", args.long_reads,
                   "-o", str(out_dir), "-t", str(args.threads)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(f"[build_hybrid_truth] unicycler failed (exit {result.returncode}):\n{result.stderr[-4000:]}\n")
            sys.exit(1)
        assembly = out_dir / "assembly.fasta"
        if not assembly.is_file():
            sys.stderr.write("[build_hybrid_truth] unicycler reported success but wrote no assembly.fasta\n")
            sys.exit(1)

        records = read_fasta_records(assembly)
        if not records:
            sys.stderr.write("[build_hybrid_truth] assembly.fasta has no records\n")
            sys.exit(1)
        labels, chromosome_id, reason = classify_contigs(records, args.min_chromosome_length)
        if labels is None:
            sys.stderr.write(f"[build_hybrid_truth] REJECTED: {reason}\n")
            sys.exit(1)

        Path(args.out_reference).write_bytes(assembly.read_bytes())
        with open(args.out_truth, "w") as out:
            out.write("sequence_id\tmolecule_type\tlength\n")
            for _, seq_id, length in records:
                out.write(f"{seq_id}\t{labels[seq_id]}\t{length}\n")

        n_plasmid = sum(1 for value in labels.values() if value == "PLASMID")
        provenance = {
            "method": "self_assembled_hybrid",
            "assembler": "unicycler", "assembler_version": unicycler_version(unicycler_path),
            "command": command,
            "min_chromosome_length": args.min_chromosome_length,
            "chromosome_id": chromosome_id,
            "contigs": [{"sequence_id": seq_id, "length": length, "circular": CIRCULAR.search(header) is not None}
                        for header, seq_id, length in records],
            "input_reads": file_fingerprint([args.long_reads, args.r1, args.r2]),
        }
        Path(args.out_provenance).write_text(json.dumps(provenance, indent=2) + "\n")

        sys.stderr.write(
            f"[build_hybrid_truth] wrote {args.out_truth}: 1 chromosome ({chromosome_id}), "
            f"{n_plasmid} plasmid(s)\n"
        )


if __name__ == "__main__":
    main()
