#!/usr/bin/env python3
"""HTML sections for the evaluation additions learned from PlasEval, plsMD and GAEMR.

Sections (always present; a missing table says "Not run" and why, never silence):
  learn-agreement   best-match (non-one-to-one) P/R/F1 and the split/join dissimilarity per tool, and the tool-vs-tool
                    dissimilarity matrix
  learn-adequacy    whether each short-read assembly contains the plasmids it is judged against (assembly adequacy)
  learn-copynumber  tool versus truth plasmid copy number per matched bin
  learn-truthqc     repeat content and read-depth anomalies of the truth
  learn-plsmd       what a database-dependent tool such as plsMD can and cannot show (leakage)
  learn-published   PlasBench's results beside the outcomes a publication reported for the same isolates
  learn-drivers     what drives per-plasmid recovery: a multivariable, study-clustered regression per tool

Called once from build_html_report.py: `inject(page, results_dir, scores_path)`. Standard library only.
"""
import csv
import html
import os
from collections import defaultdict

SECTIONS = [("learn-agreement", "Bin agreement"), ("learn-adequacy", "Assembly adequacy"),
            ("learn-copynumber", "Copy number"), ("learn-truthqc", "Truth repeats and depth"),
            ("learn-plsmd", "Database-dependent tools"), ("learn-published", "Published outcomes"), ("learn-drivers", "Performance drivers")]


from plasbench_common import number  # noqa: E402,F401


def esc(value):
    return html.escape(str(value), quote=True)


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")),
                                   delimiter=chr(9)))


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(value, digits=4):
    return "-" if value is None else f"{value:.{digits}f}"


def panel(headers, rows, empty="Nothing to report."):
    if not rows:
        return f"<div class='panel'><p style='padding:12px'>{esc(empty)}</p></div>"
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<div class='panel'><table class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def note(message):
    return f"<div class='insight caution'><p>{esc(message)}</p></div>"


def section(sid, title, lead, body):
    return f"<section id='{sid}'><h2>{esc(title)}</h2><p class='lead'>{lead}</p>{body}</section>"


def per_tool(scores):
    groups = defaultdict(list)
    for row in scores or []:
        groups[(row.get("analysis_track") or "short_read", row["tool"])].append(row)
    return dict(sorted(groups.items()))


def gate_card(gate):
    """The comparison-gate verdict: PlasBench against the original PlasEval program on this run's bins."""
    summary, rows = (gate or (None, None))
    if not summary:
        return note("PlasEval comparison gate: no verdict was written (RUN_PLASEVAL_GATE=off, an older stage 6, or the run stopped "
                    "before it).")
    status = summary.get("status", "")
    counts = summary.get("counts") or {}
    detail = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in sorted(counts.items())) or "no pairs"
    worst = summary.get("max_abs_difference")
    head = (f"PlasEval comparison gate: <strong>{esc(status)}</strong>. Tolerance {esc(summary.get('tolerance'))}; "
            f"{esc(summary.get('pairs'))} isolate-tool pair(s) ({esc(detail)})"
            + (f"; largest dissimilarity difference {worst:.6f}" if worst is not None else "")
            + (f"; original program at commit {esc(summary['original_commit'])}" if summary.get("original_commit") else "") + ".")
    if status == "PASS":
        text = head + (" PlasBench's reimplementation and the original program agree on the dissimilarity and the best-match "
                       "scores of every compared pair, on this run's real bins.")
    elif status == "FAIL":
        bad = [r for r in (rows or []) if r.get("status") == "disagree"]
        text = head + (" At least one pair disagrees: treat PlasBench's dissimilarity as unverified for this run and report it. "
                       "Disagreeing pairs: " + "; ".join(f"{esc(r['sample'])} / {esc(r['tool'])} ({esc(r['plasbench_dissimilarity'])} "
                                                         f"vs {esc(r['original_dissimilarity'])})" for r in bad[:10]) + ".")
    elif status == "PARTIAL":
        text = head + " Pairs that could be compared agree; the others timed out or failed in the original program."
    elif status == "NOT_RUN":
        text = head + " Not run: " + esc(summary.get("reason") or "the original program was not available") + "."
    else:
        text = head
    cls = "insight" if status == "PASS" else "insight caution"
    return f"<div class='{cls}'><p>{text}</p></div>"


