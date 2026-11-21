#!/usr/bin/env python3
"""Three dashboards for the report: short-read QC, assembly selection and reconstruction multiplicity.

Each answers one reviewer question and follows a familiar layout so a reader does not have to learn a new one:

  learn-readqc        MultiQC-style General Statistics: one row per sample, inline bars, a PASS / WARN / REJECT chip with its reason,
                      and a cohort summary of how many samples passed, were flagged or were excluded.
  learn-assembly      QUAST-style comparison: one column per candidate assembly, one row per measure, each row coloured from worst to
                      best across the candidates, the selected assembly marked and the eligibility of every candidate shown.
  learn-multiplicity  Alvis-style tracks of every candidate against the reference plasmid, with a coverage strip that separates reference
                      covered once, covered by several candidates (overlap) and not represented; and, per tool, where the predicted
                      sequence went (unique plasmid sequence, redundant, chromosome or unmapped).

All three are descriptive. Colour is never the only channel: statuses are words, candidate classes are also labelled and hatched, and
every mark has a tooltip. A section whose table is missing says it was not run and why, never stays silent. Called from
build_html_report.py: `inject(page, results_dir)`. Standard library only.
"""
import csv
import html
import math
import os

import report_readqc_panel as qp
from report_svg import OKABE_ITO, esc, line, num, svg_close, svg_open, text

SECTIONS = [("learn-readqc", "Short-read QC"), ("learn-assembly", "Assembly selection"), ("learn-multiplicity", "Reconstruction multiplicity"),
            ("learn-stability", "Ranking stability"), ("learn-refaudit", "Reference evidence")]
BLUE, VERM, ORANGE, GREEN, PURPLE, GREY = (OKABE_ITO["blue"], OKABE_ITO["vermillion"], OKABE_ITO["orange"], OKABE_ITO["green"],
                                           OKABE_ITO["purple"], "#8c8c8c")
RELATION_STYLE = {   # relationship -> (fill, label)
    "primary": (BLUE, "primary"), "complementary_fragment": (ORANGE, "complementary fragment"), "redundant": (PURPLE, "redundant"),
    "chimeric": (VERM, "chimeric"), "other_plasmid_part": (OKABE_ITO["sky"], "other plasmid part"),
}
CSS = """<style>
.rv-bar{position:relative;min-width:62px;height:1.55em;background:rgba(128,128,128,.12);border-radius:3px}
.rv-bar span{position:absolute;left:0;top:0;bottom:0;border-radius:3px;background:rgba(0,114,178,.38)}
.rv-bar b{position:relative;font-weight:600;padding:0 6px;font-size:.88em;line-height:1.55em;white-space:nowrap}
.rv-chip{display:inline-block;padding:1px 8px;border-radius:10px;font-weight:700;font-size:.82em;letter-spacing:.02em}
.rv-pass{background:#009E73;color:#fff}.rv-warn{background:#E69F00;color:#111}.rv-reject{background:#D55E00;color:#fff}
.rv table{border-collapse:collapse;font-size:.9em}.rv th,.rv td{border:1px solid rgba(128,128,128,.35);padding:3px 8px;text-align:right}
.rv th:first-child,.rv td:first-child{text-align:left}.rv td.rv-l{text-align:left}
.rv details{margin:8px 0}.rv summary{cursor:pointer;font-weight:600}
.qp-h{background:var(--heat);color:#111;-webkit-print-color-adjust:exact;print-color-adjust:exact}.qp-noheat .qp-h{background:none;color:inherit}
.rv table td.qp-sel,.rv table th.qp-sel{border-left:2px solid #0072B2;border-right:2px solid #0072B2}.qp-heatbox{font-weight:600}
@media print{.qp-noheat .qp-h{background:var(--heat);color:#111}.qp-heatbox{display:none}}
.mx{border:1px solid rgba(128,128,128,.35);border-radius:8px;padding:4px 10px 8px;margin:8px 0}
.mx-head,.mx-row{display:grid;grid-template-columns:minmax(80px,130px) minmax(110px,1.1fr) minmax(120px,1fr) minmax(110px,1.1fr) minmax(130px,200px);gap:4px 12px;align-items:center}
.mx-head{font-size:.78em;opacity:.75;padding:2px 0;border-bottom:1px solid rgba(128,128,128,.35)}
.mx-tool{border-bottom:1px dotted rgba(128,128,128,.4)}
.mx-tool>summary{cursor:pointer;list-style:none;padding:4px 0;min-height:26px}
.mx-tool>summary::-webkit-details-marker{display:none}
.mx-tool>summary:hover{background:rgba(128,128,128,.08)}
.mx-tool>summary:focus-visible,.mx-track>summary:focus-visible,.mx-all>summary:focus-visible{outline:3px solid #0072B2;outline-offset:1px}
.mx-name{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mx-name:before{content:"\\25B8";display:inline-block;margin-right:5px;transition:transform .1s}
.mx-tool[open]>summary .mx-name:before{transform:rotate(90deg)}
.mx-bar{display:flex;height:16px;border-radius:3px;overflow:hidden;background:rgba(128,128,128,.15)}
.mx-bar i{display:block;height:100%;min-width:2px;font:700 10px/16px Arial,sans-serif;font-style:normal;text-align:center;color:#fff;overflow:hidden}
.mx-c-unique{background:#0072B2}.mx-c-red{background:repeating-linear-gradient(45deg,#CC79A7 0 3px,#f0cfe2 3px 6px)}.mx-c-chrom{background:#D55E00}.mx-c-unm{background:repeating-linear-gradient(90deg,#999 0 3px,#ddd 3px 6px)}
.mx-o-single{background:#0072B2}.mx-o-frag{background:#E69F00;color:#111!important}.mx-o-dup{background:#CC79A7;color:#111!important}.mx-o-fd{background:repeating-linear-gradient(45deg,#CC79A7 0 4px,#E69F00 4px 8px);color:#111!important}
.mx-o-miss{background:#D55E00}.mx-o-other{background:repeating-linear-gradient(90deg,#999 0 3px,#ddd 3px 6px);color:#111!important}
.mx-dumb{position:relative;display:block;height:16px;margin:0 6px}
.mx-dumb:before{content:"";position:absolute;left:0;right:0;top:7px;height:2px;background:rgba(128,128,128,.3)}
.mx-line{position:absolute;top:6px;height:4px;background:rgba(0,114,178,.5);border-radius:2px}
.mx-best,.mx-comb{position:absolute;top:2px;width:12px;height:12px;margin-left:-6px;box-sizing:border-box;font-style:normal}
.mx-best{border-radius:50%;background:#0072B2;border:2px solid #fff}
.mx-comb{background:#E69F00;border:2px solid #fff;transform:rotate(45deg) scale(.85)}
.mx-na{font-size:.85em;opacity:.7}
.mx-txt{font-size:.8em;font-weight:400;line-height:1.25;opacity:.9}
.mx-body{padding:4px 0 8px 14px}
.mx-scroll{max-height:240px;overflow:auto;border:1px solid rgba(128,128,128,.3);border-radius:4px}
.mx-t{border-collapse:collapse;font-size:.85em;width:100%}.mx-t th,.mx-t td{border-bottom:1px solid rgba(128,128,128,.25);padding:2px 8px;text-align:left}
.mx-t thead th{position:sticky;top:0;background:var(--card,#fff)}
.mx-h{margin:10px 0 2px;font-size:.95em}
.mx-track{margin:4px 0}.mx-track>summary{cursor:pointer;font-weight:600;font-size:.9em}
.mx-track svg{display:block;width:100%;max-height:250px}
.mx-all{margin:8px 0}.mx-all>summary{cursor:pointer;font-weight:600}
.mx-key{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.78em;margin-top:6px;opacity:.9}.mx-key span{display:inline-flex;align-items:center;gap:4px}.mx-key i{display:inline-block;width:12px;height:10px;border-radius:2px;position:static;margin:0}
.mx-key i.mx-k{width:10px;height:10px;transform:none}.mx-key i.mx-comb.mx-k{transform:rotate(45deg) scale(.8)}
@media (max-width:760px){.mx-head{display:none}.mx-row{grid-template-columns:1fr 1fr;grid-template-areas:"n n" "a b" "c t"}.mx-row .mx-name{grid-area:n}}
@media print{.mx-scroll{max-height:none}}
.rv-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.88em;margin:6px 0}.rv-legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}
</style>"""


