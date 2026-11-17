// Minimal Chrome DevTools Protocol client (Node 24 built-in WebSocket/fetch). No dependencies.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export async function launch({ port = 9333, profile, width = 1400, height = 900 }) {
  const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe",
    ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
     `--window-size=${width},${height}`, "--no-first-run", "--disable-gpu", "about:blank"],
    { stdio: "ignore" });
  let targets;
  for (let i = 0; i < 60; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.length) break; } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
  const page = targets.find(t => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map(); const events = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
    else if (m.method) events.push(m);
  };
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");
  const evalJS = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const shot = async (file) => { const r = await send("Page.captureScreenshot", { format: "png" }); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, Buffer.from(r.data, "base64")); };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const consoleErrors = () => events.filter(e => (e.method === "Runtime.exceptionThrown") || (e.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(e.params.type)) || (e.method === "Log.entryAdded" && ["error", "warning"].includes(e.params.entry.level)))
    .map(e => e.method === "Runtime.exceptionThrown" ? "EXC: " + (e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text).slice(0, 300)
      : e.method === "Runtime.consoleAPICalled" ? e.params.type + ": " + e.params.args.map(a => a.value ?? a.description).join(" ").slice(0, 300)
      : e.params.entry.level + ": " + e.params.entry.text.slice(0, 300) + " " + (e.params.entry.url || ""));
  const close = async () => { try { await send("Browser.close"); } catch {} try { ws.close(); } catch {} try { chrome.kill(); } catch {} };
  return { send, evalJS, shot, sleep, events, consoleErrors, close };
}