def agreement_section(scores, matrix, gate=None):
    have = [r for r in (scores or []) if r.get("bestmatch_status") or r.get("dissim_status")]
    if not have:
        return section("learn-agreement", "Bin agreement (PlasEval-style)",
                       "Best-match scores and split/join dissimilarity on the assembly contigs.",
                       note("Not run: scores.tsv has no bin-agreement columns (RUN_BIN_AGREEMENT=0, no contig labels, or an "
                            "older stage 5)."))
    rows = []
    for (track, tool), group in per_tool(have).items():
        ok = [r for r in group if r.get("bestmatch_status") == "ok"]
        reasons = sorted({r.get("bestmatch_status") for r in group if r.get("bestmatch_status") not in ("ok", "", None)})
        rows.append([track, tool, len(ok), fmt(mean([number(r.get("f1")) for r in group])),
                     fmt(mean([number(r.get("bestmatch_f1_bp")) for r in ok])),
                     fmt(mean([number(r.get("bestmatch_f1_count")) for r in ok])),
                     fmt(mean([number(r.get("bin_dissimilarity")) for r in group])),
                     fmt(mean([number(r.get("dissim_split_cost")) for r in group])),
                     fmt(mean([number(r.get("dissim_join_cost")) for r in group])),
                     sum(int(number(r.get("bestmatch_contigs_excluded")) or 0) for r in ok),
                     "; ".join(reasons) or "-"])
    body = panel(["Track", "Tool", "Isolates", "Reference-base F1 (primary)", "Best-match F1 (bp)", "Best-match F1 (count)",
                  "Dissimilarity (0 = identical)", "Split cost", "Join cost", "Shared or misjoined contigs excluded",
                  "Not applicable because"], rows)
    body += note("Best match is per bin and not one-to-one, so one truth plasmid can be credited to several predicted bins; the "
                 "primary bin score matches one-to-one. Split cost is a predicted bin that spans several truth plasmids "
                 "(over-merging); join cost is a truth plasmid spread over several predicted bins (over-splitting). Shared "
                 "(AMBIGUOUS) and misjoined (CHIMERIC) contigs are excluded and counted; Repeated contigs are kept in "
                 "several bins and paired as PlasEval pairs them (dissim_repeat_search says whether the search was exact or capped).")
    if matrix:
        mrows = [[r["tool_a"], r["tool_b"], r["n_samples"], r["mean_dissimilarity"] or "-"] for r in matrix]
        body += "<h3>Do tools agree with each other?</h3>" + panel(
            ["Tool A", "Tool B (or truth)", "Samples", "Mean dissimilarity"], mrows)
    else:
        body += note("Tool-vs-tool agreement not run: benchmark.tool_agreement.tsv was not produced.")
    # The error profile: which kind of binning error each tool makes (extra, missing, over-merged, fragmented), drawn from
    # the same columns. Descriptive only; it never changes a ranking.
    import report_fig_binerrors
    body += gate_card(gate)
    body += "<h3>Error profile: what kind of error does each tool make?</h3>" + report_fig_binerrors.section_html(scores, matrix)
    return section("learn-agreement", "Bin agreement (PlasEval-style)",
                   "Reimplemented from PlasEval's published definitions: best-match precision, recall and F1, and a "
                   "length-weighted dissimilarity separating splits from joins. It cross-checks the one-to-one bin score and "
                   "shows whether tools agree with each other, not only with the truth. <strong>It never changes the ranking."
                   "</strong>", body)


def adequacy_section(adequacy):
    if not adequacy:
        return section("learn-adequacy", "Assembly adequacy", "Was the short-read assembly good enough to blame a tool?",
                       note("Not run: benchmark.assembly_adequacy.tsv was not produced (RUN_ASSEMBLY_ADEQUACY=0 or no "
                            "contig labels)."))
    rows = [[r["sample"], r.get("assembly_status", ""), r.get("plasmid_adequacy") or "-", r.get("adequate") or "-",
             r.get("n_contigs") or "-", r.get("assembly_n50") or "-", r.get("n_chimeric") or "0",
             r.get("chimeric_fraction") or "-", r.get("unplaced_fraction") or "-", r.get("reason") or ""] for r in adequacy]
    flagged = sum(r.get("adequate") == "no" for r in adequacy)
    body = panel(["Sample", "Status", "Plasmid adequacy", "Adequate", "Contigs", "N50", "Chimeric contigs",
                  "Chimeric fraction (bp)", "Unplaced fraction (bp)", "Reason"], rows)
    if flagged:
        body += note(f"{flagged} assembl{'y' if flagged == 1 else 'ies'} contain less of the truth plasmids than "
                     "MIN_ASSEMBLY_ADEQUACY. A tool cannot recover sequence the assembly never produced; the recall ceiling and "
                     "the assembly-aware binning recall already account for this, and EXCLUDE_INADEQUATE_ASSEMBLY is not "
                     "applied by default.")
    return section("learn-adequacy", "Assembly adequacy",
                   "Share of each truth plasmid that the isolate's own short-read assembly contains (a dataset gate in plsMD's "
                   "validation), with the share of contig bases that are chimeric (a plasmid and a chromosome joined) or "
                   "unplaced, and the assembly's N50.", body)


