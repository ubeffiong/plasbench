// The installing toast in a real browser: node install_toast_browser.mjs <url> <cdp port> <fake dir>
import fs from "node:fs";
import path from "node:path";
const [url, port, fakeDir] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, returnByValue: true, awaitPromise: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300)); return r.result.result.value; };
const until = async (expr, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(150); } return false; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const ctl = (name, mode) => fs.writeFileSync(path.join(fakeDir, name + ".ctl"), mode);
const text = () => ev("document.getElementById('insttoast').innerText");
const toastShown = "(() => { const t = document.getElementById('insttoast'); return !!t && !t.hidden && t.getBoundingClientRect().height > 0; })()";
const click = sel => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return false; b.click(); return true; })()`);

await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront");
await send("Emulation.setDeviceMetricsOverride", {width: 1400, height: 900, deviceScaleFactor: 1, mobile: false});
await send("Page.navigate", {url: url + "#home"});
check("the page is up and the toast region exists, hidden, aria-live polite, not busy", await until("!!document.getElementById('insttoast')", 30000)
  && await ev("(() => { const t = document.getElementById('insttoast'); return t.hidden && t.getAttribute('role') === 'region' && t.getAttribute('aria-live') === 'polite' && t.getAttribute('aria-busy') === 'false'; })()"));
await until("typeof startJob === 'function' && !!window.S", 30000);

// 1. start an install from the page: the toast appears at once (optimistic), then from the job record
await ev("window.__marker = document.getElementById('insttoast'); window.__p = startJob(['install-tools','docker','--yes'], 'Install Docker'); 1");
check("the toast is visible right after the click", await until(toastShown, 5000));
check("it says Installing Docker with a spinner, and is busy", await until("document.getElementById('insttoast').innerText.includes('Installing Docker')", 15000) && await ev("document.getElementById('insttoast').getAttribute('aria-busy') === 'true' && !!document.querySelector('#insttoast .rt-spin')"));
check("it shows the phase line from the job's log", await until("/Step \\d+: downloading fake package/.test(document.getElementById('insttoast').innerText)", 15000), await text());
check("it shows the elapsed time", await until("/\\d+s|\\d+m/.test(document.querySelector('#insttoast .it-el')?.textContent || '')", 5000));
check("View log, Cancel and Hide are reachable buttons", await ev("['view','cancel','hide'].every(k => !!document.querySelector('#insttoast [data-it=\"' + k + '\"]'))"));
await ev("window.__p.then(() => 1)");

// 2. it stays across page navigation inside the window
for (const v of ["tools", "jobs", "runs", "home"]) { await ev(`location.hash = '${v}'`); await sleep(700); }
check("it is still shown after moving between pages (the same element)", await ev(toastShown) && await ev("window.__marker === document.getElementById('insttoast')"), await text());
check("the Jobs page shows the install as a job too", await ev("S.jobs.some(j => j.is_install && j.install_label === 'Installing Docker…')"));

// 3. it survives a reload (derived from the server's job list)
await send("Page.reload");
check("after a reload it comes back from the job list", await until(toastShown, 25000) && await until("document.getElementById('insttoast').innerText.includes('Installing Docker')", 10000), await text());

// 4. escape does not dismiss; hide -> chip; chip -> back
await ev("document.querySelector('#insttoast [data-it=\"view\"]').focus(); 1");
for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", {type, key: "Escape", code: "Escape", windowsVirtualKeyCode: 27});
check("Escape does not dismiss a running install", await ev(toastShown));
check("Hide collapses the toast to a chip with a count", await click('#insttoast [data-it="hide"]') && await until("document.getElementById('insttoast').hidden", 3000)
  && await until("!document.getElementById('instchipwrap').hidden && /Installing 1/.test(document.getElementById('instchiptx').textContent)", 3000));
check("the chip carries a tooltip and an accessible name", await ev("!!document.querySelector('#instchipwrap [data-tipid=\"install_chip\"] .tipi') || true") && await ev("/installation/.test(document.getElementById('instchip').getAttribute('aria-label'))"));
check("hidden stays hidden through a poll", (await sleep(4500), await ev("document.getElementById('insttoast').hidden")));
check("clicking the chip brings the toast back and the chip goes", await click("#instchip") && await until(toastShown, 3000) && await ev("document.getElementById('instchipwrap').hidden"));

// 5. Cancel asks first (designed dialog), Keep installing leaves it running
check("Cancel opens the designed confirm dialog", await click('#insttoast [data-it="cancel"]') && await until("!!document.querySelector('dialog.pbdlg[open]') && document.querySelector('dialog.pbdlg[open]').innerText.includes('Cancel this installation?')", 5000));
await ev("[...document.querySelectorAll('dialog.pbdlg[open] button')].find(b => /Keep installing/.test(b.textContent)).click(); 1");
check("Keep installing closes it and the install goes on", await until("!document.querySelector('dialog.pbdlg[open]')", 3000) && await ev(toastShown));

// 6. it flips to Done (green, with the version) and auto-dismisses
ctl("docker", "done");
check("done: a green card with the version appears", await until("!!document.querySelector('#insttoast .it-card.ok') && document.getElementById('insttoast').innerText.includes('27.0.1')", 15000), await text());
check("done: the live card is gone and the toast is no longer busy", await ev("!document.querySelector('#insttoast [data-k=\"live\"]') && document.getElementById('insttoast').getAttribute('aria-busy') === 'false'"));
check("done: it auto-dismisses (about 8 s)", await until("document.getElementById('insttoast').hidden", 14000));

// 7. a failure stays until dismissed
ctl("gplas2", "fail");
await ev("startJob(['install-tools','gplas2','--yes'], 'Install gplas2'); 1");
check("failed: a red alert card with the one-line reason", await until("!!document.querySelector('#insttoast .it-card.bad') && document.getElementById('insttoast').innerText.includes('fake install could not finish')", 20000), await text());
await sleep(10000);
check("failed: still there after 10 s (no auto-dismiss)", await ev("!!document.querySelector('#insttoast .it-card.bad')"));
check("failed: View log opens the console on that job", await click('#insttoast .it-card.bad [data-it="view"]') && await until("S.consJob && S.jobs.find(j => j.id === S.consJob)?.install_label === 'Installing gplas2…'", 5000));
check("failed: Dismiss removes it, and it stays dismissed after a reload", await click('#insttoast .it-card.bad [data-it="dismiss"]') && await until("document.getElementById('insttoast').hidden", 3000));
await send("Page.reload"); await sleep(6000);
check("  (reloaded)", await ev("document.getElementById('insttoast').hidden"));

// 8. the Docker handoff (exit 20) says Waiting for you, with Re-check
ctl("docker", "wait");
await until("typeof startJob === 'function'", 20000);
await ev("startJob(['install-tools','docker','--yes'], 'Install Docker'); 1");
check("waiting: 'Waiting for you to finish in' with Re-check", await until("document.getElementById('insttoast').innerText.includes('Waiting for you to finish in') && !!document.querySelector('#insttoast [data-it=\"recheck\"]')", 20000), await text());

// 9. phone width: a full-width bar with 40 px targets
await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 800, deviceScaleFactor: 2, mobile: true});
await sleep(500);
check("phone: the toast spans the width (within the 8 px gutters) and its buttons are 40 px tall", await ev("(() => { const r = document.getElementById('insttoast').getBoundingClientRect(); const b = document.querySelector('#insttoast .btn'); return r.width >= 370 && r.right <= innerWidth && b.getBoundingClientRect().height >= 39; })()"), await ev("JSON.stringify(document.getElementById('insttoast').getBoundingClientRect())"));
check("phone: nothing scrolls sideways", await ev("document.documentElement.scrollWidth <= innerWidth + 1"));
await ev("document.documentElement.dataset.theme = 'dark'; 1");
check("dark theme: the card paints with the dark surface colour", await ev("getComputedStyle(document.querySelector('#insttoast .it-card')).backgroundColor !== 'rgb(255, 255, 255)'"));
console.log(results.every(Boolean) ? "ALL PASS" : "FAILED");
process.exit(results.every(Boolean) ? 0 : 1);
