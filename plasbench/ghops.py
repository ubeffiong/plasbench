"""GitHub actions of the Version control page, through the GitHub CLI (`gh`): repositories, branches, pull requests, checks, issues, releases.

Every operation is built here as an argument list (never a shell string, never a token: gh uses the sign-in made by plasbench/ghsignin.py), validated first. Reading operations
(`READ_OPS`) are run now and parsed from `--json` output; writing operations (`WRITE_OPS`) run as jobs in the console, with their command shown and tokens redacted. Nothing here
force-pushes, and nothing destructive runs without the window's confirmation dialog (the server also refuses a merge with failing checks or conflicts unless the user confirmed the risk).
`translate_error` turns gh/git failures into plain sentences, with an `action` for the page ("signin" opens the sign-in dialog). Standard library only.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .ghsignin import redact

NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
REPO_RE = re.compile(r"^(?:[A-Za-z0-9-]{1,39}/)?[A-Za-z0-9._-]{1,100}$")
FULL_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
TAG_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
LABEL_RE = re.compile(r"^[^,\x00-\x1f]{1,50}$")
STATES = ("open", "closed", "merged", "all")

READ_OPS = {"orgs", "repo_list", "repo_search", "pr_list", "pr_view", "pr_checks", "run_list", "issue_list", "release_list", "branch_remote_list"}
WRITE_OPS = {"repo_create", "pr_create", "pr_checkout", "pr_ready", "pr_close", "pr_reopen", "pr_merge", "run_rerun", "issue_create", "issue_comment", "issue_close",
             "release_create", "tag_push", "branch_delete_remote", "pr_comment"}
LOCAL_OPS = {"branch_delete", "tag_create"}      # quick git operations (plasbench/gitops.py)
DESTRUCTIVE = {"pr_close", "pr_merge", "branch_delete_remote", "branch_delete", "issue_close"}

JSON_FIELDS = {
    "repo_list": "nameWithOwner,description,isPrivate,url,pushedAt",
    "repo_search": "fullName,description,url,isPrivate",
    "pr_list": "number,title,state,isDraft,headRefName,baseRefName,author,updatedAt,url",
    "pr_view": "number,title,body,state,isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,files,headRefName,baseRefName,url,comments,author,autoMergeRequest",
    "pr_checks": "name,state,bucket,link,workflow",
    "run_list": "databaseId,name,status,conclusion,url,headBranch,event,createdAt",
    "issue_list": "number,title,state,author,url,updatedAt",
    "release_list": "tagName,name,isDraft,isPrerelease,publishedAt",
}


class GhError(ValueError):
    """A GitHub action that failed, in plain words. `action` tells the page what to offer ("signin" opens the sign-in dialog)."""
    action = ""
    detail = ""


class RiskError(ValueError):
    """A merge that would go wrong (failing checks, conflicts ...): the page must show the risks and ask the user to confirm."""

    def __init__(self, message, risks):
        super().__init__(message)
        self.risks = list(risks)


def _text(value, label, limit=65536, required=False) -> str:
    value = "" if value is None else str(value)
    if "\x00" in value:
        raise ValueError(f"{label} contains a character that is not allowed")
    if required and not value.strip():
        raise ValueError(f"{label} is required")
    if len(value) > limit:
        raise ValueError(f"{label} is too long")
    return value


def _num(value, label="number") -> str:
    v = str(value).strip().lstrip("#")
    if not v.isdigit() or int(v) < 1 or int(v) > 10_000_000:
        raise ValueError(f"{label}: give a pull request or issue number")
    return v


def _name(value, label, pattern=NAME_RE) -> str:
    v = (value or "").strip()
    if not pattern.match(v) or v.startswith("-") or ".." in v:
        raise ValueError(f"{label}: letters, numbers, . _ - (and / in branch names) only")
    return v


def _login_list(value, label) -> list:
    items = [x.strip().lstrip("@") for x in re.split(r"[,\s]+", value or "") if x.strip()] if isinstance(value, str) else [str(x).strip().lstrip("@") for x in (value or [])]
    for x in items:
        if not (LOGIN_RE.match(x) or re.match(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9_-]{1,100}$", x)):
            raise ValueError(f"{label}: a GitHub user name (or org/team)")
    return items


def build(op: str, gh: list, repo=None, **kw) -> list:
    """The argument list for `op` (gh prefix first). Raises ValueError for anything that does not validate."""
    gh = list(gh)
    fields = JSON_FIELDS.get(op)
    if op == "orgs":
        return gh + ["api", "user/orgs", "--paginate", "--jq", "[.[] | {login: .login, description: .description}]"]
    if op == "repo_list":
        owner = (kw.get("owner") or "").strip()
        cmd = gh + ["repo", "list"] + ([_name(owner, "owner", LOGIN_RE)] if owner else []) + ["--limit", "100", "--json", fields]
        return cmd
    if op == "repo_search":
        q = _text(kw.get("query"), "search words", 200, True).strip()
        if q.startswith("-"):
            raise ValueError("search words cannot start with -")
        return gh + ["search", "repos", "--limit", "30", "--json", fields, "--", q]
    if op == "repo_create":
        name = (kw.get("name") or "").strip()
        owner = (kw.get("owner") or "").strip()
        if "/" in name:
            owner, name = name.split("/", 1)
        full = f"{_name(owner, 'owner', LOGIN_RE)}/{_name(name, 'repository name')}" if owner else _name(name, "repository name")
        cmd = gh + ["repo", "create", full, "--public" if kw.get("visibility") == "public" else "--private", "--source", str(repo), "--remote", "origin"]
        desc = _text(kw.get("description"), "description", 350)
        if desc.strip():
            cmd += ["--description", desc]
        if kw.get("push", True):
            cmd += ["--push"]
        return cmd
    if op == "pr_create":
        cmd = gh + ["pr", "create", "--title", _text(kw.get("title"), "title", 256, True), "--body", _text(kw.get("body"), "description", 65536)]
        if kw.get("base"):
            cmd += ["--base", _name(kw["base"], "base branch", BRANCH_RE)]
        if kw.get("head"):
            cmd += ["--head", _name(kw["head"], "head branch", BRANCH_RE)]
        if kw.get("draft"):
            cmd += ["--draft"]
        for who in _login_list(kw.get("reviewers"), "reviewer"):
            cmd += ["--reviewer", who]
        for label in [x.strip() for x in re.split(r"[,]", kw.get("labels") or "") if x.strip()]:
            if not LABEL_RE.match(label):
                raise ValueError("labels: plain words separated by commas")
            cmd += ["--label", label]
        return cmd
    if op == "pr_list":
        state = kw.get("state") or "open"
        if state not in STATES:
            raise ValueError("state: open, closed, merged or all")
        return gh + ["pr", "list", "--state", state, "--limit", "50", "--json", fields]
    if op == "pr_view":
        return gh + ["pr", "view", _num(kw.get("number")), "--json", fields]
    if op == "pr_checks":
        return gh + ["pr", "checks", _num(kw.get("number")), "--json", fields]
    if op == "pr_checkout":
        return gh + ["pr", "checkout", _num(kw.get("number"))]
    if op == "pr_ready":
        return gh + ["pr", "ready", _num(kw.get("number"))]
    if op == "pr_close":
        return gh + ["pr", "close", _num(kw.get("number"))] + (["--delete-branch"] if kw.get("delete_branch") else [])
    if op == "pr_reopen":
        return gh + ["pr", "reopen", _num(kw.get("number"))]
    if op == "pr_comment":
        return gh + ["pr", "comment", _num(kw.get("number")), "--body", _text(kw.get("body"), "comment", 65536, True)]
    if op == "pr_merge":
        method = kw.get("method") or "merge"
        if method not in ("merge", "squash", "rebase"):
            raise ValueError("merge method: merge, squash or rebase")
        cmd = gh + ["pr", "merge", _num(kw.get("number")), "--" + method]
        if kw.get("delete_branch"):
            cmd += ["--delete-branch"]
        if kw.get("auto"):
            cmd += ["--auto"]
        return cmd
    if op == "run_list":
        branch = (kw.get("branch") or "").strip()
        return gh + ["run", "list", "--limit", "10", "--json", fields] + (["--branch", _name(branch, "branch", BRANCH_RE)] if branch else [])
    if op == "run_rerun":
        run_id = str(kw.get("run_id") or "").strip()
        if not run_id.isdigit():
            raise ValueError("run: give the workflow run number")
        return gh + ["run", "rerun", run_id, "--failed"]
    if op == "issue_list":
        state = kw.get("state") or "open"
        if state not in ("open", "closed", "all"):
            raise ValueError("state: open, closed or all")
        return gh + ["issue", "list", "--state", state, "--limit", "50", "--json", fields]
    if op == "issue_create":
        return gh + ["issue", "create", "--title", _text(kw.get("title"), "title", 256, True), "--body", _text(kw.get("body"), "description", 65536)]
    if op == "issue_comment":
        return gh + ["issue", "comment", _num(kw.get("number")), "--body", _text(kw.get("body"), "comment", 65536, True)]
    if op == "issue_close":
        return gh + ["issue", "close", _num(kw.get("number"))]
    if op == "release_list":
        return gh + ["release", "list", "--limit", "30", "--json", fields]
    if op == "release_create":
        tag = _name(kw.get("tag"), "tag", TAG_RE)
        cmd = gh + ["release", "create", tag, "--title", _text(kw.get("title") or tag, "title", 256), "--notes", _text(kw.get("notes"), "notes", 65536)]
        if kw.get("draft"):
            cmd += ["--draft"]
        if kw.get("prerelease"):
            cmd += ["--prerelease"]
        return cmd
    raise ValueError("unknown GitHub action")


def git_build(op: str, git: str, repo, **kw) -> list:
    """git commands for the branch and tag actions (no shell, no force)."""
    base = [git, "-C", str(repo)]
    if op == "branch_delete_remote":
        return base + ["push", _name(kw.get("remote") or "origin", "remote"), "--delete", _name(kw.get("name"), "branch", BRANCH_RE)]
    if op == "tag_push":
        return base + ["push", _name(kw.get("remote") or "origin", "remote"), _name(kw.get("tag"), "tag", TAG_RE)]
    raise ValueError("unknown git action")


# ---------------------------------------------------------------- parsing
def _json(text: str):
    try:
        return json.loads(text or "null")
    except ValueError:
        raise ValueError("GitHub's answer could not be read (" + redact((text or "")[:120]) + ")")


def _login(author) -> str:
    return (author or {}).get("login", "") if isinstance(author, dict) else str(author or "")


def checks_summary(rollup) -> dict:
    """{state: passing|failing|pending|none, failing: [names], pending: [names], total} from a statusCheckRollup (or `gh pr checks --json`) list."""
    failing, pending, passed = [], [], 0
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "check"
        verdict = str(c.get("bucket") or c.get("conclusion") or c.get("state") or c.get("status") or "").lower()
        if verdict in ("fail", "failure", "failed", "error", "cancelled", "cancel", "timed_out", "action_required"):
            failing.append(name)
        elif verdict in ("pending", "in_progress", "queued", "waiting", "requested", "expected", ""):
            pending.append(name)
        else:
            passed += 1
    state = "failing" if failing else "pending" if pending else "passing" if passed else "none"
    return {"state": state, "failing": failing, "pending": pending, "total": len(rollup or [])}


def parse(op: str, text: str):
    """The structure the page shows for a reading operation."""
    data = _json(text)
    if op == "orgs":
        return [{"login": o.get("login"), "description": o.get("description") or ""} for o in (data or [])]
    if op == "repo_list":
        return [{"full_name": r.get("nameWithOwner"), "description": r.get("description") or "", "private": bool(r.get("isPrivate")), "url": r.get("url"), "pushed": r.get("pushedAt")} for r in (data or [])]
    if op == "repo_search":
        return [{"full_name": r.get("fullName"), "description": r.get("description") or "", "private": bool(r.get("isPrivate")), "url": r.get("url")} for r in (data or [])]
    if op == "pr_list":
        return [{"number": p.get("number"), "title": p.get("title"), "state": str(p.get("state") or "").lower(), "draft": bool(p.get("isDraft")), "head": p.get("headRefName"), "base": p.get("baseRefName"),
                 "author": _login(p.get("author")), "updated": p.get("updatedAt"), "url": p.get("url")} for p in (data or [])]
    if op == "pr_view":
        d = data or {}
        merge_state = str(d.get("mergeStateStatus") or "").upper()
        mergeable = str(d.get("mergeable") or "").upper()
        checks = checks_summary(d.get("statusCheckRollup"))
        files = [{"path": f.get("path"), "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)} for f in (d.get("files") or [])]
        return {"number": d.get("number"), "title": d.get("title"), "body": d.get("body") or "", "state": str(d.get("state") or "").lower(), "draft": bool(d.get("isDraft")), "head": d.get("headRefName"), "base": d.get("baseRefName"),
                "author": _login(d.get("author")), "url": d.get("url"), "review": str(d.get("reviewDecision") or "none").lower() or "none", "mergeable": mergeable, "merge_state": merge_state,
                "conflicts": mergeable == "CONFLICTING" or merge_state == "DIRTY", "checks": checks, "files": files, "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files),
                "auto_merge": bool(d.get("autoMergeRequest")),
                "comments": [{"author": _login(c.get("author")), "body": c.get("body") or "", "created": c.get("createdAt")} for c in (d.get("comments") or [])]}
    if op == "pr_checks":
        rows = [{"name": c.get("name"), "state": str(c.get("state") or "").lower(), "bucket": str(c.get("bucket") or "").lower(), "link": c.get("link"), "workflow": c.get("workflow")} for c in (data or [])]
        return {"checks": rows, **checks_summary(data)}
    if op == "run_list":
        return [{"id": r.get("databaseId"), "name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"), "url": r.get("url"), "branch": r.get("headBranch"), "created": r.get("createdAt")} for r in (data or [])]
    if op == "issue_list":
        return [{"number": i.get("number"), "title": i.get("title"), "state": str(i.get("state") or "").lower(), "author": _login(i.get("author")), "url": i.get("url"), "updated": i.get("updatedAt")} for i in (data or [])]
    if op == "release_list":
        return [{"tag": r.get("tagName"), "name": r.get("name") or r.get("tagName"), "draft": bool(r.get("isDraft")), "prerelease": bool(r.get("isPrerelease")), "published": r.get("publishedAt")} for r in (data or [])]
    return data


def merge_risks(view: dict) -> list:
    """Plain sentences for what would go wrong if this pull request were merged now (empty when nothing is known to be wrong)."""
    risks = []
    if view.get("draft"):
        risks.append("it is still a draft")
    if view.get("conflicts"):
        risks.append("it has merge conflicts with the base branch")
    c = view.get("checks") or {}
    if c.get("state") == "failing":
        risks.append("checks are failing: " + ", ".join(c.get("failing")[:5]))
    elif c.get("state") == "pending":
        risks.append("checks are still running: " + ", ".join(c.get("pending")[:5]))
    if view.get("review") == "changes_requested":
        risks.append("a reviewer asked for changes")
    if view.get("merge_state") == "BLOCKED":
        risks.append("branch protection blocks the merge (a required review or check is missing)")
    return risks


# ---------------------------------------------------------------- errors in plain words
ERRORS = [
    (r"not logged in|gh auth login|authentication required|bad credentials|http 401|requires authentication|no oauth token|to get started with github cli", "signin", "You are not signed in to GitHub. Sign in, then try again."),
    (r"could not resolve host|dial tcp|network is unreachable|timed out|timeout|temporary failure in name resolution|connection refused", "offline", "GitHub could not be reached. Check your internet connection and try again."),
    (r"protected branch|required status check|review required|at least \d+ approving|branch protection|repository rule violations", "protection", "Branch protection stops this: a required review or check is missing. Fix that on GitHub, or ask someone with permission."),
    (r"merge conflict|conflicting|not mergeable|conflicts? (?:in|with)", "conflicts", "The pull request has merge conflicts. Update the branch with the base branch and resolve the conflicts first."),
    (r"resource not accessible|http 403|must have (?:admin|write|push)|permission|forbidden|http 404|could not resolve to a repository|not found", "permission", "You do not have permission for this on GitHub (or it does not exist): check the name and your access to the repository."),
    (r"no git remotes|no remote|does not appear to be a git repository|no default remote", "no-remote", "This repository has no remote on GitHub yet: create it or connect an existing one first."),
    (r"already exists|name already exists on this account|pull request for branch .* already exists", "exists", "That already exists on GitHub."),
    (r"no commits between|nothing to compare|head sha can't be blank|must first push the current branch|has no commits", "nothing", "There is nothing to open a pull request for: the branch has no new commits, or it has not been pushed yet."),
    (r"auto.?merge is not allowed|auto merge", "auto-merge", "Waiting for checks and merging automatically is not allowed in this repository's settings; merge once the checks pass."),
    (r"remote ref does not exist|unable to delete .* remote ref", "gone", "That branch is no longer on GitHub."),
]


def translate_error(text: str) -> dict:
    """{"action", "message"}: a plain sentence for a gh / git failure (the original last line is appended, tokens removed)."""
    clean = redact((text or "").strip())
    low = clean.lower()
    last = [l for l in clean.splitlines() if l.strip()][-1:] or [""]
    for pattern, action, sentence in ERRORS:
        if re.search(pattern, low):
            return {"action": action, "message": sentence, "detail": last[0][:300]}
    return {"action": "", "message": "GitHub reported a problem" + (": " + last[0][:300] if last[0] else "."), "detail": last[0][:300]}


def run_read(op: str, gh: list, repo=None, runner=subprocess.run, timeout: int = 60, env=None, **kw):
    """Run a reading operation now. Returns (parsed, command-as-shown). Raises ValueError(plain sentence) with `.action` set."""
    from .ghsignin import clean_env
    cmd = build(op, gh, repo, **kw)
    try:
        done = runner(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(repo) if repo else None, env=env or clean_env(), stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        err = GhError("GitHub did not answer in time. Check your internet connection and try again.")
        err.action = "offline"
        raise err
    except OSError as exc:
        raise ValueError(f"the GitHub CLI could not be started: {exc.strerror or exc}")
    if getattr(done, "returncode", 1) != 0:
        t = translate_error((getattr(done, "stderr", "") or "") + "\n" + (getattr(done, "stdout", "") or ""))
        err = GhError(t["message"])
        err.action, err.detail = t["action"], t["detail"]
        raise err
    return parse(op, done.stdout), shown(cmd)


def shown(cmd) -> str:
    """The command as written in the job log: a plain `gh ...` line, tokens removed."""
    import shlex
    parts = [Path(str(cmd[0])).name] + [str(a) for a in cmd[1:]]
    return redact(" ".join(shlex.quote(p) for p in parts))
