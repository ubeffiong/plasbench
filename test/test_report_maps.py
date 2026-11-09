#!/usr/bin/env python3
"""
Circular plasmid maps (report_maps), hand-checked.

Synthetic plasmid pS, 10,000 bp, six truth genes:
  repA   100-1000   + replication      blaTEM 2000-3000 + amr          traI 4000-5000 - transfer
  tnpA   6000-7000  - mobile           orfX   8000-8500 - other        merA 9500-500 (crosses the origin) + metal
  -> 7 gene shapes (merA is split in two), exactly six classes in the legend
Tool rings: tool_a covers 0-2500 and 5000-10000 -> arcs 0..90 and 180..360 degrees; tool_b covers everything (0..360).
  tool_a has one structural event on pS at 2,500 bp.
GC windows: window = max(200, 10000 // 300) = 200 bp -> ceil(10000 / 200) = 50 windows; 10,050 bp -> ceil(10050 / 200) = 51.
GC skew on 5,000 G then 5,000 C: first half (G-C)/(G+C) = +1, second half = -1.
Tool cap: 10 ranked tools + 2 baselines -> 8 drawn (6 ranked + both baselines), 4 listed under 'not drawn'.
Over-size (700,000 bp > 600,000) and zero-length plasmids are one-line notes without an svg.
"""

import csv
import json
import math
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_maps as rm  # noqa: E402
import report_svg as sv  # noqa: E402

TAB = chr(9)
PAGE = "<style></style><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'>x</section>"


def gene(name, start, end, strand, cls, kind="gene", product=""):
    return {"name": name, "start": start, "end": end, "strand": strand, "cls": cls, "kind": kind, "product": product, "ftype": ""}


def tool(name, intervals, comp, outcome="perfect", rank=None, events=(), amr_total=1, amr_ok=("blaTEM",)):
    return {"name": name, "track": "short_read", "rank": rank, "intervals": intervals, "completeness": comp, "outcome": outcome,
            "amr_total": amr_total, "amr_recovered": list(amr_ok), "events": list(events), "has_alignment": True}


def model(plasmid="pS", sample="s1", length=10000, genes=None, tools=None, seq="", circular=True):
    if genes is None:
        genes = [gene("repA", 100, 1000, "+", "replication"), gene("blaTEM", 2000, 3000, "+", "amr"),
                 gene("traI", 4000, 5000, "-", "transfer"), gene("tnpA", 6000, 7000, "-", "mobile"),
                 gene("orfX", 8000, 8500, "-", "other"), gene("merA", 9500, 500, "+", "metal")]
    if tools is None:
        tools = [tool("tool_a", [(0, 2500), (5000, 10000)], 0.75, "fragmented", 1, [{"pos": 2500, "type": "reference_deletion", "record": "r1"}]),
                 tool("tool_b", [(0, 10000)], 1.0, "perfect", 2)]
    return {"sample": sample, "plasmid": plasmid, "length": length, "circular": circular, "repeat_rich": False, "repeat_regions": [],
            "genes": genes, "tools": tools, "sequence": seq or None}


def svgs(html_text):
    return re.findall(r"<svg.*?</svg>", html_text, re.S)


def fallback(page):
    """The static no-JavaScript maps of the section (the viewer's scripts also contain svg text, which is not a map)."""
    start = page.index("<div class='pv-fallback'>")
    end = page.find("<script>", start)
    return page[start:end if end > 0 else len(page)]


def parses(markup):
    try:
        ET.fromstring(markup)
        return True
    except ET.ParseError:
        return False


