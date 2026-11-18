#!/usr/bin/env python3
"""Presence/absence matrix (python/report_fig_presence.py): clustering determinism, prevalence, not-annotated vs absent, the tool outcome overlay, empty states, escaping, print."""
import itertools
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import report_fig_facets as ff  # noqa: E402
import report_fig_presence as fp  # noqa: E402
import report_visuals_fixture as fx  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("clustering")
    profiles = [{1, 2}, {1, 2}, {3}, {1}, set()]
    order, merges = fp.cluster(profiles)
    check("the clustering is deterministic: the same input gives the same order and tree", fp.cluster(profiles) == (order, merges))
    check("identical profiles merge first at height 0", merges[0] == [0, 1, 0.0], merges)
    check("a worked UPGMA example: {1,2} with {1} at 0.5, then {3} with the empty profile at 1", merges[1] == [5, 3, 0.5] and merges[2] == [2, 4, 1.0], merges)
    check("the order is a permutation of all rows", sorted(order) == list(range(5)))
    check("two similar rows end up adjacent", abs(order.index(0) - order.index(1)) == 1)
    check("jaccard: identical 0, disjoint 1, both empty 0", fp.jaccard({1}, {1}) == 0 and fp.jaccard({1}, {2}) == 1 and fp.jaccard(set(), set()) == 0)
    check("a single row and no rows are handled", fp.cluster([{1}]) == ([0], []) and fp.cluster([]) == ([], []))
    base = [{1, 2}, {1}, {3}, {1, 2, 3}, {4}, set()]
    first = fp.cluster(base)[0]
    shuffled_same = all(sorted(fp.cluster([base[i] for i in perm])[1], key=lambda m: m[2])[-1][2] == sorted(fp.cluster(base)[1], key=lambda m: m[2])[-1][2]
                        for perm in itertools.islice(itertools.permutations(range(6)), 0, 40))
    check("the root height does not depend on the input order", shuffled_same)
    check("the fallback order is deterministic and puts feature-rich rows first", fp.profile_order([{1}, {1, 2, 3}, set()]) == [1, 0, 2])

    with tempfile.TemporaryDirectory() as tmp:
        scores = fx.make(tmp)
        data, why = fp.build_payload(tmp, tmp, scores)
        check("the payload builds from the fixture", data is not None, why)
        rows = [f"{r[0]}/{r[1]}" for r in data["rows"]]
        check("rows are the truth plasmids of the samples that have a truth table", sorted(rows) == ["s1/pA", "s1/pB", "s2/pC", "s4/pD", "s5/pE"], rows)
        ridx = {name: i for i, name in enumerate(rows)}
        kinds = [b["k"] for b in data["blocks"]]
        check("blocks are only those the data contain, in a fixed order (replicon, mob, AMR class, AMR gene)", kinds == ["replicon", "mob", "amr_class", "amr_gene"], kinds)
        check("there is no virulence block because nothing annotated virulence", not any("viru" in k for k in kinds))
        blk = {b["k"]: b for b in data["blocks"]}
        check("s2/pC has no truth_features.tsv: it is NOT ANNOTATED for replicon and MOB", ridx["s2/pC"] in blk["replicon"]["na"] and ridx["s2/pC"] in blk["mob"]["na"])
        check("s5/pE has an AMR table with no gene: annotated and absent, not 'not annotated'", ridx["s5/pE"] not in blk["amr_class"]["na"])
        check("every plasmid with a truth_amr.tsv is annotated for AMR (s1, s2, s4, s5)", blk["amr_class"]["na"] == [])
        fnames = {b["k"]: [f[0] for f in b["f"]] for b in data["blocks"]}
        check("replicon features are those listed in the tables, most prevalent first", fnames["replicon"] == ["ColE1", "IncFIB"] or fnames["replicon"] == ["IncFIB", "ColE1"], fnames["replicon"])
        check("AMR genes are the listed ones and nothing invented", sorted(fnames["amr_gene"]) == ["blaCTX-M-15", "sul1", "tetA"], fnames["amr_gene"])
        classes = ff.amr_classes()
        check("AMR classes come from config/amr_gene_classes.tsv", sorted(fnames["amr_class"]) == sorted({ff.gene_class_of(g, classes) for g in ("blaCTX-M-15", "sul1", "tetA")}), fnames["amr_class"])

        print("prevalence")
        rep = {"features": [], "ann": [i not in blk["replicon"]["na"] for i in range(len(rows))]}
        ibfib = [f[1] for f in blk["replicon"]["f"] if f[0] == "IncFIB"][0]
        c, n, share = fp.prevalence({"ann": rep["ann"]}, ibfib)
        check("prevalence uses annotated plasmids only: IncFIB is on 2 of 4 annotated (the unannotated s2/pC is not counted absent)", (c, n) == (2, 4) and share == 0.5, (c, n, share))
        check("no annotated plasmid gives no share, not 0", fp.prevalence({"ann": [False, False]}, [])[2] is None)
        check("clustering puts the two IncFIB/MOBF/CTX-M plasmids (pA, pD) next to each other", abs(data["order"].index(ridx["s1/pA"]) - data["order"].index(ridx["s4/pD"])) == 1, data["order"])

        print("outcome overlay")
        check("rules: correct -> recovered; covered but not correct -> partial; none covered -> missed; no value -> none",
              [ff.plasmid_outcome(c_, ok_) for c_, ok_ in ((1.0, True), (0.4, False), (0.0, False), (None, None))] == ["recovered", "partial", "missed", None])
        check("without a CPRR file completeness >= 0.90 counts as recovered", ff.plasmid_outcome(0.95, None) == "recovered" and ff.plasmid_outcome(0.5, None) == "partial")
        tools = [t[1] for t in data["tools"]]
        a = data["out"][str(tools.index("toolA"))]
        b = data["out"][str(tools.index("toolB"))]
        check("toolA: pA recovered, pB partly (0.4 not correct), pC missed, pD recovered, pE partly (0.95 but CPRR says no)",
              [a[ridx[x]] for x in ("s1/pA", "s1/pB", "s2/pC", "s4/pD", "s5/pE")] == ["r", "p", "m", "r", "p"], a)
        check("toolB: pA partly (0.5, not correct), pB recovered, pC recovered, pD recovered, pE missed", [b[ridx[x]] for x in ("s1/pA", "s1/pB", "s2/pC", "s4/pD", "s5/pE")] == ["p", "r", "r", "r", "m"], b)
        check("a tool without a per-plasmid table is not offered", len(data["tools"]) == 2)
        check("no tool selected means truth only: the static figure draws no outcome strip", "Outcome" not in fp.static_svg(data))

        print("the figure")
        svg = fp.static_svg(data)
        ET.fromstring(svg)
        check("the static SVG is well formed with a title and description", "<title" in svg and "<desc" in svg)
        present = sum(len([i for i in f[1] if i not in b_["na"]]) for b_ in data["blocks"] if b_["k"] != "amr_gene" for f in b_["f"])
        drawn = len(re.findall(r"<rect x='[\d.]+' y='[\d.]+' width='7' height='[\d.]+' fill='#0072B2'/>", svg))
        check("one blue cell per present feature, none invented", drawn == present, (drawn, present))
        check("not-annotated cells are hatched", svg.count("fill='url(#fp-hatch)'") == len([1 for b_ in data["blocks"] if b_["k"] != "amr_gene" for _ in b_["na"]]))
        check("a dendrogram path is drawn when clustered", "stroke='#555'" in svg and data["clustered"])
        table = str(fp.table_html(data))
        check("the table fold says 'not annotated' where the annotation is missing", "not annotated" in table and "s2" in table)

        print("escaping")
        hostile = dict(data, rows=[["<s>", "<p>&", 100, 1]] + data["rows"][1:], tracks=[dict(t, vals=["<b>"] + t["vals"][1:]) for t in data["tracks"]])
        hostile["blocks"] = [dict(b_, f=[["<i>x", f[1]] for f in b_["f"]]) for b_ in data["blocks"]]
        hs = fp.static_svg(hostile)
        check("feature, plasmid and track names are escaped", "<i>" not in hs and "<b>" not in hs and "<p>" not in hs)
        check("the table escapes too", "<p>" not in str(fp.table_html(hostile)))

        print("the section and print")
        page = "<style></style><section id='recommendations'></section><a href='#recommendations'>Recommendations</a>"
        out = fp.inject(page, tmp, tmp, scores)
        check("the section is injected before Recommendations", out.index("id='fig-presence'") < out.index("id='recommendations'"))
        check("the static version is in a block print shows; the live app is hidden in print", "class='fp-static'" in out and "@media print{.fp-app" in out and ".fp-root.fp-live .fp-static{display:block}" in out)
        check("the table is a collapsed fold", "<details class='rpt-collapsible fp-table' data-closed><summary>Table:" in out)
        check("one compact JSON block, script-breaking characters escaped", out.count("id='fp-data'") == 1 and "</" not in re.search(r"id='fp-data'>(.*?)</script>", out, re.S).group(1))
        for needle in ("id: 'fp-tool'", "id: 'fp-order'", "id: 'fp-amr'", "id: 'fp-group'", "aria-live", "aria-label", "tabindex", "prefers-color-scheme:dark", "max-width:900px",
                       "'aria-pressed'", "aria-controls", "#plasmid-maps?msample="):
            check(f"the interface has {needle}", needle in out, needle)

        print("empty states")
        bare = Path(tmp) / "bare"
        bare.mkdir()
        (bare / "scores.tsv").write_text("sample\ttool\tanalysis_track\nx\tt\tshort_read\n", encoding="utf-8")
        none, reason = fp.build_payload(str(bare), str(bare), str(bare / "scores.tsv"))
        check("no per-sample truth tables: a reason that names them", none is None and "truth.tsv" in reason and "--data-dir" in reason, reason)
        sec = str(fp.build_section(str(bare), str(bare), str(bare / "scores.tsv")))
        check("the section says 'Not available in this run: <what is missing>' and draws nothing", "Not available in this run:" in sec and "<svg" not in sec)
        none2, reason2 = fp.build_payload(str(bare), str(bare), str(Path(tmp) / "absent.tsv"))
        check("no scores.tsv is a reason too", none2 is None and "scores.tsv" in reason2)
        for f in (Path(tmp) / "s1" / "truth_amr.tsv", Path(tmp) / "s2" / "truth_amr.tsv", Path(tmp) / "s4" / "truth_amr.tsv", Path(tmp) / "s5" / "truth_amr.tsv",
                  Path(tmp) / "s1" / "truth_features.tsv", Path(tmp) / "s4" / "truth_features.tsv", Path(tmp) / "s5" / "truth_features.tsv"):
            f.unlink()
        none3, reason3 = fp.build_payload(tmp, tmp, scores)
        check("plasmids with no annotation table at all give 'no annotation table lists a feature', not an empty matrix", none3 is None and "annotation" in reason3, reason3)
    print()
    if not ok:
        print("PRESENCE MATRIX TESTS FAILED")
        sys.exit(1)
    print("ALL PRESENCE MATRIX TESTS PASSED")


if __name__ == "__main__":
    main()
