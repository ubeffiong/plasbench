#!/usr/bin/env python3
"""
The registry of pipeline outputs (report_surfaces.py) against the real thing.

  - every file of a freshly generated demo (test/run_demo.sh -> results_demo/) is registered; an unregistered file fails the
    test and is named, so a new output cannot be added without deciding where the report shows it
  - every scores.tsv and leaderboard column of the demo, and every column the producers declare, is in a group
  - no duplicate patterns; not-surfaced entries carry a reason and a planned section
  - the inventory lists exactly the registered groups, marks the absent ones 'not in this run', and links only to known ids

The demo is generated once when results_demo/ is missing (about ten minutes on Windows); set PLASBENCH_RESULTS_DEMO to test
another directory.
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import report_surfaces as rs  # noqa: E402

DEMO = os.environ.get("PLASBENCH_RESULTS_DEMO") or os.path.join(ROOT, "results_demo")


def header(path):
    with open(path, encoding="utf-8") as handle:
        return handle.readline().rstrip("\n").split("\t")


def ensure_demo():
    if os.path.isfile(os.path.join(DEMO, "scores.tsv")) and os.path.isfile(os.path.join(DEMO, "benchmark.leaderboard.tsv")):
        return True
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for _ in range(3):   # the demo writer can fail once on a synced Windows folder; it rebuilds from scratch
        done = subprocess.run(["bash", os.path.join(HERE, "run_demo.sh")], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if done.returncode == 0:
            return True
    return False


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the registry itself")
    patterns = [e["pattern"] for e in rs.SURFACES]
    dup = sorted({p for p in patterns if patterns.count(p) > 1})
    check("no duplicate patterns", not dup, str(dup))
    check("every entry has a valid level and status", all(e["status"] in rs.STATUSES and
          e["level"] in ("per_sample", "per_tool", "aggregate", "column") for e in rs.SURFACES))
    check("every entry has a reason and a producer", all(e["reason"] and e["producer"] for e in rs.SURFACES))
    ns = [e for e in rs.SURFACES if e["status"] == "not_surfaced"]
    check("not_surfaced entries have a reason and a planned_section", ns and all(e["reason"] and e["planned_section"] for e in ns),
          str([e["pattern"] for e in ns if not e["planned_section"]]))
    check("only not_surfaced entries carry a planned_section", all(e["planned_section"] is None for e in rs.SURFACES
                                                                    if e["status"] != "not_surfaced"))
    wanted = {"{sample}/{tool}.per_plasmid.tsv", "{sample}/{tool}.plasmid_outcomes.tsv", "{sample}/assembly_qc.tsv",
              "{sample}/assembly_stats.tsv", "benchmark.clonal_groups.tsv", "benchmark.recommender_regret.tsv",
              "{sample}/truth_depth_windows.tsv", "benchmark.leaderboard.md", "benchmark.scoring_spec.md"}
    check("the audited not-shown outputs are registered as not_surfaced", wanted <= {e["pattern"] for e in ns},
          str(wanted - {e["pattern"] for e in ns}))
    check("column groups cover the ten named groups", set(rs.SCORE_COLUMN_GROUPS) == {
        "Identity", "Core", "Recovery", "Graded recovery", "Confusion and abstention", "Bins", "Contig layer", "Agreement",
        "Calibration", "Diagnostics"})
    allc = [c for cols in rs.SCORE_COLUMN_GROUPS.values() for c in cols]
    check("no scores column is in two groups", len(allc) == len(set(allc)), str(sorted({c for c in allc if allc.count(c) > 1})))
    allb = [c for cols in rs.LEADERBOARD_COLUMN_GROUPS.values() for c in cols]
    check("no leaderboard column is in two groups", len(allb) == len(set(allb)), str(sorted({c for c in allb if allb.count(c) > 1})))
    check("classify_file knows a path and not a stranger", rs.classify_file("ecoli_a/mob_recon.bin_matches.tsv")["status"] == "shown"
          and rs.classify_file("ecoli_a/something_new.tsv") is None)
    check("a tool name does not swallow a different file", rs.classify_file("s1/truth.corrections.tsv")["pattern"] == "{sample}/truth.corrections.tsv")
    check("track leaderboards are recognised", rs.classify_file("benchmark.short_read.leaderboard.tsv")["pattern"] == "benchmark.{track}.leaderboard.tsv"
          and rs.classify_file("benchmark.leaderboard.tsv")["pattern"] == "benchmark.leaderboard.tsv")
    check("windows path separators are accepted", rs.classify_file("ecoli_a\\truth.tsv") is not None)

    print("columns declared by the producers")
    try:
        import contig_classification as cc
        import merge_bin_metrics as mb
        import merge_pr_metrics as mp
        declared = list(cc.SCORE_FIELDS) + list(mb.FIELDS) + list(mp.FIELDS)
        check("contig, bin and PR columns declared by the merge scripts are all grouped",
              not rs.unregistered_columns(declared, rs.SCORE_COLUMN_GROUPS), str(rs.unregistered_columns(declared, rs.SCORE_COLUMN_GROUPS)))
    except ImportError as exc:
        check(f"producer modules import ({exc})", False)
    src = open(os.path.join(ROOT, "python", "score_plasmids.py"), encoding="utf-8").read()
    block = src[src.index("header = [\n        \"sample\""):]
    block = block[:block.index("]\n")]
    core = re.findall(r'"([A-Za-z0-9_]+)"', block)
    check("score_plasmids.py's header is all grouped", core and not rs.unregistered_columns(core, rs.SCORE_COLUMN_GROUPS),
          str(rs.unregistered_columns(core, rs.SCORE_COLUMN_GROUPS)))
    check("unregistered_columns reports a stranger", rs.unregistered_columns(["f1", "brand_new"], rs.SCORE_COLUMN_GROUPS) == ["brand_new"])

    print("the demo")
    if not ensure_demo():
        check("results_demo could be generated", False)
    else:
        result = rs.scan(DEMO, DEMO)
        n_files = sum(len(fs) for _, _, fs in os.walk(DEMO))
        check(f"results_demo has files ({n_files})", n_files > 50)
        for path in result["unregistered"]:
            check(f"file is registered: {path}", False)
        check("every file in results_demo is registered", not result["unregistered"])
        check("registered counts add up to every file", sum(r["count"] for r in result["registered"]) == n_files)
        check("no expected output is missing from the demo", not result["missing_expected"], str(result["missing_expected"]))
        sc = header(os.path.join(DEMO, "scores.tsv"))
        lb = header(os.path.join(DEMO, "benchmark.leaderboard.tsv"))
        check("every scores.tsv column of the demo is in a group", not rs.unregistered_columns(sc, rs.SCORE_COLUMN_GROUPS),
              str(rs.unregistered_columns(sc, rs.SCORE_COLUMN_GROUPS)))
        check("every leaderboard column of the demo is in a group", not rs.unregistered_columns(lb, rs.LEADERBOARD_COLUMN_GROUPS),
              str(rs.unregistered_columns(lb, rs.LEADERBOARD_COLUMN_GROUPS)))

        print("the inventory section")
        known = {"samples", "scores", "leaderboard"}
        html = str(rs.inventory_section(DEMO, DEMO, known))
        check("section id is data-inventory", "<section id='data-inventory'" in html)
        body = html[html.index("<tbody>"):html.index("</tbody>")]
        check("one row per registered group, no more", body.count("<tr>") == len(rs.SURFACES), f"{body.count('<tr>')} vs {len(rs.SURFACES)}")
        check("every registered pattern is listed", all(f"<code>{rs.rc.esc(p)}</code>" in html for p in patterns))
        links = set(re.findall(r"href='#([^']+)'", html))
        check("links go only to known ids", links <= known, str(links - known))
        check("a present group is not marked absent", re.search(r"<code>scores.tsv::Core</code>[^|]*?8 of 8 columns", html.replace("\n", " ")) is not None)
        check("every not-surfaced item says why", html.count("Not shown yet: ") == len(ns))
        absent = [e for e in rs.SURFACES if e["pattern"] not in {r["pattern"] for r in result["registered"]} and e["level"] != "column"]
        check("groups not written by the demo are marked 'not in this run'", absent and html.count("not in this run") >= len(absent))

    print("a run with nothing in it")
    with tempfile.TemporaryDirectory() as tmp:
        html = str(rs.inventory_section(tmp, tmp, ()))
        body = html[html.index("<tbody>"):html.index("</tbody>")]
        check("every group is listed and every one is 'not in this run'", body.count("<tr>") == len(rs.SURFACES)
              and body.count("not in this run") == len(rs.SURFACES))
        check("an empty directory reports its expected outputs as missing", "Expected but absent" in html)
        check("no links with no known sections", "href=" not in html)
        page = rs.inject("<main><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'>x</section></main>", tmp, tmp)
        check("injected before Recommendations with a nav link", page.index("id='data-inventory'") < page.index("id='recommendations'")
              and "href='#data-inventory'" in page)
        sample = os.path.join(tmp, "s1")
        os.makedirs(sample)
        open(os.path.join(sample, "brand_new_output.tsv"), "w").write("x\n")
        check("a new unregistered output is reported by name", "brand_new_output.tsv" in str(rs.inventory_section(tmp, tmp, ())))

    print()
    if not ok:
        print("REPORT SURFACES TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT SURFACES TESTS PASSED")


if __name__ == "__main__":
    main()
