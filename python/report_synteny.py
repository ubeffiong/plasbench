#!/usr/bin/env python3
"""
report_synteny.py -- synteny ribbons: how each tool's records sit on a truth plasmid, in order and orientation.

A tool can cover a plasmid completely and still get it wrong: the plasmid is cut into pieces, pieces are in the wrong order, a piece is inverted, a piece
appears twice. Coverage and identity do not show that. This section draws, for one truth plasmid at a time, the plasmid as a bar along the top and each
tool's predicted records laid out along the bottom, with a ribbon for every retained alignment block joining the stretch of plasmid to the stretch of
record it matches:

  forward ribbon   orange, straight       reverse ribbon   blue, crossed (the record is inverted relative to the plasmid)
  ribbon opacity   identity of the block (about 99% and above, 95 to 99%, below 95%)
  record order     records are placed left to right by where they land on the plasmid, so a perfect reconstruction is a set of parallel ribbons and a
                   rearrangement shows as crossing ribbons

Data: results/<sample>/visualization/alignment_blocks.json (build_visualization_data.py): the largest retained primary alignment blocks of every tool, with
query and target coordinates, strand, matches and block length. Nothing is rescored; no score changes. Blocks beyond the cap per lane are not drawn and the
count of those left out is shown.

Interactions (JavaScript; without it every view is listed and readable): choose a sample and plasmid, show or hide tools, show forward or reverse blocks,
raise the minimum identity, zoom and scroll, hover or focus a ribbon to highlight it with its record and read its coordinates, click to pin the details.

Called from build_html_report.py: inject(page, results_dir). Standard library only.
"""
import json
import os

from report_svg import esc, num

SECTION_ID = "learn-synteny"
FORWARD, REVERSE = "#E69F00", "#0072B2"
LANE_TOP, LANE_H, LABEL_W = 14, 92, 150
MAX_VIEWS, MAX_LANES, MAX_RIBBONS = 60, 8, 150
BAR_Y, RIB_TOP, RIB_BOT, REC_Y, REC_H = 8, 20, 62, 62, 14
CSS = """<style>
.sy-bar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin:8px 0;font-size:.9em}.sy-bar label{white-space:nowrap}
.sy-view{margin:12px 0;border:1px solid rgba(128,128,128,.35);border-radius:6px;padding:8px 10px}
.sy.sy-js .sy-view{display:none}.sy.sy-js .sy-view.sy-on{display:block}
.sy-scroll{overflow-x:auto}.sy-view svg{display:block;min-width:100%}
.sy-rib,.sy-rec{cursor:pointer;outline:none}
.sy-rib:focus .sy-sh,.sy-rib.hl .sy-sh{stroke:currentColor;stroke-width:1.6}
.sy.sy-hl .sy-rib,.sy.sy-hl .sy-rec{opacity:.18}.sy.sy-hl .sy-rib.hl,.sy.sy-hl .sy-rec.hl{opacity:1}
.sy-detail{min-height:3.2em;border-left:4px solid rgba(128,128,128,.5);padding:4px 10px;margin:6px 0;font-size:.9em;white-space:pre-line}
.sy-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.86em;margin:6px 0}.sy-legend span{display:inline-flex;align-items:center;gap:5px}
.sy table{border-collapse:collapse;font-size:.88em}.sy th,.sy td{border:1px solid rgba(128,128,128,.35);padding:3px 8px;text-align:right}.sy th:first-child,.sy td:first-child{text-align:left}
</style>"""


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def identity(block):
    length = block.get("block_length") or 0
    return (block.get("matches") or 0) / length if length else None


def opacity(ident):
    if ident is None:
        return 0.4
    return 0.78 if ident >= 0.99 else (0.55 if ident >= 0.95 else 0.34)


def kb(value):
    return f"{value / 1000:.1f} kb" if value >= 1000 else f"{int(value)} bp"


