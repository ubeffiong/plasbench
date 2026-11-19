#!/usr/bin/env python3
"""Add your own tool, end to end, against the real code with tiny fake tools (no tool is installed, nothing leaves this computer).

test/test_add_tool_e2e.sh runs this driver and then stage 4 and the scoring on a fake cohort. This file covers the user path up to the run:

  conversions   one fake tool per task/format combination, run as the manifest says and converted by python/user_tool_adapter.py:
                binning (contig_bins), classification (contig_labels), plasmid FASTA reassembly, a multi-task manifest (one command, two
                rows <name> and <name>__classification), format = auto with an unambiguous and an ambiguous output (ambiguity is an
                error, never a guess), several formats at once
  sources       [install] method = local (copy, link), url (a real HTTPS server on this computer with a throw-away certificate: correct
                sha256, wrong sha256, no sha256, http and file URLs, a zip-slip archive, a symlink escape, the size cap, {src} in the
                command), a git source at a pinned commit (served by that same HTTPS server from a bare repository), script / conda /
                pip / none through env/install_tools.sh with a fake conda and pip on PATH (skipped where bash is not usable)
  cli           plasbench tools new / validate / add / list / show / remove / install
  window        the real window server in this process: usertools, usertools/validate, usertools/upload (limits), usertools/save,
                usertools/remove, a job that runs a tool command; every POST needs the token

Standard library, git and openssl only. A part whose program is missing prints why it was skipped.
"""
import hashlib
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import user_tool_adapter as adapter  # noqa: E402
import user_tool_detect as detect  # noqa: E402
import user_tool_source as source_lib  # noqa: E402
import user_tools as ut  # noqa: E402

FAILED = []
SKIPPED = []
TMP = Path(tempfile.mkdtemp(prefix="plasbench_e2e_"))
HOME = TMP / "home"
TOOLS = TMP / "tools"
for folder in (HOME, TOOLS):
    folder.mkdir(parents=True)
os.environ["HOME"] = os.environ["USERPROFILE"] = str(HOME)
os.environ["PLASBENCH_TOOLS_PATH"] = str(TOOLS)
os.environ["PLASBENCH_UI_HOME"] = str(TMP / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(TMP / "local.env")
(TMP / "local.env").write_text("", encoding="utf-8")
os.environ.pop("PLASBENCH_USER_TOOLS", None)
IS_WINDOWS = os.name == "nt"
CONTIGS = TMP / "contigs.fasta"
CONTIGS.write_text(">c1 len=10\nACGTACGTAC\n>c2\nGGGGCCCCAA\n>c3\nTTTTAAAAGG\n", encoding="utf-8")


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def skip(name, why):
    print(f"  skip  {name}: {why}")
    SKIPPED.append(name)


def raises(function, *args, **kwargs):
    """The message of the SourceError / ManifestError / OutputError / DetectError the call raises ('' when it does not)."""
    try:
        function(*args, **kwargs)
    except (source_lib.SourceError, ut.ManifestError, adapter.OutputError, detect.DetectError) as exc:
        return str(exc)
    return ""


def posix(path):
    return str(path).replace("\\", "/")


def write_tool(name, manifest, files=None, root=None):
    folder = Path(root or TOOLS) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ut.MANIFEST).write_text(manifest, encoding="utf-8", newline="\n")
    for fname, text in (files or {}).items():
        (folder / fname).write_text(text, encoding="utf-8", newline="\n")
    return folder


