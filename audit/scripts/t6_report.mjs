import { launch } from "./cdp.mjs";
const SP = process.argv[2]; const file = process.argv[3]; const tag = process.argv[4];
const b = await launch({ profile: `${SP}/ui/chrome_${tag}`, port: 9336 + Number(process.argv[5] || 0), width: 1400, height: 1000 });
await b.send("Page.navigate", { url: "file:///" + file.replace(/\\/g, "/") }); await b.sleep(6000);
const ev = x => b.evalJS(x);
console.log("title:", await ev("document.title"));
console.log("size KB (html):", await ev("Math.round(document.documentElement.outerHTML.length/1024)"));
console.log("sections:", JSON.stringify(await ev("[...document.querySelectorAll('section[id]')].map(s=>s.id).slice(0,40)")));
console.log("dangling #anchors:", JSON.stringify(await ev("[...new Set([...document.querySelectorAll('a[href^=\"#\"]')].map(a=>a.getAttribute('href').slice(1)).filter(h=>h&&!document.getElementById(h)))]")));
console.log("sortable tables:", await ev("document.querySelectorAll('table.sortable').length"), "| th with tabindex:", await ev("document.querySelectorAll('table.sortable th[tabindex]').length"), "| th aria-sort:", await ev("document.querySelectorAll('table.sortable th[aria-sort]').length"), "| th as button:", await ev("document.querySelectorAll('table.sortable th button').length"));
console.log("svg total / role=img:", await ev("document.querySelectorAll('svg').length"), "/", await ev("document.querySelectorAll('svg[role=img]').length"));
console.log("noscript:", await ev("document.querySelectorAll('noscript').length"), "| dark-mode media:", await ev("[...document.styleSheets].some(s=>{try{return [...s.cssRules].some(r=>r.media&&/prefers-color-scheme/.test(r.media.mediaText))}catch(e){return false}})"));
// click a sortable header twice and check order changes + errors
const before = b.consoleErrors().length;
const sortRes = await ev(`(()=>{const t=document.querySelector('table.sortable');if(!t)return 'no sortable table';const ths=[...t.querySelectorAll('th')];const col=ths.findIndex(th=>/f1|score|recall|precision/i.test(th.innerText));const c=col<0?1:col;const read=()=>[...t.querySelectorAll('tbody tr')].slice(0,6).map(r=>r.children[c]&&r.children[c].innerText.trim());const a=read();ths[c].click();const s1=read();ths[c].click();const s2=read();return JSON.stringify({col:ths[c].innerText.trim(),before:a,asc:s1,desc:s2})})()`);
console.log("sort test:", sortRes);
// score-table CSV export: read the blob content by intercepting createObjectURL
const csv = await ev(`(async()=>{const btn=document.querySelector('#export-scores');if(!btn)return 'no #export-scores button';let blobText='';const orig=URL.createObjectURL;URL.createObjectURL=b=>{b.text().then(t=>blobText=t);return orig(b)};btn.click();await new Promise(r=>setTimeout(r,500));return blobText.split('\\n').slice(0,3).join(' | ').slice(0,300)||'(no blob)'})()`);
console.log("CSV export first lines:", csv);
// help buttons
const help = await ev(`(()=>{const hs=[...document.querySelectorAll('[data-help], .rpt-info, button[aria-label*="elp" i], button[title*="elp" i]')];return {count:hs.length}})()`);
console.log("help buttons:", JSON.stringify(help));
console.log("console errors:", JSON.stringify(b.consoleErrors().slice(0, 6)));
await b.shot(`${SP}/ui/shots/report_${tag}.png`);
await b.close();
