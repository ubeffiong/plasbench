"""Git from the PlasBench window: initialise, stage, commit, branch, add a remote, pull and push, without typing git.

Ported from GenoSuv's gitops.py (same design, same author), with PlasBench's data rules:
  * git is always called with an argument LIST (never through a shell), `GIT_TERMINAL_PROMPT=0` (no hidden prompt that
    hangs) and config hardening so a repository's own .git/config cannot make reading it run a program;
  * a managed .gitignore block keeps studies, results, downloads, reads, alignments, logs and credentials out;
  * every commit is scanned first: reads/alignments/run folders, secrets (config/local.env holds the NCBI API key) and
    files over GitHub's 100 MB limit block it (data and secrets can be overridden only by typing a sentence; size not);
  * remote addresses may not contain credentials; there is no force-push and no history rewriting;
  * AI co-author / "generated with" trailers are removed from commit messages (project rule);
  * output shown in the window is redacted for tokens.
Long operations (fetch, pull, push, clone, GitHub sign-in and repository creation) are returned as argument lists for
the window's job runner, so their output streams into the console.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OVERRIDE_SENTENCE = "I UNDERSTAND THIS MAY EXPOSE DATA OR SECRETS"
MAX_FILE = 100 * 2**20
WARN_FILE = 20 * 2**20

SAFE_IGNORE = """# --- PlasBench safety block (managed: keeps run outputs, large raw files and credentials out of git) ---
studies/
results/
results_*/
data/
logs/
tmp/
.plasbench-backup/
__pycache__/
*.egg-info/
*.fastq
*.fastq.gz
*.fq
*.fq.gz
*.bam
*.bai
*.cram
*.sra
*.paf
*.gfa
*.gfa.gz
config/local.env
.ncbi.env
.env
*.pem
*.key
*.pfx
id_rsa*
id_ed25519*
.pytest_cache/
# --- end PlasBench safety block ---
"""

DATA_PATTERNS = [
    (re.compile(r"\.(fastq|fq|bam|cram|sam|sra|bcf)(\.gz)?$", re.I), "raw sequencing reads or alignments"),
    (re.compile(r"\.(paf|gfa)(\.gz)?$", re.I), "alignment or assembly-graph output"),
    (re.compile(r"(^|/)(studies|results|results_[^/]+|data|logs|tmp)/"), "run output or download folder"),
    (re.compile(r"(^|/)\.plasbench-backup/"), "PlasBench update backups"),
]
SECRET_PATTERNS = [
    (re.compile(r"\.(pem|key|pfx|p12)$", re.I), "private key / certificate file"),
    (re.compile(r"(^|/)\.env(\.|$)", re.I), "environment file with secrets"),
    (re.compile(r"(^|/)config/local\.env$"), "this computer's PlasBench settings (holds the NCBI API key)"),
    (re.compile(r"(^|/)\.ncbi\.env$"), "NCBI credentials"),
    (re.compile(r"(^|/)(id_rsa|id_ed25519|credentials)", re.I), "credentials file"),
    (re.compile(r"\.(exe|dll)$", re.I), "Windows binary (not source code)"),
]
SECRET_CONTENT = [
    (re.compile(r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gho_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"(?i)NCBI_API_KEY\s*=\s*['\"]?[0-9a-f]{30,}"), "NCBI API key"),
    (re.compile(r"(?i)(access[_-]?token|api[_-]?key|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{24,}"), "access token or key"),
]
# Isolate metadata can carry patient information (clinical isolates): direct identifier columns block a commit.
IDENTIFIER_CONTENT = [
    (re.compile(r"(?im)^.*\b(patient[_ ]?name|full[_ ]?name|surname|first[_ ]?name|date[_ ]?of[_ ]?birth|"
                r"national[_ ]?id|hospital[_ ]?number|home[_ ]?address|telephone|phone[_ ]?number)\b.*$"),
     "a column of direct patient identifiers"),
]

TOKEN_RE = re.compile(r"(?i)(ghp_|gho_|github_pat_)[A-Za-z0-9_]+|(?<=://)[^/@\s:]+:[^/@\s]+@|(?<=://)[A-Za-z0-9_\-]{20,}@")


class GitError(RuntimeError):
    pass


def redact(text: str) -> str:
    return TOKEN_RE.sub("<redacted>@" if False else "<redacted>", text or "")


def find_git() -> str | None:
    p = shutil.which("git")
    if p:
        return p
    for c in (r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe", "/usr/bin/git", "/usr/local/bin/git"):
        if Path(c).exists():
            return c
    return None


def find_gh() -> str | None:
    p = shutil.which("gh")
    if p:
        return p
    for c in (r"C:\Program Files\GitHub CLI\gh.exe", "/usr/bin/gh", "/usr/local/bin/gh"):
        if Path(c).exists():
            return c
    return None


def _env() -> dict:
    e = dict(os.environ)
    e["GIT_TERMINAL_PROMPT"] = "0"          # never wait on a hidden terminal prompt
    e["LC_ALL"] = "C"
    e.pop("GIT_ASKPASS", None)
    return e


def run(repo: str | Path | None, *args, timeout: int = 120, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    git = find_git()
    if not git:
        raise GitError("git is not installed: install Git (https://git-scm.com/) and reopen the window")
    # A repository directory is attacker-controllable input (the user can point the UI at any
    # folder, and a .git/config there can name a program to run). These -c options disable the
    # config knobs that turn "reading a repository" into "executing its contents".
    safe = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "-c", "protocol.ext.allow=never", "-c", "protocol.file.allow=user",
            "-c", "core.askPass=", "-c", "credential.helper=",
            "-c", "uploadpack.packObjectsHook=",
            "-c", "core.sshCommand=ssh -o BatchMode=yes"]
    cmd = [git] + safe + (["-C", str(repo)] if repo else []) + [str(a) for a in args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, env=_env(), input=input_text,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise GitError("git took too long and was stopped")
    if check and p.returncode != 0:
        msg = redact((p.stderr or p.stdout).strip())
        if "dubious ownership" in msg:
            msg += "\nHint: the folder belongs to another user. Run once:  git config --global --add safe.directory <folder>"
        raise GitError(msg[:1500] or f"git {args[0]} failed (exit {p.returncode})")
    return p


# ---------------------------------------------------------------- validation
def valid_remote_url(url: str) -> str:
    u = (url or "").strip()
    if not u or re.search(r"\s", u) or u.startswith("-"):
        raise ValueError("enter the repository address (for example https://github.com/your-org/your-repo.git)")
    if re.match(r"^[a-z]+::", u) or u.lower().startswith(("ext:", "file:")):
        raise ValueError("that kind of address is not allowed")
    if re.match(r"^https?://[^/]*@", u):
        raise ValueError("do not put a user name, password or token in the address (it would be stored in plain text). "
                         "Sign in with the Sign-in button instead.")
    if re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?/[\w.~/%-]+$", u) or re.match(r"^git@[A-Za-z0-9.-]+:[\w.~/-]+$", u) \
            or re.match(r"^ssh://git@[A-Za-z0-9.-]+(:\d+)?/[\w.~/-]+$", u):
        return u
    if re.match(r"^http://", u):
        raise ValueError("use https:// (plain http sends your sign-in unencrypted)")
    p = Path(u)
    if p.is_absolute() and p.exists():                       # a local or shared-drive bare repository
        return str(p)
    raise ValueError("that does not look like a git repository address (https://..., git@host:org/repo.git, or an existing local folder)")


def valid_branch(name: str) -> str:
    n = (name or "").strip()
    if not re.match(r"^(?!-)[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$", n) or ".." in n or n.endswith((".lock", "/", ".")):
        raise ValueError("branch names use letters, numbers, . _ - / and cannot start with - or contain ..")
    return n


def valid_repo(path: str, allowed_roots=None) -> Path:
    """Validate a repository folder, optionally confining it to allowed roots.

    The window passes the PlasBench folder and the workspace as the allowed roots: a repository elsewhere on the
    machine is outside what PlasBench manages, and opening an arbitrary folder as a git repository means reading a
    .git/config that somebody else may have written."""
    p = Path((path or "").strip().strip('"'))
    if not p.is_absolute():
        raise ValueError("give the full path of the folder")
    if not p.is_dir():
        raise ValueError("that folder does not exist")
    p = Path(os.path.realpath(p))
    if allowed_roots:
        roots = [Path(os.path.realpath(r)) for r in allowed_roots if r]
        if not any(p == r or r in p.parents for r in roots):
            raise ValueError("that folder is outside the PlasBench folder and the workspace; "
                             "choose a folder inside one of them")
    return p


# ---------------------------------------------------------------- status
def info(repo: str | Path) -> dict:
    out: dict = {"installed": bool(find_git()), "gh": bool(find_gh()), "repo": str(repo), "is_repo": False, "files": [], "remotes": [],
                 "branch": None, "upstream": None, "ahead": 0, "behind": 0, "user": {}, "last": None, "state": ""}
    if not out["installed"]:
        return out
    out["version"] = run(None, "--version", check=False).stdout.strip().replace("git version ", "")
    top = run(repo, "rev-parse", "--show-toplevel", check=False)
    cfg_name = run(repo, "config", "user.name", check=False).stdout.strip()
    cfg_mail = run(repo, "config", "user.email", check=False).stdout.strip()
    out["user"] = {"name": cfg_name, "email": cfg_mail}
    if top.returncode != 0:
        return out
    out["is_repo"] = True
    out["root"] = top.stdout.strip()
    # 'normal' reports an untracked DIRECTORY once; 'all' walked every file inside it, so a
    # polled status recursed through runs/ (hundreds of thousands of files) every few seconds.
    st = run(repo, "status", "--porcelain=v2", "--branch", "--untracked-files=normal", "-z", check=False)
    recs = st.stdout.split("\0")
    i = 0
    files = []
    while i < len(recs):
        r = recs[i]
        i += 1
        if not r:
            continue
        if r.startswith("# branch.head "):
            out["branch"] = r.split(" ", 2)[2]
        elif r.startswith("# branch.upstream "):
            out["upstream"] = r.split(" ", 2)[2]
        elif r.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", r)
            out["ahead"], out["behind"] = int(m[1]), int(m[2])
        elif r.startswith("# branch.oid") and r.endswith("(initial)"):
            out["no_commits"] = True
        elif r[0] == "1":
            p = r.split(" ", 8)
            files.append({"path": p[8], "x": p[1][0], "y": p[1][1]})
        elif r[0] == "2":
            p = r.split(" ", 9)
            files.append({"path": p[9], "x": p[1][0], "y": p[1][1], "from": recs[i] if i < len(recs) else ""})
            i += 1
        elif r[0] == "u":
            p = r.split(" ", 10)
            files.append({"path": p[10], "x": "U", "y": "U", "conflict": True})
        elif r[0] == "?":
            files.append({"path": r[2:], "x": "?", "y": "?"})
    for f in files:
        f["staged"] = f["x"] not in (".", "?")
        f["unstaged"] = f["y"] not in (".",) and f["x"] != "?"
        f["untracked"] = f["x"] == "?"
    out["files"] = files[:1000]
    out["n_files"] = len(files)
    for line in run(repo, "remote", "-v", check=False).stdout.splitlines():
        m = re.match(r"(\S+)\s+(\S+)\s+\((fetch|push)\)", line)
        if m and m[3] == "fetch":
            out["remotes"].append({"name": m[1], "url": redact(m[2])})
    last = run(repo, "log", "-1", "--format=%h%x09%s%x09%an%x09%ar", check=False)
    if last.returncode == 0 and last.stdout.strip():
        h, s, a, w = (last.stdout.strip().split("\t") + ["", "", "", ""])[:4]
        out["last"] = {"hash": h, "subject": s, "author": a, "when": w}
    gd = Path(out["root"]) / ".git"
    out["state"] = ("merging" if (gd / "MERGE_HEAD").exists() else "rebasing" if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists() else "")
    return out


def log(repo, n: int = 30) -> list[dict]:
    p = run(repo, "log", f"-{int(n)}", "--format=%H%x09%h%x09%s%x09%an%x09%ar", check=False)
    rows = []
    for line in p.stdout.splitlines():
        h, s, subj, a, w = (line.split("\t") + ["", "", "", ""])[:5]
        rows.append({"hash": h, "short": s, "subject": subj, "author": a, "when": w})
    return rows


def branches(repo) -> list[dict]:
    p = run(repo, "branch", "--format=%(HEAD)%09%(refname:short)%09%(upstream:short)", check=False)
    return [{"current": l[0] == "*", "name": l.split("\t")[1], "upstream": (l.split("\t") + [""])[2]} for l in p.stdout.splitlines() if "\t" in l]


def diff(repo, path: str, staged: bool = False, limit: int = 200_000) -> str:
    rel = _inside(repo, path)
    # --no-ext-diff: a repository's own config must not choose a program to run here
    args = ["diff", "--no-color", "--no-ext-diff"] + (["--cached"] if staged else []) + ["--", rel]
    p = run(repo, *args, check=False)
    text = p.stdout
    if not text and not staged:                      # untracked file: show it as an addition
        f = Path(repo) / rel
        if f.is_file() and f.stat().st_size < limit:
            try:
                text = "".join("+" + l for l in f.read_text(encoding="utf-8").splitlines(True))
            except UnicodeDecodeError:
                text = "(binary file)"
    return redact(text[:limit] + ("\n... (truncated)" if len(text) > limit else ""))


def _inside(repo, path: str) -> str:
    base = Path(os.path.realpath(repo))
    t = Path(os.path.realpath(base / path))
    if t != base and base not in t.parents:
        raise ValueError("that file is outside the repository")
    return str(t.relative_to(base)).replace("\\", "/")


# ---------------------------------------------------------------- operations
def ensure_gitignore(repo) -> bool:
    """Add the managed safety block if missing. Returns True if the file changed."""
    gi = Path(repo) / ".gitignore"
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if "PlasBench safety block" in cur:
        return False
    gi.write_text((cur.rstrip("\n") + "\n\n" if cur.strip() else "") + SAFE_IGNORE, encoding="utf-8")
    return True


def init(repo, branch: str = "main", first_commit: bool = False, message: str = "Initial commit") -> dict:
    repo = valid_repo(str(repo))
    branch = valid_branch(branch)
    if run(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0 and (repo / ".git").exists():
        raise GitError("this folder is already a git repository")
    run(repo, "init", "-b", branch)
    changed = ensure_gitignore(repo)
    res = {"initialised": True, "gitignore_updated": changed}
    if first_commit:
        run(repo, "add", "-A")
        res.update(commit(repo, message))
    return res


def set_identity(repo, name: str, email: str, scope: str = "local"):
    name, email = (name or "").strip(), (email or "").strip()
    if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError("enter your name and a valid e-mail address")
    if scope not in ("local", "global"):
        raise ValueError("scope must be local or global")
    run(repo if scope == "local" else None, "config", f"--{scope}", "user.name", name)
    run(repo if scope == "local" else None, "config", f"--{scope}", "user.email", email)


def stage(repo, paths: list[str] | None):
    """paths None or ['.'] => everything; otherwise those files (each must be inside the repo)."""
    ensure_gitignore(repo) if not (Path(repo) / ".gitignore").exists() else None
    if not paths:
        run(repo, "add", "-A")
    else:
        run(repo, "add", "--", *[_inside(repo, p) for p in paths])


def unstage(repo, paths: list[str] | None):
    has_head = run(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0
    targets = [_inside(repo, p) for p in paths] if paths else ["."]
    if has_head:
        run(repo, "reset", "-q", "HEAD", "--", *targets)
    else:
        run(repo, "rm", "-r", "--cached", "-q", "--", *targets, check=False)


def scan_staged(repo) -> list[dict]:
    """Findings for what is currently staged: [{path, level: block|warn, kind: data|secret|size, why}]."""
    p = run(repo, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", check=False)
    findings = []
    for rel in [x for x in p.stdout.split("\0") if x]:
        norm = rel.replace("\\", "/")
        f = Path(repo) / rel
        exempt = norm.startswith(("test/", "tests/"))   # small synthetic fixtures
        if not exempt:
            for pat, why in DATA_PATTERNS:
                if pat.search(norm):
                    findings.append({"path": rel, "level": "block", "kind": "data", "why": why}); break
        for pat, why in SECRET_PATTERNS:
            if pat.search(norm):
                findings.append({"path": rel, "level": "block", "kind": "secret", "why": why}); break
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE:
            findings.append({"path": rel, "level": "block", "kind": "size", "why": f"{size / 2**20:.0f} MB: over GitHub's 100 MB limit (cannot be overridden)"})
        elif size > WARN_FILE:
            findings.append({"path": rel, "level": "warn", "kind": "size", "why": f"{size / 2**20:.0f} MB is large for a source repository"})
        if size <= 1_000_000 and f.suffix.lower() in (".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sh", ".ps1", ".nf", ".html", ".js", ".csv", ".tsv", ".env", ""):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hit = False
            for pat, why in SECRET_CONTENT:
                if pat.search(text):
                    findings.append({"path": rel, "level": "block", "kind": "secret", "why": f"looks like it contains a {why}"})
                    hit = True
                    break
            if hit:
                continue
            for pat, why in IDENTIFIER_CONTENT:
                if pat.search(text):
                    findings.append({"path": rel, "level": "block", "kind": "patient_data",
                                     "why": f"contains {why}"})
                    break
    return findings


AI_ATTRIBUTION = re.compile(
    r"^\s*(?:co-authored-by:.*(?:claude|anthropic|copilot|chatgpt|openai|gemini|gpt-|llm)|"
    r"(?:\U0001F916\s*)?generated with .*(?:claude|copilot|chatgpt|codex|cursor|ai)\b|"
    r"assisted-by:.*|signed-off-by:.*\b(?:claude|anthropic|copilot|chatgpt)\b).*$",
    re.IGNORECASE)


def strip_ai_attribution(message: str) -> str:
    """Remove AI co-author / 'generated with' trailers.

    Project rule (CONTRIBUTING.md): no AI model is ever recorded as an author or co-author of this
    repository, whatever tool produced the message."""
    kept = [l for l in (message or "").splitlines() if not AI_ATTRIBUTION.match(l)]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept).strip()


def commit(repo, message: str, override: str = "") -> dict:
    ensure_gitignore(repo)          # the safety block is re-checked on every commit, not only at init
    msg = strip_ai_attribution(message)
    if not msg:
        raise ValueError("write a commit message")
    if run(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        raise GitError("nothing is staged: stage some changes first")
    findings = scan_staged(repo)
    blocks = [f for f in findings if f["level"] == "block"]
    hard = [f for f in blocks if f["kind"] == "size"]
    if hard:
        raise GitError("commit blocked: " + "; ".join(f"{f['path']} ({f['why']})" for f in hard))
    if blocks and override != OVERRIDE_SENTENCE:
        raise GitError("commit blocked to protect data and secrets: " + "; ".join(f"{f['path']} ({f['why']})" for f in blocks[:8])
                       + ". Unstage these files, or add them to .gitignore. (To commit them anyway you must type the confirmation sentence.)")
    if not run(repo, "config", "user.name", check=False).stdout.strip() or not run(repo, "config", "user.email", check=False).stdout.strip():
        raise GitError("git does not know who you are yet: save your name and e-mail first")
    run(repo, "commit", "-m", msg)
    h = run(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"committed": h, "warnings": [f for f in findings if f["level"] == "warn"], "overridden": bool(blocks)}


def create_branch(repo, name: str, switch: bool = True):
    n = valid_branch(name)
    run(repo, "check-ref-format", "--branch", n)
    run(repo, "switch", "-c", n) if switch else run(repo, "branch", n)


def checkout(repo, name: str):
    n = valid_branch(name)
    if any(f["staged"] or f["unstaged"] for f in info(repo)["files"] if not f["untracked"]):
        raise GitError("you have uncommitted changes: commit them first (switching branches could overwrite them)")
    run(repo, "switch", n)


def set_remote(repo, name: str, url: str):
    n = valid_branch(name or "origin")
    u = valid_remote_url(url)
    if run(repo, "remote", "get-url", n, check=False).returncode == 0:
        run(repo, "remote", "set-url", n, u)
    else:
        run(repo, "remote", "add", n, u)


def remove_remote(repo, name: str):
    run(repo, "remote", "remove", valid_branch(name))


# ---------------------------------------------------------------- long operations: argument lists for the job engine
# Config knobs that turn "run git in this folder" into "run what the folder says". run() already
# sets them; the long-running network operations built by argv() ran without them, so a hostile
# .git/config (core.fsmonitor, hooks, an ext:: transport) was honoured on fetch/pull/push/clone.
# The credential helper and ssh settings are deliberately left alone: pushing needs them.
SAFE_NET = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "-c", "protocol.ext.allow=never", "-c", "uploadpack.packObjectsHook="]


def argv(op: str, repo, **kw) -> list[str]:
    git = find_git()
    if op in ("fetch", "pull", "push"):
        if not git:
            raise GitError("git is not installed")
        i = info(repo)
        if not i["is_repo"]:
            raise GitError("this folder is not a git repository yet")
        if not i["remotes"]:
            raise GitError("no remote is set: add the repository address first")
        if op == "push":
            if i.get("no_commits"):
                raise GitError("there is nothing to push: make a commit first")
            remote = kw.get("remote") or (i["remotes"][0]["name"])
            branch = i["branch"]
            if not branch or branch == "(detached)":
                raise GitError("you are not on a branch")
            return [git, *SAFE_NET, "-C", str(repo), "push"] + ([] if i["upstream"] else ["-u", remote, branch])
        if op == "pull":
            return [git, *SAFE_NET, "-C", str(repo), "pull", "--ff-only"]
        return [git, *SAFE_NET, "-C", str(repo), "fetch", "--all", "--prune"]
    if op == "clone":
        url = valid_remote_url(kw["url"])
        dest = Path(kw["dest"])
        if not dest.is_absolute():
            raise ValueError("give the full path of the folder to clone into")
        if dest.exists() and any(dest.iterdir()):
            raise ValueError("the destination folder is not empty")
        return [git, *SAFE_NET, "clone", "--", url, str(dest)]
    gh = find_gh()
    if op == "gh_login":
        if not gh:
            raise GitError("GitHub CLI is not installed (https://cli.github.com/)")
        return [gh, "auth", "login", "--web", "--hostname", "github.com", "--git-protocol", "https"]
    if op == "gh_setup_git":
        return [gh, "auth", "setup-git"]
    if op == "gh_create":
        if not gh:
            raise GitError("GitHub CLI is not installed")
        name = (kw.get("name") or "").strip()
        if not re.match(r"^([A-Za-z0-9-]{1,39}/)?[A-Za-z0-9._-]{1,100}$", name):
            raise ValueError("repository name: letters, numbers, . _ - (optionally owner/name)")
        vis = "--public" if kw.get("visibility") == "public" else "--private"
        return [gh, "repo", "create", name, vis, "--source", str(repo), "--remote", "origin"]
    raise ValueError("unknown git operation")


def show(repo, rev: str, limit: int = 200_000) -> str:
    """A commit's message, file list and patch (for the history view)."""
    r = (rev or "").strip()
    if not re.match(r"^[0-9a-fA-F]{4,40}$", r):
        raise ValueError("not a commit id")
    p = run(repo, "show", "--no-color", "--stat", "--patch", "--format=%H%n%an <%ae>%n%ad%n%n%s%n%n%b", r, check=False)
    t = p.stdout
    return redact(t[:limit] + ("\n... (truncated)" if len(t) > limit else ""))


def gh_logged_in() -> bool:
    gh = find_gh()
    if not gh:
        return False
    try:
        return subprocess.run([gh, "auth", "status"], capture_output=True, timeout=30, env=_env(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
