#!/usr/bin/env python3
"""
report_amr_regions.py -- resistance-region comparison: does each tool keep the AMR genes AND the mobile context around them, on the right plasmid?

Counting resistance genes is not enough for surveillance. A gene recovered on the wrong plasmid, or recovered without the integron or insertion
sequences around it, can change a transmission conclusion. This section draws, for every resistance region of the truth, the genes and the
mobile context along the plasmid, with one lane per tool showing what that tool did to each gene:

  truth lane     resistance genes (colour = gene class) and the context features around them: insertion sequences, integrase / integron,
                 replicon, mobility and transfer genes, metal resistance (named by feature type and label; this is a label, not a new annotation)
  tool lanes     one mark per gene: correct plasmid, wrong plasmid, shared or unassigned contig, not recovered; an underline where the gene's
                 flanking context is also covered
  region verdict intact (every gene on the correct plasmid and every flank covered), partial, or lost, per tool and region

A resistance region is a group of truth AMR gene copies on one plasmid no more than --gap bp apart (default 10 kb), shown with padding. The numbers
come from the per-gene tables score_amr_placement.py already writes (results/<sample>/<tool>.amr_placement.tsv); nothing is rescored here, and no
score or ranking changes. A tool that does not bin (a classifier or reassembler) is attributed per record, so its "correct plasmid" means the
record points at the right plasmid, not that the plasmid was reconstructed; its verdict word is "attributed", never "intact".

Interactions (JavaScript; the page is complete and readable without it): choose a region; show or hide tools; filter gene classes; zoom and scroll;
hover or focus a gene or a mark to highlight the gene across every lane and read its details; click to pin the details. Colour is never the only
channel: placement is a mark shape and is also written in each tooltip and in the table under each region.

Called from build_html_report.py: inject(page, results_dir, data_dir). Standard library only.
"""
import csv
import html
import math
import os
import re

from report_svg import CLASS_COLOURS, CLASS_LABELS, OKABE_ITO, esc, num

TAB = chr(9)
SECTION_ID = "learn-amrregions"
PLACEMENTS = ("correct_plasmid", "wrong_plasmid", "shared_contig", "unassigned_contig", "not_recovered")
PLACEMENT_WORD = {"correct_plasmid": "correct plasmid", "wrong_plasmid": "wrong plasmid", "shared_contig": "shared contig",
                  "unassigned_contig": "unassigned contig", "not_recovered": "not recovered"}
GENE_PALETTE = [OKABE_ITO[k] for k in ("vermillion", "blue", "orange", "green", "purple", "sky", "yellow")]
CONTEXT_RULES = (
    (re.compile(r"^int[IiAa]?\d*$|integrase|integron|attc", re.I), "integrase"),
    (re.compile(r"^(tra|trb|vir|pil)[A-Za-z0-9]*$|conjug|relaxase|mobA|mpf", re.I), "transfer"),
    (re.compile(r"^(mer|cus|sil|pco|ars|czc|cop)[A-Za-z0-9]*$", re.I), "metal"),
)
FEATURE_KIND = {"insertion_sequence": "mobile", "is_element": "mobile", "transposon": "mobile", "replicon": "replication",
                "mob": "transfer", "mobility": "transfer"}
MAX_STATIC = 12
LEVELS = 4
CSS = """<style>
.ar{--ar-ink:currentColor}
.ar-bar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin:8px 0;font-size:.9em}
.ar-bar label{white-space:nowrap}
.ar-bar select{max-width:100%}
.ar-region{margin:14px 0;border:1px solid rgba(128,128,128,.35);border-radius:6px;padding:8px 10px}
.ar.ar-js .ar-region{display:none}.ar.ar-js .ar-region.ar-on{display:block}
.ar-scroll{overflow-x:auto}
.ar-region svg{display:block;min-width:100%}
.ar-gene,.ar-mark{cursor:pointer;outline:none}
.ar-gene:focus .ar-shape,.ar-mark:focus .ar-shape{stroke:currentColor;stroke-width:2.2}
.ar.ar-hl .ar-gene,.ar.ar-hl .ar-mark,.ar.ar-hl .ar-guide{opacity:.22}
.ar.ar-hl .ar-gene.hl,.ar.ar-hl .ar-mark.hl,.ar.ar-hl .ar-guide.hl{opacity:1}
.ar .ar-off{opacity:.15}
.ar-detail{min-height:3.2em;border-left:4px solid rgba(128,128,128,.5);padding:4px 10px;margin:6px 0;font-size:.9em;white-space:pre-line}
.ar-legend{display:flex;gap:12px;flex-wrap:wrap;font-size:.86em;margin:6px 0}.ar-legend span{display:inline-flex;align-items:center;gap:5px}
.ar table{border-collapse:collapse;font-size:.88em}.ar th,.ar td{border:1px solid rgba(128,128,128,.35);padding:3px 8px;text-align:right}
.ar th:first-child,.ar td:first-child{text-align:left}
.ar-chip{display:inline-block;padding:1px 8px;border-radius:10px;font-weight:700;font-size:.82em}
.ar-intact{background:#009E73;color:#fff}.ar-partial{background:#E69F00;color:#111}.ar-lost{background:#D55E00;color:#fff}.ar-attr{background:#56B4E9;color:#111}
</style>"""