def lane_model(tool, blocks, plasmid):
    """Records ordered by where they land on the plasmid, with the blocks that join them; None when the tool has no block on this plasmid."""
    mine = [b for b in blocks if b.get("target") == plasmid and str(b.get("molecule_type", "PLASMID")).upper() == "PLASMID"
            and all(isinstance(b.get(k), int) for k in ("query_start", "query_end", "target_start", "target_end", "query_length"))]
    if not mine:
        return None
    records = {}
    for b in mine:
        r = records.setdefault(b["record_id"], {"id": b["record_id"], "length": b["query_length"], "blocks": []})
        r["blocks"].append(b)
    ordered = sorted(records.values(), key=lambda r: (sum((b["target_start"] + b["target_end"]) / 2 * (b["block_length"] or 1) for b in r["blocks"]) /
                                                      max(sum((b["block_length"] or 1) for b in r["blocks"]), 1), r["id"]))
    shown = sorted(mine, key=lambda b: -(b["block_length"] or 0))[:MAX_RIBBONS]
    return {"tool": tool, "records": ordered, "blocks": mine, "shown": {id(b) for b in shown}, "omitted": len(mine) - len(shown),
            "covered": sum(b["target_end"] - b["target_start"] for b in mine), "reverse": sum(1 for b in mine if b.get("strand") == "-")}


