#!/usr/bin/env python3
"""One-time build step for classify_operational_plasmid.py's small, curated
reference plasmid set -- NOT part of the per-sample pipeline, run once by a
maintainer (or re-run to refresh the curated list) whenever
cohorts/reference_plasmids/curated_accessions.tsv changes.

Downloads each curated accession's real sequence directly from NCBI's own
E-utilities (db=nuccore, efetch, rettype=fasta) -- the same direct-HTTPS
eutils convention validate_cohort.py/resolve_ncbi_accessions.py already use
(this script imports their own fetch()/request_interval() rather than
duplicating retry/backoff logic), so no new subprocess-tool dependency
(sra-tools' `efetch` CLI, `datasets`) is needed just to fetch a handful of
individual plasmid records.

Then builds:
  reference.fasta          -- every downloaded record, concatenated, header
                               unchanged (NCBI's own ">accession.version
                               description" -- mash's own per-record sketch
                               id, in --individual-sketch mode, is a
                               header's first whitespace-delimited token,
                               which is exactly the accession).
  reference.msh            -- `mash sketch -i` (matching
                               compute_difficulty_features.py's own
                               individual-sketch convention) over
                               reference.fasta: one sketch per accession.
  reference_metadata.tsv   -- accession, organism, plasmid_name, length_bp,
                               cluster_id, cluster_member_count.
  reference_set_provenance.json -- when this was built, from what input
                               list, and the real query used per accession.

Clustering is static single-linkage over the reference set's own all-vs-all
Mash distances (`mash dist reference.msh reference.msh`) at
--cluster-threshold, computed ONCE here -- not COPLA's live nested
Stochastic Block Model refit (graph-tool, a non-stdlib C++/Boost-linked
dependency PlasBench does not otherwise need). A singleton (no other
reference plasmid within threshold) is still its own one-member cluster; it
is classify_operational_plasmid.py's own --min-cluster-members gate, not
this script, that later decides whether a one-member cluster is enough to
call a query "known".

The curated INPUT accession list is committed (small, real provenance); the
downloaded sequences/sketch this script builds FROM it are real data, not
metadata -- same convention as PLATON_DB/GENOMAD_DB/PLASME_DB in
config/config.sh -- so --out-dir defaults to $DATA_DIR/db/plasmid_reference,
gitignored, not cohorts/.

Usage:
  build_plasmid_reference_set.py \\
      --accessions cohorts/reference_plasmids/curated_accessions.tsv \\
      --out-dir data/db/plasmid_reference \\
      --email you@example.org
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cohort import fetch, request_interval  # noqa: E402

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def read_curated_accessions(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t",
        ))


def fetch_fasta(accession, email, api_key):
    """The record's own real FASTA from NCBI nuccore, verbatim -- never
    reconstructed or guessed. Raises ValueError (via fetch()'s own retry
    exhaustion) rather than returning a placeholder on failure: a curated
    reference set with a silently-missing record is worse than a loud
    failure a maintainer notices immediately."""
    from urllib.parse import urlencode
    from urllib.request import Request
    params = {"db": "nuccore", "id": accession, "rettype": "fasta", "retmode": "text"}
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    request = Request(EFETCH + "?" + urlencode(params), headers={"User-Agent": "PlasBench/0.1 reference-set builder"})
    payload = fetch(request, timeout=60, retries=4, label=f"efetch {accession}")
    text = payload.decode("utf-8")
    if not text.startswith(">"):
        raise ValueError(f"efetch for {accession} did not return FASTA (got: {text[:200]!r})")
    return text if text.endswith("\n") else text + "\n"


def fasta_lengths(path):
    lengths, current_id, current_len = {}, None, 0
    with open(path) as handle:
        for line in handle:
            if line.startswith(">"):
                if current_id is not None:
                    lengths[current_id] = current_len
                current_id, current_len = line[1:].strip().split()[0], 0
            else:
                current_len += len(line.strip())
    if current_id is not None:
        lengths[current_id] = current_len
    return lengths


def all_vs_all_distances(mash, sketch_path, threads):
    result = subprocess.run([mash, "dist", "-p", str(threads), str(sketch_path), str(sketch_path)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"mash dist (all-vs-all) failed: {result.stderr[-500:]}")
    distances = []
    for line in result.stdout.strip().splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0] != fields[1]:
            distances.append((fields[0], fields[1], float(fields[2])))
    return distances


def single_linkage_clusters(accessions, distances, threshold):
    """Union-find over pairs within --cluster-threshold. Returns
    accession -> (cluster_id, cluster_member_count). cluster_id is the
    lexicographically smallest accession in the cluster -- deterministic
    and stable across rebuilds without a separate counter/ordering concern."""
    parent = {acc: acc for acc in accessions}

    def find(acc):
        while parent[acc] != acc:
            parent[acc] = parent[parent[acc]]
            acc = parent[acc]
        return acc

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for ref_id, query_id, distance in distances:
        if distance <= threshold and ref_id in parent and query_id in parent:
            union(ref_id, query_id)

    members = {}
    for acc in accessions:
        members.setdefault(find(acc), []).append(acc)
    return {acc: (root, len(members[root])) for root, group in members.items() for acc in group}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accessions", required=True,
                    help="Curated TSV: accession, organism, plasmid_name, description.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--cluster-threshold", type=float, default=0.05,
                    help="Mash distance for single-linkage clustering (default: 0.05, matching "
                         "classify_operational_plasmid.py's own default --similarity-threshold).")
    ap.add_argument("--sketch-size", type=int, default=10000,
                    help="Mash sketch size (default: 10000, matching compute_difficulty_features.py).")
    ap.add_argument("--email", default="", help="NCBI E-utilities contact email (recommended by NCBI, not required).")
    ap.add_argument("--api-key", default="", help="NCBI API key; raises the request-rate allowance.")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    mash = shutil.which("mash")
    if not mash:
        sys.exit("ERROR: mash is not installed (or not on PATH). This build step needs it; "
                 "classify_operational_plasmid.py's own runtime use tolerates its absence, but "
                 "building the reference set it depends on does not.")

    curated = read_curated_accessions(args.accessions)
    if not curated:
        sys.exit(f"ERROR: no rows in {args.accessions}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reference_fasta = out_dir / "reference.fasta"
    queries_used = {}

    with open(reference_fasta, "w", encoding="utf-8") as handle:
        for row in curated:
            accession = row["accession"]
            sys.stderr.write(f"[build_plasmid_reference_set] fetching {accession} ({row.get('organism', '')}) ...\n")
            query_url = f"{EFETCH}?db=nuccore&id={accession}&rettype=fasta&retmode=text"
            handle.write(fetch_fasta(accession, args.email, args.api_key))
            queries_used[accession] = query_url
            import time
            time.sleep(request_interval(args.api_key or None))

    lengths = fasta_lengths(reference_fasta)
    accessions = list(lengths)

    sketch_prefix = out_dir / "reference"
    sketch_result = subprocess.run(
        [mash, "sketch", "-i", "-s", str(args.sketch_size), "-p", str(args.threads),
         "-o", str(sketch_prefix), str(reference_fasta)],
        capture_output=True, text=True, timeout=300,
    )
    if sketch_result.returncode != 0:
        sys.exit(f"ERROR: mash sketch failed: {sketch_result.stderr[-1000:]}")
    reference_sketch = out_dir / "reference.msh"

    distances = all_vs_all_distances(mash, reference_sketch, args.threads)
    clusters = single_linkage_clusters(accessions, distances, args.cluster_threshold)

    metadata_by_accession = {row["accession"]: row for row in curated}
    metadata_path = out_dir / "reference_metadata.tsv"
    with open(metadata_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["accession", "organism", "plasmid_name", "length_bp", "cluster_id", "cluster_member_count"])
        for accession in accessions:
            curated_row = metadata_by_accession.get(accession, {})
            cluster_id, cluster_count = clusters.get(accession, (accession, 1))
            writer.writerow([accession, curated_row.get("organism", ""), curated_row.get("plasmid_name", ""),
                             lengths[accession], cluster_id, cluster_count])

    provenance = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": "NCBI E-utilities (db=nuccore, efetch, rettype=fasta)",
        "curated_accessions_file": str(args.accessions),
        "accession_count": len(accessions),
        "cluster_threshold": args.cluster_threshold,
        "sketch_size": args.sketch_size,
        "queries_used": queries_used,
    }
    (out_dir / "reference_set_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")

    cluster_count = len({root for root, _ in clusters.values()})
    print(f"Built reference set: {len(accessions)} plasmid(s) in {cluster_count} cluster(s) "
         f"-> {reference_sketch}, {metadata_path}")


if __name__ == "__main__":
    main()
