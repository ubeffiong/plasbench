#!/usr/bin/env python3
"""Regression tests for the web-window audit fixes: AU-002 (report CSP, bundle members), AU-024 (terminal redaction), AU-025 (commit secret scan),
AU-026 (download checksum record), AU-036 (zip-bomb check), AU-037 (reserved study names), AU-038 (local.env mode, keys not in URLs), AU-039/040/041/043 (window)."""
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
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def raises(fn, *args, **kw):
    try:
        fn(*args, **kw)
    except (ValueError, OSError) as exc:
        return str(exc)
    return None


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    os.environ["PLASBENCH_TOOLS_PATH"] = str(tmp / "tools")
    os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
    (tmp / "home").mkdir()
    from plasbench import gitops, sessionlog, studies, study_manage as sm, terminal, exitcodes, webui

    print("AU-037 study names")
    for bad in ("CON", "con", "PRN", "aux", "NUL", "COM1", "lpt9", "con.txt", "foo.", "NUL.tar.gz"):
        check(f"{bad!r} is refused", raises(studies.valid_name, bad) is not None)
    for good in ("cohort1", "my.study", "console", "com10", "a-b_c", "conx.y"):
        check(f"{good!r} is accepted", raises(studies.valid_name, good) is None)

    print("AU-036 / AU-002 bundles")
    root = tmp / "project"
    (root / "config").mkdir(parents=True)
    studies.create(root, "alpha", "first")
    bundle = tmp / "alpha.zip"
    sm.export_bundle(root, "alpha", bundle)
    check("a genuine bundle imports", raises(sm.import_bundle, root, bundle, "alpha2") is None)

    def tamper(extra_name, data=b"x", manifest_edit=None):
        out = tmp / ("t_" + re.sub(r"\W", "_", extra_name) + ".zip")
        with zipfile.ZipFile(bundle) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item))
            if extra_name:
                zout.writestr(extra_name, data)
        return out

    evil = tamper("study/results/benchmark.report.html", b"<script>fetch('/api/terminal/run')</script>")
    msg = raises(sm.import_bundle, root, evil, "evil1")
    check("a member the manifest does not list makes the import fail", msg is not None and "manifest" in msg, msg)
    check("and nothing was imported", not (Path(studies.workspace(root)) / "evil1").exists())

    # a low-ratio bomb below the old 50 MB floor: 20 MB of zeros listed in the manifest
    big = tmp / "bomb.zip"
    payload = b"\0" * (20 * 2**20)
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        manifest_name = sm.BUNDLE_MANIFEST
        man = json.loads(zipfile.ZipFile(bundle).read(manifest_name))
        for item in zipfile.ZipFile(bundle).infolist():
            if item.filename != manifest_name:
                z.writestr(item, zipfile.ZipFile(bundle).read(item))
        z.writestr("study/results/zeros.bin", payload)
        import hashlib
        man["files"].append({"path": "results/zeros.bin", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        z.writestr(manifest_name, json.dumps(man))
    msg = raises(sm.import_bundle, root, big, "bomb1")
    check("a high-ratio bundle between 1 MB and 50 MB is refused", msg is not None and "unreasonable" in msg, msg)
    check("the absolute cap is lowered", sm.MAX_UNPACKED <= 4 * 2**30)

    print("AU-024 terminal redaction")
    cmd = "export NCBI_API_KEY=0123456789abcdef0123456789abcdef0123 && curl -H 'Authorization: Bearer abcdefghijklmnop' https://u:pw@h/x --token s3cr3tvalue && echo ghp_abcdefghijklmnopqrstuvwxyz0123"
    red = sessionlog.redact_command(cmd)
    check("keys, bearer tokens, URL passwords and token shapes are hidden",
          all(x not in red for x in ("0123456789abcdef", "abcdefghijklmnop", ":pw@", "s3cr3tvalue", "ghp_abcdef")), red)
    check("an ordinary command is unchanged", sessionlog.redact_command("plasbench run --threads 4 --tool x") == "plasbench run --threads 4 --tool x")
    hist = tmp / "ui" / "terminal_history.jsonl"
    log = sessionlog.SessionLog(tmp / "ui" / "sessions.jsonl")
    term = terminal.Terminal(root, hist, lambda: studies.workspace(root), on_record=lambda rec: log.event("terminal", **rec))
    term._record("export ZENODO_TOKEN=abc123def456ghi789 ; ls", 0, 0.1)
    check("terminal_history.jsonl holds no key", "abc123def456ghi789" not in hist.read_text(encoding="utf-8"))
    check("sessions.jsonl holds no key", "abc123def456ghi789" not in (tmp / "ui" / "sessions.jsonl").read_text(encoding="utf-8"))
    check("the exported script holds no key", "abc123def456ghi789" not in log.script(root))
    old = tmp / "ui" / "old.jsonl"
    old.write_text(json.dumps({"t": "2020-01-01 00:00:00", "session": "s", "kind": "terminal", "shell": "bash", "command": "export API_KEY=oldkeyvalue99", "exit": 0}) + "\n", encoding="utf-8")
    check("a key already in an old log is hidden in the exported script", "oldkeyvalue99" not in sessionlog.SessionLog(old).script(root, "s"))

    print("AU-025 commit scanner")
    check("password: in YAML", gitops.credential_in("db:\n  password: hunter22xyz\n"))
    check("ZENODO_TOKEN= in a .cfg", gitops.credential_in("[zenodo]\nZENODO_TOKEN=abcd1234efgh5678\n"))
    check("NCBI_API_KEY= in config.local", gitops.credential_in("NCBI_API_KEY=0123456789abcdef0123456789abcdef01\n"))
    for ok_line in ("password: changeme", "token = os.environ['X']", "max_tokens: 4096", "TOKEN=$TOKEN", "secret = None", "api_key: your-key-here"):
        check(f"not flagged: {ok_line}", not gitops.credential_in(ok_line), ok_line)
    repo = tmp / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "config.local").write_text("NCBI_API_KEY=0123456789abcdef0123456789abcdef01\n", encoding="utf-8")
    (repo / "x.cfg").write_text("[z]\nZENODO_TOKEN=abcd1234efgh5678\n", encoding="utf-8")
    (repo / "c.yml").write_text("password: hunter22xyz\n", encoding="utf-8")
    (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    hit = {f["path"] for f in gitops.scan_staged(repo) if f["kind"] == "secret"}
    check("the three audit misses are blocked in a staged scan", {"config.local", "x.cfg", "c.yml"} <= hit, hit)
    check("a harmless file is not", "notes.txt" not in hit)

    print("AU-038 settings file and keys in URLs")
    project = webui.Project(ROOT)
    project.save_local_env({"NCBI_API_KEY": "k" * 36})
    if os.name != "nt":
        check("local.env is owner-only", (os.stat(tmp / "local.env").st_mode & 0o777) == 0o600, oct(os.stat(tmp / "local.env").st_mode))
    import build_plasmid_reference_set as bprs
    seen = {}
    orig = bprs.fetch
    bprs.fetch = lambda request, **kw: (seen.update(url=request.full_url, data=request.data), b">x\nA\n")[1]
    try:
        bprs.fetch_fasta("CP001.1", "a@b.c", "SECRETKEY123")
    finally:
        bprs.fetch = orig
    check("the efetch key is in the POST body, not the URL", "SECRETKEY123" not in seen["url"] and b"SECRETKEY123" in (seen["data"] or b""), seen)
    check("the cohort builder keeps its key out of the URL", "api_key" in (ROOT / "python" / "build_publication_cohorts.py").read_text(encoding="utf-8")
          and 'endpoint + "?"' in (ROOT / "python" / "build_publication_cohorts.py").read_text(encoding="utf-8")
          and "urlencode(params).encode" in (ROOT / "python" / "build_publication_cohorts.py").read_text(encoding="utf-8"))

    print("AU-043 dead code")
    check("is_signal and wsl_available are gone", not hasattr(exitcodes, "is_signal") and not hasattr(terminal, "wsl_available"))

    print("AU-002 reports are served under a CSP")
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}", "X-PlasBench-Token": webui.TOKEN}
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    results = tmp / "results_x"
    results.mkdir()
    (results / "benchmark.report.html").write_text("<html><script>fetch('/api/terminal/run',{method:'POST'})</script></html>", encoding="utf-8")
    (results / "benchmark.leaderboard.tsv").write_text("rank\tanalysis_track\ttask\ttool\tmean_f1\n1\tshort_read\tclassification\tt1\t0.9\n", encoding="utf-8")
    runs = json.loads(call("/api/runs/add", {"path": str(results)})[1])["runs"]
    idx = next(i for i, r in enumerate(runs) if r["name"] == "results_x")
    code, body, hdr = call(f"/view/{idx}/benchmark.report.html")
    csp = hdr.get("Content-Security-Policy", "")
    check("the served report carries a CSP", code == 200 and csp, hdr)
    check("it blocks connections and runs in an opaque origin",
          "connect-src 'none'" in csp and re.search(r"sandbox [^;]*allow-scripts", csp) and "allow-same-origin" not in csp, csp)
    check("inline script (filters, 3D) is still allowed", "script-src 'unsafe-inline'" in csp)
    check("the run row offers Forget and a leaderboard download", runs[idx]["registered"] and runs[idx]["leaderboard"], runs[idx])
    call("/api/runs/forget", {"path": str(results)})
    check("forgetting removes a registered folder from the list", all(r["name"] != "results_x" for r in json.loads(call("/api/runs")[1])["runs"]))
    server.shutdown()

    print("AU-026 download checksums")
    bash = next((b for b in (r"C:\Program Files\Git\bin\bash.exe", "/bin/bash", "/usr/bin/bash") if os.path.exists(b)), None) or shutil.which("bash")
    if bash and not (os.name == "nt" and "system32" in bash.lower()):
        f = tmp / "db.tar.gz"
        f.write_bytes(b"database")
        prov = tmp / "prov.jsonl"
        lib = str(ROOT / "scripts" / "lib.sh").replace("\\", "/")

        def sh(want):
            return subprocess.run([bash, "-c", f'source "{lib}"; verify_or_record_download "{f.as_posix()}" http://x/db "Test DB" "{want}" "{prov.as_posix()}"'],
                                  capture_output=True, text=True)
        r = sh("")
        rec = json.loads(prov.read_text().splitlines()[-1]) if prov.exists() else {}
        check("no pin: succeeds, prints a notice and records the checksum", r.returncode == 0 and "NOTICE" in r.stderr and rec.get("sha256_verified") is False and len(rec.get("sha256", "")) == 64, r.stderr)
        r = sh("0" * 64)
        check("a wrong pin fails", r.returncode != 0, r.stderr)
        r = sh(rec.get("sha256", "x"))
        check("a right pin passes and is recorded as verified", r.returncode == 0 and json.loads(prov.read_text().splitlines()[-1])["sha256_verified"] is True, r.stderr)
        for name in ("download_platon_db.sh", "download_plascope_db.sh", "download_mobsuite_db.sh"):
            check(f"{name} uses it", "verify_or_record_download" in (ROOT / "env" / name).read_text(encoding="utf-8"))
    else:
        print("  skip  no usable bash for the checksum helper")

    print("AU-039/040/041 window")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("a Forget control for runs, git remote remove, gh create and setup-git", all(x in html for x in ('runs/forget', 'op: "remote_remove"', 'op: "gh_create"', 'op: "gh_setup_git"')))
    check("every validate call has a catch", html.count('api("validate"') == 3 and html.count('api("validate", {argv}).catch(') + html.count('try { v = await api("validate"') == 3)
    check("clipboard writes are awaited in one helper", html.count("navigator.clipboard.writeText") == 1 and "async function copyText" in html and "await navigator.clipboard.writeText" in html)
    check("no catch {} hides a failed git history/branch/session load", "catch {}\n}\nasync function gdFiles" not in html and 'Could not load the history' in html and 'could not be loaded' in html)
    check("one vocabulary: the chips, KPI and help name the three tasks alike",
          '"Binning reconstruction"' in html and '"Sequence reassembly"' in html and ">Binning<" not in html and '"Binning"]' not in html and '"Reassembly"]' not in html)
    # UI cleanup: the explanation moved from an inline note to the (?) next to the filter (ui_help.PAGE["tool_tasks"]); the page keeps the anchor id
    from plasbench import ui_help
    _tt = " ".join([ui_help.PAGE["tool_tasks"]["title"], ui_help.PAGE["tool_tasks"]["summary"]] + ui_help.PAGE["tool_tasks"]["bullets"])
    check("the Tools page explains the three tasks in a (?) tooltip", 'data-tipid="tool_tasks" id="taskhelp"' in html and all(x in _tt for x in ("Classification", "Binning reconstruction", "Sequence reassembly")))
    check("the run list can export the leaderboard", "benchmark.leaderboard.tsv" in html and "download=" in html)

    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print("AUDIT WEB FIX TESTS FAILED:", FAILED)
        return 1
    print("ALL AUDIT WEB FIX TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
