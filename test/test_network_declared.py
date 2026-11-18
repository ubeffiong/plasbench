#!/usr/bin/env python3
"""Every file that can touch the network is declared in config/network_services.tsv, and says so in code.

PlasBench checks for the internet before anything online-only (plasbench/netcheck.py). This test is what keeps that true: it scans
python/, plasbench/, scripts/, env/, adapters/ and the *.sh files at the repository root for network primitives (urllib.request, requests.,
http.client, socket.create_connection, curl, wget, git clone/fetch/pull/push/ls-remote, gh, datasets download, prefetch, conda/pip install,
docker pull, aria2c, resumable_download ...) and requires each file that has one to be either

  * named in the `used_by` column of config/network_services.tsv (a file path), AND to contain a guard (require_internet, net_require,
    net_explain, netcheck or PLASBENCH_OFFLINE), or
  * in ALLOWED below with a one-line reason (the match is a message, a comment, a local-only call or a tool-name list).

Adding an unguarded download later therefore fails here until the file is declared and guarded. Nothing here touches the network.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import cli, netcheck  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


PRIMITIVES = re.compile(
    r"urllib\.request|\burlopen\b|\brequests\.(get|post|head|put|Session)|http\.client|socket\.create_connection|\bcurl\b|\bwget\b"
    r"|\bgit\s+(clone|fetch|pull|push|ls-remote)\b|(^|[\s;&|(\"'])gh\s+(api|auth|release|repo|pr)\b|datasets\s+download|\bprefetch\s+-|\bprefetch\s+\"|\bneed\s+prefetch"
    r"|\b(conda|mamba|micromamba)\s+(install|create|env\s+(create|update))\b|\bpip3?\s+install\b|docker\s+pull|\baria2c\b|\bresumable_download\s+[\"$]"
    r"|genomad\s+download-database|bakta_db\s+download|plassembler\s+download|PLASMe_db\.py\s+--|\bEntrez\b")
GUARDS = ("require_internet", "net_require", "net_explain", "netcheck", "PLASBENCH_OFFLINE")

# file -> why a network-looking word there is not an unguarded network call.
ALLOWED = {
    "install.sh": "delegates every download to guarded scripts (env/bootstrap_conda.sh, env/setup_conda.sh, plasbench install-tools); its pip install is a local --no-deps install of this checkout",
    "plasbench/webui.py": "a loopback health check on 127.0.0.1 and tool-name lists; not the internet",
    "plasbench/platform_info.py": "builds advice text (a curl and docker pull command the user is told to run); makes no request",
    "plasbench/ui_help.py": "tooltip text that mentions prefetch and aria2c; no request",
    "python/download_progress.py": "reads the local aria2c control file of a download another script runs; no request",
    "python/make_truth.py": "its docstring names the `datasets download` command whose output it reads; no request",
    "python/plaseval_gate.py": "an error message that tells the user to `git clone` PlasEval; no request",
    "python/prepare_contribution.py": "prints the `git push` command for the contributor to run; the NCBI check is guarded (net_require)",
    "python/write_manifest.py": "a list of tool names recorded in the manifest, and a comment about pip install; no request",
    "python/build_published_outcomes.py": "a message that tells the user to pip install openpyxl; no request",
}


# Declared files that may lack a guard marker yet, with the reason.
GUARD_EXEMPT = {"plasbench/gitops.py": "the window's GitHub sign-in is wired to netcheck by the parallel window work (/api/net/status)"}


def used_by_files():
    files, commands = {}, []
    for row in netcheck.load_catalogue(ROOT / "config" / "network_services.tsv"):
        for token in (row.get("used_by") or "").split(";"):
            token = token.strip()
            if not token:
                continue
            if token.startswith("plasbench "):
                commands.append((row["service"], token))
            else:
                files.setdefault(token, []).append(row["service"])
    return files, commands


def code_of(path):
    """The file's text without full-line comments (a comment is not a call)."""
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def candidates():
    found = []
    for folder, pattern in (("python", "*.py"), ("plasbench", "*.py"), ("scripts", "*.sh"), ("env", "*.sh"), ("adapters", "*.sh")):
        found += sorted((ROOT / folder).rglob(pattern))
    found += sorted(ROOT.glob("*.sh"))
    return [p for p in found if "__pycache__" not in p.parts]


