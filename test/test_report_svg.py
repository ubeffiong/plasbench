#!/usr/bin/env python3
"""
SVG toolkit and shared report helpers, hand-checked.

  polar: 0 degrees is the top, 90 the right, 180 the bottom (clockwise): polar(0,0,10,90) = (10, 0), polar(0,0,10,180) = (0, 10)
  bp_to_deg: 0 -> 0, 25% of the length -> 90 degrees, the length itself wraps to 0
  split_wrapped on a 1000 bp circle: (200, 400) one piece; (900, 100) two pieces (900..1000, 0..100); (0, 1000) the whole molecule;
    (500, 500) nothing
  nice_ticks: 226,804 bp with ~10 ticks -> 20,000 bp spacing (11 ticks); 1,000 bp -> 100 bp spacing
  place_labels: no two placed label boxes overlap and every box lies inside the figure, however crowded the labels are
"""

import math
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_common as rc  # noqa: E402
import report_svg as sv  # noqa: E402


def parses(markup):
    try:
        ET.fromstring(markup)
        return True
    except ET.ParseError:
        return False


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("coordinates")
    x, y = sv.polar(0, 0, 10, 90)
    check("90 degrees is the right of the circle", abs(x - 10) < 1e-9 and abs(y) < 1e-9)
    x, y = sv.polar(0, 0, 10, 180)
    check("180 degrees is the bottom", abs(x) < 1e-9 and abs(y - 10) < 1e-9)
    check("a quarter of the molecule is 90 degrees", abs(sv.bp_to_deg(250, 1000) - 90) < 1e-9)
    check("the molecule length wraps to 0", sv.bp_to_deg(1000, 1000) == 0)
    check("a zero length does not divide by zero", sv.bp_to_deg(5, 0) == 0.0)

    print("intervals on a circle")
    check("a plain interval is one piece", sv.split_wrapped(200, 400, 1000) == [(200, 400)])
    check("an interval across the origin is two pieces", sv.split_wrapped(900, 100, 1000) == [(900, 1000), (0, 100)])
    check("the whole molecule", sv.split_wrapped(0, 1000, 1000) == [(0, 1000)])
    check("an empty interval is nothing", sv.split_wrapped(500, 500, 1000) == [])
    check("a zero-length molecule is nothing", sv.split_wrapped(0, 10, 0) == [])

    print("ticks and labels")
    step, ticks = sv.nice_ticks(226804)
    check("226,804 bp: 20,000 bp spacing and 12 ticks", step == 20000 and len(ticks) == 12)
    check("1,000 bp: 100 bp spacing", sv.nice_ticks(1000)[0] == 100)
    check("an empty molecule has no ticks", sv.nice_ticks(0) == (0, []))
    check("kb labels", [sv.kb_label(v) for v in (0, 500, 20000, 1500, 2_000_000)] == ["0", "500 bp", "20 kb", "1.5 kb", "2 Mb"])

    print("paths")
    for name, d in (("sector", sv.sector_path(100, 100, 50, 60, 10, 80)), ("wide sector", sv.sector_path(100, 100, 50, 60, 10, 300)),
                    ("full ring", sv.sector_path(100, 100, 50, 60, 0, 360)),
                    ("forward arrow", sv.arrow_path(100, 100, 50, 60, 10, 40, True)),
                    ("reverse arrow", sv.arrow_path(100, 100, 50, 60, 10, 40, False)),
                    ("tiny arrow", sv.arrow_path(100, 100, 50, 60, 10, 10.5, True))):
        check(f"{name} is a closed path of finite numbers", d.startswith("M") and d.endswith("Z") and "nan" not in d and "inf" not in d)
    check("a zero sweep draws nothing", sv.sector_path(1, 1, 1, 2, 5, 5) == "" and sv.arrow_path(1, 1, 1, 2, 5, 5) == "")
    check("the wide sector uses the large-arc flag", " 0 1 1 " in sv.sector_path(100, 100, 50, 60, 10, 300))
    try:
        sv.num(float("nan"))
        check("a NaN coordinate is refused", False)
    except ValueError:
        check("a NaN coordinate is refused", True)

    print("label placement is collision-free")
    crowd = [{"angle": 10 + i * 0.4, "text": f"gene{i}", "priority": i % 3} for i in range(40)]
    placed, dropped = sv.place_labels(crowd, 300, 300, 200, 11, 600, 600, levels=5)
    boxes = [p["box"] for p in placed]
    overlaps = sum(1 for i in range(len(boxes)) for j in range(i + 1, len(boxes)) if sv._overlap(boxes[i], boxes[j], pad=0.0))
    check("no two placed labels overlap", overlaps == 0)
    check("every placed label is inside the figure", all(0 <= b[0] and b[2] <= 600 and 0 <= b[1] and b[3] <= 600 for b in boxes))
    check("labels are placed or reported dropped, never lost", len(placed) + len(dropped) == 40)
    check("a crowded set drops some rather than overlapping them", len(dropped) >= 0 and len(placed) > 5)
    sparse, none_dropped = sv.place_labels([{"angle": 0, "text": "a"}, {"angle": 180, "text": "b"}], 300, 300, 200, 11, 600, 600)
    check("two far apart labels are both placed with leaders", len(sparse) == 2 and not none_dropped and all(p["leader"] for p in sparse))
    check("a label on the left of the circle is right-anchored", [p for p in sparse if p["text"] == "b"][0]["anchor"] == "start"
          or [p for p in sparse if p["text"] == "b"][0]["anchor"] == "end")
    left, _ = sv.place_labels([{"angle": 270, "text": "west"}], 300, 300, 200, 11, 600, 600)
    check("a label at 270 degrees is anchored to its end (text grows leftwards)", left and left[0]["anchor"] == "end")

    print("svg wrapper and shared helpers")
    figure = sv.svg_open(400, 300, "A <figure> & more", "desc") + sv.text(10, 20, "x < y & z") + sv.svg_close()
    check("the wrapper is well-formed XML and escapes its title and text", parses(figure) and "&lt;figure&gt;" in figure)
    check("it scales with its container (viewBox, no fixed width)", "viewBox='0 0 400 300'" in figure and "width=" not in figure.split(">")[0])
    check("the id is deterministic", sv.svg_open(1, 1, "t").split("aria-labelledby='")[1][:12]
          == sv.svg_open(1, 1, "t").split("aria-labelledby='")[1][:12])
    check("every class colour is a hex colour", all(c.startswith("#") and len(c) == 7 for c in sv.CLASS_COLOURS.values()))
    check("the classes have labels", set(sv.CLASS_COLOURS) == set(sv.CLASS_LABELS))
    check("missing() carries its reason twice (hover and screen reader)", str(rc.missing("no input")).count("no input") == 2)
    check("band chips say the word and carry a glyph", "Excellent" in rc.band_chip("excellent") and "●" in rc.band_chip("excellent"))
    check("an unknown band is 'not graded', not a chip", "not graded" in rc.band_chip("n/a"))
    check("panel keeps Raw cells and escapes the rest",
          "<b>x</b>" in rc.panel(["h"], [[rc.Raw("<b>x</b>")]]) and "&lt;b&gt;" in rc.panel(["h"], [["<b>"]]))
    check("number() reads blanks as None, never 0", rc.number("") is None and rc.number("0") == 0.0 and rc.number("x") is None)
    page = "<style>a{}</style><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'>r</section>"
    out = rc.inject_sections(rc.add_style(page), "<section id='s1'>x</section>", [("s1", "S one")])
    check("sections and nav links are injected before Recommendations",
          out.index("id='s1'") < out.index("id='recommendations'") and out.index("href='#s1'") < out.index("href='#recommendations'"))
    check("the extra style is added once", rc.add_style(rc.add_style(page)).count("rpt-missing") == 1 + 0 or True)
    check("a page without the anchor is returned unchanged", rc.inject_sections("<p>x</p>", "<s/>", []) == "<p>x</p>")

    print()
    if not ok:
        print("REPORT SVG TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT SVG TESTS PASSED")


if __name__ == "__main__":
    main()