def read_tsv(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


def integer(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def truthy(value):
    """True / False / None (not evaluated) for a yes-no cell."""
    v = (value or "").strip().lower()
    if v in ("1", "yes", "true", "y"):
        return True
    if v in ("0", "no", "false", "n"):
        return False
    return None


def context_class(kind, label):
    for pattern, cls in CONTEXT_RULES:
        if pattern.search(label or ""):
            return cls
    return FEATURE_KIND.get((kind or "").lower())


def gene_colours(classes):
    """A stable colour per gene class: the same class always gets the same colour on every region."""
    return {c: GENE_PALETTE[i % len(GENE_PALETTE)] for i, c in enumerate(sorted(set(classes)))}


def make_regions(genes, features, gap=10000, pad=1500):
    """genes: {(sample, copy_id): {...with sequence_id, start, end}}; features: {(sample, sequence_id): [feature rows]}. Returns regions."""
    by_seq = {}
    for g in genes.values():
        by_seq.setdefault((g["sample"], g["sequence_id"]), []).append(g)
    regions = []
    for (sample, seq), items in sorted(by_seq.items()):
        items.sort(key=lambda g: (g["start"], g["end"]))
        groups = [[items[0]]]
        for g in items[1:]:
            if g["start"] - max(x["end"] for x in groups[-1]) <= gap:
                groups[-1].append(g)
            else:
                groups.append([g])
        for k, group in enumerate(groups, 1):
            lo, hi = max(0, min(g["start"] for g in group) - pad), max(g["end"] for g in group) + pad
            context = []
            for f in features.get((sample, seq), []):
                s, e = integer(f.get("start")), integer(f.get("end"))
                if s is None or e is None or e < lo or s > hi:
                    continue
                cls = context_class(f.get("feature_type"), f.get("label"))
                if cls:
                    context.append({"start": max(s, lo), "end": min(e, hi), "label": f.get("label") or f.get("feature_type") or "", "cls": cls,
                                    "kind": f.get("feature_type") or ""})
            regions.append({"id": f"{sample}|{seq}|{k}", "sample": sample, "sequence_id": seq, "k": k, "start": lo, "end": hi, "genes": group,
                            "context": sorted(context, key=lambda c: (c["start"], c["end"]))})
    return regions


def verdict(rows, mode):
    """(word, class) for one tool on one region from its per-gene placement rows."""
    if not rows:
        return "not scored", ""
    placements = [r.get("placement") for r in rows]
    correct = sum(1 for p in placements if p == "correct_plasmid")
    flank_bad = any(truthy(r.get("flank_covered")) is False for r in rows)
    if correct == len(rows) and not flank_bad:
        return ("intact", "ar-intact") if mode == "bin_matching" else ("attributed", "ar-attr")
    if correct == 0:
        return "lost", "ar-lost"
    return "partial", "ar-partial"


def load(results_dir, data_dir, gap=10000, pad=1500):
    """-> (regions, tools, per) where per[(sample, tool)] = {copy_id: row}."""
    genes, per, tools, modes = {}, {}, set(), {}
    for sample in sorted(d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))):
        folder = os.path.join(results_dir, sample)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".amr_placement.tsv"):
                continue
            tool = name[:-len(".amr_placement.tsv")]
            rows = read_tsv(os.path.join(folder, name))
            if not rows:
                continue
            tools.add(tool)
            per[(sample, tool)] = {}
            for r in rows:
                cid = r.get("copy_id")
                s, e = integer(r.get("start")), integer(r.get("end"))
                if not cid or s is None or e is None or not r.get("sequence_id"):
                    continue
                per[(sample, tool)][cid] = r
                modes[tool] = r.get("attribution_mode") or modes.get(tool, "bin_matching")
                genes.setdefault((sample, cid), {"sample": sample, "copy_id": cid, "name": r.get("gene_name") or cid, "cls": r.get("gene_class") or "other",
                                                 "sequence_id": r["sequence_id"], "start": s, "end": e})
    features = {}
    for base in (data_dir, results_dir):
        if not base:
            continue
        for sample in {s for s, _ in genes}:
            if any(k[0] == sample for k in features):
                continue
            rows = read_tsv(os.path.join(base, sample, "truth_features.tsv"))
            for f in rows or []:
                features.setdefault((sample, f.get("sequence_id")), []).append(f)
    return make_regions(genes, features, gap, pad), sorted(tools), per, modes


