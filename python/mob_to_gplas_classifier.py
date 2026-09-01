#!/usr/bin/env python3
"""Convert MOB-recon plasmid membership into a validated gplas classifier TSV."""

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = ("Prob_Chromosome", "Prob_Plasmid", "Prediction", "Contig_name", "Contig_length")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def graph_nodes(path, minimum_length):
    nodes = {}
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            fields = line.rstrip("\n").split("\t")
            if not fields or fields[0] != "S":
                continue
            if len(fields) < 3 or not fields[1] or fields[2] == "*":
                raise ValueError(f"GFA line {line_number}: segment needs a name and sequence")
            if fields[1] in nodes:
                raise ValueError(f"GFA line {line_number}: duplicate segment name {fields[1]!r}")
            length = len(fields[2])
            if length >= minimum_length:
                nodes[fields[1]] = length
    if not nodes:
        raise ValueError(f"no GFA segments at least {minimum_length} bp")
    return nodes


def fasta_ids(path):
    identifiers = set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                identifier = line[1:].strip().split()[0]
                if not identifier:
                    raise ValueError(f"empty FASTA identifier in {path}")
                identifiers.add(identifier)
    return identifiers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, help="assembly GFA used by gplas")
    parser.add_argument("--mob-output", required=True, help="successful MOB-recon output directory")
    parser.add_argument("--out", required=True, help="gplas-compatible classifier TSV")
    parser.add_argument("--provenance", required=True, help="JSON evidence record written beside the classifier")
    parser.add_argument("--min-contig-length", type=int, default=1000, help="gplas extraction threshold (default: 1000)")
    args = parser.parse_args()
    if args.min_contig_length < 1:
        raise SystemExit("ERROR: --min-contig-length must be positive")
    graph = Path(args.graph)
    mob_output = Path(args.mob_output)
    plasmid_fastas = sorted(mob_output.glob("plasmid_*.fasta"))
    if not graph.is_file():
        raise SystemExit(f"ERROR: graph not found: {graph}")
    if not mob_output.is_dir():
        raise SystemExit(f"ERROR: MOB output directory not found: {mob_output}")
    nodes = graph_nodes(graph, args.min_contig_length)
    mob_ids = set().union(*(fasta_ids(path) for path in plasmid_fastas)) if plasmid_fastas else set()
    labelled = nodes.keys() & mob_ids
    # A non-empty MOB call with zero graph-node overlap means the graph and MOB
    # assembly are incompatible; refusing it prevents an all-chromosome fiction.
    if mob_ids and not labelled:
        raise SystemExit("ERROR: MOB plasmid FASTA identifiers do not match graph nodes; ensure both use the same assembly")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(REQUIRED) + "\n")
        for name in sorted(nodes):
            plasmid = name in labelled
            handle.write(f"{0.0 if plasmid else 1.0:.1f}\t{1.0 if plasmid else 0.0:.1f}\t"
                         f"{'Plasmid' if plasmid else 'Chromosome'}\t{name}\t{nodes[name]}\n")
    provenance = {
        "schema_version": "1.0", "method": "mob_recon_hard_label_transfer",
        "interpretation": "MOB-recon plasmid membership transferred as deterministic gplas seed labels; values are not calibrated probabilities.",
        "graph": {"path": str(graph), "sha256": sha256(graph), "eligible_nodes": len(nodes)},
        "mob_plasmid_fastas": [{"path": str(path), "sha256": sha256(path)} for path in plasmid_fastas],
        "mob_plasmid_record_count": len(mob_ids), "matched_graph_plasmid_nodes": len(labelled),
        "chromosome_labelled_nodes": len(nodes) - len(labelled), "minimum_contig_length": args.min_contig_length,
    }
    Path(args.provenance).write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote MOB-derived gplas classifier: {out} ({len(labelled)} plasmid-labelled / {len(nodes)} eligible nodes)")


if __name__ == "__main__":
    main()
