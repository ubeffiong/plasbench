#!/usr/bin/env python3
"""
report_workflow.py -- the "Workflow" section: a static, data-driven methods figure of the pipeline and a summary table.

The figure has three panels (a inputs and truth, b assembly and tools, c scoring, statistics and the recommendation).
Every box carries what actually ran in THIS results directory: the number of samples, tool runs by status
(completed / reused / failed / skipped / infrastructure_failure, from tool_status.tsv) and, for each scoring layer and
analysis table, whether it exists:

  ran     filled box, solid outline, with a row count
  not run dashed outline, white fill, the words "Not run"

so the figure still reads in greyscale (fill, outline style and words, never colour alone). One colour per stage family.
The table under the figure lists each stage, its status and a link to the report section that shows its results; links
are written only for ids in `known_section_ids`, so there is never a dead link.

  build_model(results_dir, scores_path=None, status_path=None, data_dir=None)  -> model dict (no files = every layer not run)
  render_svg(model)                      the figure (well-formed XML, scales through its viewBox)
  render_workflow(model, known_section_ids=())   the whole section (id `workflow`)
  inject(page, results_dir, scores_path, status_path=None, data_dir=None)    called once from build_html_report.py

Standard library only.
"""
import os
import re

import report_common as rc
import report_svg as sv

SECTION_ID = "workflow"
NAV = [(SECTION_ID, "Workflow")]
STATUSES = ("completed", "reused", "failed", "skipped", "infrastructure_failure")

# family -> (fill, stroke, name). Fill is light so dark text always reads; stroke is the saturated colour.
FAMILIES = {
    "inputs": ("#dbe9f7", "#1f5a99", "Inputs"),
    "truth": ("#d5eee8", "#0f7a68", "Truth construction"),
    "tools": ("#fbe5c8", "#a35c05", "Assembly and tools"),
    "scoring": ("#e6dcf3", "#6a3fa0", "Scoring layers"),
    "stats": ("#dcefd0", "#3b7d1e", "Statistics"),
    "output": ("#ececec", "#444444", "Recommendation and report"),
}
INK = "#1a1a1a"

TOOL_CLASSES = [
    ("binning", "Binning", ("mob_recon", "gplas2", "flye_mob", "trycycler")),
    ("reassembly", "Reassembly", ("plasmidspades", "plassembler", "hybracter")),
    ("classifier", "Classifiers", ("platon", "genomad", "plasme", "rfplasmid", "plasmidhunter", "plasmer", "plasgraph", "plascope")),
    ("baseline", "Trivial baselines", ("baseline_",)),
    ("adapter", "Optional adapters (plsMD, PlasBin-flow)", ("plsmd", "plasbin")),
]

# stage id -> candidate section ids in the report, first one that is known wins
STAGE_SECTIONS = {
    "inputs": ["samples", "cohort-qc", "metadata"],
    "truth": ["truth-label-audit", "label-schemes", "learn-truthqc", "excluded-replicons"],
    "assembly": ["learn-adequacy", "quast-diagnostics"],
    "tools": ["tools", "leaderboard"],
    "layer_reference": ["leaderboard", "scores"],
    "layer_contig": ["contig-layer"],
    "layer_bin": ["bin-diagnostics", "learn-agreement"],
    "layer_amr": ["amr-placement"],
    "layer_copy": ["learn-copynumber"],
    "layer_adequacy": ["learn-adequacy"],
    "stats_paired": ["statistics", "headline-design"],
    "stats_robust": ["rank-robustness", "robustness"],
    "stats_leakage": ["database-membership", "learn-plsmd"],
    "recommendation": ["recommendations"],
}
SECTION_TITLES = {
    "samples": "Samples", "cohort-qc": "Cohort quality", "metadata": "Metadata", "truth-label-audit": "Truth label audit",
    "label-schemes": "Labelling schemes", "learn-truthqc": "Truth repeats and depth", "excluded-replicons": "Excluded replicons",
    "learn-adequacy": "Assembly adequacy", "quast-diagnostics": "QUAST diagnostics", "tools": "Tools", "leaderboard": "Leaderboard",
    "scores": "Scores", "contig-layer": "Contig layer", "bin-diagnostics": "Bin diagnostics", "learn-agreement": "Bin agreement",
    "amr-placement": "AMR placement", "learn-copynumber": "Copy number", "statistics": "Statistics",
    "headline-design": "Headline design", "rank-robustness": "Rank robustness", "robustness": "Robustness",
    "database-membership": "Database membership", "learn-plsmd": "Database-dependent tools",
    "recommendations": "Recommendations",
}


