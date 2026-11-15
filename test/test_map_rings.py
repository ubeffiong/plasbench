#!/usr/bin/env python3
"""Identity shading and resistance-region brackets on the plasmid maps (plan D6): the python static map and the JS viewer agree."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, HERE)

import report_maps as rm  # noqa: E402
import test_plasmid_viewer as tv  # noqa: E402
import test_report_maps as tm  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    blocks = [{"ts": 0, "te": 1000, "identity": 0.999}, {"ts": 1000, "te": 3000, "identity": 0.90}, {"ts": 5000, "te": 6000, "identity": None}]
    print("identity")
    check("identity is the length-weighted mean over the overlapping blocks", abs(rm.interval_identity(blocks, 500, 2000) - (500 * 0.999 + 1000 * 0.90) / 1500) < 1e-9)
    check("a stretch with no identity-bearing block is unknown, not zero", rm.interval_identity(blocks, 5000, 6000) is None and rm.interval_identity(blocks, 8000, 9000) is None)
    check("the four bands pick the right colours", [rm.identity_colour(v) for v in (0.995, 0.97, 0.92, 0.5)] == [c for _f, c in rm.IDENTITY_BANDS])
    check("an unknown identity keeps the plain cover colour", rm.identity_colour(None) == rm.COVER_FILL)

    print("resistance regions")
    genes = [tm.gene("blaTEM", 1000, 1900, "+", "amr"), tm.gene("aac", 3000, 3500, "-", "amr"), tm.gene("sul1", 20000, 20800, "+", "amr"),
             tm.gene("repA", 500, 900, "+", "replication"), tm.gene("wrap", 9900, 100, "+", "amr")]
    regions = rm.resistance_regions(genes, 30000)
    check("genes within 5 kb merge, a distant one stands alone", [(r["start"], r["end"]) for r in regions] == [(1000, 3500), (20000, 20800)], regions)
    check("only resistance genes are bracketed, and a gene wrapping the origin is left out", all("repA" not in r["genes"] and "wrap" not in r["genes"] for r in regions))

    print("static map and payload")
    model = tm.model(length=30000, genes=genes, tools=[tm.tool("toolA", [(0, 4000)], 0.5)])
    model["tools"][0]["blocks"] = [{"record": "c1", "qlen": 4000, "qs": 0, "qe": 4000, "strand": "+", "ts": 0, "te": 4000, "identity": 0.97, "mapq": 60}]
    svg, _meta = rm.render_svg(model, "m1")
    check("the static map draws a bracket per region and shades the covered stretch by identity", svg.count("class='resistance-region'") == 2 and rm.identity_colour(0.97) in svg)
    check("the legend names identity and the resistance region", "Identity of the covered stretch" in rm._legend(_meta) and "Resistance region" in rm._legend(_meta))
    payload = rm.viewer_payload(model, "m1")
    check("the viewer payload carries the regions", payload.get("rz") == [[1000, 3500, "blaTEM, aac"], [20000, 20800, "sul1"]], payload.get("rz"))

    print("the viewer agrees")
    if not tv.NODE:
        print("  SKIP: node not found; the JS parity tests need it")
    else:
        got = tv.js("return [PV.intervalIdentity(input.blocks, 500, 2000), PV.identityColour(PV.intervalIdentity(input.blocks, 5000, 6000)), PV.identityColour(0.995), PV.identityColour(0.5)];",
                    {"blocks": [{"start": b["ts"], "end": b["te"], "identity": b["identity"]} for b in blocks]})
        check("JS identity equals python identity, unknown stays unknown, bands equal", abs(got[0] - rm.interval_identity(blocks, 500, 2000)) < 1e-9 and got[1] is None
              and got[2] == rm.identity_colour(0.995) and got[3] == rm.identity_colour(0.5), got)
        scene = tv.js("const m = PV.normalize(input); return PV.buildScene(m, PV.defaultState()).partsSvg;", payload)
        check("the live scene draws one bracket per region and shades the covered stretch by identity", scene.count("class='resistance-region'") == 2 and rm.identity_colour(0.97) in scene,
              scene.count("class='resistance-region'"))
        check("the JS viewer reads the payload's regions into its model", tv.js("return PV.normalize(input).resistance;", payload) == payload["rz"])
    print()
    if not ok:
        print("MAP RING TESTS FAILED")
        sys.exit(1)
    print("ALL MAP RING TESTS PASSED")


if __name__ == "__main__":
    main()
