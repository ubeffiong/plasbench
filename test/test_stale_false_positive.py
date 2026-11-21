#!/usr/bin/env python3
"""The 'This window is running an older version of PlasBench than the page' banner must not appear unless the running code really differs from what a restart would load.

Reported: the banner showed constantly even though the window was up to date, right after `plasbench upgrade`. What the code did wrong (plasbench/server_state.py before this change):
it judged staleness by the size and mtime of every plasbench/*.py (a touched file with the same content, a copy by OneDrive/git/an antivirus, or a module the server never loaded, counted),
it never compared the installed copy with the PlasBench folder (so the 'two installs' case, where Restart cannot help, looked like an endless restart loop), and a second `plasbench ui` or the
desktop icon silently REUSED a window started before the upgrade, whose banner was then true but 'restarting' brought the same old window back. Tested here, with temporary trees only:

  - hash, not mtime: a touched-but-identical file is not stale; a changed loaded module is, with old/new hashes; a file written into the package folder at run time, a *.pyc, a module the
    server never imported, a module imported after start: not stale; the hash is cached by (size, mtime);
  - two installs (a copy in site-packages and a different version in the project folder): kind two_installs, the install command, restart does not help; an editable layout and equal
    versions: no banner;
  - the page: unreplaced api-level placeholder means an older server; the banner is driven by the server's state (no banner when stale is false), Details carries the evidence, Dismiss is keyed
    by start time + pid + kind (node runs the pure block);
  - a running window older than this command is replaced (fake server), a same-version one is reused;
  - project-folder resolution order, install.json, the ~/.local/bin launcher (marker, never overwrites, opt-out, PATH notice), the upgrade verification and repair (fakes), plasbench ui-state.
Standard library only; node is optional.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
os.environ.pop("PLASBENCH_HOME", None)
(tmp / "home").mkdir()
from plasbench import cli, roots, server_state, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def make_root(path, version="0.5.3"):
    (path / "scripts").mkdir(parents=True, exist_ok=True)
    (path / "scripts" / "run_all.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (path / "plasbench").mkdir(exist_ok=True)
    (path / "plasbench" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    return path


def import_fake(pkgdir, name):
    """Import pkgdir/<name>.py as a module of a fake package so that loaded_modules() sees it, as it sees the real plasbench modules."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fakepb." + name, str(pkgdir / (name + ".py")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["fakepb." + name] = mod
    return mod


def main():
    print("hash, not mtime")
    pkg = tmp / "fakepb"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (pkg / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "beta.py").write_text("VALUE = 2\n", encoding="utf-8")
    import_fake(pkg, "alpha")
    started = {"version": "1.0.0", "modules": server_state.module_hashes(pkg), "at": 1.0}
    check("only the imported module is recorded", list(started["modules"]) == ["alpha.py"], started["modules"])
    st_before = os.stat(pkg / "alpha.py")
    os.utime(pkg / "alpha.py", (st_before.st_atime, st_before.st_mtime + 3600))
    check("a touched file with the same content is NOT stale (OneDrive, antivirus, git, a copy)", server_state.changed_modules(started, pkg) == [])
    (pkg / "beta.py").write_text("VALUE = 22\n", encoding="utf-8")
    check("a file the server never imported does not count, however it changes", server_state.changed_modules(started, pkg) == [])
    (pkg / "gamma.py").write_text("VALUE = 3\n", encoding="utf-8")
    (pkg / "__pycache__").mkdir(exist_ok=True)
    (pkg / "__pycache__" / "alpha.cpython-311.pyc").write_bytes(b"\x00\x01")
    (pkg / "cache.json").write_text("{}", encoding="utf-8")
    check("a file written into the package folder at run time, a .pyc or a data file does not count", server_state.changed_modules(started, pkg) == [])
    import_fake(pkg, "beta")
    check("a module imported after the start is recorded, not flagged (it loaded the files as they are)", server_state.changed_modules(started, pkg) == [] and "beta.py" in started["modules"])
    (pkg / "alpha.py").write_text("VALUE = 100\n", encoding="utf-8")
    changed = server_state.changed_modules(started, pkg)
    check("a loaded module whose content changed IS stale, with old and new hashes (12 characters)",
          len(changed) == 1 and changed[0]["module"] == "alpha.py" and len(changed[0]["old"]) == 12 and changed[0]["old"] != changed[0]["new"], changed)
    check("compare() turns it into a reason that names the module", server_state.compare(started, "1.0.0", changed)[0] and "alpha.py" in server_state.compare(started, "1.0.0", changed)[1])
    check("the version in __init__.py is read as text", server_state.read_version(pkg) == "1.0.0")
    (pkg / "__init__.py").write_text('__version__ = "1.0.1"\n', encoding="utf-8")
    check("a changed version is stale on its own", server_state.compare(started, server_state.read_version(pkg), [])[0])
    # cached by (size, mtime)
    counter = {"n": 0}
    real_sha = server_state.hashlib.sha256

    def counting(data=b""):
        counter["n"] += 1
        return real_sha(data)
    server_state.hashlib.sha256 = counting
    try:
        server_state._HASHES.clear()
        for _ in range(5):
            server_state.file_hash(pkg / "alpha.py")
        once = counter["n"]
        (pkg / "alpha.py").write_text("VALUE = 1000000\n", encoding="utf-8")
        server_state.file_hash(pkg / "alpha.py")
    finally:
        server_state.hashlib.sha256 = real_sha
    check("a hash is computed once per (size, mtime) and again only after the file changed", once == 1 and counter["n"] == 2, counter)
    check("an unreadable or missing file hashes to ''", server_state.file_hash(pkg / "nope.py") == "")
    for n in ("fakepb.alpha", "fakepb.beta"):
        sys.modules.pop(n, None)

    print("the real package: nothing changed, nothing stale")
    server_state.reset(root=ROOT)
    st = server_state.state(ROOT)
    check("a fresh start is not stale and the root is this checkout (editable layout: no second install)", st["stale"] is False and st["kind"] == "none" and st["project_root_version"] == "", st)
    check("the state names pid, port, running path and version", st["server"]["pid"] == os.getpid() and st["running_path"] == str(server_state.PKG) and st["running_version"], st)
    check("the real modules it imported were recorded at start", "server_state.py" in server_state.START["modules"] and len(server_state.START["modules"][("server_state.py")]) == 64)
    p = server_state.PKG / "server_state.py"
    stat = os.stat(p)
    os.utime(p, (stat.st_atime, stat.st_mtime + 5))
    try:
        check("touching a real loaded module without changing it is not stale", server_state.state(ROOT)["stale"] is False)
    finally:
        os.utime(p, (stat.st_atime, stat.st_mtime))

    print("two installs (a copy in site-packages next to a different checkout)")
    other = make_root(tmp / "My Plas Bench", "9.9.9")
    st = server_state.state(other)
    check("a different version in the project folder is kind two_installs and stale", st["stale"] and st["kind"] == "two_installs", st)
    check("it says where each is and gives the install command (quoted for a path with spaces)",
          st["project_root_version"] == "9.9.9" and st["project_root_path"].endswith("plasbench") and "pip install --no-deps ." in st["fix_command"] and "'" in st["fix_command"] and "conda activate plasbench" in st["fix_command"], st)
    check("restart does not help in that case, and the reason says so", st["restart_helps"] is False and "Restarting the window cannot fix" in st["reason"])
    same = make_root(tmp / "same", server_state.START["version"])
    check("the same version in both places: no banner", server_state.state(same)["stale"] is False)
    check("a folder with no plasbench package (a release layout): no banner", server_state.state(tmp / "home")["stale"] is False)
    saved = dict(server_state.START)
    server_state.START["version"] = "0.0.1"
    try:
        loaded = server_state.state(other)
    finally:
        server_state.START.update(saved)
    check("the loaded-code case is reported first, and restart helps there", loaded["kind"] == "loaded_code" and loaded["restart_helps"] is True, loaded)
    check("the install command names the checkout", server_state.install_command("/home/u/PlasBench") == "conda activate plasbench && cd /home/u/PlasBench && python -m pip install --no-deps .")
    cmd = server_state.replacement_command(Path("/x"), 8771)
    check("a restart loads the SAME package folder this server runs from (not the current folder's)", cmd[1] == "-c" and cmd[3] == str(server_state.PKG.parent) and "--new-instance" in cmd)

    print("the served page and the banner")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the page carries the api level it needs, substituted by the server", 'name="plasbench-api-level" content="__API_LEVEL__"' in html and "__API_LEVEL__" in (ROOT / "plasbench" / "windowlife.py").read_text(encoding="utf-8"))   # window stability: the substitution moved to windowlife.render_page; test_window_stability.py renders and runs the served page
    block = html.split("/* BEGIN server state (stale window server)")[-1].split("/* END server state */")[0]
    check("the banner follows the server's answer: nothing is raised for stale:false and a state with kind clears it",
          "if (staleKind(st)) raiseStale({state: st});" in block and "else if (st.kind && !SS.sticky)" in block and "pageServerMismatch(metaContent" not in block.split("async function ssPoll")[1])
    check("Details carries the evidence (versions, paths, pid and port, changed modules with hashes)",
          "evidenceLines(SS.stale)" in block and "Changed since start:" in block and "pid ${sv.pid" in block and "Project folder:" in block)
    check("Dismiss for this server run is keyed by start time, pid and kind, in sessionStorage", "Dismiss for this server run" in block and 'sessionStorage.setItem("pb_ss_dismiss", dismissKey(SS.stale))' in block)
    check("two installs shows the command, a Copy button and no Restart", 'id="ss_fix"' in block and 'id="ss_copy"' in block and "two ? `<button class=\"btn\" id=\"ss_copy\">" in block)
    check("the friendly 'no such API' message stays, shown only when that error occurs", "friendlyApiError(err.message)" in html and "STALE_API_TEXT" in block)
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the pure block is not executed")
    else:
        pure = html.split("/* ==SS-PURE-BEGIN==")[1].split("*/", 1)[1].split("/* ==SS-PURE-END== */")[0]
        js = pure + r"""
const out = [];
const eq = (n, a, b) => out.push([n, JSON.stringify(a) === JSON.stringify(b), JSON.stringify(a)]);
eq("placeholder = an older server", serverTooOld("__API_LEVEL__"), true);
eq("a number = this server knows the page", serverTooOld("2"), false);
eq("empty is not an alarm", serverTooOld(""), false);
eq("stale:false has no kind", staleKind({stale: false, kind: "none"}), "");
eq("loaded code", staleKind({stale: true, kind: "loaded_code"}), "loaded_code");
eq("two installs", staleKind({stale: true, kind: "two_installs"}), "two_installs");
eq("an older server's answer (no kind) is trusted as loaded code", staleKind({stale: true}), "loaded_code");
eq("no state, no banner", staleKind(null), "");
eq("dismiss key", dismissKey({started_at: 5, server: {pid: 7}, stale: true, kind: "loaded_code"}), "5:7:loaded_code");
eq("dismiss key changes with the kind", dismissKey({started_at: 5, server: {pid: 7}, stale: true, kind: "two_installs"}) !== dismissKey({started_at: 5, server: {pid: 7}, stale: true, kind: "loaded_code"}), true);
eq("dismiss key changes with the pid", dismissKey({started_at: 5, server: {pid: 8}, stale: true}) !== dismissKey({started_at: 5, server: {pid: 7}, stale: true}), true);
eq("headline, two installs", staleHeadline({stale: true, kind: "two_installs", running_version: "0.5.2", project_root_version: "0.5.3"}).startsWith("PlasBench is installed in two places with different versions (running 0.5.2, project folder 0.5.3)"), true);
eq("headline, loaded code", staleHeadline({stale: true, kind: "loaded_code", started_version: "0.5.2", disk_version: "0.5.3"}), "PlasBench was updated (0.5.2 -> 0.5.3) while this window was open. Restart the window to use the new version.");
const ev = evidenceLines({running_version: "0.5.2", running_path: "/s/plasbench", disk_version: "0.5.3", disk_path: "/s/plasbench", project_root_path: "/p/plasbench", project_root_version: "0.5.3", server: {pid: 11, port: 8770}, changed_modules: [{module: "webui.py", old: "aaa", new: "bbb"}], reason: "r"});
eq("evidence lines", ev.map(l => l.split(":")[0]), ["Running", "On disk there", "Project folder", "This window's server", "Changed since start", "r"]);
eq("evidence names pid and port", ev[3], "This window's server: pid 11, port 8770");
eq("evidence of an empty state is empty", evidenceLines({}), []);
console.log(JSON.stringify(out));
"""
        path = tmp / "ss.js"
        path.write_text(js, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            check("the pure block runs under node", False, done.stderr[:300])
        else:
            for name, ok, got in json.loads(done.stdout.strip().splitlines()[-1]):
                check("node: " + name, ok, got)

    print("a running window older than this command is replaced; the same version is reused")
    calls = []

    def fake_ask(state, shutdown_ok=True):
        def ask(url, route, body=None):
            calls.append((route, body))
            if route == "server-state":
                return state
            return {"ok": True} if shutdown_ok else {"ok": False}
        return ask
    said = []
    url = "http://127.0.0.1:59999/?t=KEY"
    real_seen, real_inst = webui._page_seen_of, webui._instance_file
    webui._page_seen_of = lambda port: (None, None, 0.0)
    webui._instance_file = lambda: tmp / "server.json"
    try:
        calls.clear()
        check("same version, nothing stale: reused", webui.replace_stale_instance(url, ask=fake_ask({"running_version": webui.__version__, "kind": "none", "stale": False}), say=said.append) is False and not any(r == "shutdown" for r, _ in calls))
        calls.clear()
        check("an older window: asked to quit with runs kept, replaced",
              webui.replace_stale_instance(url, ask=fake_ask({"running_version": "0.5.2", "kind": "loaded_code", "stale": True, "server": {"pid": 77}}), say=said.append) is True and ("shutdown", {"keep": True}) in calls)
        check("the notice names the pid, the port, both versions and that runs keep going", any("pid 77" in m and "59999" in m and "0.5.2" in m and webui.__version__ in m and "keep going" in m for m in said), said)
        calls.clear()
        check("a window from before server-state existed (no answer) is replaced too", webui.replace_stale_instance(url, ask=fake_ask(None), say=said.append) is True and ("shutdown", {"keep": True}) in calls)
        check("a window that refuses to close is reused, with a message", webui.replace_stale_instance(url, ask=fake_ask({"running_version": "0.5.2", "kind": "loaded_code", "stale": True}, shutdown_ok=False), say=said.append) is False and "did not agree" in said[-1])
    finally:
        webui._page_seen_of, webui._instance_file = real_seen, real_inst

    print("the project folder: the order")
    home = tmp / "home"
    cwd_root = make_root(tmp / "cwdroot")
    sub = cwd_root / "studies" / "a"
    sub.mkdir(parents=True)
    rec_root = make_root(tmp / "recorded")
    env_root = make_root(tmp / "envhome")
    exp_root = make_root(tmp / "explicit")
    empty = tmp / "empty"
    empty.mkdir()
    nowhere = tmp / "nowhere" / "plasbench" / "roots.py"
    nowhere.parent.mkdir(parents=True)
    r, how, _t = roots.resolve(explicit=exp_root, cwd=cwd_root, env={"PLASBENCH_HOME": str(env_root)})
    check("1. --project-root wins over everything", r == exp_root.resolve() and "--project-root" in how, (r, how))
    r, how, _t = roots.resolve(cwd=cwd_root, env={"PLASBENCH_HOME": str(env_root)})
    check("2. PLASBENCH_HOME beats the current folder", r == env_root.resolve() and "PLASBENCH_HOME" in how, (r, how))
    r, how, _t = roots.resolve(cwd=cwd_root, env={})
    check("3. the current folder", r == cwd_root.resolve() and how == "the current folder", (r, how))
    r, how, _t = roots.resolve(cwd=sub, env={})
    check("3. a parent of the current folder", r == cwd_root.resolve() and "parent" in how, (r, how))
    roots.record_install(rec_root, "0.5.3")
    r, how, _t = roots.resolve(cwd=empty, env={}, package_file=nowhere)
    check("4. the folder recorded at install time", r == rec_root.resolve() and how == "recorded at install time", (r, how))
    roots.install_file().unlink()
    r, how, _t = roots.resolve(cwd=empty, env={}, package_file=cwd_root / "plasbench" / "roots.py")
    check("5. the checkout the imported package lives in", r == cwd_root.resolve() and "imported" in how, (r, how))
    r, how, tried = roots.resolve(cwd=empty, env={}, package_file=nowhere)
    check("nothing found: None and every place tried", r is None and len(tried) >= 3, (r, tried))
    default = make_root(home / "PlasBench")
    r, how, _t = roots.resolve(cwd=empty, env={}, package_file=nowhere)
    check("6. ~/PlasBench", r == default.resolve() and "~/PlasBench" in how, (r, how))
    shutil.rmtree(default)
    roots.record_install(tmp / "gone")
    r, how, _t = roots.resolve(cwd=empty, env={}, package_file=nowhere)
    check("a recorded folder that no longer exists is skipped, not trusted", r is None)
    roots.install_file().unlink()
    msg = roots.not_found_message(["a", "b"])
    check("the error is short and names the three fixes", msg.count("\n") <= 6 and "cd into" in msg and "--project-root" in msg and "PLASBENCH_HOME" in msg and "./install.sh" in msg, msg)
    check("a bad PLASBENCH_HOME falls through to the next place", roots.resolve(cwd=cwd_root, env={"PLASBENCH_HOME": str(empty)})[0] == cwd_root.resolve())

    print("the notice names the folder when it was not the current one (a real process, a temporary HOME)")
    site = tmp / "site"
    site.mkdir()
    shutil.copytree(ROOT / "plasbench", site / "plasbench", ignore=shutil.ignore_patterns("__pycache__"))
    roots.record_install(ROOT, "x")
    env = {**os.environ, "PYTHONPATH": str(site)}
    done = subprocess.run([sys.executable, "-m", "plasbench", "install-tools", "validate"], cwd=str(empty), env=env, capture_output=True, text=True)
    check("`plasbench` from another folder works and says which folder it used and why", done.returncode == 0 and "Using the PlasBench folder" in done.stderr and "recorded at install time" in done.stderr, (done.returncode, done.stderr[-300:]))
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "install-tools", "validate"], cwd=str(empty), env=env, capture_output=True, text=True)
    check("a command that changes things names its folder even when it was given explicitly", "Using the PlasBench folder" in done.stderr and "given with --project-root" in done.stderr, done.stderr[-200:])
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui-state", "--json"], cwd=str(empty), env=env, capture_output=True, text=True)
    check("a read-only command does not repeat an explicit folder back", "Using the PlasBench folder" not in done.stderr, done.stderr[-200:])
    roots.install_file().unlink()

    print("install.json and the launcher")
    path = roots.record_install(ROOT, "0.5.3", python="/env/bin/python")
    data = json.loads(path.read_text(encoding="utf-8"))
    check("install.json holds the folder, version and Python", path == home / ".plasbench" / "install.json" and data["root"] == str(ROOT.resolve()) and data["version"] == "0.5.3" and data["python"] == "/env/bin/python", data)
    binrel = tmp / "lb" / "bin"
    if os.name == "nt":
        got, note = roots.write_launcher(bindir=binrel)
        check("Windows: no launcher is written (not needed there)", got is None and "Windows" in note, note)
    else:
        fake_env = tmp / "env" / "bin"
        fake_env.mkdir(parents=True)
        (fake_env / "plasbench").write_text('#!/bin/sh\necho "console:$@"\n', encoding="utf-8")
        os.chmod(fake_env / "plasbench", 0o755)
        got, note = roots.write_launcher(python=str(fake_env / "python"), bindir=binrel, env={"PATH": "/usr/bin"})
        text = got.read_text(encoding="utf-8")
        check("the launcher is written, executable, marked, and the notice says ~/.local/bin is not on PATH", got and os.access(got, os.X_OK) and roots.MARKER in text and "not on your PATH" in note, note)
        ran = subprocess.run(["sh", str(got), "--version"], capture_output=True, text=True)
        check("the launcher runs the environment's plasbench with the arguments", ran.stdout.strip() == "console:--version", (ran.stdout, ran.stderr))
        got2, note2 = roots.write_launcher(python=str(fake_env / "python"), bindir=binrel, env={"PATH": str(binrel)})
        check("written again by us: refreshed, and no PATH warning when it is on PATH", got2 and "not on your PATH" not in note2, note2)
        foreign = tmp / "lb2" / "bin"
        foreign.mkdir(parents=True)
        (foreign / "plasbench").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        got3, note3 = roots.write_launcher(bindir=foreign, env={})
        check("a file we did not make is never overwritten", got3 is None and "left alone" in note3 and "mine" in (foreign / "plasbench").read_text(encoding="utf-8"), note3)
        got4, note4 = roots.write_launcher(bindir=tmp / "lb3", env={"PLASBENCH_NO_LAUNCHER": "1"})
        check("PLASBENCH_NO_LAUNCHER=1 writes nothing", got4 is None and not (tmp / "lb3").exists() and "PLASBENCH_NO_LAUNCHER" in note4, note4)
        quoted = roots.launcher_text("/it's a path/bin/python")
        check("paths with quotes and spaces are quoted for sh", "'/it'\\''s a path/bin'" in quoted, quoted)
    fake_nt = types.SimpleNamespace(name="nt", environ={}, path=os.path, pathsep=";", chmod=os.chmod)
    real_os = roots.os
    roots.os = fake_nt
    try:
        got5, note5 = roots.write_launcher(bindir=tmp / "lb4", env={})
    finally:
        roots.os = real_os
    check("on Windows the launcher step is a no-op with a message", got5 is None and "Windows" in note5)
    win = roots.resolve(explicit=r"C:\Users\x\PlasBench")[0]
    check("a Windows-style explicit path resolves without error", win is not None)
    check("install.sh calls record, verify and launcher, non-fatally; the opt-out is documented",
          all(x in (ROOT / "install.sh").read_text(encoding="utf-8") for x in ("plasbench.roots record", "plasbench.roots verify", "plasbench.roots launcher")) and "PLASBENCH_NO_LAUNCHER" in (ROOT / "plasbench" / "roots.py").read_text(encoding="utf-8"))

    print("upgrade: verify the installed program, repair it, say so")
    folder = make_root(tmp / "upg", "0.5.3")
    ok = roots.verify(folder, run=lambda py: ("0.5.3", "/site/plasbench"))
    check("an installed copy equal to the folder verifies", ok["ok"] and "matches" in ok["message"] and ok["editable"] is False, ok)
    ed = roots.verify(folder, run=lambda py: ("0.5.3", str(folder / "plasbench")))
    check("an editable layout (the package IS the folder) verifies and says so", ed["ok"] and ed["editable"] is True and "the folder itself" in ed["message"], ed)
    bad = roots.verify(folder, run=lambda py: ("0.5.2", "/site/plasbench"))
    check("an older installed copy fails, names both versions and paths and the pip command", not bad["ok"] and "0.5.2" in bad["message"] and "0.5.3" in bad["message"] and "/site/plasbench" in bad["message"] and "pip install --no-deps" in bad["message"], bad)
    missing = roots.verify(folder, run=lambda py: ("", "No module named plasbench"))
    check("a Python that cannot import plasbench fails with the reason", not missing["ok"] and "not importable" in missing["message"], missing)
    seq = iter([bad, {"ok": True, "message": "plasbench 0.5.3 at /site/plasbench (an installed copy) matches the folder", "folder_version": "0.5.3"}])
    pips = []
    code = cli.verify_after_upgrade(folder, python="/env/bin/python", run_pip=lambda c: pips.append(c) or 0, verify=lambda r, p=None: next(seq))
    check("a mismatch is repaired with pip install --no-deps into that Python, then verified (exit 0)", code == 0 and pips == [["/env/bin/python", "-m", "pip", "install", "--no-deps", str(folder)]], (code, pips))
    check("the repair records the folder in install.json", json.loads(roots.install_file().read_text(encoding="utf-8"))["root"] == str(folder.resolve()))
    pips.clear()
    code = cli.verify_after_upgrade(folder, run_pip=lambda c: pips.append(c) or 0, verify=lambda r, p=None: bad)
    check("a repair that does not fix it exits 4 with the command", code == 4)
    pips.clear()
    code = cli.verify_after_upgrade(folder, run_pip=lambda c: pips.append(c) or 0, verify=lambda r, p=None: {"ok": True, "message": "fine", "folder_version": "0.5.3"})
    check("a match runs nothing", code == 0 and not pips)
    src = (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8")
    check("`plasbench upgrade` verifies after update.sh (also when update.sh said 'already up to date')", "code = verify_after_upgrade(root)" in src)

    print("plasbench ui-state")
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui-state", "--json"], cwd=str(empty), env=env, capture_output=True, text=True)
    info = json.loads(done.stdout) if done.returncode == 0 else {}
    check("--json gives running, project_root, copies, pip, problems", set(info) >= {"running", "project_root", "install_record", "copies", "pip", "server", "problems"} and info["running"]["version"], done.stderr[-300:])
    check("it finds the copy this command runs from", any(c["this_process"] for c in info.get("copies", [])), info.get("copies"))
    done = subprocess.run([sys.executable, "-m", "plasbench", "ui-state"], cwd=str(empty), env={**env, "PLASBENCH_HOME": ""}, capture_output=True, text=True)
    check("the text report works from any folder and ends with the problems", done.returncode == 0 and "Problems:" in done.stdout and "PlasBench folder:" in done.stdout, done.stdout[-300:] + done.stderr[-200:])

    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("\nALL FALSE-POSITIVE STALE CHECKS PASSED")


main()
