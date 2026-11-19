#!/usr/bin/env python3
"""Facet heatmaps (python/report_fig_facets.py): stratification, ordering, cell statistics, the n threshold, blanks, empty states, escaping, print markers."""
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import report_fig_facets as ff  # noqa: E402
import report_visuals_fixture as fx  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    with tempfile.TemporaryDirectory() as tmp:
        scores = fx.make(tmp)
        data, why = ff.build_payload(tmp, tmp, scores)
        check("the payload builds from the fixture", data is not None, why)
        iso, pla = data["levels"]["isolate"], data["levels"].get("plasmid")
        tools = [t[1] for t in data["tools"]]

        print("stratification")
        check("band edges: 29.9 -> <30x, 30 -> 30-59x, 99.9 -> 60-99x, 100 -> 100-199x, 200 -> >=200x, None -> not recorded",
              [ff.depth_band(x) for x in (29.9, 30, 99.9, 100, 200, None)] == ["<30x", "30-59x", "60-99x", "100-199x", ">=200x", ff.NOT_REC])
        check("plasmid size bands: 9999 -> <10kb, 10000 and 50000 -> 10-50kb, 50001 -> >50kb", [ff.size_band(x) for x in (9999, 10000, 50000, 50001)] == ["<10kb", "10-50kb", "10-50kb", ">50kb"])
        check("plasmid count bands", [ff.count_band(x) for x in (1, 2, 3, 4)] == ["1", "2-3", "2-3", "4+"])
        sp = next(s for s in iso["strata"] if s["k"] == "species")
        check("species values are sorted", sp["vals"] == ["Escherichia coli", "Klebsiella pneumoniae"], sp["vals"])
        tier = next(s for s in iso["strata"] if s["k"] == "tier")
        check("an isolate without a tier is 'not recorded' and that value comes last", tier["vals"] == ["Tier 3 (provisional)", ff.NOT_REC], tier["vals"])
        dep = next(s for s in iso["strata"] if s["k"] == "depth")
        check("depth bands follow the defined order, not alphabetical", dep["vals"] == ["<30x", "30-59x", "60-99x", "100-199x"], dep["vals"])
        check("a stratum nobody recorded (gram group) is not offered", "gram" not in [s["k"] for s in iso["strata"]])
        sel = ff.default_selection(iso)
        check("the default picks the first two strata with two or more values", sel["block"] == "species" and sel["row"] == "depth", sel)
        check("the default metrics are the ones that exist", sel["metrics"] == ["precision", "recall", "f1", "cprr"], sel)

        print("tool order")
        check("tools follow the leaderboard rank, the same list for every panel", tools == ["toolB", "toolA"], tools)

        print("cells")
        g = ff.grid(iso, "species", "depth")
        check("blocks are the species that occur, in order", [b["label"] for b in g] == ["Escherichia coli", "Klebsiella pneumoniae"])
        check("every block repeats every depth row, so a missing combination is a visible blank", all(len(b["rows"]) == 4 for b in g), [len(b["rows"]) for b in g])
        t_a, t_b = tools.index("toolA"), tools.index("toolB")
        f1 = [m["k"] for m in iso["metrics"]].index("f1")
        ecoli = g[0]
        allunits = [i for r in ecoli["rows"] for i in r["units"]]
        st = ff.cell_stats(iso, t_a, f1, allunits)
        check("a blank F1 (toolA on s3) is excluded and counted out, never 0", st["n"] == 3 and abs(st["v"] - (0.85 + 0.69 + 0.92) / 3) < 1e-9, st)
        check("a mean's interval is the range of the units and the kind says so", st["kind"] == "mean" and st["lo"] == 0.69 and st["hi"] == 0.92)
        cp = [m["k"] for m in iso["metrics"]].index("cprr")
        sp_ = ff.cell_stats(iso, t_a, cp, allunits)
        check("CPRR is pooled over plasmids (2 correct of 5), not a mean of isolate shares", sp_["c"] == 2 and sp_["total"] == 5 and abs(sp_["v"] - 0.4) < 1e-9, sp_)
        lo, hi = ff.wilson(2, 5)
        check("the CPRR interval is the Wilson interval of the pooled plasmids", abs(sp_["lo"] - lo) < 1e-9 and abs(sp_["hi"] - hi) < 1e-9 and 0 < lo < 0.4 < hi < 1)
        k_units = [i for r in g[1]["rows"] for i in r["units"]]
        nb = ff.cell_stats(iso, t_b, f1, k_units)
        check("toolB did not run on s6: the K. pneumoniae block holds one value, not two", nb["n"] == 1 and nb["few"], nb)
        empty = next(r for r in g[1]["rows"] if not r["units"])
        e = ff.cell_stats(iso, t_a, f1, empty["units"])
        check("a block and row combination with no unit is blank: n 0, no value, not hatched", e["n"] == 0 and e["v"] is None and not e["few"])
        one = ff.cell_stats(iso, t_a, f1, [allunits[0]])
        check("n below the threshold is flagged too few and n at the threshold is not", one["few"] and not ff.cell_stats(iso, t_a, f1, allunits, 3)["few"] and ff.cell_stats(iso, t_a, f1, allunits, 4)["few"])
        check("the threshold is adjustable: min_n 1 never flags", not ff.cell_stats(iso, t_a, f1, [allunits[0]], 1)["few"])
        check("the colour scale spans 0 to 1 and clamps", ff.colour(0) == "#440154" and ff.colour(1) == "#fde725" and ff.colour(-3) == ff.colour(0) and ff.colour(9) == ff.colour(1))

        print("plasmid level")
        check("the plasmid level exists when per-sample folders are present", pla is not None)
        sz = ff.stratum(pla, "size")
        check("plasmid size bands from the truth lengths", sz["vals"] == ["<10kb", "10-50kb", ">50kb"], sz["vals"])
        rep = next(s for s in pla["strata"] if s["k"] == "replicon")
        check("a plasmid whose sample has no feature table is 'not recorded' for replicon, not 'no replicon'", ff.NOT_REC in rep["vals"] and "no replicon annotated" not in rep["vals"], rep["vals"])
        amr = next(s for s in pla["strata"] if s["k"] == "amr")
        check("AMR carriage separates annotated-none from carries", "carries AMR gene" in amr["vals"] and "no AMR gene annotated" in amr["vals"], amr["vals"])
        rec = [m["k"] for m in pla["metrics"]].index("recovered")
        units = list(range(len(pla["units"])))
        r_a = ff.cell_stats(pla, t_a, rec, units)
        check("recovered share pools plasmids: toolA recovers pA, pD and pE (0.95 passes 0.90) of 5", r_a["c"] == 3 and r_a["total"] == 5, r_a)

        print("the figure")
        svg, n = ff.svg_static(iso, data["tools"], sel, 3, "short_read")
        ET.fromstring(svg)
        check("the static SVG is well formed XML with one panel per metric", n == 4)
        check("it carries a colour bar, a hatch legend, a title and a description", "fc-bar" in svg and "n &lt; 3" in svg and "<title" in svg and "<desc" in svg)
        check("hatched cells use the pattern fill and blank cells the dashed outline", "url(#fc-hatch)" in svg and "stroke-dasharray" in svg)
        check("tool columns appear in the same order in every panel (labels repeat per panel)", len(re.findall(r">toolB<", svg)) == 4 and svg.index(">toolB<") < svg.index(">toolA<"))
        table = str(ff.table_html(iso, data["tools"], sel, 3, "short_read"))
        check("the table fold lists every cell with the flag and says which interval it is", "too few" in table and "range" in table and "Wilson" in table)

        print("escaping")
        lev = {"unit": "isolate", "strata": [{"k": "species", "l": "Species", "vals": ["<script>x</script>"]}], "units": [["s<1>", "s<1>", [0]]],
               "metrics": [{"k": "f1", "l": "F1 <b>", "kind": "mean", "d": ""}], "vals": {"0": {"0": [0.5]}}}
        s_sel = {"block": "species", "row": None, "metrics": ["f1"]}
        s2, _ = ff.svg_static(lev, [["short_read", "t&<i>"]], s_sel, 3, "short_read")
        check("labels, tool names and metric names are escaped in the SVG", "<script>" not in s2 and "<b>" not in s2 and "<i>" not in s2 and "&lt;script&gt;" in s2)
        check("the table escapes too", "<script>" not in str(ff.table_html(lev, [["short_read", "t&<i>"]], s_sel, 3, "short_read")))

        print("empty states")
        none, reason = ff.build_payload(tmp, tmp, str(Path(tmp) / "nope.tsv"))
        check("no scores.tsv gives a reason, not a figure", none is None and "scores.tsv" in reason)
        bare = Path(tmp) / "bare"
        bare.mkdir()
        (bare / "scores.tsv").write_text("sample\ttool\tanalysis_track\nx\tt\tshort_read\n", encoding="utf-8")
        none2, reason2 = ff.build_payload(str(bare), str(bare), str(bare / "scores.tsv"))
        check("scores with no metric and no stratum say what is missing", none2 is None and "stratum" in reason2, reason2)
        sec = str(ff.build_section(str(bare), str(bare), str(bare / "scores.tsv")))
        check("the section degrades to 'Not available in this run: <what is missing>'", "Not available in this run:" in sec and "samples.tsv" in sec and "<svg" not in sec)

        print("the section and print")
        page = "<style></style><section id='recommendations'></section><a href='#recommendations'>Recommendations</a>"
        out = ff.inject(page, tmp, tmp, scores)
        check("the section is injected before Recommendations with its id", out.index("id='fig-facets'") < out.index("id='recommendations'"))
        check("the static figure sits in a block that print shows, and the live app hides in print", "class='fc-static'" in out and "@media print{.fc-app" in out and ".fc-root.fc-live .fc-static{display:block}" in out)
        check("the table is a collapsed fold", "<details class='rpt-collapsible fc-table' data-closed><summary>Table:" in out)
        check("the data are one compact JSON block with the script-breaking characters escaped", out.count("id='fc-data'") == 1 and "</" not in re.search(r"id='fc-data'>(.*?)</script>", out, re.S).group(1))
        for needle in ("id: 'fc-level'", "id: 'fc-track'", "id: 'fc-block'", "id: 'fc-row'", "id: 'fc-minn'", "aria-live", "role: 'tooltip'", "aria-label", "tabindex",
                       "prefers-color-scheme:dark", "max-width:900px", "type: 'checkbox'", "'aria-pressed'", "aria-controls"):
            check(f"the interface has {needle}", needle in out, needle)
        check("a cell opens on click and on Enter or Space", "'click'" in out and "ev.key === 'Enter'" in out)
    print()
    if not ok:
        print("FACET HEATMAP TESTS FAILED")
        sys.exit(1)
    print("ALL FACET HEATMAP TESTS PASSED")


if __name__ == "__main__":
    main()
