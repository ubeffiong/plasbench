#!/usr/bin/env python3
"""Static checks of the window's data-location and study-location controls (plasbench/data/ui.html, ui_help.py). No browser is available to the suite.

Wizard, step "outputs and stages": the card "Where to keep downloaded reads and assemblies" with three radios (Shared folder, Inside this study folder, Another folder); the
review command carries --keep-data-in-study or --data-dir PATH and --study-location; the Study folder card has Location (Workspace / Another folder); the Workspace page has
Location on New study, Add an existing study folder, the data location in the studies table, Delete downloaded data only, and Remove from list for studies outside the workspace;
the schema carries tooltips for every new control.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    from plasbench import ui_schema
    sch = ui_schema.schema()
    run = {a["dest"]: a for a in next(c for c in sch["commands"] if c["name"] == "run")["args"]}
    check("run has --keep-data-in-study and --study-location with tooltips", all(run[d]["tooltip"]["summary"] and not run[d]["tooltip"]["summary"].endswith("recorded for it.") for d in ("keep_data_in_study", "study_location", "data_dir")))
    check("the data folder help says shared is reused by every study and kept when a study is deleted", "kept when a study is deleted" in run["data_dir"]["help"] and "deleted together with the study" in run["keep_data_in_study"]["help"])
    check("wizard tooltips: data_location lists all three choices, study_location both", [c for c, _ in sch["wizard_help"]["data_location"]["choices"]] == ["Shared folder", "Inside this study folder", "Another folder"] and len(sch["wizard_help"]["study_location"]["choices"]) == 2)
    check("the card and its three radios", all(k in HTML for k in ("Where to keep downloaded reads and assemblies", 'name="wdata"', '"Shared folder (default)"', '"Inside this study folder"', '"Another folder"')))
    check("shared: the real path, free space and the 'reused / kept' sentence", all(k in HTML for k in ('id="wd_shared"', "Reused by every study, so nothing is downloaded twice; kept if a study is deleted.")))
    check("inside the study: git-ignored, deleted with the study", "Git-ignored; deleted with the study." in HTML)
    check("another folder: a path box, Choose a folder, and the folder check under it", all(k in HTML for k in ('id="wd_path"', 'data-browse="wd_path"', 'id="wd_check"')))
    check("the review command gets --keep-data-in-study / --data-dir / --study-location", all(k in HTML for k in ('vals.keep_data_in_study = true', "vals.data_dir = D.path", "vals.study_location = SW.location")))
    check("the generic fields no longer duplicate them", '"data_dir","keep_data_in_study","study_location"' in HTML)
    check("the Study folder card has Location (Workspace shows its path / Another folder)", all(k in HTML for k in ('name="wloc"', 'id="wloc_path"', 'id="wloc_check"', "Workspace <span")))
    check("New study has Location; Add an existing study folder exists", all(k in HTML for k in ('id="st_loc"', 'id="st_addex"', "studies/add_existing")))
    check("the studies table shows where the data is and flags studies outside the workspace / not available", all(k in HTML for k in ("data: ${st.data_location", "outside the workspace", "st.unavailable")))
    check("Manage: Delete downloaded data only (typed confirmation), Remove from list for external studies", all(k in HTML for k in ("Delete downloaded data only…", 'act === "delete_data"', "typeToConfirm: name", 'act === "unregister"', "studies/unregister")))
    check("Properties show the data location and its size", "Downloaded data kept" in HTML and "Size of the study's own data" in HTML)
    check("the summary rows list data and study location", '["Downloaded data"' in HTML and '["Study location"' in HTML)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
