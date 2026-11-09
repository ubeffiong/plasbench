#!/usr/bin/env python3
"""
report_wiring.py -- wires pipeline outputs that the report did not show into HTML, and groups the navigation.

  per-plasmid-detail   one row per truth plasmid and tool (per_plasmid.tsv + plasmid_outcomes.tsv + truth_repeat_content.tsv)
                       with client-side filters; without JavaScript the whole table is shown
  assembly-quality     assembly_stats.tsv and the assembly quality gate (assembly_qc.tsv, benchmark.assembly_qc.tsv)
  clonal groups        appended to cohort-qc (benchmark.clonal_groups.tsv)
  recommender regret   appended to recommender-eval (benchmark.recommender_regret.tsv)
  truth depth strip    appended to learn-truthqc (<sample>/truth_depth_windows.tsv, anomalies marked)
  score column groups  all columns of scores.tsv / the leaderboard behind group switches (unregistered columns: "Other")
  Run files            links to the Markdown outputs that exist (leaderboards, scoring specification), appended to `files`
  grouped navigation   the flat nav replaced by collapsible groups; every section id appears once; unknown ids go to "More"
  overlap_cell         tells "tool uses no reference database" from "checked, no overlap found"

Every section says "Not run: <reason>" when its input is absent. Standard library only.
"""
import glob
import os
import re

import report_common as rc
import report_surfaces
import report_svg as svg

TAB = chr(9)


def asset(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "report", name)
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


WIRING_STYLE = """
.rpt-controls{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0;font:13px Arial,sans-serif}
.rpt-controls[hidden]{display:none}
.rpt-colgroups table{min-width:0}
.rpt-colgroups [data-cg][hidden]{display:none}
.rpt-allcols>summary{cursor:pointer;font:bold 14px Arial,sans-serif;padding:8px 0}
.rpt-trackrow{margin:14px 0 4px;font:bold 14px Arial,sans-serif}
.nav[data-grouped]{overflow:visible}
.nav[data-grouped] .rpt-navgroups{width:100%}
.rpt-navgroups details{position:relative}
.rpt-navgroups details[data-current] summary{color:var(--green)}
.rpt-navgroups details[open]>summary{border-bottom:1px solid var(--line)}
.rpt-navlist{position:absolute;left:0;top:100%;z-index:40;min-width:230px;max-height:60vh;overflow:auto;background:#fff;
 border:1px solid var(--line);border-radius:8px;padding:6px 10px;box-shadow:0 4px 12px rgba(21,36,28,.15)}
.rpt-navgroups a{padding:4px 6px;border-radius:5px}
.rpt-navgroups a:hover{background:#eef4ef;color:var(--ink)}
.rpt-navgroups a[aria-current='true']{background:var(--green);color:#fff}
.rpt-strip text{font-family:Arial,sans-serif}
@media print{.nav{display:none}.rpt-controls{display:none}}
"""


def add_style(page):
    page = rc.add_style(page)
    if "rpt-navlist" in page.split("</style>", 1)[0]:
        return page
    return page.replace("</style>", WIRING_STYLE + "</style>", 1)


# ------------------------------------------------------------------------------------------------ page helpers
def section_ids(page):
    return re.findall(r"<section id='([a-z-]+)'", page)


def _section_end(page, start):
    """Index of the </section> that closes the section opening at `start`, skipping any inside an embedded <script>."""
    end = page.find("</section>", start)
    while end >= 0:
        chunk = page[start:end]
        if chunk.count("<script") == chunk.count("</script"):
            return end
        end = page.find("</section>", end + 1)
    return -1


def attach(page, sid, body_html, fallback_title, fallback_lead, fallback_id=None):
    """Append `body_html` inside section `sid`; when it is absent add a new section `fallback_id` before Recommendations."""
    start = page.find(f"<section id='{sid}'")
    if start >= 0:
        end = _section_end(page, start)
        if end >= 0:
            return page[:end] + body_html + page[end:]
    return rc.inject_sections(page, str(rc.section(fallback_id or sid + "-extra", fallback_title, fallback_lead, body_html)), [])