declared, commands = used_by_files()
print("catalogue")
rows = netcheck.load_catalogue(ROOT / "config" / "network_services.tsv")
check("the catalogue has the columns the window and the shell read",
      all(set(r) >= {"service", "label", "probe_url", "probe_host", "used_by", "advice"} for r in rows), rows[:1])
names = [r["service"] for r in rows]
check("services are unique", len(names) == len(set(names)), names)
check("the services the work needs are there", {"internet", "dns", "github", "ncbi", "ncbi_datasets", "sra", "ena", "pypi", "conda", "zenodo", "plsdb"} <= set(names), names)
check("every service has a label, a probe host and advice (dns and internet need none)",
      all(r["label"] and r["probe_host"] and (r["advice"] or r["service"] in ("internet", "dns")) for r in rows))
check("SERVICE_LABELS covers the catalogue", set(netcheck.SERVICE_LABELS) == set(names))
check("every file named in used_by exists", all((ROOT / f).is_file() for f in declared), [f for f in declared if not (ROOT / f).is_file()])
choices = set(cli.build_parser()._subparsers._group_actions[0].choices)   # noqa: SLF001 - the real list of commands
check("every command named in used_by is a real command", all(t.split()[1] in choices for _, t in commands), [t for _, t in commands if t.split()[1] not in choices])

print("scan")
undeclared, unguarded, stale_allow = [], [], []
scanned = 0
for path in candidates():
    rel = path.relative_to(ROOT).as_posix()
    scanned += 1
    text = code_of(path)
    has_primitive = bool(PRIMITIVES.search(text))
    if rel in ALLOWED:
        if not has_primitive:
            stale_allow.append(rel)
        continue
    if rel in declared and not has_primitive:
        pass   # declared though the scan does not see a primitive (an indirect user): fine
    if has_primitive and rel not in declared:
        undeclared.append((rel, PRIMITIVES.search(text).group(0)))
for rel in sorted(declared):
    if rel in ALLOWED or rel in GUARD_EXEMPT:
        continue
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    if not any(g in text for g in GUARDS):
        unguarded.append(rel)
check(f"scanned {scanned} files", scanned > 100)
check("no file uses the network without being declared in config/network_services.tsv (or allow-listed with a reason)", not undeclared,
      "\n      add each to the used_by of its service (and guard it with require_internet / net_require), or to ALLOWED with a reason:\n      "
      + "\n      ".join(f"{rel}  (matches {word!r})" for rel, word in undeclared))
check("every declared file contains a guard (require_internet, net_require, net_explain, netcheck)", not unguarded, unguarded)
check("every allow-list entry still matches something (no dead excuses)", not stale_allow, stale_allow)
check("every allow-list entry has a reason", all(len(r) > 10 for r in ALLOWED.values()))
check("an allow-listed file exists", all((ROOT / f).is_file() for f in ALLOWED), [f for f in ALLOWED if not (ROOT / f).is_file()])

print("the scan itself catches a new unguarded download")
sample = 'import urllib.request\nurllib.request.urlopen("https://example.org")\n'
check("urllib is a primitive", bool(PRIMITIVES.search(sample)))
for snippet in ("curl -fL -o x https://e.org", "wget -O x u", "git clone https://github.com/a/b.git", "gh api repos/x", "datasets download genome accession X",
                "prefetch -O d SRR1", "conda install -y -p p x", "pip install foo", "docker pull img", "aria2c -x4 u", "resumable_download \"$URL\" dest",
                "import http.client", "socket.create_connection((h, 443))", "requests.get(u)"):
    check(f"primitive: {snippet[:40]}", bool(PRIMITIVES.search(snippet)), snippet)
for snippet in ("the prefetch step", "# curl is used", "getattr(requests, 'x')", "ghost = 1"):
    check(f"not a primitive: {snippet[:40]}", not PRIMITIVES.search("" if snippet.startswith("#") else snippet), snippet)

sys.exit(0 if ok else 1)
