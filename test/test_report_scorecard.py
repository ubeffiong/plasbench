#!/usr/bin/env python3
"""
Weighted scorecard, hand-checked.

  transform A1 (percent; 99.9 / 99.0 / 95.0 / 90 -> 100 / 85 / 60 / 0):
    99.45 -> 85 + 15 * (0.45 / 0.9) = 92.5;  100 -> 100 (clamped);  97 -> 60 + 25 * (2 / 4) = 72.5;  80 -> 0
  lower is better A2 (0.1 / 0.5 / 2.0 / 10 -> 100 / 85 / 60 / 0):  0.3 -> 92.5;  1.25 -> 72.5;  50 -> 0
  bands are inclusive at the edge: 99.0 is Good, 98.999 is Moderate; for lower-is-better 0.5 is Good, 0.5001 is Moderate
  renormalisation: every metric at its Good threshold scores 85, B1 (weight 10) at Excellent scores 100, A4 (10) and C2 (7)
    unavailable.  scored weight 83 -> share 0.83;  sum(w*s) = 85 * 73 + 100 * 10 = 7205;  overall = 7205 / 83 = 86.807
    a tool also missing D3 (weight 5): weight 78, sum = 7205 - 425 = 6780, overall = 86.923, share 0.78 (only this tool changes)
  fixture, tool t1 over samples s1 and s2 (aligned columns 1000 and 3000):
    A1 identity   (0.999 * 1000 + 0.99 * 3000) / 4000 = 0.99225 -> 99.225 percent, score 85 + 15 * (0.225 / 0.9) = 88.75
    A2 mismatch   (0.0005 * 1000 + 0.005 * 3000) / 4000 = 0.003875 -> 0.3875 per 100 columns
    A3 indel      ins (0.3 + 6) / 4000 = 0.001575, del (0.2 + 9) / 4000 = 0.0023 -> 1 - 0.003875 = 99.6125 percent
    B1 recall (1.0 + 0.8) / 2 = 0.9;  B2 (1.0 + 0.5) / 2 = 0.75;  B3 0.75;  C3 only s1 has circular truth -> 1.0;  D1 0.95
    C1 NGOC (8 + 1) / (10 + 10) = 0.45
    C4 repeat-rich plasmid pA of s1 has completeness 0.6 -> 0.6
    E1 120 s -> 100 - 15 * (60 / 240) = 96.25;  E2 4 GB -> 100 - 15 * (2 / 6) = 95;  E3 1.0 -> 100
  scenarios: s1 multi_plasmid + annotated (complex and annotated), s2 simple (50x), s3 low_depth, s4 20x (not simple, not
    challenging by tag, but read_quality_band low -> challenging), s5 repeat_rich;  complex {s1, s5}, annotated {s1},
    simple {s2}, challenging {s3, s4}
"""

import csv
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_common as rc  # noqa: E402
import report_scorecard as sc  # noqa: E402

PAGE = ("<main><nav><a href='#recommendations'>Recommendations</a></nav><section id='composite'>c</section>"
        "<section id='recommendations'>x</section></main>")
TAB = chr(9)


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=chr(10))
        w.writerow(header)
        w.writerows(rows)