def block_bounds(page, sid):
    start = page.find(f"<section id='{sid}'")
    if start < 0:
        return None
    end = _section_end(page, start)
    if end < 0 or page.count("<section", start, end) != 1:
        return None
    return start, end + len("</section>")


def move_after(page, ids, after_ids):
    """Move the sections `ids` (in the order given) to just after the first of `after_ids` that exists."""
    anchor = next((a for a in after_ids if block_bounds(page, a)), None)
    if anchor is None:
        return page
    blocks = []
    for sid in ids:
        bounds = block_bounds(page, sid)
        if bounds and sid != anchor:
            blocks.append((sid, page[bounds[0]:bounds[1]]))
    if not blocks:
        return page
    for sid, text in blocks:
        page = page.replace(text, "", 1)
    end = block_bounds(page, anchor)[1]
    return page[:end] + "".join(text for _, text in blocks) + page[end:]


def sample_dirs(*roots):
    seen, out = set(), []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isdir(path) and not name.startswith(".") and name not in seen:
                seen.add(name)
                out.append((name, path))
    return sorted(out)


def sample_file(name, sample, *roots):
    for root in roots:
        if root:
            path = os.path.join(root, sample, name)
            if os.path.isfile(path):
                return path
    return None


def dash(value, reason="not recorded"):
    return rc.missing(reason) if value in (None, "") else value


# ------------------------------------------------------------------------------------------------ per-plasmid detail
def per_plasmid_rows(results_dir, data_dir=None):
    roots = [results_dir] + ([data_dir] if data_dir and data_dir != results_dir else [])
    rows = []
    for sample, _ in sample_dirs(*roots):
        repeat = {r.get("sequence_id"): r.get("repeat_rich", "")
                  for r in (rc.read_tsv(sample_file("truth_repeat_content.tsv", sample, *roots)) or [])}
        files = []
        for root in roots:
            files += glob.glob(os.path.join(root, sample, "*.per_plasmid.tsv"))
        for path in sorted(set(files)):
            tool = os.path.basename(path)[:-len(".per_plasmid.tsv")]
            outcome_path = os.path.join(os.path.dirname(path), tool + ".plasmid_outcomes.tsv")
            outcomes = {r.get("true_plasmid"): r for r in (rc.read_tsv(outcome_path) or [])}
            for r in rc.read_tsv(path) or []:
                o = outcomes.get(r.get("sequence_id"), {})
                extra = {k: v for k, v in {**r, **o}.items() if "replicon" in k.lower() and v not in (None, "")}
                rows.append({"sample": r.get("sample") or sample, "tool": r.get("tool") or tool,
                             "track": r.get("analysis_track", ""), "plasmid": r.get("sequence_id", ""),
                             "length": r.get("length", ""), "completeness": r.get("completeness", ""),
                             "recovered": r.get("recovered", ""), "outcome": o.get("outcome", ""),
                             "repeat": (repeat.get(r.get("sequence_id")) or ""), "bin": o.get("best_bin", ""),
                             "merged_with": o.get("merged_with", ""), "extra": extra})
    return rows


