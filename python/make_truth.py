#!/usr/bin/env python3
"""
make_truth.py -- turn an NCBI 'sequence_report.jsonl' (from `datasets download
genome`) into the truth.tsv the scorer needs.

The sequence report has one JSON object per sequence in the assembly, with the
field `assigned_molecule_location_type` == "Chromosome" or "Plasmid" (and
sometimes "Mitochondrion", "Plastid", "Segment", "Unlocalized", etc., which are
not valid bacterial plasmid/chromosome labels).

We also need the FASTA sequence names to match what minimap2 will see. NCBI's
sequence report gives both `genbank_accession`/`refseq_accession` and, usually,
`chr_name`. The FASTA headers from `datasets` are the accession (e.g.
CP012345.1). We therefore key truth on the accession that the FASTA uses.

Usage:
  make_truth.py --report sequence_report.jsonl --fasta reference.fna --out truth.tsv
  make_truth.py ... --allow-default     # legacy behaviour, see below

We read the FASTA to get the exact sequence ids + lengths (authoritative), then
map each id to a molecule type using the report.

A FASTA id that cannot be resolved unambiguously is written as `REVIEW`, never
guessed. The reasons are: the id is absent from the report, the report gives it
no usable location type (missing, or something other than Plasmid/Chromosome),
or the report contradicts itself (the same accession, or the same version-less
accession, labelled both plasmid and chromosome). `REVIEW` is rejected by
validate_truth_table.py, so stage 2 stops until a person edits the table.
Guessing is not neutral: if a sequence defaulted to CHROMOSOME is really a
plasmid, every tool that correctly calls it plasmid is charged false-positive
bases (lowering precision), and its bases are missing from recall's
denominator.

`--allow-default` restores the old behaviour of writing CHROMOSOME for an
unresolved sequence (with a warning). Use it only after reviewing the sequences
listed in the warnings.

Resolution order: exact accession; then version-less accession; then `chr_name`
as a last resort (names such as "1" or "pFoo" are not unique identifiers, so
they are only used when no accession matches and only when unambiguous).

Standard library only.
"""

import argparse
import gzip
import json
import sys

REVIEW = "REVIEW"


from plasbench_common import open_maybe_gz  # noqa: E402,F401


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


def strip_version(accession):
    """CP000001.1 -> CP000001. Names without a dot are returned unchanged."""
    return accession.rsplit(".", 1)[0] if "." in accession else accession


class Report:
    """Lookup tables built from the sequence report.

    Each table maps a key to the SET of molecule types seen for it. A set with
    more than one member is a contradiction in the report and is never resolved
    by picking one.
    """

    def __init__(self):
        self.exact = {}      # accession as written -> {types}
        self.base = {}       # version-less accession -> {types}
        self.names = {}      # chr_name -> {types}
        self.unusable = {}   # any key -> location type text that is not Plasmid/Chromosome

    def add(self, table, key, mtype):
        table.setdefault(key, set()).add(mtype)

    def ingest(self, obj):
        raw = (obj.get("assigned_molecule_location_type")
               or obj.get("assignedMoleculeLocationType") or "")
        mol = str(raw).strip()
        lowered = mol.lower()
        if lowered == "plasmid":
            mtype = "PLASMID"
        elif lowered == "chromosome":
            mtype = "CHROMOSOME"
        else:
            mtype = None
        for key in ("genbank_accession", "refseq_accession",
                    "genbankAccession", "refseqAccession"):
            val = obj.get(key)
            if not val:
                continue
            if mtype is None:
                self.unusable[val] = mol or "(no location type)"
                self.unusable[strip_version(val)] = mol or "(no location type)"
                continue
            self.add(self.exact, val, mtype)
            self.add(self.base, strip_version(val), mtype)
        if mtype is not None:
            for key in ("chr_name", "chrName"):
                val = obj.get(key)
                if val:
                    self.add(self.names, val, mtype)


