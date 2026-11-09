#!/usr/bin/env python3
"""
The Workflow section: a data-driven pipeline figure that documents what ran.

Hand-built directory (no pipeline needed):
  tool_status.tsv has completed 3, reused 1, failed 2, skipped 1, infrastructure_failure 1  -> the figure says exactly those
  samples.tsv has 4 samples                                                                 -> "4 samples"
  scores.tsv has 6 rows with contig and bin columns                                          -> reference/contig/bin layers filled
  benchmark.copy_number.tsv (2 rows) exists, benchmark.amr_placement.tsv does not           -> copy number filled, AMR 'Not run' dashed
No results directory at all: the figure still renders and every layer says Not run.
"""

import csv
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_workflow as wf  # noqa: E402

TAB = chr(9)
PAGE = ("<main><nav><a href='#recommendations'>Recommendations</a></nav><section id='leaderboard'>x</section>"
        "<section id='recommendations'>x</section></main>")


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=chr(10))
        w.writerow(header)
        w.writerows(rows)


def texts(svg):
    root = ET.fromstring(svg)
    return ["".join(t.itertext()) for t in root.iter("{http://www.w3.org/2000/svg}text")], root


def build(tmp):
    write(os.path.join(tmp, "samples.tsv"), ["sample_id", "organism"], [[f"s{i}", "E. coli"] for i in range(4)])
    status = ([["s0", f"tool{i}", "completed"] for i in range(3)] + [["s1", "tool_r", "reused"]]
              + [["s1", "tool_f", "failed"], ["s2", "tool_f", "failed"], ["s2", "baseline_x", "skipped"],
                 ["s3", "plsmd", "infrastructure_failure"]])
    write(os.path.join(tmp, "tool_status.tsv"), ["sample", "tool", "status"], status)
    write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "f1", "contig_classification_status", "bin_f1", "bestmatch_status"],
          [[f"s{i}", "tool0", "0.5", "ok", "0.4", "ok"] for i in range(6)])
    write(os.path.join(tmp, "benchmark.copy_number.tsv"), ["sample", "tool"], [["s0", "t"], ["s1", "t"]])


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("a hand-built results directory")
    with tempfile.TemporaryDirectory() as tmp:
        build(tmp)
        model = wf.build_model(tmp, os.path.join(tmp, "scores.tsv"))
        c = model["tool_counts"]
        check("status counts equal tool_status.tsv", (c["completed"], c["reused"], c["failed"], c["skipped"], c["infrastructure_failure"]) == (3, 1, 2, 1, 1))
        check("sample count is 4", model["n_samples"] == 4)
        svg = wf.render_svg(model)
        words, root = texts(svg)
        check("figure is well-formed XML with a viewBox and no fixed size", root.get("viewBox") and root.get("width") is None)
        joined = " ".join(words)
        check("figure prints the status counts",
              "completed 3, reused 1, failed 2, skipped 1, infrastructure failure 1" in " ".join(words))
        check("figure prints 4 samples", "4 samples" in joined)
        for stage in ("Isolate short reads", "Complete reference genome", "Truth construction", "Evidence labels", "Reference tiers",
                      "Labelling schemes", "Dimer check", "Repeat content", "Depth anomalies", "Short-read assembly", "Binning",
                      "Reassembly", "Classifiers", "Trivial baselines", "Optional adapters", "Reference-base", "Contig-level",
                      "Bin-level", "AMR placement", "Copy number", "Assembly adequacy", "Cluster bootstrap", "Rank robustness",
                      "Database leakage", "Recommendation and report"):
            check(f"box for {stage}", stage in joined)
        check("copy number has a filled box with 2 rows", "2 rows" in joined)
        check("AMR placement is absent, so Not run appears", "Not run" in joined)
        # the AMR layer box: its dashed rect precedes the title text; count dashed boxes vs 'Not run' texts
        dashed = svg.count("wf-notrun")
        check("dashed boxes carry the words Not run (or none recorded / no truth table)", dashed >= 1 and sum(("Not run" in w or w.startswith("none") or w.startswith("no ")) for w in words) >= dashed)
        check("plsMD run lands in the optional adapters box", model["by_class"].get("adapter", {}).get("runs") == 1)
        check("filled and dashed boxes both present", "wf-ran" in svg and "wf-notrun" in svg and "stroke-dasharray" in svg)
        check("no text smaller than 10 px", all(float(m) >= 10 for m in re.findall(r"font-size='([0-9.]+)'", svg)))

        section = str(wf.render_workflow(model, known_section_ids={"leaderboard", "samples"}))
        check("section id is workflow", "<section id='workflow'" in section)
        links = set(re.findall(r"href='#([^']+)'", section))
        check("links only go to known ids", links and links <= {"leaderboard", "samples"})
        check("tools row links to the leaderboard", "href='#leaderboard'" in section)
        check("a stage without a known section carries no link", "href='#amr-placement'" not in section)

        page = wf.inject(PAGE, tmp, os.path.join(tmp, "scores.tsv"))
        check("injected before Recommendations", page.index("id='workflow'") < page.index("id='recommendations'"))
        check("nav link added", "href='#workflow'>Workflow</a>" in page)
        check("page links to the sections already in it only", set(re.findall(r"href='#([^']+)'", page)) <=
              {"leaderboard", "recommendations", "workflow"})
        check("injecting twice adds one section", wf.inject(page, tmp, os.path.join(tmp, "scores.tsv")).count("id='workflow'") == 1)

    print("no results directory")
    for missing in (None, os.path.join(tempfile.gettempdir(), "plasbench-no-such-dir-xyz")):
        model = wf.build_model(missing, None)
        svg = wf.render_svg(model)
        words, _ = texts(svg)
        check("renders well-formed", words)
        check("every scoring layer is Not run", all(not v["present"] for v in model["layers"].values()))
        check("no 'ran' boxes among layers or statistics", all(not v["present"] for v in model["stats"].values()))
        check("Not run is shown", "Not run" in words)
        section = str(wf.render_workflow(model))
        check("no links at all by default", "href=" not in section)
        check("page injection still works", "id='workflow'" in wf.inject(PAGE, missing, None))

    print()
    if not ok:
        print("REPORT WORKFLOW TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT WORKFLOW TESTS PASSED")


if __name__ == "__main__":
    main()