def per_plasmid_section(results_dir, data_dir=None):
    title = "Per-plasmid detail: which truth plasmids each tool recovered"
    lead = ("One row for each truth plasmid and tool: how much of it was covered, the outcome class, whether it is repeat-rich "
            "and which bin held it. The same rows are in the Tools tab of the plasmid map viewer. Filter by sample, tool, outcome or repeat "
            "content; without JavaScript every row is shown.")
    rows = per_plasmid_rows(results_dir, data_dir)
    if not rows:
        return rc.section("per-plasmid-detail", title, lead,
                          rc.not_run("no <sample>/<tool>.per_plasmid.tsv was found (the scoring stage did not write per-plasmid results)."))
    extras = sorted({k for r in rows for k in r["extra"]})
    headers = ["Sample", "Tool", "Track", "Plasmid", "Length (bp)", "Completeness", "Recovered", "Outcome", "Repeat-rich",
               "Best bin", "Merged with"] + [k.replace("_", " ").capitalize() for k in extras]

    def opts(label, values):
        return (f"<label>{rc.esc(label)} <select id='pp-{label.lower().replace(' ', '-')}'><option value=''>All</option>"
                + "".join(f"<option>{rc.esc(v)}</option>" for v in values) + "</select></label>")
    controls = ("<div class='rpt-controls' id='pp-controls' hidden data-needs-js>"
                + opts("Sample", sorted({r["sample"] for r in rows})) + opts("Tool", sorted({r["tool"] for r in rows}))
                + opts("Outcome", sorted({r["outcome"] or "no outcome class" for r in rows}))
                + opts("Repeat-rich", ["yes", "no"]) + "<span id='pp-count' class='count'></span></div>")
    body_rows = []
    for r in rows:
        outcome = r["outcome"] or "no outcome class"
        cells = [r["sample"], r["tool"], dash(r["track"]), r["plasmid"], dash(r["length"]), dash(r["completeness"]),
                 "yes" if r["recovered"] == "1" else ("no" if r["recovered"] == "0" else dash(r["recovered"])),
                 r["outcome"] or rc.missing("no outcome table for this tool (not a binning method)"),
                 r["repeat"] or rc.missing("no repeat-content table"), dash(r["bin"], "no bin"), dash(r["merged_with"], "none")]
        cells += [r["extra"].get(k, "") for k in extras]
        body_rows.append(f"<tr data-sample='{rc.esc(r['sample'])}' data-tool='{rc.esc(r['tool'])}' data-outcome='{rc.esc(outcome)}' "
                         f"data-repeat='{rc.esc(r['repeat'] or 'unknown')}'>" + "".join(f"<td>{rc.cell(c)}</td>" for c in cells) + "</tr>")
    table = (f"<div class='panel'><table id='pp-table' class='sortable'><thead><tr>{''.join(f'<th>{rc.esc(h)}</th>' for h in headers)}"
             f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>")
    # the same rows are in the Tools tab of the interactive plasmid map viewer, so the table is collapsed until asked for
    folded = ("<details class='rpt-collapsible'><summary>Show the per-plasmid table (all samples and tools)</summary>"
              + controls + table + "</details>")
    return rc.section("per-plasmid-detail", title, lead, folded + asset("per_plasmid_filter_script.html"))


# ------------------------------------------------------------------------------------------------ assembly quality
def assembly_quality_section(results_dir, data_dir=None):
    title = "Assembly quality: size, contiguity and the quality gate"
    lead = ("The short-read assembly of each sample (size, contigs, N50, GC) and whether it passed the assembly quality gate. "
            "<strong>The gate is advisory: it never removes a sample from scoring.</strong>")
    roots = [results_dir] + ([data_dir] if data_dir and data_dir != results_dir else [])
    stats, qc = {}, {}
    for sample, _ in sample_dirs(*roots):
        for r in rc.read_tsv(sample_file("assembly_stats.tsv", sample, *roots)) or []:
            stats[r.get("sample_id") or sample] = r
        for r in rc.read_tsv(sample_file("assembly_qc.tsv", sample, *roots)) or []:
            qc[r.get("sample") or sample] = r
    aggregate = rc.read_tsv(os.path.join(results_dir, "benchmark.assembly_qc.tsv"))
    for r in aggregate or []:
        qc[r.get("sample", "")] = r
    if not stats and not qc:
        return rc.section("assembly-quality", title, lead, rc.not_run(
            "neither assembly_stats.tsv (per sample) nor assembly_qc.tsv / benchmark.assembly_qc.tsv was written (no assembly stage ran)."))
    rows, passed = [], 0
    for sample in sorted(set(stats) | set(qc)):
        s, q = stats.get(sample, {}), qc.get(sample, {})
        status = q.get("status", "")
        passed += status == "pass"
        chip = (rc.Raw(f"<span class='rpt-band rpt-band-{'excellent' if status == 'pass' else 'poor'}'>"
                       f"<span aria-hidden='true'>{'●' if status == 'pass' else '■'}</span> {rc.esc(status)}</span>")
                if status else rc.missing("the quality gate did not run for this sample"))
        rows.append([sample, dash(s.get("assembly_size_bp") or q.get("total_length"), "no assembly statistics"),
                     dash(s.get("contig_count") or q.get("n_contigs")), dash(q.get("n_long_contigs")), dash(s.get("n50")),
                     dash(s.get("gc_percent")), dash(q.get("gc_spread")), dash(s.get("plasmid_count")), chip,
                     q.get("reasons") or ("none (passed)" if status == "pass" else rc.missing("gate not run" if not status else "no reason recorded", "-"))])
    judged = sum(1 for sample in qc if qc[sample].get("status"))
    summary = (f"<p class='muted'><strong>{passed}</strong> of <strong>{judged}</strong> assemblies passed the gate.</p>"
               if judged else str(rc.note("The quality gate did not run, so no assembly was judged.")))
    table = rc.panel(["Sample", "Assembly size (bp)", "Contigs", "Long contigs", "N50 (bp)", "GC %", "GC spread (p90-p10)",
                      "Plasmid count", "Gate", "Reasons"], rows)
    return rc.section("assembly-quality", title, lead, summary + str(table))


# ------------------------------------------------------------------------------------------------ cohort-qc, recommender
def clonal_groups_html(results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, "benchmark.clonal_groups.tsv"))
    if rows is None:
        return "<h3>Clonal groups</h3>" + str(rc.not_run("benchmark.clonal_groups.tsv was not written (the clonal grouping step did not run)."))
    groups = {}
    for r in rows:
        groups.setdefault(r.get("clonal_group", ""), []).append(r)
    table = [[g or rc.missing("no group assigned"), len(members), ", ".join(m.get("sample", "") for m in members),
              ", ".join(sorted({m.get("method", "") for m in members if m.get("method")})) or rc.missing("not recorded")]
             for g, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    multi = sum(1 for m in groups.values() if len(m) > 1)
    return ("<h3>Clonal groups</h3><p class='muted'>Isolates in one group are near-identical and count as one independent unit in the "
            f"statistics. <strong>{len(rows)}</strong> isolates fall in <strong>{len(groups)}</strong> groups; "
            f"<strong>{multi}</strong> group(s) hold more than one isolate.</p>"
            + str(rc.panel(["Clonal group", "Isolates", "Samples", "Method"], table)))


def regret_html(results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, "benchmark.recommender_regret.tsv"))
    if rows is None:
        return "<h3>Regret per isolate</h3>" + str(rc.not_run("benchmark.recommender_regret.tsv was not written (the recommender was not evaluated)."))
    if not rows:
        return "<h3>Regret per isolate</h3>" + str(rc.not_run("benchmark.recommender_regret.tsv has no rows (too few isolates to evaluate)."))
    regrets = [rc.number(r.get("regret")) for r in rows]
    mean_regret = rc.mean(regrets)
    table = [[r.get("profile", ""), r.get("sample", ""), dash(r.get("recommended_tool")), dash(r.get("best_tool")),
              rc.fmt(rc.number(r.get("regret")), 4), r.get("near_optimal") or rc.missing("not judged"),
              dash(r.get("single_best_tool")), rc.fmt(rc.number(r.get("single_best_regret")), 4),
              r.get("floor_flag") or rc.missing("not judged"), dash(r.get("basis"))] for r in rows]
    return ("<h3>Regret per isolate</h3><p class='muted'>Regret is the score of the best tool minus the score of the recommended tool "
            f"on that isolate. Mean regret over the <strong>{len(rows)}</strong> rows is <strong>{rc.fmt(mean_regret, 4)}</strong>.</p>"
            + "<details class='rpt-collapsible'><summary>Show the regret table (the 3D view above draws the same rows)</summary>"
            + str(rc.panel(["Profile", "Sample", "Recommended", "Best tool", "Regret", "Near-optimal", "Single best tool",
                            "Single-best regret", "Floor flag", "Basis"], table)) + "</details>")


