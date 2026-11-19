// Runs plasbench/data/ui.html's script against a counting DOM stub and checks the Tools page filter: 150 tools render with ONE write of the table body, typing is debounced
// (five keystrokes, one render), an unchanged result writes nothing, and each row's HTML is built once. Called by test_window_load.py when node is installed.
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script[^>]*>([\s\S]*?)<\/script>/g).map(x => x.replace(/^<script[^>]*>/, "").replace(/<\/script>$/, "")).sort((a, b) => b.length - a.length)[0];
const stub = new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : k === "length" ? 0 : k === Symbol.iterator ? function* () {} : stub,
  apply: () => stub, construct: () => stub, set: () => true,
});
const writes = {}, els = {};
const el = sel => els[sel] || (els[sel] = new Proxy({}, {
  get: (t, k) => k in t ? t[k] : (k === "innerHTML" ? "" : stub),
  set: (t, k, v) => { if (k === "innerHTML") writes[sel] = (writes[sel] || 0) + 1; t[k] = v; return true; },
}));
const doc = new Proxy({}, {get: (t, k) => k === "querySelector" ? el : k === "querySelectorAll" ? () => [] : stub, set: () => true});
let timers = [], nextId = 1;
const ctx = {document: doc, window: stub, navigator: {clipboard: {writeText() {}}}, localStorage: stub, sessionStorage: stub, matchMedia: () => ({matches: false, addEventListener() {}}),
  addEventListener() {}, location: {hash: ""}, fetch: () => new Promise(() => {}), setInterval: () => 0, clearInterval() {}, console,
  setTimeout: (fn, ms) => { const id = nextId++; timers.push({id, fn, ms}); return id; }, clearTimeout: id => { timers = timers.filter(t => t.id !== id); },
  EventSource: function () {}, screen: {width: 1280, height: 800}, MutationObserver: function () { this.observe = () => {}; this.disconnect = () => {}; }, URL, URLSearchParams, Intl, Math, JSON, Object, Array, String, Number, Date, Promise, Set, Map, Error, RegExp};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
try { vm.runInContext(script, ctx); } catch (e) { console.log("init error:", e.message); process.exit(1); }
timers = [];
let bad = 0;
const check = (name, ok, detail = "") => { console.log(`  ${ok ? "PASS" : "FAIL"}: ${name}${ok ? "" : "  [" + detail + "]"}`); if (!ok) bad++; };
vm.runInContext(`S.tools = Array.from({length: 150}, (_, i) => ({tool: "tool_" + i, display: "Tool " + i, source: i % 10 === 0 ? "user" : "builtin", task: i % 3 ? "binning_reconstruction" : "classification",
  track: "short_read", method_class: "mc" + (i % 5), description: "desc " + i, installed: i % 2 === 0, run_flag: "RUN_T" + i, enabled: true}));
  S.toolsPending = 0; TF.q = ""; TF.chip = "all"; TF.last = undefined;`, ctx);
vm.runInContext("renderToolTable()", ctx);
const body = el("#tooltb");
check("150 tools render with one write of the table body", writes["#tooltb"] === 1, writes["#tooltb"]);
check("all 150 rows are in it", (body.innerHTML.match(/<tr>/g) || []).length === 150, (body.innerHTML.match(/<tr>/g) || []).length);
vm.runInContext("renderToolTable()", ctx);
check("an unchanged result writes nothing", writes["#tooltb"] === 1, writes["#tooltb"]);
const built = vm.runInContext("S.tools.every(t => typeof t._row === 'string')", ctx);
check("each row's HTML is built once and kept", built);
// typing: five keystrokes, one timer, one render
const input = el("#toolq");
for (const v of ["t", "to", "too", "tool", "tool_14"]) input.oninput({target: {value: v}});
check("five keystrokes leave one pending render", timers.length === 1, timers.length);
check("nothing is drawn until the pause", writes["#tooltb"] === 1, writes["#tooltb"]);
timers.shift().fn();
check("the pause draws once", writes["#tooltb"] === 2, writes["#tooltb"]);
check("search text is built once per tool", vm.runInContext("S.tools.every(t => typeof t._hay === 'string')", ctx));
const n = (body.innerHTML.match(/<tr>/g) || []).length;
check("tool_14 matches tool_14 and tool_140..149 only", n === 11, n);
// checking state shows, and a probe that finishes re-renders
vm.runInContext(`S.tools.forEach(t => { t.installed = null; t.checking = true; t._row = null; }); TF.q = ""; renderToolTable();`, ctx);
check("rows still checking say so", /checking…/.test(body.innerHTML));
// the install filters
vm.runInContext(`S.tools.forEach(t => { t.checking = false; t.installed = true; t._row = null; }); TF.chip = "installed"; renderToolTable();`, ctx);
check("the Installed filter keeps installed tools", (body.innerHTML.match(/<tr>/g) || []).length === 150);
process.exit(bad ? 1 : 0);
