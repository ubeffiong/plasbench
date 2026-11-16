#!/usr/bin/env python3
"""report_amr_regions.py: resistance regions drawn from the per-gene AMR placement tables, with context, tool lanes, verdicts and interactions."""

import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
import report_amr_regions as ar  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


FIELDS = ["sample", "tool", "copy_id", "gene_name", "gene_class", "sequence_id", "start", "end", "covering_record", "assigned_bin", "matched_plasmid",
          "placement", "replicon_type_correct", "flank_covered", "plasmid_cprr_correct", "plasmid_cprr_correct_no_identity", "truth_evidence_tier",
          "evaluation_task", "attribution", "attribution_mode"]


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=header, delimiter=TAB, lineterminator=NL)
        w.writeheader()
        w.writerows(rows)


GENES = [("c1", "blaTEM-1", "beta-lactamase", 1000, 1800), ("c2", "aadA1", "aminoglycoside", 2200, 3000), ("c3", "sul1", "sulfonamide", 40000, 40800)]


def rows_for(sample, tool, placements, flanks, mode="bin_matching"):
    out = []
    for (cid, name, cls, s, e), p, f in zip(GENES, placements, flanks):
        out.append({"sample": sample, "tool": tool, "copy_id": cid, "gene_name": name, "gene_class": cls, "sequence_id": "P1", "start": s, "end": e,
                    "placement": p, "flank_covered": f, "attribution_mode": mode})
    return out