# ------------------------------------------------------------------------------------------------ truth depth strip
def _depth_strip(sample, windows, regions):
    by_rep = {}
    for r in windows:
        s, e, d = rc.number(r.get("start")), rc.number(r.get("end")), rc.number(r.get("mean_depth"))
        if None not in (s, e, d):
            by_rep.setdefault(r.get("replicon", ""), []).append((s, e, d))
    if not by_rep:
        return None
    reps = sorted(by_rep, key=lambda k: -max(e for _, e, _ in by_rep[k]))[:12]
    width, left, right, rowh = 880, 150, 20, 46
    height = 30 + rowh * len(reps)
    out = [svg.svg_open(width, height, f"Read depth along the truth replicons of {sample}",
                        "Depth per window; shapes below the strip mark high (triangle up) and low (triangle down) depth regions.",
                        "rpt-strip")]
    top = max(d for r in reps for _, _, d in by_rep[r]) or 1.0
    marked = 0
    for i, rep in enumerate(reps):
        y0 = 18 + i * rowh
        length = max(e for _, e, _ in by_rep[rep])
        scale = (width - left - right) / length
        out.append(svg.text(left - 8, y0 + 18, rep[:22], 11, "end"))
        pts = [f"M{left:.1f},{y0 + 28:.1f}"]
        for s, e, d in sorted(by_rep[rep]):
            y = y0 + 28 - 26 * d / top
            pts.append(f"L{left + s * scale:.1f},{y:.1f}L{left + e * scale:.1f},{y:.1f}")
        pts.append(f"L{left + length * scale:.1f},{y0 + 28:.1f}Z")
        out.append(svg.path("".join(pts), fill="#9db8d8", stroke="#2563c9", width=0.6, title=f"{rep}: depth per window"))
        out.append(svg.line(left, y0 + 28, width - right, y0 + 28, "#666", 0.8))
        for a in regions:
            if a.get("sequence_id") != rep:
                continue
            s, e = rc.number(a.get("start")), rc.number(a.get("end"))
            if s is None or e is None:
                continue
            high = (a.get("direction") or "").lower().startswith("high")
            x1, x2 = left + s * scale, max(left + e * scale, left + s * scale + 3)
            colour = "#b3261e" if high else "#a35c05"
            out.append(f"<rect x='{x1:.1f}' y='{y0:.1f}' width='{x2 - x1:.1f}' height='28' fill='{colour}' fill-opacity='.22' "
                       f"stroke='{colour}' stroke-width='1'><title>{rc.esc(rep)} {'high' if high else 'low'}-depth region "
                       f"{int(s)}-{int(e)}</title></rect>")
            tri = (f"M{(x1 + x2) / 2 - 4:.1f},{y0 + 40:.1f}L{(x1 + x2) / 2 + 4:.1f},{y0 + 40:.1f}L{(x1 + x2) / 2:.1f},{y0 + 33:.1f}Z" if high
                   else f"M{(x1 + x2) / 2 - 4:.1f},{y0 + 33:.1f}L{(x1 + x2) / 2 + 4:.1f},{y0 + 33:.1f}L{(x1 + x2) / 2:.1f},{y0 + 40:.1f}Z")
            out.append(svg.path(tri, fill=colour))
            marked += 1
    out.append(svg.svg_close())
    return "".join(out), marked, len(reps)