def read_tsv(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=chr(9)))


def number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def note(message, caution=True):
    return f"<div class='insight{' caution' if caution else ''}'><p>{esc(message)}</p></div>"


def section(sid, title, lead, body):
    return f"<section id='{sid}' class='rv'><h2>{esc(title)}</h2><p class='lead'>{lead}</p>{body}</section>"


def bar(value, vmax, label, colour=None):
    if value is None:
        return "<td>-</td>"
    pct = 0 if not vmax else max(0.0, min(100.0, 100.0 * value / vmax))
    style = f" style='width:{pct:.1f}%;background:{colour}'" if colour else f" style='width:{pct:.1f}%'"
    return f"<td><div class='rv-bar' title='{esc(label)}'><span{style}></span><b>{esc(label)}</b></div></td>"


def chip(status):
    cls = {"PASS": "rv-pass", "WARN": "rv-warn", "REJECT": "rv-reject"}.get(status, "")
    return f"<span class='rv-chip {cls}'>{esc(status or '-')}</span>"


def compact(x, digits=3):
    if x is None:
        return "-"
    if abs(x) >= 1e6:
        return f"{x / 1e6:.{digits - 1}f} M"
    if abs(x) >= 1e3:
        return f"{x / 1e3:.1f} k"
    return f"{x:.{digits}g}"


# ----------------------------------------------------------------------------------------------- A. short-read QC
def readqc_section(qc, status_rows=None, ctx=None):
    """The short-read QC section: the interactive panel (python/report_readqc_panel.py) with the earlier table kept in a fold, "All values"."""
    ctx = ctx or {}
    lead = ("Each sample's raw read pair is measured before assembly and given a decision. <strong>Descriptive evidence; the gate's own "
            "rule is in FAQ Q33.</strong>")
    if not qc:
        return section("learn-readqc", "Short-read QC", lead, qp.not_measured(ctx.get("results_dir", "")))
    panel = qp.build(qc, ctx.get("results_dir", ""), ctx.get("thresholds"), status_rows if status_rows is not None else ctx.get("status_rows"),
                     ctx.get("candidates"), ctx.get("scores"), ctx.get("synthetic"))
    return section("learn-readqc", "Short-read QC", lead,
                   panel + "<details class='qp-all'><summary>All values</summary>" + _readqc_legacy(qc) + "</details>")


