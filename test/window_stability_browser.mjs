// Drives a real Chrome/Edge against a real PlasBench server (window stability): the window opens with NO stale banner and no pop-up; a stale key with a valid cookie recovers silently;
// a key AND cookie refused shows ONE persistent bar (never a dialog) and the window stops polling.
const [url, port] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(t => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async (expr, awaitPromise = false) => { const r = await send("Runtime.evaluate", {expression: expr, awaitPromise, returnByValue: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300)); return r.result.result.value; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
await send("Page.navigate", {url}); await sleep(5000);

check("the page loads and talks to the server", (await ev("typeof S !== 'undefined' && !!document.getElementById('v_home')")) === true);
check("the served meta api level is a number", /^[0-9]+$/.test(await ev("metaContent('plasbench-api-level')")), await ev("metaContent('plasbench-api-level')"));
check("the SERVED serverTooOld says this server is NOT too old (the v0.5.5 false positive)", (await ev("serverTooOld(metaContent('plasbench-api-level'))")) === false);
await sleep(3000);   // the first server-state poll has run
check("no stale banner is shown when the window opens", (await ev("document.getElementById('stalebar').hidden")) === true && !/program files changed|older than the page/.test(await ev("document.getElementById('stalebar').innerText")), await ev("document.getElementById('stalebar').innerText"));
check("no pop-up and no old-session bar", (await ev("!document.getElementById('ended') && document.getElementById('oldsession').hidden")) === true);
check("the window pings the server (liveness)", await ev("fetch('/api/windows', {headers: {'X-PlasBench-Token': TOKEN}}).then(r => r.json()).then(j => j.alive >= 1)", true));

// a stale key but the browser's cookie is valid (an older window after a restart on the same port)
await ev("TOKEN = 'a-key-from-before-the-restart'; 1");
check("a stale key with the valid cookie: calls still succeed and nothing is shown", (await ev("api('info').then(i => !!i.version, () => false)", true)) === true && (await ev("S.conn == null && !document.getElementById('ended') && document.getElementById('oldsession').hidden")) === true);

// key and cookie both refused: one bar, no dialog, polling stops
await send("Network.clearBrowserCookies");
const msg = await ev("api('info').then(() => 'ok', e => e.message)", true);
await sleep(2500);
check("key and cookie refused: the call fails as 'session ended'", msg === "session ended", msg);
check("ONE persistent bar is shown (not a dialog) saying the window belongs to an older session", (await ev("document.getElementById('oldsession').hidden")) === false && /older PlasBench session/.test(await ev("document.getElementById('oldsession').innerText")) && (await ev("!document.getElementById('ended')")), await ev("document.getElementById('oldsession').innerText"));
check("the bar has Close this window, Open the current window and Check again", (await ev("['os_close','os_open','os_check'].every(i => !!document.getElementById(i))")) === true);
const n1 = await ev("performance.getEntriesByType('resource').length");
await sleep(12000);
const n2 = await ev("performance.getEntriesByType('resource').length");
check("the refused window sends nothing more (no polling, no repeating pop-up)", n1 === n2, [n1, n2]);
check("still exactly one bar and no dialog after 12 s", (await ev("document.querySelectorAll('#oldsession').length")) === 1 && (await ev("!document.getElementById('ended')")));
console.log(results.every(Boolean) ? "ALL WINDOW STABILITY BROWSER CHECKS PASSED" : "WINDOW STABILITY BROWSER CHECKS FAILED");
ws.close(); process.exit(results.every(Boolean) ? 0 : 1);