def depth_strip_html(results_dir, data_dir=None):
    roots = [results_dir] + ([data_dir] if data_dir and data_dir != results_dir else [])
    figures = []
    for sample, _ in sample_dirs(*roots):
        windows = rc.read_tsv(sample_file("truth_depth_windows.tsv", sample, *roots))
        if not windows:
            continue
        regions = rc.read_tsv(sample_file("truth_depth_anomalies.tsv", sample, *roots)) or []
        built = _depth_strip(sample, windows, regions)
        if built:
            figure, marked, n = built
            figures.append(f"<figure class='rpt-figure'>{figure}<figcaption><strong>{rc.esc(sample)}</strong>: {n} replicon(s); "
                           f"{marked} anomalous region(s) marked (red triangle up: high depth; amber triangle down: low depth).</figcaption></figure>")
    if not figures:
        return "<h3>Read-depth windows</h3>" + str(rc.not_run(
            "no <sample>/truth_depth_windows.tsv was written (RUN_TRUTH_DEPTH_ANOMALIES is off by default)."))
    return "<h3>Read-depth windows along the truth</h3>" + "".join(figures)


# ------------------------------------------------------------------------------------------------ column groups
def group_columns(header, groups):
    """[(group, [columns present])] in the registry's group order, with unregistered columns last under 'Other'."""
    where = {c: g for g, cols in groups.items() for c in cols}
    out = {g: [] for g in groups}
    for c in header:
        out.setdefault(where.get(c, "Other"), []).append(c)
    return [(g, cols) for g, cols in out.items() if cols]


