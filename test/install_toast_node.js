// Pure state and markup functions of the installing toast (plasbench/data/ui.html, between INSTALL-TOAST-PURE-BEGIN and -END): node install_toast_node.js <ui.html> <argv-table.json>
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8"), table = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const a = html.indexOf("/* ==INSTALL-TOAST-PURE-BEGIN== */"), b = html.indexOf("/* ==INSTALL-TOAST-PURE-END== */");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const T = new Function("esc", html.slice(a, b) + "\nreturn {itKind, itIsInstallArgv, itModel, itHTML, itAway, itLiveTitle, itDoneTitle, itLive};")(esc);
let bad = 0;
const check = (name, ok, detail = "") => { if (!ok) bad++; console.log((ok ? "  ok    " : "  FAIL  ") + name + (ok ? "" : `  [${detail}]`)); };
const NOW = 1000000;
let seq = 0;
const job = (o = {}) => Object.assign({id: "j" + (++seq), is_install: true, state: "running", display_state: "running", started: NOW - 30, ended: null, exit: null,
  install_label: "Installing Docker…", install_tools: ["docker"], install_kind: "install-tools", last_line: "", command: "plasbench install-tools docker --yes"}, o);
const ctx = (o = {}) => Object.assign({now: NOW, dismissed: new Set(), hidden: new Set(), away: [], doneUntil: {}, pending: null}, o);
const model = (jobs, o) => T.itModel(jobs, ctx(o));
const H = (m, ui = {}) => T.itHTML(m, ui);

// the click-time guess equals the server's table
const wrong = table.filter(([argv, want]) => T.itIsInstallArgv(argv) !== want).map(r => r[0].join(" "));
check(`the click-time install guess matches the server table (${table.length} argvs)`, !wrong.length, wrong);

// running -> waiting -> done
let j = job({last_line: "Downloading docker-ce (42%)"});
let m = model([j]);
check("a running install shows one live card with its title, the phase line and View log / Cancel / Hide",
  m.live.length === 1 && H(m).includes("Installing Docker…") && H(m).includes("Downloading docker-ce (42%)") && H(m).includes('data-it="view"') && H(m).includes('data-it="cancel"') && H(m).includes('data-it="hide"'));
check("the live card is not an alert and has the tooltip slot", !H(m).includes('role="alert"') && H(m).includes('data-tipid="install_toast"'));
check("no clock text in the markup, so a poll that changes nothing leaves the DOM alone", H(m) === H(model([Object.assign({}, j)], {now: NOW + 5})));
j = job({id: "w1", state: "failed", display_state: "waiting_for_you", exit: 20, ended: NOW - 3, waiting_place: "Docker Desktop"});
m = model([j]);
check("exit-20 Docker handoff: Waiting for you to finish in <place>, Re-check, stays",
  m.attn.length === 1 && H(m).includes("Waiting for you to finish in Docker Desktop") && H(m).includes('data-it="recheck"') && model([j], {now: NOW + 3600}).attn.length === 1);
j = job({state: "failed", display_state: "consent_needed", exit: 21, ended: NOW - 3});
check("exit 21: Consent needed", H(model([j])).includes("Consent needed"));
j = job({state: "failed", display_state: "manual_step", exit: 20, ended: NOW - 3, install_tools: ["plsmd"], install_label: "Installing plsmd…"});
check("manual profile: Manual step needed, no Re-check", H(model([j])).includes("Manual step needed") && !H(model([j])).includes('data-it="recheck"'));
j = job({display_state: "stalled"});
check("stalled (the existing display state): Stalled? with Cancel still offered", H(model([j])).includes("Stalled? Installing Docker…") && H(model([j])).includes('data-it="cancel"'));
j = job({state: "cancelling", display_state: "cancelling"});
check("cancelling: titled Cancelling, no second Cancel", H(model([j])).includes("Cancelling: Docker") && !H(model([j])).includes('data-it="cancel"'));
// done
const done = job({id: "d1", state: "done", display_state: "done", exit: 0, ended: NOW - 2, installed_version: "27.0.1"});
check("done: green card with the version", model([done]).done.length === 1 && H(model([done])).includes("Docker installed (version 27.0.1)") && H(model([done])).includes("it-card ok"));
check("done: shown for 8 s, then gone (auto-dismiss)", model([done], {now: NOW + 5}).done.length === 1 && model([done], {now: NOW + 7}).done.length === 0);
check("done seen live in this page keeps its full 8 s even when the poll was late", model([Object.assign({}, done, {ended: NOW - 20})], {doneUntil: {d1: NOW + 4}}).done.length === 1);
check("done: a dismissed card stays dismissed", model([done], {dismissed: new Set(["d1"])}).done.length === 0);
check("done titles by kind", T.itDoneTitle(job({install_kind: "upgrade"})) === "PlasBench updated" && T.itDoneTitle(job({install_kind: "runtime-pull"})) === "Image pulled" && T.itDoneTitle(job({install_kind: "check-yes"})) === "Tools and databases ready");
// failed stays
const failed = job({id: "f1", state: "failed", display_state: "failed", exit: 1, ended: NOW - 5, last_line: "ERROR: could not resolve gplas2"});
const hf = H(model([failed]));
check("failed: red alert card with the one-line reason and View log", hf.includes('role="alert"') && hf.includes("it-card bad") && hf.includes("ERROR: could not resolve gplas2") && hf.includes('data-it="view"'));
check("failed stays well past 8 s, until dismissed", model([failed], {now: NOW + 3600}).attn.length === 1 && model([failed], {now: NOW + 3600, dismissed: new Set(["f1"])}).attn.length === 0);
check("failed is replaced when a newer try of the same install runs or succeeds",
  model([failed, job({started: NOW - 1})]).attn.length === 0 && model([failed, job({state: "done", display_state: "done", started: NOW - 2, ended: NOW - 1})], {now: NOW + 100}).attn.length === 0);