def read_report(path):
    """Parse JSONL (one object per line) or a JSON array/object into a Report."""
    report = Report()
    with open_maybe_gz(path) as fh:
        content = fh.read().strip()
    if not content:
        return report
    jsonl_ok = True
    parsed = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            jsonl_ok = False
            break
    if jsonl_ok:
        records = parsed
    else:
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("reports", data.get("sequences", [data]))
        records = data
    for obj in records:
        report.ingest(obj)
    return report


def resolve(seq_id, report):
    """Return (molecule_type, reason).

    molecule_type is PLASMID, CHROMOSOME or None. When None, reason says why, so
    the warning can tell the user what to fix rather than just that something
    failed.
    """
    for table, label in ((report.exact, "accession"),
                         (report.base, "version-less accession")):
        key = seq_id if table is report.exact else strip_version(seq_id)
        if key in table:
            types = table[key]
            if len(types) > 1:
                return None, f"the report labels this {label} both plasmid and chromosome"
            return next(iter(types)), ""
    if seq_id in report.unusable or strip_version(seq_id) in report.unusable:
        text = report.unusable.get(seq_id) or report.unusable.get(strip_version(seq_id))
        return None, f"the report's location type is '{text}', not Plasmid or Chromosome"
    if seq_id in report.names:
        types = report.names[seq_id]
        if len(types) > 1:
            return None, "the report labels this chr_name both plasmid and chromosome"
        return next(iter(types)), ""
    return None, "the id is not in the report"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True, help="sequence_report.jsonl")
    ap.add_argument("--fasta", required=True, help="reference FASTA (.fna/.fna.gz)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-default", action="store_true",
                    help="Write CHROMOSOME for sequences that cannot be resolved "
                         "(legacy behaviour). Default: write REVIEW, which stage 2 rejects.")
    args = ap.parse_args()

    fasta_ids = read_fasta_lengths(args.fasta)
    report = read_report(args.report)

    n_plasmid = n_chrom = n_unresolved = 0
    with open(args.out, "w") as out:
        out.write("sequence_id\tmolecule_type\tlength\n")
        for seq_id, length in fasta_ids:
            mtype, reason = resolve(seq_id, report)
            if mtype is None:
                n_unresolved += 1
                if args.allow_default:
                    mtype = "CHROMOSOME"
                    sys.stderr.write(
                        f"[make_truth] WARNING: '{seq_id}' ({length} bp): {reason}; "
                        f"defaulting to CHROMOSOME because --allow-default was given. "
                        f"If it is really a plasmid, correct plasmid calls on it "
                        f"will be scored as false positives.\n")
                else:
                    mtype = REVIEW
                    sys.stderr.write(
                        f"[make_truth] ERROR: '{seq_id}' ({length} bp) cannot be "
                        f"labelled: {reason}. Written as REVIEW.\n")
            if mtype == "PLASMID":
                n_plasmid += 1
            elif mtype == "CHROMOSOME":
                n_chrom += 1
            out.write(f"{seq_id}\t{mtype}\t{length}\n")

    sys.stderr.write(
        f"[make_truth] wrote {args.out}: {n_plasmid} plasmid, "
        f"{n_chrom} chromosome sequences ({n_unresolved} unresolved).\n"
    )
    if n_unresolved and not args.allow_default:
        sys.stderr.write(
            f"[make_truth] {n_unresolved} sequence(s) are marked REVIEW. Edit {args.out} "
            f"to PLASMID or CHROMOSOME after checking them; validate_truth_table.py "
            f"will refuse the table until you do.\n")
    if n_plasmid == 0 and n_unresolved == 0:
        sys.stderr.write(
            "[make_truth] NOTE: no plasmids found for this sample. Its "
            "precision/recall/F1 are undefined and it is left out of F1 "
            "ranking; it is scored as a negative control (isolate_specificity, "
            "chromosome_fp_bp). If plasmids were expected, check the report.\n"
        )


if __name__ == "__main__":
    main()
