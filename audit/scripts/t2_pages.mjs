import { launch } from "./cdp.mjs";
import fs from "node:fs";
const SP = process.argv[2];
const url = JSON.parse(fs.readFileSync(`${SP}/ui/uihome/server.json`, "utf8")).url;
const b = await launch({ profile: `${SP}/ui/chrome2`, port: 9334 });
await b.send("Page.navigate", { url }); await b.sleep(3500);
const items = await b.evalJS(`[...document.querySelectorAll('nav > a, nav > button, nav .item, nav li')].map((e,i)=>(e.innerText||'').split('\\n')[0].trim()).filter(Boolean)`);
console.log("sidebar items found:", JSON.stringify(items));
// Click each of the 15 pages by visible label
const labels = ["Home","Set up this computer","Tools","Add your own tool","Scoring decisions","Settings","Workspace & studies","New benchmark","Your own isolates","Cohorts","Runs & reports","Jobs","Version control","All commands","Guides"];
for (const L of labels) {
  const before = b.consoleErrors().length;
  const ok = await b.evalJS(`(()=>{const els=[...document.querySelectorAll('*')].filter(e=>e.children.length<=3 && (e.innerText||'').split('\\n')[0].trim()===${JSON.stringify(L)});const t=els.find(e=>e.closest('nav')||e.closest('.rail')||e.closest('aside'))||els[0];if(!t)return false;(t.closest('a,button,li,div[role]')||t).click();return true;})()`);
  await b.sleep(1200);
  const heading = await b.evalJS(`(document.querySelector('main h1, .page:not([hidden]) h1, h1')||{}).innerText||''`);
  const errs = b.consoleErrors().slice(before);
  await b.shot(`${SP}/ui/shots/page_${L.replace(/[^A-Za-z]/g,'_')}.png`);
  console.log(`${L.padEnd(24)} clicked=${ok} heading="${heading.slice(0,40)}" newErrors=${errs.length}${errs.length ? " " + JSON.stringify(errs.slice(0,2)) : ""}`);
}
console.log("ALL console errors:", JSON.stringify(b.consoleErrors()));
await b.close();
