#!/usr/bin/env python3
"""Where downloaded data goes, and where a study lives (plasbench/studies.py, plasbench/cli.py, study_manage.py).

  - run --keep-data-in-study sets DATA_DIR to <study>/data for the stage scripts, creates it and records data_location / data_dir in study.json; combined with --data-dir it is an error;
    a later run of the same study with neither flag reuses the record and says so; an explicit flag overrides and updates it; --data-dir records "custom";
  - the managed ignore block really ignores <study>/data/<sample>/SRR1_1.fastq.gz (real `git check-ignore -v`; skipped with a reason when git is missing), also in a study OUTSIDE the
    workspace, which gets its own .gitignore;
  - --study-location PARENT creates PARENT/NAME, registers it (hidden registry in the workspace, itself ignored), study_path finds it by name, names stay unique, list_studies lists it,
    a missing folder is listed as "not available" (never an exception) and every management action explains why; Add an existing study folder registers one;
  - Delete downloaded data only removes <study>/data and keeps results.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["REQUIRE_CURATED_METADATA"] = "0"
for k in ("DATA_DIR", "PLASBENCH_DATA_DIR", "RESULTS_DIR"):
    os.environ.pop(k, None)
from plasbench import gitops, study_manage, studies  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def cli(*args):
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), *args], capture_output=True, text=True, cwd=str(ROOT))
    return done.returncode, done.stdout + done.stderr


def record(name):
    return json.loads((studies.study_path(ROOT, name) / "study.json").read_text(encoding="utf-8"))


def main():
    sheet = tmp / "s.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\nA\tGCF_1.1\tSRR1\n", encoding="utf-8")
    script = tmp / "r.sh"
    print("--keep-data-in-study")
    code, out = cli("run", "-s", str(sheet), "--study", "t1", "--keep-data-in-study", "--write-script", str(script))
    folder = tmp / "ws" / "t1"
    exported = script.read_text(encoding="utf-8") if script.is_file() else ""
    check("exits 0 and says where the data stays", code == 0 and "inside the study" in out, out[-300:])
    check("DATA_DIR in the script is <study>/data", f"export DATA_DIR={folder.resolve().as_posix()}/data" in exported, exported[:400])
    check("<study>/data exists", (folder / "data").is_dir())
    rec = record("t1")
    check("study.json records data_location study and data_dir", rec["data_location"] == "study" and Path(rec["data_dir"]) == folder / "data", rec)
    code, out = cli("run", "-s", str(sheet), "--study", "t1", "--write-script", str(script))
    check("a later run with neither flag reuses it and says so in one line", code == 0 and "recorded for this study" in out and f"{folder.resolve().as_posix()}/data" in script.read_text(encoding="utf-8"), out[-300:])
    other = tmp / "elsewhere"
    code, out = cli("run", "-s", str(sheet), "--study", "t1", "--data-dir", str(other), "--write-script", str(script))
    check("an explicit --data-dir overrides and updates the record (custom)", code == 0 and record("t1")["data_location"] == "custom" and Path(record("t1")["data_dir"]) == other, out[-300:])
    code, out = cli("run", "-s", str(sheet), "--study", "t1", "--keep-data-in-study", "--data-dir", str(other))
    check("--keep-data-in-study with --data-dir is an error", code != 0 and "--keep-data-in-study or --data-dir, not both" in out, out[-200:])
    code, out = cli("run", "-s", str(sheet), "--keep-data-in-study", "-o", str(tmp / "res"))
    check("--keep-data-in-study without a study folder is an error", code != 0 and "needs a study folder" in out, out[-200:])
    code, out = cli("run", "-s", str(sheet), "--study", "t0", "--write-script", str(script))
    check("default: no flag records the shared folder and sets no DATA_DIR", code == 0 and record("t0")["data_location"] == "shared" and "export DATA_DIR" not in script.read_text(encoding="utf-8"), out[-200:])

    print("--study-location")
    ext = tmp / "drive"
    ext.mkdir()
    code, out = cli("run", "-s", str(sheet), "--study", "x1", "--study-location", str(ext), "--keep-data-in-study", "--write-script", str(script))
    check("the study is created as PARENT/NAME", code == 0 and (ext / "x1" / "study.json").is_file() and not (tmp / "ws" / "x1").exists(), out[-300:])
    check("it is registered in the workspace's hidden registry", studies.registry(ROOT).get("x1") == str((ext / "x1").resolve()), studies.registry(ROOT))
    check("study_path finds it by name; --study alone finds it again", studies.study_path(ROOT, "x1") == Path(studies.registry(ROOT)["x1"]) and cli("report", "--study", "x1", "--write-script", str(script))[0] == 0)
    check("its own .gitignore was written", "PlasBench runs block" in (ext / "x1" / ".gitignore").read_text(encoding="utf-8"))
    check("the registry file is in the managed ignore block", ".external_studies.json" in gitops.RUNS_IGNORE and ".external_studies.json" in gitops.SAFE_IGNORE)
    rows = {s["name"]: s for s in studies.list_studies(ROOT)}
    check("list_studies lists it with external, available and its data facts", rows["x1"]["external"] and rows["x1"]["available"] and rows["x1"]["data_in_study"], rows.get("x1"))
    check("the workspace repository does not claim it", rows["x1"]["tracked_in"] in (None, "own"))
    check("a name clash with a workspace study is a clear error", cli("run", "-s", str(sheet), "--study", "t1", "--study-location", str(ext), "--write-script", str(script))[0] != 0)
    other_drive = tmp / "drive2"
    other_drive.mkdir()
    try:
        studies.study_path(ROOT, "x1", other_drive)
        clash = False
    except ValueError as exc:
        clash = "already exists" in str(exc)
    check("a name clash with another external location is a clear error", clash)
    try:
        studies.study_path(ROOT, "x2", tmp / "no_such_drive")
        missing = False
    except ValueError as exc:
        missing = "does not exist" in str(exc)
    check("a location that does not exist is refused, never created", missing and not (tmp / "no_such_drive").exists())

    print("management")
    check("facts/meta work by name on the external study", study_manage.facts(ROOT, "x1")["external"] and study_manage.update_meta(ROOT, "x1", note="n")["note"] == "n")
    try:
        study_manage.rename(ROOT, "x1", "y1")
        refused = False
    except ValueError as exc:
        refused = "outside the workspace" in str(exc)
    check("rename / copy / archive of an external study say why they are not offered", refused)
    (ext / "x1" / "data" / "A").mkdir(parents=True)
    (ext / "x1" / "data" / "A" / "SRR1_1.fastq.gz").write_bytes(b"x" * 100)
    (ext / "x1" / "results").mkdir(exist_ok=True)
    (ext / "x1" / "results" / "benchmark.report.html").write_text("<html>", encoding="utf-8")
    check("facts show the data inside the study", study_manage.facts(ROOT, "x1")["data_in_study"] and study_manage.facts(ROOT, "x1")["data_bytes"] == 100)
    try:
        study_manage.delete_data(ROOT, "x1", "nope")
        wrong = False
    except ValueError:
        wrong = True
    check("delete data needs the study's name", wrong and (ext / "x1" / "data" / "A").exists())
    out = study_manage.delete_data(ROOT, "x1", "x1")
    check("delete data only removes <study>/data and keeps the results", out["files"] == 1 and out["bytes"] == 100 and not (ext / "x1" / "data" / "A").exists() and (ext / "x1" / "results" / "benchmark.report.html").is_file() and (ext / "x1" / "data").is_dir(), out)
    try:
        study_manage.delete_data(ROOT, "t0", "t0")
        nothing = False
    except ValueError as exc:
        nothing = "nothing of its own" in str(exc)
    check("a study using the shared folder has no data of its own to delete", nothing)
    shutil.rmtree(ext / "x1")
    rows = {s["name"]: s for s in studies.list_studies(ROOT)}
    check("a missing folder (a disconnected drive) is listed as not available, never an exception", rows["x1"]["available"] is False and "not available" in rows["x1"]["unavailable"] and str(ext / "x1") in rows["x1"]["unavailable"], rows["x1"])
    ok = True
    for action in (lambda: study_manage.facts(ROOT, "x1"), lambda: study_manage.update_meta(ROOT, "x1", note="x"), lambda: study_manage.delete(ROOT, "x1", "x1")):
        try:
            action()
            ok = False
        except ValueError as exc:
            ok = ok and "not available" in str(exc) and "Remove from list" in str(exc)
    check("every management action explains why it is unavailable", ok)
    check("Remove from list forgets it", study_manage.remove_from_list(ROOT, "x1") and "x1" not in studies.registry(ROOT))
    made = tmp / "other" / "adopt"
    (made / "results").mkdir(parents=True)
    (made / "study.json").write_text(json.dumps({"name": "adopt", "runs": []}), encoding="utf-8")
    studies.add_existing(ROOT, made)
    check("Add an existing study folder registers it", studies.registry(ROOT).get("adopt") == str(made.resolve()))
    try:
        studies.add_existing(ROOT, tmp / "other")
        bad = False
    except ValueError:
        bad = True
    check("a folder without study.json is refused", bad)

    print("gitignore proof")
    git = shutil.which("git")
    if not git:
        print("  skip  git is not installed: cannot run git check-ignore")
    else:
        def ignored(repo, rel):
            return subprocess.run([git, "check-ignore", "-v", rel], cwd=str(repo), capture_output=True, text=True).returncode == 0
        repo = tmp / "repo"
        (repo / "mystudy" / "data" / "S1").mkdir(parents=True)
        subprocess.run([git, "init", "-q"], cwd=str(repo), check=True)
        gitops.ensure_gitignore(repo, "runs")
        check("git check-ignore -v: <study>/data/<sample>/SRR1_1.fastq.gz is ignored by the managed block", ignored(repo, "mystudy/data/S1/SRR1_1.fastq.gz"))
        check("so is the external-study registry", ignored(repo, ".external_studies.json"))
        own = ext / "x9"
        studies.prepare(ROOT, "x9", location=ext)
        (own / "data" / "S1").mkdir(parents=True)
        subprocess.run([git, "init", "-q"], cwd=str(own), check=True)
        check("an external study's own .gitignore ignores its data too", ignored(own, "data/S1/SRR1_1.fastq.gz") and ignored(own, "results/S1/x"))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