check("failed older than a day is not shown", model([failed], {now: NOW + 90000}).attn.length === 0);
check("a cancelled install shows nothing", (() => { const m2 = model([job({state: "cancelled", display_state: "cancelled", ended: NOW - 1})]); return !m2.attn.length && !m2.done.length && !m2.live.length; })());
check("a non-install job never shows", model([job({is_install: false})]).live.length === 0);
// multiple
const many = [job({id: "a", install_label: "Installing Docker…"}), job({id: "b", install_label: "Installing plsmd…", install_tools: ["plsmd"]}), job({id: "c", install_label: "Installing gplas2…", install_tools: ["gplas2"]})];
m = model(many);
check("three concurrent installs combine into one card titled with the count", m.live.length === 3 && H(m).match(/data-k="live"/g).length === 1 && H(m).includes("Installing 3 tools…"));
check("the combined card lists the names collapsed and the per-job rows when expanded", H(m).includes("Docker, plsmd, gplas2") && !H(m).includes("it-list") && H(m, {open: true}).includes("it-list") && H(m, {open: true}).includes('aria-expanded="true"'));
check("mixed kinds say how many installations are running", T.itLiveTitle([job(), job({install_kind: "upgrade", install_tools: ["plasbench"], install_label: "Updating PlasBench…"})]) === "2 installations running…");
const lots = Array.from({length: 7}, (_, i) => job({id: "m" + i, install_tools: ["t" + i], install_label: `Installing t${i}…`}));
check("many installs: the expanded list is capped with 'and N more'", H(model(lots), {open: true}).includes("and 3 more"));
check("Cancel is per row when combined (none on the collapsed card)", !H(model(many)).includes('data-it="cancel"') && H(model(many), {open: true}).match(/data-it="cancel"/g).length === 3);
// hide / collapse
const hidden = model(many, {hidden: new Set(["a", "b", "c"])});
check("hide: the card is gone and the model says hidden (the chip shows the count)", hidden.hidden && hidden.live.length === 3 && !H(hidden).includes('data-k="live"'));
check("hide is per job: a new install un-hides it", !model(many.concat(job({id: "n"})), {hidden: new Set(["a", "b", "c"])}).hidden);
check("a failure still shows while the live card is hidden", H(model([job({id: "a"}), failed], {hidden: new Set(["a"])})).includes("it-card bad"));
// pending
check("optimistic: a click shows 'Starting: ...' before any job exists", H(model([], {pending: {label: "Install Docker", t0: NOW * 1000}})).includes("Starting: Install Docker…"));
check("optimistic card gives way to the job's own card", model([job({started: NOW})], {pending: {label: "x", t0: NOW * 1000}}).pending === null);
// last seen
const ended = job({id: "e1", state: "done", display_state: "done", ended: NOW - 600}), ended2 = job({id: "e2", state: "failed", display_state: "failed", ended: NOW - 5000});
check("away: only jobs that ended after the last time this browser saw the list", JSON.stringify(T.itAway([ended, ended2], NOW - 1000, new Set())) === '["e1"]');
check("away: a first visit (no last-seen time) shows nothing", T.itAway([ended, ended2], null, new Set()).length === 0);
check("away: a running job and a dismissed job are not in it", T.itAway([job({started: NOW - 10}), ended], NOW - 1000, new Set(["e1"])).length === 0);
const away = model([ended], {away: ["e1"]});
check("away: one 'Finished while you were away' summary, dismissible", H(away).includes("Finished while you were away") && H(away).includes('data-id="away"') && model([ended], {away: ["e1"], dismissed: new Set(["e1"])}).away.length === 0);
// markup safety
const evil = H(model([job({install_label: "Installing <img src=x onerror=1>…", last_line: "<script>1</script>"})]));
check("names and lines are escaped", !evil.includes("<img") && !evil.includes("<script>"));
console.log(bad ? "FAILED" : "ALL PASS");
process.exit(bad ? 1 : 0);