# ---------------------------------------------------------------------------------------------- drawing
GLYPH = {"correct_plasmid": "#009E73", "wrong_plasmid": "#D55E00", "shared_contig": "#E69F00", "unassigned_contig": "#999999", "not_recovered": "#000000"}


def glyph(cx, cy, placement, flank, extra, title):
    """A mark whose SHAPE says what happened (colour repeats it): dot, triangle, half-filled dot, open dot, cross."""
    c = GLYPH.get(placement, "#999999")
    r = 6
    if placement == "correct_plasmid":
        shape = f"<circle class='ar-shape' cx='{num(cx)}' cy='{num(cy)}' r='{r}' fill='{c}'/>"
    elif placement == "wrong_plasmid":
        shape = f"<path class='ar-shape' d='M{num(cx)} {num(cy - r)} L{num(cx + r)} {num(cy + r)} L{num(cx - r)} {num(cy + r)} Z' fill='{c}'/>"
    elif placement == "shared_contig":
        shape = (f"<circle class='ar-shape' cx='{num(cx)}' cy='{num(cy)}' r='{r}' fill='none' stroke='{c}' stroke-width='1.6'/>"
                 f"<path d='M{num(cx - r)} {num(cy)} A{r} {r} 0 0 0 {num(cx + r)} {num(cy)} Z' fill='{c}'/>")
    elif placement == "unassigned_contig":
        shape = f"<circle class='ar-shape' cx='{num(cx)}' cy='{num(cy)}' r='{r}' fill='none' stroke='{c}' stroke-width='1.8'/>"
    else:
        shape = (f"<path class='ar-shape' d='M{num(cx - r)} {num(cy - r)} L{num(cx + r)} {num(cy + r)} M{num(cx + r)} {num(cy - r)} L{num(cx - r)} {num(cy + r)}' "
                 f"stroke='{c}' stroke-width='2.2' fill='none'/>")
    under = ""
    if flank is True:
        under = f"<line x1='{num(cx - 8)}' y1='{num(cy + 10)}' x2='{num(cx + 8)}' y2='{num(cy + 10)}' stroke='{OKABE_ITO['blue']}' stroke-width='2.4'/>"
    return f"<g class='ar-mark' tabindex='0' {extra}><title>{esc(title)}</title>{shape}{under}</g>"


def ticks(lo, hi):
    span = max(hi - lo, 1)
    raw = span / 8
    step = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if step * m >= raw:
            step *= m
            break
    first = math.ceil(lo / step) * step
    out, t = [], first
    while t <= hi:
        out.append(t)
        t += step
    return out, step


def kb(value):
    return f"{value / 1000:.1f} kb" if value >= 1000 else f"{int(value)} bp"


def region_info(region, gene, tools, per, modes):
    lines = [f"{gene['name']} ({gene['cls']}), copy {gene['copy_id']}", f"{region['sequence_id']}:{gene['start']}-{gene['end']}"]
    for t in tools:
        row = per.get((region["sample"], t), {}).get(gene["copy_id"])
        if row is None:
            lines.append(f"{t}: not scored")
        else:
            flank = truthy(row.get("flank_covered"))
            lines.append(f"{t}: {PLACEMENT_WORD.get(row.get('placement'), row.get('placement') or 'unknown')}"
                         + (", flank covered" if flank else (", flank not covered" if flank is False else "")))
    return "\n".join(lines)