# ---------------------------------------------------------------------------------------------------------------- model
def _rows(directory, name):
    return rc.read_tsv(os.path.join(directory, name)) if directory else None


def _count_files(directory, filename):
    """Number of immediate subdirectories of `directory` that hold `filename`."""
    if not directory or not os.path.isdir(directory):
        return 0
    return sum(os.path.isfile(os.path.join(directory, d, filename)) for d in os.listdir(directory)
               if os.path.isdir(os.path.join(directory, d)))


def classify_tool(tool):
    name = (tool or "").lower()
    for key, _, prefixes in TOOL_CLASSES:
        if any(name.startswith(p) or (p in ("mob_recon",) and p in name) for p in prefixes):
            return key
    return "other"


def _layer(rows_or_none, present_note=""):
    if rows_or_none is None:
        return {"present": False, "rows": None}
    return {"present": True, "rows": len(rows_or_none)}


def build_model(results_dir, scores_path=None, status_path=None, data_dir=None):
    """Everything the figure shows, read from the files that exist. A missing directory is a valid, all-'Not run' model."""
    results_dir = results_dir if results_dir and os.path.isdir(results_dir) else None
    data_dir = data_dir if data_dir and os.path.isdir(data_dir) else results_dir
    scores = rc.read_tsv(scores_path) if scores_path else None
    if scores is None and results_dir:
        scores = _rows(results_dir, "scores.tsv")
    status = rc.read_tsv(status_path) if status_path else None
    if status is None and results_dir:
        status = _rows(results_dir, "tool_status.tsv")
    bench = lambda name: _rows(results_dir, "benchmark." + name + ".tsv")  # noqa: E731

    samples_tsv = _rows(results_dir, "samples.tsv") or _rows(data_dir, "samples.tsv")
    if samples_tsv is not None:
        n_samples = len(samples_tsv)
    elif scores:
        n_samples = len({r.get("sample") for r in scores if r.get("sample")})
    elif results_dir:
        n_samples = _count_files(results_dir, "truth.tsv") or None
    else:
        n_samples = None

    counts = {s: 0 for s in STATUSES}
    other = 0
    tools_seen = set()
    by_class = {}
    for r in status or []:
        s = (r.get("status") or "").strip()
        if s in counts:
            counts[s] += 1
        else:
            other += 1
        tool = r.get("tool") or ""
        tools_seen.add(tool)
        cls = by_class.setdefault(classify_tool(tool), {"tools": set(), "runs": 0})
        cls["tools"].add(tool)
        cls["runs"] += 1
    has_status = status is not None
    scores = scores or []
    nonblank = lambda col: sum(1 for r in scores if (r.get(col) or "").strip() != "")  # noqa: E731

    layers = {
        "layer_reference": {"present": bool(scores), "rows": len(scores)},
        "layer_contig": {"present": nonblank("contig_classification_status") > 0, "rows": nonblank("contig_classification_status"),
                         "crosscheck": bench("contig_crosscheck") is not None},
        "layer_bin": {"present": nonblank("bin_f1") > 0, "rows": nonblank("bin_f1"),
                      "bestmatch": nonblank("bestmatch_status") > 0},
        "layer_amr": _layer(bench("amr_placement")),
        "layer_copy": _layer(bench("copy_number")),
        "layer_adequacy": _layer(bench("assembly_adequacy")),
    }
    stats = {
        "stats_paired": _layer(bench("paired_comparisons")),
        "stats_robust": _layer(bench("rank_robustness")),
    }
    overlap, contain = bench("database_overlap"), bench("database_containment")
    stats["stats_leakage"] = {"present": overlap is not None or contain is not None,
                              "rows": (len(overlap or []) + len(contain or [])) if (overlap is not None or contain is not None) else None}
    truth = {
        "evidence": {"present": _count_files(data_dir, "truth_labels.tsv") > 0, "rows": _count_files(data_dir, "truth_labels.tsv"), "unit": "samples"},
        "tiers": dict(_layer(bench("reference_tiers")), unit="rows"),
        "schemes": {"present": _count_files(data_dir, "label_schemes.tsv") > 0, "rows": _count_files(data_dir, "label_schemes.tsv"), "unit": "samples"},
        "dimer": {"present": _count_files(data_dir, "truth.corrections.tsv") > 0, "rows": _count_files(data_dir, "truth.corrections.tsv"),
                  "unit": "samples corrected"},
        "repeat": dict(_layer(bench("repeat_content")), unit="rows"),
        "depth": dict(_layer(bench("truth_depth_anomalies")), unit="rows"),
    }
    n_truth = _count_files(data_dir, "truth.tsv")
    n_asm = _count_files(data_dir, "contigs.fasta") or _count_files(results_dir, "contigs.fasta")
    recs = bench("recommendations")
    return {
        "has_results": results_dir is not None,
        "n_samples": n_samples, "n_truth": n_truth, "n_assembled": n_asm,
        "tool_counts": counts, "tool_other": other, "has_status": has_status,
        "n_tools": len(tools_seen), "n_runs": sum(counts.values()) + other,
        "by_class": {k: {"tools": len(v["tools"]), "runs": v["runs"]} for k, v in by_class.items()},
        "layers": layers, "stats": stats, "truth": truth,
        "recommendation": {"present": recs is not None, "rows": len(recs) if recs is not None else None},
    }