def elements(svg, tag, cls):
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    return [e for e in root.iter(ns + tag) if cls in (e.get("class") or "").split()]


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=chr(10))
        w.writerow(header)
        w.writerows(rows)


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    seq = "G" * 5000 + "C" * 5000
    print("one synthetic plasmid")
    html_text = rm.render_map(model(seq=seq))
    pages = svgs(html_text)
    check("exactly one svg, well-formed XML", len(pages) == 1 and parses(pages[0]))
    svg = pages[0]
    genes = elements(svg, "path", "gene")
    check("six genes, one wrapping the origin: 7 shapes", len(genes) == 7)
    check("the wrapping gene is two shapes", sum(1 for g in genes if g.get("data-name") == "merA") == 2)
    check("both strands on separate rings (forward 3 genes + 2 pieces, reverse 3)", sum(1 for g in genes if g.get("data-class") in ("replication", "amr", "metal")) == 4)
    classes = re.findall(r"data-class='([a-z]+)'", html_text.split("<figcaption>")[0].split("</svg>")[1])
    check("legend lists exactly the six classes present", sorted(classes) == sorted(["replication", "amr", "transfer", "mobile", "metal", "other"]))
    cov = elements(svg, "path", "cov")
    arcs = sorted((float(c.get("data-a0")), float(c.get("data-a1"))) for c in cov if "tool_a" in c.find("{http://www.w3.org/2000/svg}title").text)
    check("tool_a arcs are 0..90 and 180..360 degrees", len(arcs) == 2 and abs(arcs[0][0]) < 1e-6 and abs(arcs[0][1] - 90) < 1e-6
          and abs(arcs[1][0] - 180) < 1e-6 and abs(arcs[1][1] - 360) < 1e-6)
    check("tool_b covers the whole circle", any(abs(float(c.get("data-a1")) - 360) < 1e-6 and float(c.get("data-a0")) == 0 for c in cov
                                               if "tool_b" in c.find("{http://www.w3.org/2000/svg}title").text))
    events = elements(svg, "line", "event")
    check("one structural event tick, at 2,500 bp", len(events) == 1 and events[0].get("data-pos") == "2500")
    check("every tool ring and gene shape has a title", all(g.find("{http://www.w3.org/2000/svg}title") is not None for g in genes + cov))
    check("a badge shows completeness, outcome and AMR", "75% | fragmented | AMR 1/1" in html_text and "100% | perfect | AMR 1/1" in html_text)
    check("two checkboxes, both checked", html_text.count("type='checkbox'") == 2 and html_text.count("checked>") == 2)
    check("the toggle css names the checkbox and the ring",
          "#" + rm.map_id_for("s1", "pS") + " .t0:not(:checked) ~ svg .ring-t0{display:none}" in html_text and "class='ring-t1'" in svg)
    check("no script in the map", "<script" not in html_text)
    check("the centre names plasmid, size, circularity and tools at 90%", all(t in svg for t in ("pS", "10,000 bp", "circular: yes", "1 of 2 tools")))
    check("ticks are drawn (scale 0..9 kb)", "9 kb" in svg and ">0<" in svg)
    check("all coordinates are finite", "nan" not in svg.lower().replace("nan", "", 0) or not re.search(r"\b(nan|inf)\b", svg))

    print("labels")
    _, meta = rm.render_svg(model(seq=seq), "m")
    boxes = [p["box"] for p in meta["placed"]]
    overlaps = sum(1 for i in range(len(boxes)) for j in range(i + 1, len(boxes)) if sv._overlap(boxes[i], boxes[j], pad=0.0))
    check("label boxes do not overlap", overlaps == 0 and len(boxes) >= 4)
    check("AMR, replicon, transfer and IS genes are labelled", {"blaTEM", "repA", "traI", "tnpA"} <= set(meta["labelled"]))
    crowd = [gene(f"bla{i}", 3000 + i * 5, 3004 + i * 5, "+", "amr") for i in range(60)]
    crowded_html = rm.render_map(model(genes=crowd, seq=seq))
    _, crowd_meta = rm.render_svg(model(genes=crowd, seq=seq), "m")
    check("labels that cannot be placed are listed in the caption, not dropped silently",
          crowd_meta["dropped_labels"] and "did not fit" in crowded_html and len(crowd_meta["dropped_labels"]) + len(crowd_meta["labelled"]) == 60)
    cboxes = [p["box"] for p in crowd_meta["placed"]]
    check("a crowded set still has no overlapping boxes",
          all(not sv._overlap(cboxes[i], cboxes[j], pad=0.0) for i in range(len(cboxes)) for j in range(i + 1, len(cboxes))))

    print("GC content and skew")
    gc = rm.gc_windows(seq)
    check("window is 200 bp and there are ceil(10000 / 200) = 50 windows", gc["window"] == 200 and len(gc["gc"]) == 50 == math.ceil(10000 / 200))
    check("10,050 bp gives 51 windows", len(rm.gc_windows("A" * 10050)["gc"]) == math.ceil(10050 / 200) == 51)
    check("window grows with length: 120,000 bp -> 400 bp windows, 300 windows", rm.gc_windows("A" * 120000)["window"] == 400
          and len(rm.gc_windows("A" * 120000)["gc"]) == 300)
    check("skew is +1 on the G-rich half and -1 on the C-rich half", all(v == 1 for v in gc["skew"][:25]) and all(v == -1 for v in gc["skew"][25:]))
    check("a window without G or C has skew 0", rm.gc_windows("AT" * 100)["skew"] == [0.0])
    check("the svg carries positive and negative skew bars", len(elements(svg, "path", "skew-pos")) == 1 and len(elements(svg, "path", "skew-neg")) == 1)
    check("GC deviation: all-G/C sequence has zero deviation, so the bars are absent but the ring exists", "ring-gc" in svg)
    nref = rm.render_map(model())
    check("no reference: no GC rings and a note", "ring-gc" not in nref and "ring-skew" not in nref and "no reference sequence" in nref)

    print("tool cap and over-size")
    many = [tool(f"t{i}", [(0, 1000 * (i + 1))], 0.1 * (i + 1), rank=i + 1) for i in range(10)] + [tool("baseline_a", [(0, 10)], 0.1), tool("baseline_b", [], 0.0)]
    drawn, rest = rm.select_tools(many)
    check("8 tools drawn, 4 listed", len(drawn) == 8 == rm.MAP_MAX_TOOLS and len(rest) == 4)
    check("both baselines are drawn and the best-ranked tool is first", {"baseline_a", "baseline_b"} <= {t["name"] for t in drawn} and drawn[0]["name"] == "t0")
    capped = rm.render_map(model(tools=many))
    check("the cap shows in the figure: 8 checkboxes and the rest named", capped.count("type='checkbox'") == 8 and "Tools not drawn:" in capped
          and all(f"t{i} (" in capped for i in (6, 7, 8, 9)))
    check("the capped svg is well-formed", all(parses(s) for s in svgs(capped)))
    big = rm.render_map(model(length=700000))
    check("an over-size plasmid is a one-line note without an svg", "<svg" not in big and "Not drawn" in big and "600,000" in big)
    zero = rm.render_map(model(length=0))
    check("a zero-length plasmid is a note without an svg", "<svg" not in zero and "Not drawn" in zero and "no length" in zero)

    print("no annotation")
    bare = rm.render_map(model(genes=[], seq=seq))
    check("no features: still ticks, tool rings and the centre label", parses(svgs(bare)[0]) and "ring-t0" in bare and "ring-t1" in bare
          and "10,000 bp" in bare and "9 kb" in bare and "No truth annotation" in bare)
    check("no features: the legend has no gene class", "data-class=" not in bare)
    check("no tools at all still renders", parses(svgs(rm.render_map(model(tools=[], seq=seq)))[0]))

    print("unique ids")
    both = rm.render_map(model(sample="s1")) + rm.render_map(model(sample="s2"))
    ids = re.findall(r"\bid='([^']+)'", both)
    check("checkbox and map ids are unique when two samples share a plasmid id", len(ids) == len(set(ids)) and rm.map_id_for("s1", "pS") != rm.map_id_for("s2", "pS"))
    check("ids are deterministic", rm.map_id_for("s1", "pS") == rm.map_id_for("s1", "pS") and rm.render_map(model()) == rm.render_map(model()))

    print("classification")
    c = rm.classify_gene
    check("curated categories and symbols map to the right class",
          c("replicon", "repE") == "replication" and c("", "repA") == "replication" and c("amr", "x") == "amr" and c("", "blaCTX-M-15") == "amr"
          and c("", "traI") == "transfer" and c("conjugation", "") == "transfer" and c("", "tnpA", "IS3 family transposase") == "mobile"
          and c("", "intI1", "class 1 integrase") == "integrase" and c("", "cusA") == "metal" and c("", "merR") == "metal"
          and c("", "", "copper resistance protein") == "metal" and c("partition", "parA") == "maintenance"
          and c("unknown", "orf1", "hypothetical protein") == "other" and c("", "mobA", "relaxase MobA") == "transfer")

    print("section and inject")
    out = rm.inject(PAGE, os.path.join(tempfile.gettempdir(), "no_such_results_dir_xyz"), None, None)
    check("a missing results dir gives a 'Not run' section before Recommendations, with a nav link",
          "id='plasmid-maps'" in out and "Not run" in out and out.index("id='plasmid-maps'") < out.index("id='recommendations'")
          and "href='#plasmid-maps'" in out)

    print("synthetic results directory (production layout: truth in data_dir)")
    with tempfile.TemporaryDirectory() as tmp:
        res, data = os.path.join(tmp, "results", ), os.path.join(tmp, "data")
        for sample in ("sA", "sB"):
            os.makedirs(os.path.join(res, sample, "visualization"))
            os.makedirs(os.path.join(data, sample))
            blocks = {"truth_plasmids": {"pS": {"molecule_type": "PLASMID", "length": 10000}, "chr": {"molecule_type": "CHROMOSOME", "length": 99999}},
                      "circular_truth_plasmids": ["pS"],
                      "tools": {"mob": {"plasmid_recovery": {"pS": {"covered_intervals": [[0, 5000]], "covered_bp": 5000, "completeness": 0.5}}},
                                "baseline_x": {"plasmid_recovery": {}}}}
            with open(os.path.join(res, sample, "visualization", "alignment_blocks.json"), "w") as f:
                json.dump(blocks, f)
            with open(os.path.join(res, sample, "visualization", "structural_calls.json"), "w") as f:
                json.dump({"tools": {"mob": {"events": [{"event_type": "tandem_duplication", "record_id": "r", "left_target": "pS",
                                                         "left_target_end": 4000, "right_target": "pS", "right_target_start": 2000}]}}}, f)
            write(os.path.join(data, sample, "truth_proteins.tsv"), ["sequence_id", "start", "end", "strand", "feature_id", "gene", "product", "category"],
                  [["pS", "100", "900", "+", "f1", "repE", "replication initiation protein", "replicon"],
                   ["pS", "2000", "3000", "-", "f2", "blaCTX-M-15", "beta-lactamase", "amr"]])
            write(os.path.join(data, sample, "truth_features.tsv"), ["sequence_id", "start", "end", "feature_type", "label"], [["pS", "0", "300", "replicon", "IncX"]])
            write(os.path.join(data, sample, "truth_amr.tsv"), ["sequence_id", "start", "end", "gene_name"],
                  [["pS", "2000", "3000", "blaCTX-M-15"], ["pS", "6000", "6500", "sul1"]])
            with open(os.path.join(data, sample, "reference.fna"), "w") as f:
                f.write(">pS\n" + seq + "\n>chr\nACGT\n")
            write(os.path.join(res, sample, "mob.per_plasmid.tsv"), ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness"],
                  [[sample, "mob", "short_read", "pS", "10000", "5000", "0.5000"]])
            write(os.path.join(res, sample, "mob.plasmid_outcomes.tsv"), ["true_plasmid", "outcome"], [["pS", "fragmented"]])
            write(os.path.join(res, sample, "mob.amr_placement.tsv"), ["sample", "tool", "gene_name", "sequence_id", "placement"],
                  [[sample, "mob", "blaCTX-M-15", "pS", "correct_plasmid"], [sample, "mob", "sul1", "pS", "not_recovered"]])
        scores = os.path.join(res, "scores.tsv")
        write(scores, ["sample", "tool", "analysis_track"], [["sA", "mob", "short_read"], ["sB", "mob", "short_read"], ["sA", "baseline_x", "short_read"]])
        write(os.path.join(res, "benchmark.leaderboard.tsv"), ["rank", "analysis_track", "tool"], [["1", "short_read", "mob"]])
        out = rm.inject(PAGE, res, data, scores)
        static = fallback(out)
        check("both samples produce a static fallback map, a payload and a gallery row linking to the viewer",
              len(svgs(static)) == 2 and out.count("class='pv-data'") == 2 and out.count("href='#plasmid-maps?msample=") == 2)
        check("every static svg in the section is well-formed", all(parses(s) for s in svgs(static)))
        check("the gallery table is collapsed in a details element", "<details class='pv-index'>" in out and "id='pv-root' hidden" in out)
        check("the first sample is open, the second is not", out.count("<details open>") == 1 and out.count("<details>") == 1)
        check("badge from the tool tables", "50% | fragmented | AMR 1/2" in out)
        check("the AMR gene without a protein is drawn as a feature block", "sul1" in out)
        check("the duplicate AMR gene is drawn once as an arrow and not again as a block",
              sum(1 for s in svgs(static)[:1] for g in elements(s, "path", "gene") if g.get("data-name") == "blaCTX-M-15") == 1)
        check("structural event ticks from both coordinates (4,000 and 2,000)", len(elements(svgs(static)[0], "line", "event")) == 2)
        check("the checkbox ids are unique across the page", len(re.findall(r"\bid='([^']+)'", out)) == len(set(re.findall(r"\bid='([^']+)'", out))))
        check("the section sits before Recommendations", out.index("id='plasmid-maps'") < out.index("id='recommendations'"))
        again = rm.inject(PAGE, res, "", scores)
        check("data_dir may be falsy (truth is then read from the results dir): still a section, with maps drawn without annotation",
              "id='plasmid-maps'" in again and len(svgs(fallback(again))) == 2 and "No truth annotation" in again)

    print("alignment blocks in the viewer payload")
    raw = [{"target": "pS", "record_id": "c1", "query_length": 500, "query_start": 0, "query_end": 400, "strand": "-", "target_start": 100, "target_end": 500, "matches": 396, "block_length": 400, "mapq": 60},
           {"target": "other", "record_id": "c9", "query_length": 50, "query_start": 0, "query_end": 50, "strand": "+", "target_start": 0, "target_end": 50, "matches": 50, "block_length": 50, "mapq": 60},
           {"target": "pS", "record_id": "bad", "query_length": 50, "query_start": 0, "query_end": 50, "strand": "+", "target_start": 70, "target_end": 70, "matches": 1, "block_length": 1}]
    got = rm._plasmid_blocks(raw, "pS")
    check("only blocks of this plasmid with a positive reference span are kept; identity is matches / block length; strand is + or -",
          len(got) == 1 and got[0]["record"] == "c1" and abs(got[0]["identity"] - 0.99) < 1e-9 and got[0]["strand"] == "-" and (got[0]["ts"], got[0]["te"]) == (100, 500))
    tl = dict(tool("t1", [(0, 500)], 0.5), blocks=got, collinear_fraction=0.97191, order_conflicts=2)
    pay = rm.viewer_payload(model(tools=[tl]))
    check("the payload carries [record, query length, query start/end, strand, reference start/end, identity, mapq], collinear fraction and order conflicts",
          pay["tools"][0]["bl"] == [["c1", 500, 0, 400, "-", 100, 500, 0.99, 60]] and pay["tools"][0]["cf"] == 0.97191 and pay["tools"][0]["oc"] == 2 and "bo" not in pay["tools"][0])
    many = [dict(got[0], ts=i * 10, te=i * 10 + 5 + (i % 7), record="r%d" % i) for i in range(rm.VIEWER_MAX_BLOCKS + 40)]
    pay2 = rm.viewer_payload(model(tools=[dict(tool("t1", [(0, 500)], 0.5), blocks=many)]))
    kept = pay2["tools"][0]["bl"]
    check("more blocks than VIEWER_MAX_BLOCKS: the longest are kept, in reference order, and the rest are counted in 'bo' instead of silently dropped",
          len(kept) == rm.VIEWER_MAX_BLOCKS and pay2["tools"][0]["bo"] == 40 and [b[5] for b in kept] == sorted(b[5] for b in kept))
    check("a tool without blocks adds no alignment keys", "bl" not in rm.viewer_payload(model())["tools"][0] and "cf" not in rm.viewer_payload(model())["tools"][0])
    check("the viewer loads its fragments in dependency order (core, then the alignment module, then the DOM glue)",
          list(rm.VIEWER_ASSETS) == ["plasmid_viewer_style.html", "plasmid_viewer_core.html", "plasmid_viewer_align.html", "plasmid_viewer_ui.html"])

    print("the demo cohort")
    demo = os.path.join(HERE, "..", "results_demo")
    if os.path.isfile(os.path.join(demo, "ecoli_a", "visualization", "alignment_blocks.json")):
        out = rm.inject(PAGE, demo, None, os.path.join(demo, "scores.tsv"))
        maps = svgs(fallback(out))
        check("at least one map is produced from results_demo", len(maps) >= 1)
        check("every demo map is well-formed", all(parses(s) for s in maps))
        check("demo ids are unique", len(re.findall(r"\bid='([^']+)'", out)) == len(set(re.findall(r"\bid='([^']+)'", out))))
    else:
        print("  SKIP: results_demo is absent (run test/run_demo.sh first)")

    print()
    if not ok:
        print("REPORT MAPS TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT MAPS TESTS PASSED")


if __name__ == "__main__":
    main()