def render_view(vid, sample, plasmid, length, lanes, default_on):
    W = 1000
    plot = W - LABEL_W - 20
    X = lambda p: LABEL_W + p / max(length, 1) * plot  # noqa: E731
    H = LANE_TOP + len(lanes) * LANE_H + 30
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' role='img' aria-label='Synteny ribbons for plasmid {esc(plasmid)} in {esc(sample)}' "
           "preserveAspectRatio='xMinYMin meet'>"]
    for i, lane in enumerate(lanes):
        y0 = LANE_TOP + i * LANE_H
        hidden = "" if lane["tool"] in default_on else " style='display:none'"
        out.append(f"<g class='sy-lane' data-tool='{esc(lane['tool'])}'{hidden}>")
        out.append(f"<text x='6' y='{y0 + 22}' font-size='11' font-weight='bold' fill='currentColor' font-family='Arial,sans-serif'>{esc(lane['tool'])}</text>"
                   f"<text x='6' y='{y0 + 36}' font-size='9' fill='currentColor' font-family='Arial,sans-serif'>{len(lane['records'])} record{'s' if len(lane['records']) != 1 else ''}, "
                   f"{lane['reverse']} reversed</text>")
        out.append(f"<rect x='{LABEL_W}' y='{y0 + BAR_Y}' width='{num(plot)}' height='10' fill='#888' opacity='.55'><title>{esc(plasmid)}, {kb(length)}</title></rect>")
        total_q = sum(r["length"] for r in lane["records"]) or 1
        gap = 5
        scale = max(plot - gap * (len(lane["records"]) - 1), 10) / total_q
        x, spans = LABEL_W, {}
        for r in lane["records"]:
            w = max(r["length"] * scale, 2)
            spans[r["id"]] = (x, scale)
            info = f"{r['id']}\n{kb(r['length'])}, {len(r['blocks'])} aligned block(s) on this plasmid\n{lane['tool']}"
            out.append(f"<g class='sy-rec' tabindex='0' data-rec='{esc(vid)}:{i}:{esc(r['id'])}' data-info='{esc(info)}'><title>{esc(info)}</title>"
                       f"<rect class='sy-sh' x='{num(x)}' y='{y0 + REC_Y}' width='{num(w)}' height='{REC_H}' rx='2' fill='#bbb' stroke='#555' stroke-width='.6'/></g>")
            x += w + gap
        shown = [b for b in lane["blocks"] if id(b) in lane["shown"]]
        for b in sorted(shown, key=lambda b: -(b["block_length"] or 0)):
            rx, sc = spans[b["record_id"]]
            t0, t1 = X(b["target_start"]), X(b["target_end"])
            q0, q1 = rx + b["query_start"] * sc, rx + b["query_end"] * sc
            ident = identity(b)
            rev = b.get("strand") == "-"
            pts = (f"{num(t0)},{y0 + RIB_TOP} {num(t1)},{y0 + RIB_TOP} {num(q0 if rev else q1)},{y0 + RIB_BOT} {num(q1 if rev else q0)},{y0 + RIB_BOT}")
            ident_text = f"{ident * 100:.1f}%" if ident is not None else "n/a"
            info = (f"{lane['tool']}: {b['record_id']} {'reverse' if rev else 'forward'} block\nplasmid {b['target_start']}-{b['target_end']} "
                    f"({kb(b['target_end'] - b['target_start'])})\nrecord {b['query_start']}-{b['query_end']}\nidentity {ident_text}, mapq {b.get('mapq', 'n/a')}")
            out.append(f"<g class='sy-rib' tabindex='0' data-strand='{'-' if rev else '+'}' data-ident='{num(ident if ident is not None else 0, 4)}' "
                       f"data-rec='{esc(vid)}:{i}:{esc(b['record_id'])}' data-info='{esc(info)}'><title>{esc(info)}</title>"
                       f"<polygon class='sy-sh' points='{pts}' fill='{REVERSE if rev else FORWARD}' fill-opacity='{opacity(ident)}' stroke='none'/></g>")
        if lane["omitted"]:
            out.append(f"<text x='{W - 22}' y='{y0 + 34}' font-size='9' text-anchor='end' fill='currentColor' font-family='Arial,sans-serif'>{lane['omitted']} smaller block(s) not drawn</text>")
        out.append("</g>")
    out.append("</svg>")
    body = "".join(
        f"<tr><td>{esc(l['tool'])}</td><td>{len(l['records'])}</td><td>{len(l['blocks'])}</td><td>{l['reverse']}</td><td>{kb(l['covered'])}</td></tr>" for l in lanes)
    table = ("<details><summary>Numbers for this plasmid</summary><div class='sy-scroll'><table><thead><tr><th>Tool</th><th>Records</th><th>Aligned blocks</th>"
             "<th>Reverse blocks</th><th>Aligned bases on the plasmid</th></tr></thead><tbody>" + body + "</tbody></table></div></details>")
    return (f"<div class='sy-view' data-view='{esc(vid)}' data-label='{esc(sample)} / {esc(plasmid)}'><h3>{esc(sample)} &middot; {esc(plasmid)} <small>({kb(length)})</small></h3>"
            f"<div class='sy-scroll'>{''.join(out)}</div>{table}</div>")


def load(results_dir):
    """-> list of views (sample, plasmid, length, {tool: lane}) with at least one tool block; ordered most structurally interesting first."""
    views = []
    if not os.path.isdir(results_dir):
        return views
    for sample in sorted(d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))):
        data = read_json(os.path.join(results_dir, sample, "visualization", "alignment_blocks.json"))
        if not data:
            continue
        for plasmid, info in (data.get("truth_plasmids") or {}).items():
            if str(info.get("molecule_type", "PLASMID")).upper() != "PLASMID" or not info.get("length"):
                continue
            lanes = [m for m in (lane_model(t, (p or {}).get("blocks") or [], plasmid) for t, p in (data.get("tools") or {}).items()) if m]
            if lanes:
                lanes.sort(key=lambda m: -m["covered"])
                views.append((sample, plasmid, int(info["length"]), lanes))
    views.sort(key=lambda v: (-sum(l["reverse"] for l in v[3]), -sum(len(l["records"]) for l in v[3]), v[0], v[1]))
    return views


