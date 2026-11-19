"""A fake GitHub CLI for the tests: `python ghfake.py ARGS...` behaves like the parts of `gh` that PlasBench uses, records every call, and never touches the network.

Environment: FAKE_GH_DIR (a folder for the state files), FAKE_GH_MODE (device | already | fail | silent), FAKE_GH_LOG is FAKE_GH_DIR/calls.jsonl. A sign-in "completes" when
FAKE_GH_DIR/approve exists; "signed in" is the file FAKE_GH_DIR/signed_in.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")
D = Path(os.environ.get("FAKE_GH_DIR", "."))
args = sys.argv[1:]
stdin_text = ""
if "--with-token" in args:
    stdin_text = sys.stdin.read()
with open(D / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "stdin_len": len(stdin_text), "stdin": stdin_text, "browser": os.environ.get("BROWSER", "")}) + "\n")
PR = {"number": 7, "title": "Add figures", "body": "Adds figures.", "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED",
      "statusCheckRollup": [{"name": "tests", "conclusion": "SUCCESS", "status": "COMPLETED"}], "files": [{"path": "a.py", "additions": 3, "deletions": 1}], "headRefName": "fig", "baseRefName": "main",
      "url": "https://github.com/o/r/pull/7", "comments": [{"author": {"login": "bob"}, "body": "Looks good", "createdAt": "2026-11-18T10:00:00Z"}], "author": {"login": "alice"}, "autoMergeRequest": None}
if os.environ.get("FAKE_GH_PR") == "failing":
    PR.update(statusCheckRollup=[{"name": "tests", "conclusion": "FAILURE", "status": "COMPLETED"}, {"name": "lint", "conclusion": "SUCCESS", "status": "COMPLETED"}], mergeable="CONFLICTING", mergeStateStatus="DIRTY")
a = args


def say(text, code=0):
    sys.stdout.write(text)
    sys.stdout.flush()
    sys.exit(code)


if a[:2] == ["auth", "login"] and "--web" in a:
    mode = os.environ.get("FAKE_GH_MODE", "device")
    if mode == "already":
        say("! You are already logged in to github.com account octocat\n")
    if mode == "silent":
        time.sleep(60)
        sys.exit(0)
    sys.stdout.write("! First copy your one-time code: ABCD-1234\nOpen this URL to continue in your web browser: https://github.com/login/device\n")
    sys.stdout.flush()
    if mode == "fail":
        time.sleep(0.5)
        say("error: authentication failed: the device code expired\n", 1)
    end = time.time() + 60
    while time.time() < end:
        if (D / "approve").exists():
            (D / "signed_in").write_text("1")
            say("✓ Authentication complete.\n")
        time.sleep(0.1)
    sys.exit(1)
if a[:2] == ["auth", "login"] and "--with-token" in a:
    if stdin_text.strip().startswith("bad"):
        say("error: the token is invalid\n", 1)
    (D / "signed_in").write_text("1")
    say("✓ Logged in\n")
if a[:2] == ["auth", "status"]:
    if (D / "signed_in").exists():
        say("github.com\n  ✓ Logged in to github.com account octocat (keyring)\n  - Active account: true\n  - Git operations protocol: https\n  - Token scopes: 'repo', 'workflow'\n")
    say("You are not logged into any GitHub hosts. To log in, run: gh auth login\n", 1)
if a[:2] == ["auth", "logout"]:
    (D / "signed_in").unlink(missing_ok=True)
    say("✓ Logged out of github.com account octocat\n")
if a[:2] == ["auth", "setup-git"]:
    say("")
if os.environ.get("FAKE_GH_FAIL"):
    say("GraphQL: Resource not accessible by personal access token (HTTP 403)\n", 1)
if a[:2] == ["api", "user/orgs"]:
    say(json.dumps([{"login": "lab-org", "description": "Our lab"}]))
if a[:2] == ["repo", "list"]:
    say(json.dumps([{"nameWithOwner": "octocat/runs", "description": "my runs", "isPrivate": True, "url": "https://github.com/octocat/runs", "pushedAt": "2026-11-17T09:00:00Z"}]))
if a[:2] == ["search", "repos"]:
    say(json.dumps([{"fullName": "o/found", "description": "d", "url": "https://github.com/o/found", "isPrivate": False}]))
if a[:2] == ["pr", "list"]:
    say(json.dumps([{"number": 7, "title": "Add figures", "state": "OPEN", "isDraft": False, "headRefName": "fig", "baseRefName": "main", "author": {"login": "alice"}, "updatedAt": "2026-11-18T10:00:00Z", "url": "https://github.com/o/r/pull/7"}]))
if a[:2] == ["pr", "view"]:
    say(json.dumps(PR))
if a[:2] == ["pr", "checks"]:
    say(json.dumps([{"name": "tests", "state": "SUCCESS", "bucket": "pass", "link": "https://github.com/o/r/actions/runs/1", "workflow": "CI"}, {"name": "lint", "state": "FAILURE", "bucket": "fail", "link": "https://github.com/o/r/actions/runs/2", "workflow": "CI"}]))
if a[:2] == ["run", "list"]:
    say(json.dumps([{"databaseId": 99, "name": "CI", "status": "completed", "conclusion": "failure", "url": "https://github.com/o/r/actions/runs/99", "headBranch": "fig", "event": "push", "createdAt": "2026-11-18T10:00:00Z"}]))
if a[:2] == ["issue", "list"]:
    say(json.dumps([{"number": 3, "title": "Bug", "state": "OPEN", "author": {"login": "bob"}, "url": "https://github.com/o/r/issues/3", "updatedAt": "2026-11-18T10:00:00Z"}]))
if a[:2] == ["release", "list"]:
    say(json.dumps([{"tagName": "v0.5.0", "name": "v0.5.0", "isDraft": False, "isPrerelease": False, "publishedAt": "2026-11-18T08:00:00Z"}]))
say("ok\n")
