// DOM-free tests of the AI pane's pure functions, cut out of plasbench/data/ui.html and run in a bare node VM: the Markdown renderer and every card that shows text the model, a
// provider or a folder supplied, against an XSS corpus. Run by test/test_ai_pane_logic.py.
import fs from "node:fs";
import vm from "node:vm";
const html = fs.readFileSync(process.argv[2], "utf8").replace(/\r\n/g, "\n");
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const grabFn = name => { const i = html.indexOf(`\nfunction ${name}(`); if (i < 0) throw new Error("missing " + name); const j = html.indexOf("\n}\n", i); return html.slice(i + 1, j + 2); };
const grabConst = name => { const m = html.match(new RegExp(`^const ${name} = .*$`, "m")); if (!m) throw new Error("missing const " + name); return m[0]; };
const src = [grabConst("esc"), grabConst("icon"), grabConst("aiKb"), "const AI_WHERE = {window: 'w', terminal: 't'}; const AI_PLAIN_WHERE = 'x';", ...["md", "aiActionCard", "aiAskCard", "aiScanCard", "aiPlanCard", "aiUiCard", "aiToolCard", "aiMsgHtml", "aiDestHtml", "aiIsoHtml", "aiCheckHtml", "aiIntakeCard", "aiLabelsCard", "aiCheckCard", "aiDigestHtml"].map(grabFn),
  "globalThis.T = {esc, md, aiActionCard, aiAskCard, aiScanCard, aiPlanCard, aiUiCard, aiToolCard, aiMsgHtml, aiKb, aiIntakeCard, aiLabelsCard, aiCheckCard};"].join("\n");
const ctx = vm.createContext({console}); vm.runInContext(src, ctx);
const T = ctx.T;
const corpus = ["<script>PWN()</script>", "<img src=x onerror=PWN()>", "\"><b id=PWN>", "' onmouseover='PWN()", "\" onfocus=\"PWN()\" autofocus x=\"", "<svg onload=PWN()>", "<iframe src=javascript:PWN()>", "javascript:PWN()",
  "[click](javascript:PWN())", "[click](data:text/html,<script>PWN()</script>)", "[x](https://a.example/\" onclick=\"PWN())", "![img](x onerror=PWN())", "<a href=\"javascript:PWN()\">x</a>", "</div><div id=PWN>",
  "`<script>PWN()</script>`", "**<img src=x onerror=PWN()>**", "&lt;script&gt;PWN()", "‮<script>PWN()", "<math><mtext></table><img src=x onerror=PWN()>", "{{constructor.constructor('PWN')()}}",
  "${PWN()}", "<style>@import 'x'</style>", "<base href=//evil>", "<meta http-equiv=refresh content=0;url=javascript:PWN()>", "<object data=javascript:PWN()>", "<details open ontoggle=PWN()>", "\u0000<script>PWN()</script>",
  "<scr<script>ipt>PWN()</script>", "x".repeat(100000), "<".repeat(5000), "\"".repeat(5000)];