SCRIPT = """<script>
(function(){
var root=document.getElementById('learn-synteny-body');if(!root)return;
root.classList.add('sy-js');
var views=[].slice.call(root.querySelectorAll('.sy-view')),sel=root.querySelector('.sy-select'),detail=root.querySelector('.sy-detail'),pinned=null;
function clear(){pinned=null;root.classList.remove('sy-hl');root.querySelectorAll('.hl').forEach(function(e){e.classList.remove('hl')});if(detail)detail.textContent='Hover or focus a ribbon or a record to read its details; click to keep them.'}
function show(i){views.forEach(function(v,k){v.classList.toggle('sy-on',k===i)});if(sel)sel.value=String(i);clear()}
function cur(){var k=views.findIndex(function(v){return v.classList.contains('sy-on')});return k<0?0:k}
if(sel)sel.addEventListener('change',function(){show(parseInt(sel.value,10)||0)});
var p=root.querySelector('.sy-prev'),n=root.querySelector('.sy-next');
if(p)p.addEventListener('click',function(){show((cur()+views.length-1)%views.length)});
if(n)n.addEventListener('click',function(){show((cur()+1)%views.length)});
root.querySelectorAll('.sy-tool').forEach(function(cb){cb.addEventListener('change',function(){
  root.querySelectorAll('.sy-lane[data-tool="'+cb.value+'"]').forEach(function(l){l.style.display=cb.checked?'':'none'})})});
function filter(){var f=root.querySelector('.sy-fwd').checked,r=root.querySelector('.sy-rev').checked,m=parseFloat(root.querySelector('.sy-ident').value)/100;
  root.querySelectorAll('.sy-rib').forEach(function(e){var s=e.getAttribute('data-strand'),id=parseFloat(e.getAttribute('data-ident'));
    e.style.display=((s==='+'&&f)||(s==='-'&&r))&&id>=m?'':'none'});
  var o=root.querySelector('.sy-identval');if(o)o.textContent=Math.round(m*100)+'%'}
['.sy-fwd','.sy-rev','.sy-ident'].forEach(function(q){var e=root.querySelector(q);if(e)e.addEventListener('input',filter)});filter();
var z=root.querySelector('.sy-zoom');if(z)z.addEventListener('input',function(){root.querySelectorAll('.sy-view svg').forEach(function(s){s.style.width=(parseFloat(z.value)*100)+'%'})});
function light(el){var k=el.getAttribute('data-rec');root.classList.add('sy-hl');
  el.closest('.sy-view').querySelectorAll('[data-rec="'+k+'"]').forEach(function(e){e.classList.add('hl')});el.classList.add('hl');
  if(detail)detail.textContent=el.getAttribute('data-info')||''}
function unlight(){if(pinned)return;root.classList.remove('sy-hl');root.querySelectorAll('.hl').forEach(function(e){e.classList.remove('hl')})}
root.addEventListener('mouseover',function(e){var t=e.target.closest('.sy-rib,.sy-rec');if(t&&!pinned)light(t)});
root.addEventListener('mouseout',function(e){if(e.target.closest('.sy-rib,.sy-rec'))unlight()});
root.addEventListener('focusin',function(e){var t=e.target.closest('.sy-rib,.sy-rec');if(t&&!pinned)light(t)});
root.addEventListener('focusout',function(e){if(e.target.closest('.sy-rib,.sy-rec'))unlight()});
root.addEventListener('click',function(e){var t=e.target.closest('.sy-rib,.sy-rec');if(!t)return;
  if(pinned===t){clear();return}root.querySelectorAll('.hl').forEach(function(x){x.classList.remove('hl')});pinned=null;light(t);pinned=t});
root.addEventListener('keydown',function(e){if(e.key==='Escape')clear()});
show(0);
})();
</script>"""