def copynumber_section(copy_number):
    if not copy_number:
        return section("learn-copynumber", "Plasmid copy number", "Tool versus truth copy number per matched plasmid.",
                       note("Not run: benchmark.copy_number.tsv was not produced. It needs SPAdes or Unicycler depth headers, "
                            "matched bins, and a per-replicon truth depth table (truth_long_read_depth.tsv, written when long "
                            "reads are staged)."))
    ok = [r for r in copy_number if r.get("status") == "ok"]
    reasons = defaultdict(int)
    for r in copy_number:
        if r.get("status") != "ok":
            reasons[r.get("status", "")] += 1
    groups = defaultdict(list)
    for r in ok:
        groups[(r.get("analysis_track") or "short_read", r["tool"])].append(r)
    rows = []
    for (track, tool), group in sorted(groups.items()):
        logs = [number(r.get("log2_ratio")) for r in group]
        logs = [v for v in logs if v is not None]
        within = sum(abs(v) <= 0.585 for v in logs) / len(logs) if logs else None   # factor 1.5 = log2 0.585
        rows.append([track, tool, len(group), fmt(mean([abs(v) for v in logs]), 3), fmt(within, 3)])
    body = panel(["Track", "Tool", "Matched plasmids", "Mean |log2(predicted / truth)|", "Fraction within a factor of 1.5"], rows,
                 "No plasmid had both a tool copy number and a truth copy number.")
    if reasons:
        body += note("Not scored: " + "; ".join(f"{k or 'unspecified'} ({v})" for k, v in sorted(reasons.items())) + ".")
    return section("learn-copynumber", "Plasmid copy number (descriptive)",
                   "Copy number matters for resistance-gene dosage. Tool copy number is the length-weighted bin depth over the "
                   "chromosomal depth estimate from the assembly headers; truth copy number is the plasmid to chromosome "
                   "long-read depth ratio. <strong>Descriptive only: it never ranks tools.</strong>", body)


def truthqc_section(repeats, anomalies):
    body = ""
    if repeats is None:
        body += note("Repeat content not run: benchmark.repeat_content.tsv was not produced (RUN_REPEAT_CONTENT=0).")
    else:
        plasmids = [r for r in repeats if r.get("molecule_type") == "PLASMID"]
        rich = sum(r.get("repeat_rich") == "yes" for r in plasmids)
        rows = [[r["sample"], r["sequence_id"], r.get("length", ""), r.get("internal_repeat_fraction") or "-",
                 r.get("chromosome_shared_fraction") or "-", r.get("shared_with_other_plasmids_fraction") or "-",
                 r.get("repeat_rich") or "-"] for r in plasmids]
        body += f"<p class='muted'>{rich} of {len(plasmids)} truth plasmids are repeat-rich.</p>" + panel(
            ["Sample", "Plasmid", "Length", "Internal repeat fraction", "Shared with chromosome", "Shared with other plasmids",
             "Repeat-rich"], rows, "No truth plasmid had a computed repeat content.")
    if anomalies is None:
        body += note("Depth anomalies not run: RUN_TRUTH_DEPTH_ANOMALIES is off by default (it maps the benchmark reads to the "
                     "truth and needs minimap2 and samtools).")
    else:
        rows = [[r.get("sample", ""), r.get("sequence_id", ""), r.get("molecule_type", ""), r.get("n_high_regions", ""),
                 r.get("n_low_regions", ""), r.get("anomalous_fraction", ""), r.get("status", "")] for r in anomalies]
        body += "<h3>Read-depth anomalies on the truth</h3>" + panel(
            ["Sample", "Replicon", "Type", "High-depth regions", "Low-depth regions", "Anomalous fraction", "Status"], rows)
    return section("learn-truthqc", "Truth quality: repeats and depth anomalies",
                   "Repeat content (k-mer based, from GAEMR's repeat statistics) explains why contigs are shared and plasmids are "
                   "hard to separate. Windows of read depth far from a replicon's median flag collapsed repeats, misjoins or "
                   "integrated elements in the truth. <strong>Advisory: neither edits the truth or a score.</strong>", body)


