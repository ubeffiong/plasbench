#!/usr/bin/env python3
"""The reconstruction ladder (python/report_fig_ladder.py, assets/report/fig_ladder_*.html): hand-computed counts, static SVG, payload,
node tests of the pure JS, section wiring, and a real check against results_demo."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_fig_ladder as L  # noqa: E402
import report_common as rc  # noqa: E402

ASSETS = os.path.join(ROOT, "assets", "report")
NODE = shutil.which("node")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as h:
        h.write(text)


def tsv(path, header, rows):
    write(path, "\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows))


def calls(path, sample, tools):
    doc = {"schema_version": "1.0", "sample": sample, "validated": False, "tools": {
        t: {"summary": {"collinear_fraction": 0.9, "inter_replicon_junction": sum(e[0] == "inter_replicon_junction" for e in ev),
                        "reference_deletion": sum(e[0] == "reference_deletion" for e in ev)},
            "events": [{"event_type": e[0], "left_target": e[1], "right_target": e[2]} for e in ev]} for t, ev in tools.items()}}
    write(path, json.dumps(doc))


def fixture(tmp):
    d = os.path.join(tmp, "res")
    s = os.path.join(d, "s1")
    oh = ["true_plasmid", "length", "best_bin", "best_bin_recall", "best_bin_precision", "bins_holding_share", "merged_with", "contamination_fraction", "outcome"]
    tsv(os.path.join(s, "t1.plasmid_outcomes.tsv"), oh, [["pA", 100, "b1", 1, 1, 1, "", 0, "perfect"], ["pB", 50, "b2", 1, 1, 1, "", 0, "perfect"],
                                                          ["pC", 40, "b3", 0.5, 1, 2, "", 0, "fragmented"]])
    tsv(os.path.join(s, "t2.plasmid_outcomes.tsv"), oh, [["pA", 100, "b1", 1, 1, 1, "", 0, "perfect"]])
    tsv(os.path.join(s, "t3.plasmid_outcomes.tsv"), oh, [["pA", 100, "b1", 1, 1, 1, "", 0, "perfect"]])        # tool without structural calls
    calls(os.path.join(s, "visualization", "structural_calls.json"), "s1",
          {"t1": [("reference_deletion", "pA", "pA"), ("inter_replicon_junction", "pB", "pC")], "t2": []})
    ph = ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"]
    tsv(os.path.join(s, "truth_circular.tsv"), ["sequence_id"], [["pA"]])
    tsv(os.path.join(s, "t1.per_plasmid.tsv"), ph, [["s1", "t1", "x", "pA", 100, 100, "1.0000", 1], ["s1", "t1", "x", "pB", 50, 50, "1.0000", 1]])
    tsv(os.path.join(s, "t2.per_plasmid.tsv"), ph, [["s1", "t2", "x", "pA", 100, 100, "1.0000", 1]])
    tsv(os.path.join(s, "t3.per_plasmid.tsv"), ph, [["s1", "t3", "x", "pA", 100, 99, "0.9900", 0]])
    return d


def test_distinctions():
    with tempfile.TemporaryDirectory() as tmp:
        d = fixture(tmp)
        got = {x["id"]: x for x in L.distinctions(d)}
        # distinction 1: perfect bins with structural calls = t1 pA, t1 pB, t2 pA (t3 has no calls) -> 3; with an event = t1 pA (deletion), t1 pB (junction) -> 2
        assert (got[1]["num"], got[1]["den"]) == (2, 3), got[1]
        # distinction 2: circular truth pA complete in t1 and t2 (t3 has no calls, and pB is not circular) -> 2; event on pA only for t1 -> 1
        assert (got[2]["num"], got[2]["den"]) == (1, 2), got[2]
        assert "1 of 2" in got[2]["line"] and "not evidence" in got[2]["detail"]
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        for x in L.distinctions(empty):
            assert x["den"] is None and x["reason"].startswith("no "), x          # not computable, with a reason, never 0
        # outcomes but no structural calls at all -> not computable, says why
        os.remove(os.path.join(d, "s1", "visualization", "structural_calls.json"))
        for x in L.distinctions(d):
            assert x["den"] is None and "structural_calls.json" in x["reason"], x


def test_payload(d_demo):
    p = L.build_payload(d_demo, d_demo, os.path.join(d_demo, "scores.tsv"))
    text = json.dumps(p, allow_nan=False)             # raises on NaN/inf
    assert json.loads(text)["schema"] == 1
    assert [s["id"] for s in p["steps"]] == [1, 2, 3, 4, 5]
    layers = {l["id"] for l in p["layers"]}
    for s in p["steps"]:
        assert s["judged"] and all(j["layer"] in layers for j in s["judged"])
        for v in s["values"]:
            assert v["v"] is None or (isinstance(v["v"], str) or v["v"] == v["v"])
    empty = L.build_payload("", "", "")
    assert not empty["any_data"]
    for s in empty["steps"]:
        for v in s["values"]:
            assert v["v"] is None and v["why"], (s["id"], v)        # a blank is 'not available' with a reason, never 0
    return p


def test_svg(p):
    for live in (None, L.live_lines(p)):
        svg = L.render_svg(live)
        root = ET.fromstring(svg)
        ids = re.findall(r"\bid='([^']+)'", svg)
        assert len(ids) == len(set(ids)), "duplicate ids"
        assert all(f"lad-step-{i}" in ids for i in range(1, 6)) and all(f"lad-note-{i}" in ids for i in (1, 2, 3))
        assert "Binning is not reconstruction" in svg and "Circular is not correct" in svg and "3D appearance is illustrative" in svg
        assert "NaN" not in svg and "inf" not in re.sub(r"[A-Za-z]inf|inf[A-Za-z]", "", svg)
        assert root.tag.endswith("svg")
    assert "0 of 10" in L.render_svg(L.live_lines(p)) and "not computable" not in L.render_svg(L.live_lines(p))
    committed = os.path.join(ROOT, "docs", "images", "reconstruction_ladder.svg")
    with open(committed, encoding="utf-8", newline="") as h:
        assert h.read() == L.render_svg() + "\n", "docs/images/reconstruction_ladder.svg is out of date: run python python/report_fig_ladder.py --out docs/images/reconstruction_ladder.svg"
    assert subprocess.run([sys.executable, os.path.join(ROOT, "python", "report_fig_ladder.py"), "--check", committed]).returncode == 0


def test_node():
    if not NODE:
        print("SKIPPED: node not found; the JS pure-function tests did not run")
        return
    for name in ("fig_ladder_core.html", "fig_ladder_ui.html"):
        with open(os.path.join(ASSETS, name), encoding="utf-8") as h:
            body = h.read()
        assert body.rstrip().endswith("</script>")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as t:
            t.write(body.strip()[len("<script>"):-len("</script>")])
        done = subprocess.run([NODE, "--check", t.name], capture_output=True, text=True)
        os.unlink(t.name)
        assert done.returncode == 0, done.stderr
    with open(os.path.join(ASSETS, "fig_ladder_style.html"), encoding="utf-8") as h:
        assert h.read().rstrip().endswith("</style>")
    script = r"""
