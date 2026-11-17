// Runs plasbench/data/ui.html's script with a permissive DOM stub and checks what the "default" choice of a tool's
// on / default / off control says (test_tool_default_label.py runs this when node is installed).
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.match(/<script[^>]*>([\s\S]*?)<\/script>/g).map(x => x.replace(/^<script[^>]*>/, "").replace(/<\/script>$/, "")).sort((a, b) => b.length - a.length)[0];
const stub = new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => "" : k === "then" ? undefined : k === "length" ? 0 : k === Symbol.iterator ? function* () {} : stub,
  apply: () => stub, construct: () => stub, set: () => true,
});
const ctx = {document: stub, window: stub, navigator: {clipboard: {writeText() {}}}, localStorage: stub, sessionStorage: stub, matchMedia: () => ({matches: false, addEventListener() {}}),
  addEventListener() {}, location: {hash: ""}, fetch: () => new Promise(() => {}), setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {}, console,
  EventSource: function () {}, URL, URLSearchParams, Intl, Math, JSON, Object, Array, String, Number, Date, Promise, Set, Map, Error, RegExp};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
try { vm.runInContext(script, ctx); } catch (e) { console.log("init error:", e.message); }
const out = vm.runInContext(`
  S.tools = [{tool: "mob_recon", run_flag: "RUN_MOB_RECON", enabled: true}, {tool: "platon", run_flag: "RUN_PLATON", enabled: false}, {tool: "no_flag", run_flag: null, enabled: null}];
  const tri = a => fieldHTML({dest: a, flags: ["--" + a], kind: "tri", choices: ["on", "off"], help: "", default: null}, {}, "x");
  ({on: defaultWord("mob_recon"), off: defaultWord("platon"), hyphen: defaultWord("mob-recon"), unknown: defaultWord("nope"), noflag: defaultWord("no_flag")})`, ctx);
const want = {on: "default · on", off: "default · off", hyphen: "default · on", unknown: "default", noflag: "default"};
let bad = 0;
for (const [k, v] of Object.entries(want)) { const ok = out[k] === v; if (!ok) bad++; console.log(`  ${ok ? "PASS" : "FAIL"}: ${k} -> ${out[k]}`); }
process.exit(bad ? 1 : 0);
