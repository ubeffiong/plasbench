// Drives a real Chrome through "Your own isolates": add a folder -> Find my files -> Place -> quick test -> Label sequences -> usable -> Benchmark this sheet.
import fs from "node:fs";
const [url, folder, sheet, dataDir, shot] = process.argv.slice(2);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const targets = await (await fetch("http://127.0.0.1:9334/json")).json();
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
await send("Page.enable"); await send("Runtime.enable");
await send("Page.navigate", {url: url + "#isolates"}); await sleep(3500);
const errors = [];
await ev("window.__errs = []; window.addEventListener('error', e => window.__errs.push(String(e.message))); 1");

check("the page opens on Your own isolates with the three steps", await ev("!!document.getElementById('in_get') && !!document.getElementById('in_find') && !!document.getElementById('in_test')"));
check("template buttons are offered (own isolates, public cohort, truth table)", await until("document.querySelectorAll('#in_tpl [data-tpl]').length === 3", 8000));
check("the default data folder and sheet are filled in", await until("document.getElementById('in_data').value.length > 0 && document.getElementById('in_sheet').value.length > 0", 8000));
check("Find my files is disabled until a folder is added", await ev("document.getElementById('in_scan').disabled"));

await ev(`document.getElementById('in_fpath').value = ${JSON.stringify(folder)}; document.getElementById('in_fadd').click(); 1`);
await ev(`document.getElementById('in_sheet').value = ${JSON.stringify(sheet)}; document.getElementById('in_data').value = ${JSON.stringify(dataDir)}; 1`);
check("the folder is listed and Find my files is enabled", await ev("document.querySelectorAll('#in_folders .tag').length === 1 && !document.getElementById('in_scan').disabled"));
await ev("document.getElementById('in_scan').click(); 1");
check("the scan lists both isolates", await until("document.querySelectorAll('#in_found tr[data-in]').length === 2"), await ev("document.getElementById('in_found').innerText.slice(0,300)"));
check("the reference match says how sure it is", /confident|likely/.test(await ev("document.getElementById('in_found').innerText")));
check("the organism is pre-filled from the FASTA header as a guess to confirm", (await ev("[...document.querySelectorAll('[data-inorg]')].map(i => i.value).join('|')")).includes("Klebsiella pneumoniae"));
await send("Page.captureScreenshot", {format: "png"}).then(r => fs.writeFileSync(shot.replace(".png", "-scan.png"), Buffer.from(r.result.data, "base64")));

await ev("document.getElementById('in_stage').click(); 1");
check("placing runs the quick test straight away", await until("document.querySelectorAll('#in_result .card').length === 2", 90000), await ev("document.getElementById('in_result').innerText.slice(0,300)"));
const text = await ev("document.getElementById('in_result').innerText");
check("an isolate whose labels are undecided is not usable, and says what to do", /not usable yet/.test(text) && /What to do/.test(text) && /REVIEW/.test(text), text.slice(0, 300));
check("a Label sequences button is offered, and a guide link", await ev("!!document.querySelector('[data-inlabel]') && !!document.querySelector('#in_result a[href=\"#help/docs/INPUT_GUIDE.md\"]')"));
check("the reads-versus-reference comparison ran and passed for the matching isolate", /Reads come from this reference's isolate/.test(text));

await ev("document.querySelector('[data-inlabel]').click(); 1");
check("the label dialog opens with one row per sequence", await until("document.getElementById('lbldlg').open && document.querySelectorAll('#lb_body tr[data-lbid]').length === 2"));
await ev("document.getElementById('lb_save').click(); 1"); await sleep(800);
check("saving with a sequence unlabelled is refused with a reason", /no label/.test(await ev("document.getElementById('lb_msg').innerText")) && await ev("document.getElementById('lbldlg').open"));
await send("Page.captureScreenshot", {format: "png"}).then(r => fs.writeFileSync(shot.replace(".png", "-labels.png"), Buffer.from(r.result.data, "base64")));
await ev("document.querySelectorAll('#lb_body [data-lbsel]').forEach((s, i) => { s.value = i === 0 ? 'CHROMOSOME' : 'PLASMID'; }); document.getElementById('lb_save').click(); 1");
check("with every sequence labelled the dialog closes and the test re-runs", await until("!document.getElementById('lbldlg').open"));
check("every isolate is now usable and Benchmark this sheet is offered", await until("!!document.getElementById('in_go') && document.querySelectorAll('#in_result .tag.bad').length === 0", 90000), await ev("document.getElementById('in_result').innerText.slice(0,500)"));
await send("Page.captureScreenshot", {format: "png"}).then(r => fs.writeFileSync(shot, Buffer.from(r.result.data, "base64")));
await ev("document.getElementById('in_go').click(); 1"); await sleep(800);
check("Benchmark this sheet opens the wizard with the sheet chosen", (await ev("location.hash")).startsWith("#wizard") && (await ev("S.wiz.values.samples")) === sheet);
check("no script errors on the way", (await ev("window.__errs.length")) === 0, await ev("window.__errs.join(' | ')"));
ws.close();
process.exit(results.every(Boolean) ? 0 : 1);