const fs=require('fs'),vm=require('vm');
let src=fs.readFileSync(process.argv[2],'utf8').trim(); src=src.slice('<script>'.length,-'</script>'.length);
const sb={module:{exports:{}},globalThis:{}}; sb.globalThis=sb; vm.createContext(sb); vm.runInContext(src,sb);
const L=sb.PBLadder, assert=require('assert');
assert.strictEqual(L.fmtValue({v:null}),'not available');
assert.strictEqual(L.fmtValue({v:0.5,f:'pct'}),'50.0%');
assert.strictEqual(L.fmtValue({v:3,f:'int'}),'3');
assert.strictEqual(L.fmtValue({v:0.40914,f:'num'}),'0.409');
assert.strictEqual(L.fmtValue({v:'a, b'}),'a, b');
assert.strictEqual(L.fmtValue({v:NaN}),'not available');
assert.strictEqual(L.ratioText({num:1,den:4}),'1 of 4 (25.0%)');
assert.strictEqual(L.ratioText({num:null,den:null,reason:'no files'}),'not computable: no files');
assert.strictEqual(L.ratioText({num:0,den:0,reason:'none'}),'not computable: none');
const P={layers:[{id:'a',glyph:'x',label:'A'},{id:'b',glyph:'y',label:'B'}],
 steps:[{id:1,title:'One',what:'w',judged:[{layer:'a',text:'ta'}],where:[{id:'sec1',label:'Sec one'}],values:[{k:'K',v:2,f:'int',n:'of 3',sec:'sec1',unvalidated:true},{k:'Z',v:null,why:'no table',sec:'nope'}]},
        {id:2,title:'Two',what:'w2',judged:[{layer:'b',text:'tb'},{layer:'a',text:'tc'}],where:[],values:[]}],
 notes:[{id:1,title:'N1',text:'t1'},{id:2,title:'N2',text:'t2'},{id:3,title:'N3',text:'t3'}],
 distinctions:[{id:1,num:1,den:4,line:'1 of 4 ...',detail:'d'},{id:2,num:null,den:null,reason:'no files'}],synthetic_note:'syn'};
