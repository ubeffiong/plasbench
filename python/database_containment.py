#!/usr/bin/env python3
"""
database_containment.py -- is each truth plasmid already inside a tool's own
reference database?

flag_database_overlap.py screens by DATE (truth released before the database
could be in it). This checks the SEQUENCE: each truth plasmid is aligned to the
database FASTA a tool actually uses (e.g. MOB-suite's
databases/ncbi_plasmid_full_seqs.fas), and counts as in the database when a
single record covers >= --min-coverage of it at >= --min-identity. A tool that
recovers in-database plasmids far better than novel ones is partly recognising,
not inferring; aggregate_results.py reports that gap per tool.

Databases are given as  --database TOOLS=FASTA  where TOOLS is a comma list of
the tools that use that database (one FASTA can serve several tools), e.g.
  --database mob_recon,flye_mob_recon,trycycler_mob_recon,gplas2_mob=/path/ncbi_plasmid_full_seqs.fas

Output TSV (one row per sample x truth plasmid x database):
  sample, sequence_id, length, tools, database, best_record, coverage,
  identity, in_database

Standard library only; minimap2 does the alignment.
"""

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from collections import defaultdict

FIELDS = ["sample", "sequence_id", "length", "tools", "database", "best_record", "coverage", "identity",
          "in_database"]


from plasbench_common import iter_fasta  # noqa: E402


def read_fasta(path, wanted=None):
    """name -> sequence (shared FASTA reader); only `wanted` names when given."""
    return {name: seq for name, _, seq in iter_fasta(path, wanted)}


def truth_plasmids(truth_path):
    with open(truth_path, newline="", encoding="utf-8") as handle:
        return [row["sequence_id"] for row in csv.DictReader(handle, delimiter="\t")
                if row.get("molecule_type", "").upper() == "PLASMID"]


def merged_length(intervals):
    total, end = 0, -1
    for start, stop in sorted(intervals):
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


def containment(query_fasta, database_fasta, threads):
    """query -> (best_record, coverage, identity) over alignments to each record."""
    result = subprocess.run(["minimap2", "-c", "-x", "asm5", "-t", str(threads), database_fasta, query_fasta],
                            text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    per_pair = defaultdict(lambda: {"q": [], "matches": 0, "block": 0, "qlen": 0})
    for line in result.stdout.splitlines():
        f = line.split("\t")
        if len(f) < 12:
            continue
        acc = per_pair[(f[0], f[5])]
        acc["q"].append((int(f[2]), int(f[3])))
        acc["matches"] += int(f[9])
        acc["block"] += int(f[10])
        acc["qlen"] = int(f[1])
    best = {}
    for (query, record), acc in per_pair.items():
        coverage = merged_length(acc["q"]) / acc["qlen"] if acc["qlen"] else 0.0
        identity = acc["matches"] / acc["block"] if acc["block"] else 0.0
        if query not in best or (coverage, identity) > best[query][1:]:
            best[query] = (record, coverage, identity)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True, help="DATA_DIR with <sample>/reference.fna and truth tables")
    ap.add_argument("--samples", nargs="+", required=True)
    ap.add_argument("--database", action="append", default=[], help="TOOLS=FASTA (repeatable)")
    ap.add_argument("--min-coverage", type=float, default=0.95)
    ap.add_argument("--min-identity", type=float, default=0.99)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    databases = []
    for spec in args.database:
        tools, _, path = spec.partition("=")
        if tools and path and os.path.isfile(path):
            databases.append((tools, path))
        else:
            sys.stderr.write(f"[database_containment] skipping unusable --database {spec!r}\n")
    # Gather every sample's truth plasmids into ONE query file, so each database is indexed and
    # aligned once instead of once per sample (a database such as MOB-suite's is gigabytes).
    queries = []                       # (synthetic id, sample, sequence id, length)
    rows = []
    with tempfile.TemporaryDirectory(prefix="plasbench_containment_") as tmp:
        query = os.path.join(tmp, "truth_plasmids.fa")
        with open(query, "w", encoding="utf-8") as handle:
            for sample in args.samples:
                sample_dir = os.path.join(args.data_dir, sample)
                # The truth file of the scored labelling scheme (TRUTH_LABEL_SCHEME;
                # python/label_schemes.py), falling back to truth.tsv.
                scheme_file = {"evidence": "truth.scored.tsv", "nonchromosomal": "truth.nonchromosomal.tsv"}.get(
                    os.environ.get("TRUTH_LABEL_SCHEME", "ncbi"), "truth.tsv")
                truth = os.path.join(sample_dir, scheme_file)
                if not os.path.isfile(truth):
                    truth = os.path.join(sample_dir, "truth.tsv")
                reference = os.path.join(sample_dir, "reference.fna")
                if not (os.path.isfile(truth) and os.path.isfile(reference)):
                    continue
                plasmids = set(truth_plasmids(truth))
                if not plasmids:
                    continue
                # Stream the reference and keep only the truth plasmids: the chromosome is
                # never held in memory (peak memory follows the plasmids, not the genome).
                sequences = read_fasta(reference, wanted=plasmids)
                for seq_id in sorted(plasmids):
                    if seq_id in sequences:
                        synthetic = f"q{len(queries)}"
                        handle.write(f">{synthetic}\n{sequences[seq_id]}\n")
                        queries.append((synthetic, sample, seq_id, len(sequences[seq_id])))
        if queries:
            for tools, path in databases:
                best = containment(query, path, args.threads)
                for synthetic, sample, seq_id, length in queries:
                    record, coverage, identity = best.get(synthetic, ("", 0.0, 0.0))
                    inside = coverage >= args.min_coverage and identity >= args.min_identity
                    rows.append({"sample": sample, "sequence_id": seq_id, "length": length,
                                 "tools": tools, "database": os.path.basename(path), "best_record": record,
                                 "coverage": f"{coverage:.4f}", "identity": f"{identity:.4f}",
                                 "in_database": "yes" if inside else "no"})
    rows.sort(key=lambda r: (r["sample"], r["sequence_id"], r["database"]))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    inside = sum(r["in_database"] == "yes" for r in rows)
    sys.stderr.write(f"[database_containment] {inside} of {len(rows)} truth plasmid x database pair(s) contained "
                     f"-> {args.out}\n")


if __name__ == "__main__":
    main()
