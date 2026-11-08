#!/usr/bin/env python3
"""
label_truth_evidence.py -- confirm each truth replicon's plasmid/chromosome
label with biological evidence instead of trusting a source label or size.

Source labels (the NCBI sequence report, or PlasBench's self-built hybrid
truth, which labels by circularity and length) mislabel chromids and
secondary chromosomes, megaplasmids, phage-plasmids and leftover fragments.
The rules (docs/METHODS.md, "Reference standard"):

  CHROMOSOME  source label CHROMOSOME, and -- when rRNA calling ran -- carries
              rRNA genes, or is the largest replicon with no plasmid marker.
  PLASMID     source label PLASMID, at least one plasmid marker (replicon/Inc
              type, MOB relaxase, or a match to the plasmid reference sketch),
              no rRNA genes, and -- when long reads were supplied -- long-read
              support.
  AMBIGUOUS   conflicting or missing evidence: a plasmid-labelled replicon
              with rRNA, a secondary chromosome without rRNA or with plasmid
              markers (chromid-like), a plasmid with no marker at all, or a
              plasmid seen only in short reads.

AMBIGUOUS replicons are excluded from scoring: they are left out of
truth.scored.tsv, so predictions on them are neither credited nor penalised
(score_plasmids.py reports them as off_truth_pred_bp). truth.tsv itself is
never modified (the truth validator requires every sequence to be labelled).
When the marker callers did not run, labels are kept as the source labels
and every row says evidence_status=not_evaluated -- missing evidence is never
read as absent evidence.

Caveat recorded in the output: plasmid markers come from the same kind of
databases many tools use, so marker-free plasmids are under-represented in
the scored truth. `marker_free` counts them for a separate stratum.

Standard library only (mash is called when available).
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys

FIELDS = ["sequence_id", "length", "source_label", "final_label", "evidence_status", "plasmid_markers",
          "plasmid_reference_match", "rrna_genes", "long_read_depth", "marker_free", "reason"]


def read_truth(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if row.get("sequence_id")]


def read_features(path):
    markers, rrna = {}, {}
    if not path or not os.path.isfile(path):
        return markers, rrna
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            seq = row.get("sequence_id", "")
            kind = row.get("feature_type", "")
            if kind in ("replicon", "mob"):
                markers.setdefault(seq, set()).add(f"{kind}:{row.get('label', '')}")
            elif kind == "rRNA":
                rrna[seq] = rrna.get(seq, 0) + 1
    return markers, rrna


def caller_status(path):
    """Which evidence classes actually ran (annotation_provenance.json)."""
    status = {"markers": False, "rrna": False}
    if not path or not os.path.isfile(path):
        return status
    with open(path, encoding="utf-8") as handle:
        callers = (json.load(handle) or {}).get("callers", {})
    ok = {name for name, record in callers.items() if (record or {}).get("status") == "ok"}
    status["markers"] = bool(ok & {"mob_typer", "abricate_replicon"})
    status["rrna"] = "barrnap" in ok
    return status


def plasmid_reference_matches(reference, sketch, max_distance):
    """Sequences within max_distance (Mash) of any plasmid in the reference sketch."""
    if not sketch or not os.path.isfile(sketch) or not shutil.which("mash"):
        return None
    try:
        result = subprocess.run(["mash", "dist", "-i", "-d", str(max_distance), sketch, reference],
                                text=True, capture_output=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    hits = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            hits.add(fields[1].split()[0])
    return hits


def read_long_read_depth(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sequence_id"]: float(row["mean_depth"]) for row in csv.DictReader(handle, delimiter="\t")}


def label(row, largest, markers, rrna, status, reference_hits, depth, min_depth):
    seq, source = row["sequence_id"], row["molecule_type"].strip().upper()
    found = sorted(markers.get(seq, set()))
    reference_match = reference_hits is not None and seq in reference_hits
    marker_present = bool(found) or reference_match
    rrna_count = rrna.get(seq, 0)
    lr_depth = depth.get(seq) if depth is not None else None
    record = {"sequence_id": seq, "length": row.get("length", ""), "source_label": source,
              "plasmid_markers": ",".join(found), "rrna_genes": rrna_count if status["rrna"] else "",
              "plasmid_reference_match": ("yes" if reference_match else "no") if reference_hits is not None else "",
              "long_read_depth": f"{lr_depth:.1f}" if lr_depth is not None else "",
              "marker_free": "", "evidence_status": "evaluated" if status["markers"] else "not_evaluated"}
    if not status["markers"]:
        return {**record, "final_label": source, "reason": "evidence not evaluated; source label kept"}
    if source == "CHROMOSOME":
        if status["rrna"] and rrna_count == 0 and (marker_present or seq != largest):
            why = "plasmid marker" if marker_present else "secondary replicon"
            return {**record, "final_label": "AMBIGUOUS",
                    "reason": f"chromosome-labelled {why} without rRNA genes (chromid-like)"}
        if not status["rrna"] and marker_present and seq != largest:
            return {**record, "final_label": "AMBIGUOUS",
                    "reason": "secondary chromosome-labelled replicon carries plasmid markers"}
        return {**record, "final_label": "CHROMOSOME",
                "reason": "rRNA genes present" if status["rrna"] and rrna_count else "source label, consistent evidence"}
    # PLASMID
    if status["rrna"] and rrna_count > 0:
        return {**record, "final_label": "AMBIGUOUS", "reason": "plasmid-labelled replicon carries rRNA genes"}
    if not marker_present:
        return {**record, "final_label": "AMBIGUOUS", "marker_free": "yes",
                "reason": "no plasmid marker (replicon, relaxase or plasmid-reference match)"}
    if lr_depth is not None and lr_depth < min_depth:
        return {**record, "final_label": "AMBIGUOUS", "marker_free": "no",
                "reason": f"long-read depth {lr_depth:.1f}x below {min_depth}x: short-read-only evidence"}
    return {**record, "final_label": "PLASMID", "marker_free": "no", "reason": "plasmid marker present"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True, help="validated source-labelled truth.tsv")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--features", help="annotate_reference.py feature TSV")
    ap.add_argument("--annotation-provenance", help="annotate_reference.py provenance JSON")
    ap.add_argument("--plasmid-sketch", help="Mash sketch of reference plasmids (PLSDB-like)")
    ap.add_argument("--plasmid-max-distance", type=float, default=0.05)
    ap.add_argument("--long-read-depth", help="long_read_support.py TSV (sequence_id, mean_depth)")
    ap.add_argument("--min-long-read-depth", type=float, default=5.0)
    ap.add_argument("--multimers", help="detect_dimers.py truth.corrections.tsv; flagged dimers become AMBIGUOUS")
    ap.add_argument("--labels-out", required=True)
    ap.add_argument("--scored-truth-out", required=True)
    args = ap.parse_args()

    rows = read_truth(args.truth)
    if not rows:
        raise SystemExit(f"ERROR: no rows in {args.truth}")
    largest = max(rows, key=lambda r: int(r.get("length") or 0))["sequence_id"]
    markers, rrna = read_features(args.features)
    status = caller_status(args.annotation_provenance)
    hits = plasmid_reference_matches(args.reference, args.plasmid_sketch, args.plasmid_max_distance) \
        if status["markers"] else None
    depth = read_long_read_depth(args.long_read_depth)
    labelled = [label(r, largest, markers, rrna, status, hits, depth, args.min_long_read_depth) for r in rows]
    # A plasmid detect_dimers.py flagged as an uncollapsed tandem dimer would
    # halve every tool's recall on it: AMBIGUOUS under this scheme (D2).
    flagged = set()
    if args.multimers and os.path.isfile(args.multimers):
        with open(args.multimers, newline="", encoding="utf-8") as handle:
            flagged = {r["sequence_id"] for r in csv.DictReader(handle, delimiter="\t")
                       if r.get("multimer") == "yes" and r.get("action") != "collapsed"}
    for record in labelled:
        if record["sequence_id"] in flagged and record["final_label"] == "PLASMID":
            record.update(final_label="AMBIGUOUS", reason="uncollapsed tandem multimer (detect_dimers.py)")

    with open(args.labels_out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(labelled)
    final = {r["sequence_id"]: r["final_label"] for r in labelled}
    with open(args.scored_truth_out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        for row in rows:
            if final[row["sequence_id"]] in ("PLASMID", "CHROMOSOME"):
                writer.writerow([row["sequence_id"], final[row["sequence_id"]], row["length"]])
    ambiguous = sum(r["final_label"] == "AMBIGUOUS" for r in labelled)
    sys.stderr.write(f"[label_truth_evidence] {len(rows)} replicon(s), {ambiguous} AMBIGUOUS "
                     f"(excluded from scoring); evidence {'evaluated' if status['markers'] else 'NOT evaluated'}\n")


if __name__ == "__main__":
    main()
