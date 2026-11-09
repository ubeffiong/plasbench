#!/usr/bin/env python3
"""
Tests for python/report_wiring.py: outputs wired from the stages into the HTML, the grouped navigation, and the
fixes to the paired-comparison and overlap tables.

Hand-computed on small fixtures (stub PAGE as in test_report_learnings.py), then checked on a real build of the demo
(a copy of results_demo, so the demo directory is never modified):
  two truth plasmids, one recovered     -> 2 rows, one 'fragmented', one repeat-rich
  one assembly that failed the gate     -> '0 of 1 assemblies passed'
  regret 0.1 and 0.3                    -> mean regret 0.2000
  one high-depth region                 -> '1 anomalous region(s) marked'
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_common as rc  # noqa: E402
import report_surfaces as rs  # noqa: E402
import report_wiring as rw  # noqa: E402

TAB = chr(9)
ok = True


def check(label, condition, detail=""):
    global ok
    print(("  PASS: " if condition else "  FAIL: ") + label + ("" if condition else "  " + str(detail)))
    ok = ok and bool(condition)


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=chr(10))
        w.writerow(header)
        w.writerows(rows)


def stub(*ids):
    nav = "".join(f"<a href='#{i}'>{i}</a>" for i in ids)
    body = "".join(f"<section id='{i}'><h2>{i} title</h2></section>" for i in ids)
    return f"<style>a{{}}</style><main><nav class='nav'>{nav}</nav>{body}</main>"


PAGE = stub("summary", "leaderboard", "scores", "cohort-qc", "learn-truthqc", "recommender-eval", "recommendations", "files")


def fixture(tmp):
    write(os.path.join(tmp, "s1", "t1.per_plasmid.tsv"),
          ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"],
          [["s1", "t1", "short_read", "pA", "1000", "500", "0.5000", "0"], ["s1", "t1", "short_read", "pB", "200", "200", "1.0000", "1"]])
    write(os.path.join(tmp, "s1", "t1.plasmid_outcomes.tsv"),
          ["true_plasmid", "length", "best_bin", "best_bin_recall", "best_bin_precision", "bins_holding_share", "merged_with",
           "contamination_fraction", "outcome"],
          [["pA", "1000", "bin_1", "0.5", "1", "2", "", "0", "fragmented"], ["pB", "200", "bin_2", "1", "1", "1", "", "0", "perfect"]])
    write(os.path.join(tmp, "s1", "truth_repeat_content.tsv"), ["sample", "sequence_id", "repeat_rich"],
          [["s1", "pA", "yes"], ["s1", "pB", "no"]])
    write(os.path.join(tmp, "s1", "assembly_stats.tsv"), ["sample_id", "assembly_size_bp", "contig_count", "n50", "gc_percent", "plasmid_count"],
          [["s1", "5000", "7", "12345", "50.5", "2"]])
    write(os.path.join(tmp, "benchmark.assembly_qc.tsv"),
          ["sample", "total_length", "n_contigs", "n_long_contigs", "gc_p10", "gc_p90", "gc_spread", "status", "reasons"],
          [["s1", "5000", "7", "3", "0.4", "0.5", "0.1", "fail", "low_n50"]])
    write(os.path.join(tmp, "benchmark.clonal_groups.tsv"), ["sample", "clonal_group", "method"],
          [["s1", "g1", "mash"], ["s2", "g1", "mash"], ["s3", "g2", "mash"]])
    write(os.path.join(tmp, "benchmark.recommender_regret.tsv"),
          ["profile", "sample", "held_out_study", "organism", "recommended_tool", "recommended_score", "predicted_score", "best_tool",
           "best_score", "regret", "near_optimal", "single_best_tool", "single_best_score", "single_best_regret", "floor_flag", "basis"],
          [["f1", "s1", "x", "o", "ta", "0.8", "0.8", "tb", "0.9", "0.1", "yes", "ta", "0.8", "0.1", "no", "loo"],
           ["f1", "s2", "x", "o", "ta", "0.6", "0.6", "tb", "0.9", "0.3", "no", "ta", "0.6", "0.3", "no", "loo"]])
    write(os.path.join(tmp, "s1", "truth_depth_windows.tsv"), ["replicon", "start", "end", "mean_depth"],
          [["pA", "0", "500", "30"], ["pA", "500", "1000", "90"]])
    write(os.path.join(tmp, "s1", "truth_depth_anomalies.tsv"),
          ["sample", "sequence_id", "molecule_type", "start", "end", "direction", "mean_depth", "replicon_median_depth", "fold_change",
           "n_windows"], [["s1", "pA", "PLASMID", "500", "1000", "high", "90", "30", "3", "1"]])
    write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "analysis_track", "f1", "brand_new_metric"], [["s1", "t1", "short_read", "0.5", "7"]])
    write(os.path.join(tmp, "benchmark.leaderboard.tsv"), ["rank", "tool", "mean_f1", "brand_new_board_column"], [["1", "t1", "0.5", "9"]])
    with open(os.path.join(tmp, "benchmark.leaderboard.md"), "w") as handle:
        handle.write("# board\n")


def main():
    print("per-plasmid detail")
    with tempfile.TemporaryDirectory() as tmp:
        fixture(tmp)
        html = str(rw.per_plasmid_section(tmp))
        check("section id", "<section id='per-plasmid-detail'" in html)
        check("one table row per truth plasmid and tool", html.count("<tr data-sample=") == 2, html.count("<tr data-sample="))
        check("outcome classes shown", "fragmented" in html and ">perfect<" in html)
        check("repeat-rich flag carried as a row attribute", "data-repeat='yes'" in html and "data-repeat='no'" in html)
        check("the four filters are present", all(f"id='pp-{k}'" in html for k in ("sample", "tool", "outcome", "repeat-rich")))
        check("no-JS fallback: filters are hidden until the script runs, no row is hidden",
              "id='pp-controls' hidden" in html and "<tr hidden" not in html and "<script>" in html)
        check("completeness value", ">0.5000<" in html)
    empty = str(rw.per_plasmid_section(tempfile.mkdtemp()))
    check("no inputs: Not run with a reason", "Not run:" in empty and "per_plasmid" in empty)

    print("assembly quality")
    with tempfile.TemporaryDirectory() as tmp:
        fixture(tmp)
        html = str(rw.assembly_quality_section(tmp))
        check("N50 and failed gate with reason shown", ">12345<" in html and "low_n50" in html and "fail" in html)
        check("hand-computed pass count", "<strong>0</strong> of <strong>1</strong> assemblies passed" in html, html[:400])
    check("assembly quality, no inputs: Not run", "Not run:" in str(rw.assembly_quality_section(tempfile.mkdtemp())))

    print("cohort, recommender, depth")
    with tempfile.TemporaryDirectory() as tmp:
        fixture(tmp)
        clon = rw.clonal_groups_html(tmp)
        check("clonal groups: 3 isolates in 2 groups, 1 multi-isolate group",
              "<strong>3</strong> isolates fall in <strong>2</strong> groups" in clon and "<strong>1</strong> group(s)" in clon)
        check("clonal group members listed", "s1, s2" in clon)
        reg = rw.regret_html(tmp)
        check("mean regret (0.1 + 0.3) / 2 = 0.2000", "<strong>0.2000</strong>" in reg, reg[:300])
        strip = rw.depth_strip_html(tmp)
        check("depth strip is an inline svg with a marked anomaly", "<svg" in strip and "1 anomalous region(s) marked" in strip)
        page = rw.inject(PAGE, tmp, None, os.path.join(tmp, "scores.tsv"))
        cohort = page[page.index("<section id='cohort-qc'"):]
        check("clonal groups sit inside the cohort-qc section", cohort.index("Clonal groups") < cohort.index("</section>"))
        check("regret sits inside recommender-eval", page.index("Regret per isolate") > page.index("<section id='recommender-eval'")
              and page.index("Regret per isolate") < page.index("<section id='recommendations'"))
        check("truth depth sits inside learn-truthqc", page.index("Read-depth windows") > page.index("<section id='learn-truthqc'"))
        ids = re.findall(r"<section id='([a-z-]+)'", page)
        check("section ids stay unique and match [a-z-]+", len(ids) == len(set(ids)) and "per-plasmid-detail" in ids and "assembly-quality" in ids)
    blank = tempfile.mkdtemp()
    for fn in (rw.clonal_groups_html, rw.regret_html, rw.depth_strip_html):
        check(f"{fn.__name__} with no input says Not run", "Not run:" in fn(blank))

    print("Run files")
    with tempfile.TemporaryDirectory() as tmp:
        fixture(tmp)
        html = rw.files_html(tmp)
        check("link to the existing leaderboard, relative", "href='benchmark.leaderboard.md'" in html)
        check("no link to a file that does not exist", "benchmark.scoring_spec.md'" not in html.replace("<span class='muted'>benchmark.scoring_spec.md", "")
              and "not written in this run" in html)
        hrefs = re.findall(r"href='([^#'][^']*)'", html)
        check("every link target exists", all(os.path.isfile(os.path.join(tmp, h)) for h in hrefs), hrefs)

    print("column groups")
    with tempfile.TemporaryDirectory() as tmp:
        fixture(tmp)
        html = rw.score_columns_html(os.path.join(tmp, "scores.tsv"))
        check("unregistered column appears under Other", "data-cg='Other'" in html and "brand_new_metric" in html)
        check("no-JS: nothing is hidden in the markup, chips are hidden until the script runs",
              re.search(r"<th data-cg='[^']+' hidden", html) is None and "rpt-chips' hidden" in html)
        board = rw.leaderboard_columns_html(tmp)
        check("leaderboard more-columns toggle keeps the unregistered column", "brand_new_board_column" in board and "<details" in board)
    demo = os.path.join(ROOT, "results_demo", "scores.tsv")
    if os.path.isfile(demo):
        header = open(demo, encoding="utf-8").readline().rstrip("\n").split(TAB)
        grouped = [c for _, cols in rw.group_columns(header, rs.SCORE_COLUMN_GROUPS) for c in cols]
        check("score column groups cover every column of the demo scores.tsv exactly once",
              sorted(grouped) == sorted(header), set(header) ^ set(grouped))
        check("every Core column of the demo is in a named group, not Other",
              not [c for c in rs.SCORE_COLUMN_GROUPS["Core"] if c in header and c in
                   dict(rw.group_columns(header, rs.SCORE_COLUMN_GROUPS)).get("Other", [])])

    print("navigation")
    ids = ["summary", "leaderboard", "mystery-section", "scorecard", "files", "recommendations"]
    groups = rw.grouped_nav(ids, {})
    flat = [i for links in groups.values() for i, _ in links]
    check("every id appears exactly once", sorted(flat) == sorted(ids), flat)
    check("an unknown id goes to More", [i for i, _ in groups.get("More", [])] == ["mystery-section"])
    check("More comes last", list(groups)[-1] == "More")
    check("known ids go to their groups", [i for i, _ in groups["Results"]] == ["summary", "leaderboard"]
          and [i for i, _ in groups["Appendix"]] == ["files"])
    page = rw.group_navigation(stub(*ids))
    nav = page[page.index("<nav class='nav'"):page.index("</nav>")]
    check("grouped nav keeps class nav and has collapsible groups", "<details" in nav and "rpt-navgroups" in nav)
    check("every section is linked once", sorted(re.findall(r"href='#([a-z-]+)'", nav)) == sorted(ids))
    check("nav scripts attached (current-group highlight)", "data-navgroup" in page and "MutationObserver" in page)
    check("print CSS hides the nav", "@media print{.nav{display:none}" in rw.WIRING_STYLE.replace("\n", ""))
    allgrouped = {i for g in rw._G.values() for i in g.split()}
    check("group table has no id in two groups",
          sum(len(g.split()) for g in rw._G.values()) == len(allgrouped))
    page2 = rw.finish(stub("summary", "leaderboard", "recommendations", "scorecard", "plasmid-maps"))
    order = re.findall(r"<section id='([a-z-]+)'", page2)
    check("scorecard and maps move up behind the leaderboard",
          order == ["summary", "leaderboard", "scorecard", "plasmid-maps", "recommendations"], order)

    print("overlap wording")
    check("no reference database: every screen row says so",
          rw.overlap_cell(0, 0, 0, ["no_reference_database", "no_reference_database"]) == rw.NO_DB)
    check("checked with no overlap found is different", rw.overlap_cell(0, 3, 0, []).startswith("checked, no overlap found"))
    check("cannot tell without screen rows, and says so", "cannot tell" in rw.overlap_cell(0, 0, 0, []))
    check("possible overlap leaves the default text", rw.overlap_cell(2, 1, 0, ["possible_overlap"]) is None)

    print("a real build of the demo")
    demo_dir = os.path.join(ROOT, "results_demo")
    if not os.path.isfile(os.path.join(demo_dir, "benchmark.paired_comparisons.tsv")):
        print("  (skipped: results_demo is not complete; run test/run_demo.sh first)")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "results_demo")
            shutil.copytree(demo_dir, work)
            p = lambda n: os.path.join(work, n)  # noqa: E731
            cmd = [sys.executable, os.path.join(ROOT, "python", "build_html_report.py"), "--project-root", ROOT, "--scores", p("scores.tsv"),
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
            done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
            check("the report builds", done.returncode == 0, done.stderr[-800:])
            html = open(p("benchmark.report.html"), encoding="utf-8").read()
            sec = lambda sid: html[html.index(f"<section id='{sid}'"):html.index("</section>", html.index(f"<section id='{sid}'"))]  # noqa: E731
            pp = sec("per-plasmid-detail")
            n_rows = sum(len(rows) for rows in [list(csv.DictReader(open(f, encoding="utf-8"), delimiter=TAB))
                                                for f in __import__("glob").glob(os.path.join(work, "*", "*.per_plasmid.tsv"))])
            check("per-plasmid table has one row per per_plasmid.tsv row", pp.count("<tr data-sample=") == n_rows, (pp.count("<tr data-sample="), n_rows))
            check("per-plasmid outcome classes and repeat flags from the demo", "merged" in pp and "data-repeat='yes'" in pp)
            aq = sec("assembly-quality")
            check("assembly quality lists the six demo samples", all(s in aq for s in ("abauma_a", "ecoli_b", "kpneu_b")) and "assemblies passed" in aq)
            st = sec("statistics")
            check("paired table has track, task, metric, Wilcoxon Holm and equivalence columns",
                  all(h in st for h in ("<th>Track</th>", "<th>Task</th>", "<th>Metric</th>", "Wilcoxon p (Holm)", "Equivalent within delta")))
            check("paired values from the demo (platon_like vs weak_like, 0.5331, 0.093750)", "0.5331" in st and "0.093750" in st)
            check("paired table grouped by track", "Track: short_read" in st)
            check("regret table present", "Regret per isolate" in sec("recommender-eval"))
            rob = sec("robustness")
            check("overlap cell never claims 'no reference database' without screen rows",
                  "n/a (tool uses no reference database)" not in rob or os.path.isfile(p("benchmark.database_overlap.tsv")))
            check("overlap cell says it cannot tell when the screen has no rows", "cannot tell" in rob or "possible /" in rob or "not assessed" in rob)
            check("score column-group table covers every scores.tsv column",
                  html.count("<th data-cg=", html.index("id='score-groups-table'"), html.index("</table>", html.index("id='score-groups-table'")))
                  == len(open(p("scores.tsv"), encoding="utf-8").readline().rstrip("\n").split(TAB)))
            check("leaderboard more-columns toggle present", "id='leaderboard-groups-table'" in html)
            hrefs = [h for h in re.findall(r"href='([^#'][^']*\.md)'", sec("files"))]
            check("Run files links exist and include the leaderboard and the spec",
                  hrefs and all(os.path.isfile(p(h)) for h in hrefs) and "benchmark.leaderboard.md" in hrefs and "benchmark.scoring_spec.md" in hrefs, hrefs)
            for sid, marker in (("headline-design", "<table"), ("metric-framework", "<table"), ("scorecard-definitions", "<table"),
                                ("interpretation-limits", "These results do NOT show"),
                                ("per-plasmid-detail", "<table")):
                block = sec(sid)
                check(f"{sid}: its detail is collapsed in a closed <details> until clicked",
                      "<details class='rpt-collapsible'>" in block and "<details class='rpt-collapsible' open" not in block
                      and block.index("<details") < block.index(marker) < block.index("</details>"))
            nav = html[html.index("<nav class='nav'"):html.index("</nav>")]
            ids = re.findall(r"<section id='([a-z-]+)'", html)
            check("nav links every section exactly once", sorted(re.findall(r"href='#([a-z-]+)'", nav)) == sorted(ids))
            groups = re.findall(r"data-navgroup='([^']+)'", nav)
            check("the named groups lead the nav in order (Figures only when a figure module produced a section)",
                  groups[:len(groups)] == [g for g in rw.NAV_GROUP_ORDER if g in groups] and len(groups) >= 6, groups)
            check("scorecard sits right after the robustness section", ids.index("scorecard") == ids.index("robustness") + 1, ids[:10])
            check("inventory no longer lists the wired outputs as not shown", "Not shown yet" not in sec("data-inventory"))

    print()
    if not ok:
        print("REPORT WIRING TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT WIRING TESTS PASSED")


if __name__ == "__main__":
    main()