def run_fake(tool, sample="s1"):
    """Run the manifest's command the way stage 4 does (run_spec, then the shell command) and return the output location."""
    out = TMP / "out" / tool.name / sample
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    spec = tool.run_spec(sample, {"contigs": str(CONTIGS)}, str(out), "1")
    if spec["missing"]:
        return spec, out, None
    subprocess.run([shutil.which("bash") or "bash", "-c", spec["command"]], check=True, cwd=str(out), env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return spec, out, spec["output"]


def convert(tool, output, task=None, tool_id=None, sample="s1"):
    task = task or tool.task
    tool_id = tool_id or tool.task_id(task)
    fasta = TMP / "conv" / f"{tool_id}.plasmid.fasta"
    fasta.parent.mkdir(parents=True, exist_ok=True)
    prov = adapter.convert(tool, str(output), str(CONTIGS), str(fasta), task, tool_id, sample)
    return prov, fasta


def fasta_ids(path):
    return [line[1:].split()[0] for line in Path(path).read_text().splitlines() if line.startswith(">")]


def bins_of(fasta):
    stem = str(fasta)[:-len(".plasmid.fasta")]
    lines = Path(stem + ".bins.tsv").read_text().splitlines()[1:]
    return sorted(line.split("\t") for line in lines)


PY = "python" if IS_WINDOWS else "python3"
BINNER = ("import sys\nout = sys.argv[1]\nopen(out + '/bins.tsv', 'w').write('contig\\tbin\\nc1\\tB1\\nc2\\tB1\\nc3\\tB2\\n')\n")
LABELER = ("import sys\nout = sys.argv[1]\nopen(out + '/labels.csv', 'w').write('contig,call,p\\nc1,plasmid,0.9\\nc2,plasmid,0.8\\nc3,chromosome,0.1\\n')\n")
FASTAER = ("import sys\nout = sys.argv[1]\nopen(out + '/plasmids.fasta', 'w').write('>pA\\nACGTACGTAC\\n>pB\\nGGGGCCCCAA\\n')\n")
ALL3 = BINNER + LABELER + FASTAER


def head(name, tasks, track="short_read", install="[install]\nmethod = none\n"):
    return f"[tool]\nname = {name}\ntask = {tasks}\nanalysis_track = {track}\n{install}"


def conversions():
    print("conversions: one fake tool per task and format")
    # (a) a single binning tool, [output] format = contig_bins
    write_tool("e_bin", head("e_bin", "binning_reconstruction") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = contig_bins\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n", {"fake.py": BINNER})
    # (b) classification from labels
    write_tool("e_cls", head("e_cls", "classification") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = contig_labels\npath = labels.csv\ndelimiter = comma\ncontig_column = contig\nlabel_column = call\nscore_column = p\n",
               {"fake.py": LABELER})
    # (c) plasmid FASTA reassembly
    write_tool("e_fa", head("e_fa", "sequence_reassembly", "long_read") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = plasmid_fasta\npath = plasmids.fasta\n", {"fake.py": FASTAER})
    # (d) multi-task: one command, two rows
    write_tool("e_multi", head("e_multi", "binning_reconstruction, classification") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = contig_bins, contig_labels\n[output.contig_bins]\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n"
               "[output.contig_labels]\npath = labels.csv\ndelimiter = comma\ncontig_column = contig\nlabel_column = call\nscore_column = p\n",
               {"fake.py": BINNER + LABELER})
    # (e) auto, unambiguous: a contig table, a label table with a different header, and plasmid FASTA
    write_tool("e_auto", head("e_auto", "binning_reconstruction, classification, sequence_reassembly") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = auto\ncandidates = bins.tsv, plasmids.fasta\n", {"fake.py": BINNER + FASTAER})
    # (e) auto, ambiguous: two different tables that could each serve binning
    ambiguous = BINNER + "open(out + '/bins2.tsv', 'w').write('contig\\tbin\\nc1\\tB9\\nc2\\tB9\\n')\n"
    write_tool("e_amb", head("e_amb", "binning_reconstruction") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = auto\ncandidates = bins.tsv, bins2.tsv\n", {"fake.py": ambiguous})
    # (e) auto, nothing recognisable
    write_tool("e_none", head("e_none", "classification") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
               "[output]\nformat = auto\ncandidates = x.txt\n", {"fake.py": "import sys\nopen(sys.argv[1] + '/x.txt', 'w').write('hello')\n"})
    tools = ut.discover(strict=True)
    check("all fake manifests validate", {"e_bin", "e_cls", "e_fa", "e_multi", "e_auto", "e_amb", "e_none"} <= set(tools), sorted(tools))

    tool = tools["e_bin"]
    spec, out, output = run_fake(tool)
    prov, fasta = convert(tool, output)
    check("(a) binning: contig_bins -> bins.tsv with B1={c1,c2}, B2={c3}", bins_of(fasta) == [["B1", "c1"], ["B1", "c2"], ["B2", "c3"]], bins_of(fasta))
    check("(a) binning: the predicted FASTA holds the binned contigs", sorted(fasta_ids(fasta)) == ["B1", "B2"] or sorted(fasta_ids(fasta)) == ["c1", "c2", "c3"], fasta_ids(fasta))

    tool = tools["e_cls"]
    spec, out, output = run_fake(tool)
    prov, fasta = convert(tool, output)
    stem = str(fasta)[:-len(".plasmid.fasta")]
    check("(b) classification: the plasmid-labelled contigs are the prediction", sorted(fasta_ids(fasta)) == ["c1", "c2"], fasta_ids(fasta))
    check("(b) classification: probabilities are kept for the PR curve and no bins are written", Path(stem + ".scores.tsv").is_file() and not Path(stem + ".bins.tsv").exists())

    tool = tools["e_fa"]
    spec, out, output = run_fake(tool)
    prov, fasta = convert(tool, output)
    check("(c) reassembly: each record of the plasmid FASTA is a predicted plasmid", fasta_ids(fasta) == ["pA", "pB"], fasta_ids(fasta))

    tool = tools["e_multi"]
    spec, out, output = run_fake(tool)
    check("(d) multi-task: the registry has one id per task", [i for i, _ in tool.task_ids()] == ["e_multi", "e_multi__classification" if False else tool.task_ids()[1][0]], tool.task_ids())
    check("(d) multi-task: the primary keeps the tool's name and the second is <name>__<task>", tool.task_ids()[0][0] == "e_multi" and tool.task_ids()[1][0] == "e_multi__classification", tool.task_ids())
    first, f1 = convert(tool, output, "binning_reconstruction", "e_multi")
    second, f2 = convert(tool, output, "classification", "e_multi__classification")
    check("(d) multi-task: both rows come from the ONE output the command wrote", len(list(out.iterdir())) == 2 and first["output_sha256"] != second["output_sha256"])
    check("(d) multi-task: the binning row has real bins, the classification row has scores",
          bins_of(f1)[0][0] == "B1" and Path(str(f2)[:-len(".plasmid.fasta")] + ".scores.tsv").is_file())

    tool = tools["e_auto"]
    spec, out, output = run_fake(tool)
    p_bin, f_bin = convert(tool, output, "binning_reconstruction", "e_auto")
    p_cls, f_cls = convert(tool, output, "classification", "e_auto__classification")
    p_fa, f_fa = convert(tool, output, "sequence_reassembly", "e_auto__sequence_reassembly")
    check("(e) auto: binning is recognised from the contig table, reassembly from the FASTA",
          p_bin["chosen_format"] == "contig_bins" and p_fa["chosen_format"] == "plasmid_fasta" and fasta_ids(f_fa) == ["pA", "pB"], (p_bin["chosen_format"], p_fa["chosen_format"]))
    check("(e) auto: classification is derived from the same contig table (a binned contig is plasmid) and says so", p_cls["chosen_format"] == "contig_bins" and "derived" in p_cls, p_cls)
    check("(e) auto: the choice and the files seen are recorded in the provenance", p_bin["candidates_seen"] and p_bin["summary"].startswith("binning_reconstruction <- contig_bins"))

    tool = tools["e_amb"]
    spec, out, output = run_fake(tool)
    message = raises(convert, tool, output)
    check("(e) auto: two candidates that could each serve binning are an ERROR that names both and says how to narrow", "bins.tsv" in message and "bins2.tsv" in message and "candidates" in message, message)
    tool = tools["e_none"]
    spec, out, output = run_fake(tool)
    message = raises(convert, tool, output)
    check("(e) auto: an unrecognisable output is an error listing what was seen, not an empty prediction", "x.txt" in message and "usable" in message, message)

    # (f) several formats: each task prefers its own best declared format
    tool = tools["e_multi"]
    check("(f) several formats: the derivation table says native for both tasks", [e["status"] for e in tool.derivation()] == ["native", "native"], tool.derivation())
    # a declared format the tool did not write is reported with where it looked
    spec, out, output = run_fake(tool)
    (out / "labels.csv").unlink()
    (out / "bins.tsv").unlink()
    message = raises(convert, tool, output, "classification", "e_multi__classification")
    check("(f) a declared output the tool did not write is a named error, never a silent empty row", "labels.csv" in message or "contig_bins" in message, message)
    # (f) the wrong format for the task is refused by validation, not at run time
    problems = ut.validate_text(head("bad_fmt", "classification, binning_reconstruction") + "[run]\nmode = command\ncommand = x {outdir}\n[output]\nformat = plasmid_fasta\npath = p.fasta\n")
    check("(f) a multi-task manifest whose output cannot serve a task is a validation problem (never a silent empty row)", not problems["ok"] and any("classification" in p or "binning" in p for p in problems["problems"]), problems)
    legacy = ut.validate_text(head("legacy_fmt", "binning_reconstruction") + "[run]\nmode = command\ncommand = x {outdir}\n[output]\nformat = plasmid_fasta\npath = p.fasta\n")
    check("(f) the legacy single-format case is allowed but flagged as not a real grouping", legacy["ok"] and any("not a real grouping" in w for w in legacy["warnings"]), legacy)
    # a typo in a manifest key is reported
    typo = ut.validate_text(head("typo_t", "classification") + "[run]\nmode = command\ncommand = x {outdir}\n[output]\nformat = contig_labels\npath = x\nlabell_column = 2\n")
    check("a misspelt key is reported, never silently ignored", not typo["ok"] and any("labell_column" in p for p in typo["problems"]), typo)
    shutil.rmtree(TOOLS / "e_none"); shutil.rmtree(TOOLS / "e_amb")


# -- sources: a real HTTPS server with a throw-away certificate -------------------------------------------------------------
def tar_gz(members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, kind, payload in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = payload.encode()
                info.size, info.mode = len(data), 0o755
                tf.addfile(info, io.BytesIO(data))
            elif kind == "sym":
                info.type, info.linkname = tarfile.SYMTYPE, payload
                tf.addfile(info)
    return buffer.getvalue()


def make_web():
    openssl = shutil.which("openssl")
    git = shutil.which("git")
    web = TMP / "web"
    web.mkdir()
    if not openssl:
        return None, None, "openssl is not installed"
    cert, key = TMP / "cert.pem", TMP / "key.pem"
    conf = TMP / "openssl.cnf"
    conf.write_text("\n".join(["[req]", "distinguished_name = dn", "[dn]", ""]), encoding="utf-8")
    done = subprocess.run([openssl, "req", "-config", str(conf), "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=localhost",
                           "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], capture_output=True, text=True)
    if done.returncode != 0:
        return None, None, "openssl could not make a certificate: " + done.stderr[-200:]
    tool_py = "import sys\nopen(sys.argv[1] + '/bins.tsv', 'w').write('contig\\tbin\\nc1\\tB1\\n')\n"
    (web / "good.tar.gz").write_bytes(tar_gz([("tool-1.0/run.py", "file", tool_py), ("tool-1.0/README", "file", "hi")]))
    (web / "escape.tar.gz").write_bytes(tar_gz([("tool/run.py", "file", tool_py), ("tool/link", "sym", "../../outside")]))
    (web / "run.py").write_text(tool_py, encoding="utf-8")
    with zipfile.ZipFile(web / "slip.zip", "w") as zf:
        zf.writestr("tool/run.py", tool_py)
        zf.writestr("../../zip_slip.txt", "owned")
    (web / "big.tar.gz").write_bytes(tar_gz([("big/blob", "file", "x" * 6_000_000)]))
    if git:
        work = TMP / "gitwork"
        work.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x")

        def g(*args, cwd=work):
            return subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false"] + list(args), cwd=str(cwd), env=env, capture_output=True, text=True, check=True).stdout.strip()
        g("init")
        (work / "run.py").write_text(tool_py, encoding="utf-8")
        g("add", "-A"); g("commit", "-m", "one")
        first = g("rev-parse", "HEAD")
        (work / "run.py").write_text(tool_py + "# version two\n", encoding="utf-8")
        g("add", "-A"); g("commit", "-m", "two")
        g("tag", "v2")
        bare = web / "tool.git"
        g("clone", "--bare", str(work), str(bare), cwd=TMP)
        g("update-server-info", cwd=bare)
        (TMP / "git_first").write_text(first)
    handler = partial(SimpleHTTPRequestHandler, directory=str(web))
    handler.log_message = lambda *a, **k: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.handle_error = lambda *a, **k: None   # a client that stops at the size cap is not an error here
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, cert, ""


def sources():
    print("sources: local copy / link, url, git, and the refusals")
    # local copy and link
    src = TMP / "local_src"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "run.py").write_text("import sys\nopen(sys.argv[1] + '/bins.tsv', 'w').write('contig\\tbin\\nc1\\tB1\\n')\n", encoding="utf-8")
    base = ("[run]\nmode = command\ncommand = {py} {src}/bin/run.py {outdir}\nrequires = contigs\n[output]\nformat = contig_bins\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n").replace("{py}", PY)
    copy = write_tool("s_copy", head("s_copy", "binning_reconstruction", install=f"[install]\nmethod = local\npath = {posix(src)}\nmode = copy\n") + base)
    link = write_tool("s_link", head("s_link", "binning_reconstruction", install=f"[install]\nmethod = local\npath = {posix(src)}\nmode = link\n") + base)
    tools = ut.discover(strict=True)
    messages = []
    before = tools["s_copy"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")
    check("{src} before the install: the run is refused with the install command, not a crash", "not installed" in before["missing"] and "install-tools s_copy" in before["missing"], before["missing"])
    check("source_missing: a url/local tool whose source is not fetched yet is reported (stage 0 uses it)", tools["s_copy"].source_missing())
    entry = tools["s_copy"].install_source(log=messages.append)
    check("source_missing: false once the source is installed", not ut.discover()["s_copy"].source_missing())
    check("local copy: the source is copied into the tool's folder and recorded with a checksum", (copy / "src" / "bin" / "run.py").is_file() and entry["sha256"] and entry["mode"] == "copy", entry)
    spec = tools["s_copy"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")
    check("{src} is the copy in the command", posix(copy / "src") in posix(spec["command"]) and not spec["missing"], spec)
    sig_before = spec["checksum"]
    (src / "bin" / "run.py").write_text((src / "bin" / "run.py").read_text() + "# newer\n", encoding="utf-8")
    check("a copy is not changed by the original changing", "newer" not in (copy / "src" / "bin" / "run.py").read_text())
    tools["s_copy"].install_source(log=messages.append)
    after = tools["s_copy"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")["checksum"]
    check("re-installing a changed source changes the run fingerprint (so the next run is not 'reused')", after != sig_before)
    entry = tools["s_link"].install_source(log=messages.append)
    check("local link: used in place, with the mode recorded and a warning that it can change", entry["mode"] == "link" and entry["src"] == str(src.resolve()) and any("link" in m for m in messages))
    ln_before = tools["s_link"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")["checksum"]
    (src / "bin" / "run.py").write_text((src / "bin" / "run.py").read_text() + "# newest\n", encoding="utf-8")
    check("a linked source that changes changes the fingerprint at the next run (no stale reuse)", tools["s_link"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")["checksum"] != ln_before)
    missing = write_tool("s_nolocal", head("s_nolocal", "binning_reconstruction", install="[install]\nmethod = local\npath = /no/such/place\n") + base)
    message = raises(ut.discover(strict=True)["s_nolocal"].install_source, log=lambda m: None)
    check("a local path that does not exist is a named error", "does not exist" in message, message)
    shutil.rmtree(missing)
    big_src = TMP / "bigsrc"
    big_src.mkdir()
    (big_src / "blob").write_bytes(b"x" * 1_500_000)
    write_tool("s_cap", head("s_cap", "binning_reconstruction", install=f"[install]\nmethod = local\npath = {posix(big_src)}\nmode = copy\nmax_download_mb = 1\n") + base)
    message = raises(ut.discover(strict=True)["s_cap"].install_source, log=lambda m: None)
    check("size cap: a local copy over max_download_mb is refused and nothing is copied", "cap" in message and not (TOOLS / "s_cap" / "src").exists(), message)

    server, cert, why = make_web()
    if server is None:
        skip("url and git sources", why)
        return
    port = server.server_address[1]
    ctx = ssl.create_default_context(cafile=str(cert))
    opener = lambda request, timeout=60: urllib.request.urlopen(request, timeout=timeout, context=ctx)  # noqa: E731
    fetch = partial(source_lib.http_fetch, opener=opener)
    base_url = f"https://127.0.0.1:{port}"

    def url_tool(name, url, extra="", tasks="binning_reconstruction"):
        write_tool(name, head(name, tasks, install=f"[install]\nmethod = url\nurl = {url}\n{extra}") + base.replace("/bin/run.py", "/run.py"))
        return ut.discover(strict=True)[name]

    good = hashlib.sha256((TMP / "web" / "good.tar.gz").read_bytes()).hexdigest()
    log = []
    tool = url_tool("u_ok", f"{base_url}/good.tar.gz", f"sha256 = {good}\n")
    entry = tool.install_source(fetch=fetch, log=log.append)
    check("url: an archive with the right sha256 is downloaded over HTTPS, verified, and unpacked into src/ (the single top folder stripped)",
          entry["sha256_verified"] and (TOOLS / "u_ok" / "src" / "run.py").is_file() and entry["sha256"] == good, entry)
    spec = ut.discover()["u_ok"].run_spec("s1", {"contigs": str(CONTIGS)}, str(TMP / "o"), "1")
    check("url: {src} reaches the command and the provenance file holds url, sha256 and a tree checksum",
          posix(TOOLS / "u_ok" / "src") in posix(spec["command"]) and entry["tree_sha256"] and (TOOLS / "u_ok" / source_lib.PROVENANCE).is_file())
    # the installed tool actually runs and converts
    ok_tool = ut.discover()["u_ok"]
    spec, out, output = run_fake(ok_tool)
    prov, fasta = convert(ok_tool, output)
    check("url: the downloaded tool runs from {src} and its output converts", bins_of(fasta) == [["B1", "c1"]], bins_of(fasta))

    tool = url_tool("u_bad", f"{base_url}/good.tar.gz", "sha256 = " + "0" * 64 + "\n")
    message = raises(tool.install_source, fetch=fetch, log=lambda m: None)
    check("url: a WRONG sha256 is refused, the download is deleted and nothing is installed", "sha256" in message and "nothing was installed" in message
          and not (TOOLS / "u_bad" / "src").exists() and not (TOOLS / "u_bad" / ".download").exists(), message)
    log = []
    tool = url_tool("u_nopin", f"{base_url}/good.tar.gz")
    entry = tool.install_source(fetch=fetch, log=log.append)
    check("url: no sha256 pinned is a warning that prints the observed hash to pin", any("WARNING" in m and good in m for m in log) and not entry["sha256_verified"], log)
    check("url: the validation says 'not pinned'", any("pin" in w.lower() for w in tool.check()[1]) or any("pin" in w.lower() for w in ut.validate_text(tool.path.read_text())["warnings"]))
    for name, url in (("u_http", "http://127.0.0.1:1/good.tar.gz"), ("u_file", "file:///etc/passwd"), ("u_ftp", "ftp://example.org/x.tar.gz"), ("u_cred", "https://user:pw@example.org/x.tar.gz")):
        text = head(name, "binning_reconstruction", install="[install]\nmethod = url\nurl = " + url + "\n") + base
        verdict = ut.validate_text(text)
        refused = raises(ut.UserTool, write_tool(name, text) / ut.MANIFEST)
        message = raises(source_lib.install_url, {"name": name, "url": url}, TMP / "direct" / name, fetch=fetch, log=lambda m: None)
        shutil.rmtree(TOOLS / name)
        check(f"url: {url.split(':')[0]}{'+credentials' if name == 'u_cred' else ''} URL is refused by validation, by loading the manifest and by the installer; nothing is installed",
              not verdict["ok"] and refused and message and not (TMP / "direct" / name / "src").exists(), (verdict["problems"], refused, message))
    tool = url_tool("u_slip", f"{base_url}/slip.zip")
    message = raises(tool.install_source, fetch=fetch, log=lambda m: None)
    check("url: a zip with a '../' member (zip-slip) is refused, no src/ left, nothing written outside", message and not (TOOLS / "u_slip" / "src").exists() and not (TOOLS.parent / "zip_slip.txt").exists()
          and not (TOOLS / "zip_slip.txt").exists(), message)
    tool = url_tool("u_link", f"{base_url}/escape.tar.gz")
    message = raises(tool.install_source, fetch=fetch, log=lambda m: None)
    check("url: an archive with a symlink pointing outside is refused and leaves no src/", message and not (TOOLS / "u_link" / "src").exists(), message)
    tool = url_tool("u_big", f"{base_url}/big.tar.gz", "max_download_mb = 1\n")
    big_file_size = (TMP / "web" / "big.tar.gz").stat().st_size
    message = raises(tool.install_source, fetch=fetch, log=lambda m: None)
    check(f"url: a small archive that unpacks to 6 MB (a decompression bomb, {big_file_size} bytes on the wire) is refused against the 1 MB cap and leaves no src/",
          message and "cap" in message and not (TOOLS / "u_big" / "src").exists(), message)
    (TMP / "web" / "random.bin").write_bytes(os.urandom(1_500_000))
    tool = url_tool("u_rand", f"{base_url}/random.bin", "kind = file\nmax_download_mb = 1\n")
    message = raises(tool.install_source, fetch=fetch, log=lambda m: None)
    check("url: a 1.5 MB download over the 1 MB cap is refused from its Content-Length, and nothing is kept",
          "cap" in message and not (TOOLS / "u_rand" / "src").exists() and not list((TOOLS / "u_rand").glob("**/*.part")), message)
    tool = url_tool("u_file1", f"{base_url}/run.py", "kind = file\n")
    entry = tool.install_source(fetch=fetch, log=lambda m: None)
    check("url: a single file source is placed in src/ and is the {src} folder's only content", (TOOLS / "u_file1" / "src" / "run.py").is_file(), entry)
    message = raises(url_tool("u_404", f"{base_url}/nothing.tar.gz").install_source, fetch=fetch, log=lambda m: None)
    check("url: HTTP 404 is a named error with the url", "404" in message, message)

    if (TMP / "git_first").exists():
        first = (TMP / "git_first").read_text().strip()
        env_run = lambda command, **kw: subprocess.run(command, **dict(kw, env=dict(kw.get("env") or os.environ, GIT_SSL_CAINFO=str(cert), GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.sslBackend", GIT_CONFIG_VALUE_0="openssl")))  # noqa: E731
        tool = url_tool("g_pin", f"{base_url}/tool.git", f"kind = git\nref = {first}\n")
        try:
            entry = tool.install_source(run=env_run, log=lambda m: None)
            head_commit = subprocess.run(["git", "-C", str(TOOLS / "g_pin" / "src"), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            check("git: a source cloned over HTTPS at a pinned commit is at exactly that commit and records it", head_commit == first == entry["commit"], (head_commit, first, entry.get("commit")))
            check("git: the older commit's file content is checked out (not the newer one)", "version two" not in (TOOLS / "g_pin" / "src" / "run.py").read_text())
            skip("git tag/branch ref", "a tag or branch is cloned with --depth 1, which the static HTTPS server here cannot serve (needs a smart-HTTP git server); a commit ref is what is tested")
            log = []
            tool = url_tool("g_float", f"{base_url}/tool.git", "kind = git\n")
            tool.install_source(run=env_run, log=log.append)
            check("git: no ref is a warning that records the commit it got", any("WARNING" in m and "no ref" in m for m in log), log)
            verdict = ut.validate_text(head("g_sha", "binning_reconstruction", install=f"[install]{chr(10)}method = url{chr(10)}url = {base_url}/tool.git{chr(10)}kind = git{chr(10)}ref = {first}{chr(10)}sha256 = {'1' * 64}{chr(10)}") + base)
            message = " ".join(verdict["problems"])
            check("git: a sha256 on a git source is refused (pin the commit instead)", not verdict["ok"] and "git" in message, message)
            message = raises(url_tool("g_badref", f"{base_url}/tool.git", "kind = git\nref = deadbeefdeadbeef\n").install_source, run=env_run, log=lambda m: None)
            check("git: a ref that does not exist is a named error and leaves no src/", message and not (TOOLS / "g_badref" / "src").exists(), message)
        except (source_lib.SourceError, OSError) as exc:
            check("git source over HTTPS", False, str(exc))
    else:
        skip("git source", "git is not installed")
    server.shutdown()


# -- script / conda / pip / none through env/install_tools.sh --------------------------------------------------------------
def installers():
    print("installers: script, conda, pip and none with a fake conda and pip on PATH")
    bash = shutil.which("bash")
    if IS_WINDOWS or not bash:
        skip("script/conda/pip/none install", "needs bash on Linux or macOS (runs in CI)")
        return
    bin_dir = TMP / "fakebin"
    bin_dir.mkdir()
    calls = TMP / "calls.log"
    for name in ("conda", "mamba", "micromamba"):
        (bin_dir / name).write_text('#!/usr/bin/env bash\necho "' + name + ' $*" >> "$FAKE_CALLS"\n'
                                    'case "$1" in env) exit 0;; run) shift; shift; shift; exec "$@";; --version) echo "conda 24.1.0";; esac\nexit 0\n', encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (bin_dir / "mytool").write_text("#!/usr/bin/env bash\necho mytool 1.0\n", encoding="utf-8")
    (bin_dir / "mytool").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", FAKE_CALLS=str(calls), PLASBENCH_TOOLS_PATH=str(TOOLS), HOME=str(HOME),
               PLASBENCH_INSTALL_DRY_RUN="", CONDA_EXE=str(bin_dir / "conda"))
    write_tool("i_none", head("i_none", "classification", install="[install]\nmethod = none\nverify_command = mytool --version\n") + "[run]\nmode = command\ncommand = mytool\n[output]\nformat = contig_labels\npath = x\nlabel_column = 2\n")
    write_tool("i_conda", head("i_conda", "classification", install="[install]\nmethod = conda\npackages = mytool=1.0\nverify_command = mytool --version\n") + "[run]\nmode = command\ncommand = mytool\n[output]\nformat = contig_labels\npath = x\nlabel_column = 2\n")
    write_tool("i_pip", head("i_pip", "classification", install="[install]\nmethod = pip\npip_packages = mytool==1.0\nverify_command = mytool --version\n") + "[run]\nmode = command\ncommand = mytool\n[output]\nformat = contig_labels\npath = x\nlabel_column = 2\n")
    write_tool("i_script", head("i_script", "classification", install="[install]\nmethod = script\nscript = install.sh\nverify_command = test -f $HOME/script_ran\n") + "[run]\nmode = command\ncommand = mytool\n[output]\nformat = contig_labels\npath = x\nlabel_column = 2\n",
               {"install.sh": '#!/usr/bin/env bash\ntouch "$HOME/script_ran"\n'})
    write_tool("i_badverify", head("i_badverify", "classification", install="[install]\nmethod = none\nverify_command = definitely_not_a_command_xyz\n") + "[run]\nmode = command\ncommand = mytool\n[output]\nformat = contig_labels\npath = x\nlabel_column = 2\n")
    for name, expect_ok, needle in (("i_none", True, ""), ("i_conda", True, "create"), ("i_pip", True, "pip"), ("i_script", True, ""), ("i_badverify", False, "")):
        if calls.exists():
            calls.unlink()
        done = subprocess.run([bash, str(ROOT / "env" / "install_tools.sh"), "--yes", name], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
        log = calls.read_text() if calls.exists() else ""
        ok = (done.returncode == 0) == expect_ok
        check(f"install {name}: exit {'0' if expect_ok else 'non-zero'} (got {done.returncode})", ok, (done.stdout + done.stderr)[-400:])
        if needle:
            check(f"install {name}: the fake conda was asked to '{needle}' for the tool's own environment", needle in log and f"plasbench-{name}" in log, log)
    check("install i_script: the shipped script ran", (HOME / "script_ran").exists())


# -- the command line -------------------------------------------------------------------------------------------------------
def cli(*args, check_ok=None, cwd=None):
    env = dict(os.environ, PLASBENCH_TOOLS_PATH=str(TOOLS), HOME=str(HOME), USERPROFILE=str(HOME), PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-m", "plasbench", *args], cwd=str(cwd or ROOT), env=env, capture_output=True, text=True, timeout=300)
    return done.returncode, done.stdout + done.stderr


def command_line():
    print("command line: plasbench tools new / validate / add / list / show / remove")
    dest = HOME / ".plasbench" / "tools"
    os.environ["PLASBENCH_TOOLS_PATH"] = str(dest)       # the user's own folder is the search path for this part
    code, out = cli("tools", "new", "cli_tool", "--task", "binning_reconstruction,classification", "--source", "installed", "--output-format", "auto")
    check("tools new writes a commented manifest in the user's folder", code == 0 and (dest / "cli_tool" / ut.MANIFEST).is_file(), out)
    text = (dest / "cli_tool" / ut.MANIFEST).read_text()
    check("tools new: --task a,b and --output-format auto are in the manifest", "task = binning_reconstruction,classification" in text.replace(", ", ",") and "format = auto" in text, text[:400])
    code, out = cli("tools", "new", "cli_tool")
    check("tools new over an existing tool does not overwrite it silently", code != 0 or "exists" in out.lower() or (dest / "cli_tool" / ut.MANIFEST).read_text() == text, out)
    code, out = cli("tools", "validate", "cli_tool")
    check("tools validate on the fresh template reports each task and the source (the placeholder command may be flagged, never crash)", "Traceback" not in out, out[-400:])
    # a working manifest to add from a folder outside the search path
    folder = TMP / "to_add" / "added_tool"
    write_tool("added_tool", head("added_tool", "binning_reconstruction") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n[output]\nformat = contig_bins\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n",
               {"fake.py": BINNER}, root=TMP / "to_add")
    code, out = cli("tools", "add", str(folder))
    check("tools add copies the folder (manifest and script) onto the search path", code == 0 and (dest / "added_tool" / "fake.py").is_file(), out)
    code, out = cli("tools", "validate", "added_tool")
    check("tools validate on the added tool passes and prints the derivation", code == 0 and "binning_reconstruction" in out and "native" in out, out)
    code, out = cli("tools", "list")
    check("tools list shows the added tool with task, track, mode, format and install", "added_tool" in out and "contig_bins" in out and "short_read" in out, out)
    code, out = cli("tools", "show", "added_tool")
    check("tools show prints the manifest as PlasBench reads it", "[tool]" in out and "name = added_tool" in out, out)
    # adding a tool that is already ON the search path must not delete it (copy onto itself)
    code, out = cli("tools", "add", str(dest / "added_tool"))
    check("tools add of a folder that already is the installed copy keeps the tool (never deletes the source)", (dest / "added_tool" / "fake.py").is_file() and (dest / "added_tool" / ut.MANIFEST).is_file(), out)
    bad = TMP / "to_add" / "bad_tool"
    write_tool("bad_tool", "[tool]\nname = bad_tool\ntask = nonsense\nanalysis_track = short_read\n[run]\nmode = command\ncommand = x\n[output]\nformat = contig_bins\n", root=TMP / "to_add")
    code, out = cli("tools", "add", str(bad))
    check("tools add refuses a manifest that does not validate and installs nothing", code != 0 and not (dest / "bad_tool").exists(), out)
    builtin = TMP / "to_add" / "mob_recon"
    write_tool("mob_recon", head("mob_recon", "binning_reconstruction") + "[run]\nmode = command\ncommand = x\n[output]\nformat = contig_bins\npath = b\n", root=TMP / "to_add")
    code, out = cli("tools", "add", str(builtin))
    check("tools add refuses a name that is a built-in tool", code != 0 and "built-in" in out, out)
    code, out = cli("tools", "install", "added_tool")
    check("tools install on a method = none tool completes (nothing to install)", code == 0 or not shutil.which("bash") or IS_WINDOWS, out[-300:])
    code, out = cli("tools", "remove", "added_tool")
    check("tools remove deletes the tool's folder from the user's folder", code == 0 and not (dest / "added_tool").exists(), out)
    code, out = cli("tools", "list")
    check("tools list no longer shows it", "added_tool" not in out, out)
    code, out = cli("tools", "remove", "added_tool")
    check("tools remove of a tool that is not there is a named error, not a crash", code != 0 and "added_tool" in out and "Traceback" not in out, out)
    code, out = cli("tools", "remove", "mob_recon")
    check("tools remove refuses a built-in tool", code != 0 and "Traceback" not in out, out)
    os.environ["PLASBENCH_TOOLS_PATH"] = str(TOOLS)


# -- the window -------------------------------------------------------------------------------------------------------------
def window():
    print("window routes: the real server in this process")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = TMP / "ui"
    home = HOME / ".plasbench" / "tools"
    os.environ["PLASBENCH_TOOLS_PATH"] = str(home)
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, token=True):
        headers = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if token:
            headers["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}

    manifest = (head("win_tool", "binning_reconstruction, classification") + f"[run]\nmode = command\ncommand = {PY} {{tool_dir}}/fake.py {{outdir}}\nrequires = contigs\n"
                "[output]\nformat = contig_bins, contig_labels\n[output.contig_bins]\npath = bins.tsv\ncontig_column = contig\nbin_column = bin\n"
                "[output.contig_labels]\npath = labels.csv\ndelimiter = comma\ncontig_column = contig\nlabel_column = call\nscore_column = p\n")
    code, r = call("/api/usertools/validate", {"text": manifest})
    check("validate: ok, two tasks, both native, source and outputs present", code == 200 and r["ok"] and [t["status"] for t in r["tasks"]] == ["native", "native"] and r["outputs"] and r["source"]["method"] == "none", r)
    code, r = call("/api/usertools/validate", {"text": manifest}, token=False)
    check("validate: every POST needs the token (403 without)", code == 403, (code, r))
    code, r = call("/api/usertools/validate", {"text": manifest.replace("format = contig_bins, contig_labels", "format = plasmid_fasta")})
    check("validate: a format that cannot serve a task is a problem the form can show", code == 200 and not r["ok"] and r["problems"], r)
    code, r = call("/api/usertools/validate", {"text": "not an ini at all"})
    check("validate: text that is not a manifest answers ok=false with a reason (no server error)", code == 200 and not r["ok"] and r["problems"], (code, r))
    code, r = call("/api/usertools/save", {"text": manifest}, token=False)
    check("save: needs the token", code == 403)
    code, r = call("/api/usertools/save", {"text": manifest})
    check("save: writes ~/.plasbench/tools/<name>/plasbench-tool.ini", code == 200 and r["ok"] and (home / "win_tool" / ut.MANIFEST).is_file(), r)
    code, r = call("/api/usertools/save", {"text": manifest})
    check("save: an existing tool is not overwritten unless the form says so", code == 200 and not r["ok"] and r.get("exists"), r)
    code, r = call("/api/usertools/save", {"text": manifest, "overwrite": True})
    check("save: overwrite = true replaces it", code == 200 and r["ok"], r)
    code, r = call("/api/usertools/save", {"text": manifest.replace("name = win_tool", "name = mob_recon")})
    check("save: a built-in tool's name is refused", code == 200 and not r["ok"] and any("built-in" in p for p in r["problems"]), r)
    code, r = call("/api/usertools/save", {"text": manifest.replace("name = win_tool", "name = ../../evil")})
    check("save: a path-like tool name is refused and nothing is written outside the tools folder", code == 200 and not r["ok"] and not (HOME / ".plasbench" / "evil").exists() and not (HOME / "evil").exists(), r)
    code, r = call("/api/usertools/upload", {"name": "win_tool", "filename": "fake.py", "text": BINNER + LABELER})
    check("upload: the helper script is stored beside the manifest", code == 200 and (home / "win_tool" / "fake.py").is_file(), r)
    code, r = call("/api/usertools/upload", {"name": "win_tool", "filename": "huge.py", "text": "x" * (webui.UPLOAD_MAX_BYTES + 1)})
    check("upload: over the 5 MB limit is refused", code == 400, (code, str(r)[:80]))
    code, r = call("/api/usertools/upload", {"name": "win_tool", "filename": "../x.py", "text": "x"})
    check("upload: a traversing file name is refused", code == 400)
    code, r = call("/api/usertools")
    row = next((t for t in r.get("tools", []) if t["name"] == "win_tool"), None)
    check("list: the saved tool is listed with both tasks and its source", code == 200 and row and row["tasks"] == ["binning_reconstruction", "classification"] and row["install_source"] == "installed", r)
    code, r = call("/api/usertools/get?name=win_tool")
    check("get: the manifest text comes back for editing", code == 200 and "name = win_tool" in r["text"])
    code, r = call("/api/usertools/get?name=nosuch")
    check("get: an unknown tool is a 404, not a crash", code == 404, (code, r))
    # run through Jobs: the tool's own validation as a job, and the tool command run against the fake contigs
    code, job = call("/api/jobs", {"argv": ["tools", "validate", "win_tool"]})
    check("jobs: a `plasbench tools validate` job starts", code == 200 and job.get("id"), (code, job))
    final = {}
    for _ in range(120):
        code, final = call(f"/api/jobs/{job['id']}")
        if final.get("state") not in ("running", "starting", "cancelling"):
            break
        time.sleep(0.5)
    check("jobs: the job finishes ok and its log shows both task rows", final.get("exit") == 0, {k: final.get(k) for k in ("state", "exit")})
    # the window's remove
    code, r = call("/api/usertools/remove", {"name": "win_tool"}, token=False)
    check("remove: needs the token", code == 403)
    code, r = call("/api/usertools/remove", {"name": "win_tool"})
    check("remove: deletes the tool's folder", code == 200 and r.get("ok") and not (home / "win_tool").exists(), (code, r))
    code, r = call("/api/usertools/remove", {"name": "mob_recon"})
    check("remove: a built-in tool is refused", code in (400, 404) and "error" in r, (code, r))
    code, r = call("/api/usertools/remove", {"name": "../x"})
    check("remove: a path-like name is refused", code in (400, 404) and "error" in r, (code, r))
    code, r = call("/api/usertools")
    check("list: the removed tool is gone", all(t["name"] != "win_tool" for t in r["tools"]))
    server.shutdown()
    os.environ["PLASBENCH_TOOLS_PATH"] = str(TOOLS)


def main():
    sections = [conversions, sources, installers, command_line, window]
    only = os.environ.get("E2E_ONLY")
    for section in sections:
        if only and section.__name__ != only:
            continue
        try:
            section()
        except Exception as exc:  # noqa: BLE001 - a crashed section is a failed test, with the traceback
            import traceback
            traceback.print_exc()
            check(f"section {section.__name__} ran without an exception", False, repr(exc))
    shutil.rmtree(TMP, ignore_errors=True)
    if SKIPPED:
        print("SKIPPED: " + ", ".join(SKIPPED))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL ADD-TOOL E2E CHECKS PASSED")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
