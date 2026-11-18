#!/usr/bin/env python3
"""Add your own tool: several tasks, several sources, several outputs (plasbench/data/ui.html, plasbench/webui.py, plasbench/ui_help.py).

  - the form model <-> manifest text functions (the UTPURE block of ui.html) run under node (skipped with a printed reason when node is missing): a task list with the
    primary first, a single output as a plain [output], several as [output.<format>] sections, auto as format = auto + candidates, a text -> model -> text round trip,
    the live source checks (https only, SHA-256 shape, "not pinned"), the output problems with their fixes, task status wording, type-ahead, the Tools-page source line;
  - static checks of the page: the multi-select (roles, aria-multiselectable, chips, primary tag, keys, type-ahead, outside click), the source selector, the output rows,
    the upload control, designed dialogs only, and `node --check` of the page script;
  - the upload route over HTTP (token required, size cap, a name with a separator or '..', a bad tool name, binary content), and store_tool_upload itself;
  - /api/usertools carries the help sentences, /api/usertools/validate has the same shape with or without the backend's richer check (a stub of it is tried too).
Standard library only. There is no browser here: nothing in this test draws the page.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


NODE_TEST = r"""
const out = {};
const M = utBlank();
M.tool.name = "t1"; M.tool.task = "binning_reconstruction, classification";
let text = utModelToText(M);
out.taskLine = text.split("\n").find(l => l.startsWith("task ="));
out.single = /\[output\]\nformat = contig_bins\npath = bins.tsv/.test(text) && !text.includes("[output.");
// several outputs
M.out.rows.push(utNewRow("plasmid_fasta"));
text = utModelToText(M);
out.multiHead = /\[output\]\nformat = contig_bins, plasmid_fasta\n/.test(text);
out.multiSecs = text.includes("[output.contig_bins]") && text.includes("[output.plasmid_fasta]") && /\[output\.plasmid_fasta\]\npath = plasmids.fasta/.test(text);
const back = utTextToModel(text);
out.roundRows = back.out.rows.map(r => r.format).join();
out.roundPath = back.out.rows[0].path + "|" + back.out.rows[1].path;
out.roundText = utModelToText(back) === text;
// auto
M.out.auto = true; M.out.candidates = "bins.tsv, *.labels.tsv";
text = utModelToText(M);
out.auto = /\[output\]\nformat = auto\ncandidates = bins.tsv, \*.labels.tsv\n/.test(text) && !text.includes("path = bins");
const a2 = utTextToModel(text);
out.autoBack = a2.out.auto === true && a2.out.candidates === "bins.tsv, *.labels.tsv";
// an existing single-task manifest loads as a one-item selection, and a legacy output section is one row
const legacy = "[tool]\nname = old\ntask = classification\nanalysis_track = short_read\n[install]\nmethod = none\n[run]\nmode = command\ncommand = x {contigs}\nrequires = contigs\n[output]\nformat = contig_labels\npath = x.tsv\nlabel_column = 2\n";
const L = utTextToModel(legacy);
out.legacyTasks = JSON.stringify(utTaskList(L.tool.task));
out.legacyRow = L.out.rows.length + ":" + L.out.rows[0].format + ":" + L.out.rows[0].label_column;
out.legacyText = utModelToText(L).includes("task = classification") && utModelToText(L).includes("[output]\nformat = contig_labels\npath = x.tsv\nlabel_column = 2");
// tasks
out.toggle = JSON.stringify([utToggleTask(["a"], "b"), utToggleTask(["a", "b"], "a")]);
out.move = JSON.stringify([utMoveTask(["a", "b", "c"], "c", -1), utMoveTask(["a", "b"], "a", -1), utMoveTask(["a", "b"], "b", 1)]);
out.dedupe = JSON.stringify(utTaskList("a, b ,a,,c"));
out.primaryFirst = utModelToText(Object.assign(utBlank(), {tool: {name: "z", task: "classification, binning_reconstruction", analysis_track: "short_read"}})).includes("task = classification, binning_reconstruction");
out.status = [utStatusText({status: "native"}), utStatusText({status: "derived", how: "contig_bins"}), utStatusText({status: "derived", how: "derived from contig_bins"}),
              utStatusText({status: "not_possible", how: "labels carry no bins"}), utStatusText(null)].join("|");
