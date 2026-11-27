function aiActionCard(a, mi, i) {
  const where = AI_WHERE[a.where] || AI_PLAIN_WHERE;
  const termOk = a.ok && (a.where === "window" || a.where === "terminal");
  return `<div class="aicard2" data-m="${mi}" data-i="${i}"><div class="ch"><b>Suggested command</b><span class="risk ${esc(a.risk)}">${esc(String(a.risk).replace("_", " "))}</span></div><div class="cb">
    <div class="cmdbox">${esc(a.cmd)}</div><div class="where">Run it here: ${esc(where)}</div>${a.why ? `<div class="why">${esc(a.why)}</div>` : ""}
    ${a.runnable ? "" : `<div class="no">Not runnable here: ${esc(a.reason)}</div>`}
    <div class="acts">${a.runnable ? `<button class="btn sm" data-aiact="run">${icon("play")}Run in PlasBench</button>` : ""}<button class="btn sec sm" data-aiact="copy">${icon("copy")}Copy</button>${termOk ? `<button class="btn sec sm" data-aiact="term">${icon("term")}Open Terminal tab</button>` : ""}</div>
    <div class="runstate" aria-live="polite"></div></div></div>`;
}
