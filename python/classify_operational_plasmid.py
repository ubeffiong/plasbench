#!/usr/bin/env python3
"""Novel-vs-known plasmid classification for the OPERATIONAL (no-truth) path.

Reimplements, independently and in PlasBench's own stdlib-only + subprocess
style, the *pattern* santirdnd/COPLA uses (ANI to a reference plasmid
network, then a known-cluster-or-novel call with a confidence score) --
never its code, and not its specific machinery: COPLA computes ANI via its
own `ani.rb`/FastANI wrapper and refits a live nested Stochastic Block Model
(`graph-tool`, a non-stdlib C++/Boost-linked dependency) against a ~6,300-
plasmid external reference network of unstated data license. This script
instead reuses Mash (already a direct PlasBench dependency -- see
`compute_difficulty_features.py`'s own `mash sketch`/`mash dist` convention,
duplicated here rather than imported since the two scripts' sketching shapes
differ) against a small, PlasBench-curated reference set (curated accession
list: `cohorts/reference_plasmids/curated_accessions.tsv`; the actual
downloaded sequences/sketch built from it: `data/db/plasmid_reference/`,
gitignored like every other tool database -- see config/config.sh), with
STATIC clusters precomputed once by `build_plasmid_reference_set.py` -- no
live graph refit, no new non-stdlib dependency.

This is explicitly an OPERATIONAL-mode signal, not a benchmark metric: it
answers "how similar is this isolate's own reconstructed plasmid to a small
set of known reference plasmids", which is a real signal only when there is
NO truth reference to score against directly. It must never be computed
against, or leak into, `recommendation_model.py`'s training features --
those are fit from BENCHMARK isolates that DO have truth, and this script's
whole reason to exist is the opposite situation.

Mash distance is a proxy for ANI (Ondov et al. 2016: for closely related
sequences, ~(1 - mash_distance) approximates ANI), not a claim of exact
equivalence to COPLA's own alignment-based ANI. The default
--similarity-threshold (0.05, roughly ANI >= 95%) is a PlasBench-chosen,
documented starting point -- NOT a reproduction of COPLA's own calibrated
0.90 partition-overlap threshold, which is specific to COPLA's own score
definition and ~6,300-plasmid RefSeq84/200 reference and does not transfer.

Each query FASTA record (a candidate plasmid contig) is classified
independently against every reference plasmid's own individual Mash sketch
(the reference sketch file is built with `mash sketch -i`, one sketch per
reference record, by build_plasmid_reference_set.py): the reference with the
MINIMUM Mash distance is this query record's nearest neighbor. The call is:
  known_cluster  -- nearest-neighbor distance <= --similarity-threshold AND
                     that reference's own cluster has >= --min-cluster-members
                     members (a lone reference "cluster" of 1 is too weak a
                     basis to call anything "known" rather than "novel but
                     nearest to this specific plasmid").
  novel          -- nearest-neighbor distance > --similarity-threshold (or
                     the nearest cluster is below --min-cluster-members).
  insufficient_reference -- mash is not installed, or the reference sketch/
                     metadata is missing -- never guessed as novel or known.
confidence_score is a simple, transparent, PlasBench-native margin against
the threshold (not COPLA's partition-overlap score, which has no meaning
outside COPLA's own SBM):
  known:  1 - (distance / threshold), clipped to [0, 1] -- 1.0 at distance 0,
          approaching 0 as distance approaches the threshold.
  novel:  min(1, (distance - threshold) / threshold) -- 0.0 at the threshold,
          approaching/exceeding 1 the farther past it the distance is.

Usage:
  classify_operational_plasmid.py --query results/s1/pred_platon.plasmid.fasta \\
      --reference-sketch data/db/plasmid_reference/reference.msh \\
      --reference-metadata data/db/plasmid_reference/reference_metadata.tsv \\
      --sample-id s1 --out results/s1/plasmid_similarity.tsv
"""

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HEADER = ["sample_id", "query_record_id", "best_reference_id", "best_reference_organism",
          "best_reference_plasmid_name", "mash_distance", "cluster_membership_status",
          "cluster_id", "cluster_member_count", "confidence_score", "notes"]


def read_reference_metadata(path):
    """accession -> {organism, plasmid_name, cluster_id, cluster_member_count}."""
    metadata = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            metadata[row["accession"]] = row
    return metadata


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


