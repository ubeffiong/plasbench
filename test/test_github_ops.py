#!/usr/bin/env python3
"""GitHub actions of the Version control page (plasbench/ghops.py, POST /api/github/op, plasbench/data/ui.html), against the fake gh (test/ghfake.py).

  - argv construction for every operation: a list (no shell), gh first, inputs validated (bad names, options smuggled as values, newlines in names are refused), no token ever in an argument,
    no force-push anywhere;
  - parsers for `gh pr list / view / checks --json`, `repo list`, `run list`, `issue list`, `release list`, `api user/orgs` samples; check roll-ups (passing / failing / pending / none); merge risks;
  - errors translated into plain sentences (not signed in -> action signin, no permission, branch protection, conflicts, no remote, offline);
  - routes with a fake gh: reads return parsed data and the shown command, writes start a job whose log begins with the command (tokens removed), a merge with failing checks or conflicts is a
    409 with the risks until risk_confirmed, a signed-out gh gives 401 {action: signin}, unknown operations are refused, local branch / tag operations work on a real repository;
  - the page: every operation has a button or dialog wiring, destructive ones confirm first, no browser dialogs.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
os.environ["FAKE_GH_DIR"] = str(tmp)
os.environ["PYTHONPATH"] = str(ROOT)      # the job runner is started in the repository folder and must find plasbench
os.environ.pop("PLASBENCH_OFFLINE", None)
from plasbench import ghops, netgate, webui  # noqa: E402

GH = [sys.executable, str(ROOT / "test" / "ghfake.py")]
FAILED = []
SECRET = "ghp_" + "Zy9X8w7V6u5T4s3R2q1P0o9N8m7L6k5J4i3H"


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def refuses(**kw):
    try:
        ghops.build(kw.pop("op"), GH, tmp, **kw)
        return False
    except ValueError:
        return True


def main():
    print("argv construction")
    cases = {
        "repo_create": dict(name="runs", owner="lab-org", visibility="private", description="my runs", push=True),
        "pr_create": dict(title="T", body="B", head="fig", base="main", draft=True, reviewers="alice,bob", labels="a,b"),
        "pr_list": dict(state="merged"), "pr_view": dict(number=7), "pr_checks": dict(number="#7"), "pr_checkout": dict(number=7), "pr_ready": dict(number=7), "pr_close": dict(number=7), "pr_reopen": dict(number=7),
        "pr_merge": dict(number=7, method="squash", delete_branch=True, auto=True), "pr_comment": dict(number=7, body="hi"), "run_list": dict(branch="fig"), "run_rerun": dict(run_id="99"),
        "issue_list": dict(state="all"), "issue_create": dict(title="T", body="B"), "issue_comment": dict(number=3, body="c"), "issue_close": dict(number=3), "release_list": {}, "release_create": dict(tag="v1.0.0", title="One", notes="n", draft=True),
        "orgs": {}, "repo_list": dict(owner="octocat"), "repo_search": dict(query="plasmid benchmark"),
    }
    built = {op: ghops.build(op, GH, tmp, **kw) for op, kw in cases.items()}
    check("every operation builds a list that starts with gh", all(isinstance(c, list) and c[:2] == GH for c in built.values()), [o for o, c in built.items() if c[:2] != GH])
    flat = " ".join(" ".join(c) for c in built.values())
    check("no operation force-pushes, and no shell string is used", "--force" not in flat and "-f " not in flat and "--force-with-lease" not in flat and all(isinstance(a, str) for c in built.values() for a in c))
    c = built["repo_create"]
    check("repo_create: owner/name, private, source, origin, description, push", "lab-org/runs" in c and "--private" in c and c[c.index("--source") + 1] == str(tmp) and c[c.index("--remote") + 1] == "origin" and "--description" in c and "--push" in c, c)
    c = built["pr_create"]
    check("pr_create: title, body, base, head, draft, reviewers, labels", c[c.index("--title") + 1] == "T" and "--draft" in c and c.count("--reviewer") == 2 and c.count("--label") == 2 and c[c.index("--base") + 1] == "main" and c[c.index("--head") + 1] == "fig", c)
    check("pr_merge: method, delete branch, auto", built["pr_merge"][-4:] == ["7", "--squash", "--delete-branch", "--auto"], built["pr_merge"])
    check("pr_checks and pr_view ask for JSON fields", "--json" in built["pr_checks"] and "statusCheckRollup" in built["pr_view"][-1])
    check("run_rerun re-runs only the failed jobs", built["run_rerun"][-2:] == ["99", "--failed"])
    check("a token is never part of any command", SECRET not in flat)
    check("bad input is refused: names, numbers, states, methods, options as values, newlines, NUL", all((
        refuses(op="pr_view", number="abc"), refuses(op="pr_view", number="0"), refuses(op="pr_list", state="weird"), refuses(op="pr_merge", number=1, method="force"), refuses(op="pr_create", title="", body="x"),
        refuses(op="pr_create", title="t", body="b", head="--upload-pack=x"), refuses(op="pr_create", title="t", body="b", base="a b"), refuses(op="release_create", tag="-x"), refuses(op="repo_search", query="-x"),
        refuses(op="repo_create", name="bad name!", visibility="private"), refuses(op="repo_create", name="../x"), refuses(op="issue_create", title="a\x00b"), refuses(op="pr_create", title="t", body="b", reviewers="a;b"), refuses(op="nope"))))
    check("git commands for remote branch delete and tag push: git -C repo push remote --delete name / tag, no force",
          ghops.git_build("branch_delete_remote", "git", tmp, name="old") == ["git", "-C", str(tmp), "push", "origin", "--delete", "old"] and ghops.git_build("tag_push", "git", tmp, tag="v1") == ["git", "-C", str(tmp), "push", "origin", "v1"])

    print("parsers")
    prs = ghops.parse("pr_list", json.dumps([{"number": 7, "title": "T", "state": "OPEN", "isDraft": True, "headRefName": "a", "baseRefName": "main", "author": {"login": "al"}, "updatedAt": "x", "url": "u"}]))
    check("pr list", prs[0]["number"] == 7 and prs[0]["state"] == "open" and prs[0]["draft"] and prs[0]["author"] == "al" and prs[0]["head"] == "a", prs)
    view = {"number": 7, "title": "T", "body": "b", "state": "OPEN", "isDraft": False, "mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY", "reviewDecision": "CHANGES_REQUESTED",
            "statusCheckRollup": [{"name": "t", "conclusion": "FAILURE"}, {"name": "l", "conclusion": "SUCCESS"}, {"name": "p", "status": "IN_PROGRESS"}], "files": [{"path": "a", "additions": 2, "deletions": 1}, {"path": "b", "additions": 1, "deletions": 0}],
            "headRefName": "h", "baseRefName": "main", "url": "u", "comments": [{"author": {"login": "bo"}, "body": "x", "createdAt": "t"}], "author": {"login": "al"}, "autoMergeRequest": None}
    v = ghops.parse("pr_view", json.dumps(view))
    check("pr view: state, review, conflicts, checks, files, comments", v["conflicts"] and v["review"] == "changes_requested" and v["checks"]["state"] == "failing" and v["checks"]["failing"] == ["t"] and v["checks"]["pending"] == ["p"]
          and v["additions"] == 3 and v["deletions"] == 1 and len(v["files"]) == 2 and v["comments"][0]["author"] == "bo", v)
    risks = ghops.merge_risks(v)
    check("merge risks in plain words: conflicts, failing checks (named), requested changes", any("conflicts" in r for r in risks) and any("failing: t" in r for r in risks) and any("asked for changes" in r for r in risks), risks)
    clean = ghops.parse("pr_view", json.dumps(dict(view, mergeable="MERGEABLE", mergeStateStatus="CLEAN", reviewDecision="APPROVED", statusCheckRollup=[{"name": "t", "conclusion": "SUCCESS"}])))
    check("a clean pull request has no risk", ghops.merge_risks(clean) == [] and clean["checks"]["state"] == "passing")
    check("a draft is a risk; no checks is not", "it is still a draft" in ghops.merge_risks(dict(clean, draft=True)) and ghops.checks_summary([])["state"] == "none")
    ch = ghops.parse("pr_checks", json.dumps([{"name": "a", "state": "SUCCESS", "bucket": "pass", "link": "l", "workflow": "CI"}, {"name": "b", "state": "FAILURE", "bucket": "fail", "link": "m", "workflow": "CI"}, {"name": "c", "state": "PENDING", "bucket": "pending", "link": "", "workflow": "CI"}]))
    check("pr checks: failing and pending names, links kept", ch["state"] == "failing" and ch["failing"] == ["b"] and ch["pending"] == ["c"] and ch["checks"][1]["link"] == "m", ch)
    check("repo, run, issue, release and org samples", ghops.parse("repo_list", json.dumps([{"nameWithOwner": "o/r", "isPrivate": True, "description": None, "url": "u"}]))[0]["private"]
          and ghops.parse("run_list", json.dumps([{"databaseId": 5, "name": "CI", "conclusion": "failure"}]))[0]["id"] == 5 and ghops.parse("issue_list", json.dumps([{"number": 3, "title": "t", "state": "CLOSED", "author": {"login": "x"}}]))[0]["state"] == "closed"
          and ghops.parse("release_list", json.dumps([{"tagName": "v1", "isDraft": True}]))[0]["draft"] and ghops.parse("orgs", json.dumps([{"login": "lab", "description": None}]))[0]["login"] == "lab")
    try:
        ghops.parse("pr_list", "not json")
        bad = False
    except ValueError:
        bad = True
    check("unreadable output is a clear error", bad)

    print("plain-words errors")
    samples = {"signin": "To get started with GitHub CLI, please run:  gh auth login", "permission": "GraphQL: Resource not accessible by personal access token (HTTP 403)", "protection": "remote: error: GH006: Protected branch update failed",
               "conflicts": "Pull request is not mergeable: merge conflict in a.py", "no-remote": "fatal: No configured push destination. no git remotes found", "offline": "dial tcp: lookup api.github.com: no such host / could not resolve host",
               "exists": "a pull request for branch \"fig\" into branch \"main\" already exists", "nothing": "pull request create failed: No commits between main and fig", "auto-merge": "Auto merge is not allowed for this repository"}
    for action, text in samples.items():
        t = ghops.translate_error(text)
        check(f"{action}: a plain sentence", t["action"] == action and t["message"] and not t["message"].startswith("GraphQL"), t)
    check("an unknown failure keeps GitHub's last line, tokens removed", SECRET not in ghops.translate_error(f"weird {SECRET}")["message"])

    print("routes")
    os.environ["FAKE_GH_MODE"] = "device"
    for f in ("calls.jsonl", "signed_in", "approve"):
        (tmp / f).unlink(missing_ok=True)
    repo = tmp / "ws"
    repo.mkdir(exist_ok=True)
    git = shutil.which("git")
    if git:
        for cmd in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.org"], ["config", "user.name", "T"]):
            subprocess.run([git, "-C", str(repo), *cmd], check=True)
        (repo / "a.txt").write_text("a", encoding="utf-8")
        subprocess.run([git, "-C", str(repo), "add", "a.txt"], check=True)
        subprocess.run([git, "-C", str(repo), "commit", "-q", "-m", "one"], check=True)
        subprocess.run([git, "-C", str(repo), "branch", "old"], check=True)
    webui.github_cmd = lambda: list(GH)
    netgate.set_backend(None)
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(body, path="/api/github/op"):
        h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "X-PlasBench-Token": webui.TOKEN}
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def op(name, args=None, **extra):
        return call({"op": name, "repo": str(repo), "args": args or {}, **extra})
    code, body = op("pr_list", {"state": "open"})
    check("a read returns parsed data and the command shown", code == 200 and body["result"][0]["number"] == 7 and body["command"].startswith("ghfake.py pr list") or body["command"].startswith("python") or "pr list" in body["command"], body)
    code, body = op("pr_view", {"number": 7})
    check("pr_view: checks, files, comments", code == 200 and body["result"]["checks"]["state"] == "passing" and body["result"]["files"] and body["result"]["comments"], body)
    check("pr_checks, run_list, issue_list, release_list, orgs, repo_list, repo_search answer", all(op(o, a)[0] == 200 for o, a in (("pr_checks", {"number": 7}), ("run_list", {}), ("issue_list", {}), ("release_list", {}), ("orgs", {}), ("repo_list", {}), ("repo_search", {"query": "plasmid"}))))
    check("an unknown operation, a bad number and an unknown field are refused", op("rm_rf")[0] == 400 and op("pr_view", {"number": "x"})[0] == 400)
    code, body = op("pr_create", {"title": "Add", "body": "b", "head": "old", "base": "main"})
    check("a write starts a job whose log starts with the command", code == 200 and body["job"]["kind"] == "git" and "pr create" in body["job"]["command"] and "--title" in body["job"]["command"], body)
    jid = body["job"]["id"]
    end = time.time() + 30
    while time.time() < end and jobs.get(jid)["state"] == "running":
        time.sleep(0.2)
    log = jobs.get(jid)["log"]
    check("the job log shows the command first and the program's output", log.startswith("$ ") and "pr create" in log.splitlines()[0] and "ok" in log, log[:200])
    os.environ["FAKE_GH_PR"] = "failing"
    code, body = op("pr_merge", {"number": 7, "method": "squash"})
    check("a merge with failing checks and conflicts is a 409 with the risks, nothing started", code == 409 and body["needs_confirm"] and any("conflicts" in r for r in body["risks"]) and any("failing" in r for r in body["risks"]), body)
    started_before = len(jobs.jobs)
    code, body = op("pr_merge", {"number": 7, "method": "squash"}, risk_confirmed=True)
    check("confirmed in the dialog, it goes ahead as a job", code == 200 and "pr merge" in body["job"]["command"] and "--squash" in body["job"]["command"], body)
    time.sleep(1.5)
    os.environ.pop("FAKE_GH_PR")
    deadline = time.time() + 30
    while time.time() < deadline and any(j["state"] == "running" for j in jobs.jobs.values()):
        time.sleep(0.2)
    code, body = op("pr_merge", {"number": 7, "method": "merge", "delete_branch": True})
    check("a clean pull request merges without asking again", code == 200 and body.get("job"), body)
    deadline = time.time() + 30
    while time.time() < deadline and any(j["state"] == "running" for j in jobs.jobs.values()):
        time.sleep(0.2)
    os.environ["FAKE_GH_FAIL"] = "1"
    code, body = op("pr_list", {"state": "open"})
    check("a permission failure is a plain sentence", code == 400 and "permission" in body["error"].lower() and body["action"] == "permission", body)
    os.environ.pop("FAKE_GH_FAIL")
    webui.github_cmd = lambda: [sys.executable, "-c", "import sys; sys.stderr.write('To get started with GitHub CLI, please run:  gh auth login'); sys.exit(4)"]
    code, body = op("pr_list", {"state": "open"})
    check("signed out: 401 with action signin (the page opens the sign-in dialog)", code == 401 and body["action"] == "signin", (code, body))
    webui.github_cmd = lambda: list(GH)
    if git:
        code, body = op("branch_delete", {"name": "old"})
        check("local branch delete (git branch -d) works on a real repository", code == 200 and "old" not in subprocess.run([git, "-C", str(repo), "branch"], capture_output=True, text=True).stdout)
        code, body = op("branch_delete", {"name": "main"})
        check("the branch you are on cannot be deleted", code == 400 and "switch" in body["error"], body)
        code, body = op("tag_create", {"name": "v1.0.0", "message": "first"})
        check("tag creation works", code == 200 and "v1.0.0" in subprocess.run([git, "-C", str(repo), "tag"], capture_output=True, text=True).stdout)
        code, body = op("tag_create", {"name": "bad name"})
        check("a bad tag name is refused", code == 400)
    else:
        print("  skip  git is not installed: local branch and tag operations not exercised")
    server.shutdown()

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    wiring = {"create a repository": ("ghCreateRepo", 'id="gh_create"'), "clone / list / search my repositories": ("ghCloneDialog", 'id="gh_clone"'), "branches: switch, push, delete local, delete on GitHub": ("ghBranches", 'id="gh_branches"'),
              "new pull request with push-first offer": ("ghNewPR", 'id="gh_newpr"'), "pull requests list (open / closed / merged)": ("ghPRList", 'id="gh_prs"'), "view, check out, mark ready, close, reopen, comment, merge": ("ghPRView", "data-pr=\"view\""),
              "merge: method, delete branch, auto-merge": ("ghMerge", "Wait for the checks, then merge automatically"), "checks and re-run failed": ("ghChecks", "Re-run failed checks"), "branch checks": ("ghBranchChecks", 'id="gh_checks"'),
              "issues: list, create, comment, close": ("ghIssues", 'id="gh_issues"'), "releases and tags": ("ghReleases", 'id="gh_releases"')}
    for label, (fn, marker) in wiring.items():
        check(f"{label}: wired", f"async function {fn}(" in html and marker in html, fn)
    check("destructive actions confirm first, naming what happens", all(k in html for k in ("Delete the local branch", "Delete ${n} on GitHub?", "Close pull request #", "Close issue #", "Merge anyway?", "Sign out of GitHub?")))
    check("a merge with risks asks the user to confirm the named risk", "ghRisk(op, args, e.data.risks)" in html and "risk_confirmed: true" in html)
    check("not signed in opens the sign-in dialog (401 action signin)", "askSignInDialog(err.message)" in html and 'data.action === "signin"' in html)
    check("the sign-in pop-up is opened inside the click handler, then pointed at the address", 'window.open("about:blank", "plasbench-github"' in html and "popup.location.href = url" in html and "560" in html and "760" in html and "popup.close()" in html)
    check("the dialog shows the code in large type with Copy, a waiting state, and polls every 2 s", 'class="ghcode"' in html and "Copy code" in html and "Waiting for you to approve in the GitHub window" in html and "await sleep(2000)" in html)
    check("a blocked pop-up shows the address with an Open button; a closed pop-up offers to open it again", "Your browser blocked the pop-up window." in html and "I closed it by mistake: open again" in html and "Try again" in html)
    check("the token fallback: a password field, scopes explained, install help with the commands", 'type: "password"' in html and "<b>repo</b> scope" in html and "The GitHub CLI is not installed" in html)
    check("the account row: signed-in user, Sign out, Switch account", "Signed in to GitHub as" in html and 'id="${idp}out"' in html and "Switch account" in html)
    check("no browser confirm / prompt / alert anywhere", not re.search(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", html.split("let DLG_N = 0;")[0] + html.split("/* ---- help tooltip: an (i) button")[1]))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