# ---------------------------------------------------------------------------------------------------------------- SVG
def _wrap(content, width_px, size):
    """Greedy word wrap using a conservative average glyph width of 0.56 em (bold text is given a smaller width_px)."""
    per_line = max(6, int(width_px / (size * 0.56)))
    lines, current = [], ""
    for word in str(content).split():
        trial = (current + " " + word).strip()
        if len(trial) <= per_line or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _box(x, y, w, h, family, title, lines=(), filled=True, title_size=12.5, size=11.5, extra_title=""):
    fill, stroke, _ = FAMILIES[family]
    attrs = (f"fill='{fill}' stroke='{stroke}' stroke-width='2'" if filled
             else f"fill='#ffffff' stroke='{stroke}' stroke-width='2' stroke-dasharray='6 4'")
    out = [f"<rect x='{sv.num(x)}' y='{sv.num(y)}' width='{sv.num(w)}' height='{sv.num(h)}' rx='10' ry='10' {attrs}"
           f" class='wf-box {'wf-ran' if filled else 'wf-notrun'}'/>"]
    cy = y + 8 + title_size
    for ln in _wrap(title, w - 16, title_size * 1.08):
        out.append(sv.text(x + w / 2, cy, ln, size=title_size, anchor="middle", weight="bold", fill=INK))
        cy += title_size + 2
    for text_line in lines:
        for ln in _wrap(text_line, w - 14, size):
            out.append(sv.text(x + w / 2, cy + 2, ln, size=size, anchor="middle", fill=INK))
            cy += size + 2.5
    return "".join(out)


def _frame(x, y, w, h, family, label):
    _, stroke, _ = FAMILIES[family]
    return (f"<rect x='{sv.num(x)}' y='{sv.num(y)}' width='{sv.num(w)}' height='{sv.num(h)}' rx='14' ry='14' fill='none' "
            f"stroke='{stroke}' stroke-width='1' class='wf-frame'/>" + sv.text(x + 12, y + 17, label, size=12, weight="bold", fill=stroke))


def _arrow(x1, y1, x2, y2):
    return (f"<line x1='{sv.num(x1)}' y1='{sv.num(y1)}' x2='{sv.num(x2)}' y2='{sv.num(y2)}' stroke='#333' stroke-width='2' "
            f"marker-end='url(#wf-arrow)'/>")


