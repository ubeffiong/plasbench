#!/usr/bin/env python3
"""Starting PlasBench as a desktop program, and the footer terminal.

- platform_info.recommend: the right plan for Windows, WSL2, Linux and macOS (simulated machines)
- the PlasBench icon: valid PNG, ICO and ICNS bytes, drawn from the logo geometry; the logo SVG ships with the package
- the Linux applications-menu entry runs scripts/plasbench_launcher.sh; the launcher exists and is valid bash
- `plasbench desktop-icon` is a CLI command and is in the window's schema
- the terminal: cd stays inside the PlasBench folder and the workspace, commands run in the current folder, history kept
- the server: /logo.svg and /favicon.ico need no key; the terminal endpoints need it; shutdown refuses while a job runs
- single instance: no running window is reported for a folder that has none
"""

import json
import os
import shutil
import struct
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
    os.environ["XDG_DATA_HOME"] = str(tmp / "xdg")
    os.environ.pop("RESULTS_DIR", None)
    from plasbench import desktop, platform_info, terminal

    print("platform plan")
    base = {"arch": "x86_64", "in_wsl": False, "conda_solver": "mamba", "env_ready": True,
            "resources": {"cpus": 8, "ram_gb": 32}, "docker": {"installed": False}}
    win = platform_info.recommend(dict(base, os="windows", wsl_installed=False))
    check("Windows: run inside WSL2, with the install step", win["mode"] == "wsl"
          and any("wsl --install" in s for s in win["steps"]), win)
    wsl = platform_info.recommend(dict(base, os="linux", in_wsl=True))
    check("WSL2: conda, warns about /mnt/c speed", wsl["mode"] == "conda" and any("/mnt/c" in w for w in wsl["warnings"]), wsl)
    lin = platform_info.recommend(dict(base, os="linux", conda_solver=None, env_ready=False))
    check("Linux without conda: install conda, then the environment",
          any("install-conda" in s for s in lin["steps"]) and any("install-tools core" in s for s in lin["steps"]), lin["steps"])
    check("Linux: Docker image offered as the alternative", any(platform_info.IMAGE in a for a in lin["alternatives"]))
    mac = platform_info.recommend(dict(base, os="macos", arch="arm64"))
    check("Apple Silicon: conda, Rosetta warning", mac["mode"] == "conda" and any("Rosetta" in w for w in mac["warnings"]))
    small = platform_info.recommend(dict(base, os="linux", resources={"cpus": 4, "ram_gb": 8}))
    check("low RAM is called out", any("8 GB RAM" in w for w in small["warnings"]))
    info = platform_info.detect(fast=True)
    check("detect() describes this machine", info["os"] in ("windows", "linux", "macos") and info["resources"]["cpus"] >= 1)

    print("icon and logo")
    png = desktop.png_bytes(48)
    check("PNG: signature and 48x48 RGBA header", png[:8] == b"\x89PNG\r\n\x1a\n"
          and struct.unpack(">II", png[16:24]) == (48, 48) and png[25] == 6)
    rgba = desktop.icon_rgba(32)
    check("icon: transparent corner, opaque centre", rgba[3] == 0 and rgba[(16 * 32 + 16) * 4 + 3] == 255)
    ico = desktop.ico_bytes()
    check("ICO: header with 2 images, PNG payloads", ico[:6] == struct.pack("<HHH", 0, 1, 2)
          and ico[struct.unpack("<I", ico[18:22])[0]:][:4] == b"\x89PNG")
    icns = desktop.icns_bytes()
    check("ICNS: magic and length", icns[:4] == b"icns" and struct.unpack(">I", icns[4:8])[0] == len(icns))
    logo = ROOT / "plasbench" / "data" / "logo.svg"
    check("logo.svg ships with the package", logo.is_file() and "<svg" in logo.read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    check("logo.svg is package data", '"data/*.svg"' in pyproject)
    check("README logo files exist", (ROOT / "docs/images/plasbench-logo.svg").is_file()
          and (ROOT / "docs/images/plasbench-icon.svg").is_file())

    print("desktop entry and launcher")
    launcher = ROOT / "scripts" / "plasbench_launcher.sh"
    check("launcher exists", launcher.is_file())
    bash = shutil.which("bash")
    if bash:
        p = subprocess.run([bash, "-n", str(launcher)], capture_output=True, text=True)
        check("launcher is valid bash", p.returncode == 0, p.stderr)
    entry = desktop.linux_entry(ROOT, tmp / "icon.png")
    check("Linux entry runs the launcher, no terminal", "[Desktop Entry]" in entry and "plasbench_launcher.sh" in entry
          and "Terminal=false" in entry and "Name=PlasBench" in entry)
    icons = desktop.write_icons(tmp / "icons")
    made = desktop.install_linux(ROOT, icons, desktop=False)
    target = tmp / "xdg" / "applications" / "plasbench.desktop"
    check("applications-menu entry written under XDG_DATA_HOME", target.is_file() and str(target) in made, made)
    from plasbench import cli, ui_schema
    names = set(cli.build_parser()._subparsers._group_actions[0].choices)
    check("plasbench desktop-icon is a command", "desktop-icon" in names)
    check("desktop-icon is offered in the window", ui_schema.validate_argv(["desktop-icon", "--no-desktop"])[0])

    print("terminal")
    proj = tmp / "pb"
    (proj / "sub").mkdir(parents=True)
    ws = tmp / "ws"
    ws.mkdir()
    t = terminal.Terminal(proj, tmp / "ui" / "terminal_history.jsonl", lambda: ws)
    t.set_cwd("sub")
    check("cd into a folder inside PlasBench", t.cwd == (proj / "sub").resolve() and t.shown_cwd() == "PlasBench/sub")
    t.set_cwd(str(ws))
    check("cd into the workspace", t.shown_cwd() == "workspace")
    try:
        t.set_cwd(str(tmp))
        check("cd outside is refused", False)
    except terminal.TerminalError as exc:
        check("cd outside is refused", "outside" in str(exc))
    t.set_cwd("~")
    check("cd ~ returns to the PlasBench folder", t.cwd == proj.resolve())
    try:
        t.run("")
        check("an empty command is refused", False)
    except terminal.TerminalError:
        check("an empty command is refused", True)
    if "posix" in terminal.available_shells() or "powershell" in terminal.available_shells():
        t.use_shell("posix" if "posix" in terminal.available_shells() else "powershell")
        (proj / "marker.txt").write_text("x", encoding="utf-8")
        r = t.run("ls" if t.shell == "posix" else "Get-ChildItem -Name")
        check("a command runs in the current folder", r["exit"] == 0 and "marker.txt" in r["output"], r)
        r = t.run("cd sub")
        check("`cd` is handled by the terminal", r["exit"] == 0 and t.cwd == (proj / "sub").resolve())
    hist = (tmp / "ui" / "terminal_history.jsonl").read_text(encoding="utf-8").splitlines()
    check("commands are recorded with exit status", hist and all("exit" in json.loads(h) for h in hist), hist[-1:])
    check("the WSL path of a drive folder", terminal.to_wsl_path(Path("C:/Users/x y/pb")) in ("/mnt/c/Users/x y/pb", None))

    print("session log and run script")
    from plasbench import sessionlog
    log = sessionlog.SessionLog(tmp / "sl" / "sessions.jsonl")
    log.event("server_start", version="x", root=str(proj))
    log.event("job_start", job="j1", label="Check", command="plasbench check --yes", cwd=str(proj))
    log.event("job_input", job="j1", label="Check", answer="n")
    log.event("job_end", job="j1", label="Check", state="done", exit=0, seconds=1.0)
    log.event("job_start", job="j2", label="Run", command="plasbench run --cohort x", env={"THREADS": "4"}, cwd=str(proj))
    log.event("job_end", job="j2", label="Run", state="failed", exit=1, seconds=2.0)
    log.event("terminal", shell="posix", cwd=str(proj / "sub"), command="ls -la", exit=0, seconds=0.1)
    log.event("terminal", shell="posix", cwd=str(proj), command="false", exit=1, seconds=0.1)
    log.event("terminal", shell="powershell", cwd=str(proj), command="Get-ChildItem", exit=0, seconds=0.1)
    log.settings({"NCBI_API_KEY": "abc123secret", "THREADS": "8", "OLD": None})
    log.event("workspace", path=str(ws))
    evs = log.events()
    check("events are read back in order, for this session", [e["kind"] for e in evs][:3] == ["server_start", "job_start", "job_input"]
          and all(e["session"] == log.session for e in evs))
    check("a secret setting is never written", "abc123secret" not in (tmp / "sl" / "sessions.jsonl").read_text(encoding="utf-8"))
    check("every event reads as a sentence", all(sessionlog.describe(e) for e in evs) and
          sessionlog.describe(evs[1]).startswith("started Check"))
    sc = log.script(proj)
    lines = sc.splitlines()
    check("script: bash, defines plasbench for this folder", lines[0] == "#!/usr/bin/env bash" and "plasbench()" in sc)
    check("script: a successful command runs", "plasbench check --yes" in lines)
    check("script: a failed command is a comment, with its settings", "# THREADS=4 plasbench run --cohort x" in lines)
    check("script: answers are notes", "#   answered: n" in lines)
    check("script: terminal command runs in its folder", any(l.startswith("(cd ") and l.endswith("&& ls -la)") for l in lines))
    check("script: failed terminal command and PowerShell are comments", "# false" in lines and "# PowerShell: Get-ChildItem" in lines)
    check("script: workspace is exported", any(l.startswith("export PLASBENCH_WORKSPACE=") for l in lines))
    if bash:
        sp = tmp / "s.sh"
        sp.write_bytes(sc.encode("utf-8"))
        r = subprocess.run([bash, "-n", str(sp)], capture_output=True, text=True)
        check("script is valid bash", r.returncode == 0, r.stderr)
    check("sessions are listed with their event counts", log.sessions()[0]["events"] == len(evs))

    print("server")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"
    check("no running window for a folder without one", webui.running_instance(proj) is None)
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(path, body=None, tok=True):
        h = {"Host": f"127.0.0.1:{port}"}
        if tok:
            h["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")

    code, body, ctype = call("/logo.svg", tok=False)
    check("/logo.svg is served without the key", code == 200 and ctype.startswith("image/svg") and b"<svg" in body)
    code, body, ctype = call("/favicon.ico", tok=False)
    check("/favicon.ico is the PlasBench PNG", code == 200 and body[:4] == b"\x89PNG")
    code, _, _ = call("/api/terminal", tok=False)
    check("the terminal needs the session key", code == 403)
    code, body, _ = call("/api/terminal")
    st = json.loads(body)
    check("terminal state lists the shells", code == 200 and "shells" in st and "prompt" in st, st)
    code, body, _ = call("/api/terminal/run", {"command": "cd " + str(tmp)})
    check("terminal cd outside is a 400", code == 400 and b"outside" in body, body[:200])
    code, body, _ = call("/api/terminal/shell", {"shell": "nope"})
    check("an unknown shell is a 400", code == 400)
    code, body, _ = call("/api/platform")
    plat = json.loads(body)
    check("/api/platform gives info and a plan", code == 200 and plat["plan"]["mode"] in ("conda", "docker", "wsl"))
    code, body, _ = call("/api/terminal/run", {"command": "cd ~"})
    code, body, _ = call("/api/sessions")
    sj = json.loads(body)
    check("/api/sessions: this session's events, as sentences", code == 200 and sj["session"] and
          any(e["kind"] == "terminal" and e["text"] for e in sj["events"]), body[:300])
    code, body, ctype = call("/api/sessions/script")
    check("/api/sessions/script downloads a bash script", code == 200 and body.startswith(b"#!/usr/bin/env bash")
          and "shellscript" in ctype)
    code, _, _ = call("/api/sessions/script?session=../../etc")
    check("a malformed session id is refused", code == 400)
    code, _, _ = call("/api/sessions", tok=False)
    check("the session log needs the session key", code == 403)
    page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("page: Session log tab and Save as script", 'id="tab_sess"' in page and 'id="sscript"' in page)
    check("page: content is never hidden behind the fixed console (body min-height, bottom padding = console)",
          "body{margin:0;min-height:100%}" in page and "html,body{margin:0;height:100%}" not in page
          and "padding-bottom:var(--cons)" in page and "scroll-padding-bottom:calc(var(--cons)" in page)
    check("page: logo, favicon, Terminal tab, Quit, This computer",
          all(s in page for s in ('href="#pb-mark"', 'rel="icon"', 'id="tab_term"', 'id="quitbtn"', 'id="pc_card"')))
    # a job that is still running (recorded, no process): Quit must ask before stopping it
    jobs.jobs["fake"] = {"id": "fake", "label": "a long benchmark", "state": "running", "started": 1.0, "argv": [],
                         "kind": "plasbench"}
    code, body, _ = call("/api/shutdown", {})
    res = json.loads(body)
    check("Quit asks first while a job runs", code == 200 and res["ok"] is False and res["running"], res)
    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all desktop/window checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