def plsmd_section(scores):
    tools = sorted({r["tool"] for r in (scores or []) if r["tool"] == "plsmd"})
    if not tools:
        body = note("plsMD was not run in this benchmark (RUN_PLSMD=0, or it was skipped: it needs the plsMD command, a PLSDB "
                    "BLAST index in PLSMD_DB and a Unicycler assembly).")
    else:
        rows = [[track, tool, len(group), fmt(mean([number(r.get("f1")) for r in group])),
                 fmt(mean([number(r.get("lw_bin_f1")) for r in group]))]
                for (track, tool), group in per_tool([r for r in scores if r["tool"] == "plsmd"]).items()]
        body = panel(["Track", "Tool", "Isolates", "Mean F1", "Mean length-weighted bin F1"], rows)
    body += note("plsMD reconstructs against PLSDB, which very probably contains the complete genomes used as truth. Read its "
                 "score together with the database-overlap table and the in-database versus out-of-database recovery "
                 "(database_containment); a high score on plasmids already in PLSDB shows retrieval, not reconstruction of "
                 "something new. Enter the PLSDB release in config/tool_database_releases.tsv, or leakage is reported as "
                 "not assessed.")
    return section("learn-plsmd", "Database-dependent tools (plsMD)",
                   "plsMD is wrapped as an optional benchmarked tool. Its reference-guided design is exactly where database "
                   "membership matters most.", body)


def published_section(report, summary_rows):
    """PlasBench against the publication's own outcomes (python/compare_published.py). Descriptive; never ranks."""
    lead = ("When the cohort holds isolates of a published benchmark, this puts PlasBench's result beside the paper's for the same isolates "
            "and tools. <strong>A comparison for your own judgement: not a gate and not a ranking.</strong>")
    if not report:
        return section("learn-published", "Comparison with published outcomes", lead,
                       note("Not run: no comparison with a publication was written (benchmark.published_comparison.json). It is written when "
                            "the cohort holds isolates of a published benchmark (pub-*.tsv or publication-v1.tsv) and RUN_PUBLISHED_COMPARISON "
                            "is not off; or run: plasbench compare-published --results-dir <results> --samples <cohort.tsv>."))
    import compare_published as cp
    for study in report.get("studies", []):
        study["summary"] = []
        for row in summary_rows or []:
            if row.get("study") == study["study"]:
                study["summary"].append({k: (cp.fnum(v) if k in ("published_mean", "plasbench_mean", "mean_difference", "mean_abs_difference", "correlation", "share_within_tolerance", "tolerance") else v)
                                         for k, v in row.items()})
                for key in ("n_pairs", "n_published_only"):
                    study["summary"][-1][key] = int(float(row.get(key) or 0))
    return section("learn-published", "Comparison with published outcomes", lead, cp.html_body(report))


