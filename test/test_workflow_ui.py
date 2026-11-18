#!/usr/bin/env python3
"""The Workflow view and the On / Off colour rule in plasbench/data/ui.html (block 'workflow steps').

  - node (skipped with a printed reason when missing) runs the page's pure JavaScript (the WF-PURE block: state of an item, estimate, per-10 scaling, 'not measured', needs / needed-by,
    what can I add) on the same cases as plasbench/workflow_steps.py and requires identical numbers;
  - node also draws every step card from the real chain (stubbed DOM helpers) and checks what a reader would see: On / Off words and shapes, 'changed', badges, costs, 'not measured';
  - static checks: the Workflow | List toggle on the Tools page and in the wizard, one settings store (the same /api/settings and wizard state, no second store), keyed rendering,
    designed dialogs only (no confirm / prompt / alert), keyboard roles, colour tokens with light and dark values, Off distinct from On, WCAG AA contrast, a text label and a shape besides colour.
Standard library only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def lum(hexcolour):
    h = hexcolour.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def block(name):
    m = re.search(r"/\* BEGIN workflow steps.*?(?=/\* END workflow steps \*/)", HTML, re.S)
    return m.group(0) if m else ""


def main():
    from plasbench import workflow_steps as ws
    rows = ws.load(ROOT)
    script = re.search(r'<script id="wf-script">(.*?)</script>', HTML, re.S)
    script = script.group(1) if script else ""
    style = re.search(r'<style id="wf-style">(.*?)</style>', HTML, re.S)
    style = style.group(1) if style else ""
    check("the page has the workflow script and style blocks", bool(script) and bool(style))
    pure = script.split("/* ==WF-PURE-BEGIN==")[1].split("*/", 1)[1].split("/* ==WF-PURE-END== */")[0] if "==WF-PURE-BEGIN==" in script else ""
    check("the pure block is present and holds no DOM access", bool(pure) and not re.search(r"\bdocument\b|\bwindow\b|querySelector|innerHTML", pure))

    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the page's JavaScript is not executed (static checks below still run)")
    else:
        payload = ws.payload(ROOT, {})
        items = [i for s in payload["steps"] for i in s["items"]]
        defaults = ws.default_states(rows)
        cases = [defaults, dict(defaults, genomad="on", plasmer="on"), dict(defaults, platon="off", plasmidspades="off"), dict(defaults, mob_recon="off", gplas2_mob="on"),
                 dict(defaults, RUN_TRUTH_LABEL_EVIDENCE="on", RUN_PLSDB_NOVELTY="auto", flye_mob_recon="on")]
        expected = []
        for st in cases:
            expected.append({"est1": ws.estimate(rows, st, 1), "est10": ws.estimate(rows, st, 10), "delta": ws.estimate_delta(rows, st, 10),
                             "miss": {i: ws.missing_requires(rows, st, i) for i in ("gplas2_mob", "RUN_TRUTH_LABEL_EVIDENCE", "platon", "flye_mob_recon")},
                             "deps": {i: ws.dependents_on(rows, st, i) for i in ("mob_recon", "RUN_REFERENCE_ANNOTATION", "core_trim_assemble")},
                             "add": [r["item_id"] for r in ws.addable(rows, st)]})
        values = [[i["item_id"], v, ws.state_of(i, v), ws.is_changed(i, v)] for i in items for v in (None, "", "0", "1", "auto", "report", "off", "enforce")]
        driver = pure + r"""
const rows = %s, cases = %s, values = %s, out = {est: [], vals: []};
const byId = wfById(rows);
for (const st of cases) out.est.push({est1: wfEstimate(rows, st, 1), est10: wfEstimate(rows, st, 10), delta: wfDelta(rows, st, 10),
  miss: Object.fromEntries(["gplas2_mob", "RUN_TRUTH_LABEL_EVIDENCE", "platon", "flye_mob_recon"].map(i => [i, wfMissingRequires(rows, st, i)])),
  deps: Object.fromEntries(["mob_recon", "RUN_REFERENCE_ANNOTATION", "core_trim_assemble"].map(i => [i, wfDependentsOn(rows, st, i)])),
  add: wfAddable(rows, st).map(r => r.item_id)});
