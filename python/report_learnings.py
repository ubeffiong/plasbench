#!/usr/bin/env python3
"""HTML sections for the evaluation additions learned from PlasEval, plsMD and GAEMR.

Sections (always present; a missing table says "Not run" and why, never silence):
  learn-agreement   best-match (non-one-to-one) P/R/F1 and the split/join dissimilarity per tool, and the tool-vs-tool
                    dissimilarity matrix
  learn-adequacy    whether each short-read assembly contains the plasmids it is judged against (assembly adequacy)
  learn-copynumber  tool versus truth plasmid copy number per matched bin
  learn-truthqc     repeat content and read-depth anomalies of the truth
  learn-plsmd       what a database-dependent tool such as plsMD can and cannot show (leakage)

Called once from build_html_report.py: `inject(page, results_dir, scores_path)`. Standard library only.
"""
import csv
import html
import os
from collections import defaultdict

SECTIONS = [("learn-agreement", "Bin agreement"), ("learn-adequacy", "Assembly adequacy"),
            ("learn-copynumber", "Copy number"), ("learn-truthqc", "Truth repeats and depth"),
            ("learn-plsmd", "Database-dependent tools")]


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


def agreement_section(scores, matrix):
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
                 "(AMBIGUOUS) and misjoined (CHIMERIC) contigs are excluded and counted; PlasEval keeps repeated contigs "
                 "in several bins, which this layer does not.")
    if matrix:
        mrows = [[r["tool_a"], r["tool_b"], r["n_samples"], r["mean_dissimilarity"] or "-"] for r in matrix]
        body += "<h3>Do tools agree with each other?</h3>" + panel(
            ["Tool A", "Tool B (or truth)", "Samples", "Mean dissimilarity"], mrows)
    else:
        body += note("Tool-vs-tool agreement not run: benchmark.tool_agreement.tsv was not produced.")
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


def inject(page, results_dir, scores_path):
    scores = read_tsv(scores_path) or []
    r = lambda name: read_tsv(os.path.join(results_dir, "benchmark." + name + ".tsv"))  # noqa: E731
    sections = (agreement_section(scores, r("tool_agreement")) + adequacy_section(r("assembly_adequacy"))
                + copynumber_section(r("copy_number")) + truthqc_section(r("repeat_content"), r("truth_depth_anomalies"))
                + plsmd_section(scores))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, sections + anchor, 1)
        nav_anchor = "<a href='#recommendations'>Recommendations</a>"
        links = "".join(f"<a href='#{sid}'>{esc(label)}</a>" for sid, label in SECTIONS)
        page = page.replace(nav_anchor, links + nav_anchor, 1)
    return page