out.cls = [utStatusClass("native"), utStatusClass("derived"), utStatusClass("not_possible")].join();
// type-ahead
const labels = ["Classification", "Binning reconstruction", "Sequence reassembly"];
out.ta = [utTypeahead(labels, "b", 0), utTypeahead(labels, "se", 0), utTypeahead(labels, "c", 0), utTypeahead(labels, "c", -1), utTypeahead(labels, "z", 0), utTypeahead(labels, "", 0)].join();
// source
const S1 = utBlank(); S1.install = {method: "url", url: "http://x.org/a.tgz"};
out.http = utSourceProblems(S1).errors.length + ":" + /https/.test(utSourceProblems(S1).errors[0]);
S1.install.url = "https://x.org/a.tgz";
out.pinWarn = utSourceProblems(S1).errors.length + ":" + utSourceProblems(S1).warnings.some(w => /Not pinned/.test(w));
S1.install.sha256 = "abc"; out.badSha = utSourceProblems(S1).errors.length;
S1.install.sha256 = "a".repeat(64); out.goodSha = utSourceProblems(S1).errors.length + ":" + utSourceProblems(S1).warnings.length;
S1.install.url = "file:///etc/passwd"; out.file = utSourceProblems(S1).errors.length;
S1.install.url = ""; out.emptyUrl = utSourceProblems(S1).errors.length;
const S2 = utBlank(); S2.install = {method: "local", path: ""}; out.localNoPath = utSourceProblems(S2).errors.length;
S2.install = {method: "local", path: "C:\\tools\\x", mode: "copy"}; out.localCopy = utSourceProblems(S2).errors.length + ":" + utSourceProblems(S2).warnings.length;
S2.install.mode = "link"; out.localLink = utSourceProblems(S2).warnings.length;
out.srcOf = ["none", "conda", "pip", "url", "local", "script", undefined].map(m => utSourceOf({install: {method: m}})).join();
out.srcMethod = [utSourceMethod("installed", S1), utSourceMethod("package", {install: {method: "pip"}}), utSourceMethod("package", S1), utSourceMethod("url", S1)].join();
// the url/local keys are written only for their source
S1.install = {method: "url", url: "https://x.org/a.tgz", sha256: "a".repeat(64), kind: "archive", build_command: "make", packages: "stale"};
text = utModelToText(S1);
out.urlText = text.includes("method = url") && text.includes("url = https://x.org/a.tgz") && text.includes("kind = archive") && text.includes("build_command = make") && !text.includes("packages");
S1.install = {method: "local", path: "/opt/tool", mode: "copy", url: "https://stale"};
text = utModelToText(S1); out.localText = text.includes("path = /opt/tool") && text.includes("mode = copy") && !text.includes("https://stale");
S1.install = {method: "url", url: "https://x.org/r.git", kind: "archive", ref: "v1"}; out.refHidden = !utModelToText(S1).includes("ref = v1");
S1.install.kind = "git"; out.refShown = utModelToText(S1).includes("ref = v1");
// the same text read back keeps the source
const U = utTextToModel("[tool]\nname = u\ntask = classification\n[install]\nmethod = url\nurl = https://x.org/a.tgz\nsha256 = " + "b".repeat(64) + "\nkind = archive\n");
out.urlBack = U.install.method + "|" + U.install.url + "|" + U.install.sha256.length + "|" + U.install.kind;
// outputs
const O1 = utBlank(); O1.out.rows = [utNewRow("contig_bins"), utNewRow("contig_bins")];
out.dup = utOutputProblems(O1).some(p => /already used/.test(p) && /remove it/.test(p));
O1.out.rows = []; out.none = utOutputProblems(O1).length;
O1.out = {auto: true, candidates: ""}; out.autoNoCand = utOutputProblems(O1).length;
O1.out = {auto: false, candidates: "", rows: [{format: "contig_labels", path: "x.tsv"}]}; out.labelsNoCol = utOutputProblems(O1).some(p => /label column or a probability column/.test(p));
O1.out.rows = [{format: "adapter", path: "o"}]; out.adapterNoScript = utOutputProblems(O1).some(p => /adapter script/.test(p));
O1.out.rows = [utNewRow("contig_bins"), utNewRow("plasmid_fasta"), utNewRow("fasta_dir")]; out.okRows = utOutputProblems(O1).length;
// keys revealed per format
out.keys = ["contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter"].map(f => utOutKeys(f).map(x => x[0]).join("+")).join("/");
// import mode writes no path
const I = utBlank(); I.run = {mode: "import", dir: "/r", pattern: "{sample}.tsv"}; out.importNoPath = !/\npath = /.test(utModelToText(I).split("[output]")[1]);
// the Tools page source line
out.line = [utSourceLine({install_source: "url", sha256: ""}), utSourceLine({install_source: "local", sha256: "0123456789abcdef0123"}), utSourceLine({install_source: "conda"}), utSourceLine({install_source: "installed"}), utSourceLine({})].join("|");
out.toolTasks = JSON.stringify([utToolTasks({tasks: ["a", "b"], task: "a"}), utToolTasks({task: "c"}), utToolTasks({})]);
// an unknown section and an unknown key are kept
const K = utTextToModel("[tool]\nname = k\ntask = classification\nfuture = 1\n[meta]\nx = 2\n");
out.keep = utModelToText(K).includes("future = 1") && utModelToText(K).includes("[meta]\nx = 2");
console.log(JSON.stringify(out));
"""


def run_node(pure):
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the manifest functions are not executed (the static checks below still run)")
        return
    path = Path(tempfile.mkdtemp()) / "ut.js"
    path.write_text(pure + NODE_TEST, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("node runs the manifest functions", done.returncode == 0, done.stderr[:500])
    if done.returncode:
        return
    o = json.loads(done.stdout.strip().splitlines()[-1])
    check("a task list is written as task = a, b with the first as primary", o["taskLine"] == "task = binning_reconstruction, classification" and o["primaryFirst"], o["taskLine"])
    check("one output is a plain [output] section", o["single"])
    check("several outputs: format = a, b and one [output.<format>] section each", o["multiHead"] and o["multiSecs"], o)
    check("several outputs read back into rows and write back identically", o["roundRows"] == "contig_bins,plasmid_fasta" and o["roundPath"] == "bins.tsv|plasmids.fasta" and o["roundText"], o)
    check("auto detection: format = auto + candidates, and it reads back", o["auto"] and o["autoBack"], o)
    check("an existing single-task manifest is a one-chip selection with one output row", o["legacyTasks"] == '["classification"]' and o["legacyRow"] == "1:contig_labels:2" and o["legacyText"], o)
    check("toggling and reordering tasks", o["toggle"] == '[["a","b"],["b"]]' and o["move"] == '[["a","c","b"],["a","b"],["a","b"]]' and o["dedupe"] == '["a","b","c"]', o)
    check("status wording: native, derived from <output>, not possible: <reason>", o["status"] == "native|derived from contig_bins|derived from contig_bins|not possible: labels carry no bins|", o["status"])
    check("status colours", o["cls"] == "ok,warn,bad", o["cls"])
    ta = o["ta"].split(",")
    check("type-ahead: b -> Binning, se -> Sequence, c from 0 -> next C (cycles), z -> none", ta[0] == "1" and ta[1] == "2" and ta[4] == "-1" and ta[5] == "-1", o["ta"])
    check("a non-https address is rejected live, with the reason", o["http"] == "1:true" and o["file"] == 1 and o["emptyUrl"] == 1, o)
    check("an empty SHA-256 is a warning (not pinned), a malformed one an error, a good one clean", o["pinWarn"] == "0:true" and o["badSha"] == 1 and o["goodSha"] == "0:0", o)
    check("a local source needs a path; link warns, copy does not", o["localNoPath"] == 1 and o["localCopy"] == "0:0" and o["localLink"] == 1, o)
    check("the source follows install.method", o["srcOf"] == "installed,package,package,url,local,script,installed" and o["srcMethod"] == "none,pip,conda,url", o)
    check("url and local keys are written only for their own source; ref only for git", o["urlText"] and o["localText"] and o["refHidden"] and o["refShown"], o)
    check("a url source reads back", o["urlBack"] == "url|https://x.org/a.tgz|64|archive", o["urlBack"])
    check("output problems carry their fix", o["dup"] and o["none"] == 1 and o["autoNoCand"] == 1 and o["labelsNoCol"] and o["adapterNoScript"] and o["okRows"] == 0, o)
    check("each format reveals only its own keys", o["keys"] == "delimiter+header+contig_column+bin_column+contig_id_from+contig_id_strip_regex/delimiter+header+contig_column+label_column+plasmid_values+score_column+threshold+contig_id_from+contig_id_strip_regex//fasta_glob/adapter", o["keys"])
    check("import mode writes no output path", o["importNoPath"])
    check("the Tools-page source line: url/local show the pin, others the source", o["line"] == "source: URL · not pinned|source: local file · sha256 0123456789ab…|source: conda|source: already installed|", o["line"])
    check("a tool's tasks: its list, else its one task", o["toolTasks"] == '[["a","b"],["c"],[]]', o["toolTasks"])
    check("unknown keys and sections survive a form round trip", o["keep"])


RENDER_TEST = r"""
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = (n, cls) => `<svg class="${cls || "ico sm"}"><use href="#i-${n}"/></svg>`;
const tipBtn = (t, label) => t ? `<button class="tipi" aria-label="Help: ${esc(label)}">i</button>` : "";
const S = {schema: {usertool_help: new Proxy({}, {get: (o, k) => ({summary: String(k)})})}, user: {task_help: {classification: "Labels each contig.", binning_reconstruction: "Groups contigs.", sequence_reassembly: "Makes sequences."}, source_help: {url: "Downloads it."}, format_help: {contig_bins: "A table of bins."}, placeholders: {contigs: "the contigs"}}};
const taskLabel = t => String(t).replace(/_/g, " ");
const document = {addEventListener() {}, querySelectorAll() { return []; }, getElementById() { return null; }};
const $ = () => null, $$ = () => [];
@@CODE@@
const out = {};
UT = utBlank(); UT.tool.task = "binning_reconstruction, classification"; UT.tool.name = "t1";
utLast = {ok: true, tasks: [{task: "binning_reconstruction", status: "native", how: "contig_bins"}, {task: "classification", status: "derived", how: "contig_bins"}, {task: "sequence_reassembly", status: "not_possible", how: "no plasmid FASTA output"}],
          outputs: [{format: "contig_bins", path: "bins.tsv", serves: ["binning_reconstruction", "classification"], rule: "a contig in a bin is a plasmid contig"}], warnings: ["w1"], source: {}};
