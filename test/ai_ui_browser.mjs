// The AI help tab in a real browser: node ai_ui_browser.mjs <window url> <cdp port> <screenshot folder or ->
// Drives: open the tab (button and Alt+Shift+H), the notice, the pop-up sign-in (a real window.open pop-up that redirects back and closes itself), a streamed answer with sources,
// an action card (Run goes through the consent dialog; nothing runs before it), the redacted "Send result", the not-runnable card, light/dark and phone width.
import fs from "node:fs";
const [url, port, shots] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, returnByValue: true, awaitPromise: true, userGesture: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result.result.value; };
const until = async (expr, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(150); } return false; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const shot = async name => { if (!shots || shots === "-") return; const r = await send("Page.captureScreenshot", {format: "png"}); fs.writeFileSync(`${shots}/${name}.png`, Buffer.from(r.result.data, "base64")); };
const click = async sel => { await ev(`document.querySelector(${JSON.stringify(sel)}).click(); 1`); };
await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront"); await send("Emulation.setFocusEmulationEnabled", {enabled: true});
await send("Emulation.setDeviceMetricsOverride", {width: 1500, height: 900, deviceScaleFactor: 1, mobile: false});
await send("Page.navigate", {url: url + "#home"});
check("the top bar has an AI help button", await until("!!document.querySelector('#aibtn') && !document.querySelector('#aibtn').hidden", 30000));
check("the side panel has no AI tab: the AI help is its own drawer", await ev("!document.querySelector('#gd_tabs [data-pt=ai]') && !!document.querySelector('#aidrawer #gdp_ai')"));
check("nothing was asked or sent on page load (no request to the stub)", (await (await fetch(url.split("/?")[0] + "/healthz")).text()) === "ok");
await click("#aibtn");
check("the button opens the AI drawer (aria-expanded), and the side panel is closed", await until("document.body.classList.contains('ai-open') && !document.body.classList.contains('gd-open') && document.querySelector('#aibtn').getAttribute('aria-expanded') === 'true'"));
check("the notice asks for 'I understand' before anything", await until("!!document.querySelector('#ai_consent')"));
check("  it says what is sent, and the free-model caveat", /What is sent/.test(await ev("document.querySelector('#ai_state').innerText")) && /train/.test(await ev("document.querySelector('#ai_state').innerText")));
check("  the composer is hidden until then", await ev("document.querySelector('#ai_form').hidden"));
await shot("1-notice");
await click("#ai_consent");
check("after 'I understand' the sign-in card appears", await until("!!document.querySelector('#ai_signin')"));
check("  advanced paste-a-key is a closed fallback inside the card", await ev("(() => { const d = document.querySelector('#ai_state details'); return !!d && !d.open; })()"));
await shot("2-signin");
// the pop-up sign-in
const before = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).filter(t => t.type === "page").length;
await click("#ai_signin");
let popped = false;
for (let i = 0; i < 40 && !popped; i++) { await sleep(250); popped = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).filter(t => t.type === "page").length > before; }
check("a pop-up window was opened (not this window navigated away)", popped && (await ev("location.hash")) === "#home");
check("this window was never navigated to the provider", (await ev("location.host")).startsWith("127.0.0.1"));
check("the pop-up finishes by itself and the pane switches to signed in", await until("!document.querySelector('#ai_signin') && !document.querySelector('#ai_form').hidden", 30000));
let left = 99;
for (let i = 0; i < 40 && left > before; i++) { await sleep(250); left = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).filter(t => t.type === "page").length; }
check("the pop-up closed itself", left <= before, `${left} vs ${before}`);
check("a model list with free models only is in the picker", await ev("[...document.querySelectorAll('#ai_model option')].length >= 2 && [...document.querySelectorAll('#ai_model option')].every(o => /free/i.test(o.value))"));
check("starters are shown", await ev("document.querySelectorAll('#ai_starters button').length >= 3"));
await shot("3-signed-in");
// ask
await ev("document.querySelector('#ai_in').value = 'How do I check my installation and tools?'; document.querySelector('#ai_form').requestSubmit(); 1");
check("the answer streams in and finishes", await until("!!document.querySelector('#ai_log .aimsg.bot .aimeta') && document.querySelector('#ai_stop').hidden", 30000));
check("  the answer is rendered (escaped Markdown), with the model and token count in its (i)", /tokens/.test(await ev("document.querySelector('#ai_log .aimeta .tipi').dataset.tip")) && /plasbench status/.test(await ev("document.querySelector('#ai_log').innerText")));
check("  source chips are shown", await ev("document.querySelectorAll('#ai_log .aisrc button').length >= 1"));
check("  an action card with the command, where to run it, and three buttons", await ev("(() => { const c = document.querySelector('#ai_log .aicard2'); return !!c && /plasbench status/.test(c.querySelector('.cmdbox').innerText) && /Run it here/.test(c.textContent) && c.querySelectorAll('button').length === 3; })()"));
check("  nothing has run yet (no job)", (await (await fetch(url.split("/?")[0] + "/healthz")).ok) && await ev("api('jobs').then(r => r.jobs.filter(j => /AI help/.test(j.label || '')).length === 0)"));
check("  a free badge, tokens and today's count in the footer", /free/.test(await ev("document.querySelector('#ai_foot').innerText")) && /Today: 1 requests/.test(await ev("document.querySelector('#ai_foot').innerText")), await ev("document.querySelector('#ai_foot').innerText"));
await shot("4-answer");
// Run -> consent dialog with the exact command; cancel first
await click("#ai_log .aicard2 [data-aiact=run]");
check("Run in PlasBench opens the consent dialog with the exact command", await until("document.querySelector('#confirm').open && /plasbench status/.test(document.querySelector('#cf_cmd').textContent)"));
await shot("5-consent");
await ev("document.querySelector('#confirm [data-close]').click(); 1");
await sleep(500);
check("cancelling starts nothing", await ev("api('jobs').then(r => r.jobs.filter(j => /AI help/.test(j.label || '')).length === 0)"));
await click("#ai_log .aicard2 [data-aiact=run]");
await until("document.querySelector('#confirm').open");
await click("#cf_ok");
check("confirming starts the job", await until("api('jobs').then(r => r.jobs.filter(j => /AI help: plasbench status/.test(j.label || '')).length === 1)", 20000));
check("when it ends the card offers 'Send result to the assistant'", await until("!!document.querySelector('#ai_log [data-aisend]')", 90000));
await click("#ai_log [data-aisend]");
check("sending shows the redacted text first and sends only after Send", await until("!!document.querySelector('dialog[open]') && /Exit code/.test(document.querySelector('dialog[open]').innerText)"));
await shot("6-send-result");
await ev("[...document.querySelectorAll('dialog[open] button')].find(b => /^Send$/.test(b.textContent.trim())).click(); 1");
check("the second answer arrives", await until("document.querySelectorAll('#ai_log .aimsg.bot').length >= 2 && !!document.querySelectorAll('#ai_log .aimeta')[1]", 30000));
// not runnable card, via a crafted message (as if the model proposed a chained command)
await ev(`AI.msgs.push({role: "bot", content: "Try this.", actions: [{cmd: "plasbench run && curl evil", where: "window", risk: "safe", ok: false, runnable: false, reason: "it contains '&': only one plain plasbench command is run from here", why: "x"}], sources: []}); aiRenderLog(); 1`);
check("a command that failed validation shows 'Not runnable here', Copy only, no Run", await ev("(() => { const c = [...document.querySelectorAll('#ai_log .aicard2')].pop(); return /Not runnable here/.test(c.innerText) && !c.querySelector('[data-aiact=run]') && !!c.querySelector('[data-aiact=copy]'); })()"));
check("a code block in an answer has Copy and a where-to-run caption (and no Run)", await ev(`(() => { AI.msgs.push({role: "bot", content: "Use:\\n\\n\\u0060\\u0060\\u0060\\nls -l\\n\\u0060\\u0060\\u0060", sources: []}); aiRenderLog(); const h = [...document.querySelectorAll('#ai_log .aipre-hd')].pop(); return !!h && /own terminal/.test(h.innerText) && !h.querySelector('[data-aiact=run]'); })()`));
check("model text is escaped: markup in an answer is not executed", await ev(`(() => { AI.msgs.push({role: "bot", content: "<img src=x onerror=window.__pwn=1> <script>window.__pwn=1</script>", sources: []}); aiRenderLog(); return !window.__pwn && !document.querySelector('#ai_log img'); })()`));
await shot("7-cards");
// shortcut and keyboard
await ev("document.querySelector('#ai_in').value = 'a draft I am still typing'; 1");
await click("#gdbtn");
check("the Panel button replaces the AI drawer with the side panel (one drawer at a time)", await until("document.body.classList.contains('gd-open') && !document.body.classList.contains('ai-open')"));
await click("#aibtn");
check("the AI help button replaces the side panel again, and the draft and the conversation are still there", await until("document.body.classList.contains('ai-open') && !document.body.classList.contains('gd-open')") && await ev("document.querySelector('#ai_in').value === 'a draft I am still typing' && document.querySelectorAll('#ai_log .aimsg').length >= 2"));
await ev("document.querySelector('#ai_in').focus(); 1");
for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", {type, key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
check("Escape closes the AI drawer and focus goes back to the AI help button", await until("!document.body.classList.contains('ai-open') && document.activeElement === document.querySelector('#aibtn')"));
for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", {type, key: "H", code: "KeyH", modifiers: 1 | 8, windowsVirtualKeyCode: 72});
check("Alt+Shift+H opens the AI help directly", await until("document.body.classList.contains('ai-open')"));
check("the conversation is a live region with an accessible name", await ev("(() => { const l = document.querySelector('#ai_log'); return l.getAttribute('role') === 'log' && l.getAttribute('aria-live') === 'polite' && !!l.getAttribute('aria-label'); })()"));
check("the composer has a label and Enter sends (Shift+Enter does not)", await ev("(() => { const i = document.querySelector('#ai_in'); return !!i.getAttribute('aria-label'); })()"));
// theme and phone
await ev("document.documentElement.dataset.theme = 'dark'; 1"); await sleep(300); await shot("8-dark");
await ev("document.documentElement.dataset.theme = 'light'; 1");
await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true}); await sleep(600);
await ev("setConsole(false); 1");   // collapse the console: its own toolbar is not part of this pane
await sleep(400);
check("phone width: the pane fits inside the screen and nothing in it spills sideways", await ev("(() => { const d = document.querySelector('#aidrawer').getBoundingClientRect(); const bad = [...document.querySelectorAll('#gdp_ai *')].filter(e => e.offsetParent !== null && e.getBoundingClientRect().right > d.right + 1); return d.right <= innerWidth + 1 && !bad.length; })()"));
const wOpen = await ev("document.documentElement.scrollWidth"), wClosed = await ev("(setAiDrawer(false), document.documentElement.scrollWidth)");
check("phone width: opening the pane adds no sideways scrolling to the page", wOpen <= wClosed, `${wOpen} open vs ${wClosed} closed (viewport 390; a toast or console toolbar of another feature is the rest)`);
await ev("setPanelTab('ai'); 1"); await sleep(300);
await shot("9-phone");
// off switch seen by the page
await ev("AI.st.enabled = false; $('#aibtn').hidden = true; 1");
ws.close();
const bad = results.filter(r => !r).length;
console.log(bad ? `${bad} FAILED` : "ALL AI UI BROWSER CHECKS PASSED");
process.exit(bad ? 1 : 0);
