#!/usr/bin/env python3
"""
make_truth.py -- turn an NCBI 'sequence_report.jsonl' (from `datasets download
genome`) into the truth.tsv the scorer needs.

The sequence report has one JSON object per sequence in the assembly, with the
field `assigned_molecule_location_type` == "Chromosome" or "Plasmid" (and
sometimes "Mitochondrion", "Plastid", etc. which we ignore for bacteria).

We also need the FASTA sequence names to match what minimap2 will see. NCBI's
sequence report gives both `genbank_accession`/`refseq_accession` and, usually,
`chr_name`. The FASTA headers from `datasets` are the accession (e.g.
CP012345.1). We therefore key truth on the accession that the FASTA uses.

Usage:
  make_truth.py --report sequence_report.jsonl --fasta reference.fna --out truth.tsv

We read the FASTA to get the exact sequence ids + lengths (authoritative), then
map each id to a molecule type using the report. Any FASTA id not resolvable
from the report defaults to CHROMOSOME with a warning (safe: it will only ever
create false negatives if it was really a plasmid, which the log flags).

Standard library only.
"""

import argparse
import gzip
import json
import sys


def open_maybe_gz(path, mode="rt"):
    return gzip.open(path, mode) if path.endswith(".gz") else open(path, mode)


def read_fasta_lengths(path):
    """Return list of (seq_id, length) preserving order. seq_id = first token."""
    ids = []
    seq_id = None
    length = 0
    with open_maybe_gz(path) as fh:
        for line in fh:
            if line.startswith(">"):
                if seq_id is not None:
                    ids.append((seq_id, length))
                seq_id = line[1:].strip().split()[0]
                length = 0
            else:
                length += len(line.strip())
        if seq_id is not None:
            ids.append((seq_id, length))
    return ids


def read_report(path):
    """
    Build a lookup from any known accession -> molecule type.
    Handles both JSONL (one object per line) and a JSON array.
    """
    acc2type = {}

    def ingest(obj):
        mol = (obj.get("assigned_molecule_location_type")
               or obj.get("assignedMoleculeLocationType") or "").strip()
        mtype = "PLASMID" if mol.lower() == "plasmid" else \
                ("CHROMOSOME" if mol.lower() == "chromosome" else None)
        if mtype is None:
            return
        for key in ("genbank_accession", "refseq_accession",
                    "genbankAccession", "refseqAccession", "chr_name", "chrName"):
            val = obj.get(key)
            if val:
                acc2type[val] = mtype

    with open_maybe_gz(path) as fh:
        content = fh.read().strip()
    if not content:
        return acc2type
    # Try JSONL first.
    jsonl_ok = True
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ingest(json.loads(line))
        except json.JSONDecodeError:
            jsonl_ok = False
            break
    if not jsonl_ok:
        # Fall back to a single JSON array/object.
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("reports", data.get("sequences", [data]))
        for obj in data:
            ingest(obj)
    return acc2type


def resolve(seq_id, acc2type):
    """Try exact match, then version-stripped match."""
    if seq_id in acc2type:
        return acc2type[seq_id]
    base = seq_id.rsplit(".", 1)[0]
    for k, v in acc2type.items():
        if k == base or k.rsplit(".", 1)[0] == base:
            return v
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="sequence_report.jsonl")
    ap.add_argument("--fasta", required=True, help="reference FASTA (.fna/.fna.gz)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fasta_ids = read_fasta_lengths(args.fasta)
    acc2type = read_report(args.report)

    n_plasmid = n_chrom = n_default = 0
    with open(args.out, "w") as out:
        out.write("sequence_id\tmolecule_type\tlength\n")
        for seq_id, length in fasta_ids:
            mtype = resolve(seq_id, acc2type)
            if mtype is None:
                mtype = "CHROMOSOME"
                n_default += 1
                sys.stderr.write(
                    f"[make_truth] WARNING: '{seq_id}' not found in report; "
                    f"defaulting to CHROMOSOME.\n"
                )
            if mtype == "PLASMID":
                n_plasmid += 1
            else:
                n_chrom += 1
            out.write(f"{seq_id}\t{mtype}\t{length}\n")

    sys.stderr.write(
        f"[make_truth] wrote {args.out}: {n_plasmid} plasmid, "
        f"{n_chrom} chromosome sequences ({n_default} defaulted).\n"
    )
    if n_plasmid == 0:
        sys.stderr.write(
            "[make_truth] WARNING: no plasmids found for this sample. "
            "It will contribute only to precision, not recall. Consider "
            "excluding plasmid-free isolates from the benchmark.\n"
        )


if __name__ == "__main__":
    main()
