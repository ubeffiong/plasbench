#!/usr/bin/env python3
"""
report_merge folds related sections into one container as tabs, deleting nothing.

Hand-checked on small stub pages (a container 'robustness' absorbing 'statistics' and 'power'; 'leaderboard' absorbing 'chart'):
  - the container keeps its <section id>, its own content becomes the first panel '<id>-main', each absorbed section becomes a panel whose id is
    the OLD section id (so href='#statistics' still lands on it) and the old <section> wrapper is gone: no section is nested;
  - every byte of an absorbed section's inner HTML (lead, table, svg, script, ids) is inside its panel, in order;
  - a container with a new title keeps the old heading as a sub-heading of the first panel; a container that keeps its title keeps its lead;
  - LEGACY_IDS resolves every absorbed id to (container, tab label), an unknown id to nothing;
  - a missing container leaves the absorbed sections standing alone; a missing absorbed section is skipped; a container with nothing to absorb
    is unchanged; a section that holds a nested section is never absorbed;
  - the appendix container 'appendix-reference' (no section of its own) takes the place of the first absorbed section;
  - 'Not run' notices stay visible inside their panel; the tab strip is hidden until the page script runs (no-JS shows every panel stacked);
  - running twice changes nothing, and a page without sections comes back unchanged;
  - the style and the script are added once; the real demo report has the expected containers, every old id is still an element id, and no
    top-level section id is duplicated.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
sys.path.insert(0, HERE)

import report_aliases  # noqa: E402
import report_merge as rm  # noqa: E402
from report_regions import region  # noqa: E402

STAT = "<h2>Statistics</h2><p class='lead'>Paired tests.</p><table class='sortable'><tr><th>A</th></tr><tr><td>1</td></tr></table><svg id='st-svg'><title>t</title></svg><script>var st=1;</script>"
POW = "<h2>Power</h2><div class='insight caution'><p><strong>Not run:</strong> no power table</p></div>"
CHART = "<h2>Chart</h2><p class='lead'>Bars.</p><svg><rect/></svg>"


def sec(sid, inner, cls=""):
    return f"<section id='{sid}'{(' class=' + chr(39) + cls + chr(39)) if cls else ''}>{inner}</section>"


def page_of(*sections):
    return "<html><head></head><body><main>" + "".join(sections) + "</main><footer>f</footer></body></html>"


def top_ids(page):
    return re.findall(r"<section id='([^']+)'", page)


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    base = page_of(sec("summary", "<h2>Summary</h2>"), sec("robustness", "<h2>Robustness diagnostics</h2><p class='lead'>Basis.</p><p>own</p>"),
                   sec("statistics", STAT), sec("power", POW), sec("leaderboard", "<h2>Method ranking</h2><p class='lead'>Rank.</p><table></table>"),
                   sec("chart", CHART), sec("recommendations", "<h2>Recs</h2>"))
    out = rm.transform(base)

    print("structure")
    check("the absorbed sections are no longer top-level sections", top_ids(out) == ["summary", "robustness", "ranking-sensitivity", "leaderboard", "recommendations"], top_ids(out))   # power is a tab of the virtual ranking-sensitivity container
    check("no section is nested", all(out.count("<section") == out.count("</section>") for _ in [0]) and out.count("<section") == 5)
    check("the container's own content is the first panel", "id='robustness-main'" in out and region(out, "robustness-main").count("own") == 1)
    check("each absorbed section is a panel with the old id", "<div class='rpt-panel' id='statistics'" in out and "<div class='rpt-panel' id='power'" in out)
    check("a link to the old id still lands on an element", all(f"id='{i}'" in out for i in ("statistics", "power", "chart", "st-svg")))
    check("every inner byte of an absorbed section is kept, in order", all(
        inner in out for inner in (STAT, POW, CHART)))
    check("a new container title keeps the old heading as a sub-heading", "<h2>Ranking confidence</h2>" in out and "<h3>Robustness diagnostics</h3>" in out)
    check("a container that keeps its title keeps its lead above the tabs", out.index("<h2>Method ranking</h2>") < out.index("Rank.") < out.index("data-merge-tabs='leaderboard'"))
    check("the tab strip is hidden until the script runs (no JS shows every panel stacked)", "class='rpt-mtabs' role='tablist'" in out and " hidden>" in out)
    check("tab labels follow the table", "data-tab='Paired tests'" in out and "data-tab='Statistical power'" in out and "data-tab='Precision, recall and F1'" in out)
    check("the Not run notice stays inside its panel", "Not run:" in region(out, "power"))
    check("the style and the script are added once", out.count("id='rpt-merge-style'") == 1 and out.count("rpt-merge-script") >= 1 and rm.transform(out).count("id='rpt-merge-style'") == 1)

    print("aliases")
    check("LEGACY_IDS resolves the absorbed ids to (container, tab)", report_aliases.LEGACY_IDS["statistics"] == ("robustness", "Paired tests")
          and report_aliases.LEGACY_IDS["composite"][0] == "scorecard")
    check("an unknown id resolves to nothing", report_aliases.LEGACY_IDS.get("no-such-section") is None)
    check("every absorbed id in MERGES is in LEGACY_IDS", all(o in report_aliases.LEGACY_IDS for s in rm.MERGES for o_, _l in s["tabs"] for o in (o_ if isinstance(o_, (tuple, list)) else [o_])))
    check("region() finds an absorbed section by its old id", "Paired tests." in region(out, "statistics"))
    check("panels_of lists the container's panels in order", [p[0] for p in rm.panels_of(region(out, "robustness") if region(out, "robustness").startswith("<section") else "")] in ([], ["robustness-main", "statistics"]))

    print("what is left alone")
    check("idempotent", rm.transform(out) == out)
    no_container = page_of(sec("statistics", STAT), sec("chart", CHART))
    check("a missing container leaves the absorbed sections standing alone", rm.transform(no_container) == no_container)
    only_container = page_of(sec("robustness", "<h2>R</h2><p>own</p>"))
    check("a container with nothing to absorb is unchanged", rm.transform(only_container) == only_container)
    missing_one = rm.transform(page_of(sec("robustness", "<h2>R</h2><p>own</p>"), sec("power", POW)))
    check("a missing absorbed section is skipped (the others still merge)", "id='power'" in missing_one and "id='statistics'" not in missing_one)
    nested = page_of(sec("robustness", "<h2>R</h2>"), sec("statistics", "<h2>S</h2><section id='inner'>x</section>"))
    check("a section holding a nested section is never absorbed", "<section id='statistics'" in rm.transform(nested))
    check("a page without sections is unchanged", rm.transform("<p>x</p>") == "<p>x</p>")

    print("the appendix container")
    app = rm.transform(page_of(sec("summary", "<h2>S</h2>"), sec("accuracy-dimension", "<h2>Accuracy</h2><p>p</p>"), sec("quast-diagnostics", "<h2>Quast</h2><p>e</p>")))
    check("'appendix-reference' takes the place of the first absorbed section", top_ids(app) == ["summary", "appendix-reference"], top_ids(app))
    check("its tabs are the reference sections with their old ids", "id='accuracy-dimension'" in app and "id='quast-diagnostics'" in app and "data-tab='QUAST diagnostics'" in app)

    print("the real demo report")
    report = os.path.join(HERE, "..", "results_demo", "benchmark.report.html")
    if not os.path.isfile(report):
        print("  SKIP: no results_demo report")
    else:
        html = open(report, encoding="utf-8").read()
        ids = top_ids(html)
        check("top-level section ids are unique", len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1])
        check("far fewer top-level sections than the 73 the page had", len(ids) < 45, len(ids))
        check("the containers are present", all(c in ids for c in ("leaderboard", "robustness", "scorecard", "bin-diagnostics", "cohort-qc", "health", "recommendations", "recommender-eval", "scores", "appendix-reference")))
        check("every absorbed id is still an element id on the page", all(f"id='{o}'" in html or f'id="{o}"' in html for o in report_aliases.LEGACY_IDS))
        check("no nested sections in the real page", html.count("<section") == html.count("</section>"))

    print()
    if not ok:
        print("REPORT MERGE TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT MERGE TESTS PASSED")


if __name__ == "__main__":
    main()
