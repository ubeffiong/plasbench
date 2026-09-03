#!/usr/bin/env python3
"""Checks for the reconstruction evidence explorer's data mapping.

The explorer is a vendored design fed from measured output. These tests pin the
mapping: every field it shows is either derived from the run or explicitly null,
and no unmeasured value is reported as a zero.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import build_explorer_view as explorer  # noqa: E402


def payload():
    """One sample with every behaviour the explorer has to display."""
    blocks = [
        # Clean recovery of the first half.
        {"record_id": "r1", "query_length": 5000, "query_start": 0, "query_end": 5000,
         "strand": "+", "target": "pA", "target_start": 0, "target_end": 5000,
         "matches": 5000, "block_length": 5000, "mapq": 60, "cigar": "",
         "molecule_type": "PLASMID",
         "local_alignment": {"reference": "ACGT" * 25, "prediction": "ACGA" * 25,
                             "meaning": "bounded local alignment"}},
        # Reverse-strand block, and a reference gap before it.
        {"record_id": "r2", "query_length": 2000, "query_start": 0, "query_end": 2000,
         "strand": "-", "target": "pA", "target_start": 7000, "target_end": 9000,
         "matches": 1900, "block_length": 2000, "mapq": 40, "cigar": "",
         "molecule_type": "PLASMID"},
    ]
    return {
        "sample": "s1",
        "truth_plasmids": {"pA": {"molecule_type": "PLASMID", "length": 10000},
                           "chr1": {"molecule_type": "CHROMOSOME", "length": 100000}},
        "circular_truth_plasmids": ["pA"],
        "amr_features": [{"sequence_id": "pA", "start": 1000, "end": 1800, "label": "blaX"}],
        "context_features": [{"sequence_id": "pA", "start": 0, "end": 900,
                              "feature_type": "replicon", "label": "IncQ",
                              "source": "test", "version": "0"}],
        "protein_features": [{"sequence_id": "pA", "start": 2000, "end": 2600, "strand": "+",
                              "feature_id": "cds1", "gene": "repA", "product": "replication protein",
                              "category": "replicon", "source": "test", "version": "0",
                              "confidence": "high"},
                             {"sequence_id": "pA", "start": 8000, "end": 8600, "strand": "-",
                              "feature_id": "cds2", "gene": "pemK", "product": "toxin",
                              "category": "toxin_antitoxin", "source": "test", "version": "0",
                              "confidence": "high"}],
        "tools": {"toolx": {
            "blocks": blocks,
            "plasmid_recovery": {"pA": {"covered_bp": 7000, "completeness": 0.7}},
            "bin_assignment_flows": [
                {"bin_id": "b1", "true_plasmid": "pA", "aligned_bp": 5000, "status": "matched"},
                {"bin_id": "b2", "true_plasmid": "pA", "aligned_bp": 2000, "status": "matched"},
            ],
        }},
    }


def calls():
    return {"s1": {"tools": {"toolx": {"events": [
        {"record_id": "r2", "event_type": "inversion_junction", "span_bp": 2000,
         "left_target": "pA", "left_target_end": 7000, "right_target": "pA",
         "right_target_start": 7000, "detail": "reverse block", "validated": False},
        {"record_id": "r1", "event_type": "inter_replicon_junction", "span_bp": 100,
         "left_target": "pA", "left_target_end": 5000, "right_target": "chr1",
         "right_target_start": 0, "detail": "joins pA and chr1", "validated": False},
    ]}}}}


def main():
    data = explorer.build({"s1": payload()}, calls(), {"toolx": "1.2.3"})

    assert data["samples"], "no sample reached the explorer payload"
    sample = data["samples"][0]
    assert sample["id"] == "s1"
    # Chromosomes are not plasmids and must not become explorer rows.
    assert [p["id"] for p in sample["plasmids"]] == ["pA"], "non-plasmid targets leaked in"
    plasmid = sample["plasmids"][0]

    assert plasmid["length"] == 10000
    assert plasmid["circular"] is True
    assert plasmid["replicon"] == "IncQ", "replicon not taken from the curated context feature"
    assert plasmid["recovery"] == 0.7, "recovery must come from measured completeness"
    # Purity is measured per predicted bin, not per truth plasmid.
    assert plasmid["purity"] is None, "purity must not be invented at plasmid scope"

    # Every annotation source contributes, and the protein schema's own
    # "category" column decides the category rather than "feature_type".
    categories = {f["name"]: f["category"] for f in plasmid["proteins"]}
    assert categories["blaX"] == "AMR"
    assert categories["IncQ"] == "Replication"
    assert categories["repA"] == "Replication"
    assert categories["pemK"] == "Maintenance", "protein category column ignored"

    # Coordinate recovery, not amino-acid identity.
    status = {f["name"]: f["status"] for f in plasmid["proteins"]}
    assert status["repA"] == "Complete", "feature inside a recovered segment must be complete"
    assert status["blaX"] == "Complete"

    track = plasmid["tools"][0]
    assert track["version"] == "1.2.3", "tool version not carried through"
    assert track["mapQ"] == 50.0, "mapping quality is measured and must be reported"
    assert track["identity"] is not None
    # The one field projection scoring never measures.
    assert track["coverage"] is None, "read coverage must be null, never zero"
    assert data["unmeasured"]["coverage"], "the unmeasured field must be named for the reader"

    # Segments cover the whole reference: measured blocks plus explicit gaps.
    kinds = [s["type"] for s in track["segments"]]
    assert "inverted" in kinds, "reverse-strand block lost its classification"
    assert "missing" in kinds, "uncovered reference interval not reported as missing"
    spans = sorted((s["start"], s["end"]) for s in track["segments"])
    assert spans[0][0] == 0 and spans[-1][1] == plasmid["length"], \
        "segment track does not span the reference"
    for seg in track["segments"]:
        assert seg["end"] > seg["start"], f"segment has non-increasing coordinates: {seg}"
        assert 0 <= seg["start"] and seg["end"] <= plasmid["length"], \
            f"segment leaves the reference: {seg}"

    # Nucleotide strings resolve only where a CIGAR-bounded alignment exists.
    assert track["resolvedBases"] == 100, "resolved bases miscounted"
    assert plasmid["sequence"].count(explorer.UNKNOWN_BASE) == 9900, \
        "unresolved reference bases must stay unresolved, not be invented"

    # Structural navigation targets, all from the caller or the segment track.
    events = plasmid["events"]
    assert events["inversions"], "inversion junction not offered for navigation"
    assert events["breakpoints"], "inter-replicon junction not offered for navigation"
    assert events["gaps"], "reference gap not offered for navigation"
    assert events["mismatches"], "mismatch columns not offered for navigation"
    for group in events.values():
        positions = [e["pos"] for e in group]
        assert positions == sorted(positions), "navigation targets are not in coordinate order"
        assert all(e["validated"] is False for e in group), \
            "alignment-derived calls must not be presented as validated"

    # Split and merge are properties of one method's binning. Two bins from the
    # same method carrying one truth plasmid is a split, not four unrelated 1:1s.
    links = sample["split_merge"]["links"]
    assert len(links) == 2
    assert {l["type"] for l in links} == {"split"}, \
        "fan-out within one method must be classified as a split"

    # Pooling methods must not manufacture splits: one bin per method is 1:1.
    pooled = payload()
    pooled["tools"]["tooly"] = {
        "blocks": [], "plasmid_recovery": {},
        "bin_assignment_flows": [{"bin_id": "c1", "true_plasmid": "pA",
                                  "aligned_bp": 9000, "status": "matched"}]}
    pooled["tools"]["toolx"]["bin_assignment_flows"] = [
        {"bin_id": "b1", "true_plasmid": "pA", "aligned_bp": 9000, "status": "matched"}]
    relations = explorer.split_merge_for(pooled, {"pA": {"length": 10000}})
    assert {l["type"] for l in relations["links"]} == {"1:1"}, \
        "one bin per method is not a split; the count must be per method"

    print("ALL EXPLORER VIEW TESTS PASSED "
          f"({len(track['segments'])} segments, {sum(len(v) for v in events.values())} events)")


if __name__ == "__main__":
    main()