assert.deepStrictEqual(L.stepsForLayers(P,{}),[1,2]);
assert.deepStrictEqual(L.stepsForLayers(P,{a:true}),[1,2]);
assert.deepStrictEqual(L.stepsForLayers(P,{b:true}),[2]);
assert.deepStrictEqual(L.stepsForLayers(P,{b:false}),[1,2]);
const h=L.stepHtml(P,1,id=>id==='sec1');
assert(h.includes('href="#sec1"')); assert(!h.includes('href="#nope"')); assert(h.includes('not available (no table)')); assert(h.includes('(unvalidated)'));
assert(L.distinctionsHtml(P).includes('1 of 4')); assert(L.distinctionsHtml(P).includes('not computable: no files'));
assert(!L.linksHtml(P,()=>false).includes('<a '));
const csv=L.csvText(P).trim().split('\n'); assert.strictEqual(csv[0],'kind,step,step_title,name,value,note,report_section');
assert(csv.some(r=>r.startsWith('live_value,1,One,K,2,')));
assert(csv.some(r=>r.includes('not computable: no files')));
assert.strictEqual(L.esc('<a "x">&'),'&lt;a &quot;x&quot;&gt;&amp;');
console.log('node ok');
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as t:
        t.write(script)
    done = subprocess.run([NODE, t.name, os.path.join(ASSETS, "fig_ladder_core.html")], capture_output=True, text=True)
    os.unlink(t.name)
    assert done.returncode == 0 and "node ok" in done.stdout, done.stderr + done.stdout


def test_section(d_demo):
    page = "<html><head><style></style></head><body><nav><a href='#recommendations'>Recommendations</a></nav>" \
           "<section id='contig-layer'></section><section id='recommendations'></section></body></html>"
    out = L.inject(page, d_demo, d_demo, os.path.join(d_demo, "scores.tsv"))
    assert out.index("id='fig-ladder'") < out.index("id='recommendations'")
    assert "href='#fig-ladder'" in out and L.inject(out, d_demo, d_demo, "") == out          # idempotent
    ids = re.findall(r"\bid=['\"]([^'\"]+)['\"]", out)
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    data = re.search(r"<script type='application/json' id='lad-data'>(.*?)</script>", out, re.S).group(1)
    payload = json.loads(data)
    present = set(ids)
    for s in payload["steps"]:
        assert all(w["id"] in present for w in s["where"]), "payload lists a section that is not on the page"   # no dead links
    assert "<th>Step</th>" in out and "not available" not in out.split("id='lad-data'")[0].split("lad-static")[0]
    # nothing found: visible Not run, never blank
    blank = L.inject(page, "", "", "")
    assert "Not run:" in blank and "id='fig-ladder'" in blank
    return len(out) - len(page)


def main():
    d_demo = os.path.join(ROOT, "results_demo")
    test_distinctions()
    if not os.path.isdir(d_demo):
        print("SKIPPED: results_demo missing; the real-build checks did not run")
        return
    p = test_payload(d_demo)
    got = {x["id"]: (x["num"], x["den"]) for x in p["distinctions"]}
    assert got == {1: (0, 10), 2: (5, 11)}, got                       # the bundled demo, counted by hand from structural_calls.json
    test_svg(p)
    test_node()
    size = test_section(d_demo)
    print(f"ALL LADDER FIGURE TESTS PASSED (section adds {size} bytes to a minimal page)")


if __name__ == "__main__":
    main()
