#!/usr/bin/env python3
"""study_manage.py: rename, clone, archive and restore, delete safely, export and import a bundle, notes and tags, and nested-repository handling."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import gitops, studies, study_manage as sm  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except (ValueError, OSError) as exc:
        return str(exc)
    return None


with tempfile.TemporaryDirectory() as d:
    root = Path(d) / "project"
    (root / "config").mkdir(parents=True)
    ws = Path(d) / "ws"
    os.environ["PLASBENCH_WORKSPACE"] = str(ws)
    studies.create(root, "alpha", "first")
    a = ws / "alpha"
    (a / "results" / "S1").mkdir(parents=True)
    (a / "results" / "S1" / "pred.fasta").write_text(">x\nACGT\n")
    (a / "results" / "benchmark.leaderboard.tsv").write_text("tool\tf1\nA\t0.9\n")
    (a / "results" / "benchmark.report.html").write_text("<html></html>")
    (a / "logs" / "run.log").write_text("log\n")
    (a / "tmp" / "scratch").write_text("x")
    rec = json.loads((a / "study.json").read_text())
    rec.update(sample_sheet="/x/s.tsv", cohort="public-v4")
    (a / "study.json").write_text(json.dumps(rec))

    print("metadata")
    out = sm.update_meta(root, "alpha", note="  for the paper  ", tags=["Real data", "real data", " v4 ", "", "x" * 80])
    check("a note and tags are saved; duplicate and empty tags are dropped, long ones trimmed", out["note"] == "for the paper" and out["tags"][0] == "Real data"
          and out["tags"][1] == "v4" and len(out["tags"]) == 3 and len(out["tags"][2]) == sm.MAX_TAG_LEN, out)
    check("study.json carries a schema version", json.loads((a / "study.json").read_text())["schema_version"] == sm.SCHEMA_VERSION)
    listed = {s["name"]: s for s in studies.list_studies(root)}
    check("the list shows the tags and the note", listed["alpha"]["tags"][0] == "Real data" and listed["alpha"]["note"] == "for the paper")

    print("confinement")
    check("a path is not a study name", raises(sm.study_dir, root, "../ws") is not None and raises(sm.study_dir, root, "a/b") is not None)
    check("an unknown study is refused", "no study named" in (raises(sm.study_dir, root, "nope") or ""))

    print("clone")
    c = sm.clone(root, "alpha", "alpha-copy")
    crec = json.loads((c / "study.json").read_text())
    check("a clone keeps the sample sheet, cohort, note and tags, has no runs, and says where it came from",
          crec["sample_sheet"] == "/x/s.tsv" and crec["cohort"] == "public-v4" and crec["tags"][0] == "Real data" and crec["runs"] == [] and crec["cloned_from"] == "alpha")
    check("a clone has no results unless asked", not (c / "results" / "benchmark.leaderboard.tsv").exists())
    c2 = sm.clone(root, "alpha", "alpha-full", with_results=True)
    check("with results it copies them", (c2 / "results" / "benchmark.leaderboard.tsv").is_file() and (c2 / "results" / "S1" / "pred.fasta").is_file())
    check("a clone onto an existing name is refused", "already exists" in (raises(sm.clone, root, "alpha", "alpha-copy") or ""))

    print("rename")
    check("a run in progress blocks a rename", "run is using" in (raises(sm.rename, root, "alpha-copy", "x", busy=True) or ""))
    r = sm.rename(root, "alpha-copy", "beta")
    check("rename moves the folder and records the old name", r.name == "beta" and not (ws / "alpha-copy").exists()
          and json.loads((r / "study.json").read_text())["renamed_from"] == "alpha-copy" and json.loads((r / "study.json").read_text())["name"] == "beta")
    check("a rename onto an existing study is refused", "already exists" in (raises(sm.rename, root, "beta", "alpha") or ""))
    check("an invalid new name is refused", raises(sm.rename, root, "beta", "bad name!") is not None)

    print("delete")
    f = sm.facts(root, "alpha-full")
    check("the facts count files and bytes and say whether there is a report", f["files"] == 4 and f["bytes"] > 0 and f["report"] is True and f["runs"] == 0 and f["tracked"] is False, f)
    check("a delete needs the study's own name", "type the study" in (raises(sm.delete, root, "alpha-full", "") or "") and (ws / "alpha-full").exists())
    check("a wrong name does not delete", "type the study" in (raises(sm.delete, root, "alpha-full", "alpha") or "") and (ws / "alpha-full").exists())
    check("a run in progress blocks a delete", "run is using" in (raises(sm.delete, root, "alpha-full", "alpha-full", busy=True) or ""))
    removed = sm.delete(root, "alpha-full", "alpha-full")
    check("the right name deletes the study and reports what went", not (ws / "alpha-full").exists() and removed["files"] == 4, removed)
    # a read-only file (git objects on Windows) does not stop a delete
    ro = ws / "beta" / "results" / "ro.txt"
    ro.write_text("x")
    os.chmod(ro, 0o444)
    sm.delete(root, "beta", "beta")
    check("a read-only file does not stop a delete", not (ws / "beta").exists())

    print("archive and restore")
    arch = sm.archive(root, "alpha")
    check("archive moves the study under .archive and keeps everything", arch.parent.name == sm.ARCHIVE_DIR and (arch / "results" / "S1" / "pred.fasta").is_file() and not (ws / "alpha").exists())
    check("an archived study is not in the list", "alpha" not in {s["name"] for s in studies.list_studies(root)})
    listed = sm.list_archived(root)
    check("the archive is listed with its name and date", len(listed) == 1 and listed[0]["name"] == "alpha" and listed[0]["archived"], listed)
    studies.create(root, "alpha", "a new one with the old name")
    back = sm.restore(root, listed[0]["archive"])
    check("restore brings it back under a free name when the old one is taken", back.name == "alpha-2" and (back / "results" / "benchmark.leaderboard.tsv").is_file(), back)
    check("restoring a name that is not archived is refused", raises(sm.restore, root, "../alpha") is not None)

    print("bundles")
    out = sm.export_bundle(root, "alpha-2", Path(d) / "alpha-2.zip", include_results=False, version="0.4.1")
    with zipfile.ZipFile(out["path"]) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read(sm.BUNDLE_MANIFEST))
    check("a light bundle holds the record and study-level tables, not per-sample data or tmp",
          "study/study.json" in names and "study/results/benchmark.leaderboard.tsv" in names and "study/results/benchmark.report.html" in names
          and not any("S1/pred.fasta" in n or "/tmp/" in n for n in names), sorted(names))
    check("the manifest has a schema version, the file list and checksums", manifest["bundle_schema"] == sm.BUNDLE_SCHEMA and manifest["kind"] == "plasbench-study"
          and manifest["include_results"] is False and all(f["sha256"] and f["bytes"] >= 0 for f in manifest["files"]) and manifest["plasbench_version"] == "0.4.1")
    full = sm.export_bundle(root, "alpha-2", Path(d) / "alpha-2-full.zip", include_results=True)
    with zipfile.ZipFile(full["path"]) as z:
        check("a full bundle includes the per-sample results", "study/results/S1/pred.fasta" in z.namelist())
    imp = sm.import_bundle(root, out["path"], "imported-light")
    irec = json.loads((imp / "study.json").read_text())
    check("import creates a new study with its record, marks where it came from, and rebuilds the folders",
          imp.name == "imported-light" and irec["imported_from"] == "alpha-2" and (imp / "tmp").is_dir() and (imp / "results" / "benchmark.leaderboard.tsv").is_file(), irec)
    check("import never overwrites an existing study", "already exists" in (raises(sm.import_bundle, root, out["path"], "imported-light") or ""))
    check("a file that is not a bundle is refused", "not a study bundle" in (raises(sm.import_bundle, root, ROOT / "README.md") or ""))

    bad = Path(d) / "evil.zip"       # path traversal
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("study/../../escape.txt", "x")
        z.writestr(sm.BUNDLE_MANIFEST, json.dumps({"bundle_schema": 1, "kind": "plasbench-study", "study": "evil", "files": []}))
    msg = raises(sm.import_bundle, root, bad)
    check("a path-traversal bundle is refused and nothing is written outside the workspace", msg is not None and not (Path(d) / "escape.txt").exists() and not (ws / "evil").exists()
          and not any(p.name.startswith(".import-") for p in ws.iterdir()), msg)
    tampered = Path(d) / "tampered.zip"
    with zipfile.ZipFile(out["path"]) as zin, zipfile.ZipFile(tampered, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "study/results/benchmark.leaderboard.tsv":
                data = b"tool\tf1\nA\t0.1\n"
            zout.writestr(item.filename, data)
    msg = raises(sm.import_bundle, root, tampered, "tampered")
    check("a bundle whose file no longer matches its checksum is refused", "checksum" in (msg or "") and not (ws / "tampered").exists(), msg)
    newer = Path(d) / "newer.zip"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(sm.BUNDLE_MANIFEST, json.dumps({"bundle_schema": 99, "kind": "plasbench-study", "study": "n", "files": []}))
    check("a bundle from a newer PlasBench is refused", "newer PlasBench" in (raises(sm.import_bundle, root, newer) or ""))

    print("nested repositories")
    if gitops.find_git():
        own = ws / "own"
        studies.create(root, "own")
        subprocess.run(["git", "-C", str(own), "init", "-q"], capture_output=True)
        res = gitops.init(ws, "main", False, "x", kind="runs")
        exclude = (ws / ".git" / "info" / "exclude").read_text()
        check("a study that already has its own repository is left out of the working-directory one", res.get("left_out") == ["own"] and "/own/" in exclude, (res, exclude))
        res2 = gitops.exclude_nested_repos(ws)
        check("excluding twice does not repeat the entry", (ws / ".git" / "info" / "exclude").read_text().count("/own/") == 1 and res2 == ["own"])
    else:
        print("  skip  git is not installed")

print("ALL STUDY MANAGE TESTS PASSED" if ok else "STUDY MANAGE TESTS FAILED")
sys.exit(0 if ok else 1)
