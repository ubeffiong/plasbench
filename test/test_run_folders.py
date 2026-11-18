#!/usr/bin/env python3
"""Delete run folder (plasbench/runfolders.py, POST /api/runs/delete) versus Remove from list (POST /api/runs/forget), and the Workspace folder tree API.

Deleting is allowed ONLY for a study's results / results_* folder, or a folder in the saved Runs list that holds PlasBench results; refused (403) for the PlasBench folder,
the workspace, a study folder, the home folder, a filesystem root, a parent of those, a symlink, a folder that does not look like results; refused (409) while a run that
is going uses it; a wrong typed name is a 400. The happy path really removes the tree, drops it from the saved list and logs run_deleted. Remove from list keeps the files.
The tree API (fs/list, fs/properties) is token-protected, confined to the workspace, never follows symlinks, and caps its work.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
from plasbench import runfolders, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def refused(fn, status=None):
    try:
        fn()
    except runfolders.RunFolderError as exc:
        return exc.status == status if status else True
    return False


def make_study(ws, name):
    study = ws / name
    (study / "results").mkdir(parents=True)
    (study / "study.json").write_text(json.dumps({"name": name, "runs": [{"command": "plasbench run"}], "note": "n", "tags": ["a"]}), encoding="utf-8")
    (study / "results" / "benchmark.leaderboard.tsv").write_text("tool\tf1\n", encoding="utf-8")
    (study / "results" / "tool_status.tsv").write_text("sample\ttool\tstatus\ns1\tmob\tok\ns2\tmob\tfailed\n", encoding="utf-8")
    (study / "results" / "benchmark.report.html").write_text("<html></html>", encoding="utf-8")
    return study


def main():
    ws, home, proj = tmp / "ws", tmp / "home", tmp / "proj"
    for d in (ws, home, proj):
        d.mkdir()
    study = make_study(ws, "s1")
    res = study / "results"
    loose = tmp / "elsewhere" / "myrun"
    loose.mkdir(parents=True)
    (loose / "scores.tsv").write_text("x\n", encoding="utf-8")
    plain = tmp / "elsewhere" / "notes"
    plain.mkdir()
    (plain / "a.txt").write_text("x", encoding="utf-8")

    print("check_deletable")
    chk = lambda p, reg=(), run=(): runfolders.check_deletable(proj, ws, home, p, reg, run)   # noqa: E731
    check("a study's results folder is allowed", chk(res) == Path(os.path.realpath(res)))
    (study / "results_v2").mkdir()
    check("results_* too", chk(study / "results_v2").name == "results_v2")
    check("a registered folder that looks like results is allowed", chk(loose, [str(loose)]).name == "myrun")
    check("the same folder is refused when it is not registered", refused(lambda: chk(loose), 403))
    check("a registered folder that does not look like results is refused", refused(lambda: chk(plain, [str(plain)]), 403))
    check("the PlasBench folder, the workspace, home, a study folder and a root are refused",
          all(refused(lambda p=p: chk(p, [str(p)]), 403) for p in (proj, ws, home, study, Path(os.path.abspath(os.sep)))))
    check("a parent of the workspace is refused", refused(lambda: chk(tmp, [str(tmp)]), 403))
    check("a study root not named results* is refused", refused(lambda: chk(study), 403))
    check("a missing folder is a 404", refused(lambda: chk(tmp / "nope"), 404))
    check("a running job on the folder is a 409 that says to cancel", refused(lambda: chk(res, run=[str(res)]), 409))
    check("a running job on a folder inside it is a 409 too", refused(lambda: chk(res, run=[str(res / "x")]), 409))
    try:
        link = tmp / "link"
        link.symlink_to(res, target_is_directory=True)
        outside_link = ws / "evil"
        outside_link.symlink_to(plain, target_is_directory=True)
        check("a symlink is refused", refused(lambda: chk(link, [str(link)]), 403))
        check("a symlink in the workspace that points outside is refused", refused(lambda: chk(outside_link / ".", [str(outside_link)]), 403))
    except (OSError, NotImplementedError):
        print("  skip  symlinks cannot be created here")

    print("delete")
    check("a wrong typed name is refused (400) and nothing is removed", refused(lambda: runfolders.delete(proj, ws, home, str(res), "nope", []), 400) and res.is_dir())
    out = runfolders.delete(proj, ws, home, str(res), "results", [])
    check("the happy path removes the tree and reports files and bytes", not res.exists() and out["files"] == 3 and out["bytes"] > 0 and out["removed"], out)
    check("the study folder itself is untouched", (study / "study.json").is_file())
    ro = ws / "s2" / "results"
    ro.mkdir(parents=True)
    (ws / "s2" / "study.json").write_text("{}", encoding="utf-8")
    (ro / "scores.tsv").write_text("x", encoding="utf-8")
    os.chmod(ro / "scores.tsv", 0o444)
    runfolders.delete(proj, ws, home, str(ro), "results", [])
    check("a read-only file does not stop the delete", not ro.exists())

    print("over HTTP")
    study = make_study(ws, "s3")
    res3 = study / "results"
    project = webui.Project(proj)
    webui.save_state({"runs": [str(loose), str(res3)]})
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(path, body=None, token=True):
        h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode("utf-8", "replace")}
    q = urllib.parse.quote
    code, body = call("/api/runs/delete", {"path": str(proj), "confirm": "proj"})
    check("the program folder: 403 with an error and a status", code == 403 and body["status"] == 403 and "error" in body, (code, body))
    code, body = call("/api/runs/delete", {"path": str(ws), "confirm": "ws"})
    check("the workspace: 403", code == 403, (code, body))
    jobs.jobs["j"] = {"id": "j", "state": "running", "results": str(res3), "label": "x", "argv": [], "command": "", "env": {}, "kind": "plasbench", "started": time.time()}
    code, body = call("/api/runs/delete", {"path": str(res3), "confirm": "results"})
    check("a running job on it: 409 'Cancel the run first'", code == 409 and "Cancel the run first" in body["error"] and res3.is_dir(), (code, body))
    jobs.jobs["j"]["state"] = "done"
    code, body = call(f"/api/runs/facts?path={q(str(res3))}")
    check("runs/facts says what goes", code == 200 and body["files"] == 3 and body["report"] and body["leaderboard"] and body["tool_status"]["by_status"] == {"ok": 1, "failed": 1}, (code, body))
    code, body = call("/api/runs/forget", {"path": str(loose)})
    check("Remove from list keeps the files", code == 200 and loose.is_dir() and str(loose) not in webui.load_state()["runs"])
    code, body = call("/api/runs/delete", {"path": str(res3), "confirm": "results"})
    check("delete answers 200 with files and bytes freed", code == 200 and body["freed_files"] == 3 and body["freed_bytes"] > 0 and not res3.exists(), (code, body))
    check("the saved Runs list no longer holds it", str(res3) not in webui.load_state()["runs"])
    events = [json.loads(l) for f in (tmp / "ui").rglob("*.jsonl") for l in f.read_text(encoding="utf-8").splitlines() if "run_deleted" in l]
    check("a run_deleted event was logged", bool(events), events)

    print("tree API")
    make_study(ws, "s4")
    (ws / "s4" / "big").mkdir()
    code, body = call("/api/fs/list?path=")
    names = [e["name"] for e in body["entries"]]
    check("fs/list: the workspace root lists its studies, with study facts", code == 200 and body["is_root"] and {"s1", "s4"} <= set(names) and any(e.get("study", {}).get("tags") == ["a"] for e in body["entries"] if e["name"] == "s4"), (code, body))
    code, body = call(f"/api/fs/list?path={q(str(ws / 's4'))}")
    check("fs/list: a study lists dirs first with kinds, sizes and child counts", code == 200 and body["entries"][0]["kind"] == "dir" and any(e["name"] == "study.json" and e["kind"] == "file" and e["size"] for e in body["entries"]) and body["parent"], body)
    check("fs/list: outside the workspace is refused (403)", call(f"/api/fs/list?path={q(str(proj))}")[0] == 403 and call(f"/api/fs/list?path={q(str(tmp))}")[0] == 403)
    check("fs/list: .. cannot climb out", call("/api/fs/list?path=" + q("../.."))[0] == 403)
    check("fs/list: a missing folder is 404", call("/api/fs/list?path=" + q("nope"))[0] == 404)
    check("fs/list and fs/properties need the session token", call("/api/fs/list?path=", token=False)[0] == 403 and call("/api/fs/properties?path=", token=False)[0] == 403)
    code, body = call(f"/api/fs/properties?path={q(str(ws / 's4'))}")
    check("fs/properties: study notes, tags, runs and counts", code == 200 and body["study"]["note"] == "n" and body["study"]["runs"] == 1 and body["files"] >= 4 and body["bytes"] > 0 and body["relative"] == "s4", (code, body))
    code, body = call(f"/api/fs/properties?path={q(str(ws / 's4' / 'results'))}")
    check("fs/properties: a results folder says what it holds", body["results"]["report"] and body["results"]["leaderboard"] and body["results"]["tool_status"]["rows"] == 2, body)
    big = ws / "bigdir"
    big.mkdir()
    for i in range(30):
        (big / f"f{i}").write_text("x")
    old_cap, runfolders.WALK_ENTRIES = runfolders.WALK_ENTRIES, 10
    try:
        code, body = call(f"/api/fs/properties?path={q(str(big))}")
        check("the properties walk honours its cap and says so", code == 200 and body["capped"] and body["files"] <= 11, body)
    finally:
        runfolders.WALK_ENTRIES = old_cap
    old_list, runfolders.LIST_CAP = runfolders.LIST_CAP, 5
    try:
        code, body = call(f"/api/fs/list?path={q(str(big))}")
        check("the listing honours its cap and says so", body["truncated"] and len(body["entries"]) == 5, body)
    finally:
        runfolders.LIST_CAP = old_list
    try:
        outside = tmp / "outside_dir"
        outside.mkdir()
        (outside / "secret.txt").write_text("s")
        (ws / "portal").symlink_to(outside, target_is_directory=True)
        code, body = call("/api/fs/list?path=")
        check("a symlink is listed as a link, not followed", any(e["name"] == "portal" and e["kind"] == "link" for e in body["entries"]), body)
        check("a path through a symlink is refused", call(f"/api/fs/list?path={q(str(ws / 'portal'))}")[0] == 403 and call(f"/api/fs/properties?path={q(str(ws / 'portal' / 'secret.txt'))}")[0] == 403)
    except (OSError, NotImplementedError):
        print("  skip  symlinks cannot be created here")
    server.shutdown()
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
