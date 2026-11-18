#!/usr/bin/env python3
"""The JavaScript of the facet heatmaps and the presence matrix, run in node.

  - the pure helpers (cell statistics, grid, colour, Wilson, row order, prevalence, tool recovery, CSV) must give the numbers the Python helpers give
  - the interface scripts run against a small fake DOM: a cell click fills the side panel, arrow keys move the focus, the stratum and threshold pickers redraw,
    a presence row and a feature column fill their panels, and the tool overlay adds the outcome strip

Node is optional: without it the test prints why it was skipped and exits 0. It cannot stand in for a browser: layout, colours, focus rings and touch are not checked here.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import report_fig_facets as ff  # noqa: E402
import report_fig_presence as fp  # noqa: E402
import report_visuals_fixture as fx  # noqa: E402

NODE = shutil.which("node")
ASSETS = ROOT / "assets" / "report"

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function script(name) { const t = fs.readFileSync(process.argv[3] + '/' + name, 'utf8'); return t.replace(/^\s*<script>/, '').replace(/<\/script>\s*$/, ''); }
function stub(tag) {
  const e = {tag: tag, attrs: {}, children: [], handlers: {}, _text: '', hidden: false, style: {}, parent: null, value: '', checked: false, selected: false, ownerSVGElement: null,
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') { this.value = String(v); } },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter(function (x) { return x !== c; }); return c; },
    addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); },
    fire(t, ev) { (this.handlers[t] || []).forEach(function (f) { f(Object.assign({key: '', clientX: 0, clientY: 0, preventDefault() {}}, ev || {})); }); },
    focus() { this.focused = true; }, getBoundingClientRect() { return {right: 0, top: 0}; }, click() {},
    classList: {add(c) { e.attrs['class'] = ((e.attrs['class'] || '') + ' ' + c).trim(); }, remove(c) { e.attrs['class'] = (e.attrs['class'] || '').split(' ').filter(function (x) { return x !== c; }).join(' '); },
      toggle(c, on) { if (on) { e.classList.add(c); } else { e.classList.remove(c); } }},
    get textContent() { return this._text + this.children.map(function (c) { return c.textContent; }).join(' '); },
    set textContent(v) { this.children = []; this._text = String(v); },
    set innerHTML(h) { this._html = h; this.children = []; this._text = ''; parse(this, h); },
    get innerHTML() { return this._html || ''; },
    get firstChild() { return this.children[0] || null; },
    all() { let out = []; this.children.forEach(function (c) { out.push(c); out = out.concat(c.all ? c.all() : []); }); return out; },
    querySelectorAll(sel) {
      const m = /^([a-z]*)(?:\.([\w-]+))?(?:\[([\w-]+)="([^"]*)"\])?$/.exec(sel); if (!m) { return []; }
      return this.all().filter(function (n) {
        if (m[1] && n.tag !== m[1]) { return false; }
        if (m[2] && (n.attrs['class'] || '').split(' ').indexOf(m[2]) < 0) { return false; }
        if (m[3] && n.attrs[m[3]] !== m[4]) { return false; }
        return true;
      });
    },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }};
  return e;
}
function parse(host, html) {
  const svg = stub('svg'); let any = false;
  const re = /<(svg|g|rect)\s([^>]*)>/g; let m;
  while ((m = re.exec(html))) {
    const attrs = {}, are = /([\w-]+)="([^"]*)"/g; let a;
    while ((a = are.exec(m[2]))) { attrs[a[1]] = a[2]; }
    if (m[1] === 'svg') { Object.assign(svg.attrs, attrs); any = true; continue; }
    const cls = attrs['class'] || '';
    if (/fc-cell|fp-row|fp-col/.test(cls) || attrs.id) { const n = stub(m[1]); n.attrs = attrs; n.ownerSVGElement = svg; n.parent = svg; svg.children.push(n); }
  }
  if (any) { host.children.push(svg); }
}
const body = stub('body'), sandbox = {console: console, setTimeout: setTimeout, JSON: JSON, Set: Set, Math: Math, Object: Object, Array: Array, String: String, Number: Number, parseInt: parseInt, isNaN: isNaN, Blob: function () {}, URL: {createObjectURL() { return ''; }}};
sandbox.window = sandbox; sandbox.addEventListener = function () {};
sandbox.innerWidth = 1200;
sandbox.document = {body: body, documentElement: {getAttribute() { return null; }, dataset: {}}, createElement: stub, createTextNode(t) { const n = stub('#text'); n._text = String(t); return n; },
  getElementById(id) { return body.all().filter(function (n) { return n.attrs.id === id; })[0] || null; }};
vm.createContext(sandbox);
vm.runInContext(script('fig_facets_core.html') + '\n' + script('fig_presence_core.html'), sandbox);
const FC = sandbox.FCCore, FP = sandbox.FPCore, out = {};

// ---------------------------------------------------------------- pure helpers
const fd = input.facets, lv = fd.levels.isolate, sel = FC.defaultSelection(lv, fd.defaults);
out.fc_sel = sel;
out.fc_cells = [];
FC.grid(lv, sel.block, sel.row).forEach(function (b, bi) { b.rows.forEach(function (r, ri) { lv.metrics.forEach(function (m, mi) { fd.tools.forEach(function (t, ti) {
  const s = FC.cellStats(lv, ti, mi, r.units, 3); out.fc_cells.push([bi, ri, mi, ti, s.n, s.v, s.lo, s.hi, s.few]); }); }); }); });
out.fc_colour = [0, 0.1, 0.25, 0.5, 0.77, 1, -1, 2].map(FC.colour);
out.fc_wilson = [[2, 5], [0, 4], [4, 4], [0, 0]].map(function (a) { return FC.wilson(a[0], a[1]); });
out.fc_csv_head = FC.csv(fd, lv, sel, {track: 'short_read', minN: 3}).split(String.fromCharCode(10))[0];
const drawn = FC.svg(fd, lv, sel, {track: 'short_read', minN: 3});
out.fc_svg = {cells: drawn.cells.length, hatched: (drawn.svg.match(/url\(#fc-hatch-l\)/g) || []).length - 1, empty: (drawn.svg.match(/class="fc-empty"/g) || []).length, panels: drawn.metrics.length};
out.fc_neighbour = [FC.neighbour(drawn.cells, 0, 'ArrowRight'), FC.neighbour(drawn.cells, 0, 'ArrowLeft'), FC.neighbour(drawn.cells, 0, 'ArrowDown')];

const pd = input.presence; FP.prepare(pd);
out.fp_order_species = FP.rowOrder(pd, 'species'); out.fp_order_size = FP.rowOrder(pd, 'size'); out.fp_order_cluster = FP.rowOrder(pd, 'cluster');
out.fp_prev = []; pd.blocks.forEach(function (b, bi) { b.f.forEach(function (f, fi) { const p = FP.prevalence(pd, b, fi); out.fp_prev.push([bi, fi, p.c, p.n, p.share]); }); });
out.fp_rec = FP.toolRecovery(pd, pd.blocks[0], 0).map(function (x) { return [x.ti, x.withFeature.c, x.withFeature.n, x.without.c, x.without.n]; });
out.fp_by = FP.prevalenceBy(pd, pd.blocks[0], 0, 'species');
out.fp_csv_head = FP.csv(pd).split(String.fromCharCode(10))[0];
const ps = FP.svg(pd, {tool: null, order: 'cluster'}), pt = FP.svg(pd, {tool: '0', order: 'size'});
out.fp_svg = {rows: (ps.svg.match(/class="fp-row"/g) || []).length, cols: (ps.svg.match(/class="fp-col"/g) || []).length, hatched: (ps.svg.match(/fill="url\(#fp-hatch-l\)"/g) || []).length,
  dend: ps.svg.indexOf('fp-dend') >= 0, dendWhenSorted: pt.svg.indexOf('fp-dend') >= 0, outcomeStrip: ps.svg.indexOf('Outcome') >= 0, outcomeStripTool: pt.svg.indexOf('Outcome') >= 0};

// ---------------------------------------------------------------- interface, fake DOM
function mount(id, dataId, data, files) {
  const root = stub('div'); root.attrs.id = id; const d = stub('script'); d.attrs.id = dataId; d._text = JSON.stringify(data);
  body.appendChild(root); body.appendChild(d);
  files.forEach(function (f) { vm.runInContext(script(f), sandbox); });
  return root;
}
const maps = stub('section'); maps.attrs.id = 'plasmid-maps'; body.appendChild(maps);
const fcRoot = mount('fc-root', 'fc-data', fd, ['fig_facets_ui.html']);
const cells = fcRoot.querySelectorAll('g'), ui = {};
ui.fc_live = (fcRoot.attrs['class'] || '').indexOf('fc-live') >= 0;
ui.fc_cells = cells.length;
const panel = sandbox.document.getElementById('fc-panel');
ui.fc_panel_before = panel.textContent;
const first = cells[0]; first.fire('click');
ui.fc_panel_after = panel.textContent;
ui.fc_selected = (first.attrs['class'] || '').indexOf('fc-sel') >= 0;
first.fire('keydown', {key: 'ArrowRight'});
ui.fc_tab0 = cells.filter(function (c) { return c.attrs.tabindex === '0'; }).length;
const selects = fcRoot.querySelectorAll('select');
function pick(id, value) { const s = sandbox.document.getElementById(id); s.value = value; s.fire('change'); return s; }
pick('fc-block', 'depth'); ui.fc_block_cells = fcRoot.querySelectorAll('g').length;
pick('fc-row', ''); ui.fc_row_none_cells = fcRoot.querySelectorAll('g').length;
const mn = sandbox.document.getElementById('fc-minn'); mn.value = '1'; mn.fire('change'); ui.fc_hatched_min1 = (fcRoot.innerHTML + fcRoot.children.map(function (c) { return c.innerHTML; }).join('')).length > 0;
ui.fc_levels = sandbox.document.getElementById('fc-level') ? 'has level picker' : 'no level picker';
const lvl = sandbox.document.getElementById('fc-level'); lvl.value = 'plasmid'; lvl.fire('change'); ui.fc_plasmid_cells = fcRoot.querySelectorAll('g').length;
const pc = fcRoot.querySelectorAll('g')[0]; pc.fire('click'); ui.fc_plasmid_panel = sandbox.document.getElementById('fc-panel').textContent; ui.fc_plasmid_link = sandbox.document.getElementById('fc-panel').all().filter(function (n) { return n.tag === 'a'; }).map(function (n) { return n.attrs.href; });

const fpRoot = mount('fp-root', 'fp-data', input.presence_raw, ['fig_presence_ui.html']);
const rows = fpRoot.querySelectorAll('g').filter(function (g) { return g.attrs['class'] === 'fp-row'; }), colsEls = fpRoot.querySelectorAll('g').filter(function (g) { return g.attrs['class'] === 'fp-col'; });
ui.fp_rows = rows.length; ui.fp_cols = colsEls.length;
const fpanel = sandbox.document.getElementById('fp-panel');
ui.fp_panel_before = fpanel.textContent;
rows[0].fire('click'); ui.fp_row_panel = fpanel.textContent; ui.fp_row_link = fpanel.all().filter(function (n) { return n.tag === 'a'; }).map(function (n) { return n.attrs.href; });
colsEls[0].fire('click'); ui.fp_col_panel = fpanel.textContent;
rows[0].fire('keydown', {key: 'ArrowDown'}); ui.fp_row_tab = rows.filter(function (g) { return g.attrs.tabindex === '0'; }).length;
const tool = pick('fp-tool', '0'); ui.fp_tool_svg = fpRoot.querySelectorAll('g').length > 0;
ui.fp_tool_note = fpRoot.textContent.indexOf('Overlay for') >= 0;
pick('fp-order', 'species'); ui.fp_after_order = fpRoot.querySelectorAll('g').filter(function (g) { return g.attrs['class'] === 'fp-row'; }).length;
console.log(JSON.stringify(Object.assign(out, {ui: ui})));
"""


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    if not NODE:
        print("SKIPPED: node is not installed, so the JavaScript of the facet heatmaps and the presence matrix was not run")
        return
    with tempfile.TemporaryDirectory() as tmp:
        scores = fx.make(Path(tmp) / "res")
        facets, why = ff.build_payload(str(Path(tmp) / "res"), str(Path(tmp) / "res"), scores)
        presence, why2 = fp.build_payload(str(Path(tmp) / "res"), str(Path(tmp) / "res"), scores)
        assert facets and presence, (why, why2)
        (Path(tmp) / "in.json").write_text(json.dumps({"facets": facets, "presence": presence, "presence_raw": presence}), encoding="utf-8")
        (Path(tmp) / "run.js").write_text(RUNNER, encoding="utf-8")
        done = subprocess.run([NODE, str(Path(tmp) / "run.js"), str(Path(tmp) / "in.json"), str(ASSETS)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            print(done.stderr[-2000:])
        check("the scripts run in node without an exception", done.returncode == 0)
        if done.returncode != 0:
            sys.exit(1)
        js = json.loads(done.stdout.strip().splitlines()[-1])

    iso = facets["levels"]["isolate"]
    sel = ff.default_selection(iso)
    print("parity with Python")
    check("the default selection is the same", js["fc_sel"] == sel, (js["fc_sel"], sel))
    mism = []
    i = 0
    for bi, b in enumerate(ff.grid(iso, sel["block"], sel["row"])):
        for ri, r in enumerate(b["rows"]):
            for mi, m in enumerate(iso["metrics"]):
                for ti, t in enumerate(facets["tools"]):
                    s = ff.cell_stats(iso, ti, mi, r["units"], 3)
                    got = js["fc_cells"][i]
                    i += 1
                    want = [bi, ri, mi, ti, s["n"], s["v"], s["lo"], s["hi"], s["few"]]
                    same = got[:5] == want[:5] and got[8] == want[8] and all((a is None and b_ is None) or (a is not None and b_ is not None and abs(a - b_) < 1e-9) for a, b_ in zip(got[5:8], want[5:8]))
                    if not same:
                        mism.append((got, want))
    check(f"every cell (n, value, interval, too-few flag) matches Python ({i} cells)", not mism and i == len(js["fc_cells"]), mism[:2])
    check("the colour scale matches", js["fc_colour"] == [ff.colour(v) for v in (0, 0.1, 0.25, 0.5, 0.77, 1, -1, 2)], js["fc_colour"])
    check("Wilson intervals match (and 0 of 0 is null)", all((a is None and b_ is None) or all(abs(x - y) < 1e-12 for x, y in zip(a, b_)) for a, b_ in zip(js["fc_wilson"], [ff.wilson(2, 5), ff.wilson(0, 4), ff.wilson(4, 4), None])), js["fc_wilson"])
    check("the CSV has the documented header", js["fc_csv_head"] == "block,row,tool,metric,n,value,low,high,flag")
    svg, n = ff.svg_static(iso, facets["tools"], sel, 3, "short_read")
    check("the live SVG draws as many panels as the static one", js["fc_svg"]["panels"] == n == 4)
    check("it hatches the cells the static figure hatches", js["fc_svg"]["hatched"] == svg.count("fill='url(#fc-hatch)'") - 1, (js["fc_svg"], svg.count("fill='url(#fc-hatch)'")))   # the legend swatch is the extra one
    check("it draws the blanks the static figure draws", js["fc_svg"]["empty"] == svg.count("stroke-dasharray='2 2'"), (js["fc_svg"]["empty"], svg.count("stroke-dasharray='2 2'")))
    check("arrow keys move between cells (right goes on, left at the edge stays, down moves a row)", js["fc_neighbour"][0] != 0 and js["fc_neighbour"][1] == 0 and js["fc_neighbour"][2] != 0, js["fc_neighbour"])

    rows = presence["rows"]
    tracks = {t["k"]: t for t in presence["tracks"]}
    rank = {r: i for i, r in enumerate(presence["order"])}
    want_sp = sorted(presence["order"], key=lambda r: (tracks["species"]["r"][r], rank[r]))
    check("reordering by an annotation is stable inside the clustered order (species, size)", js["fp_order_species"] == want_sp and js["fp_order_cluster"] == presence["order"] and
          js["fp_order_size"] == sorted(presence["order"], key=lambda r: (tracks["size"]["r"][r], rank[r])))
    want_prev = []
    for bi, b in enumerate(presence["blocks"]):
        ann = len(rows) - len(b["na"])
        for fi, (name, rws) in enumerate(b["f"]):
            c, n_, share = fp.prevalence({"ann": [i not in b["na"] for i in range(len(rows))]}, rws)
            want_prev.append([bi, fi, c, n_, share])
    check("prevalence of every feature matches Python", js["fp_prev"] == want_prev, (js["fp_prev"][:3], want_prev[:3]))
    check("a stratified prevalence lists only groups with annotated plasmids", all(g["n"] > 0 for g in js["fp_by"]))
    check("the per-tool recovery of carriers uses annotated plasmids with a value", all(x[2] <= len(rows) and x[1] <= x[2] for x in js["fp_rec"]), js["fp_rec"])
    check("the presence CSV starts with the plasmid, sample and length columns", js["fp_csv_head"].startswith("plasmid,sample,length_bp,species"))
    s = js["fp_svg"]
    check("one row target per plasmid and one column target per drawn feature", s["rows"] == len(rows) and s["cols"] == sum(len(b["f"]) for b in presence["blocks"] if b["k"] != "amr_gene"), s)
    check("not-annotated cells are hatched", s["hatched"] == sum(len(b["na"]) for b in presence["blocks"] if b["k"] != "amr_gene"), s)
    check("the dendrogram shows in cluster order only and the outcome strip only with a tool", s["dend"] and not s["dendWhenSorted"] and not s["outcomeStrip"] and s["outcomeStripTool"], s)

    ui = js["ui"]
    print("interface (fake DOM, not a browser)")
    check("the facet app starts and marks itself live", ui["fc_live"] and ui["fc_cells"] > 0)
    check("before a click the panel says how to open a cell", "Click a cell" in ui["fc_panel_before"])
    check("a click fills the side panel with n, the value, the interval and the units", all(w in ui["fc_panel_after"] for w in ("n", "Value", "Interval")) and "s1" in ui["fc_panel_after"], ui["fc_panel_after"][:300])
    check("the clicked cell is marked selected and one cell keeps tabindex 0 after an arrow key", ui["fc_selected"] and ui["fc_tab0"] == 1, ui)
    check("the block picker redraws and 'Rows by: None' redraws", ui["fc_block_cells"] > 0 and ui["fc_row_none_cells"] > 0)
    check("switching to plasmids redraws and a plasmid cell lists plasmids with a map link", ui["fc_plasmid_cells"] > 0 and "Plasmid" in ui["fc_plasmid_panel"] and any(h.startswith("#plasmid-maps?msample=") for h in ui["fc_plasmid_link"]), ui["fc_plasmid_link"])
    check("the presence app lists a row and a column per plasmid and feature", ui["fp_rows"] == len(rows) and ui["fp_cols"] == sum(len(b["f"]) for b in presence["blocks"] if b["k"] != "amr_gene"), ui)
    check("a presence row click fills the plasmid panel with facts, features and tool outcomes", all(w in ui["fp_row_panel"] for w in ("Sample", "Features", "Outcome per tool")), ui["fp_row_panel"][:300])
    check("it offers the link to the circular map when the maps section exists", any(h.startswith("#plasmid-maps?msample=") for h in ui["fp_row_link"]), ui["fp_row_link"])
    check("a feature click fills the feature panel with prevalence and per-tool recovery", all(w in ui["fp_col_panel"] for w in ("Carried by", "Recovery of the plasmids that carry it")), ui["fp_col_panel"][:300])
    check("the tool overlay and the order picker redraw", ui["fp_tool_svg"] and ui["fp_tool_note"] and ui["fp_after_order"] == len(rows), ui)
    print()
    if not ok:
        print("VISUALS JAVASCRIPT TESTS FAILED")
        sys.exit(1)
    print("ALL VISUALS JAVASCRIPT TESTS PASSED")


if __name__ == "__main__":
    main()
