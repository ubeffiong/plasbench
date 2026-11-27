// The console colours in the real window: node terminal_colour_browser.mjs <url> <cdp port> <screenshot dir or "">
// A sample log with every type is fed through the page's own renderer into Job output; a real Terminal command that prints colour codes comes back coloured; the Colours
// menu switches the mode; Copy's text is plain; screenshots in both themes at 1280 and 700 px when a folder is given.
import {writeFileSync} from "node:fs";
const [url, port, shots] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const page = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async expr => { const r = await send("Runtime.evaluate", {expression: expr, returnByValue: true, awaitPromise: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result.result.value; };
const until = async (expr, ms = 8000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(150); } return false; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const shot = async name => { if (!shots) return; const r = await send("Page.captureScreenshot", {format: "png"}); writeFileSync(`${shots}/${name}.png`, Buffer.from(r.result.data, "base64")); };
const SAMPLE = ["############ PlasBench ############", "[2026-11-27 10:00:01] Running stages: 1 2 3", ">>>>> STAGE 3 : 03_assemble.sh", "=== Assemble escherichia_coli_017 ===",
  "[2026-11-27 10:02:10]   fastp trimming (escherichia_coli_017) ...", "Read1 before filtering: total reads: 1203321",
  "[2026-11-27 10:04:40] WARNING: SPAdes failed for acinetobacter_baumannii_008; excluded from tool runs", "What to do: free memory, then run the same command again.",
  "NOTE: the computer was asleep for 12 min; the run was paused, not slow.", "[2026-11-27 10:05:00] ERROR: truth table for s2 is not usable; fix it and re-run",
  "Traceback (most recent call last):", '  File "make_truth.py", line 88, in <module>', "    main()", "ValueError: duplicate sequence id 'p1'",
  "\x1b[1;32m==>\x1b[0m conda: \x1b[32mSolving environment: done\x1b[0m", "\x1b[33mwarning  libmamba\x1b[0m Added empty dependency",
  "\x1b[38;5;208m256-colour\x1b[0m \x1b[38;2;120;160;255mtrue colour\x1b[0m \x1b[1;4mbold underline\x1b[0m \x1b[44m background \x1b[0m",
  " [####      ] 40%\r [##########] 100%", "<img src=x onerror=window.__pwned=1> stays text", "one failed sample is tolerated -> PASS",
  "Stage 3 (assembly) complete: 4 of 5 assembled.", "$ plasbench check", "[exit 1]"].join("\n") + "\n";

await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront");
await send("Emulation.setDeviceMetricsOverride", {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
await send("Page.navigate", {url});
check("the window loads with the console", await until("!!document.getElementById('clog') && typeof TermStream === 'function'", 20000));
await ev(`setConsole(true); setCTab("out"); document.getElementById("clog").textContent = ""; S.consJob = ""; S.cstream = new TermStream(document.getElementById("clog"));
  S.cstream.feed(${JSON.stringify(SAMPLE.slice(0, 300))}); S.cstream.feed(${JSON.stringify(SAMPLE.slice(300))}); 1`);
check("hostile text is shown, not run", await ev("!window.__pwned && document.getElementById('clog').textContent.includes('<img src=x onerror=window.__pwned=1> stays text')"));
check("the text on screen is the plain text (no codes, no markers): what Copy gives", await ev(`document.getElementById("clog").textContent === tcPlain(${JSON.stringify(SAMPLE)})`));
check("errors, warnings, successes and notes get a marker in the gutter", await ev(`["lv-err","lv-warn","lv-ok","lv-info"].every(c => { const el = document.querySelector("#clog .ln." + c); return el && getComputedStyle(el, "::before").content.length > 2; })`));
check("an error line is red, plain output keeps the console colour", await ev(`getComputedStyle(document.querySelector("#clog .ln.lv-err")).color !== getComputedStyle(document.getElementById("clog")).color
  && getComputedStyle([...document.querySelectorAll("#clog .ln")].find(l => l.className === "ln" && /Read1/.test(l.textContent))).color === getComputedStyle(document.getElementById("clog")).color`));
check("the program's own colours are shown (16, 256 and true colour)", await ev(`!!document.querySelector("#clog .a-f2") && [...document.querySelectorAll("#clog .a")].some(s => s.style.color)`));
check("the progress line shows only its last state", await ev(`document.getElementById("clog").textContent.includes(" [##########] 100%") && !document.getElementById("clog").textContent.includes("40%")`));
// the Colours menu
await ev(`document.getElementById("tcmenu").open = true; 1`);
check("the Colours menu opens with the mode and a legend of 7 types", await until(`document.getElementById("tcmode").value === TC.mode && document.querySelectorAll("#tclegend li").length === 7`));
for (const theme of ["dark", "light"]) {
  await ev(`document.documentElement.dataset.theme = "${theme}"; 1`);
  for (const w of [1280, 700]) {
    await send("Emulation.setDeviceMetricsOverride", {width: w, height: 900, deviceScaleFactor: 1, mobile: false}); await sleep(300); await shot(`window_${theme}_${w}`);
    check(`${theme} theme, ${w} px: the Colours menu is inside the window`, await ev(`(() => { const r = document.querySelector("#tcmenu .tcpop").getBoundingClientRect(); return r.width > 100 && r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0; })()`),
      await ev(`JSON.stringify(document.querySelector("#tcmenu .tcpop").getBoundingClientRect())`));
  }
}
await send("Emulation.setDeviceMetricsOverride", {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
await ev(`{ const s = document.getElementById("tcmode"); s.value = "full"; s.dispatchEvent(new Event("change")); } 1`);
check("Full by type colours a whole warning line", await ev(`document.getElementById("clog").dataset.tc === "full" && getComputedStyle(document.querySelector("#clog .ln.lv-warn")).color !== getComputedStyle(document.getElementById("clog")).color`));
await shot("window_full");
await ev(`{ const s = document.getElementById("tcmode"); s.value = "off"; s.dispatchEvent(new Event("change")); } 1`);
check("Off: plain text, no markers, no colours", await ev(`document.getElementById("clog").dataset.tc === "off" && getComputedStyle(document.querySelector("#clog .ln.lv-err")).color === getComputedStyle(document.getElementById("clog")).color
  && getComputedStyle(document.querySelector("#clog .ln.lv-err"), "::before").content === "none"`));
await ev(`{ const s = document.getElementById("tcmode"); s.value = "status"; s.dispatchEvent(new Event("change")); } document.getElementById("tcmenu").open = false; 1`);
// a real Terminal command that prints colour codes
await ev(`setCTab("term"); 1`);
const ready = await until("!document.getElementById('tcmd').disabled", 30000);
if (ready) {
  const shell = await ev(`document.getElementById("tsh").value || ""`);
  const cmd = /powershell|pwsh/i.test(shell) ? 'Write-Output "$([char]27)[32mgreen$([char]27)[0m and plain"' : /cmd/i.test(shell) ? "" : "printf '\\033[32mgreen\\033[0m and plain\\n'";
  if (!cmd) { console.log("  n/a   the Terminal shell here is cmd: no colour command to try"); process.exit(results.every(Boolean) ? 0 : 1); }
  await ev(`document.getElementById("tcmd").value = ${JSON.stringify(cmd)}; termRun(); 1`);
  check("a real Terminal command's colour codes come back as colours", await until(`!!document.querySelector("#tlog .a-f2") && document.getElementById("tlog").textContent.includes("green and plain")`, 30000),
    await ev(`document.getElementById("tlog").textContent.slice(-300)`));
  await shot("terminal_tab");
} else console.log("  n/a   the Terminal tab is not available here");
console.log(results.every(Boolean) ? "ALL TERMINAL COLOUR BROWSER TESTS PASSED" : "TERMINAL COLOUR BROWSER TESTS FAILED");
process.exit(results.every(Boolean) ? 0 : 1);
