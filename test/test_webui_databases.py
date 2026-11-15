#!/usr/bin/env python3
"""The window reports where each tool database already is, so a run reuses it.

Project.databases() must mirror config/config.sh's plasbench_db_path: an explicit
setting wins; otherwise the machine-wide store (PLASBENCH_DB_DIR); a copy under
DATA_DIR/db is used only while the store has none. A database counts as found only
when its folder exists and is not empty. The run form shows this, so an installed
database is visibly reused instead of looking like a field to fill in.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plasbench.webui import Project  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def filled(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "marker").write_text("x")


def main():
    keep = {k: os.environ.get(k) for k in ("PLASBENCH_DB_DIR", "DATA_DIR", "PLASBENCH_LOCAL_SETTINGS", "PLATON_DB", "GENOMAD_DB", "PLASME_DB", "PLASGRAPH2_MODEL_DIR")}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        store, data = tmp / "store", tmp / "data"
        os.environ.update(PLASBENCH_DB_DIR=str(store), DATA_DIR=str(data), PLASBENCH_LOCAL_SETTINGS=str(tmp / "none.env"))
        for k in ("PLATON_DB", "GENOMAD_DB", "PLASME_DB", "PLASGRAPH2_MODEL_DIR"):
            os.environ.pop(k, None)
        p = Project(ROOT)

        print("nothing installed")
        d = p.databases()
        check("Platon points at the store", d["platon_db"]["path"] == str(store / "platon" / "db"), d["platon_db"])
        check("and is not found", d["platon_db"]["found"] is False)
        check("an empty folder is not a database", (store / "genomad").mkdir(parents=True) or p.databases()["genomad_db"]["found"] is False)
        check("plASgraph2 has no default location", d["plasgraph2_model_dir"]["source"] == "none")

        print("installed in the machine store")
        filled(store / "platon" / "db")
        d = p.databases()
        check("Platon found in the store", d["platon_db"]["found"] and d["platon_db"]["source"] == "store", d["platon_db"])

        print("an older copy under DATA_DIR/db, store empty for that tool")
        filled(data / "db" / "plasme")
        d = p.databases()
        check("PLASMe found in the project data folder", d["plasme_db"]["found"] and d["plasme_db"]["source"] == "project"
              and d["plasme_db"]["path"] == str(data / "db" / "plasme"), d["plasme_db"])
        filled(store / "plasme")
        check("once the store has it, the store wins", p.databases()["plasme_db"]["source"] == "store")

        print("an explicit setting wins")
        filled(tmp / "elsewhere" / "genomad")
        os.environ["GENOMAD_DB"] = str(tmp / "elsewhere" / "genomad")
        d = p.databases()
        check("geNomad uses the setting", d["genomad_db"]["source"] == "setting" and d["genomad_db"]["found"], d["genomad_db"])

        print("the window's info carries it")
        check("info() includes databases", "databases" in p.info() and "platon_db" in p.info()["databases"])

        print("Settings shows what shell-code defaults mean on this computer")
        os.environ.pop("GENOMAD_DB", None)
        rows = {r["key"]: r for r in p.settings_resolved()}
        check("PLATON_DB resolves to the store and is installed",
              rows["PLATON_DB"].get("resolved") == str(store / "platon" / "db") and rows["PLATON_DB"].get("found") is True, rows["PLATON_DB"])
        check("PLASMER_DB resolves and is not installed",
              rows["PLASMER_DB"].get("resolved") == str(store / "plasmer") and rows["PLASMER_DB"].get("found") is False, rows["PLASMER_DB"])
        check("a database file (reference sketch) resolves too",
              rows["PLASMID_REFERENCE_SKETCH"].get("resolved") == str(store / "plasmid_reference" / "reference.msh"))
        check("DATA_DIR shows the real data folder, not shell code", rows["DATA_DIR"].get("resolved") == str(data))
        check("LOG_DIR shows a path under the install", rows["LOG_DIR"].get("resolved") == str(ROOT / "logs"))
        check("a plain setting gets nothing extra", "resolved" not in rows.get("THREADS", {}) or not rows["THREADS"].get("resolved"))

    for k, v in keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    ui = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    print("the run form uses it")
    check("database fields show their status", "function dbStatusHTML" in ui and "${dbStatusHTML(a.dest)}" in ui)
    check("the wizard refreshes it on open", 'S.info = await api("info")' in ui.split("async function loadWizard", 1)[1][:400])
    check("the settings route sends resolved locations", "project.settings_resolved()" in (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8"))
    check("Settings shows installed / not installed and the path", "r.resolved ?" in ui and "Not installed yet</span> at" in ui)
    check("data, results and log folders say what empty means",
          "leave empty: the shared data folder" in ui and "leave empty: the run's own study folder" in ui and "leave empty: the logs folder" in ui)
    check("database paths are an optional fold, closed unless one is filled in",
          "Use a different database copy (optional)" in ui and 'dbArgs.some(a => V[a.dest]) ? "open" : ""' in ui
          and "groupedFields(io, V, \"w\", true)}${dbBlock}" in ui)

    print("ALL WEBUI DATABASE TESTS PASSED" if not FAILED else f"WEBUI DATABASE TESTS FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