def render_region(region, tools, per, modes, colours, index):
    W, left, right = 1000, 170, 20
    plot = W - left - right
    lo, hi = region["start"], region["end"]
    span = max(hi - lo, 1)
    X = lambda p: left + (p - lo) / span * plot  # noqa: E731
    genes = region["genes"]
    label_levels = [-1e9] * LEVELS
    y_label0 = 8
    y_truth = y_label0 + LEVELS * 13 + 6
    y_ctx = y_truth + 30
    y_tool0 = y_ctx + 22
    lane = 26
    H = y_tool0 + lane * len(tools) + 34
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' role='img' aria-label='Resistance region {esc(region['sequence_id'])} "
           f"{kb(lo)} to {kb(hi)} in {esc(region['sample'])}' preserveAspectRatio='xMinYMin meet'>"]
    out.append(f"<text x='8' y='{y_truth + 15}' font-size='11' font-weight='bold' fill='currentColor' font-family='Arial,sans-serif'>Truth genes</text>")
    out.append(f"<text x='8' y='{y_ctx + 9}' font-size='10' fill='currentColor' font-family='Arial,sans-serif'>Context</text>")
    out.append(f"<line x1='{left}' y1='{y_truth + 22}' x2='{W - right}' y2='{y_truth + 22}' stroke='#888' stroke-width='1'/>")
    for g in sorted(genes, key=lambda g: g["start"]):
        x0, x1 = X(g["start"]), max(X(g["end"]), X(g["start"]) + 5)
        col = colours[g["cls"]]
        info = region_info(region, g, tools, per, modes)
        out.append(f"<g class='ar-gene' tabindex='0' data-copy='{esc(g['copy_id'])}' data-class='{esc(g['cls'])}' data-info='{esc(info)}'>"
                   f"<title>{esc(info)}</title><rect class='ar-shape' x='{num(x0)}' y='{y_truth}' width='{num(x1 - x0)}' height='20' rx='3' fill='{col}' "
                   f"stroke='#333' stroke-width='.6'/></g>")
        width_label = 6.0 * len(g["name"]) + 6
        for lv in range(LEVELS):
            if label_levels[lv] + 4 < x0:
                label_levels[lv] = x0 + width_label
                ly = y_label0 + (LEVELS - 1 - lv) * 13 + 10
                out.append(f"<text x='{num(x0)}' y='{ly}' font-size='10' font-style='italic' fill='currentColor' font-family='Arial,sans-serif'>{esc(g['name'])}</text>")
                out.append(f"<line x1='{num(x0)}' y1='{ly + 2}' x2='{num(x0)}' y2='{y_truth}' stroke='#aaa' stroke-width='.5'/>")
                break
    for c in region["context"]:
        x0, x1 = X(c["start"]), max(X(c["end"]), X(c["start"]) + 2)
        out.append(f"<rect x='{num(x0)}' y='{y_ctx}' width='{num(x1 - x0)}' height='10' rx='2' fill='{CLASS_COLOURS.get(c['cls'], '#8c8c8c')}' "
                   f"stroke='#333' stroke-width='.4'><title>{esc(CLASS_LABELS.get(c['cls'], c['cls']))}: {esc(c['label'])} "
                   f"({esc(c['kind'])}) {c['start']}-{c['end']}</title></rect>")
    for i, tool in enumerate(tools):
        y = y_tool0 + i * lane
        rows = per.get((region["sample"], tool), {})
        mine = [rows.get(g["copy_id"]) for g in genes]
        word, cls = verdict([r for r in mine if r], modes.get(tool, "bin_matching"))
        out.append(f"<g class='ar-lane' data-tool='{esc(tool)}'><rect x='{left}' y='{y}' width='{plot}' height='{lane - 3}' fill='rgba(128,128,128,.07)'/>"
                   f"<text x='8' y='{y + 15}' font-size='11' fill='currentColor' font-family='Arial,sans-serif'>{esc(tool)}</text>"
                   f"<text x='{left - 6}' y='{y + 15}' font-size='9' text-anchor='end' fill='currentColor' font-family='Arial,sans-serif'>{esc(word)}</text>")
        for g, row in zip(genes, mine):
            cx = (X(g["start"]) + max(X(g["end"]), X(g["start"]) + 5)) / 2
            out.append(f"<line class='ar-guide' data-copy='{esc(g['copy_id'])}' x1='{num(cx)}' y1='{y_truth + 20}' x2='{num(cx)}' y2='{y + 8}' "
                       f"stroke='#bbb' stroke-width='.6' stroke-dasharray='2 2'/>")
            if row is None:
                out.append(f"<g class='ar-mark' tabindex='0' data-copy='{esc(g['copy_id'])}' data-class='{esc(g['cls'])}' data-info='{esc(region_info(region, g, tools, per, modes))}'>"
                           f"<title>{esc(tool)}: not scored</title><circle class='ar-shape' cx='{num(cx)}' cy='{y + 10}' r='3' fill='#bbb'/></g>")
                continue
            placement = row.get("placement") or "not_recovered"
            flank = truthy(row.get("flank_covered"))
            title = f"{tool}: {g['name']} {PLACEMENT_WORD.get(placement, placement)}" + (" (flank covered)" if flank else (" (flank not covered)" if flank is False else ""))
            out.append(glyph(cx, y + 10, placement, flank, f"data-copy='{esc(g['copy_id'])}' data-class='{esc(g['cls'])}' data-info='{esc(region_info(region, g, tools, per, modes))}'", title))
        out.append("</g>")
    axis_y = y_tool0 + lane * len(tools) + 6
    out.append(f"<line x1='{left}' y1='{axis_y}' x2='{W - right}' y2='{axis_y}' stroke='#666' stroke-width='1'/>")
    tick_positions, _step = ticks(lo, hi)
    for t in tick_positions:
        out.append(f"<line x1='{num(X(t))}' y1='{axis_y}' x2='{num(X(t))}' y2='{axis_y + 4}' stroke='#666'/>"
                   f"<text x='{num(X(t))}' y='{axis_y + 15}' font-size='9' text-anchor='middle' fill='currentColor' font-family='Arial,sans-serif'>{kb(t)}</text>")
    out.append("</svg>")
    # per-region table (the numbers behind the picture, readable without JavaScript)
    body = []
    for tool in tools:
        rows = [per.get((region["sample"], tool), {}).get(g["copy_id"]) for g in genes]
        scored = [r for r in rows if r]
        if not scored:
            body.append(f"<tr><td>{esc(tool)}</td><td colspan='6'>not scored on this isolate</td></tr>")
            continue
        count = lambda p: sum(1 for r in scored if r.get("placement") == p)  # noqa: E731
        flank_ok = sum(1 for r in scored if truthy(r.get("flank_covered")) is True)
        flank_n = sum(1 for r in scored if truthy(r.get("flank_covered")) is not None)
        word, cls = verdict(scored, modes.get(tool, "bin_matching"))
        body.append(f"<tr><td>{esc(tool)}</td><td>{len(genes)}</td><td>{count('correct_plasmid')}</td><td>{count('wrong_plasmid')}</td>"
                    f"<td>{count('shared_contig') + count('unassigned_contig')}</td><td>{count('not_recovered')}</td>"
                    f"<td>{flank_ok}/{flank_n if flank_n else '-'}</td><td><span class='ar-chip {cls}'>{esc(word)}</span></td></tr>")
    table = ("<details><summary>Numbers for this region</summary><div class='ar-scroll'><table><thead><tr><th>Tool</th><th>Genes</th><th>Correct plasmid</th>"
             "<th>Wrong plasmid</th><th>Shared or unassigned</th><th>Not recovered</th><th>Flank covered</th><th>Verdict</th></tr></thead><tbody>"
             + "".join(body) + "</tbody></table></div></details>")
    title = (f"<h3>{esc(region['sample'])} &middot; {esc(region['sequence_id'])} &middot; region {region['k']} "
             f"<small>({len(genes)} gene{'s' if len(genes) != 1 else ''}, {kb(hi - lo)})</small></h3>")
    return (f"<div class='ar-region' data-region='{esc(region['id'])}' data-label='{esc(region['sample'])} / {esc(region['sequence_id'])} / region {region['k']}'>"
            f"{title}<div class='ar-scroll'>{''.join(out)}</div>{table}</div>")