tmp = tempfile.mkdtemp(prefix="arreg_")
try:
    res, data = os.path.join(tmp, "results"), os.path.join(tmp, "data")
    write(os.path.join(res, "S1", "toolA.amr_placement.tsv"), FIELDS, rows_for("S1", "toolA", ["correct_plasmid"] * 3, ["yes"] * 3))
    write(os.path.join(res, "S1", "toolB.amr_placement.tsv"), FIELDS, rows_for("S1", "toolB", ["correct_plasmid", "wrong_plasmid", "not_recovered"], ["yes", "no", "no"]))
    write(os.path.join(res, "S1", "toolC.amr_placement.tsv"), FIELDS, rows_for("S1", "toolC", ["correct_plasmid"] * 3, ["yes"] * 3, "contig_attribution"))
    write(os.path.join(data, "S1", "truth_features.tsv"), ["sequence_id", "start", "end", "feature_type", "label", "source", "version"],
          [{"sequence_id": "P1", "start": 1800, "end": 2200, "feature_type": "insertion_sequence", "label": "IS26"},
           {"sequence_id": "P1", "start": 900, "end": 1000, "feature_type": "gene", "label": "intI1"},
           {"sequence_id": "P1", "start": 3000, "end": 3400, "feature_type": "gene", "label": "merA"},
           {"sequence_id": "P1", "start": 41000, "end": 41300, "feature_type": "replicon", "label": "IncFII"},
           {"sequence_id": "P1", "start": 90000, "end": 91000, "feature_type": "insertion_sequence", "label": "IS1"},
           {"sequence_id": "P1", "start": 1100, "end": 1200, "feature_type": "gene", "label": "hypothetical protein"}])
    regions, tools, per, modes = ar.load(res, data)
    check("three genes on one plasmid form two regions (2 kb apart together, 37 kb apart separate)", len(regions) == 2 and [len(r["genes"]) for r in regions] == [2, 1], [len(r["genes"]) for r in regions])
    check("three tools are found, and the non-binning one is marked as attributed", tools == ["toolA", "toolB", "toolC"] and modes["toolC"] == "contig_attribution", (tools, modes))
    ctx = {c["label"]: c["cls"] for c in regions[0]["context"]}
    check("context is classified by feature type and label (IS, integrase, metal), unrelated genes are left out",
          ctx.get("IS26") == "mobile" and ctx.get("intI1") == "integrase" and ctx.get("merA") == "metal" and "hypothetical protein" not in ctx, ctx)
    check("features outside the region are not drawn in it", "IS1" not in ctx and "IncFII" not in ctx)
    r0 = regions[0]
    v = lambda t: ar.verdict([per[("S1", t)][g["copy_id"]] for g in r0["genes"]], modes[t])  # noqa: E731
    check("every gene on the correct plasmid with flanks covered is intact for a binning tool", v("toolA")[0] == "intact", v("toolA"))
    check("a wrong-plasmid gene makes the region partial", v("toolB")[0] == "partial", v("toolB"))
    check("a non-binning tool is 'attributed', never 'intact'", v("toolC")[0] == "attributed", v("toolC"))
    lost = ar.verdict([{"placement": "not_recovered", "flank_covered": "no"}, {"placement": "wrong_plasmid", "flank_covered": ""}], "bin_matching")
    check("no gene on the correct plasmid is lost", lost[0] == "lost")
    check("an unevaluated flank does not block intact", ar.verdict([{"placement": "correct_plasmid", "flank_covered": ""}], "bin_matching")[0] == "intact")
    check("no rows at all is 'not scored', not a pass", ar.verdict([], "bin_matching")[0] == "not scored")

    page = "<html><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></html>"
    out = ar.inject(page, res, data)
    check("the section and its navigation link are added before Recommendations", "id='learn-amrregions'" in out and "href='#learn-amrregions'" in out
          and out.index("learn-amrregions") < out.index("id='recommendations'"))
    check("each region has a table with the numbers behind the picture", out.count("Numbers for this region") == 2 and "Correct plasmid" in out and "Flank covered" in out)
    check("controls: region choice, tool toggles, class filter, zoom", "class='ar-select'" in out and out.count("class='ar-tool'") == 3 and "class='ar-cls'" in out and "class='ar-zoom'" in out)
    check("every gene and mark carries its details for the hover panel and is keyboard focusable", "data-info=" in out and "tabindex='0'" in out)
    check("placement is a shape and a word, not only a colour", "wrong plasmid" in out and "not recovered" in out and "<title>toolB: aadA1 wrong plasmid" in out)
    check("the summary chart counts regions per tool", "regions" in out and "aria-label='Resistance regions by verdict for each tool'" in out)
    f_html, f_rows = ar.funnel(regions, tools, per, modes)
    fa = {r[0]: r for r in f_rows}
    check("the funnel keeps only what the step before kept (genes, recovered, correct plasmid, flank, intact regions)",
          fa["toolA"][1:] == (3, 3, 3, 3, 2, 2) and fa["toolB"][1:] == (3, 2, 1, 1, 0, 2) and "Where resistance information is lost" in out, (fa["toolA"], fa["toolB"]))
    check("the non-binning caveat is shown", "attributed record by record" in out and "toolC" in out)

    svgs = re.findall(r"<svg\b.*?</svg>", out, flags=re.S)
    bad = []
    for s in svgs:
        try:
            ET.fromstring(s)
        except ET.ParseError as exc:
            bad.append(str(exc))
    check("every drawing is well-formed SVG", svgs and not bad, bad[:2])

    script = re.search(r"<script>(.*?)</script>", out, flags=re.S).group(1)
    node = shutil.which("node")
    if node:
        path = os.path.join(tmp, "s.js")
        open(path, "w", encoding="utf-8").write(script)
        done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        check("the page script is valid JavaScript", done.returncode == 0, done.stderr[-300:])
    check("the script keeps the page readable without it (regions are hidden only once it runs)", "classList.add('ar-js')" in script and ".ar.ar-js .ar-region{display:none}" in out)

    write(os.path.join(res, "S2", "toolA.amr_placement.tsv"), FIELDS, [dict(rows_for("S2", "toolA", ["correct_plasmid"], ["yes"])[0], gene_name="<script>x</script>", sequence_id="<b>P</b>")])
    esc_out = ar.inject(page, res, data)
    check("gene and sequence names are escaped everywhere", "<script>x</script>" not in esc_out.replace(script, "") and "<b>P</b>" not in esc_out)

    empty = ar.inject(page, os.path.join(tmp, "nothing"), None)
    check("with no AMR placement tables the section says it was not run and why", "Not run" in empty and "amr_placement.tsv" in empty and "learn-amrregions" in empty)
    check("a feature table missing or malformed does not stop the section", "AMR regions" in ar.inject(page, res, os.path.join(tmp, "no-such-data")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL AMR REGION TESTS PASSED" if ok else "AMR REGION TESTS FAILED")
sys.exit(0 if ok else 1)
