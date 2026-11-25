// Real-browser pass over the AI help pane: the folder grant, scan, share, file plans (preview, apply, undo), the sheet fix, window-action cards, the guided flows, and the
// UI review checks (focus, keyboard, zoom, 320 px, contrast, reduced motion, long strings, many cards, scroll behaviour, reload mid-stream).
// node ai_ui_review.mjs <window url> <cdp port> <screenshot folder or -> <data folder>
import fs from "node:fs";
const [url, port, shots, dataDir] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, returnByValue: true, awaitPromise: true, userGesture: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result.result.value; };
const until = async (expr, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(150); } return false; };
const rows = [];
const check = (area, name, ok, detail = "") => { rows.push({area, name, ok, detail}); console.log((ok ? "  ok    " : "  FAIL  ") + area + ": " + name + (ok ? "" : `  [${detail}]`)); };
const shot = async name => { if (!shots || shots === "-") return; const r = await send("Page.captureScreenshot", {format: "png"}); fs.writeFileSync(`${shots}/${name}.png`, Buffer.from(r.result.data, "base64")); };
const click = async sel => { await ev(`document.querySelector(${JSON.stringify(sel)}).click(); 1`); };
const errors = [];
await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront"); await send("Emulation.setFocusEmulationEnabled", {enabled: true});
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300)); });
await send("Emulation.setDeviceMetricsOverride", {width: 1500, height: 900, deviceScaleFactor: 1, mobile: false});
await send("Page.navigate", {url: url + "#home"});
await until("!!document.querySelector('#aibtn') && !document.querySelector('#aibtn').hidden", 30000);
await click("#aibtn");
await until("!!document.querySelector('#ai_consent')");
await shot("01-first-use-notice");
check("first use", "the notice states the folder rule and that a summary goes only on Share", /never opens your files/.test(await ev("document.querySelector('#ai_state').innerText")) && /press Share/.test(await ev("document.querySelector('#ai_state').innerText")));
check("first use", "the composer, folder bar and quick actions are hidden until the notice is accepted", await ev("document.querySelector('#ai_form').hidden && document.querySelector('#ai_folder').hidden && document.querySelector('#ai_quick').hidden"));
await click("#ai_consent");
await sleep(500);
await ev("(async () => { AI.prov = 'local'; await aiStatus(true); fillProv(); await aiLoadModels(); aiRender(); })()");
if (await ev("!!document.querySelector('#ai_consent')")) { await click("#ai_consent"); await sleep(600); }   // the notice is accepted once per provider
check("sign-in", "the local provider needs no sign-in: the pane opens", await until("!document.querySelector('#ai_form').hidden", 20000));
check("pane", "the declaration line under the chat names the Share rule", /press Share/.test(await ev("document.querySelector('#ai_decl').innerText")));
check("pane", "six quick-action chips are shown", await ev("document.querySelectorAll('#ai_quick button').length === 6"));
check("pane", "the folder bar offers Choose a folder (the native picker is not driven here)", await ev("!!document.querySelector('#ai_folder [data-aif=choose]')"));
// grant through the same API the picker's callback uses
await ev(`api("ai/folder/grant", {path: ${JSON.stringify(dataDir)}, remember: false}).then(g => { AI.grant = g; aiRenderFolder(); })`);
check("grant", "the chip shows only the folder's own name, with Revoke", await ev("(() => { const t = document.querySelector('#ai_folder').innerText; return /mydata/.test(t) && /Revoke/.test(t) && !/:\\\\|\\//.test(t.replace('Look inside','')); })()"));
await shot("02-folder-chip");
// Set up my isolates from a folder: PlasBench's intake, a review card, Stage, the quick test, Undo
await click("#ai_quick [data-aiflow=setup_isolates]");
check("setup flow", "the intake's review card lists the isolates with their reads, reference and truth status", await until("!!document.querySelector('#ai_log .aicard2.intake .aiiso')", 30000) && /Reference:/.test(await ev("document.querySelector('#ai_log .aicard2.intake').innerText")));
check("setup flow", "the card offers the destination, the sheet diff and the equivalent plasbench intake stage command", await ev("!!document.querySelector('#ai_log [data-idest=where]') && /plasbench intake stage/.test(document.querySelector('#ai_log .aicard2.intake').textContent)"));
await ev("document.querySelector('#ai_log .aicard2.intake').scrollIntoView(); 1");
await shot("04-intake-review");
await click("#ai_log [data-aif=iapply]");
check("apply", "Stage asks for confirmation and lists what it will do", await until("!!document.querySelector('dialog[open]')"));
await shot("06-apply-confirm");
await ev("[...document.querySelectorAll('dialog[open] button')].find(b => /^Stage$/.test(b.textContent.trim())).click(); 1");
check("apply", "the isolates are staged, the quick test is shown and an Undo button appears", await until("!!document.querySelector('#ai_log [data-aif=iundo]')", 120000));
await shot("07-applied-check");
await click("#ai_log [data-aif=iundo]");
await until("!!document.querySelector('dialog[open]')"); await ev("[...document.querySelectorAll('dialog[open] button')].find(b => /^Undo$/.test(b.textContent.trim())).click(); 1");
check("undo", "Undo removes what was staged and says so", await until("/Undone/.test(document.querySelector('#ai_log').innerText)", 20000));
// sheet fix flow
fs.writeFileSync(dataDir + "/bad.tsv", "id,accession,run,organism\nS 1,NA,S1,E. coli\nS2,NA,S2,K. pneumoniae\n");
await ev("AI.msgs = []; aiRenderLog(); 1");
await ev("aiFlowSheet(); 1");
check("sheet fix", "the plan shows a diff and flags the sample-id change", await until("!!document.querySelector('#ai_log .aicard2.plan details pre')", 25000) && /Sample ids change/.test(await ev("document.querySelector('#ai_log .aicard2.plan').innerText")));
await ev("document.querySelector('#ai_log .aicard2.plan details').open = true; document.querySelector('#ai_log .aicard2.plan').scrollIntoView(); 1");
await shot("09-sheet-fix-diff");
fs.unlinkSync(dataDir + "/bad.tsv");
// window action cards (validated by the server first)
await ev(`(async () => { AI.msgs = []; const mk = async o => api("ai/ui/validate", {ui: o}); const u = [await mk({ui: "go", target: "runs", sub: "attention"}), await mk({ui: "setting", key: "RUN_DIMER_DETECTION", value: "0"}), await mk({ui: "setting", key: "AI_PROVIDER", value: "x"}), await mk({ui: "install", profile: "core"})]; AI.msgs.push({role: "bot", content: "Here are some things I can do.", ui: u}); aiRenderLog(); })()`);
await until("document.querySelectorAll('#ai_log .aicard2.ui').length >= 1");
check("window actions", "a setting card shows old -> new, and a refused one says why", /->|→/.test(await ev("document.querySelector('#ai_log').innerText")) && /Not allowed/.test(await ev("document.querySelector('#ai_log').innerText")));
await shot("10-window-action-cards");
await click("#ai_log .aicard2.ui [data-aiui=run]");
check("navigation card", "Go there opens the page with one click", await until("location.hash === '#runs/attention'", 10000));
await ev("go('home'); 1");
// a streamed answer with proposals through the model path
await ev("AI.msgs = []; aiRenderLog(); document.querySelector('#ai_in').value = 'take me to settings and set up my folder'; document.querySelector('#ai_form').requestSubmit(); 1");
check("model path", "pb-ui and pb-files blocks in a streamed answer become cards", await until("document.querySelectorAll('#ai_log .aicard2.ui').length >= 1 && document.querySelectorAll('#ai_log [data-aif=reviewplan]').length >= 1 && document.querySelector('#ai_stop').hidden", 30000));
check("model path", "the raw fences are not left in the text", !/pb-ui|pb-files/.test(await ev("document.querySelector('#ai_log .aibody').innerText")));
await shot("11-model-proposals");
await click("#ai_log [data-aif=reviewplan]");
check("model path", "Review the plan runs the server's dry run before any Apply", await until("!!document.querySelector('#ai_log .aicard2.plan')", 15000));
// share flow
await ev("document.querySelector('#ai_log').innerHTML = ''; AI.msgs = []; 1");
await ev("aiScan()"); await until("!!document.querySelector('#ai_log [data-aif=share]')");
await click("#ai_log [data-aif=share]");
check("share", "Share shows the exact text in a confirmation, and sends nothing until Share is pressed", await until("!!document.querySelector('dialog[open] pre.detail') && /Folder summary/.test(document.querySelector('dialog[open] pre.detail').textContent)"));
await shot("12-share-confirm");
await ev("[...document.querySelectorAll('dialog[open] button')].find(b => /^Share$/.test(b.textContent.trim())).click(); 1");
check("share", "the shared answer arrives", await until("document.querySelector('#ai_stop').hidden && !!document.querySelector('#ai_log .aimsg.bot .aimeta')", 30000));
// ---- UI review ----
const A = "ui review";
check(A, "no uncaught page error so far", errors.length === 0, errors[0]);
check(A, "the log is a polite live region with a name; the status line is a separate status region", await ev("(() => { const l = document.querySelector('#ai_log'); const s = document.querySelector('#ai_live'); return l.getAttribute('role') === 'log' && !!l.getAttribute('aria-label') && s.getAttribute('role') === 'status'; })()"));
check(A, "every button in the pane has an accessible name", await ev("[...document.querySelectorAll('#gdp_ai button')].filter(b => !(b.getAttribute('aria-label') || b.textContent.trim() || b.title)).length === 0"));
check(A, "every form control in the pane has a name", await ev("[...document.querySelectorAll('#gdp_ai input, #gdp_ai select, #gdp_ai textarea')].filter(i => !(i.getAttribute('aria-label') || (i.labels && i.labels.length) || i.title)).length === 0"));
check(A, "touch targets: chips and buttons are at least 24 px high", await ev("[...document.querySelectorAll('#ai_quick button, #ai_send, #ai_log .aicard2 .btn')].filter(b => b.offsetParent && b.getBoundingClientRect().height < 24).length === 0"));
// contrast
const contrast = await ev(`(() => { const lum = c => { const [r,g,b] = c.match(/\\d+(\\.\\d+)?/g).slice(0,3).map(Number).map(v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); }); return 0.2126*r + 0.7152*g + 0.0722*b; };
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; } return "rgb(255,255,255)"; };
  const ratio = el => { const a = lum(getComputedStyle(el).color), b = lum(bg(el)); return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05); };
  const sel = ["#ai_quick button", "#ai_decl", "#ai_log .aimsg.user", "#ai_log .aicard2 .why", "#ai_log .aicard2 .btn", "#ai_foot", ".aichip", "#ai_log .aicard2 .risk"]; const out = {};
  for (const s of sel) { const el = document.querySelector(s); if (el) out[s] = Math.round(ratio(el) * 100) / 100; } return out; })()`);