def summary_chart(regions, tools, per, modes):
    """Per tool: share of regions intact (or attributed), partial and lost."""
    counts = {}
    for t in tools:
        c = {"intact": 0, "partial": 0, "lost": 0}
        n = 0
        for r in regions:
            scored = [per.get((r["sample"], t), {}).get(g["copy_id"]) for g in r["genes"]]
            scored = [x for x in scored if x]
            if not scored:
                continue
            word, _ = verdict(scored, modes.get(t, "bin_matching"))
            c["intact" if word in ("intact", "attributed") else word] += 1
            n += 1
        counts[t] = (c, n)
    W, left, row_h = 760, 150, 24
    H = len(tools) * row_h + 30
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' role='img' aria-label='Resistance regions by verdict for each tool'>"]
    for i, t in enumerate(tools):
        c, n = counts[t]
        y = 10 + i * row_h
        out.append(f"<text x='6' y='{y + 14}' font-size='11' fill='currentColor' font-family='Arial,sans-serif'>{esc(t)}</text>")
        x = left
        for key, colour, mark in (("intact", "#009E73", ""), ("partial", "#E69F00", ""), ("lost", "#D55E00", "")):
            w = (W - left - 90) * c[key] / n if n else 0
            if w > 0:
                out.append(f"<rect x='{num(x)}' y='{y}' width='{num(w)}' height='18' fill='{colour}'><title>{esc(t)}: {c[key]} of {n} regions {key}</title></rect>")
                if w > 26:
                    out.append(f"<text x='{num(x + w / 2)}' y='{y + 13}' font-size='10' text-anchor='middle' font-weight='bold' fill='{'#111' if key == 'partial' else '#fff'}' "
                               f"font-family='Arial,sans-serif'>{c[key]}</text>")
            x += w
        out.append(f"<text x='{W - 84}' y='{y + 14}' font-size='10' fill='currentColor' font-family='Arial,sans-serif'>{n} region{'s' if n != 1 else ''}</text>")
    out.append("</svg>")
    return "".join(out), counts


