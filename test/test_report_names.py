#!/usr/bin/env python3
"""
Reader-facing tool names are applied when the report is built (python/report_names.py), and the page keeps the order the review asked for.

Hand-checked on small fragments (labels: spades_like -> SPAdes-like, mob_like -> MOB-like):
  - text nodes are renamed; attribute values (href, title, data-*, value) are not;
  - whole ids only: 'xmob_like', 'mob_like2' and 'my-mob_like' stay;
  - not inside <script>, <style>, <textarea>, <code>, <pre>, <option> or <template>;
  - SVG <title> tooltips are renamed;
  - link text is renamed only when it is exactly one id ('spades_like' yes; the file name 'spades_like.per_plasmid.tsv' no);
  - running twice changes nothing; no labels, or labels equal to their ids, leave the page as it was;
  - the real demo report: no raw tool id is left in a visible text node outside links to files, options, code and templates; the views come in the
    reviewed order with titles equal to rail labels; the Summary shows the headline numbers, then Start here, then the plasmid matrix, report card and
    scorecard overall; there is no KPI strip in the banner; the explorers are sections of the Figures and Plasmid maps views; the top bar has the
    actions menu button.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_names as rn  # noqa: E402

L = {"spades_like": "SPAdes-like", "mob_like": "MOB-like"}


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("renaming")
    check("text nodes are renamed", rn.humanise("<td>spades_like</td><p>mob_like and spades_like</p>", L) == "<td>SPAdes-like</td><p>MOB-like and SPAdes-like</p>")
    check("attributes are never touched", rn.humanise("<td title='mob_like' data-tool='mob_like' value='mob_like'>x</td>", L) == "<td title='mob_like' data-tool='mob_like' value='mob_like'>x</td>")
    check("whole ids only", rn.humanise("<td>xmob_like mob_like2 my-mob_like mob_like</td>", L) == "<td>xmob_like mob_like2 my-mob_like MOB-like</td>")
    skipped = "<script>var a='mob_like'</script><style>.mob_like{}</style><textarea>mob_like</textarea><code>mob_like</code><pre>mob_like</pre><option value='x'>mob_like</option><template><td>mob_like</td></template>"
    check("script, style, textarea, code, pre, option and template content is left alone", rn.humanise(skipped, L) == skipped)
    check("SVG <title> tooltips are renamed", rn.humanise("<svg><title>mob_like covered 100%</title></svg>", L) == "<svg><title>MOB-like covered 100%</title></svg>")
    check("link text is renamed when it is exactly one id", rn.humanise("<a href='#t'>spades_like</a>", L) == "<a href='#t'>SPAdes-like</a>")
    check("a file name in a link is not", rn.humanise("<a href='f'>spades_like.per_plasmid.tsv</a>", L) == "<a href='f'>spades_like.per_plasmid.tsv</a>")
    once = rn.humanise("<td>spades_like</td><a>mob_like</a>", L)
    check("running twice changes nothing", rn.humanise(once, L) == once)
    check("no labels, or labels equal to their ids, leave the page as it was", rn.humanise("<td>mob_like</td>", {}) == "<td>mob_like</td>" and rn.humanise("<td>mob_like</td>", {"mob_like": "mob_like"}) == "<td>mob_like</td>")
    check("the longer id wins when one id starts with another", rn.humanise("<td>mob_like_v2 mob_like</td>", {"mob_like": "MOB-like", "mob_like_v2": "MOB v2"}) == "<td>MOB v2 MOB-like</td>")

    print("the real demo report")
    report = os.path.join(HERE, "..", "results_demo", "benchmark.report.html")
    if not os.path.isfile(report):
        print("  SKIP: no results_demo report")
    else:
        text = open(report, encoding="utf-8").read()
        body = re.sub(r"<script\b.*?</script>|<template\b.*?</template>|<style\b.*?</style>|<code\b.*?</code>|<pre\b.*?</pre>|<option\b.*?</option>", "", text, flags=re.S)
        visible = re.findall(r">([^<>]*(?:spades_like|mob_like|gplas_like|platon_like|weak_like)[^<>]*)<", body)
        # what may keep a raw id: a file name (contains a dot after the id) or a path
        raw = [v for v in visible if re.search(r"(?<![A-Za-z0-9_-])(?:spades_like|mob_like|gplas_like|platon_like|weak_like)(?![A-Za-z0-9_.-])", v)]
        check("no raw tool id is left in the visible text (file names excepted)", not raw, raw[:3])
        rail = text[text.index("<nav class='rpt-rail'"):]
        rail = rail[:rail.index("</nav>")]
        labels = re.findall(r"class='rpt-rail-label'>([^<]*)<", rail)
        check("the views come in the reviewed order",
              labels == ["Overview", "Recommendation", "Figures", "Plasmid maps", "Detailed results", "Data quality", "Methods and limits", "Scorecard (exploratory)", "Appendix"], labels)
        titles = re.findall(r"class='rpt-view-title' role='heading' aria-level='2'>([^<]+)<", text)
        check("each view's title equals its menu label", titles == labels, titles)
        summary = text[text.index("<section id='summary'"):]
        summary = summary[:summary.index("</section>")]
        order = [summary.index(k) for k in ("sum-stats", "<h3>Start here</h3>", "id='summary-plasmids'", "<h3>Report card", "id='summary-scorecard'")]
        check("Summary: headline numbers, Start here, plasmid matrix, report card, scorecard overall", order == sorted(order), order)
        check("there is no KPI strip in the banner", "class='rpt-kpis'" not in text and "<small>Samples observed</small>" not in text)
        ids = re.findall(r"<section id='([a-z-]+)'", text)
        check("the dashboard is in the Figures view and the evidence explorer in the Plasmid maps view",
              "id='view-figures'" in text and ids.index("enterprise") < ids.index("plasmid-maps") < ids.index("evidence-explorer"), ids)
        figs = [i for i in ids if i.startswith("fig-")]
        check("figures: CPRR differences first, the 3D landscape last", figs[0] == "fig-forest" and figs[-1] == "fig-landscape", figs)
        check("the top bar has the actions menu button for narrow screens", "id='rpt-more'" in text and "aria-controls='rpt-actions'" in text and "id='rpt-actions'" in text)
        long_labels = [x for x in re.findall(r"class='rpt-rail-sub'.*?</ul>", rail, re.S)]
        subs = re.findall(r"<a href='#[^']+'>([^<]+)</a>", "".join(long_labels))
        check("section labels in the menu are short", all(len(s) <= 30 for s in subs), [s for s in subs if len(s) > 30])

    print()
    if not ok:
        print("REPORT NAMES TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT NAMES TESTS PASSED")


if __name__ == "__main__":
    main()
