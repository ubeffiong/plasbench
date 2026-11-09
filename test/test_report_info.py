#!/usr/bin/env python3
"""
Tests for python/report_info.py: the report's explanatory notes become hover/focus info popovers.

Hand-computed on a small stub page, then checked on a real build of the demo (a copy of results_demo, so the demo
directory is never modified).

Stub page (every figure below is counted by hand):
  alpha : h2 + lead (with a link, an <em>, an escaped '&lt;')   -> 1 icon in the h2, the lead paragraph gone
          h3 + muted explanatory note                            -> 1 icon in the h3
          a figure whose caption says how to read it             -> 1 icon in the figcaption
          a 'Not run:' notice, a caution box, a data caption     -> untouched
  beta  : h2 + empty lead                                        -> skipped, untouched
  summary: the report's own start-here text                      -> kept
  gamma : h2 + muted + muted (two notes, one heading)            -> ONE icon, both notes in its popover
          <summary> + muted note                                 -> icon in the summary
  total : 5 icons, popover ids unique, each referenced by aria-describedby of its button
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import report_info as ri  # noqa: E402

ok = True


def check(label, cond, extra=None):
    global ok
    if cond:
        print(f"  ok  {label}")
    else:
        ok = False
        print(f"  FAIL {label}" + (f"  -> {extra!r}" if extra is not None else ""))


LEAD = "Read <a href='t.tsv' download>the table</a>; <em>mean</em> F1 where a &lt; b &amp; c."
MUTED = "Switch column groups on or off; <code>--flag</code> stays."
CAPTION = "Dots on the dashed diagonal are perfectly calibrated."
STUB = (
    "<html><body><nav class='nav'><a href='#alpha'>Alpha</a><a href='#beta'>Beta</a><a href='#summary'>Summary</a>"
    "<a href='#gamma'>Gamma</a></nav><main>"
    f"<section id='alpha'><h2>Tools &amp; <em>rings</em></h2><p class='lead'>{LEAD}</p>"
    f"<h3>Columns</h3><p class='muted'>{MUTED}</p>"
    f"<figure class='rpt-figure'><svg></svg><figcaption>{CAPTION}</figcaption></figure>"
    "<figure class='rpt-figure'><svg></svg><figcaption>mob_like: overall 99.8, scored share 0.83</figcaption></figure>"
    "<div class='insight caution'><p><strong>Not run:</strong> no alignments were found.</p></div>"
    "<div class='insight caution'><p class='lead'>A caution that happens to use the lead class.</p></div>"
    "</section>"
    "<section id='beta'><h2>Beta</h2><p class='lead'> </p><p>body</p></section>"
    "<section id='summary'><h2>Summary</h2><p class='lead'>The headline numbers. Start here.</p></section>"
    "<section id='gamma'><h2>Gamma</h2><p class='muted'>First note.</p><p class='muted'>Second note.</p>"
    "<details><summary><strong>Sample</strong> <span>3 tools</span></summary><p class='muted'>Open a sample to compare tools.</p>"
    "<p>body</p></details>"
    "<p class='muted'>No tool was scored in this run.</p></section>"
    "</main><script>var s = \"<p class='lead'>not a note</p>\";</script></body></html>")

# What a real demo build still prints as a lead right after an h2: the Summary section, and sections whose lead carries
# a standing caveat in bold ('advisory only', 'descriptive only') or a data value. Kept on purpose; see report_info.STATUS.
KEPT_AFTER_H2 = {"summary", "assembly-quality", "data-inventory", "cohort-qc", "replicon-recovery", "truth-label-audit",
                 "accuracy-dimension", "bin-quality"}


def _span_end(page, start):
    """Index just past the </span> that closes the <span> opened at `start` (spans nest: merged notes use inner spans)."""
    depth = 0
    for m in re.finditer(r"<span[ >]|</span>", page[start:]):
        depth += 1 if m.group(0) != "</span>" else -1
        if depth == 0:
            return start + m.end()
    raise AssertionError("unbalanced span")


def infos(page):
    return [page[m.start():_span_end(page, m.start())] for m in re.finditer(r"<span class='rpt-info'>", page)]


def strip_infos(page):
    for block in infos(page):
        page = page.replace(block, "", 1)
    return page


def popovers(page):
    """[(id, inner html)] of every popover on the page."""
    found = []
    for m in re.finditer(r"<span role='tooltip' id='(rpt-info-[^']+)' class='rpt-info-pop'>", page):
        end = _span_end(page, m.start())
        found.append((m.group(1), page[m.end():end - len("</span>")]))
    return found


def main():
    print("a stub page")
    out, recs = ri.transform_with_records(STUB)
    moved = [r for r in recs if r["action"] == "moved"]
    check("lead, muted, figcaption and the summary muted note are moved (6 notes)", len(moved) == 6, [r["kind"] for r in moved])
    n_info = out.count("class='rpt-info'")
    check("5 icons (the two notes under Gamma share one)", n_info == 5, n_info)
    check("the lead paragraph is gone from the page body (3 left: caution box, empty, Summary; plus 1 in a script string)",
          out.count("<p class='lead'>") == 4, out.count("<p class='lead'>"))
    check("the lead text sits verbatim in a popover (link, em, escaped < and & kept)",
          f"class='rpt-info-pop'>{LEAD}</span>" in out)
    check("the muted note sits verbatim in a popover", f"class='rpt-info-pop'>{MUTED}</span>" in out)
    check("the figure caption sits verbatim in a popover", f"class='rpt-info-pop'>{CAPTION}</span>" in out)
    check("a lead's link survives", "<a href='t.tsv' download>the table</a>" in out)
    check("no raw '<' was introduced into the note text", "a &lt; b &amp; c" in out and "a < b" not in out)
    check("the icon is inside the h2, the heading text is unchanged",
          re.search(r"<h2>Tools &amp; <em>rings</em><span class='rpt-info'>", out) is not None)
    check("aria-label names the heading, escaped", "aria-label='About this section: Tools &amp; rings'" in out)
    check("the figure icon is labelled for the figure", "aria-label='About this figure'" in out)
    check("the icon sits in the figcaption", f"<figcaption><span class='rpt-info'>" in out)
    check("two notes under one heading make one icon with two paragraphs",
          "<span class='rpt-info-para'>First note.</span><span class='rpt-info-para'>Second note.</span>" in out)
    check("an icon in a summary comes after its text",
          re.search(r"<summary><strong>Sample</strong> <span>3 tools</span><span class='rpt-info'>", out) is not None)
    check("'Not run:' notice untouched", "<div class='insight caution'><p><strong>Not run:</strong> no alignments were found.</p></div>" in out)
    check("a caution box that uses the lead class is untouched",
          "<div class='insight caution'><p class='lead'>A caution that happens to use the lead class.</p></div>" in out)
    check("a data caption stays", "<figcaption>mob_like: overall 99.8, scored share 0.83</figcaption>" in out)
    check("a status note stays", "<p class='muted'>No tool was scored in this run.</p>" in out)
    check("an empty lead is skipped", "<section id='beta'><h2>Beta</h2><p class='lead'> </p><p>body</p></section>" in out)
    check("the Summary lead stays", "<h2>Summary</h2><p class='lead'>The headline numbers. Start here.</p>" in out)
    check("script text that looks like a note is not touched", "var s = \"<p class='lead'>not a note</p>\";" in out)

    ids = re.findall(r"role='tooltip' id='([^']+)'", out)
    described = re.findall(r"aria-describedby='([^']+)'", out)
    check("popover ids are unique", len(ids) == len(set(ids)) == 5, ids)
    check("each button references its popover", described == ids, (described, ids))
    check("ids are deterministic (a second run gives the same ids)", re.findall(r"role='tooltip' id='([^']+)'", ri.transform(STUB)) == ids)
    check("ids come from a hash of section id and index, not from document position",
          ids[0] == "rpt-info-" + __import__("hashlib").sha1(b"alpha:1").hexdigest()[:8], ids[0])

    check("idempotent: a second pass changes nothing", ri.transform(out) == out)
    twice = ri.transform(ri.transform(STUB, "<script id='rpt-info-script'>1</script>"), "<script id='rpt-info-script'>1</script>")
    check("the script is added once", twice.count("id='rpt-info-script'") == 1)
    check("section ids and their order are unchanged",
          re.findall(r"<section id='([^']+)'", out) == re.findall(r"<section id='([^']+)'", STUB) == ["alpha", "beta", "summary", "gamma"])
    check("the nav is untouched", re.search(r"<nav.*?</nav>", out, re.S).group(0) == re.search(r"<nav.*?</nav>", STUB, re.S).group(0))
    plain = strip_infos(out)
    check("with the icons removed the headings read as before",
          re.findall(r"<h2>(.*?)</h2>", plain) == re.findall(r"<h2>(.*?)</h2>", STUB))
    check("only the moved notes left the page: removing popovers and empty lead paragraphs leaves no explanatory paragraph",
          LEAD not in plain and MUTED not in plain and CAPTION not in plain)
    with_script = ri.transform(STUB, "<script id='rpt-info-script'>1</script>")
    check("the script lands just before </body>", with_script.endswith("<script id='rpt-info-script'>1</script></body></html>"))

    print("the CSS and script fragments")
    import report_common as rc
    css = rc.STYLE
    check("the popover CSS is at the end of STYLE", css.rstrip().rfind(".rpt-info-pop") > css.rfind(".rpt-collapsible"))
    check("hover and focus show the popover without JavaScript", ".rpt-info:hover>.rpt-info-pop" in css and ".rpt-info:focus-within>.rpt-info-pop" in css)
    check("print shows every note inline and hides the icon", "@media print{.rpt-info{display:block" in css and ".rpt-info-btn{display:none!important}" in css)
    check("reduced motion is respected", "prefers-reduced-motion:no-preference" in css)
    script = open(os.path.join(ROOT, "assets", "report", "info_script.html"), encoding="utf-8").read()
    for needle in ("mouseover", "focusin", "Escape", "stopPropagation", "closest('summary')", "aria-expanded"):
        check(f"the script handles {needle}", needle in script)

    print("a real build of the demo")
    demo_dir = os.path.join(ROOT, "results_demo")
    if not os.path.isfile(os.path.join(demo_dir, "benchmark.paired_comparisons.tsv")):
        print("  (skipped: results_demo is not complete; run test/run_demo.sh first)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "results_demo")
            shutil.copytree(demo_dir, work)
            p = lambda n: os.path.join(work, n)  # noqa: E731
            cmd = [os.path.join(ROOT, "python", "build_html_report.py"), "--project-root", ROOT, "--scores", p("scores.tsv"),
                   "--tool-status", p("tool_status.tsv"), "--leaderboard", p("benchmark.leaderboard.tsv"), "--sample-sheet", p("samples.tsv"),
                   "--recommendations", p("benchmark.recommendations.tsv"), "--recommendation-validation", p("benchmark.recommendation_validation.tsv"),
                   "--manifest", p("run_manifest.json"), "--recovery-by-replicon", p("benchmark.recovery_by_replicon.tsv"),
                   "--truth-label-audit", p("benchmark.truth_label_audit.tsv"), "--dimensions-prefix", p("benchmark"),
                   "--comparisons", p("benchmark.paired_comparisons.tsv"), "--stratified", p("benchmark.stratified.tsv"),
                   "--rank-robustness", p("benchmark.rank_robustness.tsv"), "--data-dir", work, "--label-schemes", p("benchmark.label_schemes.tsv"),
                   "--label-scheme-summary", p("benchmark.label_scheme_summary.tsv"), "--truth-provenance", p("benchmark.truth_provenance.tsv"),
                   "--outcome-states", p("benchmark.outcome_states.tsv"), "--recommender-eval", p("benchmark.recommender_eval.tsv"),
                   "--recommender-verdict", p("benchmark.recommender_verdict.json"), "--warning-eval", p("benchmark.warning_eval.tsv"),
                   "--leave-taxon-out", p("benchmark.leave_taxon_out.tsv"), "--amr-placement", p("benchmark.amr_placement.tsv"),
                   "--contig-crosscheck", p("benchmark.contig_crosscheck.tsv"), "--out", p("benchmark.report.html")]
            # Build in this process with the transform wrapped, so the page as it was just before the transform is captured.
            import build_html_report as bhr
            captured = {}
            real = ri.transform
            ri.transform = lambda page, script=None: (captured.setdefault("pre", page), real(page, script))[1]
            old_argv = sys.argv
            sys.argv = cmd
            try:
                bhr.main()
            finally:
                ri.transform = real
                sys.argv = old_argv
            pre = captured["pre"]
            post = open(p("benchmark.report.html"), encoding="utf-8").read()

        t0 = time.time()
        again, records = ri.transform_with_records(pre)
        elapsed = time.time() - t0
        check(f"the transform of the {len(pre) / 1e6:.1f} MB page takes under 3 s ({elapsed:.2f} s)", elapsed < 3, elapsed)
        moved = [r for r in records if r["action"] == "moved"]
        kept = [r for r in records if r["action"] == "kept"]
        by_kind = {}
        for r in records:
            by_kind.setdefault((r["kind"], r["action"]), 0)
            by_kind[(r["kind"], r["action"])] += 1
        print("  moved/kept by kind:", dict(sorted(by_kind.items())))

        after_h2 = re.findall(r"<section id='([^']+)'[^>]*><h2[^>]*>(?:(?!</h2>).)*</h2><p class='lead'>", post, re.S)
        check("no lead directly after an h2 remains except the deliberately kept ones",
              set(after_h2) <= KEPT_AFTER_H2, sorted(set(after_h2) - KEPT_AFTER_H2))
        distinct = {r["id"] for r in moved}
        check("every moved note has an icon in the page", len(infos(post)) == len(distinct) >= 50, (len(infos(post)), len(distinct)))
        check("at least as many icons as moved leads", post.count("class='rpt-info'") >= sum(1 for r in moved if r["kind"] == "lead") - 5)

        originals = set(re.findall(r"<p class='(?:lead|muted)'>(.*?)</p>", pre, re.S))
        originals |= set(re.findall(r"<figcaption>(.*?)</figcaption>", pre, re.S))
        pops = popovers(post)
        bad = []
        for ident, body in pops:
            parts = [body]
            if body.startswith("<span class='rpt-info-para'>"):
                parts = re.findall(r"<span class='rpt-info-para'>(.*?)</span>(?=<span class='rpt-info-para'>|$)", body, re.S)
            for part in parts:
                if part not in originals:
                    bad.append((ident, part[:60]))
        check("every popover text equals an original note of the pre-transform page", pops and not bad, bad[:3])
        check("popover ids are unique across the page", len({i for i, _ in pops}) == len(pops))
        check("every button points at an existing popover",
              set(re.findall(r"aria-describedby='(rpt-info-[^']+)'", post)) == {i for i, _ in pops})

        kept_text = " ".join(r["note"] for r in kept)
        for must_stay in ("Not run", "All demo data is synthetic"):
            if must_stay in pre:
                check(f"'{must_stay}' is not inside any popover", all(must_stay not in b for _, b in pops))
        check("every status / data note was kept (none of the kept reasons is a bug)", all(r["reason"] for r in kept))
        check("the recommender verdict banner stays on the page", "v3-verdict" not in pre or "v3-verdict" in post.replace("rpt-info-pop", ""))
        check("caution boxes are unchanged", pre.count("insight caution") == post.count("insight caution"))
        check("the Summary lead is not moved", "id='summary'" not in pre or "<section id='summary'" in post)

        sec_pre = re.findall(r"<section id='([^']+)'", pre)
        sec_post = re.findall(r"<section id='([^']+)'", post)
        check("section ids and order unchanged", sec_pre == sec_post and len(sec_post) >= 60, (len(sec_pre), len(sec_post)))
        nav = lambda s: re.findall(r"href='#([^']+)'", re.search(r"<nav class='nav'.*?</nav>", s, re.S).group(0))  # noqa: E731
        check("navigation ids unchanged and all are sections", nav(pre) == nav(post) and set(nav(post)) <= set(sec_post))
        text = lambda s: [html.unescape(re.sub(r"<[^>]+>", "", strip_infos(h))).strip()  # noqa: E731
                          for h in re.findall(r"<h2[^>]*>(.*?)</h2>", s, re.S)]
        check("every h2 reads as before", text(pre) == text(post))
        check("running the transform on the finished page changes nothing", ri.transform(post) == post)
        check("the positioning script is in the page once", post.count("id='rpt-info-script'") == 1)
        check("the viewer and the 3D views build their icons with the same classes",
              "rpt-info-btn" in open(os.path.join(ROOT, "assets", "report", "plasmid_viewer_ui.html"), encoding="utf-8").read()
              and "rpt-info-btn" in open(os.path.join(ROOT, "assets", "report", "viz3d_core.html"), encoding="utf-8").read())
        print(f"  page size {len(pre):,} -> {len(post):,} bytes ({len(post) - len(pre):+,}); {len(distinct)} icons; "
              f"{len(moved)} notes moved, {len(kept)} kept")

    print("ALL REPORT INFO TESTS PASSED" if ok else "REPORT INFO TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
