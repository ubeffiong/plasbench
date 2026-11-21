#!/usr/bin/env python3
"""The AI help tab in plasbench/data/ui.html, checked statically (and with Node when it is installed): the page script still parses, the elements the code needs exist once,
accessibility attributes are there, the pop-up is opened by the click itself and never navigates this window, model text only reaches the page through md() (escape first), the
message handler checks origin and source, and no secret or provider-specific key is in the page."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


print("elements")
for ident in ("aibtn", "gdp_ai", "ai_tools", "ai_prov", "ai_model", "ai_brief", "ai_remember", "ai_new", "ai_state", "ai_log", "ai_starters", "ai_form", "ai_in", "ai_send", "ai_stop", "ai_foot", "ai_live"):
    check(f"#{ident} appears exactly once", len(re.findall(r'id="%s"' % ident, html)) == 1)
check("the AI tab is in the drawer's tab list", 'data-pt="ai"' in html)
check("the log is a live region with a name", re.search(r'id="ai_log" role="log" aria-live="polite" aria-label="[^"]+"', html))
check("the composer has an accessible label and Enter sends, Shift+Enter does not", 'aria-label="Your question (Enter sends, Shift+Enter adds a line)"' in html and 'e.key === "Enter" && !e.shiftKey' in html)
check("the shortcut is Alt+Shift+H and the button names it", "Alt+Shift+H" in html and 'e.altKey && e.shiftKey' in html)
check("a tooltip id is used for the privacy note", 'data-tipid="ai_privacy"' in html)

print("safety of the page code")
check("the pop-up is opened by the click handler itself, named, ~520x720, with no tab fallback", 'window.open("about:blank", "pb_ai_auth"' in html and "width=${w},height=${h}" in html and "w = 520, h = 720" in html and "target=\"_blank\"" not in html.split("function aiSignIn")[1].split("function aiWatchPop")[0])
check("a blocked pop-up shows a message and a retry, and never navigates this window", "Allow pop-ups for this page" in html and "location.href = r.url" in html and "pop.location.href" in html and not re.search(r"(?<!pop\.)location\.href = r\.url", html))
check("the sign-in is cancelled cleanly when the pop-up is closed", "AI.pop.closed" in html and 'AI.note = "cancelled"' in html and "Sign-in cancelled" in html)
check("no iframe or embedded webview for sign-in", "<iframe" not in html.split("AI help (the AI help tab")[1][:20000] if "AI help (the AI help tab" in html else False)
check("the message handler checks the origin, the source window and the state", "ok.has(e.origin)" in html and "e.source !== AI.pop" in html and "d.state !== AI.state" in html)
check("model text is rendered through md() (which escapes first) or esc()", "md(m.content" in html and "innerHTML = md(bot.content)" in html)
check("an action is run only after server validation, the extra confirmation and the consent dialog", 'api("ai/validate"' in html and "needs_extra_confirm" in html and "confirmRun(v.argv" in html)
check("confirmRun takes an optional callback and still shows the exact command", "function confirmRun(argv, label, env, onStart)" in html and '$("#cf_cmd").textContent' in html)
check("Send result shows the redacted text and asks before sending", 'api("ai/redact"' in html and "Send this result to the assistant?" in html)
check("votes and chats stay in this browser (localStorage), chats only when ticked", 'aiLS("votes"' in html and "function aiSaveChat() { if (!AI.remember) return;" in html)
check("no key, secret or provider key literal in the page", not re.search(r"sk-or-[A-Za-z0-9]{8,}|hf_[A-Za-z0-9]{12,}|client_secret", html))
check("the page asks the server for nothing at load except the local status", html.count("aiBoot()") == 2 and 'detect ? 1 : 0' in html)

print("script syntax")
node = shutil.which("node")
if node:
    scripts = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)
    big = max(scripts, key=len)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(big)
        name = fh.name
    r = subprocess.run([node, "--check", name], capture_output=True, text=True)
    check("the page script parses (node --check)", r.returncode == 0, r.stderr[-300:])
else:
    print("  (node not installed: syntax is checked by the browser test)")
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
