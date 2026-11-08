#!/usr/bin/env python3
"""
What the nearest-reference screen means, pinned so the documentation cannot drift
from the behaviour: the Mash threshold arithmetic quoted in the docstring, equal
sketch sizes for query and reference, p-value gating, and the renamed outputs.
No real mash binary is run.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import classify_operational_plasmid as cop  # noqa: E402

K = 21  # Mash default k-mer size; the scripts never override it


def distance_equal_size(shared_fraction):
    """Mash D for two equal-length sequences sharing this fraction of k-mers exactly."""
    return -math.log(shared_fraction) / K


def distance_fragment(fraction):
    """Mash D for an exact piece covering this fraction of a reference (j = f)."""
    return -math.log(2 * fraction / (1 + fraction)) / K


META = {"REF": {"organism": "Escherichia coli", "plasmid_name": "pX", "cluster_id": "REF",
                "cluster_member_count": "3"}}


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("the numbers quoted in the docstring are the formula's numbers")
    check("80% shared -> D = 0.011", abs(distance_equal_size(0.80) - 0.0106) < 5e-4)
    check("50% shared -> D = 0.033", abs(distance_equal_size(0.50) - 0.0330) < 5e-4)
    check("35% shared reaches the 0.05 threshold", abs(distance_equal_size(0.35) - 0.0500) < 5e-4)
    check("a 21.2% fragment reaches the threshold", abs(distance_fragment(0.212) - 0.0500) < 5e-4)
    check("a 15% fragment is beyond it (D = 0.064)", abs(distance_fragment(0.15) - 0.0639) < 5e-4)
    doc = cop.__doc__
    for quoted in ("s = 0.80 gives D = 0.011", "s = 0.50 gives D = 0.033", "s = 0.35", "f >= 0.212"):
        check(f"the docstring states '{quoted}'", quoted in doc)
    check("the docstring no longer claims 'roughly ANI >= 95%' as the meaning", "NOT \"ANI >= 95%\"" in doc)

    print("documented limitation, pinned: the threshold is not a similarity of 95%")
    half = cop.classify(["q"], [("REF", "q", distance_equal_size(0.50), 0.0, "500/1000")], META, 0.05, 2)
    check("two equal-size plasmids sharing only HALF their sequence still match",
          half["q"]["cluster_membership_status"] == "close_reference_match")
    fragment = cop.classify(["q"], [("REF", "q", distance_fragment(0.15), 0.0, "150/1000")], META, 0.05, 2)
    check("an exact 15% fragment of a reference plasmid is reported as no_close_reference",
          fragment["q"]["cluster_membership_status"] == "no_close_reference")
    check("and its note says this is not evidence of novelty", "not evidence that the plasmid is novel" in fragment["q"]["notes"])

    print("p-value gating")
    weak = cop.classify(["q"], [("REF", "q", 0.01, 0.5, "3/1000")], META, 0.05, 2, max_p_value=1e-3)
    check("a close but unsupported hit is no_close_reference", weak["q"]["cluster_membership_status"] == "no_close_reference")
    check("the note says why", "not statistically supported" in weak["q"]["notes"])
    strong = cop.classify(["q"], [("REF", "q", 0.01, 1e-9, "900/1000")], META, 0.05, 2, max_p_value=1e-3)
    check("a close, supported hit matches", strong["q"]["cluster_membership_status"] == "close_reference_match")
    check("p-value and shared hashes are kept in the output",
          strong["q"]["mash_p_value"] == "1e-09" and strong["q"]["shared_hashes"] == "900/1000")
    legacy = cop.classify(["q"], [("REF", "q", 0.01)], META, 0.05, 2)
    check("a bare (ref, query, distance) row still works", legacy["q"]["cluster_membership_status"] == "close_reference_match")

    print("renamed outputs")
    check("HEADER has distance_margin, mash_p_value, shared_hashes",
          {"distance_margin", "mash_p_value", "shared_hashes"} <= set(cop.HEADER))
    check("HEADER no longer has confidence_score", "confidence_score" not in cop.HEADER)
    check("no row uses the old labels",
          all(r["cluster_membership_status"] not in ("novel", "known_cluster")
              for r in (half["q"], fragment["q"], weak["q"], strong["q"])))

    print("query and reference are sketched at the same size")
    with tempfile.TemporaryDirectory() as tmp:
        sketch = Path(tmp) / "reference.msh"
        sketch.write_bytes(b"x")
        check("no provenance file -> the build default (10000)", cop.reference_sketch_size(sketch) == 10000)
        (Path(tmp) / "reference_set_provenance.json").write_text(json.dumps({"sketch_size": 2500}))
        check("provenance sketch_size is read", cop.reference_sketch_size(sketch) == 2500)
        (Path(tmp) / "reference_set_provenance.json").write_text("not json")
        check("an unreadable provenance file falls back, never raises", cop.reference_sketch_size(sketch) == 10000)

        calls = []

        def fake_run(command, **kwargs):
            calls.append(list(command))
            if command[1] == "sketch":
                Path(command[command.index("-o") + 1] + ".msh").write_bytes(b"q")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="REF\tq\t0.01\t0\t900/1000\n", stderr="")

        original = cop.subprocess.run
        cop.subprocess.run = fake_run
        try:
            query = Path(tmp) / "q.fa"
            query.write_text(">q\nACGT\n")
            rows = cop.run_mash_dist("mash", sketch, query, tmp, 1, sketch_size=2500)
        finally:
            cop.subprocess.run = original
        sketch_cmd = next(c for c in calls if c[1] == "sketch")
        check("the query sketch command passes -s 2500", "-s" in sketch_cmd and sketch_cmd[sketch_cmd.index("-s") + 1] == "2500")
        check("mash dist's p-value and shared hashes are parsed", rows == [("REF", "q", 0.01, 0.0, "900/1000")])

    print()
    if not ok:
        print("CLASSIFIER SEMANTICS TESTS FAILED")
        sys.exit(1)
    print("ALL CLASSIFIER SEMANTICS TESTS PASSED")


if __name__ == "__main__":
    main()