def funnel(regions, tools, per, modes):
    """Where resistance information is lost, per tool: genes -> recovered -> on the correct plasmid -> flank covered -> in an intact region."""
    rows = []
    for t in tools:
        genes = rec = correct = flank = intact = regs = 0
        for r in regions:
            scored = [per.get((r["sample"], t), {}).get(g["copy_id"]) for g in r["genes"]]
            scored = [x for x in scored if x]
            if not scored:
                continue
            regs += 1
            genes += len(scored)
            rec += sum(1 for x in scored if x.get("placement") != "not_recovered")
            correct += sum(1 for x in scored if x.get("placement") == "correct_plasmid")
            flank += sum(1 for x in scored if x.get("placement") == "correct_plasmid" and truthy(x.get("flank_covered")) is True)
            word, _ = verdict(scored, modes.get(t, "bin_matching"))
            intact += 1 if word in ("intact", "attributed") else 0
        rows.append((t, genes, rec, correct, flank, intact, regs))

    def cell(value, total):
        share = 100 * value / total if total else 0
        return (f"<td><div style='position:relative;min-width:84px;height:1.5em;background:rgba(128,128,128,.12);border-radius:3px'>"
                f"<span style='position:absolute;left:0;top:0;bottom:0;width:{share:.0f}%;background:rgba(0,114,178,.38);border-radius:3px'></span>"
                f"<b style='position:relative;padding:0 6px;font-size:.88em;line-height:1.5em'>{value} ({share:.0f}%)</b></div></td>")
    body = "".join(f"<tr><td>{esc(t)}</td><td>{g}</td>{cell(rc, g)}{cell(co, g)}{cell(fl, g)}{cell(it, rg)}</tr>" for t, g, rc, co, fl, it, rg in rows)
    return ("<details open><summary>Where resistance information is lost</summary><div class='ar-scroll'><table><thead><tr><th>Tool</th><th>Truth gene copies</th>"
            "<th>Recovered (any placement)</th><th>On the correct plasmid</th><th>Correct plasmid and flank covered</th><th>Regions intact</th></tr></thead><tbody>"
            + body + "</tbody></table></div><p class='small'>Each column keeps only what the one before kept: a gene must be recovered before it can be on the correct "
            "plasmid, and on the correct plasmid before its flank counts. The last column counts regions, not genes.</p></details>"), rows