def _count(item, unit="rows"):
    return f"{item['rows']:,} {unit}" if item.get("present") else "Not run"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def render_svg(model):
    W, H = 1000, 700
    parts = [sv.svg_open(W, H, "PlasBench workflow: inputs, truth, tools, scoring, statistics and recommendation",
                         "A three-panel schematic of the pipeline. Boxes drawn solid and filled ran in this run; boxes drawn "
                         "dashed with the words Not run did not.", css_class="wf-figure"),
             "<defs><marker id='wf-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto'>"
             "<path d='M0,0 L10,5 L0,10 z' fill='#333'/></marker></defs>",
             f"<rect x='0' y='0' width='{W}' height='{H}' fill='#ffffff'/>"]
    n = model["n_samples"]
    n_txt = "no samples found" if not n else _plural(n, "sample")

    # panel a ---------------------------------------------------------------------------------------------------
    parts.append(sv.text(12, 22, "a", size=18, weight="bold", fill=INK) + sv.text(32, 22, "Inputs and truth", size=13, fill=INK))
    parts.append(_box(20, 40, 215, 112, "inputs", "Isolate short reads", [n_txt, "paired Illumina reads of one isolate"], filled=bool(n)))
    parts.append(_box(255, 40, 215, 112, "inputs", "Complete reference genome",
                      ["long-read or hybrid assembly, chromosome plus plasmids", f"truth table for {model['n_truth']} of {n or 0}"
                       if n else "no truth table found"], filled=bool(model["n_truth"])))
    parts.append(_frame(500, 32, 480, 150, "truth", "Truth construction"))
    t = model["truth"]
    chips = [("Evidence labels", t["evidence"]), ("Reference tiers", t["tiers"]), ("Labelling schemes", t["schemes"]),
             ("Dimer check", t["dimer"]), ("Repeat content", t["repeat"]), ("Depth anomalies", t["depth"])]
    for i, (label, item) in enumerate(chips):
        cx, cy = 512 + (i % 3) * 156, 52 + (i // 3) * 60
        if item["present"]:
            parts.append(_box(cx, cy, 148, 52, "truth", label, [f"{item['rows']:,} {item.get('unit', 'rows')}"], title_size=12, size=11))
        else:
            word = "none recorded" if label == "Dimer check" else "Not run"
            parts.append(_box(cx, cy, 148, 52, "truth", label, [word], filled=False, title_size=12, size=11))
    parts.append(_arrow(470, 96, 498, 96))
    parts.append(_arrow(127, 152, 127, 232))

    # panel b ---------------------------------------------------------------------------------------------------
    parts.append(sv.text(12, 212, "b", size=18, weight="bold", fill=INK) + sv.text(32, 212, "Short-read assembly and tools", size=13, fill=INK))
    parts.append(_box(20, 236, 215, 118, "tools", "Short-read assembly", ["trim, assemble, standardise",
                                                                        f"{model['n_assembled']} of {n or 0} assembled" if n else "no assemblies found"],
                      filled=bool(model["n_assembled"])))
    parts.append(_frame(255, 226, 725, 150, "tools", "Tools, grouped by class"))
    tc = model["tool_counts"]
    if model["has_status"]:
        status_line = (f"{model['n_tools']} tools, {model['n_runs']} runs: " + ", ".join(f"{k.replace('_', ' ')} {tc[k]}" for k in STATUSES)
                       + (f", other {model['tool_other']}" if model["tool_other"] else ""))
    else:
        status_line = "tool_status.tsv not found: Not run"
    parts.append(sv.text(480, 241, status_line, size=11, fill=INK))
    classes = [(k, label) for k, label, _ in TOOL_CLASSES]
    if "other" in model["by_class"]:
        classes.append(("other", "Other or custom"))
    bw = (725 - 24 - 8 * (len(classes) - 1)) / len(classes)
    for i, (key, label) in enumerate(classes):
        info = model["by_class"].get(key)
        bx = 267 + i * (bw + 8)
        if info:
            parts.append(_box(bx, 252, bw, 112, "tools", label, [_plural(info["tools"], "tool"), _plural(info["runs"], "run")],
                              title_size=12, size=11))
        else:
            parts.append(_box(bx, 252, bw, 112, "tools", label, ["Not run"], filled=False, title_size=12, size=11))
    parts.append(_arrow(235, 295, 253, 295))
    parts.append(_arrow(617, 376, 617, 404))

    # panel c ---------------------------------------------------------------------------------------------------
    parts.append(sv.text(12, 398, "c", size=18, weight="bold", fill=INK) + sv.text(32, 398, "Scoring, statistics and recommendation", size=13, fill=INK))
    L = model["layers"]
    layer_boxes = [
        ("Reference-base", L["layer_reference"], "scores rows"),
        ("Contig-level with cross-check", L["layer_contig"], "scores rows"),
        ("Bin-level incl. best-match and dissimilarity", L["layer_bin"], "scores rows"),
        ("AMR placement", L["layer_amr"], "rows"),
        ("Copy number", L["layer_copy"], "rows"),
        ("Assembly adequacy", L["layer_adequacy"], "rows"),
    ]
    bw = (960 - 5 * 10) / 6
    for i, (label, item, unit) in enumerate(layer_boxes):
        extra = []
        if label.startswith("Contig") and item["present"]:
            extra = ["cross-check: " + ("yes" if item.get("crosscheck") else "no")]
        if label.startswith("Bin") and item["present"]:
            extra = ["best-match: " + ("yes" if item.get("bestmatch") else "no")]
        bx = 20 + i * (bw + 10)
        if item["present"]:
            parts.append(_box(bx, 406, bw, 118, "scoring", label, [f"{item['rows']:,} {unit}"] + extra, title_size=12, size=11))
        else:
            parts.append(_box(bx, 406, bw, 118, "scoring", label, ["Not run"], filled=False, title_size=12, size=11))
    parts.append(_arrow(500, 526, 500, 552))
    S = model["stats"]
    parts.append(_frame(20, 556, 650, 100, "stats", "Statistics"))
    stat_boxes = [("Cluster bootstrap, sign-flip permutation, Wilcoxon, Holm", S["stats_paired"]), ("Rank robustness", S["stats_robust"]),
                  ("Database leakage screens", S["stats_leakage"])]
    widths = [270, 160, 170]
    sx = 30
    for (label, item), w in zip(stat_boxes, widths):
        if item["present"]:
            parts.append(_box(sx, 576, w, 72, "stats", label, [_count(item)], title_size=11.5, size=11))
        else:
            parts.append(_box(sx, 576, w, 72, "stats", label, ["Not run"], filled=False, title_size=11.5, size=11))
        sx += w + 8
    R = model["recommendation"]
    parts.append(_arrow(670, 606, 700, 606))
    parts.append(_box(702, 566, 278, 80, "output", "Recommendation and report",
                      [f"{R['rows']} recommendation rows" if R["present"] else "recommendation table: Not run", "this HTML report"],
                      filled=True))

    # legend ----------------------------------------------------------------------------------------------------
    ly = 672
    parts.append(f"<rect x='20' y='{ly}' width='26' height='14' rx='4' fill='#dbe9f7' stroke='#1f5a99' stroke-width='2'/>")
    parts.append(sv.text(52, ly + 11, "Ran in this run (filled, solid outline, count shown)", size=11, fill=INK))
    parts.append(f"<rect x='340' y='{ly}' width='26' height='14' rx='4' fill='#ffffff' stroke='#1f5a99' stroke-width='2' stroke-dasharray='6 4'/>")
    parts.append(sv.text(372, ly + 11, "Not run (dashed outline, white)", size=11, fill=INK))
    lx = 590
    for key in ("inputs", "truth", "tools", "scoring", "stats", "output"):
        fill, stroke, name = FAMILIES[key]
        parts.append(f"<rect x='{lx}' y='{ly + 1}' width='10' height='10' fill='{fill}' stroke='{stroke}' stroke-width='1.5'/>")
        short = {"inputs": "Inputs", "truth": "Truth", "tools": "Tools", "scoring": "Scoring", "stats": "Statistics", "output": "Output"}[key]
        parts.append(sv.text(lx + 14, ly + 11, short, size=10, fill=INK))
        lx += 14 + 6.2 * len(short) + 10
    parts.append(sv.svg_close())
    return "".join(parts)


# ---------------------------------------------------------------------------------------------------------------- table
def stage_rows(model):
    """[(stage_id, label, family, state, detail)] with state in ran / not_run / partly."""
    L, S, T = model["layers"], model["stats"], model["truth"]
    n = model["n_samples"] or 0
    tc = model["tool_counts"]
    truth_present = sum(1 for k in ("evidence", "tiers", "schemes", "repeat", "depth") if T[k]["present"])
    truth_state = "ran" if model["n_truth"] and truth_present >= 3 else ("partly" if (model["n_truth"] or truth_present) else "not_run")
    tool_state = "not_run" if not model["n_runs"] else ("partly" if tc["failed"] or tc["infrastructure_failure"] or tc["skipped"] else "ran")
    state = lambda item: "ran" if item["present"] else "not_run"  # noqa: E731
    rows = [
        ("inputs", "Inputs: short reads and reference genome", "inputs", "ran" if n else "not_run", f"{n} samples" if n else "no samples"),
        ("truth", "Truth construction", "truth", truth_state,
         f"truth.tsv in {model['n_truth']} samples; evidence labels {T['evidence']['rows']}, label schemes {T['schemes']['rows']}, "
         f"reference tiers {'yes' if T['tiers']['present'] else 'no'}, repeat content {'yes' if T['repeat']['present'] else 'no'}, "
         f"depth anomalies {'yes' if T['depth']['present'] else 'no'}"),
        ("assembly", "Short-read assembly", "tools", "ran" if model["n_assembled"] else "not_run", f"{model['n_assembled']} of {n} assembled"),
        ("tools", "Tools", "tools", tool_state,
         ", ".join(f"{k.replace('_', ' ')} {tc[k]}" for k in STATUSES) if model["has_status"] else "tool_status.tsv not found"),
        ("layer_reference", "Scoring: reference-base", "scoring", state(L["layer_reference"]), f"{L['layer_reference']['rows']} scores rows"),
        ("layer_contig", "Scoring: contig-level with cross-check", "scoring", state(L["layer_contig"]),
         f"{L['layer_contig']['rows']} scores rows; cross-check table {'yes' if L['layer_contig']['crosscheck'] else 'no'}"),
        ("layer_bin", "Scoring: bin-level, best-match and dissimilarity", "scoring", state(L["layer_bin"]),
         f"{L['layer_bin']['rows']} scores rows; best-match {'yes' if L['layer_bin']['bestmatch'] else 'no'}"),
        ("layer_amr", "Scoring: AMR placement", "scoring", state(L["layer_amr"]), f"{L['layer_amr']['rows']} rows" if L["layer_amr"]["present"] else "table absent"),
        ("layer_copy", "Scoring: copy number", "scoring", state(L["layer_copy"]), f"{L['layer_copy']['rows']} rows" if L["layer_copy"]["present"] else "table absent"),
        ("layer_adequacy", "Scoring: assembly adequacy", "scoring", state(L["layer_adequacy"]),
         f"{L['layer_adequacy']['rows']} rows" if L["layer_adequacy"]["present"] else "table absent"),
        ("stats_paired", "Statistics: cluster bootstrap, permutation, Wilcoxon, Holm", "stats", state(S["stats_paired"]),
         f"{S['stats_paired']['rows']} comparison rows" if S["stats_paired"]["present"] else "table absent"),
        ("stats_robust", "Statistics: rank robustness", "stats", state(S["stats_robust"]),
         f"{S['stats_robust']['rows']} rows" if S["stats_robust"]["present"] else "table absent"),
        ("stats_leakage", "Statistics: database leakage screens", "stats", state(S["stats_leakage"]),
         f"{S['stats_leakage']['rows']} rows" if S["stats_leakage"]["present"] else "tables absent"),
        ("recommendation", "Recommendation and report", "output", state(model["recommendation"]),
         f"{model['recommendation']['rows']} rows" if model["recommendation"]["present"] else "table absent"),
    ]
    return rows


STATE_LABEL = {"ran": "● Ran", "partly": "◐ Partly", "not_run": "○ Not run"}


def render_table(model, known_section_ids=()):
    known = set(known_section_ids or ())
    body = []
    for sid, label, family, state, detail in stage_rows(model):
        target = next((c for c in STAGE_SECTIONS.get(sid, []) if c in known), None)
        link = (rc.Raw(f"<a href='#{rc.esc(target)}'>{rc.esc(SECTION_TITLES.get(target, target))}</a>") if target
                else rc.missing("no section of this report shows it", "none"))
        body.append([label, FAMILIES[family][2], STATE_LABEL[state], detail, link])
    return rc.panel(["Stage", "Family", "Status", "What ran in this run", "Results shown in"], body, sortable=False)


def render_workflow(model, known_section_ids=()):
    lead = ("How the benchmark runs, drawn from this run's own files. Filled boxes with a solid outline ran and show a count; "
            "dashed boxes marked <em>Not run</em> did not, so the figure documents what produced the numbers below.")
    figure = (f"<figure class='rpt-figure'>{render_svg(model)}<figcaption>Figure. Pipeline of this run: a, inputs and truth "
              "construction; b, short-read assembly and tools; c, scoring layers, statistics and the recommendation. Counts are read "
              "from the results directory.</figcaption></figure>")
    return rc.section(SECTION_ID, "Workflow", lead, figure + str(render_table(model, known_section_ids)))


def known_ids_in(page):
    return set(re.findall(r"<section id='([^']+)'", page)) | set(re.findall(r'<section id="([^"]+)"', page))


def inject(page, results_dir, scores_path, status_path=None, data_dir=None, known_section_ids=None):
    """`known_section_ids` (the ids the final page will have) defaults to the section ids already in `page`."""
    model = build_model(results_dir, scores_path, status_path, data_dir)
    html = str(render_workflow(model, known_ids_in(page) if known_section_ids is None else known_section_ids))
    if SECTION_ID in known_ids_in(page):
        return page
    page = rc.add_style(page)
    return rc.inject_sections(page, html, NAV)
