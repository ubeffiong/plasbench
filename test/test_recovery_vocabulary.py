#!/usr/bin/env python3
"""Every documented recovery class and segment type must be reachable.

Declaring a vocabulary is not the same as producing it. An earlier revision
defined nine segment types but emitted seven: `ambiguous` was shadowed by a
broader branch, and `unsupported_join` duplicated the `missing` span it should
have replaced. `complete_discordant` was likewise unreachable because the
collinearity it keys on was read from a payload that never carried it.
"""

import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import build_enterprise_view as ev  # noqa: E402


SEGMENT_TYPES = {"good", "missing", "inverted", "duplicated", "chromosomal",
                 "wrong_plasmid", "ambiguous", "low_identity", "unsupported_join"}
RECOVERY_CLASSES = {"complete_concordant", "complete_discordant", "near_complete",
                    "partial", "fragmented", "merged", "chromosomal_contam",
                    "not_recovered", "ambiguous"}


def block(record, target, start, end, strand="+", molecule="PLASMID",
          qstart=0, qend=None, matches=None, length=None):
    length = length or (end - start)
    return {"record_id": record, "target": target, "target_start": start,
            "target_end": end, "strand": strand, "molecule_type": molecule,
            "matches": length if matches is None else matches,
            "block_length": length, "query_length": 9000,
            "query_start": qstart,
            "query_end": qstart + (end - start) if qend is None else qend}


def main():
    # One record per intended segment type, so a miscall names its own record.
    blocks = [
        block("dup", "pA", 0, 500), block("dup", "pA", 400, 900, qstart=500),
        block("inv", "pA", 1000, 1500, strand="-"),
        block("chr", "pA", 2000, 2500), block("chr", "chr1", 0, 400, molecule="CHROMOSOME"),
        block("xpl", "pA", 3000, 3500), block("xpl", "pB", 0, 400),
        block("amb", "pA", 4000, 4500), block("amb", "pB", 500, 900), block("amb", "pC", 0, 300),
        block("low", "pA", 5000, 5500, matches=400, length=500),
        # Query runs straight across the reference gap: an unsupported join.
        block("join", "pA", 6000, 6200, qstart=0, qend=200),
        block("join", "pA", 8000, 8200, qstart=200, qend=400),
        # Query stops too: genuinely missing reference.
        block("miss", "pA", 100, 300, qstart=0, qend=200),
        block("miss", "pA", 2000, 2200, qstart=900, qend=1100),
    ]
    payload = {"truth_plasmids": {"pA": {"length": 9000}},
               "tools": {"t": {"blocks": blocks,
                               "plasmid_recovery": {"pA": {"completeness": 0.9}},
                               "structural_diagnostics": {}}}}

    produced = {}
    for row in ev.contig_rows(payload, "t", "pA"):
        for segment in row["segments"]:
            produced.setdefault(segment["type"], set()).add(row["id"])

    missing = sorted(SEGMENT_TYPES - set(produced))
    assert not missing, f"segment types declared but never produced: {missing}"
    unknown = sorted(set(produced) - SEGMENT_TYPES)
    assert not unknown, f"undocumented segment types emitted: {unknown}"

    # Each discriminating type must come from its own record, not a broader branch.
    for kind, record in (("ambiguous", "amb"), ("wrong_plasmid", "xpl"),
                         ("chromosomal", "chr"), ("unsupported_join", "join"),
                         ("duplicated", "dup"), ("low_identity", "low")):
        assert produced[kind] == {record}, f"{kind} came from {sorted(produced[kind])}, expected {record}"

    # A reference gap is one thing or the other, never both.
    for row in ev.contig_rows(payload, "t", "pA"):
        spans = {}
        for segment in row["segments"]:
            spans.setdefault((segment["start"], segment["end"]), []).append(segment["type"])
        doubled = {k: v for k, v in spans.items() if len(v) > 1}
        assert not doubled, f"{row['id']}: one span carries several types: {doubled}"
        starts = [segment["start"] for segment in row["segments"]]
        assert starts == sorted(starts), f"{row['id']}: segments are not in coordinate order"

    # Collinearity reaches classify from the structural summary, not the payload.
    single = {"truth_plasmids": {"pA": {"length": 1000}},
              "tools": {"t": {"blocks": [block("r", "pA", 0, 990)],
                              "plasmid_recovery": {"pA": {"completeness": 0.99}},
                              "structural_diagnostics": {}}}}
    assert ev.plasmid_rows(single, "t", None)[0]["recoveryClass"] == "complete_concordant"
    assert ev.plasmid_rows(single, "t", 0.50)[0]["recoveryClass"] == "complete_discordant", \
        "low collinearity must downgrade a fully covered plasmid"

    reachable = {
        ev.classify(1.0, 1, ambiguous=True), ev.classify(1.0, 1, chromosomal=True),
        ev.classify(1.0, 1, merged=True), ev.classify(0.95, 1, collinear=0.5),
        ev.classify(1.0, 1), ev.classify(0.93, 1),
        ev.classify(0.6, 3), ev.classify(0.6, 1), ev.classify(0.0, 0),
    }
    unreachable = sorted(RECOVERY_CLASSES - reachable)
    assert not unreachable, f"recovery classes declared but unreachable: {unreachable}"

    print(f"ALL RECOVERY VOCABULARY TESTS PASSED "
          f"({len(SEGMENT_TYPES)} segment types, {len(RECOVERY_CLASSES)} recovery classes)")


if __name__ == "__main__":
    sys.exit(main())
