import { launch } from "./cdp.mjs";
import fs from "node:fs";
const SP = process.argv[2];
const url = JSON.parse(fs.readFileSync(`${SP}/ui/uihome/server.json`, "utf8")).url;
const b = await launch({ profile: `${SP}/ui/chrome3`, port: 9335 });
await b.send("Page.navigate", { url }); await b.sleep(3000);
// open the Cohorts page
await b.evalJS(`(()=>{const e=[...document.querySelectorAll('*')].filter(x=>x.children.length<=3&&(x.innerText||'').split('\\n')[0].trim()==='Cohorts');(e.find(x=>x.closest('nav,aside'))||e[0]).closest('a,button,li,div').click();})()`);
await b.sleep(2000);
const rows = await b.evalJS(`[...document.querySelectorAll('#cohtb tr')].map(r=>({name:r.dataset.coh, hasDetails:!!r.querySelector('button[onclick^="cohortInfo"]'), onclick:(r.querySelector('button[onclick^="cohortInfo"]')||{}).getAttribute?.('onclick'), dataRun:(r.querySelector('button[data-run]')||{}).outerHTML?.slice(0,260)}))`);
console.log("cohort rows:", rows.length);
for (const r of rows.filter(r => /pwn|Neil/.test(r.name || ""))) console.log(JSON.stringify(r, null, 1));
const before = b.consoleErrors().length;
console.log("window.__pwn before click:", await b.evalJS("String(window.__pwn)"));
// click Details on the crafted row, exactly as a user would
await b.evalJS(`(()=>{const r=[...document.querySelectorAll('#cohtb tr')].find(r=>/pwn/.test(r.dataset.coh||''));r.querySelector('button[onclick^="cohortInfo"]').click();})()`);
await b.sleep(1500);
console.log("window.__pwn after click Details on crafted name:", await b.evalJS("String(window.__pwn)"));
// the O'Neil row: Details and Validate
await b.evalJS(`(()=>{const r=[...document.querySelectorAll('#cohtb tr')].find(r=>/Neil/.test(r.dataset.coh||''));if(!r)return 'no row';r.querySelector('button[onclick^="cohortInfo"]')?.click();return 'clicked';})()`);
await b.sleep(1200);
const valBtn = await b.evalJS(`(()=>{const r=[...document.querySelectorAll('#cohtb tr')].find(r=>/Neil/.test(r.dataset.coh||''));const v=r&&r.querySelector('button[data-run]');return v?{run:v.getAttribute('data-run'),label:v.getAttribute('data-label')}:null})()`);
console.log("O'Neil Validate button data-run attribute as parsed by the browser:", JSON.stringify(valBtn));
let parsed = "n/a"; try { parsed = JSON.stringify(JSON.parse(valBtn.run)); } catch (e) { parsed = "JSON.parse throws: " + e.message; }
console.log("JSON.parse of that attribute:", parsed);
console.log("new console errors:", JSON.stringify(b.consoleErrors().slice(before)));
await b.shot(`${SP}/ui/shots/inject_after.png`);
await b.close();