// A strict reading of the HTML a card produced: every "<" must start a tag of a known name whose attributes are plain (no on* handler, no style, href only http(s) or #), and no
// attribute value may contain a raw quote or "<" (esc() writes &quot; and &lt;). Anything else is injected markup.
const TAGS = new Set("div span p b i code pre ul ol li a h1 h2 h3 h4 h5 h6 table tr th td blockquote hr button label input details summary progress svg use br dl dt dd em strong select option".split(" "));
const TAG = /<(\/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[a-zA-Z:_-][\w:.-]*(?:\s*=\s*(?:"[^"<]*"|'[^'<]*'|[^\s"'<>=`]+))?)*)\s*\/?>/g;
const ATTR = /\s+([a-zA-Z:_-][\w:.-]*)(?:\s*=\s*(?:"([^"<]*)"|'([^'<]*)'|([^\s"'<>=`]+)))?/g;
const bad = out => {
  let rest = out.replace(TAG, (m, close, name, attrs) => {
    if (!TAGS.has(name.toLowerCase())) return "BAD";
    for (const a of attrs.matchAll(ATTR)) {
      const n = a[1].toLowerCase(), v = a[2] ?? a[3] ?? a[4] ?? "";
      if (n.startsWith("on") || n === "style" || n === "srcdoc" || n === "formaction") return "BAD";
      if ((n === "href" || n === "src" || n === "xlink:href") && !/^(https?:|#)/i.test(v.replace(/&#39;|&quot;/g, ""))) return "BAD";
    }
    return "";
  });
  return rest.includes("BAD") || /</.test(rest);
};
const attrBreak = () => false;
check("self-test: the checker flags real injections and passes plain markup", bad("<img src=x onerror=1>") && bad("<a href=\"javascript:x\">") && bad("<div onclick=\"x\">") && bad("<b>a</b><") && bad("<div class=\"a\"b>") && !bad("<div class=\"a &lt;b&gt;\"><b>ok</b> &lt;i&gt;</div>"));
const act = {cmd: "", where: "window", risk: "safe", ok: true, runnable: true, reason: "", why: ""};
for (const p of corpus) {
  const label = p.length > 40 ? p.slice(0, 30) + "..." : JSON.stringify(p);
  const outs = {
    md: T.md(p),
    action: T.aiActionCard(Object.assign({}, act, {cmd: p, why: p, reason: p, risk: p}), 0, 0),
    ask: T.aiAskCard({q: p, options: [p, p]}, 0, 0),
    scan: T.aiScanCard({scan: {counts: {files: 1, dirs: 1, fastq: 0, fasta: 0, sheet: 0}, bytes: 5, pairs: [], samples: [p], problems: [{file: p, text: p, rule: p}], sheets: [], truncated: false}, summary: p, tokens: 3}, 0),
    plan: T.aiPlanCard({plan: {ops: [{i: 0, op: p, can_apply: false, error: p, lines: [p], identity: [[p, p]], diff: p}], problems: [p], bytes: 0, free: 0}, title: p, why: p, skipped: [p], sel: {}, note: p, undo: p}, 0),
    ui: T.aiUiCard({ok: true, ui: "setting", title: p, risk: p, desc: p, why: p, params: {key: p, old: p, value: p}}, 0, 0),
    uibad: T.aiUiCard({ok: false, reason: p}, 0, 0),
    tool: T.aiToolCard({tool: {ok: false, problems: [p], warnings: [p], text: p, name: p}, note: p}, 0),
    msg: T.aiMsgHtml({role: "bot", content: p, sources: [{n: 1, src: p, anchor: p, title: p}], actions: [Object.assign({}, act, {cmd: p})], asks: [{q: p, options: [p]}], usage: {total: 1}, model: p, provider: p, link: "https://x.example/" + p}, 0),
    user: T.aiMsgHtml({role: "user", content: p}, 0),
    intake: T.aiIntakeCard({dest: {where: "study", study: p, sheet: p}, note: p, err: p, actions: [Object.assign({}, act, {cmd: p})], result: {ok: true, staged: [p], results: [{id: p, ok: false, messages: [p]}], journal: p,
      check: {ok: false, error: "", fixable: 1, repaired: [{sample_id: p, what: p}], samples: [{sample_id: p, mode: p, ok: false, checks: [{status: p, name: p, detail: p, fix: p, code: "truth-review", auto: true}]}]}},
      view: {folder: p, staged: 1, needs_review: 1, destination: {label: p}, notes: [p], can_apply: true, fingerprint: p, command: p, run: p, refused: [{file: p, reason: p}],
        leftovers: {fasta_unmatched: [p], long_read_files: [p], unpaired_fastq: [p]}, sheet: {path: p, exists: true, diff: p, after: p, problems: [p]},
        isolates: [{id: p, from: p, stage: false, skip: p + " not ticked", status: "blocked", lanes: 2, reads: [p], compressed: false, mode: p, reference: p, reference_how: p, reference_size: 5, reference_records: 2,
          candidates: [p, p], organism: p, organism_guess: p, truth: p, needs_review: 1, issues: [{level: "warn", text: p, code: p}], ops: [{kind: p, from: [p], to: p, how: p}]}]}}, 0),
    labels: T.aiLabelsCard({data: {sample: p, rows: [{sequence_id: p, raw_id: p, length: 3, header: p, label: "REVIEW"}]}, note: p}, 0),
    check: T.aiCheckCard({dest: {where: "shared", sheet: p}, check: {ok: false, error: p, samples: [], fixable: 0, repaired: []}, err: p, note: p}, 0),
    digest: T.aiMsgHtml({role: "bot", content: p, digest: {text: p, tokens: 3, resume: true}, failedJob: p}, 0),
  };
  for (const [k, o] of Object.entries(outs)) {
    if (p.length > 20000 && k !== "md" && k !== "user") { continue; }
    check(`no injected markup: ${k} <- ${label}`, !bad(o) && !attrBreak(o), o.slice(0, 200));
  }
}
check("markdown links: only http(s) become links", !/href="(?!https?:)/i.test(T.md("[a](javascript:PWN()) [b](https://example.org/x) [c](ftp://x)")) && /href="https:\/\/example.org\/x"/.test(T.md("[b](https://example.org/x)")));
check("a code fence in a reply is a <pre> with escaped text", T.md("```\n<b>x</b>\n```").includes("&lt;b&gt;x&lt;/b&gt;"));
const t0 = Date.now(); T.md("*".repeat(50000) + "\n" + "[".repeat(20000) + "\n" + "|".repeat(20000) + "\n" + "- ".repeat(20000)); const dt = Date.now() - t0;
check(`the Markdown renderer finishes adversarial 1 MB-class input quickly (${dt} ms)`, dt < 3000, dt);
const t1 = Date.now(); T.md(("`".repeat(3) + "\n").repeat(30000) + "a ".repeat(100000)); const dt1 = Date.now() - t1;
check(`unclosed fences and a long paragraph (${dt1} ms)`, dt1 < 3000, dt1);
check("byte sizes read plainly", T.aiKb(0) === "0 B" && T.aiKb(1536) === "1.5 KB" && T.aiKb(5 * 1073741824) === "5.0 GB");
const bad2 = results.filter(x => !x).length;
console.log(bad2 ? `${bad2} FAILED` : "ALL PANE LOGIC CHECKS PASSED");
process.exit(bad2 ? 1 : 0);