const task = utFieldHTML("tool", UT_FIELDS.tool.find(f => f[0] === "task"));
out.msRoles = ['role="listbox"', 'aria-multiselectable="true"', 'aria-haspopup="listbox"', 'aria-expanded="false"', 'role="option"'].every(x => task.includes(x));
out.msChips = (task.match(/class="ms-chip"/g) || []).length + ":" + (task.match(/class="ms-pri">primary/g) || []).length;
out.msSelected = (task.match(/aria-selected="true"/g) || []).length + ":" + (task.match(/aria-selected="false"/g) || []).length;
out.msStatus = ["native", "derived from contig_bins", "not possible: no plasmid FASTA output"].every(x => task.includes(">" + x + "<"));
out.msDesc = task.includes("Groups contigs.") && task.includes("Makes sequences.");
out.msNa = /ms-na/.test(task) && !/disabled|aria-disabled/.test(task.split("<ul")[1].split("</ul>")[0]);
out.msOrder = task.includes('aria-label="Move Classification earlier"') && task.includes('aria-label="Move Binning reconstruction later"');
out.msLabelled = task.includes('aria-labelledby="ut_task_lbl ut_tool_task_btn"') && task.includes('id="ut_tool_task_btn"');
UT.tool.task = "classification"; const one = utFieldHTML("tool", UT_FIELDS.tool.find(f => f[0] === "task"));
out.oneChip = (one.match(/class="ms-chip"/g) || []).length === 1 && !one.includes("ms-mv");
const src = {};
for (const m of ["none", "conda", "url", "local", "script"]) { UT.install = {method: m}; src[m] = utSourceHTML(); }
out.srcCards = UT_SOURCES.every(([id]) => src.url.includes(`value="${id}"`)) && (src.url.match(/type="radio"/g) || []).length === 5 && (src.url.match(/checked/g) || []).length === 1;
out.srcWarn = Object.values(src).every(h => h.includes("PlasBench will run code you download or point to"));
out.srcPkg = src.conda.includes('id="ut_install_method"') && !src.url.includes('id="ut_install_method"');
out.srcHelp = src.url.includes("Downloads it.");
const fields = m => { UT.install = Object.assign({method: m}, m === "url" ? {kind: "git"} : {}); return UT_FIELDS.install.filter(f => utVisible(f[4], UT) && f[0] !== "method").map(f => f[0]).join(); };
out.fUrl = fields("url"); out.fLocal = fields("local"); out.fScript = fields("script"); out.fConda = fields("conda");
UT.install = {method: "local", path: "/x"}; const lp = utFieldHTML("install", UT_FIELDS.install.find(f => f[0] === "path"));
out.localBtns = lp.includes("Choose file…") && lp.includes("Choose folder…") && lp.includes('data-dir="0"') && lp.includes('data-dir="1"');
UT.install = {method: "script"}; const up = utFieldHTML("install", UT_FIELDS.install.find(f => f[0] === "script"));
out.upload = up.includes("data-upload=") && up.includes('type="file"') && up.includes("Upload from this computer");
UT.install = {method: "conda"}; UT.out = {auto: false, candidates: "", rows: [utNewRow("contig_bins"), utNewRow("contig_labels")]};
const o2 = utOutHTML();
out.rows = (o2.match(/class="outrow"/g) || []).length + ":" + (o2.match(/data-outdel=/g) || []).length;
out.rowFormats = o2.includes('id="ut_out_0_format"') && o2.includes('id="ut_out_1_format"') && /<option value="contig_bins" selected/.test(o2);
out.usedDisabled = /<option value="contig_labels" +disabled/.test(o2.split('id="ut_out_0_format"')[1].split("</select>")[0]);
out.labelKeys = o2.includes('data-k="label_column"') && o2.includes('data-k="plasmid_values"') && o2.includes('data-k="bin_column"') && !o2.includes('data-k="fasta_glob"') && !o2.includes('data-k="adapter"');
out.serve = o2.includes('data-serve="contig_bins"') && o2.includes('id="ut_out_errs"');
UT.out.rows = [utNewRow("fasta_dir")]; const o1 = utOutHTML(); out.oneNoRemove = !o1.includes("data-outdel") && o1.includes('data-k="fasta_glob"');
UT.out.rows = UT_FORMATS.map(utNewRow); out.allUsed = utOutHTML().includes('id="ut_outadd" disabled');
UT.out = {auto: true, candidates: "a.tsv"}; const oa = utOutHTML(); out.auto = oa.includes('data-out="candidates"') && oa.includes('value="a.tsv"') && !oa.includes('class="outrow"');
UT.run.mode = "import"; UT.out = {auto: false, candidates: "", rows: [utNewRow("contig_bins")]}; out.importNoPath = !utOutHTML().includes('data-k="path"');
UT.run.mode = "command";
UT.install = {method: "url", url: "https://x.org/a.tgz"}; UT.tool.task = "binning_reconstruction, classification";
const ok = utCheckHTML(utLast, utSourceProblems(UT));
out.chkTable = ok.includes("<th>Task</th><th>Result</th><th>How</th>") && ok.includes("derived") && ok.includes("not possible") && ok.includes("primary");
out.chkWarn = ok.includes("w1") && ok.includes("Not pinned");
out.chkOut = ok.includes("serves") && ok.includes("a contig in a bin is a plasmid contig");
UT.install.url = "http://x.org/a";
const bad = utCheckHTML({ok: true, tasks: [], outputs: []}, utSourceProblems(UT));
out.chkBad = bad.includes("thing") && bad.includes("Only https://");
const inv = utCheckHTML({ok: false, problems: ["[output] ambiguous"], tasks: []}, {errors: [], warnings: []});
out.chkInvalid = inv.includes("1 thing to fix") && inv.includes("ambiguous");
let n = 0; for (const m of ["none", "conda", "pip", "url", "local", "script"]) for (const mode of ["command", "import"]) { UT.install = {method: m, kind: "git"}; UT.run.mode = mode;
  for (const sec of Object.keys(UT_FIELDS)) for (const f of UT_FIELDS[sec]) if (utVisible(f[4], UT)) { utFieldHTML(sec, f); n++; } }