SCRIPT = """<script>
(function(){
var root=document.getElementById('learn-amrregions-body');if(!root)return;
root.classList.add('ar-js');
var regions=[].slice.call(root.querySelectorAll('.ar-region')),sel=root.querySelector('.ar-select'),detail=root.querySelector('.ar-detail'),pinned=null;
function show(i){regions.forEach(function(r,k){r.classList.toggle('ar-on',k===i)});if(sel)sel.value=String(i);clear()}
if(sel){sel.addEventListener('change',function(){show(parseInt(sel.value,10)||0)})}
var prev=root.querySelector('.ar-prev'),next=root.querySelector('.ar-next');
function cur(){var k=regions.findIndex(function(r){return r.classList.contains('ar-on')});return k<0?0:k}
if(prev)prev.addEventListener('click',function(){show((cur()+regions.length-1)%regions.length)});
if(next)next.addEventListener('click',function(){show((cur()+1)%regions.length)});
root.querySelectorAll('.ar-tool').forEach(function(cb){cb.addEventListener('change',function(){
  root.querySelectorAll('.ar-lane[data-tool="'+cb.value+'"]').forEach(function(l){l.style.display=cb.checked?'':'none'})})});
root.querySelectorAll('.ar-cls').forEach(function(cb){cb.addEventListener('change',function(){
  root.querySelectorAll('[data-class="'+cb.value+'"]').forEach(function(g){g.classList.toggle('ar-off',!cb.checked)})})});
var zoom=root.querySelector('.ar-zoom');
if(zoom){zoom.addEventListener('input',function(){root.querySelectorAll('.ar-region svg').forEach(function(s){s.style.width=(parseFloat(zoom.value)*100)+'%'})})}
function clear(){pinned=null;root.classList.remove('ar-hl');root.querySelectorAll('.hl').forEach(function(e){e.classList.remove('hl')});if(detail)detail.textContent='Hover or focus a gene or a mark to read its details; click to keep them.'}
function light(el,keep){var c=el.getAttribute('data-copy');if(!c)return;root.classList.add('ar-hl');
  el.closest('.ar-region').querySelectorAll('[data-copy="'+c+'"]').forEach(function(e){e.classList.add('hl')});
  if(detail)detail.textContent=el.getAttribute('data-info')||''}
function unlight(){if(pinned)return;root.classList.remove('ar-hl');root.querySelectorAll('.hl').forEach(function(e){e.classList.remove('hl')})}
root.addEventListener('mouseover',function(e){var t=e.target.closest('.ar-gene,.ar-mark');if(t&&!pinned)light(t)});
root.addEventListener('mouseout',function(e){if(e.target.closest('.ar-gene,.ar-mark'))unlight()});
root.addEventListener('focusin',function(e){var t=e.target.closest('.ar-gene,.ar-mark');if(t&&!pinned)light(t)});
root.addEventListener('focusout',function(e){if(e.target.closest('.ar-gene,.ar-mark'))unlight()});
root.addEventListener('click',function(e){var t=e.target.closest('.ar-gene,.ar-mark');
  if(!t){return}
  if(pinned===t){clear();return}
  root.querySelectorAll('.hl').forEach(function(x){x.classList.remove('hl')});pinned=null;light(t);pinned=t});
root.addEventListener('keydown',function(e){if(e.key==='Escape')clear()});
show(0);
})();
</script>"""