def _readqc_legacy(qc):
    """The earlier plain view: decision bar, reasons, table with inline bars and the thresholds note (kept so nothing is removed)."""
    counts = {k: sum(1 for r in qc if r.get("qc_status") == k) for k in ("PASS", "WARN", "REJECT")}
    total = len(qc) or 1
    W, H, left = 760, 56, 8
    svg = [svg_open(W, H, "Short-read QC decisions", "Stacked bar of samples by decision: pass, warn, reject.")]
    x = left
    for key, colour in (("PASS", "#009E73"), ("WARN", "#E69F00"), ("REJECT", "#D55E00")):
        w = (W - 2 * left) * counts[key] / total
        if w > 0:
            svg.append(f"<rect x='{num(x)}' y='10' width='{num(w)}' height='26' fill='{colour}'><title>{counts[key]} {key}</title></rect>")
            if w > 70:
                svg.append(text(x + w / 2, 28, f"{counts[key]} {key}", 12, "middle", "bold", "#111111" if key == "WARN" else "#ffffff"))
        x += w
    svg.append(text(left, 52, f"{len(qc)} samples screened", 11))
    svg.append(svg_close())
    reasons = {}
    for r in qc:
        for part in (r.get("reasons") or "").split(";"):
            part = part.strip()
            if part:
                key = part.split(" ")[0].rstrip(":")
                reasons[key] = reasons.get(key, 0) + 1
    why = ("<p>Reasons recorded: " + ", ".join(f"{esc(k)} ({n})" for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])) + ".</p>"
           if reasons else "<p>No sample triggered a warning or rejection.</p>")
    pairs_max = max([number(r.get("read_pairs_total")) or 0 for r in qc] + [1])
    depth_max = max([number(r.get("estimated_depth_x")) or 0 for r in qc] + [1])
    len_max = max([number(r.get("median_read_length")) or 0 for r in qc] + [1])
    head = ["Sample", "Decision", "Read pairs", "Depth (x)", "Mean Q", "% Q30", "Median length", "% GC", "% duplicates", "% adapter", "Reasons"]
    rows = []
    for r in sorted(qc, key=lambda r: ({"REJECT": 0, "WARN": 1, "PASS": 2}.get(r.get("qc_status"), 3), r.get("sample", ""))):
        pairs, depth, q, q30 = (number(r.get(k)) for k in ("read_pairs_total", "estimated_depth_x", "mean_quality", "q30_fraction"))
        mlen, gc, dup, ada = (number(r.get(k)) for k in ("median_read_length", "gc_percent", "duplication_fraction", "adapter_fraction"))
        basis = "" if r.get("pairs_basis") == "exact" else "~"
        assumed = "*" if r.get("genome_size_assumed") == "yes" else ""
        rows.append(
            f"<tr><td><b>{esc(r.get('sample'))}</b></td><td>{chip(r.get('qc_status'))}</td>"
            + bar(pairs, pairs_max, basis + compact(pairs)) + bar(depth, depth_max, (f"{depth:.1f}" if depth is not None else "-") + assumed)
            + bar(q, 40, f"{q:.1f}" if q is not None else "-") + bar(q30, 1, f"{100 * q30:.0f}" if q30 is not None else "-")
            + bar(mlen, len_max, f"{mlen:g}" if mlen is not None else "-")
            + bar(gc, 100, f"{gc:.1f}" if gc is not None else "-", "rgba(204,121,167,.45)")
            + bar(dup, 1, f"{100 * dup:.1f}" if dup is not None else "-", "rgba(213,94,0,.35)")
            + bar(ada, 1, f"{100 * ada:.1f}" if ada is not None else "-", "rgba(230,159,0,.45)")
            + f"<td class='rv-l'>{esc(r.get('reasons') or r.get('integrity') if r.get('integrity') not in ('ok', None, '') else r.get('reasons') or '')}</td></tr>")
    table = ("<div class='panel' style='overflow-x:auto'><table><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head)
             + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    policy = qc[0].get("policy_status", "")
    sha = qc[0].get("thresholds_sha", "")
    key = "<p class='small'>~ the total is estimated from the sampled reads; * the depth assumes the default genome size (5 Mb) because none was given.</p>"
    foot = key + note(f"Thresholds are {policy or 'not recorded'} (file hash {sha or 'not recorded'}). "
                + ("They are provisional starting points, not universal cut-offs: set them from pilot data on the intended platform, "
                   "freeze them, and only then run the main benchmark. " if policy != "frozen" else "")
                + "Taxonomic contamination is not screened here (it needs a database); an unreadable, truncated, empty or malformed file is "
                  "always rejected. Report the passed, flagged and excluded counts with any result, and check whether the flagged samples "
                  "change the conclusion.", caution=policy != "frozen")
    return "".join(svg) + why + table + foot


# ----------------------------------------------------------------------------------------------- B. assembly selection
MEASURES = [("Contigs", "n_contigs", "low"), ("Largest contig (bp)", "largest_contig", "high"), ("Total length (bp)", "total_length", None),
            ("N50 (bp)", "n50", "high"), ("L50", "l50", "low"), ("Length in contigs >= 1 kb (bp)", "bp_ge_1kb", "high"),
            ("Length in contigs >= 10 kb (bp)", "bp_ge_10kb", "high"), ("GC (%)", "gc_percent", None),
            ("Reads mapping to the assembly", "mapped_read_fraction", "high")]


def heat(t):
    """Worst (0) to best (1): red, white, blue, as in QUAST's comparison table."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        k = t / 0.5
        rgb = (round(244 + 11 * k), round(166 + 89 * k), round(166 + 89 * k))
    else:
        k = (t - 0.5) / 0.5
        rgb = (round(255 - 149 * k), round(255 - 132 * k), round(255 - 16 * k))
    return "#%02x%02x%02x" % rgb


def assembly_section(candidates, ctx=None):
    ctx = ctx or {}
    lead = ("Every candidate assembly is measured from the assembly itself and kept; the policy chooses from that evidence only, "
            "<strong>never from the truth or a benchmark score</strong>.")
    if not candidates:
        return section("learn-assembly", "Assembly selection", lead, qp.not_measured(ctx.get("results_dir", ""), "assembly selection"))
    by = {}
    for r in candidates:
        by.setdefault(r["sample"], []).append(r)
    tally = {}
    for rows in by.values():
        pick = next((r["assembler"] for r in rows if r.get("selected") == "yes"), "none eligible")
        tally[pick] = tally.get(pick, 0) + 1
    policy = candidates[0].get("policy", "")
    primary = candidates[0].get("primary", "")
    summary = ("<p>Policy <strong>" + esc(policy) + "</strong> (configured assembler " + esc(primary) + "): selected "
               + ", ".join(f"{esc(k)} for {n} sample(s)" for k, n in sorted(tally.items())) + ".</p>")
    synthetic = ctx.get("synthetic")
    if synthetic is None:
        synthetic = qp.is_synthetic(ctx.get("results_dir", ""))
    flag = f"<div class='insight caution qp-synthetic' role='note'><p><strong>Synthetic.</strong> {esc(qp.SYNTHETIC_NOTE)}</p></div>" if synthetic else ""
    legend = ("<div class='rv-legend'><label class='qp-heatbox'><input type='checkbox' id='qp-heat' checked> Show heatmap</label>"
              "<span><i style='background:" + heat(0) + "'></i>Worst</span><span><i style='background:" + heat(.5)
              + ";border:1px solid #bbb'></i>Median</span><span><i style='background:" + heat(1) + "'></i>Best</span>"
              "<span>Colour compares candidates within a row; total length and GC are not coloured (neither direction is better). "
              "The selected assembly is marked with a star and a heavy outline.</span></div>")
    blocks = []
    for i, (sample, rows) in enumerate(sorted(by.items())):
        names = [r["assembler"] for r in rows]
        sel = [r.get("selected") == "yes" for r in rows]
        head = "".join(f"<th{' class=qp-sel' if sel[j] else ''}>{esc(r['assembler'])}{' &#9733; selected' if sel[j] else ''}</th>" for j, r in enumerate(rows))
        body = []
        for label, key, direction in MEASURES:
            values = [number(r.get(key)) for r in rows]
            known = [v for v in values if v is not None]
            cells = []
            for j, v in enumerate(values):
                cls = " qp-sel" if sel[j] else ""
                if v is None:
                    cells.append(f"<td class='{cls.strip()}'>{esc(next((r.get(key) for r in rows if number(r.get(key)) is None and r.get(key)), '-'))}</td>")
                    continue
                shown = f"{v:.3f}" if key == "mapped_read_fraction" else (f"{v:.2f}" if key == "gc_percent" else f"{v:,.0f}")
                if direction and len(known) > 1 and max(known) != min(known):
                    t = (v - min(known)) / (max(known) - min(known))
                    t = t if direction == "high" else 1 - t
                    cells.append(f"<td class='qp-h{cls}' style='--heat:{heat(t)}'>{shown}</td>")
                else:
                    cells.append(f"<td class='{cls.strip()}'>{shown}</td>")
            body.append(f"<tr><th class='rv-l'>{esc(label)}</th>{''.join(cells)}</tr>")
        elig = "".join(f"<td class='rv-l{' qp-sel' if sel[j] else ''}' title='{esc(r.get('reasons') or '')}'>{'eligible' if r.get('eligible') == 'yes' else 'not eligible'}"
                       f"{(': ' + esc(r.get('reasons'))) if r.get('reasons') else ''}</td>" for j, r in enumerate(rows))
        body.append(f"<tr><th class='rv-l'>Eligibility</th>{elig}</tr>")
        why = next((r.get("selection_reason") for r in rows if r.get("selection_reason")), "")
        table = (f"<div class='panel' style='overflow-x:auto'><table><thead><tr><th class='rv-l'>{esc(sample)}</th>{head}</tr></thead>"
                 f"<tbody>{''.join(body)}</tbody></table></div><p class='small'><strong>Reason:</strong> {esc(why or 'no reason recorded')}</p>")
        blocks.append(f"<details{' open' if i == 0 else ''}><summary>{esc(sample)}: {len(names)} candidate(s)</summary>{table}</details>")
    foot = note("Assemblers being compared are not 'selected': keep each as its own input condition. The alternatives above are retained "
                "for a sensitivity analysis; running every tool on each alternative is not done yet.", caution=False)
    return section("learn-assembly", "Assembly selection", lead, flag + summary + legend + "".join(blocks) + foot + "<script>" + HEAT_JS + "</script>")


HEAT_JS = ("(function(){var c=document.getElementById('qp-heat'),s=document.getElementById('learn-assembly');if(!c||!s)return;"
           "c.addEventListener('change',function(){s.classList.toggle('qp-noheat',!c.checked)})})();")


# ----------------------------------------------------------------------------------------------- C. multiplicity
def tool_composition(candidates, plasmids):
    """Per tool: predicted bp split into unique plasmid sequence, redundant, chromosome and unmapped."""
    out = {}
    for r in candidates or []:
        e = out.setdefault(r["tool"], {"length": 0.0, "plasmid": 0.0, "chrom": 0.0, "redundant": 0.0, "n": 0, "chimeric": 0, "off": 0, "unmapped": 0})
        e["length"] += number(r.get("length")) or 0
        e["plasmid"] += number(r.get("plasmid_bp")) or 0
        e["chrom"] += number(r.get("chromosome_bp")) or 0
        e["n"] += 1
        rel = r.get("relationship")
        e["chimeric"] += rel == "chimeric"
        e["off"] += rel == "off_target"
        e["unmapped"] += rel == "unmapped"
    for r in plasmids or []:
        if r["tool"] in out:
            out[r["tool"]]["redundant"] += number(r.get("redundant_bp")) or 0
    return out


def composition_chart(comp):
    if not comp:
        return ""
    tools = sorted(comp)
    W, left, right, top, rowh = 760, 150, 20, 34, 34
    H = top + rowh * len(tools) + 40
    scale = (W - left - right)
    parts = [("unique", "Unique plasmid sequence", BLUE), ("redundant", "Redundant plasmid sequence", PURPLE),
             ("chrom", "Chromosome (off-target)", VERM), ("unmapped", "Unmapped", GREY)]
    out = [svg_open(W, H, "Where each tool's predicted sequence went",
                    "Each bar is all the sequence a tool predicted, split into plasmid sequence counted once, plasmid sequence that other "
                    "candidates already cover, sequence that aligns to the chromosome, and sequence that aligns nowhere.")]
    x0 = left
    for i, (_, label, colour) in enumerate(parts):
        out.append(f"<rect x='{x0 + i * 175}' y='8' width='11' height='11' rx='2' fill='{colour}'/>")
        out.append(text(x0 + i * 175 + 16, 18, label, 10.5))
    for k, tool in enumerate(tools):
        e = comp[tool]
        total = e["length"] or 1.0
        unique = max(0.0, e["plasmid"] - e["redundant"])
        unmapped = max(0.0, e["length"] - e["plasmid"] - e["chrom"])
        vals = {"unique": unique, "redundant": e["redundant"], "chrom": e["chrom"], "unmapped": unmapped}
        y = top + k * rowh
        out.append(text(left - 10, y + 17, tool, 11.5, "end", "bold"))
        x = left
        for key, label, colour in parts:
            w = scale * vals[key] / max(sum(vals.values()), total)
            if w > 0:
                out.append(f"<rect x='{num(x)}' y='{y + 4}' width='{num(w)}' height='20' fill='{colour}'><title>{esc(tool)}: {esc(label)} "
                           f"{vals[key]:,.0f} bp ({100 * vals[key] / total:.1f}% of {total:,.0f} bp predicted)</title></rect>")
                if w > 44:
                    out.append(text(x + w / 2, y + 18, f"{100 * vals[key] / total:.0f}%", 9.5, "middle", fill="#ffffff"))
            x += w
    out.append(svg_close())
    return "".join(out)


def coverage_chart(plasmids):
    tools = sorted({r["tool"] for r in plasmids or []})
    if not tools:
        return ""
    stats = []
    for t in tools:
        rows = [r for r in plasmids if r["tool"] == t]
        stats.append((t, mean([number(r["best_candidate_coverage"]) for r in rows]), mean([number(r["combined_coverage"]) for r in rows]),
                      mean([number(r["n_candidates"]) for r in rows]), mean([number(r["redundancy_fraction"]) for r in rows]), len(rows)))
    W, left, right, top, rowh = 760, 150, 250, 30, 50
    H = top + rowh * len(stats) + 30
    scale = W - left - right
    out = [svg_open(W, H, "Best candidate against all candidates combined",
                    "For each tool, the mean share of a truth plasmid covered by its single best candidate (darker bar) and by all its "
                    "candidates together, counting reference bases once (lighter bar). The gap is what extra candidates add.")]
    out.append(f"<rect x='{left}' y='8' width='11' height='11' rx='2' fill='{BLUE}'/>" + text(left + 16, 18, "Best single candidate", 10.5)
               + f"<rect x='{left + 170}' y='8' width='11' height='11' rx='2' fill='{OKABE_ITO['sky']}'/>" + text(left + 186, 18, "All candidates combined (union)", 10.5))
    for k, (tool, best, comb, n, red, count) in enumerate(stats):
        y = top + k * rowh
        out.append(text(left - 10, y + 22, tool, 11.5, "end", "bold"))
        for j, (v, colour, label) in enumerate(((best, BLUE, "best"), (comb, OKABE_ITO["sky"], "combined"))):
            if v is not None:
                out.append(f"<rect x='{left}' y='{y + 4 + j * 19}' width='{num(scale * v)}' height='16' fill='{colour}'><title>{esc(tool)}: "
                           f"{label} coverage {v:.3f} over {count} plasmids</title></rect>")
                out.append(text(left + scale * v + 6, y + 16 + j * 19, f"{v:.2f}", 10.5))
        out.append(text(W - right + 8, y + 22, f"{n:.2f} candidates, {100 * (red or 0):.0f}% redundant", 10))
    out.append(svg_close())
    return "".join(out)


def depth_segments(spans, length):
    events = sorted([(s, 1) for s, e in spans] + [(e, -1) for s, e in spans])
    segs, depth, last = [], 0, 0
    for pos, d in events:
        if pos > last:
            segs.append((last, pos, depth))
        depth += d
        last = max(last, pos)
    if last < length:
        segs.append((last, length, 0))
    return segs


def track_figure(plasmid_row, intervals):
    length = int(number(plasmid_row["plasmid_length"]))
    cands = {}
    for r in intervals:
        cands.setdefault(r["candidate"], {"rel": r["relationship"], "spans": []})["spans"].append((int(r["start"]), int(r["end"])))
    order = sorted(cands, key=lambda q: (-sum(e - s for s, e in cands[q]["spans"]), q))
    W, left, right, top = 760, 90, 150, 30
    rowh = 20
    H = top + 36 + rowh * len(order) + 60
    scale = (W - left - right) / length
    title = f"{plasmid_row['sample']} / {plasmid_row['tool']} / {plasmid_row['plasmid']}"
    out = [svg_open(W, H, f"Candidates against {title}",
                    f"The reference plasmid ({length:,} bp) on top and every candidate that aligns to it below, positioned by alignment. The "
                    f"strip underneath shows reference covered once, covered by several candidates, or not represented.")]
    out.append("<defs><pattern id='rvh' width='6' height='6' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><line x1='0' y1='0' x2='0' y2='6' "
               "stroke='#fff' stroke-width='2'/></pattern><pattern id='rvg' width='5' height='5' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
               "<line x1='0' y1='0' x2='0' y2='5' stroke='#999' stroke-width='1.3'/></pattern></defs>")
    out.append(text(left, 16, f"{title}   {length / 1000:.1f} kb   outcome: {plasmid_row['outcome'].replace('_', ' ')}", 11.5, "start", "bold"))
    out.append(f"<rect x='{left}' y='{top}' width='{num(length * scale)}' height='14' fill='{GREEN}'><title>reference plasmid {length:,} bp</title></rect>")
    out.append(text(left - 8, top + 11, "Reference", 10.5, "end"))
    for i, q in enumerate(order):
        y = top + 24 + i * rowh
        fill, label = RELATION_STYLE.get(cands[q]["rel"], (GREY, cands[q]["rel"]))
        out.append(text(left - 8, y + 11, q if len(q) < 14 else q[:12] + "..", 9.5, "end"))
        out.append(line(left, y + 7, left + length * scale, y + 7, "currentColor", 0.5, "opacity='0.25'"))
        for s, e in cands[q]["spans"]:
            hatch = "<rect x='{x}' y='{y}' width='{w}' height='12' fill='url(#rvh)'/>" if cands[q]["rel"] == "redundant" else ""
            out.append(f"<rect x='{num(left + s * scale)}' y='{y + 1}' width='{num(max((e - s) * scale, 1))}' height='12' fill='{fill}'>"
                       f"<title>{esc(q)} ({esc(label)}): {s:,}-{e:,} ({e - s:,} bp)</title></rect>"
                       + hatch.format(x=num(left + s * scale), y=y + 1, w=num(max((e - s) * scale, 1))))
        out.append(text(left + length * scale + 4, y + 11, label, 9, "start"))
    strip_y = top + 30 + rowh * len(order)
    all_spans = [sp for q in order for sp in cands[q]["spans"]]
    out.append(text(left - 8, strip_y + 10, "Coverage", 10.5, "end"))
    for s, e, d in depth_segments(sorted(all_spans), length):
        fill = "url(#rvg)" if d == 0 else (BLUE if d == 1 else PURPLE)
        word = "not represented" if d == 0 else ("covered once" if d == 1 else f"covered by {d} candidates")
        out.append(f"<rect x='{num(left + s * scale)}' y='{strip_y}' width='{num(max((e - s) * scale, 0.5))}' height='14' fill='{fill}'>"
                   f"<title>{s:,}-{e:,}: {word}</title></rect>")
    for kb in range(0, length + 1, max(1000, int(length / 8 / 1000) * 1000)):
        x = left + kb * scale
        out.append(line(x, strip_y + 14, x, strip_y + 19, "currentColor", 1))
        out.append(text(x, strip_y + 30, f"{kb / 1000:.0f} kb", 9, "middle"))
    out.append(svg_close())
    return "".join(out)


MX_OUTCOMES = [("single", "single candidate", BLUE, "mx-o-single"), ("fragmented", "fragmented", ORANGE, "mx-o-frag"), ("duplicated", "duplicated", PURPLE, "mx-o-dup"),
               ("fragmented_and_duplicated", "fragmented and duplicated", PURPLE, "mx-o-fd"), ("missed", "missed", VERM, "mx-o-miss"),
               ("carried_only_in_other_candidates", "carried only in other candidates", GREY, "mx-o-other")]


def _pct(x):
    return f"{max(0.0, min(100.0, x)):.2f}"


def _mx_composition(tool, e):
    """One thin stacked bar: where the sequence a tool predicted went. Each segment has a tooltip and a pattern; the legend names them."""
    total = e["length"] or 1.0
    unique = max(0.0, e["plasmid"] - e["redundant"])
    unmapped = max(0.0, e["length"] - e["plasmid"] - e["chrom"])
    vals = (("mx-c-unique", "unique plasmid sequence", unique), ("mx-c-red", "redundant plasmid sequence", e["redundant"]),
            ("mx-c-chrom", "chromosome (off-target)", e["chrom"]), ("mx-c-unm", "unmapped", unmapped))
    denom = max(sum(v for _, _, v in vals), total)
    segs = "".join(f"<i class='{cls}' style='width:{_pct(100 * v / denom)}%' title='{esc(tool)}: {esc(label)} {v:,.0f} bp ({100 * v / total:.1f}% of {total:,.0f} bp predicted)'></i>"
                   for cls, label, v in vals if v > 0)
    words = "; ".join(f"{label} {100 * v / total:.0f}%" for _, label, v in vals if v > 0)
    return f"<span class='mx-bar' role='img' aria-label='{esc(tool)}: predicted sequence split into {esc(words)}'>{segs}</span>"


def _mx_dumbbell(tool, best, comb, count):
    """Best single candidate (dot) against all candidates combined (diamond) on a fixed 0..1 scale; the line between them is what extra candidates add."""
    if best is None or comb is None:
        return "<span class='mx-dumb mx-na' title='not assessed'>not assessed</span>"
    lo, hi = min(best, comb), max(best, comb)
    return (f"<span class='mx-dumb' role='img' aria-label='{esc(tool)}: best single candidate covers {best:.2f} of a plasmid, all candidates together {comb:.2f}, over {count} plasmids'>"
            f"<b class='mx-line' style='left:{_pct(100 * lo)}%;width:{_pct(100 * (hi - lo))}%'></b>"
            f"<i class='mx-best' style='left:{_pct(100 * best)}%' title='{esc(tool)}: best single candidate {best:.3f} (mean over {count} plasmids)'></i>"
            f"<i class='mx-comb' style='left:{_pct(100 * comb)}%' title='{esc(tool)}: all candidates combined {comb:.3f} (reference bases counted once)'></i>"
            f"</span>")


def _mx_outcomes(tool, counts):
    total = sum(counts.values()) or 1
    segs = "".join(f"<i class='{cls}' style='width:{_pct(100 * counts[key] / total)}%' title='{esc(tool)}: {counts[key]} plasmid(s) {esc(label)}'>{counts[key]}</i>"
                   for key, label, _c, cls in MX_OUTCOMES if counts.get(key))
    words = "; ".join(f"{counts[key]} {label}" for key, label, _c, _x in MX_OUTCOMES if counts.get(key))
    return f"<span class='mx-bar mx-oc' role='img' aria-label='{esc(tool)}: reference plasmids by outcome: {esc(words)}'>{segs}</span>"


def multiplicity_section(plasmids, candidates, intervals):
    lead = ("Does a tool return one clean record per plasmid, or several overlapping or mixed ones? Click a tool for its plasmids and tracks. "
            "<strong>Descriptive: it never changes a score, and extra candidates cannot raise the primary endpoint.</strong>")
    if not plasmids:
        return section("learn-multiplicity", "Reconstruction multiplicity", lead, note(
            "Not run: benchmark.candidate_multiplicity.tsv was not produced (RUN_CANDIDATE_MULTIPLICITY=0, or stage 5 has not run)."))
    comp = tool_composition(candidates, plasmids)
    outcomes = {}
    for r in plasmids:
        outcomes.setdefault(r["tool"], {}).setdefault(r["outcome"], 0)
        outcomes[r["tool"]][r["outcome"]] += 1
    names = [k for k, _l, _c, _x in MX_OUTCOMES]
    rows = []
    for tool in sorted(outcomes):
        group = [r for r in plasmids if r["tool"] == tool]
        c = comp.get(tool, {})
        rows.append([tool, len(group), f"{mean([number(r['n_candidates']) for r in group]):.2f}",
                     f"{mean([number(r['best_candidate_coverage']) for r in group]):.3f}", f"{mean([number(r['combined_coverage']) for r in group]):.3f}",
                     f"{mean([number(r['redundancy_fraction']) for r in group]):.3f}", int(c.get("chimeric", 0)), int(c.get("off", 0)),
                     int(c.get("unmapped", 0))] + [outcomes[tool].get(n, 0) for n in names])
    head = ["Tool", "Plasmids", "Mean candidates", "Best coverage", "Combined coverage", "Redundancy", "Chimeric", "Off-target", "Unmapped"] + [
        n.replace("_", " ") for n in names]
    table = ("<div class='panel' style='overflow-x:auto'><table><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")
    by_plasmid = {}
    for r in intervals or []:
        by_plasmid.setdefault((r["sample"], r["tool"], r["plasmid"]), []).append(r)
    chosen = sorted((r for r in plasmids if (r["sample"], r["tool"], r["plasmid"]) in by_plasmid and (number(r["n_touching"]) or 0) > 1),
                    key=lambda r: (-(number(r["n_touching"]) or 0), -(number(r["redundant_bp"]) or 0), r["sample"], r["tool"], r["plasmid"]))[:6]
    legend = ("<div class='rv-legend'>" + "".join(f"<span><i style='background:{c}'></i>{esc(lbl)}</span>" for c, lbl in
                                                  ((BLUE, "primary / covered once"), (ORANGE, "complementary fragment"), (PURPLE, "redundant / covered by several"),
                                                   (VERM, "chimeric"), (GREEN, "reference"))) + "<span>grey hatching: not represented</span></div>")
    tool_rows = []
    for tool in sorted(outcomes):
        group = [r for r in plasmids if r["tool"] == tool]
        gain = mean([number(r["coverage_gain"]) for r in group])
        red = mean([number(r["redundancy_fraction"]) for r in group])
        many = sum(1 for r in group if (number(r["n_candidates"]) or 0) > 1)
        n_cand = mean([number(r["n_candidates"]) for r in group])
        if many:
            reading = (f"{tool}: {many} of {len(group)} plasmids have more than one candidate; extra candidates add {100 * (gain or 0):.1f} "
                       f"points of coverage over the best one and {100 * (red or 0):.1f}% of the candidate sequence on plasmids is redundant.")
        else:
            reading = f"{tool}: no plasmid has more than one candidate."
        best = mean([number(r["best_candidate_coverage"]) for r in group])
        comb = mean([number(r["combined_coverage"]) for r in group])
        order = {k: i for i, k in enumerate(names)}
        body_rows = "".join(
            f"<tr><td>{esc(r['sample'])}</td><td>{esc(r['plasmid'])}</td><td>{esc(r['n_candidates'])}</td><td>{esc(r['best_candidate_coverage'])}</td>"
            f"<td>{esc(r['combined_coverage'])}</td><td>{esc(r['redundancy_fraction'])}</td><td>{esc(r['outcome'].replace('_', ' '))}</td></tr>"
            for r in sorted(group, key=lambda r: (order.get(r["outcome"], 99), r["sample"], r["plasmid"]))[:300])
        plasmid_table = ("<div class='mx-scroll'><table class='mx-t'><thead><tr><th>Isolate</th><th>Plasmid</th><th>Candidates</th><th>Best</th><th>Combined</th>"
                         f"<th>Redundancy</th><th>Outcome</th></tr></thead><tbody>{body_rows}</tbody></table></div>"
                         + (f"<p class='small'>The first 300 of {len(group)} plasmids; the full table is benchmark.candidate_multiplicity.tsv.</p>" if len(group) > 300 else ""))
        mine = [r for r in chosen if r["tool"] == tool]
        tracks = "".join(
            f"<details class='mx-track'><summary>{esc(r['sample'])} / {esc(r['plasmid'])}: {esc(r['n_touching'])} records touch it, outcome {esc(r['outcome'].replace('_', ' '))}</summary>"
            f"<figure class='binfig'>{track_figure(r, by_plasmid[(r['sample'], r['tool'], r['plasmid'])])}</figure></details>" for r in mine)
        tool_rows.append(
            f"<details class='mx-tool'><summary class='mx-row'><span class='mx-name'>{esc(tool)}</span>{_mx_composition(tool, comp.get(tool, {'length': 0, 'plasmid': 0, 'chrom': 0, 'redundant': 0}))}"
            f"{_mx_dumbbell(tool, best, comb, len(group))}{_mx_outcomes(tool, outcomes[tool])}"
            f"<span class='mx-txt'>coverage {best:.2f} &rarr; {comb:.2f}; {(n_cand or 0):.1f} candidates per plasmid; {100 * (red or 0):.0f}% redundant</span></summary>"
            f"<div class='mx-body'><p class='small'>{esc(reading)}</p>{plasmid_table}"
            + (f"<h4 class='mx-h'>Candidates against the reference</h4>{legend}{tracks}" if tracks else "") + "</div></details>")
    key = ("<div class='mx-key'><span><i class='mx-c-unique'></i>unique plasmid sequence</span><span><i class='mx-c-red'></i>redundant</span>"
           "<span><i class='mx-c-chrom'></i>chromosome</span><span><i class='mx-c-unm'></i>unmapped</span>"
           "<span><i class='mx-best mx-k'></i>best single candidate</span><span><i class='mx-comb mx-k'></i>all combined</span>"
           + "".join(f"<span><i class='{cls}'></i>{esc(lbl)}</span>" for _k, lbl, _c, cls in MX_OUTCOMES) + "</div>")
    heads = ("<div class='mx-head' aria-hidden='true'><span>Tool</span><span>Where the predicted sequence went</span><span>Coverage of a plasmid: best &rarr; all combined</span>"
             "<span>What happened to each reference plasmid (count)</span><span></span></div>")
    full = ""
    figs = [composition_chart(comp), coverage_chart(plasmids)]
    if any(figs):
        full = ("<details class='mx-all'><summary>Full-size charts</summary>"
                + "".join(f"<figure class='binfig'><div style='overflow-x:auto'>{f}</div></figure>" for f in figs if f) + "</details>")
    if not chosen:
        full += note("No plasmid in this run has more than one candidate touching it, so there are no tracks to draw.", caution=False)
    return section("learn-multiplicity", "Reconstruction multiplicity", lead,
                   "<div class='mx'>" + heads + "".join(tool_rows) + key + "</div>"
                   + "<details class='mx-all'><summary>All values (one row per tool)</summary>" + table + "</details>" + full)


def stability_section(summary, study_rows=None, species_rows=None):
    lead = ("Does the order of the tools survive removing one study or one species, or giving every study the same weight? "
            "<strong>Descriptive; it never changes the leaderboard.</strong> A ranking dominated by one study is reported as fragile.")
    if not summary:
        return section("learn-stability", "Ranking stability", lead, note(
            "Not run: results/benchmark.ranking_stability.tsv was not produced (RUN_RANKING_STABILITY=0, or no task had two tools with scores)."))
    rows = []
    for s in summary:
        fragile = s.get("verdict", "").startswith("fragile")
        chip = ("rv-warn" if fragile else "rv-pass") if s.get("verdict", "").startswith(("fragile", "stable")) else ""
        word = s.get("verdict", "").split(":")[0]
        rows.append(
            f"<tr><td>{esc(s['analysis_track'])}</td><td>{esc(s['evaluation_task'])}</td><td>{esc(s['n_isolates'])}</td>"
            f"<td>{esc(s['n_studies'])}</td><td>{esc(s['n_species'])}</td>"
            f"<td>{esc(s['largest_study'])} ({esc(s['largest_study_share'])})</td><td>{esc(s['baseline_leader'])}</td>"
            f"<td>{esc(s['study_leader_changes'] or '-')}/{esc(s['study_leave_outs'])}</td>"
            f"<td>{esc(s['species_leader_changes'] or '-')}/{esc(s['species_leave_outs'])}</td>"
            f"<td>{esc(s['equal_study_leader'] or '-')}</td><td><span class='rv-chip {chip}'>{esc(word)}</span> {esc(s['verdict'].partition(': ')[2])}</td></tr>")
    table = ("<div class='panel'><table><thead><tr><th>Track</th><th>Task</th><th>Isolates</th><th>Studies</th><th>Species</th>"
             "<th>Largest study (share)</th><th>Leader</th><th>Leader changes, study leave-outs</th><th>Leader changes, species leave-outs</th>"
             "<th>Leader with equal study weights</th><th>Verdict</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    changed = [r for r in (study_rows or []) + (species_rows or []) if r.get("leader_changed") == "yes"]
    detail = ""
    if changed:
        detail = ("<h3>Leave-outs that change the leader</h3><div class='panel'><table><thead><tr><th>Task</th><th>Left out</th><th>Isolates removed</th>"
                  "<th>New leader</th><th>Kendall tau</th></tr></thead><tbody>"
                  + "".join(f"<tr><td>{esc(r['evaluation_task'])}</td><td>{esc(r['left_out'])}</td><td>{esc(r['isolates_removed'])}</td>"
                            f"<td>{esc(r['leader'])}</td><td>{esc(r['kendall_tau'])}</td></tr>" for r in changed) + "</tbody></table></div>")
    return section("learn-stability", "Ranking stability", lead, table + detail)


def refaudit_section(rows):
    lead = ("How far can each isolate's truth assembly be trusted? <strong>Descriptive; it never changes a score.</strong> A weak reference is "
            "kept in the tables and named here, so a reader can see what a headline rests on.")
    if not rows:
        return section("learn-refaudit", "Reference evidence", lead, note(
            "Not run: results/benchmark.reference_evidence_audit.tsv was not produced (RUN_REFERENCE_EVIDENCE_AUDIT=0, or no truth provenance table)."))
    counts = {k: sum(1 for r in rows if r.get("audit_status") == k) for k in ("strong", "usable_with_caveats", "weak")}
    eligible = sum(1 for r in rows if r.get("headline_eligible") == "yes")
    chips = " ".join(f"<span class='rv-chip {cls}'>{counts[k]} {label}</span>" for k, label, cls in
                     (("strong", "strong", "rv-pass"), ("usable_with_caveats", "usable with caveats", "rv-warn"), ("weak", "weak", "rv-reject")))
    head = f"<p>{chips} of {len(rows)} isolates; {eligible} meet the headline reference rule.</p>"
    order = {"weak": 0, "usable_with_caveats": 1, "strong": 2}
    shown = sorted(rows, key=lambda r: (order.get(r.get("audit_status"), 3), r.get("sample", "")))[:40]
    body = "".join(f"<tr><td>{esc(r['sample'])}</td><td>{esc(r['audit_status'])}</td><td>{esc(r['reference_tier'])}</td>"
                   f"<td>{esc(r['evaluation_independence'])}</td><td>{esc(r['evidence_recorded'])}</td><td>{esc(r['audit_reasons'] or '-')}</td></tr>"
                   for r in shown)
    table = ("<div class='panel'><table><thead><tr><th>Isolate</th><th>Status</th><th>Tier</th><th>Independence</th><th>Evidence recorded</th>"
             f"<th>Reasons</th></tr></thead><tbody>{body}</tbody></table></div>")
    more = f"<p class='small'>Showing the {len(shown)} least trusted of {len(rows)}; the full table is benchmark.reference_evidence_audit.tsv.</p>" if len(rows) > len(shown) else ""
    return section("learn-refaudit", "Reference evidence", lead, head + table + more)


def inject(page, results_dir):
    r = lambda name: read_tsv(os.path.join(results_dir, name))  # noqa: E731
    candidates = r("assembly_candidates.tsv")
    ctx = {"results_dir": results_dir, "candidates": candidates, "status_rows": r("short_read_qc_status.tsv"), "scores": r("scores.tsv")}
    sections = (readqc_section(r("short_read_qc.tsv"), None, ctx) + assembly_section(candidates, ctx)
                + multiplicity_section(r("benchmark.candidate_multiplicity.tsv"), r("benchmark.candidates.tsv"),
                                       r("benchmark.candidate_intervals.tsv"))
                + refaudit_section(r("benchmark.reference_evidence_audit.tsv"))
                + stability_section(r("benchmark.ranking_stability.tsv"), r("benchmark.study_sensitivity.tsv"), r("benchmark.species_sensitivity.tsv")))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, CSS + qp.CSS + sections + anchor, 1)
        nav_anchor = "<a href='#recommendations'>Recommendations</a>"
        links = "".join(f"<a href='#{sid}'>{esc(label)}</a>" for sid, label in SECTIONS)
        page = page.replace(nav_anchor, links + nav_anchor, 1)
    return page