def grouped_table(table_id, rows, header, groups, default_groups):
    cols = [(g, c) for g, cs in group_columns(header, groups) for c in cs]
    gnames = [g for g, _ in group_columns(header, groups)]
    chips = ("<div class='rpt-chips' hidden data-needs-js>"
             + "".join(f"<label><input type='checkbox' data-cg-toggle='{rc.esc(g)}'> {rc.esc(g)}</label>" for g in gnames) + "</div>")
    head = "".join(f"<th data-cg='{rc.esc(g)}'>{rc.esc(c)}</th>" for g, c in cols)
    body = "".join("<tr>" + "".join(f"<td data-cg='{rc.esc(g)}'>" + (rc.esc(r.get(c)) if r.get(c) not in (None, "")
                                                                      else str(rc.missing("not available"))) + "</td>"
                                    for g, c in cols) + "</tr>" for r in rows)
    return (f"<div class='rpt-colgroups' data-default='{rc.esc('|'.join(default_groups))}'>{chips}"
            f"<div class='panel'><table id='{table_id}' class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
            f"</div>")


def score_columns_html(scores_path):
    rows = rc.read_tsv(scores_path)
    if not rows:
        return "<h3>All score columns by group</h3>" + str(rc.not_run("scores.tsv has no rows."))
    header = list(rows[0].keys())
    return ("<details class='rpt-allcols' open><summary>All score columns by group (" + str(len(header)) + " columns)</summary>"
            "<p class='muted'>Switch column groups on or off; without JavaScript every column is shown. Columns the report does not "
            "know yet appear under Other.</p>"
            + grouped_table("score-groups-table", rows, header, report_surfaces.SCORE_COLUMN_GROUPS, ["Identity", "Core"])
            + "</details>" + asset("column_groups_script.html"))


