#!/usr/bin/env python3
"""Study folders, the workspace, and the window's Git page.

- plasbench run keeps each benchmark in <workspace>/<study>/ (results, logs, tmp, study.json), named after the cohort
  or sample sheet unless --study is given; report --study rebuilds one; --study with --results-dir is refused
- the workspace check refuses relative paths, system folders and files, tests writing, and warns about sync folders
- the window switches the workspace (saved in config/local.env), creates studies and lists them
- the Git page: a repository only inside the PlasBench folder or the workspace; initialise; identity; staging; the
  commit scan blocks config/local.env (it holds the NCBI API key); AI co-author trailers are removed; a remote address
  with credentials is refused
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ.pop("PLASBENCH_WORKSPACE", None)
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    (tmp / "home").mkdir()
    ws = tmp / "ws"
    (tmp / "local.env").write_text(f"export PLASBENCH_WORKSPACE={ws.as_posix()}\n", encoding="utf-8")
    from plasbench import cli, studies, workspace, gitops

    print("study names and records")
    check("a cohort names its study", studies.default_name("cohort1") == "cohort1")
    check("a sample sheet names its study", studies.default_name(None, "/x/my isolates.tsv") == "my-isolates")
    check("the metagenomic track prefixes meta-", studies.default_name("bmock12", meta=True) == "meta-bmock12")
    for bad in ("../up", "", "-x", "a" * 81, "with space"):
        try:
            studies.valid_name(bad)
            ok = False
        except ValueError:
            ok = True
        check(f"invalid study name refused: {bad[:12]!r}", ok)
    check("the workspace comes from config/local.env", studies.workspace(ROOT) == ws)

    def run_cli(*argv):
        """cli.main ends with SystemExit; return its code instead."""
        try:
            return cli.main(["--project-root", str(ROOT), *argv]) or 0
        except SystemExit as exc:
            return exc.code or 0

    print("plasbench run / report with study folders")
    script = tmp / "run.sh"
    code = run_cli("run", "--cohort", "public-v1", "--write-script", str(script))
    text = script.read_text(encoding="utf-8")
    folder = ws / "public-v1"
    check("run --cohort writes into <workspace>/<cohort>/", code == 0 and f"RESULTS_DIR={(folder / 'results').resolve().as_posix()}" in text
          and f"LOG_DIR={(folder / 'logs').resolve().as_posix()}" in text and f"TMP_DIR={(folder / 'tmp').resolve().as_posix()}" in text, text)
    record = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    check("study.json records the cohort, the sheet's checksum and the command", record["cohort"] == "public-v1"
          and len(record["sample_sheet_sha256"]) == 64 and "run --cohort public-v1" in record["runs"][-1]["command"], record)
    run_cli("run", "--cohort", "public-v1", "--study", "trial-2", "--write-script", str(script))
    check("--study names the folder", "trial-2/results" in script.read_text(encoding="utf-8"))
    both = run_cli("run", "--study", "x", "--results-dir", str(tmp / "r"), "--write-script", str(script)) == 2
    check("--study with --results-dir is refused", both)
    run_cli("report", "--study", "trial-2", "--write-script", str(script))
    check("report --study rebuilds that study", "trial-2/results" in script.read_text(encoding="utf-8"))
    run_cli("report", "--results-dir", str(tmp / "old"), "--write-script", str(script))
    check("report --results-dir still works (no study)", (tmp / "old").resolve().as_posix() in script.read_text(encoding="utf-8"))
    names = [s["name"] for s in studies.list_studies(ROOT)]
    check("studies are listed", {"public-v1", "trial-2"} <= set(names), names)

    print("workspace checks")
    check("a relative path is refused", workspace.check("relative/x")["errors"])
    sysdir = "C:\\Windows\\x" if os.name == "nt" else "/etc/plasbench"
    check("a system folder is refused", "operating-system" in " ".join(workspace.check(sysdir)["errors"]))
    (tmp / "afile").write_text("x", encoding="utf-8")
    check("a file is refused", "is a file" in " ".join(workspace.check(str(tmp / "afile"))["errors"]))
    rep = workspace.check(str(tmp / "OneDrive" / "studies"))
    check("a new folder is ok, will be created, and a sync folder is warned about",
          rep["ok"] and rep["will_create"] and any("cloud-sync" in w for w in rep["warnings"]), rep)

    print("the window: workspace and studies")
    from plasbench import webui
    webui.UI_HOME = tmp / "ui"
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        headers = {"Host": host, "X-PlasBench-Token": webui.TOKEN}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"http://{host}{path}", data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    code, info = call("/api/workspace")
    check("the workspace page reports the folder and its studies", code == 200 and info["path"] == str(ws)
          and {"public-v1", "trial-2"} <= {s["name"] for s in info["studies"]}, info)
    new_ws = tmp / "ws2"
    code, r = call("/api/workspace/set", {"path": str(new_ws)})
    check("a missing folder is created only after confirmation", code == 200 and r.get("needs_create") and not new_ws.exists(), r)
    code, r = call("/api/workspace/set", {"path": str(new_ws), "create": True})
    check("switching saves PLASBENCH_WORKSPACE for this computer", code == 200 and new_ws.is_dir()
          and str(new_ws) in (tmp / "local.env").read_text(encoding="utf-8"), r)
    code, r = call("/api/studies/create", {"name": "cohort1", "note": "first study"})
    check("New study creates its folders and record", code == 200 and (new_ws / "cohort1" / "study.json").is_file()
          and (new_ws / "cohort1" / "results").is_dir())
    check("a duplicate study is refused", call("/api/studies/create", {"name": "cohort1"})[0] == 400)
    code, info = call("/api/workspace")
    check("the new workspace lists its study", [s["name"] for s in info["studies"]] == ["cohort1"], info["studies"])

    print("the window: version control")
    if not gitops.find_git():
        print("  skip  git is not installed")
    else:
        repo = new_ws / "notes"
        repo.mkdir()
        code, r = call("/api/git", {"op": "init", "repo": str(repo)})
        check("a repository is initialised inside the workspace, with the safety block", code == 200
              and "PlasBench safety block" in (repo / ".gitignore").read_text(encoding="utf-8"), r)
        outside = tmp / "elsewhere"
        outside.mkdir()
        check("a folder outside the PlasBench folder and the workspace is refused",
              call(f"/api/git/status?repo={urllib.request.quote(str(outside))}")[0] == 400)
        check("identity is saved", call("/api/git", {"op": "identity", "repo": str(repo), "name": "Test User",
                                                      "email": "test@example.org"})[0] == 200)
        (repo / "notes.md").write_text("# study notes\n", encoding="utf-8")
        (repo / "config").mkdir()
        (repo / "config" / "local.env").write_text("export NCBI_API_KEY=0123456789abcdef0123456789abcdef01\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-f", "config/local.env"], capture_output=True)
        call("/api/git", {"op": "stage", "repo": str(repo), "paths": ["notes.md"]})
        code, r = call(f"/api/git/scan?repo={urllib.request.quote(str(repo))}")
        check("the commit scan blocks config/local.env (NCBI API key)",
              any(f["path"].endswith("local.env") and f["level"] == "block" for f in r["findings"]), r)
        code, r = call("/api/git", {"op": "commit", "repo": str(repo), "message": "notes"})
        check("the commit is refused while it is staged", code == 400 and "blocked" in r.get("error", ""), r)
        call("/api/git", {"op": "unstage", "repo": str(repo), "paths": ["config/local.env"]})
        code, r = call("/api/git", {"op": "commit", "repo": str(repo),
                                    "message": "Study notes\n\nCo-Authored-By: Claude <noreply@anthropic.com>"})
        log = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
        check("after unstaging, it commits, without the AI co-author trailer", code == 200 and r.get("committed")
              and "Co-Authored-By" not in log and log.strip() == "Study notes", (r, log))
        code, st = call(f"/api/git/status?repo={urllib.request.quote(str(repo))}")
        check("status shows the branch and the last commit", st.get("branch") == "main" and st["last"]["subject"] == "Study notes", st)
        check("a remote address with credentials is refused",
              call("/api/git", {"op": "remote_set", "repo": str(repo), "url": "https://user:token@github.com/a/b.git"})[0] == 400)
        check("a push needs confirmation", call("/api/git", {"op": "push", "repo": str(repo)})[0] == 400)

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print("WORKSPACE AND STUDY TESTS FAILED")
        return 1
    print("ALL WORKSPACE AND STUDY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
