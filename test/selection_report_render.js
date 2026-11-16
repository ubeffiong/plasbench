// Executes plasbench/data/ui.html's script with a permissive DOM stub, calls selectionReport() on a real report,
// and checks the pop-up it builds (test_selection_report.py runs this when node is installed).
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script[^>]*>([\s\S]*?)<\/script>/g).map(x => x.replace(/^<script[^>]*>/, "").replace(/<\/script>$/, "")).sort((a, b) => b.length - a.length)[0];
const report = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const made = [];
const stub = new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : k === "length" ? 0 : k === Symbol.iterator ? function* () {} : stub,
  apply: () => stub, construct: () => stub, set: () => true,
});
const dlg = {innerHTML: "", className: "", setAttribute() {}, querySelectorAll: () => [], showModal() {}, close() {}, addEventListener() {}, remove() {},
  querySelector: () => ({value: "", textContent: "", innerHTML: "", oninput: null, onclick: null})};
const elements = {};
const doc = new Proxy({}, {get: (t, k) => k === "createElement" ? () => { made.push(dlg); return dlg; } : k === "body" ? {append() {}} : stub});
const ctx = {document: doc, window: stub, navigator: {clipboard: {writeText() {}}}, localStorage: stub, sessionStorage: stub, matchMedia: () => ({matches: false, addEventListener() {}}), addEventListener() {}, location: {hash: ""}, fetch: () => new Promise(() => {}),
  setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {}, console, EventSource: function () {}, URL, URLSearchParams, Intl, Math, JSON, Object, Array, String, Number, Date, Promise, Set, Map, Error, RegExp};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
try { vm.runInContext(script, ctx); } catch (e) { console.log("init error (ignored if the functions exist):", e.message); }
vm.runInContext(`S.cohInfo = {name: "demo", selection: ${JSON.stringify(report)}}; globalThis.__done = selectionReport("demo");`, ctx);
Promise.resolve(ctx.__done).then(() => {
  const out = dlg.innerHTML;
  if (!out) { console.log("FAIL: no dialog content"); process.exit(1); }
  const text = out.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  console.log("dialog html chars:", out.length);
  console.log(text.slice(0, 1800));
  for (const must of ["Where they came from", "Selection criteria", "From available to selected", "Why candidates were dropped", "Sequence information", "What this selection does not establish"]) {
    if (!out.includes(must)) { console.log("FAIL missing section:", must); process.exit(1); }
  }
  if (/undefined|NaN|\[object Object\]/.test(text)) { console.log("FAIL: undefined/NaN/[object Object] in the rendered text"); process.exit(1); }
  console.log("RENDER OK");
}).catch(e => { console.log("FAIL", e.stack); process.exit(1); });