def leaderboard_columns_html(results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv"))
    if not rows:
        return "<h3>More leaderboard columns</h3>" + str(rc.not_run("benchmark.leaderboard.tsv was not written."))
    return ("<details class='rpt-allcols'><summary>More columns of the leaderboard (" + str(len(rows[0])) + " columns)</summary>"
            "<p class='muted'>The full leaderboard, one row per track and tool. Switch column groups on or off; without JavaScript "
            "every column is shown.</p>"
            + grouped_table("leaderboard-groups-table", rows, list(rows[0].keys()), report_surfaces.LEADERBOARD_COLUMN_GROUPS,
                            ["Rank and basis", "Base-level accuracy"])
            + "</details>" + asset("column_groups_script.html"))


# ------------------------------------------------------------------------------------------------ Run files
def run_files(results_dir):
    """[(label, filename, exists)] for the Markdown outputs worth linking."""
    wanted = [("Leaderboard (Markdown)", "benchmark.leaderboard.md")]
    wanted += [(f"Leaderboard, track {os.path.basename(p)[len('benchmark.'):-len('.leaderboard.md')]} (Markdown)", os.path.basename(p))
               for p in sorted(glob.glob(os.path.join(results_dir, "benchmark.*.leaderboard.md")))]
    wanted.append(("Scoring specification (text)", "benchmark.scoring_spec.md"))
    return [(label, name, os.path.isfile(os.path.join(results_dir, name))) for label, name in wanted]


def files_html(results_dir):
    items = []
    for label, name, exists in run_files(results_dir):
        if exists:
            items.append(f"<li><a href='{rc.esc(name)}'>{rc.esc(label)}</a> <span class='muted'>{rc.esc(name)}</span></li>")
        else:
            items.append(f"<li>{rc.esc(label)}: {rc.missing('not written in this run', 'not written in this run')}</li>")
    return ("<h3 id='run-files'>Run files</h3><p class='muted'>Plain-text copies of the main results, next to this report.</p><ul>"
            + "".join(items) + "</ul>")


# ------------------------------------------------------------------------------------------------ database overlap wording
NO_DB = "n/a (tool uses no reference database)"


def overlap_statuses(results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, "benchmark.database_overlap.tsv")) if results_dir else None
    out = {}
    for r in rows or []:
        out.setdefault(r.get("tool", ""), []).append(r.get("overlap_status", ""))
    return out


def overlap_cell(possible, after, unknown, statuses):
    """Cell text (plain text; no HTML) for a tool with no unknown-only result.

    statuses: the overlap_status of every sample for this tool in benchmark.database_overlap.tsv ([] when unavailable).
    """
    if possible == 0 and after == 0 and unknown == 0:
        if statuses and all(s == "no_reference_database" for s in statuses):
            return NO_DB
        return ("cannot tell: no database-overlap rows for this tool, so 'uses no reference database' and 'checked, "
                "no overlap found' look the same (0 possible, 0 after)")
    if possible == 0 and after > 0 and unknown == 0:
        return f"checked, no overlap found (0 possible / {int(after)} after)"
    return None


# ------------------------------------------------------------------------------------------------ navigation
NAV_GROUP_ORDER = ["Results", "Scorecard and maps", "Figures", "Evidence and quality", "Recommendation", "Methods and limits", "Appendix"]
_G = {
    "Results": "summary metadata insights chart leaderboard robustness scores statistics stratified scenarios enterprise selected "
               "tools samples",
    "Scorecard and maps": "scorecard scorecard-definitions scorecard-scenarios plasmid-maps per-plasmid-detail "
                          "plasmid-outcomes bin-diagnostics bin-quality graded-tiers replicon-recovery zero-plasmid contig-layer "
                          "amr-placement learn-agreement learn-copynumber accuracy-dimension feature-preservation",
    "Figures": "fig-ladder fig-landscape fig-heatmap fig-distributions fig-forest fig-pr",
    "Evidence and quality": "database-membership baselines-calibration excluded-replicons label-schemes validity learn-adequacy "
                            "learn-truthqc learn-plsmd assembly-quality cohort-qc isolate-difficulty quast-diagnostics "
                            "rank-robustness truth-label-audit orthogonal-evidence metadata-completeness health outcome-states "
                            "reproducibility performance power composite",
    "Recommendation": "recommendations recommender-eval taxon-transfer validation",
    "Methods and limits": "metric-framework headline-design interpretation-limits prereg scoring-additions keys method scoring-spec",
    "Appendix": "data-inventory files extended",
}
GROUP_OF = {sid: group for group, ids in _G.items() for sid in ids.split()}
NAV_LABELS = {"per-plasmid-detail": "Per-plasmid detail", "assembly-quality": "Assembly quality"}


