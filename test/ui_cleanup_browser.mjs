// The (?) help tooltips and the phone layout in a real browser: node ui_cleanup_browser.mjs <url> <cdp port>
// hover, keyboard focus and a touch tap open the tooltip; Escape closes it; it stays inside the window at phone width; no page scrolls sideways at phone width.
const [url, port] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, returnByValue: true, awaitPromise: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 300)); return r.result.result.value; };
const until = async (expr, ms = 8000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(150); } return false; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const key = async (k, code) => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", {type, key: k, code: code || k, windowsVirtualKeyCode: k === "Escape" ? 27 : 0}); };
const centre = async sel => JSON.parse(await ev(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2}); })()`));
const shown = "!document.getElementById('tipbox').hidden";
const inside = "(() => { const r = document.getElementById('tipbox').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight; })()";
const TIP = '#v_tools [data-tipid="p_tools"] .tipi';
await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront"); await send("Emulation.setFocusEmulationEnabled", {enabled: true});   // a headless page is not focused by itself: focus events need it
await send("Emulation.setDeviceMetricsOverride", {width: 1400, height: 900, deviceScaleFactor: 1, mobile: false});
await send("Page.navigate", {url: url + "#tools"});
check("the Tools page has its (?) next to the title", await until(`!!document.querySelector('${TIP}')`, 20000));
const tip = JSON.parse(await ev(`document.querySelector('${TIP}').dataset.tip`));
check("it is a plain page tooltip with a title and bullets", tip.plain && tip.title === "Tools" && tip.bullets.length >= 3);
check("it names the tooltip box (aria-describedby) and is collapsed", await ev(`document.querySelector('${TIP}').getAttribute('aria-describedby') === 'tipbox' && document.querySelector('${TIP}').getAttribute('aria-expanded') === 'false'`));
// keyboard focus
await ev(`document.querySelector('${TIP}').focus(); 1`);
check("keyboard focus opens it", await until(shown));
check("  it holds the title and the bullet text", /Tools/.test(await ev("document.getElementById('tipbox').innerText")) && /skipped unless you turn it on/.test(await ev("document.getElementById('tipbox').innerText")));
check("  it is aria-expanded while open", await ev(`document.querySelector('${TIP}').getAttribute('aria-expanded') === 'true'`));
await key("Escape");
check("Escape closes it", await until("document.getElementById('tipbox').hidden"));
check("  and focus stays on the (?)", await ev(`document.activeElement === document.querySelector('${TIP}')`));
await ev("document.activeElement.blur(); 1");
// hover
let c = await centre(TIP);
await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: c.x, y: c.y});
check("hover opens it", await until(shown));
await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: 5, y: 500});
check("moving away closes it", await until("document.getElementById('tipbox').hidden"));
// click pins, a second click or Escape closes
await send("Input.dispatchMouseEvent", {type: "mousePressed", x: c.x, y: c.y, button: "left", clickCount: 1}); await send("Input.dispatchMouseEvent", {type: "mouseReleased", x: c.x, y: c.y, button: "left", clickCount: 1});
await send("Input.dispatchMouseEvent", {type: "mouseMoved", x: 5, y: 500});
await sleep(300);
check("a click keeps it open (pinned) after the pointer leaves", await ev(shown));
await key("Escape");
check("Escape closes the pinned tooltip", await until("document.getElementById('tipbox').hidden"));
await ev("document.activeElement.blur(); 1");
// phone: touch tap, and the tooltip stays on screen
await send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
await send("Emulation.setTouchEmulationEnabled", {enabled: true});
await sleep(600);
c = await centre(TIP);
await send("Input.dispatchTouchEvent", {type: "touchStart", touchPoints: [{x: c.x, y: c.y}]}); await send("Input.dispatchTouchEvent", {type: "touchEnd", touchPoints: []});
check("a tap opens it on a phone", await until(shown));
check("  and it is inside the screen (not cut off)", await ev(inside), await ev("JSON.stringify(document.getElementById('tipbox').getBoundingClientRect())"));
await send("Input.dispatchTouchEvent", {type: "touchStart", touchPoints: [{x: 200, y: 700}]}); await send("Input.dispatchTouchEvent", {type: "touchEnd", touchPoints: []});
check("a tap elsewhere closes it", await until("document.getElementById('tipbox').hidden"));
// no sideways scrolling at phone width, on every page
for (const v of ["home", "setup", "tools", "addtool", "prereg", "settings", "wizard", "workspace", "isolates", "cohorts", "runs", "jobs", "git", "commands", "help"]) {
  await ev(`location.hash = '#${v}'; 1`); await sleep(700);
  const m = JSON.parse(await ev("JSON.stringify({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})"));
  check(`phone width: ${v} does not scroll sideways`, m.sw <= m.cw + 1, JSON.stringify(m));
}
ws.close();
const bad = results.filter(r => !r).length;
console.log(bad ? `${bad} FAILED` : "ALL UI CLEANUP BROWSER CHECKS PASSED");
process.exit(bad ? 1 : 0);