def section(views, total=None):
    lead = ("Coverage and identity do not show whether a plasmid was put back together in the right order and orientation. Each ribbon joins a stretch of the "
            "truth plasmid to the stretch of a predicted record that matches it. <strong>Descriptive; it changes no score.</strong>")
    if not views:
        return (f"<section id='{SECTION_ID}' class='sy'><h2>Synteny ribbons</h2><p class='lead'>{lead}</p><div class='insight caution'><p>Not run: no "
                "results/&lt;sample&gt;/visualization/alignment_blocks.json exists. It is written by the visual-data step of stage 5 "
                "(build_visualization_data.py); without it the report cannot draw how records sit on each plasmid.</p></div></section>")
    total = total if total is not None else len(views)
    shown = views[:MAX_VIEWS]
    tools = sorted({l["tool"] for v in shown for l in v[3]})
    blocks = []
    for k, (sample, plasmid, length, lanes) in enumerate(shown):
        top = lanes[:MAX_LANES]
        blocks.append(render_view(str(k), sample, plasmid, length, lanes, {l["tool"] for l in top}))
    options = "".join(f"<option value='{k}'>{esc(v[0])} / {esc(v[1])} ({len(v[3])} tools)</option>" for k, v in enumerate(shown))
    controls = ("<div class='sy-bar'><label>Plasmid <select class='sy-select' aria-label='Choose a plasmid'>" + options + "</select></label>"
                "<button type='button' class='sy-prev' aria-label='Previous plasmid'>&larr;</button><button type='button' class='sy-next' aria-label='Next plasmid'>&rarr;</button>"
                "<label>Zoom <input type='range' class='sy-zoom' min='1' max='6' step='0.25' value='1' aria-label='Zoom'></label></div>"
                "<div class='sy-bar'><strong>Blocks</strong><label><input type='checkbox' class='sy-fwd' checked> forward</label>"
                "<label><input type='checkbox' class='sy-rev' checked> reverse</label>"
                "<label>Minimum identity <input type='range' class='sy-ident' min='0' max='100' step='1' value='0' aria-label='Minimum identity'> <output class='sy-identval'>0%</output></label></div>"
                "<div class='sy-bar'><strong>Tools</strong>" + "".join(
                    f"<label><input type='checkbox' class='sy-tool' value='{esc(t)}'{' checked' if any(t in {l['tool'] for l in v[3][:MAX_LANES]} for v in shown[:1]) else ''}> {esc(t)}</label>"
                    for t in tools) + "</div>")
    legend = (f"<div class='sy-legend'><span><svg width='26' height='12'><polygon points='0,0 8,0 26,12 18,12' fill='{FORWARD}' fill-opacity='.78'/></svg> forward block</span>"
              f"<span><svg width='26' height='12'><polygon points='0,0 8,0 18,12 26,12' fill='{REVERSE}' fill-opacity='.78'/></svg> reverse block (crossed)</span>"
              "<span>opacity: about 99% identity or more, 95 to 99%, below 95%</span><span>grey bar: truth plasmid; grey boxes: predicted records in plasmid order</span></div>")
    note = (f"<p class='small'>Showing {len(shown)} of {total} plasmids, those with the most reversed blocks and records first; the rest are in each sample's "
            "visualization/alignment_blocks.json.</p>") if total > len(shown) else ""
    return (f"<section id='{SECTION_ID}' class='sy'><h2>Synteny ribbons</h2><p class='lead'>{lead}</p><div id='learn-synteny-body' class='sy'>{legend}{controls}"
            f"<div class='sy-detail' aria-live='polite'>Hover or focus a ribbon or a record to read its details; click to keep them.</div>{''.join(blocks)}{note}</div>{SCRIPT}</section>")


def inject(page, results_dir):
    import report_fig_synteny    # the compact single-comparison redesign; the stacked drawing below is kept as inject_legacy
    return report_fig_synteny.inject(page, results_dir)


def inject_legacy(page, results_dir):
    views = load(results_dir)
    body = CSS + section(views, len(views))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, body + anchor, 1)
        nav = "<a href='#recommendations'>Recommendations</a>"
        page = page.replace(nav, f"<a href='#{SECTION_ID}'>Synteny ribbons</a>" + nav, 1)
    return page
