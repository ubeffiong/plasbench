#!/usr/bin/env python3
"""The pre-registered scoring decisions: confirmed, recorded, and changeable in a controlled way (python/prereg_admin.py, config/prereg_plain.tsv, config/prereg_decisions.tsv, the window's
Scoring decisions page).

The shipped state
  - every decision has a plain-language description, and the three files are consistent (`prereg_admin.py check`);
  - the project owner confirmed all 29 decisions that were proposed (none is proposed or TO_FIX), each with a dated record that names who and why;
  - every decision that is a setting has, as its program default in config/config.sh, the value that was decided (a decision that the program does not follow is not a decision:
    tool_timeout_seconds was 7200 on paper and 'no limit' in the program until this test existed).
Changing a decision
  - `set` changes one decision that is a setting: exactly one row of prereg.tsv, a new line in the record (old value, new value, who, why), this computer's setting, and optionally the
    default in config.sh; it refuses a decision that is built into the code or a scorecard table, a missing reason or name, a value of the wrong kind, and a no-op;
  - the lock goes stale when a decision changes and can be renewed with `lock`, which refuses while a decision is still proposed;
  - the window's data (Project.prereg) shows the value this computer uses and flags a setting that departs from the decision.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import prereg_admin as admin  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def fresh_root():
    """A copy of the pre-registration files and config.sh in a temp folder, so a test can change them."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "config").mkdir()
    for name in ("prereg.tsv", "prereg_plain.tsv", "prereg_decisions.tsv", "config.sh"):
        shutil.copy(ROOT / "config" / name, tmp / "config" / name)
    return tmp


def refuses(call, needle):
    try:
        call()
    except ValueError as exc:
        return needle.lower() in str(exc).lower()
    return False