def nav_group(sid):
    return GROUP_OF.get(sid, "More")


def grouped_nav(ids, labels):
    """Return {group: [(id, label)]} in document order within each group, only for groups that have sections."""
    groups = {}
    for sid in ids:
        groups.setdefault(nav_group(sid), []).append((sid, labels.get(sid) or NAV_LABELS.get(sid) or sid.replace("-", " ").capitalize()))
    ordered = [g for g in NAV_GROUP_ORDER if g in groups] + [g for g in groups if g not in NAV_GROUP_ORDER]
    return {g: groups[g] for g in ordered}


def nav_html(groups):
    parts = []
    for name, links in groups.items():
        items = "".join(f"<a href='#{rc.esc(sid)}'>{label}</a>" for sid, label in links)
        parts.append(f"<details data-navgroup='{rc.esc(name)}'><summary>{rc.esc(name)} <span class='muted'>({len(links)})</span></summary>"
                     f"<div class='rpt-navlist'>{items}</div></details>")
    return "<nav class='nav' data-grouped aria-label='Report sections'><div class='rpt-navgroups'>" + "".join(parts) + "</div></nav>"


def group_navigation(page):
    """Replace the flat nav by grouped collapsible groups built from the section ids in document order."""
    start = page.find("<nav class='nav'")
    if start < 0:
        return page
    end = page.find("</nav>", start)
    if end < 0:
        return page
    old = page[start:end]
    labels = dict(re.findall(r"href='#([a-z-]+)'>([^<]*)<", old))
    ids, seen = [], set()
    for sid in section_ids(page):
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    for sid in ids:                       # a section whose nav link is missing takes its heading
        if sid not in labels and sid not in NAV_LABELS:
            m = re.search(rf"<section id='{sid}'[^>]*><h2>(.*?)</h2>", page)
            if m:
                labels[sid] = m.group(1)
    page = page[:start] + nav_html(grouped_nav(ids, labels)) + page[end + len("</nav>"):]
    return page.replace("</nav>", "</nav>" + asset("nav_groups_script.html"), 1) if "nav_groups_script" not in page else page


# ------------------------------------------------------------------------------------------------ entry points
def inject(page, results_dir, data_dir=None, scores_path=None):
    """Add every wired section and block to the page (call before report_surfaces.inject so the inventory sees them)."""
    results_dir = str(results_dir)
    page = add_style(page)
    new = str(per_plasmid_section(results_dir, data_dir)) + str(assembly_quality_section(results_dir, data_dir))
    if "<section id='per-plasmid-detail'" not in page:
        page = rc.inject_sections(page, new, [])
    page = attach(page, "cohort-qc", clonal_groups_html(results_dir), "Clonal groups", "Groups of near-identical isolates.", "clonal-groups")
    page = attach(page, "recommender-eval", regret_html(results_dir), "Recommender regret", "Regret per isolate.", "recommender-regret")
    page = attach(page, "learn-truthqc", depth_strip_html(results_dir, data_dir), "Truth read depth", "Depth along the truth.", "truth-depth")
    scores = scores_path or os.path.join(results_dir, "scores.tsv")
    page = attach(page, "scores", score_columns_html(scores), "All score columns", "Every column of scores.tsv.", "score-columns")
    page = attach(page, "leaderboard", leaderboard_columns_html(results_dir), "More leaderboard columns", "The full leaderboard.", "leaderboard-columns")
    page = attach(page, "files", files_html(results_dir), "Run files", "Links to the Markdown outputs.", "run-files")
    return page


def finish(page):
    """After every section exists: move the scorecard and maps up, then group the navigation."""
    page = move_after(page, ["scorecard", "scorecard-definitions", "scorecard-scenarios", "plasmid-maps", "fig-ladder", "fig-landscape", "fig-heatmap", "fig-distributions", "fig-forest", "fig-pr"],
                      ["robustness", "leaderboard"])
    return group_navigation(page)
