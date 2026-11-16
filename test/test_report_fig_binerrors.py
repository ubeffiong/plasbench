#!/usr/bin/env python3
"""The binning error-profile charts: numbers, well-formed SVG, honest empty states, no markup injection.

Rows are hand-built so every share can be checked by arithmetic. Standard library only.
"""
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_fig_binerrors as fig  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def near(a, b, eps=1e-9):
    return a is not None and abs(a - b) < eps


def row(sample, tool, extra, missing, split, join, norm, f1=0.8, prec=0.9, rec=0.7, status="ok", a0=None, a1=None, search="none"):
    total = (extra + missing + split + join) / norm
    return {"sample": sample, "tool": tool, "dissim_status": status, "bin_dissimilarity": f"{total:.6f}",
            "dissim_extra_cost": str(extra), "dissim_missing_cost": str(missing), "dissim_split_cost": str(split),
            "dissim_join_cost": str(join), "dissim_norm": str(norm), "bestmatch_f1_bp": str(f1),
            "bestmatch_precision_bp": str(prec), "bestmatch_recall_bp": str(rec), "dissim_repeat_search": search,
            "bin_dissimilarity_alpha0": "" if a0 is None else str(a0), "bin_dissimilarity_alpha1": "" if a1 is None else str(a1)}


def well_formed(svg):
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return False, str(exc)
    return root.tag.endswith("svg") and root.find("{http://www.w3.org/2000/svg}title") is not None, ""


rows = []
for i in range(6):
    s = f"S{i}"
    rows.append(row(s, "toolA", extra=10 + i, missing=40, split=0, join=0, norm=200, f1=0.80, a0=0.20, a1=0.30))
    rows.append(row(s, "toolB", extra=0, missing=0, split=30, join=20, norm=200, f1=0.81, a0=0.30, a1=0.20))
    rows.append(row(s, "toolC", extra=60, missing=60, split=10, join=10, norm=200, f1=0.40, a0=0.9, a1=0.8))
rows.append(row("S0", "assembler", 0, 0, 0, 0, 1, status="not_applicable_not_assembly_contigs"))
rows.append({"sample": "S9", "tool": "toolA", "dissim_status": "ok", "bin_dissimilarity": "", "dissim_norm": "200"})

print("data")
check("not-applicable and blank rows are left out", {r["tool"] for r in fig.usable(rows)} == {"toolA", "toolB", "toolC"}
      and len(fig.usable(rows)) == 18)
p = fig.parts_of(rows[0])
check("the four shares add up to the row's dissimilarity", near(sum(p.values()), float(rows[0]["bin_dissimilarity"]), 1e-6), p)
check("each share is its cost over the normaliser", near(p["extra"], 10 / 200) and near(p["missing"], 40 / 200)
      and p["merged"] == 0 and p["fragmented"] == 0)
check("over-merged is PlasEval's split cost and fragmented its join cost",
      near(fig.parts_of(rows[1])["merged"], 30 / 200) and near(fig.parts_of(rows[1])["fragmented"], 20 / 200))
agg = {e["tool"]: e for e in fig.aggregate(rows)}
check("per-tool means: toolA extra is the mean of 10..15 over 200", near(agg["toolA"]["extra"], 12.5 / 200)
      and agg["toolA"]["n"] == 6, agg["toolA"])
check("tools are ordered by mean dissimilarity, lowest first", [e["tool"] for e in fig.aggregate(rows)] == ["toolB", "toolA", "toolC"],
      [e["tool"] for e in fig.aggregate(rows)])
check("a tool with no usable row is not drawn", "assembler" not in agg)

print("charts")
a = fig.aggregate(rows)
heat, hidden = fig.sample_heatmap(rows)
matrix = [{"tool_a": "toolA", "tool_b": "toolB", "n_samples": "6", "mean_dissimilarity": "0.30"},
          {"tool_a": "toolA", "tool_b": "truth", "n_samples": "6", "mean_dissimilarity": "0.27"},
          {"tool_a": "toolB", "tool_b": "truth", "n_samples": "6", "mean_dissimilarity": "0.25"}]
charts = {"error bars": fig.tool_error_bars(a), "tool by part": fig.tool_error_heatmap(a),
          "precision/recall": fig.precision_recall(rows), "F1 vs agreement": fig.f1_vs_agreement(a, rows),
          "per-isolate composition": fig.sample_composition(rows), "isolate heatmap": heat,
          "agreement matrix": fig.agreement_matrix(matrix)}
for name, svg in charts.items():
    good, why = well_formed(svg)
    check(f"{name}: well-formed SVG with an accessible title", good, why)
check("every mark carries a tooltip", all("<title>" in svg for svg in charts.values()))
check("the error bars use one colour per error part", all(c in charts["error bars"] for _, _, _, c, _ in fig.PARTS))
check("the heatmap has no omitted isolates when few", hidden == 0)
check("agreement matrix includes the truth row and column", "truth" in charts["agreement matrix"])
check("one precision/recall panel per tool", charts["precision/recall"].count("mean: recall") == 3)

big = [row(f"X{i:03d}", t, 5, 5, 5, 5, 100) for i in range(150) for t in ("toolA", "toolB")]
svg_big, omitted = fig.sample_heatmap(big)
check("a long isolate list is cut to the hardest rows and says so", omitted == 150 - fig.MAX_HEATMAP_ROWS
      and well_formed(svg_big)[0])
na_cell = [r for r in rows if r["sample"] == "S5" and r["tool"] != "toolC"] + [row("S4", "toolC", 1, 1, 1, 1, 100)]
check("a missing isolate-tool pair is hatched, not drawn as zero", "fill='url(#na)'" in fig.sample_heatmap(na_cell)[0])

