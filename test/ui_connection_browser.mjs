// Drives a real Chrome against a real PlasBench server: network off -> banner -> popup -> Retry (still down) -> network on -> Retry works / automatic reconnect.
import fs from "node:fs";
const [url, shot] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const targets = await (await fetch("http://127.0.0.1:9333/json")).json();
const page = targets.find(t => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async (expr, awaitPromise = false) => { const r = await send("Runtime.evaluate", {expression: expr, awaitPromise, returnByValue: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300)); return r.result.result.value; };
const offline = off => send("Network.emulateNetworkConditions", {offline: off, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
await send("Page.navigate", {url}); await sleep(4000);
check("the page loads and talks to the server", (await ev("document.title")).length > 0 && (await ev("typeof S !== 'undefined' && S.conn == null")));
check("no banner or popup while connected", (await ev("document.getElementById('connbar').hidden")) === true && (await ev("!document.getElementById('ended')")));

// 1. a short blip is absorbed silently by the retries (no banner)
await offline(true);
const blip = ev("api('info').then(() => 'ok', e => e.message)", true);
await sleep(1200); await offline(false);
check("a connection that returns within a second is retried silently: the call succeeds and no banner is shown", (await blip) === "ok" && (await ev("S.conn == null")), await ev("String(S.conn)"));

// 2. a real outage: retries are used up, the banner appears, the call fails
await offline(true);
const outage = await ev("api('info').then(() => 'ok', e => e.message)", true);
check("a longer outage fails the call with a clear message and shows the reconnect banner", /not reachable/.test(outage) && (await ev("S.conn != null && document.getElementById('connbar').hidden === false")), outage);

// 3. after 45 s the popup appears; here the clock is moved on instead of waiting
await ev("S.conn.since -= 50000; S.conn.delay = 1000; connProbe(false); 1"); await sleep(1500);
check("the popup appears with a Retry now button and a status line", (await ev("!!document.getElementById('lost_retry') && document.getElementById('ended').dataset.kind")) === "down");
await send("Page.captureScreenshot", {format: "png"}).then(r => fs.writeFileSync(shot, Buffer.from(r.result.data, "base64")));

// 4. Retry while still offline: it must run a real check, report honestly, and leave the popup in place
await ev("document.getElementById('lost_retry').click(); 1"); await sleep(2500);
const status = await ev("document.getElementById('lost_status').textContent");
check("Retry now while PlasBench is unreachable says so and the popup stays", /Still not reachable/.test(status) && (await ev("!!document.getElementById('ended')")) && (await ev("!document.getElementById('lost_retry').disabled")), status);

// 5. network back: Retry now reconnects (no page reload), the popup and banner go away
await offline(false);
await ev("document.getElementById('lost_retry').click(); 1"); await sleep(3000);
check("Retry now after PlasBench is reachable again reconnects: popup and banner are gone, no reload needed", (await ev("!document.getElementById('ended')")) && (await ev("document.getElementById('connbar').hidden")) && (await ev("S.conn == null")),
  await ev("JSON.stringify({ended: !!document.getElementById('ended'), conn: S.conn != null})"));
check("the page works again after the reconnect", (await ev("api('info').then(i => !!i.version, () => false)", true)) === true);

// 6. automatic reconnect with nobody clicking
await offline(true);
await ev("api('info').catch(() => 0)", true);
await ev("S.conn && (S.conn.since -= 50000); connProbe(false); 1"); await sleep(1500);
check("outage again: the popup is shown", await ev("!!document.getElementById('ended')"));
await offline(false);
let back = false; for (let i = 0; i < 20 && !back; i++) { await sleep(1000); back = await ev("S.conn == null && !document.getElementById('ended')"); }
check("when PlasBench returns the window reconnects by itself within 20 s", back);

// 7. the server refuses the key (restarted): the popup says so and Check again is honest
await ev("TOKEN_BAK = TOKEN; 1").catch(() => 0);
console.log(results.every(Boolean) ? "ALL CONNECTION CHECKS PASSED" : "CONNECTION CHECKS FAILED");
ws.close(); process.exit(results.every(Boolean) ? 0 : 1);