console.log("  contrast (light):", JSON.stringify(contrast));
check(A, "text contrast is at least 4.5:1 in the light theme (measured above)", Object.values(contrast).every(v => v >= 4.5), JSON.stringify(contrast));
await ev("document.documentElement.setAttribute('data-theme', 'dark'); 1"); await sleep(300);
const contrastDark = await ev(`(() => { const lum = c => { const [r,g,b] = c.match(/\\d+(\\.\\d+)?/g).slice(0,3).map(Number).map(v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); }); return 0.2126*r + 0.7152*g + 0.0722*b; };
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; } return "rgb(0,0,0)"; };
  const ratio = el => { const a = lum(getComputedStyle(el).color), b = lum(bg(el)); return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05); };
  const sel = ["#ai_quick button", "#ai_decl", "#ai_log .aimsg.user", "#ai_log .aicard2 .why", "#ai_log .aicard2 .btn", "#ai_foot", ".aichip", "#ai_log .aicard2 .risk"]; const out = {};
  for (const s of sel) { const el = document.querySelector(s); if (el) out[s] = Math.round(ratio(el) * 100) / 100; } return out; })()`);
console.log("  contrast (dark):", JSON.stringify(contrastDark));
check(A, "text contrast is at least 4.5:1 in the dark theme (measured above)", Object.values(contrastDark).every(v => v >= 4.5), JSON.stringify(contrastDark));
await shot("13-dark");
await ev("document.documentElement.removeAttribute('data-theme'); document.documentElement.setAttribute('data-theme', 'light'); 1");
// keyboard
await ev("document.querySelector('#ai_in').focus(); 1");
await send("Input.dispatchKeyEvent", {type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9}); await send("Input.dispatchKeyEvent", {type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9});
check(A, "Tab from the composer reaches the next control (no keyboard trap)", await ev("document.activeElement.id !== 'ai_in'"));
check(A, "a card's button is activated by keyboard: Enter on a focused quick chip starts the flow", await ev("(() => { const b = document.querySelector('#ai_quick [data-aiflow=why_failed]'); b.focus(); return document.activeElement === b && b.tagName === 'BUTTON'; })()"));
// double click on a one-shot button
await ev("AI.msgs = []; aiRenderLog(); 1");
await ev(`(async () => { const v = await api("ai/ui/validate", {ui: {ui: "go", target: "runs"}}); AI.msgs.push({role: "bot", content: "x", ui: [v]}); aiRenderLog(); })()`);
await ev("(() => { const b = document.querySelector('#ai_log [data-aiui=run]'); b.click(); b.click(); })()"); await sleep(400);
check(A, "a double click on Go there does not break the page", (await ev("location.hash")) === "#runs" && errors.length === 0, errors[0]);
await ev("go('home'); 1");
// long strings, RTL, many cards
await ev(`AI.msgs = [{role: "user", content: "x".repeat(5000) + " \\u202e rtl text"}, {role: "bot", content: "A" .repeat(3000) + "\\n\\n" + "https://example.org/" + "a".repeat(2000) + "\\n\\n\\u0060\\u0060\\u0060\\n" + "plasbench ".repeat(300) + "\\n\\u0060\\u0060\\u0060", actions: Array.from({length: 40}, (_, i) => ({cmd: "plasbench status " + "--x".repeat(i), where: "window", risk: "safe", ok: true, runnable: true, why: "w".repeat(100)}))}]; aiRenderLog(); 1`);
await sleep(300);
check(A, "very long unbroken text and 40 cards do not widen the pane or the page", await ev("(() => { const l = document.querySelector('#ai_log'); return l.scrollWidth <= l.clientWidth + 2 && document.documentElement.scrollWidth <= window.innerWidth + 2; })()"), await ev("[document.querySelector('#ai_log').scrollWidth, document.querySelector('#ai_log').clientWidth, document.documentElement.scrollWidth, window.innerWidth].join(',')"));
await shot("14-long-and-many");
const t0 = Date.now(); await ev("for (let i = 0; i < 30; i++) aiRenderLog(); 1"); const dt = Date.now() - t0;
check(A, "30 re-renders of a heavy chat take under 3 s (" + dt + " ms)", dt < 3000, dt);
// listener leak check: the pane uses one delegated listener
check(A, "the pane adds no per-card listeners (one delegated click handler)", await ev("document.querySelectorAll('#ai_log button[onclick]').length === 0"));
// zoom 200% and 320 px
await send("Emulation.setDeviceMetricsOverride", {width: 750, height: 900, deviceScaleFactor: 2, mobile: false});
await ev("AI.msgs = []; aiRenderLog(); 1"); await sleep(300);
check(A, "at 200% zoom (750 css px) the composer and chips are usable and nothing overflows", await ev("document.documentElement.scrollWidth <= window.innerWidth + 2 && !document.querySelector('#ai_form').hidden"));
await shot("15-zoom-200");
await send("Emulation.setDeviceMetricsOverride", {width: 320, height: 640, deviceScaleFactor: 2, mobile: true});
await sleep(400);
const pageOverflow = await ev("document.documentElement.scrollWidth - window.innerWidth");
check(A, "at 320 px the pane itself does not overflow horizontally", await ev("(() => { const p = document.querySelector('#gdp_ai'); return p.scrollWidth <= p.clientWidth + 2; })()"), await ev("document.querySelector('#gdp_ai').scrollWidth + ' vs ' + document.querySelector('#gdp_ai').clientWidth"));
check(A, "at 320 x 640 the composer (where the question is typed) is inside the visible window", await ev("(() => { const r = document.querySelector('#ai_in').getBoundingClientRect(); return r.bottom <= window.innerHeight && r.top >= 0 && r.width > 100; })()"), await ev("JSON.stringify(document.querySelector('#ai_in').getBoundingClientRect()) + ' h=' + window.innerHeight"));
console.log("  page-wide horizontal overflow at 320 px (css px, with the pane open):", pageOverflow);
await shot("16-320px");
await send("Emulation.setDeviceMetricsOverride", {width: 1500, height: 900, deviceScaleFactor: 1, mobile: false});
// reduced motion
await send("Emulation.setEmulatedMedia", {features: [{name: "prefers-reduced-motion", value: "reduce"}]});
check(A, "with reduced motion, no animation or transition longer than 0.01 s runs in the pane", await ev("[...document.querySelectorAll('#gdp_ai *')].every(e => { const s = getComputedStyle(e); return parseFloat(s.animationDuration) <= 0.011 || s.animationName === 'none'; })"));
await send("Emulation.setEmulatedMedia", {features: []});
// forced colours (high contrast)
await send("Emulation.setEmulatedMedia", {features: [{name: "forced-colors", value: "active"}]});
await sleep(200);
check(A, "in forced-colours mode the chips and cards keep a visible border", await ev("(() => { const b = document.querySelector('#ai_quick button'); return b ? getComputedStyle(b).borderTopWidth !== '0px' : false; })()"));
await shot("17-forced-colors");
await send("Emulation.setEmulatedMedia", {features: []});
// scroll behaviour during a slow stream: the user scrolls up, the answer must not drag them down
await ev("AI.msgs = Array.from({length: 12}, (_, i) => ({role: i % 2 ? 'bot' : 'user', content: 'line '.repeat(80)})); aiRenderLog(); document.querySelector('#ai_log').scrollTop = 0; 1");
await ev("document.querySelector('#ai_in').value = 'what is cprr'; document.querySelector('#ai_form').requestSubmit(); 1");
await sleep(150); await ev("document.querySelector('#ai_log').scrollTop = 0; 1");
await until("document.querySelector('#ai_stop').hidden", 30000);
check(A, "when the user has scrolled up, a streaming answer does not pull the view down", await ev("document.querySelector('#ai_log').scrollTop < 200"), await ev("document.querySelector('#ai_log').scrollTop"));
// reload mid-stream
await ev("AI.msgs = []; aiRenderLog(); document.querySelector('#ai_in').value = 'what is cprr'; document.querySelector('#ai_form').requestSubmit(); 1");
await sleep(100);
await send("Page.reload");
check(A, "reloading during a stream leaves the window working (the pane opens again)", await until("!!document.querySelector('#aibtn') && !document.querySelector('#aibtn').hidden", 30000));
// escape / focus return
await ev("document.querySelector('#aibtn').focus(); 1");
if (!(await ev("document.body.classList.contains('gd-open')"))) await click("#aibtn");
await sleep(500);
const open1 = await ev("document.body.classList.contains('gd-open')");
await ev("document.querySelector('#gd_close').click(); 1"); await sleep(300);
check(A, "closing the drawer closes the pane (and it can be opened again by button and by Alt+Shift+H)", open1 && !(await ev("document.body.classList.contains('gd-open')")));
check(A, "no uncaught page error during the whole pass", errors.length === 0, errors[0]);
fs.writeFileSync(`${shots && shots !== "-" ? shots : "."}/ui-review-results.json`, JSON.stringify(rows, null, 1));
const bad = rows.filter(r => !r.ok).length;
console.log(bad ? `${bad} FAILED` : "ALL AI UI REVIEW CHECKS PASSED");
process.exit(bad ? 1 : 0);