def run_mash_dist(mash, reference_sketch, query_fasta, tmp_dir, threads):
    """Sketch every query record individually (-i, matching
    compute_difficulty_features.py's own convention) and return mash dist's
    raw (ref_id, query_id, distance) rows against the prebuilt reference
    sketch. Returns None on any failure (missing tool/files, non-zero exit,
    empty output) -- never a fabricated empty-but-successful result."""
    query_sketch = Path(tmp_dir) / "query.msh"
    try:
        sketch = subprocess.run([mash, "sketch", "-i", "-p", str(threads), "-o", str(query_sketch)[:-4], str(query_fasta)],
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
            rows.append((fields[0], fields[1], float(fields[2])))
        return rows
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def classify(query_ids, dist_rows, reference_metadata, threshold, min_cluster_members):
    """query_record_id -> classification dict (see HEADER, minus sample_id).
    A query id absent from dist_rows (mash dropped it, or mash never ran)
    still gets a row -- 'insufficient_reference', never silently omitted."""
    by_query = {}
    if dist_rows:
        for ref_id, query_id, distance in dist_rows:
            if query_id not in by_query or distance < by_query[query_id][1]:
                by_query[query_id] = (ref_id, distance)

    results = {}
    for query_id in query_ids:
        if query_id not in by_query:
            results[query_id] = {
                "best_reference_id": "", "best_reference_organism": "", "best_reference_plasmid_name": "",
                "mash_distance": "", "cluster_membership_status": "insufficient_reference",
                "cluster_id": "", "cluster_member_count": "", "confidence_score": "",
                "notes": "mash produced no distance for this record (tool unavailable, or record too short to sketch).",
            }
            continue
        ref_id, distance = by_query[query_id]
        ref_meta = reference_metadata.get(ref_id, {})
        cluster_id = ref_meta.get("cluster_id", "")
        cluster_size = int(ref_meta["cluster_member_count"]) if ref_meta.get("cluster_member_count", "").isdigit() else 0
        is_known = distance <= threshold and cluster_size >= min_cluster_members
        if is_known:
            confidence = max(0.0, 1.0 - (distance / threshold)) if threshold > 0 else 0.0
            status, note = "known_cluster", f"Nearest reference within threshold, cluster has {cluster_size} member(s)."
        else:
            confidence = min(1.0, (distance - threshold) / threshold) if threshold > 0 else 1.0
            reason = "beyond the similarity threshold" if distance > threshold else f"nearest cluster too small ({cluster_size} member(s))"
            status, note = "novel", f"Nearest reference is {reason}; treated as a putative novel plasmid, not an error."
        results[query_id] = {
            "best_reference_id": ref_id, "best_reference_organism": ref_meta.get("organism", ""),
            "best_reference_plasmid_name": ref_meta.get("plasmid_name", ""),
            "mash_distance": f"{distance:.6f}", "cluster_membership_status": status,
            "cluster_id": cluster_id, "cluster_member_count": ref_meta.get("cluster_member_count", ""),
            "confidence_score": f"{confidence:.4f}", "notes": note,
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
                    help="Max Mash distance to call a nearest reference 'known' (default: 0.05, roughly ANI >= 95%%).")
    ap.add_argument("--min-cluster-members", type=int, default=2,
                    help="Minimum reference-cluster size to call a match 'known' rather than 'novel' (default: 2).")
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
        rows = classify(query_ids, None, {}, args.similarity_threshold, args.min_cluster_members)
    elif not Path(args.reference_sketch).is_file() or not Path(args.reference_metadata).is_file():
        sys.stderr.write(f"[classify_operational_plasmid] reference sketch/metadata not found "
                         f"({args.reference_sketch}, {args.reference_metadata}); no classification performed\n")
        query_ids = read_fasta_ids(args.query)
        rows = classify(query_ids, None, {}, args.similarity_threshold, args.min_cluster_members)
    else:
        query_ids = read_fasta_ids(args.query)
        reference_metadata = read_reference_metadata(args.reference_metadata)
        with tempfile.TemporaryDirectory(prefix="classify_operational_plasmid_") as tmp:
            dist_rows = run_mash_dist(mash, args.reference_sketch, args.query, tmp, args.threads)
        rows = classify(query_ids, dist_rows, reference_metadata, args.similarity_threshold, args.min_cluster_members)

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for query_id, fields in rows.items():
            writer.writerow([args.sample_id, query_id] + [fields[key] for key in HEADER[2:]])

    statuses = ", ".join(f"{qid}={fields['cluster_membership_status']}" for qid, fields in rows.items())
    sys.stderr.write(f"[classify_operational_plasmid] wrote {args.out} for {args.sample_id} ({statuses or 'no records'})\n")


if __name__ == "__main__":
    main()
