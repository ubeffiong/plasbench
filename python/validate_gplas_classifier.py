#!/usr/bin/env python3
"""Validate a gplas classifier TSV against the exact eligible GFA nodes."""

import argparse
import csv
from pathlib import Path


REQUIRED = ("Prob_Chromosome", "Prob_Plasmid", "Prediction", "Contig_name", "Contig_length")


def nodes(path, minimum):
    result = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split("\t")
        if not fields or fields[0] != "S":
            continue
        if len(fields) < 3 or not fields[1] or fields[2] == "*":
            raise ValueError(f"GFA line {number}: segment needs a name and sequence")
        if fields[1] in result:
            raise ValueError(f"GFA line {number}: duplicate segment name {fields[1]!r}")
        if len(fields[2]) >= minimum:
            result[fields[1]] = len(fields[2])
    if not result:
        raise ValueError(f"no GFA segments at least {minimum} bp")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--classifier", required=True)
    parser.add_argument("--min-contig-length", type=int, default=1000)
    args = parser.parse_args()
    if args.min_contig_length < 1:
        raise SystemExit("ERROR: --min-contig-length must be positive")
    try:
        graph_nodes = nodes(args.graph, args.min_contig_length)
        with open(args.classifier, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not reader.fieldnames or any(name not in reader.fieldnames for name in REQUIRED):
                raise ValueError("classifier must contain exactly named columns: " + ", ".join(REQUIRED))
            rows = list(reader)
        seen = set()
        for number, row in enumerate(rows, 2):
            name = row["Contig_name"]
            if name in seen: raise ValueError(f"classifier row {number}: duplicate Contig_name {name!r}")
            seen.add(name)
            if name not in graph_nodes: raise ValueError(f"classifier row {number}: node {name!r} is not an eligible graph segment")
            if int(row["Contig_length"]) != graph_nodes[name]: raise ValueError(f"classifier row {number}: Contig_length disagrees with graph for {name!r}")
            chromosome, plasmid = float(row["Prob_Chromosome"]), float(row["Prob_Plasmid"])
            if not (0 <= chromosome <= 1 and 0 <= plasmid <= 1): raise ValueError(f"classifier row {number}: probabilities must lie in [0, 1]")
            if row["Prediction"] not in ("Plasmid", "Chromosome"): raise ValueError(f"classifier row {number}: Prediction must be Plasmid or Chromosome")
        missing = sorted(set(graph_nodes) - seen)
        if missing: raise ValueError(f"classifier omits {len(missing)} eligible graph node(s), e.g. {missing[0]!r}")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: invalid gplas classifier: {exc}")
    print(f"Validated gplas classifier: {args.classifier} ({len(rows)} graph nodes)")


if __name__ == "__main__":
    main()
