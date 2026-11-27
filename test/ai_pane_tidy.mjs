// The tidied AI pane loses nothing: every string and control that used to be visible is still in the DOM (shown, folded into a <details> or in an (i) tooltip), the risk badge and
// the consent path of a command card are intact, and the AI help is its own right-hand drawer that replaces the side panel (and is replaced by it). Run by test/test_ai_pane_tidy.py.
import fs from "node:fs";
import vm from "node:vm";
const html = fs.readFileSync(process.argv[2], "utf8").replace(/\r\n/g, "\n");
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${String(detail).slice(0, 300)}]`)); };
const grabFn = name => { const i = html.indexOf(`\nfunction ${name}(`); if (i < 0) throw new Error("missing " + name); const j = html.indexOf("\n}\n", i); return html.slice(i + 1, j + 2); };
const grabConst = name => { const m = html.match(new RegExp(`^const ${name} = .*$`, "m")); if (!m) throw new Error("missing const " + name); return m[0]; };
const src = [grabConst("esc"), grabConst("icon"), grabConst("dattr"), grabConst("aiKb"), grabConst("aiTip"), "const AI_WHERE = {window: \"In PlasBench's Terminal tab (bottom panel), or press Run in PlasBench\", terminal: 't'}; const AI_PLAIN_WHERE = 'Run it in your own terminal (PlasBench does not run this)';",
  "const AI = {grant: null, msgs: []}; const aiFlowQuick = " + html.match(/^const aiFlowQuick = (\[.*\]);$/m)[1] + ";",
  ...["tipBtn", "md", "aiActionCard", "aiAskCard", "aiUiCard", "aiMsgHtml", "aiSourcesHtml", "aiAnswerTip", "aiDeclHtml", "aiFootHtml", "aiFolderHtml", "aiQuickHtml", "aiDigestHtml"].map(grabFn),
  "globalThis.T = {aiActionCard, aiMsgHtml, aiSourcesHtml, aiDeclHtml, aiFootHtml, aiFolderHtml, aiQuickHtml, setGrant: g => { AI.grant = g; }};"].join("\n");
const ctx = vm.createContext({console}); vm.runInContext(src, ctx);
const T = ctx.T;
// what a person can reach: visible text, the text inside folded <details>, and the tooltip text (data-tip, unescaped)
const reach = h => h.replace(/data-tip="([^"]*)"/g, (_, t) => " " + t.replace(/&quot;/g, '"').replace(/&amp;/g, "&") + " ").replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");

// (d) the command card stays exactly as designed (the owner's decision): same heading, badge, command, where-to-run line, explanation, three buttons, order and consent path
const pinned = fs.readFileSync(new URL("./fixtures/ai_action_card.js", import.meta.url), "utf8").replace(/\r\n/g, "\n").trim();
check("the command card's code is exactly the pinned design (test/fixtures/ai_action_card.js)", grabFn("aiActionCard").trim() === pinned);
const pre = {cmd: "plasbench diagnose", where: "window", risk: "safe", ok: true, runnable: true, reason: "", why: "Reads the latest run and says what went wrong. It changes nothing."};
const c = T.aiActionCard(pre, -1, 0);
const order = ["Suggested command", '<span class="risk safe">safe</span>', "plasbench diagnose", "Run it here: In PlasBench's Terminal tab (bottom panel), or press Run in PlasBench",
  "Reads the latest run and says what went wrong. It changes nothing.", "Run in PlasBench</button>", "Copy</button>", "Open Terminal tab</button>"];
const at = order.map(t => reach(c).indexOf(t));
check("the failed-run card shows, in this order: Suggested command, safe, the command, Run it here ..., the explanation, Run in PlasBench, Copy, Open Terminal tab", at.every(x => x >= 0) && at.every((x, k) => !k || x > at[k - 1]), JSON.stringify(at));
check("no part of the card is folded or in a tooltip", !/<details|class="tipi"/.test(c));
check("the empty chat still introduces it with the same sentence", html.includes("<p>You have a failed run. This check is safe and changes nothing:</p>"));
for (const risk of ["changes_files", "destructive"]) {
  const d = T.aiActionCard({cmd: "plasbench install-tools core", where: "window", risk, ok: true, runnable: true, reason: "", why: "x"}, 0, 0);
  check(`a ${risk} card shows its badge`, d.includes(`<span class="risk ${risk}">${risk.replace("_", " ")}</span>`));
}
const consent = (() => { const k = html.indexOf("\nasync function aiAct("); return html.slice(k, html.indexOf("\n}\n", k)); })();
check("Run in PlasBench still goes through the server check, the extra confirmation and the consent dialog", /api\("ai\/validate"/.test(consent) && /needs_extra_confirm/.test(consent) && /confirmRun\(/.test(consent));

// (a) sources
const srcs = [{n: 1, src: "README.md", anchor: "supplementary-metrics", title: "README.md > Supplementary metrics (never used to rank)"}, {n: 2, src: "docs/COHORTS.md", anchor: "truth", title: "Cohorts > truth_independent_of_long_reads"},
  {n: 3, src: "README.md", anchor: "supplementary-metrics", title: "README.md > Supplementary metrics (never used to rank)"}, {n: 4, src: "config/config.sh", anchor: "", title: "Settings: Parallelism"}];
const sh = T.aiMsgHtml({role: "bot", content: "Use it [1] and [4].", sources: srcs}, 0);
check("one collapsed line per answer: Sources (3), identical sources once", /<details class="aisrc"><summary>Sources \(3\)<\/summary>/.test(sh));
check("the list keeps every full title and file, and the numbers of a repeated source together", ["Supplementary metrics (never used to rank)", "truth_independent_of_long_reads", "Settings: Parallelism", "config/config.sh", "[1, 3]", "[2]", "[4]"].every(t => sh.includes(t)), sh);
check("each source still opens its guide (data-aisrc and data-anchor)", (sh.match(/data-aisrc=/g) || []).length === 3);

// (b) the declaration
const full = "The assistant never opens your files. A folder you choose is read by PlasBench itself; a summary goes to the assistant only when you press Share.";
const dh = T.aiDeclHtml(full);
check("one short line with an (i) that opens on hover, focus and tap", dh.includes("The assistant can't see your files") && /class="tipi"/.test(dh));
check("the full promise is in the tooltip AND in the line for screen readers", reach(dh).split(full).length >= 3);

// (c) the folder, quick actions and toggles
const fh = reach(T.aiFolderHtml());
check("Choose a folder, its explanation and the remember option (in its own popover) are all there", ["Choose a folder", "remember", "~/.plasbench/ai/grants.json", "Nothing goes to the assistant until you press Share"].every(t => fh.includes(t)) && /<details class="aipop">/.test(fh));
T.setGrant({id: "x", name: "mydata", remember: true});
const gh = reach(T.aiFolderHtml());
check("a chosen folder keeps its chip, Look inside and Revoke", ["mydata", "(remembered)", "Look inside", "Revoke"].every(t => gh.includes(t)));
const qh = T.aiQuickHtml();
check("all six quick actions are there", ["Set up my isolates from a folder", "Check my sample sheet", "Why did my run fail?", "Where is my run?", "Install the tools I need", "Add my own tool"].every(t => qh.includes(t)));
const page = html;
check("Quick actions is a real <details> holding the folder bar and the chips", /<details id="ai_qa" hidden><summary>[\s\S]*?<div id="ai_folder" hidden><\/div><div id="ai_quick" hidden[^>]*><\/div><\/details>/.test(page));
check("Brief and Remember chats are labelled toggles, each with an (i)", /<label><input type="checkbox" id="ai_brief">Brief<\/label><span id="ai_brief_tip">/.test(page) && /<label><input type="checkbox" id="ai_remember">Remember chats<\/label><span id="ai_remember_tip">/.test(page));
const tt = grabFn("aiToolTips");
check("their tooltips say what each does and costs (tokens, where it is stored)", /600 tokens/.test(tt) && /local storage on this computer/.test(tt));

// the footer and the answer's meta line
const FS = {used_today: {requests: 3, tokens: 6042}, cap: 0, signed_in: true, needs_key: true};
const foot = T.aiFootHtml(FS, "openrouter", {usage: {prompt: 1581, completion: 375, estimated: false}, free_requests: {remaining: 48, limit: 50}}), fr = reach(foot);
check("usage: one small indicator ('48 left') in plain sight, beside the free badge and Sign out", /<span class="aiuse " id="ai_use" data-level="ok"[^>]*>48 left<\/span>/.test(foot) && fr.includes("free") && fr.includes("Sign out"), foot);
check("usage: the (i) holds the three lines unchanged in meaning", ["Today: 3 requests, 6,042 tokens", "Last: 1581 in / 375 out", "48 of 50 free requests left today"].every(x => fr.includes(x)), fr);
check("usage: the (i) is a tooltip button (opens on hover, focus and tap; aria-describedby the role=tooltip box)", /class="tipi"[^>]*aria-describedby="tipbox"/.test(foot) && /<div id="tipbox" role="tooltip"/.test(html));
const few = T.aiFootHtml(FS, "openrouter", {usage: {prompt: 1, completion: 1}, free_requests: {remaining: 4, limit: 50}});
check("nearly used up (5 or fewer): the indicator itself turns amber with the number, without hover", /class="aiuse warn"[^>]*data-level="warn"[^>]*>4 left</.test(few), few);
const none = T.aiFootHtml(FS, "openrouter", {usage: {prompt: 1, completion: 1}, free_requests: {remaining: 0, limit: 50}});
check("used up: the indicator itself turns red and says so, without hover", /class="aiuse bad"[^>]*data-level="bad"[^>]*>No free requests left today</.test(none) && reach(none).includes("0 of 50 free requests left today"), none);
const unk = reach(T.aiFootHtml({used_today: {requests: 2, tokens: 10}}, "local", null));
check("no free-request limit known: that line is left out, nothing invented; the indicator shows today's requests", !/free requests left/.test(unk) && unk.includes(">2 today<") && unk.includes("Today: 2 requests, 10 tokens"), unk);
const meta = reach(T.aiMsgHtml({role: "bot", content: "x", usage: {total: 1020, prompt: 900, completion: 120}, model: "stub/free-a:free", provider: "openrouter", free: true}, 0));
check("an answer keeps its model, token count and free/credits in its (i), and the two votes", ["stub/free-a:free", "1020 tokens", "a free model", "Helpful", "Not helpful"].every(t => meta.includes(t)));

// one right drawer: the AI help is its own drawer, the side panel has no AI tab
check("the side panel has no AI tab any more", !/data-pt="ai"/.test(page));
const gdr = page.slice(page.indexOf('<aside id="gdrawer"'), page.indexOf("</aside>", page.indexOf('<aside id="gdrawer"')));
check("the AI pane is not inside the side panel", !gdr.includes('id="gdp_ai"'));
check("the AI pane lives in its own drawer, controlled by the AI help button", /<aside id="aidrawer"[^>]*>[\s\S]*id="gdp_ai"/.test(page) && /id="aibtn"[^>]*aria-expanded="false"[^>]*aria-controls="aidrawer"/.test(page));
const sd = grabFn("setDrawer"), sa = grabFn("setAiDrawer");
check("opening the side panel closes the AI drawer, and opening the AI drawer closes the side panel", /if \(open && AI\.open\) setAiDrawer\(false/.test(sd) && /if \(open && GD\.open\) setDrawer\(false/.test(sa));
check("the AI drawer is hidden, never destroyed (no innerHTML reset), and it returns focus to its button", !/innerHTML/.test(sa) && /\$\("#aibtn"\)\.focus\(\)/.test(sa));
check("an old link to the AI tab opens the AI drawer", /if \(t === "ai"\) \{ setAiDrawer\(true\); return; \}/.test(grabFn("setPanelTab")));
check("Escape closes the AI drawer (after any open tooltip, popover or dialog)", /\$\("#aidrawer"\)\.addEventListener\("keydown"/.test(page) && /\$\("#tipbox"\)\.hidden/.test(page));
check("the stored state is restored (the AI drawer or the side panel, never both)", /localStorage\.getItem\("pb_ai_open"\) === "1"\) AI\.reopen = true; else if/.test(page));
check("no dangling reference to the old AI tab (gd-ai, the ai tab of setPanelTab)", !/gd-ai/.test(page) && !/\["studies", "jobs", "git", "ai"\]/.test(page));
const bad = results.filter(x => !x).length;
console.log(bad ? `${bad} FAILED` : "ALL PANE TIDY CHECKS PASSED");
process.exit(bad ? 1 : 0);