def main():
    print("the shipped state")
    problems = admin.check(ROOT)
    check("the three files are consistent and every decision is described in plain words", not problems, problems[:3])
    rows = admin.load(ROOT)
    status = admin.status(ROOT)
    check("no decision is proposed or TO_FIX: the plan is not a draft", status["counts"]["proposed"] == 0 and status["counts"]["TO_FIX"] == 0 and not status["draft"], status["counts"])
    log = admin.history(ROOT)
    confirmed = {e["parameter"] for e in log if e["action"] == "confirmed"}
    expected = {"primary_endpoint", "primary_endpoint_reassembly", "tool_timeout_seconds", "headline_independence", "interval_method", "dominant_study_share", "headline_min_clusters",
                "amr_flank_bp", "scorecard_weights", "map_max_bp", "chromid_min_bp", "large_plasmid_bp"}
    check("the confirmation of the formerly proposed decisions is recorded (29 of them)", len(confirmed) == 29 and expected <= confirmed, (len(confirmed), expected - confirmed))
    check("each record names a date, who decided, and why", all(re.fullmatch(r"\d{4}-\d\d-\d\d", e["date"]) and e["decided_by"].strip() and len(e["reason"].strip()) >= 5 for e in log), log[:1])
    text = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    drift = []
    for r in rows:
        var = r["config_variable"]
        if not var:
            continue
        m = re.search(rf'export\s+{var}="\$\{{{var}:-([^}}]*)\}}"', text)
        if not m or not admin.freeze_prereg_equal(r["value"], m.group(1)):
            drift.append((r["parameter"], r["value"], m.group(1) if m else "no default"))
    check("every decision that is a setting has the decided value as the program's default", not drift, drift)
    state = admin.status(ROOT)
    check("the shipped lock matches the shipped decisions (a decision edited without locking again is caught here)", state["locked"] and state["matches"] and not state["draft"], state)
    check("the lock names its file with forward slashes (the same lock on every system)", json.loads((ROOT / "config" / "prereg.lock.json").read_text(encoding="utf-8"))["prereg_file"] == "config/prereg.tsv")
    kinds = {k: sum(1 for r in rows if r["where"] == k) for k in ("setting", "file", "built-in")}
    check("each decision says whether it can be changed (setting), is a scorecard table (file) or is in the code (built-in)", sum(kinds.values()) == len(rows) and kinds["setting"] >= 30 and kinds["file"] >= 10, kinds)
    doc = admin.markdown(ROOT)
    check("the Markdown table lists every decision", all(f"`{r['parameter']}`" in doc for r in rows))

    print("confirming")
    tmp = fresh_root()
    rewritten = (tmp / "config" / "prereg.tsv").read_text(encoding="utf-8").replace("\r\n", "\n").replace("dominant_study_share\t0.30\tPLASBENCH_DOMINANT_SHARE\t8\tno\tfixed", "dominant_study_share\t0.30\tPLASBENCH_DOMINANT_SHARE\t8\tno\tproposed")
    (tmp / "config" / "prereg.tsv").write_text(rewritten, encoding="utf-8", newline="\n")
    (tmp / "config" / "prereg_decisions.tsv").write_text("\t".join(admin.DECISION_FIELDS) + "\n", encoding="utf-8")
    check("a proposed decision is seen as proposed", admin.status(tmp)["counts"]["proposed"] == 1 and admin.status(tmp)["draft"])
    check("confirming needs a reason and a name", refuses(lambda: admin.confirm(tmp, ["dominant_study_share"], "", "me"), "why") and refuses(lambda: admin.confirm(tmp, ["dominant_study_share"], "fine by me", ""), "who"))
    check("an unknown decision is refused", refuses(lambda: admin.confirm(tmp, ["nonsense"], "fine by me", "me"), "no such decision"))
    entries = admin.confirm(tmp, ["dominant_study_share"], "Accepted for the test", "tester", today="2026-12-01")
    check("confirming sets status fixed, writes one dated record and leaves the value alone",
          len(entries) == 1 and admin.status(tmp)["counts"]["proposed"] == 0 and entries[0]["date"] == "2026-12-01" and [r for r in admin.load(tmp) if r["parameter"] == "dominant_study_share"][0]["value"] == "0.30")
    check("confirming an already confirmed decision does nothing", admin.confirm(tmp, ["dominant_study_share"], "again", "tester") == [])

    print("changing")
    tmp = fresh_root()
    env_file = tmp / "local.env"
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(env_file)
    before = (tmp / "config" / "prereg.tsv").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    entry = admin.set_value(tmp, "dominant_study_share", "0.4", "The cohort has two very large studies", "tester", today="2026-12-02")
    after = (tmp / "config" / "prereg.tsv").read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    check("exactly one row of prereg.tsv changes, and only its value", len(before) == len(after) and len(changed) == 1 and changed[0][0].startswith("dominant_study_share\t0.30\t") and changed[0][1].startswith("dominant_study_share\t0.4\t"), changed)
    check("the record gets the change with old value, new value, who, why and the date", entry["old_value"] == "0.30" and entry["new_value"] == "0.4" and entry["date"] == "2026-12-02"
          and admin.history(tmp, "dominant_study_share")[-1]["reason"] == "The cohort has two very large studies")
    check("this computer's setting is written so the program uses the new value", "PLASBENCH_DOMINANT_SHARE=0.4" in env_file.read_text(encoding="utf-8"))
    check("the default in config.sh is left alone unless asked", "PLASBENCH_DOMINANT_SHARE:-0.30" in (tmp / "config" / "config.sh").read_text(encoding="utf-8"))
    admin.set_value(tmp, "headline_min_clusters", "6", "More studies are available now", "tester", update_default=True)
    check("--update-default also changes the default in config.sh (so the change travels with the source)", "HEADLINE_MIN_CLUSTERS:-6" in (tmp / "config" / "config.sh").read_text(encoding="utf-8"))
    check("a decision built into the scoring code cannot be changed here, and the reason says why", refuses(lambda: admin.set_value(tmp, "primary_endpoint", "x", "testing it", "me"), "written into the scoring code"))
    check("a scorecard table cannot be changed here either (edit the file)", refuses(lambda: admin.set_value(tmp, "scorecard_weights", "x", "testing it", "me"), "config/scorecard.tsv"))
    check("a reason and a name are required", refuses(lambda: admin.set_value(tmp, "tool_retries", "2", "", "me"), "why") and refuses(lambda: admin.set_value(tmp, "tool_retries", "2", "needs more", " "), "who"))
    check("a value of the wrong kind is refused with a plain sentence", refuses(lambda: admin.set_value(tmp, "tool_retries", "two", "needs more", "me"), "whole number")
          and refuses(lambda: admin.set_value(tmp, "dominant_study_share", "lots", "needs more", "me"), "enter a number")
          and refuses(lambda: admin.set_value(tmp, "collapse_dimers", "maybe", "needs more", "me"), "1 for yes")
          and refuses(lambda: admin.set_value(tmp, "interval_method", "magic", "needs more", "me"), "choose from"))
    check("a list of choices is accepted where several are allowed, and refused when one is not on the list",
          admin.set_value(tmp, "headline_independence", "independent,partially_independent", "widen to the first check", "me")["new_value"] == "independent,partially_independent"
          and refuses(lambda: admin.set_value(tmp, "headline_independence", "independent,sometimes", "not a valid choice", "me"), "choose from"))
    check("changing a decision to the value it already has is refused", refuses(lambda: admin.set_value(tmp, "tool_retries", "1", "no change", "me"), "already"))
    check("an unknown decision is refused", refuses(lambda: admin.set_value(tmp, "nonsense", "1", "testing it", "me"), "no such decision"))

    print("the lock")
    tmp = fresh_root()
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    (tmp / "python").mkdir()
    check("with no lock, status says so", admin.status(tmp)["locked"] is False)
    shutil.copy(ROOT / "python" / "plasbench_common.py", tmp / "python" / "plasbench_common.py") if (ROOT / "python" / "plasbench_common.py").is_file() else None
    state = admin.lock(tmp)
    check("lock records the fingerprint and it matches", state["locked"] and state["matches"] and (tmp / "config" / "prereg.lock.json").is_file())
    admin.set_value(tmp, "tool_retries", "2", "More retries for a flaky network", "tester")
    check("a change makes the lock stale (it no longer matches)", admin.status(tmp)["locked"] and not admin.status(tmp)["matches"])
    check("locking again renews it", admin.lock(tmp)["matches"])
    (tmp / "config" / "prereg.tsv").write_text((tmp / "config" / "prereg.tsv").read_text(encoding="utf-8").replace("\tfixed\t", "\tproposed\t", 1), encoding="utf-8")
    check("the lock refuses while a decision is still proposed", refuses(lambda: admin.lock(tmp), "draft"))

    print("the command line and the window")
    done = subprocess.run([sys.executable, str(ROOT / "python" / "prereg_admin.py"), "check"], capture_output=True, text=True, cwd=str(ROOT))
    check("`prereg_admin.py check` passes on the shipped files", done.returncode == 0 and "consistent" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "analysis", "prereg", "show", "interval_method"], capture_output=True, text=True, cwd=str(ROOT))
    check("`plasbench analysis prereg show` works and shows the record", done.returncode == 0 and "Confirmed" not in done.stdout and "confirmed by" in done.stdout and "cluster_t" in done.stdout, done.stdout[-300:] + done.stderr[-300:])
    sys.path.insert(0, str(ROOT))
    from plasbench import webui
    tmp = fresh_root()
    env_file = tmp / "local.env"
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(env_file)
    (tmp / "python").mkdir(exist_ok=True)
    for f in (ROOT / "python").glob("*.py"):
        if f.name in ("prereg_admin.py", "freeze_prereg.py", "plasbench_common.py"):
            shutil.copy(f, tmp / "python" / f.name)
    project = webui.Project(tmp)
    data = project.prereg()
    row = {r["parameter"]: r for r in data["rows"]}
    check("the window's data lists every decision with its plain text, status and the value this computer uses", len(data["rows"]) == len(rows) and row["dominant_study_share"]["current"] in ("0.30", "0.3") and not row["dominant_study_share"]["departs"], row["dominant_study_share"])
    env_file.write_text("export PLASBENCH_DOMINANT_SHARE=0.55\n", encoding="utf-8")
    row = {r["parameter"]: r for r in project.prereg()["rows"]}
    check("a setting that differs from the decision is flagged (this computer would not follow the plan)", row["dominant_study_share"]["departs"] and row["dominant_study_share"]["current"] == "0.55")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the page: a Scoring decisions entry and page with status, search, topics, Change, Decision record and Lock",
          'data-view="prereg"' in html and 'id="v_prereg"' in html and "async function loadPrereg" in html and 'api("prereg/set"' in html and 'api("prereg/lock"' in html and "Decision record" in html and "Why are you changing it?" in html)
    check("changing warns that earlier and later results cannot be compared and that the decisions must be locked again",
          "cannot be compared with results made after it" in html and "Lock the decisions again" in html.replace("Lock the decisions again when ready", "Lock the decisions again"))
    check("a decision built into the code offers no Change button, and says why", "Built into the program: it cannot be changed here." in html and 'data-pe="' in html)
    guide = (ROOT / "docs" / "PREREGISTRATION.md").read_text(encoding="utf-8")
    table = guide.split("<!-- prereg-table:start -->")[1].split("<!-- prereg-table:end -->")[0].strip()
    check("docs/PREREGISTRATION.md holds the table generated from the data (run `prereg_admin.py doc` to refresh it)", table == admin.markdown(ROOT).strip())
    check("the guide says the decisions are confirmed, how to look, how to change them, and what a change means",
          "confirmed all 29 decisions" in guide and "plasbench analysis prereg set" in guide and "cannot be compared with results made after it" in guide and "Scoring decisions" in guide)
    print("ALL PREREG ADMIN TESTS PASSED" if not FAILED else f"PREREG ADMIN TESTS FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