def drivers_section(summary, rows):
    """Per tool: the drivers of per-plasmid recovery from one multivariable model (python/performance_drivers.py). Descriptive; never ranks."""
    lead = ("Which plasmid and isolate characteristics go with worse recovery, <strong>holding the others fixed</strong>: size, repeats, replicon family, "
            "resistance genes, species, read depth and recent versus older data, in one model per tool with intervals that treat each study as one unit. "
            "<strong>Associations, not causes; descriptive, it never changes a score or ranking.</strong>")
    if not summary:
        return section("learn-drivers", "Performance drivers", lead,
                       note("Not run: benchmark.performance_drivers.json was not produced (RUN_PERFORMANCE_DRIVERS=0, or an older stage 6)."))
    body = ""
    tools = summary.get("tools", [])
    estimated = [t for t in tools if t.get("status") == "estimated"]
    if not estimated:
        body += note("No tool had enough scored plasmids and studies for a model: " + "; ".join(f"{t['tool']}: {t.get('reason', '')}" for t in tools[:6]) + ".")
    by_tool = defaultdict(list)
    for r in rows or []:
        by_tool[(r.get("analysis_track"), r.get("tool"))].append(r)
    for t in tools:
        key = (t.get("analysis_track"), t.get("tool"))
        head = f"<h3>{esc(t['tool'])} <span class='muted'>({esc(t.get('analysis_track', ''))})</span></h3>"
        if t.get("status") != "estimated":
            body += head + f"<p class='muted'>Not estimable: {esc(t.get('reason', ''))}.</p>"
            continue
        size = t.get("size_effect")
        said = ""
        if size and size.get("ci_low") is not None:
            direction = "lower" if size["estimate"] < 0 else "higher"
            said = (f" Larger plasmids go with {direction} recovery by {abs(size['estimate']):.3f} per standard deviation of log size "
                    f"(95% interval {size['ci_low']:.3f} to {size['ci_high']:.3f}; {esc(size['status'])}).")
        body += head + (f"<p class='muted'>{t['n_plasmids']} plasmids from {t['n_clusters']} studies, R&sup2; {t['r2']:.2f}.{said}</p>" if t.get("r2") is not None
                        else f"<p class='muted'>{t['n_plasmids']} plasmids from {t['n_clusters']} studies.{said}</p>")
        trs = []
        for r in sorted(by_tool.get(key, []), key=lambda r: -abs(float(r["estimate"] or 0))):
            ref = f" (vs {r['reference']})" if r.get("reference") else ""
            trs.append([r["term"] + ref, fmt(number_or_none(r["estimate"]), 3),
                        f"{fmt(number_or_none(r['ci_low']), 3)} to {fmt(number_or_none(r['ci_high']), 3)}", r["status"], fmt(number_or_none(r["delta_r2_without"]), 3)])
        body += panel(["Driver", "Effect on recovery", "95% interval", "Status", "Variance explained by this driver"], trs)
        extra = [x["driver"] + ": " + x["reason"] for x in t.get("left_out", [])]
        if extra:
            body += f"<p class='muted'>Left out: {esc('; '.join(extra))}.</p>"
        for w in t.get("warnings", []):
            body += note(w)
    body += note("Effects are per one standard deviation for numeric drivers and a difference from the stated reference for categories. 'Supported' means the estimate "
                 "lies outside an interval widened for the number of terms in the model and its sign was stable across study resamples; 'unclear' is not 'no effect'.")
    return section("learn-drivers", "Performance drivers", lead, body)


def number_or_none(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def inject(page, results_dir, scores_path):
    scores = read_tsv(scores_path) or []
    r = lambda name: read_tsv(os.path.join(results_dir, "benchmark." + name + ".tsv"))  # noqa: E731
    gate_json = os.path.join(results_dir, "benchmark.plaseval_gate.json")
    gate = None
    if os.path.isfile(gate_json):
        import json
        with open(gate_json, encoding="utf-8") as handle:
            gate = (json.load(handle), r("plaseval_gate") or [])
    published_json = os.path.join(results_dir, "benchmark.published_comparison.json")
    published = None
    if os.path.isfile(published_json):
        import json
        with open(published_json, encoding="utf-8") as handle:
            published = json.load(handle)
        if published.get("status") == "NO_DATA":
            published = None
    drivers_json = os.path.join(results_dir, "benchmark.performance_drivers.json")
    drivers = None
    if os.path.isfile(drivers_json):
        import json
        with open(drivers_json, encoding="utf-8") as handle:
            drivers = json.load(handle)
    sections = (agreement_section(scores, r("tool_agreement"), gate) + adequacy_section(r("assembly_adequacy"))
                + copynumber_section(r("copy_number")) + truthqc_section(r("repeat_content"), r("truth_depth_anomalies"))
                + plsmd_section(scores)
                + published_section(published, r("published_comparison"))
                + drivers_section(drivers, r("performance_drivers")))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, sections + anchor, 1)
        nav_anchor = "<a href='#recommendations'>Recommendations</a>"
        links = "".join(f"<a href='#{sid}'>{esc(label)}</a>" for sid, label in SECTIONS)
        page = page.replace(nav_anchor, links + nav_anchor, 1)
    return page
