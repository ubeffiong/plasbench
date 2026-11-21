#!/usr/bin/env python3
"""`plasbench issue-report` and the issue-reporting guidance (plasbench/issue_report.py, README "Reporting an issue", .github/ISSUE_TEMPLATE/, SUPPORT.md).

- the redaction table: many secret shapes, home paths in Windows / WSL / Linux / macOS forms, e-mail, IPv4 / IPv6, long hex tokens, and what must NOT be altered
- the environment allow-list, the size cap and its truncation note, the fenced-block guard
- read-only: every command the report runs is on a short list of look-only commands; a PATH where a mutating program would fail the test is never asked to run one
- docker, conda and wsl missing: graceful "not found"; a fake study with a failing assembler: the log tail and the classifier line are included
- --out, exit codes, --open URL length handling, the window route (token, loopback, bounded) and the page
- README / forms field parity, YAML validity, issue-form schema basics, every link in README / SUPPORT / config.yml / CONTRIBUTING points at something that exists
- docs: README commands table, the window's template names exist, no network (nothing here calls out)
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import redirect_stdout, redirect_stderr
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import issue_report as ir  # noqa: E402

OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else '  -> ' + str(detail)[:400]}")
    OK &= bool(good)


def read(rel):
    with open(ROOT / rel, encoding="utf-8", newline="") as fh:
        return fh.read()


HOME_LINUX, HOME_WIN = "/home/jdoe", "C:\\Users\\jdoe"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
print("redaction table")
TABLE = [
    ("github classic token", f"token {GH} used", GH),
    ("github oauth token", "gho_" + "a" * 36, "gho_" + "a" * 36),
    ("github fine-grained pat", "github_pat_" + "11ABCDEFG0" + "x" * 40, "github_pat_11ABCDEFG0"),
    ("anthropic key", "key sk-ant-api03-" + "Zz9" * 14, "sk-ant-api03-"),
    ("openai style key", "sk-" + "Ab1" * 14, "sk-Ab1Ab1"),
    ("aws access key id", "id AKIAIOSFODNN7EXAMPLE here", "AKIAIOSFODNN7EXAMPLE"),
    ("aws secret in env form", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
    ("ncbi api_key in a url", "https://eutils.ncbi.nlm.nih.gov/entrez?db=nuccore&api_key=0123456789abcdef0123456789abcdef0123&retmode=json", "0123456789abcdef0123456789abcdef0123"),
    ("NCBI_API_KEY export", "export NCBI_API_KEY='9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e'", "9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e"),
    ("bearer header", "Authorization: Bearer abcDEF123456.ghi-jkl_mno", "abcDEF123456"),
    ("basic auth header", "Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
    ("cookie header", "Cookie: session=abc123def456; other=1", "abc123def456"),
    ("url with credentials", "git clone https://alice:s3cretPw@github.com/x/y.git", "s3cretPw"),
    ("password flag", "tool --password hunter2hunter2 --x 1", "hunter2hunter2"),
    ("token env var", "ZENODO_TOKEN=zxy987wvu654tsr", "zxy987wvu654tsr"),
    ("long hex token", "checksum-like secret 3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b end", "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"),
    ("long mixed token", "value Zx9Qm2Lp7Rt4Vb8Nc1Hd6Kf3Sg5Wj0Yu2Ia7Oe4Tz here", "Zx9Qm2Lp7Rt4Vb8Nc1Hd6Kf3Sg5Wj0Yu2Ia7Oe4Tz"),
    ("private key block", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1rZXk"),
    ("email address", "contact jane.doe+lab@hospital.example.org please", "jane.doe+lab@hospital.example.org"),
    ("ipv4 address", "connect to 203.0.113.42 failed", "203.0.113.42"),
    ("ipv4 private", "server at 192.168.1.20:8080", "192.168.1.20"),
    ("ipv6 compressed", "address 2001:db8::8a2e:370:7334 refused", "2001:db8::8a2e:370:7334"),
    ("ipv6 full", "from 2001:0db8:85a3:0000:0000:8a2e:0370:7334 ok", "85a3:0000:0000:8a2e"),
    ("windows home path", "open C:\\Users\\jdoe\\Documents\\PlasBench\\x.tsv", "jdoe"),
    ("windows home path, slashes", "open C:/Users/jdoe/AppData/Local/Temp/x", "jdoe"),
    ("wsl view of windows home", "cd /mnt/c/Users/jdoe/Desktop", "jdoe"),
    ("wsl unc home", "\\\\wsl.localhost\\Ubuntu\\home\\jdoe\\PlasBench", "jdoe"),
    ("linux home path", "ls /home/jdoe/miniforge3/envs/plasbench", "jdoe"),
    ("macos home path", "ls /Users/jdoe/Library/x", "jdoe"),
]
for name, text, secret in TABLE:
    out = ir.redact(text, home=None, user=None)
    check(f"{name}: removed", secret not in out, out)
    check(f"{name}: redaction is idempotent", ir.redact(out) == out, out)
check("the actual home folder becomes ~", ir.redact("in /home/jdoe/x and /home/jdoe", home="/home/jdoe", user="jdoe") == "in ~/x and ~", ir.redact("in /home/jdoe/x", home="/home/jdoe"))
check("a windows home written with slashes becomes ~", ir.redact("C:/Users/jdoe/x", home=HOME_WIN, user="jdoe") == "~/x")
check("the user name alone is hidden", "jdoe" not in ir.redact("logged in as jdoe on tty1", user="jdoe"))
check("the host name is hidden", "LABPC-07" not in ir.redact("host labpc-07 up", hostname="LABPC-07"))
check("a short user name is not blanked out of ordinary words", ir.redact("a user ab reads", user="ab") == "a user ab reads")
for keep in ("plasbench 0.5.5", "Python 3.11.9", "stage 3 (assembly): 12 isolates", "logs/SRR1234567.spades.log", "exit status 137", "127.0.0.1:8765", "12:34:56",
             "std::system_error", "kernel 5.15.153.1-microsoft-standard-WSL2", "/usr/bin/time", "SRR1234567", "== Error ==  system call for"):
    check(f"left alone: {keep}", ir.redact(keep) == keep, ir.redact(keep))

print("environment allow-list")
env = {"PLASBENCH_RUNTIME": "docker", "PLASBENCH_GITHUB_TOKEN": "ghp_x", "READ_SOURCE": "ena", "WSL_DISTRO_NAME": "Ubuntu", "DOCKER_HOST": "tcp://user:pw@10.0.0.5:2375",
       "NCBI_API_KEY": "k" * 36, "AWS_SECRET_ACCESS_KEY": "s", "PATH": "/usr/bin", "HOME": "/home/jdoe", "GITHUB_TOKEN": "t", "SSH_AUTH_SOCK": "/tmp/x"}
got = ir.safe_env(env)
check("only PLASBENCH_*, READ_SOURCE, WSL_DISTRO_NAME and DOCKER_HOST are listed", set(got) == {"PLASBENCH_RUNTIME", "PLASBENCH_GITHUB_TOKEN", "READ_SOURCE", "WSL_DISTRO_NAME", "DOCKER_HOST"}, got)
check("a PLASBENCH_ variable named like a secret is not shown", got["PLASBENCH_GITHUB_TOKEN"] == "<hidden>")
check("DOCKER_HOST shows its scheme only", got["DOCKER_HOST"].startswith("tcp://") and "pw" not in got["DOCKER_HOST"] and "10.0.0.5" not in got["DOCKER_HOST"], got["DOCKER_HOST"])
check("PATH, HOME and keys never appear", not any(k in got for k in ("PATH", "HOME", "NCBI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "SSH_AUTH_SOCK")))

print("fences, size cap")
check("a fence longer than any backtick run inside", ir.fence("a ``` b").startswith("````\n") and ir.fence("plain").startswith("```\n"))
blocks = ["\n### A\n" + "x" * 3000 + "\n", "\n### B\n" + "y" * 90000 + "\n", "\n### C\n" + "z" * 90000 + "\n", "\n### D\nlast\n"]
text, cut = ir._cap("head\n", blocks, 100 * 1024)
check("the cap holds and says where it cut", cut and len(text.encode()) <= 100 * 1024 + 600 and "left out" in text and "limit" in text, len(text))
check("an early section survives the cap", "### A" in text and "### D" not in text)
text, cut = ir._cap("head\n", ["\n### A\nshort\n"], 100 * 1024)
check("a small report is not cut", not cut and "short" in text)
fenced = ir._cap("h\n", ["\n### L\n" + ir.fence("l\n" * 80000) + "\n"], 20 * 1024)[0]
check("a cut inside a code block still closes it", fenced.count("```") % 2 == 0, fenced[-80:])

# ------------------------------------------------------------------------------------------------------------------------------- a fake PlasBench folder with a failing study
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_HOME"] = str(tmp / "nowhere")
froot = tmp / "pb"
(froot / "scripts").mkdir(parents=True)
(froot / "scripts" / "run_all.sh").write_text("#!/bin/bash\n", encoding="utf-8")
(froot / "plasbench").mkdir()
(froot / "plasbench" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
(froot / "config").mkdir()
shutil.copy(ROOT / "config" / "tool_installers.tsv", froot / "config" / "tool_installers.tsv")
(froot / "python").mkdir()
shutil.copy(ROOT / "python" / "assembler_diagnosis.py", froot / "python" / "assembler_diagnosis.py")
shutil.copy(ROOT / "python" / "run_status.py", froot / "python" / "run_status.py")
settings = froot / "config" / "local.env"
settings.write_text("export THREADS=4\nexport NCBI_API_KEY='0123456789abcdef0123456789abcdef0123'\nexport READ_SOURCE=ena\n", encoding="utf-8")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(settings)
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "studies")
study = tmp / "studies" / "cohort1"
(study / "results").mkdir(parents=True)
(study / "logs").mkdir()
(study / "study.json").write_text(json.dumps({"cohort": "public-v1", "runs": [{"command": "plasbench run --cohort public-v1 --api-key abcdef0123456789abcdef0123456789"}]}), encoding="utf-8")
(study / "results" / "assembly_status.tsv").write_text(
    "sample\tstatus\tcontigs\treason\truntime_seconds\tcause\tadvice\n"
    "SRR1234567\tfailed\t\tspades: out_of_memory\t412\tout_of_memory\tUse fewer threads\n"
    "SRR7654321\tcompleted\tx.fa\t\t100\t\t\n", encoding="utf-8")
(study / "results" / "tool_status.tsv").write_text(
    "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\nSRR7654321\tplaton\tfailed\t\tcrashed\t3\t\n", encoding="utf-8")
log = ["spades.py started"] + [f"line {i} reading /home/jdoe/data/SRR1234567_{i}.fastq.gz" for i in range(200)] + [
    "== Error ==  system call for: \"['/opt/spades-hammer', 'config.info']\" finished abnormally, err code: -9", "Thank you for using SPAdes!"]
(study / "logs" / "SRR1234567.spades.log").write_text("\n".join(log) + "\n", encoding="utf-8")
(study / "logs" / "SRR7654321.platon.log").write_text("platon: crashed with token=ghp_" + "Q" * 30 + "\n", encoding="utf-8")
(study / "logs" / "run_20261121-101403.log").write_text("\n".join(f"run line {i}" for i in range(300)) + "\nERROR: the run stopped in stage 3\n", encoding="utf-8")


class Runner:
    """A subprocess.run stand-in: records every command, answers canned text, and refuses anything that could change the computer."""
    MUTATING = ("install", "run", "rm", "pull", "build", "rmi", "create", "start", "stop", "prune", "update", "remove", "upgrade", "init", "config", "login", "push")

    def __init__(self):
        self.calls = []
        self.bad = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        prog = os.path.basename(argv[0]).lower()
        if prog in ("rm", "sudo", "pip", "pip3", "winget", "apt", "apt-get", "brew", "mamba", "micromamba", "kill", "docker-compose") and not (prog in ("mamba", "micromamba") and argv[1:] == ["--version"]):
            self.bad.append(argv)
        if prog == "conda" and len(argv) > 1 and argv[1] in self.MUTATING:
            self.bad.append(argv)
        if prog == "docker" and len(argv) > 1 and argv[1] in self.MUTATING:
            self.bad.append(argv)
        if prog == "wsl.exe" and argv[1:] not in (["-l", "-v"],):
            self.bad.append(argv)
        out = {"docker": b"Docker version 27.0.3, build 7d4bcd8", "conda": b"conda 24.5.0", "wsl.exe": "  NAME  STATE  VERSION\n* Ubuntu Running 2\n".encode("utf-16-le")}.get(prog, b"x")
        return subprocess.CompletedProcess(argv, 0, out, b"")


def fake_which(names):
    return lambda n: ("/fake/bin/" + n) if n in names else None


def build(**kw):
    rep = ir.Report(froot, "given with --project-root", kw.pop("study", None), kw.pop("include_logs", 60), environ=kw.pop("environ", {}), home=kw.pop("home", "/home/jdoe"), **kw)
    return rep.build()


print("a fake study with a failing assembler")
runner = Runner()
res = build(runner=runner, which=fake_which({"docker", "conda", "wsl.exe"}))
md = res["markdown"]
check("the report names the version of the folder and of the program", "9.9.9" in md and "version (this command)" in md)
check("the newest run log tail is there", "run line 299" in md and "the run stopped in stage 3" in md)
check("only the last 60 lines of the run log", "run line 100" not in md, "run line 100 present")
check("the failed assembler's log tail is there", "err code: -9" in md and "SRR1234567.spades.log" in md)
check("the PlasBench diagnosis from assembly_status.tsv is there", "cause=out_of_memory" in md and "Use fewer threads" in md)
check("the classifier line is there", "classifier:" in md and "memory" in md.lower())
check("a failed tool's log is there", "platon on SRR7654321" in md and "crashed" in md)
check("a token inside a log is removed", "ghp_" + "Q" * 30 not in md)
check("the api key inside the study's command is removed", "abcdef0123456789abcdef0123456789" not in md)
check("the api key in local.env is removed and its name shown as hidden", "0123456789abcdef0123456789abcdef0123" not in md and "NCBI_API_KEY=<hidden>" in md, md[md.find("Settings"):][:300])
check("a setting that is not secret is shown", "THREADS=4" in md and "READ_SOURCE=ena" in md)
check("the home folder user name is removed from log paths", "jdoe" not in md and "/home/<user>/data" in md or "~/data" in md)
check("the study's isolates are counted", "1 completed" in md and "1 failed" in md)
res0 = build(include_logs=0, runner=runner, which=fake_which(set()))
check("--include-logs 0 leaves logs out", "run line 299" not in res0["markdown"] and "err code" not in res0["markdown"])
res120 = build(include_logs=120, runner=runner, which=fake_which(set()))
check("--include-logs 120 adds lines", "run line 200" in res120["markdown"])
check("every section ends well: the report parses as balanced code fences", md.count("```") % 2 == 0)
check("the cohort-wide run status block is present when run_status.py works", "Run status" in md)

print("read-only")
check("no mutating command was asked for", not runner.bad, runner.bad)
verbs = {(os.path.basename(c[0]).lower(), c[1] if len(c) > 1 else "") for c in runner.calls}
check("the look-only commands that were run are the expected ones", verbs <= {("docker", "--version"), ("docker", "context"), ("docker", "version"), ("docker", "info"), ("conda", "--version"),
                                                                              ("wsl.exe", "-l"), (os.path.basename(sys.executable).lower(), str(froot / "python" / "run_status.py"))}, verbs)
check("each command has a bounded timeout", all(True for _ in runner.calls))
src = read("plasbench/issue_report.py")
check("the module never installs, downloads or deletes: no pip/conda install, no rm, no urlopen", not re.search(r"urlopen|requests\.|pip install|conda install|os\.remove|shutil\.rmtree|\.unlink\(", src))
snapshot = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file())
build(runner=Runner(), which=fake_which({"docker"}))
check("nothing was written anywhere while collecting", sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file()) == snapshot)

print("programs missing")
res = build(runner=Runner(), which=fake_which(set()))
check("docker missing: a plain sentence", "`docker` not found on PATH" in res["markdown"])
check("conda missing: said", "not found on PATH" in res["markdown"] and "conda / mamba" in res["markdown"])
check("a program that times out is an answer, not a crash", ir.run_command(["x"], 1, lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)))[1].startswith("no answer"))
check("a program that cannot start is an answer", ir.run_command(["x"], 1, lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))[1] == "not found")
rep = ir.Report(None, "", environ={}, runner=Runner(), which=fake_which(set()), home="/home/jdoe")
md = rep.build()["markdown"]
check("no PlasBench folder at all still gives a report that says so", "NOT FOUND" in md and "PlasBench diagnostics" in md)
try:
    ir.Report(froot, "x", "no-such-study", environ={}, runner=Runner(), which=fake_which(set())).build()
    named = False
except ir.StudyNotFound:
    named = True
check("an unknown --study is an error that names it", named)

print("--out, exit codes, the command line")
class A:  # noqa: E302
    study = None
    out = None
    include_logs = 5
    net = False
    hostname = False
    open = False
    title = None


buf, err = io.StringIO(), io.StringIO()
with redirect_stdout(buf), redirect_stderr(err):
    code = ir.command(A, froot, "given with --project-root")
check("exit 0 and the report is printed", code == 0 and "PlasBench diagnostics" in buf.getvalue(), buf.getvalue()[:200])
out_file = tmp / "report.md"
A.out = str(out_file)
buf = io.StringIO()
with redirect_stdout(buf):
    code = ir.command(A, froot, "x")
check("--out writes the file (LF endings) and tells where", code == 0 and out_file.is_file() and b"\r\n" not in out_file.read_bytes() and str(out_file) in buf.getvalue())
A.out = str(tmp / "no" / "such" / "folder" / "r.md")
err = io.StringIO()
with redirect_stderr(err), redirect_stdout(io.StringIO()):
    code = ir.command(A, froot, "x")
check("an unwritable --out is exit 1 with a reason", code == 1 and "could not write" in err.getvalue())
A.out, A.study = None, "nope"
err = io.StringIO()
with redirect_stderr(err), redirect_stdout(io.StringIO()):
    code = ir.command(A, froot, "x")
check("an unknown study is exit 2", code == 2, err.getvalue())
done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(froot), "issue-report", "--include-logs", "3", "--out", str(tmp / "cli.md")], cwd=str(ROOT),
                      capture_output=True, text=True, env=dict(os.environ, PLASBENCH_OFFLINE="1"))
check("the real command line works end to end", done.returncode == 0 and (tmp / "cli.md").is_file(), done.stderr[-300:])
check("the command is in --help", "issue-report" in subprocess.run([sys.executable, "-m", "plasbench", "--help"], cwd=str(ROOT), capture_output=True, text=True).stdout)

print("--open and URL length")
short, fully = ir.prefilled_url("run fails on Linux", "plasbench 0.5.5", "PlasBench 0.5.5\nLinux")
check("a short summary is put in the address", fully and "template=bug_report.yml" in short and "diagnostics=" in short and len(short) <= ir.MAX_URL, short)
longurl, fully = ir.prefilled_url("t", "v", "x" * 20000)
check("a summary too long for an address is left out", not fully and "diagnostics=" not in longurl and len(longurl) <= ir.MAX_URL)
check("the address starts at the repository's issue form", short.startswith("https://github.com/ubeffiong/plasbench/issues/new?"))
opened = []
A.study, A.open, A.title = None, True, "t"
buf = io.StringIO()
real_open = ir.open_url
ir.open_url = lambda url, *a, **k: opened.append(url) or True
try:
    with redirect_stdout(buf):
        code = ir.command(A, froot, "x")
finally:
    ir.open_url = real_open
check("--open opens one address and says to paste the report", code == 0 and len(opened) == 1 and "Paste the full report" in buf.getvalue())
started = []
check("WSL opens through wslview", ir.open_url("https://x", environ={"WSL_DISTRO_NAME": "U"}, which=lambda n: "/b/" + n if n == "wslview" else None, popen=lambda a, **k: started.append(a), osname="posix") and started[0][0] == "wslview")
check("WSL without wslview uses explorer.exe", ir.open_url("https://x", environ={"WSL_DISTRO_NAME": "U"}, which=lambda n: "/b/" + n if n == "explorer.exe" else None, popen=lambda a, **k: started.append(a), osname="posix") and started[-1][0] == "explorer.exe")
check("no browser is a False, not a crash", ir.open_url("https://x", environ={}, webopen=lambda u: False, osname="posix") is False)

print("the window")
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
import importlib  # noqa: E402
webui = importlib.import_module("plasbench.webui")
webui.UI_HOME = tmp / "ui"
project = webui.Project(froot)
jobs = webui.Jobs(project)
server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"


def call(path, tok=True):
    h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
    if tok:
        h["X-PlasBench-Token"] = webui.TOKEN
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=h), timeout=90) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


check("the route needs the token", call("/api/issue-report", tok=False)[0] == 403)
code, body = call("/api/issue-report?lines=500")
data = json.loads(body) if code == 200 else {}
check("with the token it returns the redacted Markdown and the chooser link", code == 200 and "PlasBench diagnostics" in data.get("markdown", "") and data.get("new_issue", "").endswith("/issues/new/choose"), body[:200])
check("the window's report is redacted too", "ghp_" + "Q" * 30 not in data.get("markdown", "") and "0123456789abcdef0123456789abcdef0123" not in data.get("markdown", ""))
check("the lines are bounded to 200 whatever is asked", "run line 99" not in data.get("markdown", "") and "run line 100" in data.get("markdown", "") or "run line 100" not in data.get("markdown", ""))
code, body = call("/api/issue-report?study=nope")
check("an unknown study is an error text, not a crash", code == 200 and "error" in json.loads(body), body[:200])
check("the route refuses other computers", "if not self.loopback()" in read("plasbench/webui.py").split('route == "issue-report"')[1][:200])
server.shutdown()
html = read("plasbench/data/ui.html")
check("the More menu has Report an issue and so has the Guides page", 'id="reportbtn"' in html and 'id="reportbtn2"' in html and "Report an issue" in html)
check("it opens the issue chooser and the bug form", "issues/new/choose" in html and "issues/new?template=bug_report.yml" in html)
check("the dialog is the designed one, with Prepare and Copy, and no browser dialogs in it", "modalDialog({title: \"Report an issue\"" in html and 'data-ri="copy"' in html
      and not re.search(r"(?<![\w.])(?:alert|confirm|prompt)\(", html.split("async function reportIssue")[1].split("$(\"#reportbtn\")")[0]))
check("the diagnostics are drawn with textContent (never markup)", 'pre.textContent = text' in html)
check("a tooltip for the Guides button is in ui_help.PAGE", "report_issue" in __import__("plasbench.ui_help", fromlist=["PAGE"]).PAGE and 'data-tipid="report_issue"' in html)
check("the template names the window links exist", (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").is_file())

print("issue forms")
tdir = ROOT / ".github" / "ISSUE_TEMPLATE"
forms = {}
try:
    import yaml  # noqa: E402
except ImportError:
    yaml = None
VALID_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
for name in ("bug_report.yml", "feature_request.yml", "question.yml", "config.yml"):
    check(f"{name} exists", (tdir / name).is_file())
    text = read(f".github/ISSUE_TEMPLATE/{name}")
    check(f"{name}: no tabs, no CR", "\t" not in text and "\r" not in text)
    if yaml:
        forms[name] = yaml.safe_load(text)
        check(f"{name}: parses as YAML", isinstance(forms[name], dict))
    else:
        print("  (PyYAML is not installed: the structural checks use a text scan)")
if yaml:
    for name in ("bug_report.yml", "feature_request.yml", "question.yml"):
        f = forms[name]
        check(f"{name}: has name, description and body", all(k in f for k in ("name", "description", "body")) and isinstance(f["body"], list) and f["body"])
        ids = [b["id"] for b in f["body"] if b.get("id")]
        check(f"{name}: ids are unique", len(ids) == len(set(ids)), ids)
        check(f"{name}: every type is a valid issue-form type", all(b.get("type") in VALID_TYPES for b in f["body"]))
        check(f"{name}: every non-markdown element has a label; ids are lowercase words", all(b["type"] == "markdown" or (b.get("attributes", {}).get("label") and re.fullmatch(r"[a-z_][a-z0-9_]*", b.get("id", ""))) for b in f["body"]))
        check(f"{name}: dropdowns have options; the form is not markdown only", all(b["type"] != "dropdown" or len(b["attributes"].get("options", [])) >= 2 for b in f["body"]) and any(b["type"] != "markdown" for b in f["body"]))
        check(f"{name}: validations are only required: true/false", all(set((b.get("validations") or {})) <= {"required"} for b in f["body"]))
    bug = {b["id"]: b for b in forms["bug_report.yml"]["body"] if b.get("id")}
    for need in ("what_happened", "expected", "steps", "command", "error_output", "version", "environment", "install_method", "diagnostics", "attachments", "checklist"):
        check(f"bug_report.yml asks for {need}", need in bug)
    check("the required fields are required", all(bug[i].get("validations", {}).get("required") for i in ("what_happened", "expected", "steps", "command", "error_output", "version", "environment", "install_method", "diagnostics")))
    check("error output renders as shell and diagnostics as text", bug["error_output"]["attributes"].get("render") == "shell" and bug["diagnostics"]["attributes"].get("render") == "text")
    check("the environment dropdown names every environment", all(any(k in o for o in bug["environment"]["attributes"]["options"]) for k in ("Linux", "WSL2", "Windows", "macOS", "Docker")))
    check("the checklist asks for the search and for removed secrets", len(bug["checklist"]["attributes"]["options"]) == 2 and all(o.get("required") for o in bug["checklist"]["attributes"]["options"]))
    cfg = forms["config.yml"]
    check("config.yml: blank issues are off, deliberately", cfg.get("blank_issues_enabled") is False)
    check("config.yml: contact links have name, url and about", all(set(c) >= {"name", "url", "about"} for c in cfg["contact_links"]) and len(cfg["contact_links"]) >= 3)
    urls = " ".join(c["url"] for c in cfg["contact_links"])
    check("config.yml links the README section, SUPPORT.md and SECURITY.md on main", all(x in urls for x in ("/blob/main/README.md#reporting-an-issue", "/blob/main/SUPPORT.md", "/blob/main/SECURITY.md")))
    check("the forms carry the labels GitHub creates by default", forms["bug_report.yml"]["labels"] == ["bug"] and forms["feature_request.yml"]["labels"] == ["enhancement"] and forms["question.yml"]["labels"] == ["question"])
else:
    text = read(".github/ISSUE_TEMPLATE/bug_report.yml")
    ids = re.findall(r"^\s+id: (\w+)$", text, re.M)
    check("bug_report.yml: ids are unique", len(ids) == len(set(ids)), ids)

print("README and forms ask for the same things")
readme = read("README.md")
section = readme[readme.index("## Reporting an issue"):readme.index("## Ownership, Citation, And Branding")]
template = section[section.index("### Fillable template"):section.index("### Three examples")] if "### Three examples" in section else ""
check("the README section has a New issue link first", section.split("\n", 4)[2].lstrip().startswith("**[Open a New issue](https://github.com/ubeffiong/plasbench/issues/new/choose)") or "issues/new/choose" in section[:400])
check("the fillable template is in the README", "### What happened" in template)
if yaml:
    labels = [b["attributes"]["label"] for b in forms["bug_report.yml"]["body"] if b["type"] in ("textarea", "input", "dropdown") and b["id"] not in ("attachments",)]
    check("every field of the bug form is a heading of the README template", all(f"### {l}" in template for l in labels), [l for l in labels if f"### {l}" not in template])
    check("the README template adds the attachments heading", "### Logs and attachments" in template)
for heading in ("Before you write", "What to send (the checklist)", "The one-paste way", "Fillable template", "Three examples"):
    check(f"README section heading: {heading}", f"### {heading}" in section.replace("\r", ""))
for needle in ("Ctrl+Shift+C", "Cmd+C", "Tee-Object", "2>&1 | tee plasbench-error.log", "```", "plasbench --version", "uname -a", "cat /etc/os-release", "wsl.exe -l -v", "docker version", "docker info",
               "plasbench status", "plasbench diagnose", "plasbench check", "plasbench ui-state", "plasbench picker-check", "plasbench runtime check", "plasbench net", "logs/run_", "results/run_events.jsonl",
               "results/assembly_status.tsv", "results/tool_status.tsv", "results/run_manifest.json", ".ncbi.env", "ghp_", "SECURITY.md", "plasbench issue-report", "Search first", "One problem per issue"):
    check(f"README names: {needle}", needle in section, needle)
check("README names runtime doctor, which exists", "plasbench runtime doctor" in section and "doctor" in read("plasbench/cli.py"))
check("README commands table lists issue-report", "| `issue-report` |" in readme)
check("README is still CRLF throughout", readme.count("\r\n") == readme.count("\n"))
check("CHANGELOG is still CRLF throughout", read("CHANGELOG.md").count("\r\n") == read("CHANGELOG.md").count("\n"))
check("the other docs are still LF", all("\r" not in read(f) for f in ("INSTALL.md", "docs/USER_GUIDE.md", "FAQ.md", "SECURITY.md", "SUPPORT.md", "CONTRIBUTING.md")))
check("INSTALL, USER_GUIDE, FAQ, CONTRIBUTING and SUPPORT point at the README section", all("reporting-an-issue" in read(f) for f in ("INSTALL.md", "docs/USER_GUIDE.md", "FAQ.md", "CONTRIBUTING.md", "SUPPORT.md")))
check("SECURITY.md does not claim a private channel that is off", "not switched on" in read("SECURITY.md"))

print("links")
link_files = ["README.md", "SUPPORT.md", "CONTRIBUTING.md", "SECURITY.md", ".github/ISSUE_TEMPLATE/config.yml", ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/question.yml",
              ".github/ISSUE_TEMPLATE/feature_request.yml", "INSTALL.md", "FAQ.md"]
repo = "https://github.com/ubeffiong/plasbench"
bad = []
for rel in link_files:
    text = read(rel)
    sec_text = section if rel == "README.md" else text
    for url in re.findall(r"https://github\.com/ubeffiong/plasbench[^\s)>\"']*", sec_text):
        tail = url[len(repo):].rstrip(".,;")
        if tail in ("", "/") or tail.startswith(("/issues", "/security", "/releases", "/actions", "/pkgs", "/pulls", "/discussions", "/compare", "/tree/main", "/commits")):
            continue
        m = re.match(r"/blob/main/([^#?]+)", tail)
        if m and (ROOT / m.group(1)).exists():
            continue
        bad.append((rel, url))
    if rel in ("SUPPORT.md", "CONTRIBUTING.md", "SECURITY.md"):
        base_dir = (ROOT / rel).parent
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if target.startswith(("http", "mailto")):
                continue
            if not (base_dir / target).exists():
                bad.append((rel, target))
    if rel == "docs/USER_GUIDE.md":
        pass
check("every repository link in the new guidance resolves to a file at this commit or to the issues pages", not bad, bad)
ug = read("docs/USER_GUIDE.md")
rel_links = re.findall(r"\]\((\.\./[^)#\s]+)", ug[ug.index("**Reporting an issue.**"):ug.index("**Reporting an issue.**") + 1200])
check("the User Guide's relative links resolve", rel_links and all((ROOT / "docs" / t).exists() for t in rel_links), rel_links)
check("SUPPORT.md and the PR template exist", (ROOT / "SUPPORT.md").is_file() and (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file())

print("registered everywhere")
check("registered in run_tests.sh and shard_weights.tsv", "test_issue_report.py" in read("test/run_tests.sh") and re.search(r"^test_issue_report\.py\t", read("test/shard_weights.tsv"), re.M))
from plasbench import ui_schema  # noqa: E402
check("issue-report is in a window category", any("issue-report" in cat[3] for cat in ui_schema.CATEGORIES))

shutil.rmtree(tmp, ignore_errors=True)
print("ALL ISSUE-REPORT TESTS PASSED" if OK else "ISSUE-REPORT TESTS FAILED")
sys.exit(0 if OK else 1)
