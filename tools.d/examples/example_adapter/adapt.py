#!/usr/bin/env python3
"""Example adapter: JSON {"plasmids": [{"id": "p1", "contigs": ["c1", "c2"]}, ...]} -> PlasBench's native files.

Writes <out>.plasmid.fasta (the predicted plasmid contigs) and, beside it, .bins.tsv (bin_id<TAB>sequence_id).
Exits non-zero if the output does not belong to this assembly; PlasBench then records the sample as skipped.
"""
import json
import sys

output, contigs, out_fasta = sys.argv[1:4]
seqs, name = {}, None
with open(contigs, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line.startswith(">"):
            name = line[1:].split()[0]
            seqs[name] = []
        elif name:
            seqs[name].append(line)
with open(output, encoding="utf-8") as handle:
    plasmids = json.load(handle)["plasmids"]
unknown = [c for p in plasmids for c in p["contigs"] if c not in seqs]
if unknown:
    sys.exit(f"contigs not in this assembly: {unknown}")
stem = out_fasta[: -len(".plasmid.fasta")]
with open(out_fasta, "w", encoding="utf-8") as fasta, open(stem + ".bins.tsv", "w", encoding="utf-8") as bins:
    bins.write("bin_id\tsequence_id\n")
    for plasmid in plasmids:
        for contig in plasmid["contigs"]:
            fasta.write(">" + contig + "\n" + "".join(seqs[contig]) + "\n")
            bins.write(plasmid["id"] + "\t" + contig + "\n")