for (const [id, v, st, ch] of values) out.vals.push([wfStateOf(byId[id], v) === st && wfIsChanged(byId[id], v) === ch]);
out.text = wfEstimateText(wfEstimate(rows, cases[0], 1));
out.text2 = wfEstimateText(wfEstimate(rows, cases[1], 10));
out.fmt = [wfFmtTime(0), wfFmtTime(0.4), wfFmtTime(14.4), wfFmtTime(144), wfFmtGB(0.63), wfFmtGB(4.38), wfFmtGB(32)];
console.log(JSON.stringify(out));
""" % (json.dumps(items), json.dumps(cases), json.dumps(values))
        path = Path(tempfile.mkdtemp()) / "pure.js"
        path.write_text(driver, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True)
        try:
            out = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {}
            check("the pure block runs under node", False, done.stderr[:400])
        if out:
            same = all(json.loads(json.dumps(e)) == o for e, o in zip(expected, out["est"]))
            check("the page and plasbench/workflow_steps.py give identical estimates (1 and 10 isolates), differences, needs, needed-by and 'what can I add' on 5 cases", same,
                  next(((e, o) for e, o in zip(expected, out["est"]) if json.loads(json.dumps(e)) != o), None))
            check("state and 'changed' agree for every item and 8 setting values", all(v[0] for v in out["vals"]), [v for v in out["vals"] if not v[0]][:3])
            check("the estimate text names what is not measured instead of showing 0", out["text"][0].startswith("at least 14.4 min") and "peak memory" in out["text"][1] and out["text"][2].startswith("at least 630 MB"), out["text"])
            check("per 10 isolates the text scales time and disk", out["text2"][0].startswith("at least 2.4 h") and out["text2"][2].startswith("at least 6.3 GB") or out["text2"][2].startswith("at least 6.3"), out["text2"])
            check("time and size formats", out["fmt"] == ["0 min", "under a minute", "14.4 min", "2.4 h", "630 MB", "4.4 GB", "32 GB"], out["fmt"])

        # draw the real chain with stubbed helpers
        body = script.split("/* ==WF-PURE-END== */")[1]
        body = re.sub(r"\(function wfWire\(\) \{.*?\n\}\)\(\);", "", body, flags=re.S)
        smoke = pure + r"""
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = (n) => `<svg data-i="${n}"></svg>`, tipBtn = (t, l) => `<button class="tipi" data-tip="${esc(JSON.stringify(t))}" aria-label="Help: ${esc(l)}">i</button>`, wizTip = k => `<i data-wiz="${k}"></i>`;
const document = {activeElement: null, body: {contains: () => true}, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, getElementById: () => null};
const localStorage = {getItem() { throw new Error("blocked"); }, setItem() {}};
const S = {tools: [], user: {tools: [{name: "mytool", display: "My tool", task: "classification", track: "short_read", mode: "command"}]}, wiz: {values: {}}};
const setIfChanged = () => {}, applyKeyed = () => {}, $ = () => null, $$ = () => [], window = {};
""" + body + r"""
const data = %s; WF.data = data; WF.vals = {}; for (const s of data.steps) for (const it of s.items) if (it.setting_key) WF.vals[it.setting_key] = it.value ?? "";
const all = wfRows(), states = wfStates("tools"), out = {};
out.html = Object.fromEntries(data.steps.map(s => [s.id, wfStepHTML(s, all, states, "tools", 1)]));
out.html10 = wfStepHTML(data.steps.find(s => s.id === "tools"), all, states, "tools", 10);
S.tools = [{tool: "genomad", run_flag: "RUN_GENOMAD", enabled: true}, {tool: "platon", run_flag: "RUN_PLATON", enabled: false}];
const st2 = wfStates("tools"); out.changed = wfStepHTML(data.steps.find(s => s.id === "tools"), wfRows(), st2, "tools", 1);
S.tools = []; S.wiz.values = {genomad: "on"}; S.wiz.wf = {RUN_DIMER_DETECTION: "0"}; out.wiz = wfStates("wizard"); out.wizval = [wfValue(wfById(wfRows()).genomad, "wizard"), wfOverridden(wfById(wfRows()).genomad, "wizard"), wfValue(wfById(wfRows()).RUN_DIMER_DETECTION, "wizard")];
out.user = wfById(wfRows())["user:mytool"] ? wfById(wfRows())["user:mytool"].label : null;
out.dest = wfDest({cli_flag: "--flye-mob-recon"});
console.log(JSON.stringify(out));
""" % json.dumps(payload)
        path2 = Path(tempfile.mkdtemp()) / "smoke.js"
        path2.write_text(smoke, encoding="utf-8")
        done = subprocess.run([node, str(path2)], capture_output=True, text=True)
        try:
            sm = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            sm = {}
            check("the cards are drawn under node", False, (done.stderr or done.stdout)[:600])
        if sm:
            tools = sm["html"]["tools"]
            check("every step is drawn with its number and name", all(f'class="wfn"' in h for h in sm["html"].values()) and len(sm["html"]) == 10)
            check("a default-on tool shows On with a tick and its default-off neighbour shows Off with a cross", 'onoff on"><svg data-i="check"></svg>On</span>' in tools and 'onoff off"><svg data-i="x"></svg>Off</span>' in tools)
            check("a toggle is a real button with role=switch, aria-checked and a spoken label", 'role="switch"' in tools and 'aria-checked="true"' in tools and 'aria-checked="false"' in tools and "Press to turn" in tools)
            check("nothing is marked changed when everything is at its default", "chgtag" not in tools)
            check("a measured tool shows its time, memory and where the figure comes from", "Adds about 6.6 min" in tools and "3.8 GB peak memory" in tools and "estimated (measured)" in tools)
            check("a tool with no figure says 'not measured' and not a number", "Added cost: not measured" in tools)
            check("a documented floor is labelled documented", "32 GB peak memory" in tools and "estimated (documented)" in tools)
            check("badges: needs database, needs internet, needs an earlier step, needs an input", "needs database" in tools and "needs MOB-recon" in tools and "needs paired reads" in tools and "needs internet" in sm["html"]["download"] and "needs long reads" in sm["html"]["long_read"])
            check("per 10 isolates the time is scaled in the card", "Adds about 66 min" in sm["html10"] and "per 10 isolates" in sm["html10"], sm["html10"][:200])
            check("'What can I add here?' lists the optional tools that are off, with a Turn on button", "What can I add here?" in tools and 'data-wftoggle="genomad"' in tools)
            check("the demo methods are folded away and have no switch", "Demo methods (5)" in tools and 'data-wftoggle="mob_like"' not in tools)
            check("core items have no switch and say Always on", "Always on" in sm["html"]["assemble"] and 'data-wftoggle="core_trim_assemble"' not in sm["html"]["assemble"])
            check("a user tool appears under the Run the tools step", "user:mytool" in tools.replace("wfc_user_mytool", "user:mytool") and "your tool" in tools and sm["user"] == "My tool")
            ch = sm["changed"]
            check("an item changed from its default carries a 'changed' tag; a default-off tool that is now on shows On", 'chgtag' in ch and re.search(r'id="wfi_wfc_genomad"', ch) and 'class="wfi on" id="wfi_wfc_genomad"' in ch)
            check("a default-on tool that is now off shows Off and changed", 'class="wfi off" id="wfi_wfc_platon"' in ch)
            check("in the wizard a per-run choice and a per-run setting override the saved ones, and are the same stores the wizard uses", sm["wiz"]["genomad"] == "on" and sm["wiz"]["RUN_DIMER_DETECTION"] == "off" and sm["wizval"] == ["1", True, "0"], sm["wizval"])
            check("a flag names its wizard destination", sm["dest"] == "flye_mob_recon")

    print("static")
    check("the Tools page and the wizard each get a Workflow | List toggle", "data-wfview" in script and '[["workflow", "Workflow"], ["list", "List"]]' in script and 'dataset.ctx = "tools"' in script and 'dataset.ctx = "wizard"' in script)
    check("the wizard calls it after drawing the tool step; the existing list stays in the page", "wfAfterWizard();" in HTML and "function renderWizard()" in HTML and "Built-in tools" in HTML)
    check("a toggle writes the same saved setting as the list switch and the Settings page (POST /api/settings), and clears with null", 'api("settings", {changes: set})' in script and '"default" ? null' in script)
    check("in the wizard it writes the wizard's own per-run state (the tool buttons' value, S.wiz.wf for items with no flag), not a new store", "V[d] =" in script and "S.wiz.wf" in HTML and "Object.assign(d, S.wiz.wf)" in HTML)
    check("the view is chosen with localStorage only inside try/catch", "try { const v = localStorage.getItem" in script and "try { localStorage.setItem" in script)
    check("the chain is read from GET /api/workflow", 'api("workflow")' in script)
    check("keyed rendering: step cards are patched by key and the summary is only redrawn when it changed", "applyKeyed(list, items" in script and "setIfChanged(top, head)" in script)
    check("focus survives a redraw (by element id)", "document.activeElement.id" in script and "b.focus({preventScroll: true})" in script)
    check("dependencies use the designed dialog: turning on something that needs a disabled step offers to turn it on, turning off something others need warns",
          "This needs an earlier step" in script and "Other steps need this one" in script and script.count("modalDialog(") >= 2 and "wfMissingRequires(" in script and "wfDependentsOn(" in script)
    check("no browser confirm, prompt or alert is used", not re.search(r"(?<![A-Za-z_.])(confirm|prompt|alert)\(", script))
    check("keyboard: toggles are buttons with role=switch, the view and per-N choices are buttons with aria-pressed, the chain is an ordered list, jump links are anchors",
          'role="switch"' in script and 'aria-pressed="${WF.view === k}"' in script and '<ol class="wfchain"' in script and "data-wfjump" in script and 'aria-live="polite"' in script)
    check("a total estimate bar says 'estimated' and recalculates on every render", "This selection adds about" in script and 'class="tag">estimated</span>' in script and "wfEstimate(rows, states, per)" in script)
    check("a summary 'Enabled extras' strip and a 'What can I add here?' list per step", "Enabled extras" in script and "What can I add here?" in script)
    check("phone width: the chain collapses to one column with a 16px-or-less gutter and no horizontal page scroll", "@media (max-width:640px)" in style and ".wfstep{margin-left:14px" in style)
    check("the new controls have help text from the server", all(f'wizTip("{k}")' in script for k in ("workflow_view", "workflow_estimate", "workflow_colours")))

    print("colour rule")
    light = dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6})", re.search(r":root\{(--on:[^}]*)\}", style).group(1)))
    dark = dict(re.findall(r"--([a-z-]+):(#[0-9a-fA-F]{6})", re.search(r":root\[data-theme=dark\]\{(--on:[^}]*)\}", style).group(1)))
    check("tokens --on, --on-bg, --off, --off-bg exist for light and dark", {"on", "on-bg", "off", "off-bg"} <= set(light) and {"on", "on-bg", "off", "off-bg"} <= set(dark), (light, dark))
    check("Off is a different colour from On in both themes (and Off's tint from On's)", light["off"] != light["on"] and dark["off"] != dark["on"] and light["off-bg"] != light["on-bg"] and dark["off-bg"] != dark["on-bg"])
    base = {"light": {"surface": "#ffffff"}, "dark": {"surface": "#1f2226"}}
    for theme, t in (("light", light), ("dark", dark)):
        pairs = {"On text on its tint": (t["on"], t["on-bg"]), "Off text on its tint": (t["off"], t["off-bg"]), "On text on the surface": (t["on"], base[theme]["surface"]),
                 "Off text on the surface": (t["off"], base[theme]["surface"]), "On solid with its ink": (t["on-ink"], t["on-solid"]), "Off solid with its ink": (t["off-ink"], t["off-solid"])}
        for what, (fg, bg) in pairs.items():
            check(f"{theme}: {what} has contrast >= 4.5:1 (WCAG AA)", contrast(fg, bg) >= 4.5, round(contrast(fg, bg), 2))
    ok_hue = re.search(r"--ok:(#[0-9a-f]{6})", HTML).group(1), re.search(r"--bad:(#[0-9a-f]{6})", HTML).group(1), re.search(r"--warn:(#[0-9a-f]{6})", HTML).group(1)
    check("Off is not the error red, the warning amber or the help green, so those keep their meaning", light["off"] not in ok_hue and light["off"].lower() not in ("#b3261e", "#8a5a00"))
    check("never colour alone: the pill carries the word On / Off, a tick or a cross, and Off has a dashed outline", ".onoff.off{" in style and "dashed" in style.split(".onoff.off{")[1].split("}")[0] and 'icon("check")' in script and 'icon("x")' in script and ">Off<" not in "" and '"Off"' in script)
    check("the existing controls use the same colours: switch, tri-state buttons, the on/off text in the tools table, flag selects", all(n in style for n in (".switch input:checked+span{background:var(--on-solid)}", ".tri button.on.off{background:var(--off-solid)", "b[data-flagtxt].mut{color:var(--off)}", "select[data-st=off]")))
    check("the default button of a tool takes its default's colour (def-on / def-off) and the tool's row gets a 'changed' tag", ".def-off{background:var(--off-solid)" in style and "def-on" in script and "chgtag" in script)
    check("the colour rule is stated in the page for the reader (legend) and in the server help", "An item at its default shows its default colour." in script and "default-off tool shows Off" in (ROOT / "plasbench" / "ui_help.py").read_text(encoding="utf-8"))
    check("the existing green help mark, warnings and errors are untouched", "--ok:#1e7a3c" in HTML and "--warn:#8a5a00" in HTML and "--bad:#b3261e" in HTML)
    rw = re.search(r"^function renderWizard\(\) \{.*?^\}", HTML, re.S | re.M)
    check("the only change inside the existing wizard code is the hook call at the end of renderWizard", bool(rw) and "wfAfterWizard();" in rw.group(0).split("bindWizard();")[-1], rw.group(0)[-120:] if rw else "")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
