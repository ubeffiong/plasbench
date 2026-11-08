#!/usr/bin/env python3
"""Nearest-reference screen for the OPERATIONAL (no-truth) path.

EXPERIMENTAL AND UNVALIDATED. This reports how close each predicted plasmid
record is, by Mash distance, to a small curated set of reference plasmids. It is
NOT a plasmid taxonomy, NOT a relatedness inference, and NOT a test of whether a
plasmid is biologically novel. Read "no_close_reference" as "nothing in this
16-plasmid reference set is close", which says almost nothing about the world.

It follows the pattern santirdnd/COPLA uses (distance to a reference network,
then a membership call) without COPLA's code or machinery: COPLA computes
alignment-based ANI and refits a nested Stochastic Block Model (`graph-tool`)
against a ~6,300-plasmid network. This script instead uses Mash against a small
PlasBench-curated set (accession list: `cohorts/reference_plasmids/
curated_accessions.tsv`; sequences and sketch built by
`build_plasmid_reference_set.py` into `data/db/plasmid_reference/`), with STATIC
single-linkage clusters. No threshold here is calibrated against any
independent partition of plasmids.

WHAT THE THRESHOLD MEANS (read before trusting a call)
Mash distance is D = -(1/k) ln(2j / (1 + j)), k = 21 by default, where j is the
Jaccard index of the two k-mer sets. It estimates a point-mutation rate between
sequences that are otherwise colinear. Plasmids violate that assumption: they
gain, lose and rearrange whole blocks. Consequences, exact for sequences whose
shared k-mers are identical:
  * Two equal-length plasmids that share a fraction s of their sequence have
    D = -ln(s)/21. s = 0.80 gives D = 0.011, s = 0.50 gives D = 0.033, and the
    default threshold 0.05 is reached at s = 0.35. So 0.05 is NOT "ANI >= 95%":
    a plasmid sharing about a third of a reference can pass it.
  * A contig that is an exact piece covering a fraction f of a reference plasmid
    has j = f, so D = -ln(2f/(1+f))/21. D <= 0.05 needs f >= 0.212. A short-read
    assembly splits plasmids into contigs, so a fragment of a plasmid that IS in
    the reference can fail the threshold and be reported as "no_close_reference".
  * Each record is judged on its own; nothing here groups records into plasmids.
These numbers describe direction and size of the effect, not a simulation.

CALLS (per query record)
  close_reference_match -- nearest-neighbour distance <= --similarity-threshold,
                     the hit is statistically supported (Mash p-value <=
                     --max-p-value), AND that reference's own cluster has >=
                     --min-cluster-members members (a lone one-member "cluster"
                     is too weak a basis for the label).
  no_close_reference -- anything else: the nearest reference is beyond the
                     threshold, unsupported, or its cluster is too small.
  insufficient_reference -- mash is not installed, the reference sketch/metadata
                     is missing, or mash returned nothing for the record. Never
                     guessed either way.
distance_margin is a transparent linear margin against the threshold, NOT a
probability and NOT calibrated:
  close_reference_match: 1 - (distance / threshold), clipped to [0, 1]
  no_close_reference:    min(1, (distance - threshold) / threshold)
It is not comparable across plasmids of different size.

Query and reference are sketched at the SAME size. The reference size is read
from `reference_set_provenance.json` next to the sketch (written by
build_plasmid_reference_set.py), or set with --sketch-size. Sketching the query
at Mash's default (1000) against a 10000-hash reference silently lowers the
resolution of every distance to the smaller sketch.

Usage:
  classify_operational_plasmid.py --query results/s1/pred_platon.plasmid.fasta \\
      --reference-sketch data/db/plasmid_reference/reference.msh \\
      --reference-metadata data/db/plasmid_reference/reference_metadata.tsv \\
      --sample-id s1 --out results/s1/plasmid_similarity.tsv
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Matches build_plasmid_reference_set.py's own default; used only when the
# reference's provenance file is absent and --sketch-size is not given.
DEFAULT_SKETCH_SIZE = 10000

HEADER = ["sample_id", "query_record_id", "best_reference_id", "best_reference_organism",
          "best_reference_plasmid_name", "mash_distance", "mash_p_value", "shared_hashes",
          "cluster_membership_status", "cluster_id", "cluster_member_count",
          "distance_margin", "notes"]

BLANK = {"best_reference_id": "", "best_reference_organism": "", "best_reference_plasmid_name": "",
         "mash_distance": "", "mash_p_value": "", "shared_hashes": "", "cluster_id": "",
         "cluster_member_count": "", "distance_margin": ""}


def read_reference_metadata(path):
    """accession -> {organism, plasmid_name, cluster_id, cluster_member_count}."""
    metadata = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            metadata[row["accession"]] = row
    return metadata


def reference_sketch_size(reference_sketch):
    """Sketch size the reference was built with, from its provenance file, else
    DEFAULT_SKETCH_SIZE. Never raises: a missing or unreadable provenance file
    just means the default is used."""
    provenance = Path(reference_sketch).with_name("reference_set_provenance.json")
    try:
        size = int(json.loads(provenance.read_text(encoding="utf-8"))["sketch_size"])
        return size if size > 0 else DEFAULT_SKETCH_SIZE
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SKETCH_SIZE


def read_fasta_ids(path):
    """Every record id (first whitespace-delimited token of each header),
    in file order -- what this query actually has to classify, independent
    of whatever mash reports (mash silently drops a record it cannot hash,
    e.g. one shorter than its k-mer size, so this is the ground truth for
    "what should have a row", not mash's own output)."""
    ids = []
    with open(path) as handle:
        for line in handle:
            if line.startswith(">"):
                ids.append(line[1:].strip().split()[0])
    return ids


def run_mash_dist(mash, reference_sketch, query_fasta, tmp_dir, threads, sketch_size=DEFAULT_SKETCH_SIZE):
    """Sketch every query record individually (-i) at sketch_size and return
    mash dist's raw (ref_id, query_id, distance, p_value, shared_hashes) rows
    against the prebuilt reference sketch. Returns None on any failure (missing
    tool/files, non-zero exit, empty output) -- never a fabricated
    empty-but-successful result."""
    query_sketch = Path(tmp_dir) / "query.msh"
    try:
        sketch = subprocess.run([mash, "sketch", "-i", "-s", str(sketch_size), "-p", str(threads),
                                 "-o", str(query_sketch)[:-4], str(query_fasta)],
                                capture_output=True, timeout=300)
        if sketch.returncode != 0 or not query_sketch.is_file():
            return None
        result = subprocess.run([mash, "dist", "-p", str(threads), str(reference_sketch), str(query_sketch)],
                                capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        rows = []
        for line in result.stdout.strip().splitlines():
            fields = line.split("\t")
            if len(fields) < 3:
                continue
            p_value = float(fields[3]) if len(fields) > 3 and fields[3] else None
            shared = fields[4] if len(fields) > 4 else ""
            rows.append((fields[0], fields[1], float(fields[2]), p_value, shared))
        return rows
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def classify(query_ids, dist_rows, reference_metadata, threshold, min_cluster_members, max_p_value=1.0):
    """query_record_id -> classification dict (see HEADER, minus sample_id).

    dist_rows holds (ref_id, query_id, distance) or, as run_mash_dist returns,
    (ref_id, query_id, distance, p_value, shared_hashes). A query id absent from
    dist_rows (mash dropped it, or mash never ran) still gets a row --
    'insufficient_reference', never silently omitted."""
    by_query = {}
    if dist_rows:
        for row in dist_rows:
            ref_id, query_id, distance = row[0], row[1], row[2]
            p_value = row[3] if len(row) > 3 else None
            shared = row[4] if len(row) > 4 else ""
            if query_id not in by_query or distance < by_query[query_id][1]:
                by_query[query_id] = (ref_id, distance, p_value, shared)

    results = {}
    for query_id in query_ids:
        if query_id not in by_query:
            results[query_id] = dict(
                BLANK, cluster_membership_status="insufficient_reference",
                notes="mash produced no distance for this record (tool unavailable, or record too short to sketch).")
            continue
        ref_id, distance, p_value, shared = by_query[query_id]
        ref_meta = reference_metadata.get(ref_id, {})
        cluster_id = ref_meta.get("cluster_id", "")
        cluster_size = int(ref_meta["cluster_member_count"]) if ref_meta.get("cluster_member_count", "").isdigit() else 0
        supported = p_value is None or p_value <= max_p_value
        is_close = distance <= threshold and cluster_size >= min_cluster_members and supported
        if is_close:
            margin = max(0.0, 1.0 - (distance / threshold)) if threshold > 0 else 0.0
            status = "close_reference_match"
            note = (f"Nearest reference is within the Mash threshold and its cluster has {cluster_size} "
                    f"member(s). Not a taxonomy or a relatedness claim.")
        else:
            margin = min(1.0, (distance - threshold) / threshold) if threshold > 0 else 1.0
            if distance > threshold:
                reason = "beyond the Mash threshold"
            elif not supported:
                reason = f"within the threshold but not statistically supported (Mash p-value {p_value:g})"
            else:
                reason = f"within the threshold but its cluster is too small ({cluster_size} member(s))"
            status = "no_close_reference"
            note = (f"Nearest reference is {reason}. This means nothing in the small reference set is close; "
                    f"it is not evidence that the plasmid is novel (a fragment of a reference plasmid can also land here).")
        results[query_id] = {
            "best_reference_id": ref_id, "best_reference_organism": ref_meta.get("organism", ""),
            "best_reference_plasmid_name": ref_meta.get("plasmid_name", ""),
            "mash_distance": f"{distance:.6f}",
            "mash_p_value": "" if p_value is None else f"{p_value:g}", "shared_hashes": shared,
            "cluster_membership_status": status,
            "cluster_id": cluster_id, "cluster_member_count": ref_meta.get("cluster_member_count", ""),
            "distance_margin": f"{margin:.4f}", "notes": note,
        }
    return results


def write_header_only(out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="Candidate plasmid FASTA (may have multiple records).")
    ap.add_argument("--reference-sketch", required=True, help="Prebuilt reference.msh from build_plasmid_reference_set.py.")
    ap.add_argument("--reference-metadata", required=True, help="Prebuilt reference_metadata.tsv from build_plasmid_reference_set.py.")
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--similarity-threshold", type=float, default=0.05,
                    help="Max Mash distance for a close reference match (default: 0.05). NOT 'ANI >= 95%%': "
                         "see this script's docstring for what the number means for plasmids.")
    ap.add_argument("--min-cluster-members", type=int, default=2,
                    help="Minimum reference-cluster size for a close match (default: 2).")
    ap.add_argument("--max-p-value", type=float, default=1e-3,
                    help="Largest Mash p-value for a hit to count as supported (default: 0.001).")
    ap.add_argument("--sketch-size", type=int, default=None,
                    help="Mash sketch size for the query. Default: the size recorded in the reference's "
                         "reference_set_provenance.json, else 10000. It must match the reference.")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()

    if not Path(args.query).is_file() or Path(args.query).stat().st_size == 0:
        sys.stderr.write(f"[classify_operational_plasmid] {args.query} is empty or missing; no rows written\n")
        write_header_only(args.out)
        return

    mash = shutil.which("mash")
    if not mash:
        sys.stderr.write("[classify_operational_plasmid] mash is not installed (or not on PATH); no classification performed\n")
        query_ids = read_fasta_ids(args.query)
        rows = classify(query_ids, None, {}, args.similarity_threshold, args.min_cluster_members, args.max_p_value)
    elif not Path(args.reference_sketch).is_file() or not Path(args.reference_metadata).is_file():
        sys.stderr.write(f"[classify_operational_plasmid] reference sketch/metadata not found "
                         f"({args.reference_sketch}, {args.reference_metadata}); no classification performed\n")
        query_ids = read_fasta_ids(args.query)
        rows = classify(query_ids, None, {}, args.similarity_threshold, args.min_cluster_members, args.max_p_value)
    else:
        query_ids = read_fasta_ids(args.query)
        reference_metadata = read_reference_metadata(args.reference_metadata)
        sketch_size = args.sketch_size or reference_sketch_size(args.reference_sketch)
        with tempfile.TemporaryDirectory(prefix="classify_operational_plasmid_") as tmp:
            dist_rows = run_mash_dist(mash, args.reference_sketch, args.query, tmp, args.threads, sketch_size)
        rows = classify(query_ids, dist_rows, reference_metadata, args.similarity_threshold,
                        args.min_cluster_members, args.max_p_value)

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for query_id, fields in rows.items():
            writer.writerow([args.sample_id, query_id] + [fields[key] for key in HEADER[2:]])

    statuses = ", ".join(f"{qid}={fields['cluster_membership_status']}" for qid, fields in rows.items())
    sys.stderr.write(f"[classify_operational_plasmid] wrote {args.out} for {args.sample_id} ({statuses or 'no records'})\n")


if __name__ == "__main__":
    main()