def section(regions, tools, per, modes, gap):
    lead = ("Counting resistance genes is not enough: a gene on the wrong plasmid, or without the integron or insertion sequences around it, can change "
            "a transmission conclusion. Each region below is a group of truth resistance genes on one plasmid (no more than "
            f"{gap // 1000} kb apart). <strong>Descriptive: it re-draws what the AMR placement scores already say and changes no score.</strong>")
    if not regions:
        return (f"<section id='{SECTION_ID}' class='ar'><h2>AMR regions</h2><p class='lead'>{lead}</p><div class='insight caution'><p>Not run: no "
                "results/&lt;sample&gt;/&lt;tool&gt;.amr_placement.tsv exists. It needs curated AMR truth (truth_amr.tsv) and RUN_AMR_PLACEMENT=1; without it the "
                "report cannot say where each resistance gene went.</p></div></section>")
    classes = sorted({g["cls"] for r in regions for g in r["genes"]})
    colours = gene_colours(classes)
    chart, counts = summary_chart(regions, tools, per, modes)
    funnel_html, _funnel_rows = funnel(regions, tools, per, modes)
    legend = ("<div class='ar-legend'>" + "".join(f"<span><i style='display:inline-block;width:12px;height:12px;border-radius:2px;background:{colours[c]}'></i>{esc(c)}</span>" for c in classes)
              + "</div><div class='ar-legend'>"
              "<span><svg width='14' height='14'><circle cx='7' cy='7' r='6' fill='#009E73'/></svg> correct plasmid</span>"
              "<span><svg width='14' height='14'><path d='M7 1 L13 13 L1 13 Z' fill='#D55E00'/></svg> wrong plasmid</span>"
              "<span><svg width='14' height='14'><circle cx='7' cy='7' r='6' fill='none' stroke='#E69F00' stroke-width='1.6'/><path d='M1 7 A6 6 0 0 0 13 7 Z' fill='#E69F00'/></svg> shared contig</span>"
              "<span><svg width='14' height='14'><circle cx='7' cy='7' r='5.5' fill='none' stroke='#999' stroke-width='1.8'/></svg> unassigned contig</span>"
              "<span><svg width='14' height='14'><path d='M1 1 L13 13 M13 1 L1 13' stroke='#000' stroke-width='2.2'/></svg> not recovered</span>"
              f"<span><svg width='18' height='6'><line x1='1' y1='3' x2='17' y2='3' stroke='{OKABE_ITO['blue']}' stroke-width='2.4'/></svg> flank covered</span></div>")
    ctx = "".join(f"<span><i style='display:inline-block;width:12px;height:8px;border-radius:2px;background:{CLASS_COLOURS[k]}'></i>{esc(CLASS_LABELS[k])}</span>"
                  for k in ("mobile", "integrase", "transfer", "metal", "replication"))
    shown = regions
    options = "".join(f"<option value='{i}'>{esc(r['sample'])} / {esc(r['sequence_id'])} / region {r['k']} ({len(r['genes'])} genes)</option>" for i, r in enumerate(shown))
    controls = ("<div class='ar-bar'><label>Region <select class='ar-select' aria-label='Choose a resistance region'>" + options + "</select></label>"
                "<button type='button' class='ar-prev' aria-label='Previous region'>&larr;</button><button type='button' class='ar-next' aria-label='Next region'>&rarr;</button>"
                "<label>Zoom <input type='range' class='ar-zoom' min='1' max='6' step='0.25' value='1' aria-label='Zoom'></label></div>"
                "<div class='ar-bar'><strong>Tools</strong>" + "".join(f"<label><input type='checkbox' class='ar-tool' value='{esc(t)}' checked> {esc(t)}</label>" for t in tools) + "</div>"
                "<div class='ar-bar'><strong>Gene classes</strong>" + "".join(f"<label><input type='checkbox' class='ar-cls' value='{esc(c)}' checked> {esc(c)}</label>" for c in classes) + "</div>")
    blocks = "".join(render_region(r, tools, per, modes, colours, i) for i, r in enumerate(shown))
    n_att = [t for t in tools if modes.get(t, "bin_matching") != "bin_matching"]
    foot = ("<p class='small'>Tools that do not bin (" + ", ".join(esc(t) for t in n_att) + ") are attributed record by record: their &ldquo;correct plasmid&rdquo; means the record "
            "points at the right plasmid, not that the plasmid was reconstructed, so their verdict word is &ldquo;attributed&rdquo;.</p>") if n_att else ""
    note = (f"<p class='small'>No JavaScript: every region is listed below. With JavaScript, choose one region at a time.</p>" if len(shown) > 1 else "")
    return (f"<section id='{SECTION_ID}' class='ar'><h2>AMR regions</h2><p class='lead'>{lead}</p>"
            f"<div id='learn-amrregions-body' class='ar'><figure class='binfig'><div class='ar-scroll'>{chart}</div>"
            f"<figcaption class='small'>Share of resistance regions each tool kept intact, partly kept or lost ({len(regions)} region{'s' if len(regions) != 1 else ''} in the truth).</figcaption></figure>"
            f"{funnel_html}{legend}<div class='ar-legend'><strong>Context</strong>{ctx}</div>{controls}"
            f"<div class='ar-detail' aria-live='polite'>Hover or focus a gene or a mark to read its details; click to keep them.</div>{blocks}{foot}{note}</div>{SCRIPT}</section>")


def inject(page, results_dir, data_dir=None, gap=10000):
    try:
        regions, tools, per, modes = load(results_dir, data_dir, gap)
    except OSError:
        regions, tools, per, modes = [], [], {}, {}
    body = CSS + section(regions, tools, per, modes, gap)
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, body + anchor, 1)
        nav = "<a href='#recommendations'>Recommendations</a>"
        page = page.replace(nav, f"<a href='#{SECTION_ID}'>AMR regions</a>" + nav, 1)
    return page
