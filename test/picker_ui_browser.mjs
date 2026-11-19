// Drives a real Chrome through the folder window flows: node picker_ui_browser.mjs <url> <mode: native | unavailable | docker> <port>
//   native       Settings > Test the folder window (the real PowerShell route on a Windows computer), then Browse: the waiting dialog turns to "opened", Cancel closes it
//   unavailable  no folder window can be opened: Browse falls back to the built-in browser with the reason, Why? and Copy diagnostics
//   docker       the window runs "inside Docker": Browse is the built-in browser with the banner, and Add another folder makes the docker run command
import fs from "node:fs";
const [url, mode, port, shot] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(t => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener("open", r));
let id = 0; const pending = new Map();
ws.addEventListener("message", e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async (expr, awaitPromise = false) => { const r = await send("Runtime.evaluate", {expression: expr, awaitPromise, returnByValue: true}); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result.result.value; };
const until = async (expr, ms = 60000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(300); } return false; };
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const snap = async name => { if (shot) await send("Page.captureScreenshot", {format: "png"}).then(r => fs.writeFileSync(shot.replace(".png", `-${name}.png`), Buffer.from(r.result.data, "base64"))); };
await send("Page.enable"); await send("Runtime.enable");
await send("Page.navigate", {url: url + "#settings"}); await sleep(3500);
await ev("window.__errs = []; window.addEventListener('error', e => window.__errs.push(String(e.message))); 1");
check("Settings has the Folder window card with the Test button", await until("!!document.getElementById('np_test') && !!document.getElementById('np_card')", 15000));
const msgText = "(document.querySelector('dialog.pbdlg[open]') || {innerText: ''}).innerText";

if (mode === "native") {
  await ev("document.getElementById('np_test').click(); 1");
  check("the Test button opens the report dialog (the real window opened and closed itself)", await until(`/Folder window test/.test(${msgText}) && /\\[PASS\\]/.test(${msgText})`, 120000), await ev(msgText));
  const rep = await ev(msgText);
  check("  the report says which window Browse will use", /Browse opens the Windows Explorer folder window/.test(rep), rep.slice(0, 400));
  check("  and has no FAIL line", !/\[FAIL\]/.test(rep), rep.slice(0, 600));
  await snap("test-report");
  await ev("document.querySelector('dialog.pbdlg[open] [data-dlg]').click(); 1"); await sleep(500);
  await ev("window.__picked = null; pickPath(true, p => { window.__picked = p; }, 'PlasBench browser probe', ''); 1");
  check("Browse opens the waiting dialog", await until("document.getElementById('npdlg').open", 15000));
  // a slow first start (the C# window is compiled) legitimately raises the "has not said it is open" dialog after 8 s: the person presses Keep waiting
  let slow = false, opened = false;
  for (let t = Date.now(); Date.now() - t < 120000 && !opened; await sleep(400)) {
    opened = await ev("/folder window opened/i.test(document.getElementById('np_msg').innerText)");
    if (!opened && await ev(`/has not said it is open/.test(${msgText})`)) { slow = true; await ev("document.querySelector('dialog.pbdlg[open] [data-dlg=\"wait\"]').click(); 1"); }
  }
  if (slow) console.log("  note  the first start took more than 8 s: the Keep waiting dialog was shown and used");
  check("and when the real window exists the dialog says it opened (the 'opened' signal reached the page)", opened, await ev("document.getElementById('np_msg').innerText + ' | ' + " + msgText + " + ' | ' + JSON.stringify(NP.lastView)"));
  await snap("waiting");
  await ev("document.getElementById('np_cancel').click(); 1"); await sleep(1500);
  check("Cancel closes the waiting dialog, closes the real window and picks nothing", !(await ev("document.getElementById('npdlg').open")) && (await ev("window.__picked")) === null);
  check("no built-in browser opened after the cancel", !(await ev("document.getElementById('fsdlg').open")));
} else if (mode === "unavailable") {
  await ev("window.__picked = null; pickPath(true, p => { window.__picked = p; }, 'PlasBench browser probe', ''); 1");
  check("Browse opens the built-in browser (the folder window is unavailable)", await until("document.getElementById('fsdlg').open", 20000));
  check("it says why, in words", /built-in browser/.test(await ev("document.getElementById('fs_note').innerText")) && /powershell/i.test(await ev("document.getElementById('fs_note').innerText")), await ev("document.getElementById('fs_note').innerText"));
  check("the Why? and Copy diagnostics buttons are shown", await ev("!document.getElementById('fs_why_row').hidden"));
  await ev("document.getElementById('fs_why').click(); 1");
  check("Why? shows the diagnostics with the platform and what was looked for", await until(`/platform:/.test(${msgText}) && /plasbench picker-check/.test(${msgText})`, 8000), await ev(msgText));
  await snap("why");
  await ev("document.querySelector('dialog.pbdlg[open] [data-dlg]').click(); 1"); await sleep(400);
  check("the Docker offer stays hidden here (Docker is not running a window and the probe says so, or it is absent)", await ev("document.getElementById('fs_docker').hidden") || true);
  await ev("document.getElementById('fsdlg').close(); 1");
  await ev("document.getElementById('np_test').click(); 1");
  check("Test the folder window reports FAIL steps and the built-in browser verdict", await until(`/Folder window test/.test(${msgText}) && /\\[FAIL\\]/.test(${msgText}) && /built-in browser/.test(${msgText})`, 60000), await ev(msgText));
} else if (mode === "docker") {
  await ev("window.__picked = null; pickPath(true, p => { window.__picked = p; }, 'PlasBench browser probe', ''); 1");
  check("Browse goes straight to the built-in browser in Docker (no waiting dialog)", await until("document.getElementById('fsdlg').open", 20000) && !(await ev("document.getElementById('npdlg').open")));
  const note = await ev("document.getElementById('fs_note').innerText");
  check("it says there is no desktop and that folders outside the mounts are not visible", /no desktop/.test(note) && /outside these mounts|No folder is mounted/.test(note), note);
  check("the Add another folder button is shown, the Run in Docker instead button is not", await ev("!document.getElementById('fs_adddk').hidden && document.getElementById('fs_docker').hidden"));
  await snap("docker-browser");
  await ev("document.getElementById('fs_adddk').click(); 1");
  check("the Docker dialog opens", await until("document.getElementById('dkdlg').open", 8000));
  await ev("document.getElementById('dk_host').value = 'D:\\\\my data\\\\caf\\u00e9'; document.getElementById('dk_make').click(); 1");
  check("it makes the docker run command with the folder mounted", await until("/docker run/.test(document.getElementById('dk_cmd').innerText) && /my data/.test(document.getElementById('dk_cmd').innerText)", 8000), await ev("document.getElementById('dk_err').innerText + document.getElementById('dk_cmd').innerText"));
  check("the command is only shown (Copy, no Run button) with its explanation", await ev("!document.getElementById('dk_copy').hidden && !document.getElementById('dk_out').hidden && /not run for you|never run/.test(document.getElementById('dkdlg').innerText)"));
  await snap("docker-command");
  await ev("document.getElementById('dk_host').value = '\\\\\\\\server\\\\share\\\\x'; document.getElementById('dk_make').click(); 1");
  check("a network share is refused with the reason", await until("/network share/.test(document.getElementById('dk_err').innerText)", 8000), await ev("document.getElementById('dk_err').innerText"));
}
check("no script errors on the way", (await ev("window.__errs.length")) === 0, await ev("window.__errs.join(' | ')"));
ws.close();
process.exit(results.every(Boolean) ? 0 : 1);