print("reading")
notes = fig.findings(a, rows)
check("names the lowest-dissimilarity tool", notes[0].startswith("toolB has the lowest"), notes[0])
check("says which error dominates each tool", any(n.startswith("toolA: the largest part of its error is missing contigs") for n in notes), notes)
check("close dissimilarities with close F1 are not called different",
      not any("nearly the same best-match F1" in n for n in notes), notes)
sim = [row(f"S{i}", "toolP", 10, 10, 0, 0, 200, f1=0.80) for i in range(4)] + [row(f"S{i}", "toolQ", 60, 60, 0, 0, 200, f1=0.81)
                                                                                 for i in range(4)]
check("flags tools with similar F1 but clearly different dissimilarity",
      any("toolP and toolQ have nearly the same best-match F1 (0.800 and 0.810) but differ in dissimilarity (0.100 and 0.600)" in n
          for n in fig.findings(fig.aggregate(sim), sim)), fig.findings(fig.aggregate(sim), sim))
stab = fig.alpha_stability(rows)
check("the length-exponent check finds that the order changes", stab and not stab["stable"], stab)
check("and says so, asking for the exponent to be reported", any("order changes with how contig length is weighted" in n for n in notes), notes)
stable = [row(f"S{i}", t, e, m, 0, 0, 100, a0=v, a1=v) for i in range(3) for t, e, m, v in (("x", 5, 5, 0.1), ("y", 20, 20, 0.4))]
check("a stable order is reported as stable", any("same whether contig length is ignored" in n for n in fig.findings(fig.aggregate(stable), stable)))
capped = [row("S1", "t", 5, 5, 0, 0, 100, search="capped")]
check("a capped repeat search is called out as an upper bound", any("upper bounds" in n for n in fig.findings(fig.aggregate(capped), capped)))

print("section")
html = fig.section_html(rows, matrix)
for title in ("Error profile by tool.", "Tool by error part.", "Precision against recall.", "F1 against agreement with the truth.",
              "Error composition per isolate.", "Isolate by tool.", "Do tools agree?", "Does the length exponent matter?"):
    check(f"section has: {title}", title in html)
check("section has the reading notes", "What the figures say" in html)
check("an empty run says why instead of drawing nothing", "No error profile" in fig.section_html([], None))
check("only not-applicable tools also says why", "No error profile" in fig.section_html(
    [row("S0", "asm", 0, 0, 0, 0, 1, status="not_applicable_not_assembly_contigs")], None))
evil = [row("S0", "<script>alert(1)</script>", 5, 5, 0, 0, 100)]
out = fig.section_html(evil, None)
check("tool names are escaped in text and tooltips", "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out)
check("the whole section parses with its SVGs", all(well_formed(s)[0] for s in
                                                    [x + "</svg>" for x in html.split("</svg>")[:-1] if "<svg" in x
                                                     for x in [x[x.index("<svg"):]]]))

print("comparison with the original program")
cmp_rows = [
    {"sample": "a", "tool": "t1", "bin_dissimilarity": "0.300000", "original_dissimilarity": "0.300000", "original_status": "ok"},
    {"sample": "b", "tool": "t1", "bin_dissimilarity": "0.400000", "original_dissimilarity": "0.405000", "original_status": "ok"},
    {"sample": "c", "tool": "t2", "bin_dissimilarity": "0.500000", "original_dissimilarity": "0.450000", "original_status": "ok", "dissim_repeat_search": "capped"},
    {"sample": "d", "tool": "t2", "bin_dissimilarity": "0.200000", "original_dissimilarity": "", "original_status": "timeout", "dissim_repeat_families": "79"},
    {"sample": "e", "tool": "t2", "bin_dissimilarity": "0.100000", "original_dissimilarity": "0.100000", "original_status": "ok"},
]
items = {i["sample"]: i for i in fig.comparison_rows(cmp_rows)}
check("each pair gets a verdict: agree, disagree, capped upper bound, or not compared",
      (items["a"]["verdict"], items["b"]["verdict"], items["c"]["verdict"], items["d"]["verdict"], items["e"]["verdict"])
      == ("agree", "disagree", "capped_upper_bound", "not_compared", "agree"), {k: v["verdict"] for k, v in items.items()})
page = fig.original_comparison_html(cmp_rows)
check("a disagreement makes the verdict FAIL and counts every outcome", "Comparison with the original PlasEval program: FAIL" in page
      and "4 of 5 isolate-tool pairs were compared" in page and "1 disagree" in page and "1 PlasBench upper bound(s)" in page, page[:400])
check("the pair that timed out is listed with its repeat families, not hidden", "Pairs the original program did not finish" in page and "<td>79</td>" in page)
check("the scatter is well-formed SVG with the diagonal", well_formed(page[page.index("<svg"):page.index("</svg>") + 6])[0] and "stroke-dasharray" in page)
agree_only = [r for r in cmp_rows if r["sample"] in ("a", "e")]
check("all compared pairs agreeing is PASS", "Comparison with the original PlasEval program: PASS" in fig.original_comparison_html(agree_only))
check("no original results says so, rather than showing nothing", "was not run on these bins" in fig.original_comparison_html([{"sample": "a", "tool": "t"}]))
check("every pair timing out is NOT RUN, never PASS", "NOT RUN" in fig.original_comparison_html(
    [{"sample": "a", "tool": "t", "bin_dissimilarity": "0.1", "original_dissimilarity": "", "original_status": "timeout"}]))

print("ALL BINNING ERROR CHART TESTS PASSED" if ok else "BINNING ERROR CHART TESTS FAILED")
sys.exit(0 if ok else 1)