def fixture(tmp):
    scores = os.path.join(tmp, "scores.tsv")
    write(scores, ["sample", "tool", "analysis_track", "recall", "plasmid_recall_ge90", "plasmid_recall",
                   "complete_circular_plasmid_recall", "amr_gene_recall"],
          [["s1", "t1", "short_read", "1.0", "1.0", "1.0", "1.0", "1.0"],
           ["s2", "t1", "short_read", "0.8", "0.5", "0.5", "", "0.9"]])
    write(os.path.join(tmp, "benchmark.accuracy.tsv"),
          ["sample", "tool", "analysis_track", "aligned_columns", "identity", "mismatch_rate", "insertion_rate", "deletion_rate"],
          [["s1", "t1", "short_read", "1000", "0.999", "0.0005", "0.0003", "0.0002"],
           ["s2", "t1", "short_read", "3000", "0.99", "0.005", "0.002", "0.003"]])
    write(os.path.join(tmp, "benchmark.ngoc.tsv"), ["sample", "tool", "analysis_track", "ngoc_features", "n_pairs", "n_conserved", "ngoc"],
          [["s1", "t1", "short_read", "5", "10", "8", "0.8"], ["s2", "t1", "short_read", "5", "10", "1", "0.1"]])
    write(os.path.join(tmp, "benchmark.feature_preservation.tsv"),
          ["sample", "tool", "analysis_track", "feature_kind", "n_expected", "n_full_length", "n_truncated", "n_missed",
           "full_length_rate", "mean_covered_fraction"],
          [["s1", "t1", "short_read", "amr", "2", "2", "0", "0", "1.0", "1.0"],
           ["s1", "t1", "short_read", "replicon", "2", "1", "1", "0", "0.5", "0.5"],
           ["s1", "t1", "short_read", "all", "4", "3", "1", "0", "0.75", "0.75"]])
    write(os.path.join(tmp, "benchmark.performance.tsv"),
          ["tool", "success_rate", "median_runtime_seconds", "median_peak_memory_gb"], [["t1", "1.0", "120", "4"]])
    write(os.path.join(tmp, "benchmark.repeat_content.tsv"),
          ["sample", "sequence_id", "molecule_type", "length", "repeat_rich"],
          [["s1", "pA", "PLASMID", "90000", "yes"], ["s1", "pB", "PLASMID", "8000", "no"], ["s2", "pC", "PLASMID", "5000", "no"]])
    write(os.path.join(tmp, "s1", "t1.per_plasmid.tsv"), ["sample", "tool", "analysis_track", "sequence_id", "completeness"],
          [["s1", "t1", "short_read", "pA", "0.6"], ["s1", "t1", "short_read", "pB", "1.0"]])
    write(os.path.join(tmp, "benchmark.scenarios.tsv"),
          ["sample", "scenario", "tags", "n_plasmids", "read_depth_x"],
          [["s1", "complex", "multi_plasmid,annotated", "2", "100"], ["s2", "simple", "", "1", "50"],
           ["s3", "challenging", "low_depth", "1", "10"], ["s4", "simple", "", "1", "20"],
           ["s5", "complex", "repeat_rich", "1", "80"]])
    write(os.path.join(tmp, "samples.tsv"), ["sample_id", "read_quality_band"], [["s4", "low"]])
    return scores


def parses(markup):
    try:
        ET.fromstring(markup)
        return True
    except ET.ParseError:
        return False


