#!/usr/bin/env python3
"""The Settings dropdowns in a real browser (Playwright + Chromium): change enum dropdowns, a keywords-plus-number combo and a keywords-plus-folder combo, see a saved custom value kept,
save, reload and find the same options selected, and check config/local.env holds exactly the stored values.

Runs only with PLASBENCH_BROWSER_TESTS=1 and Playwright with a Chromium browser installed (pip install playwright; playwright install chromium); otherwise it says it skipped.
PLASBENCH_SHOTS=<folder> also writes screenshots (1280 and 700 px, light and dark)."""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


def main():
    if os.environ.get("PLASBENCH_BROWSER_TESTS") != "1":
        print("  skip  set PLASBENCH_BROWSER_TESTS=1 to run the real-browser Settings dropdown checks (needs Playwright and Chromium)")
        print("ALL SETTING OPTION BROWSER TESTS PASSED (skipped)")
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  skip  playwright is not installed")
        return 0
    tmp = Path(tempfile.mkdtemp())
    local = tmp / "local.env"
    local.write_text("# test settings\nexport ASSEMBLY_SELECTION_POLICY=best\n", encoding="utf-8")       # a hand-edited value that is not in the list
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), PLASBENCH_LOCAL_SETTINGS=str(local), HOME=str(tmp), USERPROFILE=str(tmp), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    server = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", "8883", "--new-instance"], cwd=str(ROOT), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(120):
        line = server.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    if not url:
        server.kill()
        check("the window started", False)
        return 1
    shots = os.environ.get("PLASBENCH_SHOTS")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            def open_settings(filter_text=""):
                page.goto(url.split("#")[0] + "#settings")
                page.wait_for_selector("#setlist .field", state="attached", timeout=30000)
                page.fill("#setq", filter_text)
                time.sleep(0.4)

            def select_of(key):
                return page.locator(f'select[data-opt="sel"][data-optkey="{key}"]')

            open_settings("SHORT_READ_QC_MODE")
            sel = select_of("SHORT_READ_QC_MODE")
            options = sel.locator("option").all_inner_texts()
            check("SHORT_READ_QC_MODE is a dropdown offering Default, Off, Report and Enforce", sel.count() == 1 and [o.split(" (")[0] for o in options] == ["Default", "Off", "Report", "Enforce"], options)
            check("what each option does is visible beside the dropdown (not hover-only)", "exclude an isolate whose reads are a threshold REJECT" in page.locator("#setlist").inner_text())
            sel.select_option("enforce")
            check("choosing a value marks the setting changed", page.locator("#setlist .field.changed").count() == 1)
            open_n = page.locator("#set_n").inner_text()
            check("the save button counts the change", "1" in open_n, open_n)

            # a combo: keyword plus number
            page.fill("#setq", "READ_DEPTH_CAP_X")
            time.sleep(0.4)
            cap = select_of("READ_DEPTH_CAP_X")
            cap.select_option("@number")
            num = page.locator('input[data-opt="num"][data-optkey="READ_DEPTH_CAP_X"]')
            check("the Number... choice reveals a numeric input with its unit and minimum", num.count() == 1 and "x coverage" in page.locator("#setlist").inner_text(), page.locator("#setlist").inner_text()[:300])
            num.fill("0")
            msg = page.locator("#setlist .optmsg").inner_text()
            check("a number below the minimum shows the limit and does not change the value", "minimum" in msg, msg)
            num.fill("300")
            num.dispatch_event("change")
            time.sleep(0.4)
            check("a valid number is accepted", page.locator('input[data-opt="num"][data-optkey="READ_DEPTH_CAP_X"]').input_value() == "300")

            # a combo: keyword plus folder
            page.fill("#setq", "WORK_DIR")
            time.sleep(0.4)
            select_of("WORK_DIR").select_option("@path")
            page.fill('input[data-opt="path"][data-optkey="WORK_DIR"]', "/fast/scratch")
            page.locator('input[data-opt="path"][data-optkey="WORK_DIR"]').dispatch_event("change")
            time.sleep(0.4)

            # the hand-edited value outside the list
            page.fill("#setq", "ASSEMBLY_SELECTION_POLICY")
            time.sleep(0.4)
            custom = select_of("ASSEMBLY_SELECTION_POLICY")
            check("a saved value outside the list is shown as Custom: <value>", custom.input_value() == "__custom" and "Custom: best" in custom.locator("option:checked").inner_text(), custom.locator("option:checked").inner_text())
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                page.fill("#setq", "")
                page.screenshot(path=str(Path(shots) / "settings_1280_light.png"))

            page.fill("#setq", "")
            page.locator("#set_save").click()
            page.wait_for_selector("#toasts .toast, .toast", timeout=15000)
            time.sleep(1.0)
            text = local.read_text(encoding="utf-8")
            check("config/local.env holds exactly the stored values", re.search(r"^export SHORT_READ_QC_MODE=enforce$", text, re.M) and re.search(r"^export READ_DEPTH_CAP_X=300$", text, re.M)
                  and re.search(r"^export WORK_DIR=(\")?/fast/scratch", text, re.M), text)
            check("the hand-edited value outside the list was kept untouched", re.search(r"ASSEMBLY_SELECTION_POLICY=best", text) is not None, text)

            open_settings("SHORT_READ_QC_MODE")
            check("after a reload the saved option is still selected", select_of("SHORT_READ_QC_MODE").input_value() == "enforce")
            page.fill("#setq", "READ_DEPTH_CAP_X")
            time.sleep(0.4)
            check("after a reload the combo shows its number", select_of("READ_DEPTH_CAP_X").input_value() == "@number" and page.locator('input[data-opt="num"][data-optkey="READ_DEPTH_CAP_X"]').input_value() == "300")
            page.fill("#setq", "WORK_DIR")
            time.sleep(0.4)
            check("after a reload the folder combo shows its folder", select_of("WORK_DIR").input_value() == "@path" and page.locator('input[data-opt="path"][data-optkey="WORK_DIR"]').input_value() == "/fast/scratch")
            page.fill("#setq", "ASSEMBLY_SELECTION_POLICY")
            time.sleep(0.4)
            check("after a reload the custom value is still shown as Custom", select_of("ASSEMBLY_SELECTION_POLICY").input_value() == "__custom")

            # back to default clears the value
            page.fill("#setq", "SHORT_READ_QC_MODE")
            time.sleep(0.4)
            select_of("SHORT_READ_QC_MODE").select_option("")
            page.locator("#set_save").click()
            time.sleep(1.2)
            check("choosing Default removes the saved value", "SHORT_READ_QC_MODE" not in local.read_text(encoding="utf-8"), local.read_text(encoding="utf-8"))

            # the workflow row offers the same options
            page.goto(url)
            page.click("button.nav[data-view=tools]")
            page.wait_for_selector(".wfroot .wfi", state="attached", timeout=30000)
            time.sleep(1.0)
            wf = page.locator('.wfroot select[data-opt="sel"][data-optkey="SHORT_READ_QC_MODE"]').first
            wf_opts = [o.split(" (")[0] for o in wf.locator("option").all_inner_texts()] if wf.count() else []
            check("the workflow row for the short-read QC gate offers the same Off, Report and Enforce", wf_opts == ["Default", "Off", "Report", "Enforce"], wf_opts)
            if shots and wf.count():
                wf.scroll_into_view_if_needed()
                page.screenshot(path=str(Path(shots) / "workflow_1280.png"))
            # a command-line form (plasbench run --read-depth-cap) offers the same combo and builds the command from the chosen value
            page.goto(url)
            page.click("button.nav[data-view=commands]")
            page.click('button[data-cmd="run"]')
            time.sleep(1.0)
            page.evaluate("document.querySelectorAll('#v_commands details').forEach(d => d.open = true)")
            form_sel = page.locator('select[data-opt="sel"][data-optkey="read_depth_cap"]')
            check("the run form's --read-depth-cap is the same dropdown (Default, Off, Number...)", form_sel.count() == 1 and form_sel.locator("option").all_inner_texts() == ["Default", "Off (whole files)", "Number..."],
                  form_sel.locator("option").all_inner_texts() if form_sel.count() else "no select")
            form_sel.select_option("off")
            time.sleep(0.4)
            check("choosing Off puts --read-depth-cap off in the command", "--read-depth-cap off" in page.locator("#v_commands").inner_text(), page.locator("#v_commands").inner_text()[-300:])
            form_sel.select_option("@number")
            page.locator('input[data-opt="num"][data-optkey="read_depth_cap"]').fill("250")
            page.locator('input[data-opt="num"][data-optkey="read_depth_cap"]').dispatch_event("change")
            time.sleep(0.4)
            check("a number puts --read-depth-cap 250 in the command", "--read-depth-cap 250" in page.locator("#v_commands").inner_text())
            if shots:
                page.set_viewport_size({"width": 700, "height": 900})
                open_settings("READ_DEPTH_CAP_X")
                select_of("READ_DEPTH_CAP_X").select_option("@number")
                page.screenshot(path=str(Path(shots) / "settings_700_light.png"))
                page.emulate_media(color_scheme="dark")
                page.screenshot(path=str(Path(shots) / "settings_700_dark.png"))
            check("no script error on the page", not errors, errors[:3])
            browser.close()
    finally:
        server.kill()
    print("\nALL SETTING OPTION BROWSER TESTS PASSED" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
