#!/usr/bin/env python3
"""The window's clutter rule, kept honest (the "UI cleanup" before release).

Rule: text that explains what a control means or how it works is a tooltip (the green (?) next to the label; its text lives in plasbench/ui_help.py);
text that reports a state, a problem or a decision the person must make stays visible.

  1. word budget: the descriptive paragraphs and notes written into each front-facing page (the static markup of ui.html) stay inside a budget, so explanation
     cannot creep back onto the page; states, warnings and errors are allow-listed by id;
  2. every help id the page uses (data-tipid="...", pageTip("..."), wizTip("...")) exists in ui_help.py, and every PAGE entry is used;
  3. no control was lost: the buttons, inputs, selects and links that were in the window before the cleanup are all still there (test/fixtures/ui_controls_before.json),
     except those named in MERGED below;
  4. the tooltip component opens on hover, focus and tap, closes on Escape, is role=tooltip and is described by aria-describedby.
Static checks of ui.html and ui_help.py (the browser behaviour is test_ui_cleanup_browser.py, opt-in).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from plasbench import ui_help, ui_schema  # noqa: E402

html = open(os.path.join(ROOT, "plasbench", "data", "ui.html"), encoding="utf-8").read()
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


# ---- 1. word budget ---------------------------------------------------------------------------------------------------------------------------------
VIEWS = ["home", "setup", "tools", "addtool", "prereg", "settings", "wizard", "workspace", "isolates", "cohorts", "runs", "jobs", "git", "commands", "help"]
BUDGET = 28          # words of explanation per page in the static markup (page subtitle + any leftover paragraph); the subtitle alone is about 12
# These carry a state, a warning or a decision, not an explanation of a control, so they are not counted.
ALLOW_IDS = {"herop", "pc_body", "pc_comp", "dk_title", "dk_wait", "dk_steps", "instbar", "ws_report", "ws_recent", "sessnote", "sc_msg", "in_scan_msg", "in_run_msg", "wt_status",
             "st_loccheck", "updresult", "envsum", "ringv", "h_root", "h_sys", "in_found", "in_result", "sc_out", "wvalid"}


def section(view):
    a = html.index(f'<section class="view" id="v_{view}"')
    b = html.index("</section>", a)
    return html[a:b]


def words(markup):
    return len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).split())


def explanation_words(view):
    sec = section(view)
    n = 0
    for m in re.finditer(r"<(p|div)\b([^>]*)>(.*?)</\1>", sec, re.S):
        tag, attrs, inner = m.groups()
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1].split()
        ident = (re.search(r'\bid="([^"]*)"', attrs) or [None, ""])[1]
        descriptive = tag == "p" or "note" in cls or "help" in cls
        if not descriptive or ident in ALLOW_IDS or "bad" in cls or "warn" in cls or "<div" in inner or "<p" in inner:
            continue
        if re.search(r"<(button|input|select|table|textarea)\b", inner):
            continue
        n += words(inner)
    return n


for v in VIEWS:
    n = explanation_words(v)
    check(f"{v}: {n} words of visible explanation (budget {BUDGET})", n <= BUDGET, f"{n} words")

# The same rule for text the page's script writes (cards drawn from data): long descriptive paragraphs are counted over the whole file. The ceiling is what is left after the
# cleanup (the guide dialog, consent facts, states, per-item facts); a new long note has to be a tooltip instead, or this number is raised on purpose, in review.
LONG_WORDS, LONG_CEILING = 22, 18   # 18 left: the Add-your-own-tool guide dialog, consent and install dialogs, per-setting states, study Manage
longs = []
for m in re.finditer(r'<(p class="(?:mut|small mut|mut small)[^"]*"|div class="note info[^"]*"|div class="help")[^>]*>(.*?)</(?:p|div)>', html, re.S):
    n = len(re.sub(r"<[^>]+>", " ", m.group(2)).split())
    if n >= LONG_WORDS:
        longs.append(n)
check(f"long descriptive notes in the whole page: {len(longs)} (ceiling {LONG_CEILING})", len(longs) <= LONG_CEILING, longs)

# ---- 2. help ids exist -----------------------------------------------------------------------------------------------------------------------------
page_ids = set(re.findall(r'data-tipid="([\w]+)"', html)) | set(re.findall(r'pageTip\("([\w]+)"\)', html))
wiz_ids = set(re.findall(r'wizTip\("([\w]+)"\)', html))
check("every page help id used by ui.html is in ui_help.PAGE", page_ids <= set(ui_help.PAGE), sorted(page_ids - set(ui_help.PAGE)))
check("every wizard help id used by ui.html is in ui_help.WIZARD", wiz_ids <= set(ui_help.WIZARD), sorted(wiz_ids - set(ui_help.WIZARD)))
check("every ui_help.PAGE entry is used by the page", set(ui_help.PAGE) <= page_ids, sorted(set(ui_help.PAGE) - page_ids))
check("every PAGE entry has a title and a summary", all(e.get("title") and e.get("summary") for e in ui_help.PAGE.values()))
sch = ui_schema.schema()
check("the schema sends the page tooltips (page_help)", set(sch["page_help"]) == set(ui_help.PAGE) and all(t["plain"] for t in sch["page_help"].values()))

# ---- 3. controls preserved ---------------------------------------------------------------------------------------------------------------------------
MERGED = {}   # control token -> what replaced it (none yet: the top bar's Help, Reload and theme buttons kept their ids and moved into the More menu)


def controls(markup):
    out = set()
    for m in re.finditer(r"<(button|input|select|textarea|a)\b([^>]*)>", markup):
        attrs = m.group(2)
        for k in ("id", "data-run", "data-op", "data-go", "data-act", "data-dk", "data-view", "data-browse", "data-cmd", "data-tpl", "data-uthelp", "data-pghelp"):
            for v in re.findall(r'(?<![\w-])%s="([^"$]+)"' % k, attrs):
                out.add(f"{m.group(1)}:{k}={v}")
    return out


before = set(json.load(open(os.path.join(ROOT, "test", "fixtures", "ui_controls_before.json"), encoding="utf-8")))
now = controls(html)
lost = sorted(c for c in before - now if c not in MERGED)
check(f"all {len(before)} controls of the window before the cleanup are still there", not lost, lost[:12])

# ---- 4. the tooltip component -----------------------------------------------------------------------------------------------------------------------
check("the tooltip box is role=tooltip and every (?) names it with aria-describedby", 'id="tipbox" role="tooltip"' in html and 'aria-describedby="tipbox"' in html)
check("it opens on hover and keyboard focus, and closes on Escape", all(x in html for x in ('"mouseover"', '"focusin"', 'e.key === "Escape" && cur')))
check("it opens (pins) on click or tap", 'if (cur === b && pinned) hide(); else show(b, true)' in html)
check("it is kept on screen (clamped to the window edges)", "innerWidth - w - 12" in html and "innerHeight - 8" in html)
check("the hit area of a (?) grows on touch screens (pointer: coarse)", "@media (pointer:coarse){.tipi::after" in html)

# ---- 5. the installing toast's controls are deliberate additions (not in the before-fixture; the toast text is drawn by script, so it adds no static explanation) ----------------
check("the installing toast region and its top-bar chip are in the page", 'id="insttoast"' in html and 'id="instchip"' in html and 'data-tipid="install_chip"' in html)
check("the toast's actions are all there: View log, Cancel, Hide, Re-check, Dismiss, Show list, Open Jobs", all(f'data-it="{k}"' in html for k in ("view", "cancel", "hide", "recheck", "dismiss", "expand", "jobs")))

# ---- 6. Report an issue: deliberate additions (More menu item, Guides page button; not in the before-fixture) ------------------------------------------------------------
check("Report an issue is in the More menu and on the Guides page, with a tooltip id", 'id="reportbtn"' in html and 'id="reportbtn2"' in html and 'data-tipid="report_issue"' in html)

# ---- 7. the page tabs (#mtabs) stay fixed under the application bar while the page scrolls ---------------------------------------------------------------------
mt = re.search(r"^\.mtabs\{([^}]*)\}", html, re.M)
check("the page tab strip is sticky under the top bar, above the content, with its own background (it does not scroll away)",
      bool(mt) and "position:sticky" in mt.group(1) and "top:var(--hdr)" in mt.group(1) and "background:var(--bg)" in mt.group(1) and re.search(r"z-index:\d+", mt.group(1)) is not None, mt.group(1) if mt else "no .mtabs rule")
check("other sticky panels start below the tab strip (--mtabh), so the strip never covers them", "--mtabh" in html and "var(--hdr) + var(--mtabh)" in html)
print("ALL UI CLEANUP TESTS PASSED" if OK else "UI CLEANUP TESTS FAILED")
sys.exit(0 if OK else 1)