out.rendered = n > 100;
console.log(JSON.stringify(out));
"""


def run_render(page):
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the form's HTML builders are not executed")
        return
    a = page.index("const UT_TITLES = ")
    b = page.index("/* ---- events ---- */")
    pure = page.split("/* ==UTPURE-BEGIN== (no DOM here: tested under node by test/test_ut_multi_task_ui.py) */")[1].split("/* ==UTPURE-END== */")[0]
    path = Path(tempfile.mkdtemp()) / "render.js"
    path.write_text(RENDER_TEST.replace("@@CODE@@", pure + "\n" + page[a:b]), encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("the form's HTML builders run under node with a stub page", done.returncode == 0, (done.stderr or done.stdout)[-600:])
    if done.returncode:
        return
    o = json.loads(done.stdout.strip().splitlines()[-1])
    check("multi-select markup: listbox, aria-multiselectable, options, popup button, labelled", o["msRoles"] and o["msLabelled"], o)
    check("multi-select shows the chosen tasks as chips, the first tagged primary, and selection state", o["msChips"] == "2:1" and o["msSelected"] == "2:1", o)
    check("each option carries its explanation and the live status (native / derived from / not possible: reason)", o["msStatus"] and o["msDesc"], o)
    check("a not-possible task is dimmed but selectable", o["msNa"], o)
    check("reorder buttons are labelled; one chosen task has none", o["msOrder"] and o["oneChip"], o)
    check("source selector: five radio cards, one checked, the trust warning on every source, the package manager choice only for packages", o["srcCards"] and o["srcWarn"] and o["srcPkg"] and o["srcHelp"], o)
    check("the fields follow the source", o["fUrl"] == "url,sha256,kind,ref,build_command,env_name,verify_command" and o["fLocal"] == "path,mode,build_command,env_name,verify_command"
          and o["fScript"] == "script,env_name,verify_command" and o["fConda"] == "packages,channels,pip_packages,env_name,verify_command", o)
    check("local path has Choose file / Choose folder; script has an upload button with a file input", o["localBtns"] and o["upload"], o)
    check("output rows: one per output, remove only when several, formats already used are disabled in other rows", o["rows"] == "2:2" and o["rowFormats"] and o["usedDisabled"] and o["oneNoRemove"], o)
    check("each row shows only its format's keys; each row has a place for which task it serves and inline errors", o["labelKeys"] and o["serve"], o)
    check("Add another output is disabled when every format is used; auto shows the candidates field only; import hides the path", o["allUsed"] and o["auto"] and o["importNoPath"], o)
    check("check panel: per-task table with primary, warnings, outputs and the rule used", o["chkTable"] and o["chkWarn"] and o["chkOut"], o)
    check("check panel: a source error makes it invalid even if the server said ok; server problems are listed", o["chkBad"] and o["chkInvalid"], o)
    check("every visible field renders for every source and mode", o["rendered"], o)


def static_checks():
    check("the page has the UTPURE block", "/* ==UTPURE-BEGIN==" in HTML and "/* ==UTPURE-END== */" in HTML)
    # multi-select
    for needle, what in (('role="listbox" aria-multiselectable="true"', "listbox, aria-multiselectable"), ('role="option"', "options"), ('aria-selected="${sel.includes(o.value)}"', "aria-selected on options"),
                         ('aria-haspopup="listbox" aria-expanded="false"', "a button that opens the popup"), ('aria-activedescendant', "active descendant"), ('class="ms-chip"', "chips"),
                         ('class="ms-pri">primary', "the primary tag"), ('data-mv="-1"', "reorder earlier"), ('data-mv="1"', "reorder later"),
                         ('e.key === "ArrowDown"', "Down"), ('e.key === "ArrowUp"', "Up"), ('e.key === "Home"', "Home"), ('e.key === "End"', "End"), ('e.key === " "', "Space"),
                         ('e.key === "Escape"', "Escape"), ('e.key === "Enter"', "Enter"), ("utTypeahead(", "type-ahead"), ('document.addEventListener("mousedown"', "closes on an outside click"),
                         ("e.altKey", "Alt+arrows reorder")):
        check(f"multi-select: {what}", needle in HTML, needle)
    check("the Task field is the multi-select, writing task = a, b", '["task","Task","tasks"' in HTML and 'UT.tool.task = list.join(", ")' in HTML)
    check("each task option shows its explanation and the live status", "o.desc" in HTML and "utStatusText(st)" in HTML and "task_help" in HTML and 'class="ms-st ' in HTML)
    check("a task that is not possible stays selectable (dimmed, not disabled)", '"ms-na"' in HTML and "aria-disabled" not in HTML.split("function msOptionsHTML")[1].split("function msOrderHTML")[0])
    check("dark theme and phone width: the component uses theme variables and a narrow-screen rule", ".ms-list{" in HTML and "var(--surface)" in HTML.split(".ms-list{")[1][:300] and "@media (max-width:640px){.ms{max-width:none}" in HTML)
    check("no library", not re.search(r"<script[^>]+src=", HTML))
    # source selector
    check("the Source selector is a radio group of five cards", 'role="radiogroup" aria-labelledby="ut_src_lbl"' in HTML and all(l in HTML for l in (
        "Already installed on this computer", "Package manager", "Download from a URL", "A file or folder on this computer", "My own install script")))
    check("the trust warning is visible", "PlasBench will run code you download or point to. Only use sources you trust; nothing is downloaded or run until you press Save &amp; install." in HTML)
    check("URL fields: https address, SHA-256, kind, ref, build command", all(f'["{k}",' in HTML for k in ("url", "sha256", "kind", "ref", "build_command")) and "Only https://" in HTML)
    check("local: a path with Choose file / Choose folder through the existing chooser, link or copy", "Choose file…" in HTML and "Choose folder…" in HTML and 'data-dir="0"' in HTML and 'select:link|copy' in HTML)
    check("local: link and copy are explained", "copy records a checksum and is reproducible" in HTML and "link follows the file as it changes" in HTML)
    # outputs
    check("output rows: add, remove, a format select per row, the keys of the format", 'id="ut_outadd"' in HTML and "data-outdel" in HTML and 'data-k="format"' in HTML and "utOutKeys(r.format)" in HTML)
    check("output: Detect automatically with a candidates field", "Detect automatically" in HTML and 'data-out="candidates"' in HTML)
    check("output: which task each output serves, and inline problems with fixes", "data-serve" in HTML and 'id="ut_out_errs"' in HTML and "utOutputProblems(UT)" in HTML)
    # upload
    check("upload: a client-side file read, sent as text to the upload route, with a size cap and a message that large tools are located", 'api("usertools/upload"' in HTML and "file.text()" in HTML
          and "uploads are limited to" in HTML and "A large tool is located, not uploaded" in HTML)
    # check panel, Tools page, wizard
    check("the check panel has the per-task table, the source summary and the warnings", "<th>Task</th><th>Result</th><th>How</th>" in HTML and "utSourceSummary(UT)" in HTML and "utCheckHTML" in HTML)
    check("the Tools page shows one chip per task and the source", "utToolTasks(t).map" in HTML and "utSourceLine(t)" in HTML)
    check("the wizard's own-tools list shows one chip per task and the source", "utToolTasks(u).map" in HTML and "utSourceLine(u)" in HTML)
    check("the guide explains several tasks, sources and outputs, and has the two new examples", all(k in HTML for k in ('id="uh_multi"', 'id="uh_src"', 'id="uh_ex2"', 'id="uh_ex3"', "data-uhex=\"multi\"", "data-uhex=\"url\"", "UT_EXAMPLE_MULTI", "UT_EXAMPLE_URL")))
    # dialogs
    outside = HTML
    check("no alert( / confirm( / prompt( anywhere in the new code", not re.findall(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", outside.split("let DLG_N = 0;")[0] + outside.split("/* ---- help tooltip: an (i) button")[1]))
    check("the example loader asks with the designed dialog", "await askConfirm({title: \"Replace the form with the example?\"" in HTML)
    # the page script
    node = shutil.which("node")
    if node:
        script = max(re.findall(r"<script>(.*?)</script>", HTML, re.S), key=len)
        path = Path(tempfile.mkdtemp()) / "page.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        check("node --check of the page script passes", done.returncode == 0, done.stderr[:300])
    else:
        print("  skip  node not found: page script not syntax-checked")


def http_checks():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    os.environ["PLASBENCH_TOOLS_PATH"] = str(tmp / "tools")
    (tmp / "home").mkdir()
    (tmp / "local.env").write_text("", encoding="utf-8")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, tok=True):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if tok:
            h["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    folder = tmp / "home" / ".plasbench" / "tools" / "up_tool"
    good = {"name": "up_tool", "filename": "install.sh", "text": "#!/bin/bash\r\necho hi\r\n"}
    print("the upload route")
    check("without the token it is refused", call("/api/usertools/upload", good, tok=False)[0] == 403)
    code, r = call("/api/usertools/upload", good)
    check("a small script is stored in the tool's own folder and the relative path is returned", code == 200 and r["path"] == "install.sh" and (folder / "install.sh").is_file(), (code, r))
    check("its line endings are stored as LF (it must run under bash)", (folder / "install.sh").read_bytes() == b"#!/bin/bash\necho hi\n")
    for bad_name in ("../evil.sh", "a/b.sh", "a\\b.sh", "..", "C:evil.sh", ".hidden", "x..y", "", "plasbench-tool.ini", "a\x00b"):
        code, r = call("/api/usertools/upload", dict(good, filename=bad_name))
        check(f"the file name {bad_name!r} is refused", code == 400 and "error" in r, (code, r))
    for bad_tool in ("../up", "Up_Tool", "a/b", "", "x", "up tool"):
        code, r = call("/api/usertools/upload", dict(good, name=bad_tool))
        check(f"the tool name {bad_tool!r} is refused", code == 400 and "name" in r.get("error", ""), (code, r))
    check("nothing was written outside the tool's folder", not (tmp / "home" / ".plasbench" / "evil.sh").exists() and not (tmp / "home" / ".plasbench" / "tools" / "evil.sh").exists())
    big = "x" * (webui.UPLOAD_MAX_BYTES + 1)
    code, r = call("/api/usertools/upload", dict(good, filename="big.sh", text=big))
    check("a file over 5 MB is refused with the reason and the advice to locate it", code == 400 and "5 MB" in r["error"] and "Locate" in r["error"] and not (folder / "big.sh").exists(), (code, r))
    atcap = "y" * webui.UPLOAD_MAX_BYTES
    code, r = call("/api/usertools/upload", dict(good, filename="cap.sh", text=atcap))
    check("a file of exactly 5 MB is accepted", code == 200 and (folder / "cap.sh").stat().st_size == webui.UPLOAD_MAX_BYTES, (code, str(r)[:100]))
    code, r = call("/api/usertools/upload", dict(good, filename="bin.dat", text="a\x00b"))
    check("binary content is refused", code == 400 and "text" in r["error"], (code, r))
    code, r = call("/api/usertools/upload", {"name": "up_tool", "filename": 5, "text": "x"})
    check("a non-string file name is refused", code == 400, (code, r))
    check("the manifest cannot be overwritten through the upload route", call("/api/usertools/upload", dict(good, filename="PlasBench-Tool.ini"))[0] == 400)
    try:
        webui.store_tool_upload("up_tool", "../x", "a")
        check("store_tool_upload refuses a traversal", False)
    except ValueError:
        check("store_tool_upload refuses a traversal", True)

    print("the user-tool API")
    code, lst = call("/api/usertools")
    check("/api/usertools carries one plain sentence per task, format and source", code == 200 and all(lst[k] for k in ("task_help", "format_help", "source_help")) and set(lst["task_help"]) >= {"classification", "binning_reconstruction", "sequence_reassembly"}
          and lst["upload_max_bytes"] == 5 * 1024 * 1024, list(lst))
    ini = ("[tool]\nname = ui_tool\ntask = classification\nanalysis_track = short_read\n[install]\nmethod = none\n"
           "[run]\nmode = command\ncommand = echo {contigs}\nrequires = contigs\n[output]\nformat = contig_labels\npath = x.tsv\nlabel_column = 2\n")
    code, r = call("/api/usertools/validate", {"text": ini})
    check("validate always answers with tasks, source and outputs, so the page has one code path", code == 200 and r["ok"] and isinstance(r.get("tasks"), list) and r["tasks"] and "source" in r and "outputs" in r, r)
    # a stub of the backend's richer check
    import user_tools
    stub = {"ok": True, "problems": [], "warnings": ["stub warning"], "tasks": [{"task": "classification", "status": "native", "how": "contig_labels"}, {"task": "binning_reconstruction", "status": "not_possible", "how": "labels carry no bins"}],
            "source": {"method": "none"}, "outputs": [{"format": "contig_labels", "serves": ["classification"], "rule": "labels are the classification"}]}
    user_tools.validate_text = lambda text: dict(stub)
    try:
        code, r = call("/api/usertools/validate", {"text": ini.replace("task = classification", "task = classification, binning_reconstruction")})
        check("a richer validate_text result is passed through", code == 200 and r["ok"] and [t["status"] for t in r["tasks"]] == ["native", "not_possible"] and r["outputs"][0]["serves"] == ["classification"], r)
        check("its warnings are kept", "stub warning" in r["warnings"], r["warnings"])
    finally:
        del user_tools.validate_text
    code, r = call("/api/schema")
    check("the schema carries a tooltip for every new control", code == 200 and r.get("usertool_help") and all((t.get("summary") or "") for t in r["usertool_help"].values()), list(r))
    summary = webui.user_tool_summary(type("T", (), {"task": "a", "get": lambda self, s, k, d="": {("tool", "task"): "binning_reconstruction, classification", ("install", "method"): "url", ("install", "sha256"): "ab" * 32, ("install", "mode"): ""}.get((s, k), d)})())
    check("a user tool's summary lists every task, its source and its pinned checksum", summary["tasks"] == ["binning_reconstruction", "classification"] and summary["install_source"] == "url" and summary["sha256"] == "ab" * 32, summary)
    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    pure = HTML.split("tested under node by test/test_ut_multi_task_ui.py) */")[1].split("/* ==UTPURE-END== */")[0]
    print("manifest functions (node)")
    run_node(pure)
    print("rendered markup (node, stub page)")
    run_render(HTML)
    print("page")
    static_checks()
    http_checks()
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