def close(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    def raises(fn):
        try:
            fn()
        except ValueError:
            return True
        return False

    print("config")
    specs = sc.load_config()
    by_id = {s["id"]: s for s in specs}
    check("the shipped config loads: 17 metrics, weights sum to 100", len(specs) == 17 and close(sum(s["weight"] for s in specs), 100))
    check("A4 and C2 have no invented bands: status undefined, thresholds blank",
          all(by_id[k]["status"] == "undefined" and by_id[k]["excellent"] is None and by_id[k]["floor"] is None for k in ("A4", "C2")))
    check("an undefined metric cannot be graded even if given a value",
          sc.score_value(by_id["A4"], 0.97) == (None, None) and sc.band_of(by_id["A4"], 0.97) is None)
    inv = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in specs]
    [r for r in inv if r["id"] == "A4"][0]["excellent"] = "0.99"
    check("an undefined metric with a threshold filled in is rejected", raises(lambda: sc.validate_config(inv)))
    check("A4 and C2 are present with their weights (10 and 7)", by_id["A4"]["weight"] == 10 and by_id["C2"]["weight"] == 7)
    rows = rc.read_tsv(sc.DEFAULT_CONFIG)
    bad = [dict(r) for r in rows]
    bad[0]["weight"] = "11"
    check("weights not summing to 100 are rejected", raises(lambda: sc.validate_config(bad)))
    dup = [dict(r) for r in rows]
    dup[1]["id"] = dup[0]["id"]
    check("a duplicate id is rejected", raises(lambda: sc.validate_config(dup)))
    mis = [dict(r) for r in rows]
    mis[0]["good"] = "99.95"
    check("misordered thresholds (higher-is-better) are rejected", raises(lambda: sc.validate_config(mis)))
    mis2 = [dict(r) for r in rows]
    a2 = [r for r in mis2 if r["id"] == "A2"][0]
    a2["good"] = "0.05"
    check("misordered thresholds (lower-is-better) are rejected", raises(lambda: sc.validate_config(mis2)))
    stat = [dict(r) for r in rows]
    stat[0]["status"] = "maybe"
    check("an unknown status is rejected", raises(lambda: sc.validate_config(stat)))
    check("A1 carries the stated bands 99.9 / 99 / 95 / 90 and is fixed",
          (by_id["A1"]["excellent"], by_id["A1"]["good"], by_id["A1"]["moderate"], by_id["A1"]["floor"]) == (99.9, 99.0, 95.0, 90.0)
          and by_id["A1"]["status"] == "fixed")

    print("score transform")
    a1 = by_id["A1"]
    for value, expected in ((99.9, 100), (99.0, 85), (95.0, 60), (90, 0), (99.45, 92.5), (100, 100), (97, 72.5), (80, 0)):
        check(f"A1 {value} -> {expected}", close(sc.score_value(a1, value)[0], expected))
    a2 = by_id["A2"]
    for value, expected in ((0.1, 100), (0.5, 85), (2.0, 60), (10, 0), (0.3, 92.5), (1.25, 72.5), (50, 0), (0.0, 100)):
        check(f"A2 {value} -> {expected} (lower is better)", close(sc.score_value(a2, value)[0], expected))
    check("no value gives no score", sc.score_value(a1, None) == (None, None))
    check("band edges inclusive (higher)", [sc.score_value(a1, v)[1] for v in (99.9, 99.0, 95.0, 94.999, 98.999)]
          == ["excellent", "good", "moderate", "poor", "moderate"])
    check("band edges inclusive (lower)", [sc.score_value(a2, v)[1] for v in (0.1, 0.5, 2.0, 2.0001, 0.5001)]
          == ["excellent", "good", "moderate", "poor", "moderate"])
    check("overall bands at 90 / 75 / 55", [sc.overall_band(v) for v in (90, 89.99, 75, 55, 54.9)]
          == ["excellent", "good", "good", "moderate", "poor"])

    print("renormalisation")
    values = {s["id"]: {"value": s["good"], "reason": ""} for s in specs}
    values["B1"]["value"] = by_id["B1"]["excellent"]
    values["A4"] = {"value": None, "reason": "no truth variants"}
    values["C2"] = {"value": None, "reason": "no truth variants"}
    res = sc.overall(specs, values)
    check("scored weight share 0.83", close(res["scored_share"], 0.83))
    check("overall = 7205 / 83", close(res["score"], 7205 / 83))
    check("not-available metrics listed with reasons", [i for i, _ in res["unavailable"]] == ["A4", "C2"] and res["unavailable"][0][1])
    check("not provisional at 0.83", not res["provisional"])
    values2 = dict(values)
    values2["D3"] = {"value": None, "reason": "no features"}
    res2 = sc.overall(specs, values2)
    check("a tool missing D3 as well: share 0.78, overall 6780 / 78", close(res2["scored_share"], 0.78) and close(res2["score"], 6780 / 78))
    check("the other tool is unchanged", close(res["score"], 7205 / 83))
    only_e = {s["id"]: {"value": None, "reason": "x"} for s in specs}
    only_e["E3"] = {"value": 1.0, "reason": ""}
    res3 = sc.overall(specs, only_e)
    check("a scored share below 0.5 is provisional (E3 alone: 3 / 100)", res3["provisional"] and close(res3["score"], 100))
    check("nothing scored: no overall", sc.overall(specs, {})["score"] is None)

    print("scenario membership")
    members = sc.scenario_membership(
        [{"sample": "s1", "tags": "multi_plasmid,annotated", "n_plasmids": "2", "read_depth_x": "100"},
         {"sample": "s2", "tags": "", "n_plasmids": "1", "read_depth_x": "50"},
         {"sample": "s3", "tags": "low_depth", "n_plasmids": "1", "read_depth_x": "10"},
         {"sample": "s4", "tags": "", "n_plasmids": "1", "read_depth_x": "20"},
         {"sample": "s5", "tags": "repeat_rich", "n_plasmids": "1", "read_depth_x": "80"},
         {"sample": "s6", "tags": "", "n_plasmids": "0", "read_depth_x": "90"}], {"s4": "low"})
    check("complex {s1, s5}", members["complex"] == {"s1", "s5"})
    check("annotated {s1}: a sample can be complex and annotated", members["annotated"] == {"s1"} and "s1" in members["complex"])
    check("simple {s2} (no complex tag, depth >= 30, has plasmids)", members["simple"] == {"s2"})
    check("challenging {s3, s4} (low_depth tag or read_quality_band low)", members["challenging"] == {"s3", "s4"})
    check("underpowered below 5 samples", sc.underpowered(4) and not sc.underpowered(5) and sc.SCORECARD_MIN_SAMPLES == 5)

    print("metric values on a hand-computed fixture")
    with tempfile.TemporaryDirectory() as tmp:
        scores = fixture(tmp)
        per_tool = sc.metric_values(tmp, scores)
        v = {k: x["value"] for k, x in per_tool[("short_read", "t1")].items()}
        for sid, expected in (("A1", 99.225), ("A2", 0.3875), ("A3", 99.6125), ("B1", 0.9), ("B2", 0.75), ("B3", 0.75), ("C1", 0.45),
                              ("C3", 1.0), ("C4", 0.6), ("D1", 0.95), ("D3", 0.75), ("E1", 120), ("E2", 4), ("E3", 1.0)):
            check(f"{sid} = {expected}", close(v[sid], expected))
        check("A4 and C2 not available, with a reason", v["A4"] is None and v["C2"] is None
              and "truth variant" in per_tool[("short_read", "t1")]["A4"]["reason"])
        check("D2 not available without predicted annotation, with a reason", v["D2"] is None
              and per_tool[("short_read", "t1")]["D2"]["reason"])
        check("A1 scores 88.75", close(sc.score_value(by_id["A1"], v["A1"])[0], 88.75))
        check("E1 scores 96.25 and E2 95", close(sc.score_value(by_id["E1"], v["E1"])[0], 96.25)
              and close(sc.score_value(by_id["E2"], v["E2"])[0], 95))
        only_s1 = sc.metric_values(tmp, scores, samples={"s1"})[("short_read", "t1")]
        check("restricted to s1: B1 = 1.0, A1 = 99.9, runtime not scored per scenario",
              close(only_s1["B1"]["value"], 1.0) and close(only_s1["A1"]["value"], 99.9) and only_s1["E1"]["value"] is None)
        res = sc.overall(specs, per_tool[("short_read", "t1")])
        check("scored share = (100 - A4 10 - C2 7 - D2 5) / 100 = 0.78", close(res["scored_share"], 0.78))

        print("injection")
        page = sc.inject(PAGE, tmp, scores)
        for sid, _ in sc.SECTIONS:
            check(f"section {sid} present and linked", f"id='{sid}'" in page and f"href='#{sid}'" in page)
        check("sections sit before Recommendations", page.index("id='scorecard'") < page.index("id='recommendations'"))
        check("says it is another view, never the ranking and links both targets",
              "never the ranking" in page and "href='#rank-robustness'" in page and "href='#composite'" in page)
        check("real values shown (99.2 identity, tool name)", "99.2" in page and ">t1<" in page)
        check("overall with its scored share 0.78", "0.78" in page)
        check("not-available metrics are shown as such", "n/a" in page and "truth variant" in page)
        check("definitions table carries the user's wording and a status column",
              "Example scoring definitions" in page and "<th>Status</th>" in page and ">proposed<" in page and ">fixed<" in page)
        check("scenario tables with counts and underpowered flags",
              "Complex: 2 isolates" in page and "Simple: 1 isolate" in page and "underpowered" in page)
        check("alignment-derived caveat shown", "alignment-derived, unvalidated" in page)
        svgs = [s.split("</svg>")[0] + "</svg>" for s in page.split("<svg")[1:]]
        svgs = ["<svg" + s for s in svgs]
        check("a profile strip per tool, valid XML, 17 bars with titles",
              len(svgs) == 1 and parses(svgs[0]) and svgs[0].count("<rect") == 17 and svgs[0].count("<title>") >= 17)
        nolink = sc.inject(PAGE.replace("id='composite'", "id='other'"), tmp, scores)
        check("the composite link is only added when the composite section exists", "href='#composite'" not in nolink)

    print("missing inputs")
    with tempfile.TemporaryDirectory() as tmp:
        write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "analysis_track", "recall"], [])
        page = sc.inject(PAGE, tmp, os.path.join(tmp, "scores.tsv"))
        defs = page.split("id='scorecard-definitions'")[1].split("</section>")[0]
        check("the definitions table is collapsed until clicked (a closed <details> holding the table)",
              "<details class='rpt-collapsible'>" in defs and "<details class='rpt-collapsible' open" not in defs
              and defs.index("<details") < defs.index("<table") < defs.index("</details>"))
        check("an empty score table: the scorecard and scenario sections say Not run (definitions stay, they come from config)", page.count("Not run") == 2
              and all(f"id='{sid}'" in page for sid, _ in sc.SECTIONS))
        page = sc.inject(PAGE, tmp, os.path.join(tmp, "absent.tsv"))
        check("no score table at all: Not run, not blank", page.count("Not run") == 2)
    with tempfile.TemporaryDirectory() as tmp:
        write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "analysis_track", "recall"], [["s1", "t1", "short_read", "0.5"]])
        page = sc.inject(PAGE, tmp, os.path.join(tmp, "scores.tsv"))
        check("only scores present: scored on what exists, scenarios Not run, share well below 1",
              "benchmark.scenarios.tsv was not produced" in page and "0.10" in page)
        bad_cfg = os.path.join(tmp, "bad.tsv")
        write(bad_cfg, ["id", "weight"], [["A1", "5"]])
        page = sc.inject(PAGE, tmp, os.path.join(tmp, "scores.tsv"), config_path=bad_cfg)
        check("an invalid config is a visible Not run", "configuration is invalid" in page)
    check("an unrecognised page is returned unchanged", sc.inject("<p>x</p>", ".", "none.tsv") == "<p>x</p>")

    demo = os.path.join(HERE, "..", "results_demo")
    if os.path.isfile(os.path.join(demo, "benchmark.accuracy.tsv")) and os.path.isfile(os.path.join(demo, "scores.tsv")):
        print("results_demo")
        page = sc.inject(PAGE, demo, os.path.join(demo, "scores.tsv"))
        check("demo: the three sections render with tools and overall scores", all(f"id='{sid}'" in page for sid, _ in sc.SECTIONS)
              and "mob_like" in page and "Not run" not in page.split("id='scorecard-definitions'")[0])
    else:
        print("results_demo not built here; skipped (run bash test/run_demo.sh to include it)")

    print()
    if not ok:
        print("REPORT SCORECARD TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT SCORECARD TESTS PASSED")


if __name__ == "__main__":
    main()
