#!/usr/bin/env python3
"""Internet-dependent services, globally (plasbench/netgate.py and the routes that start network work), over the real plasbench/netcheck.py (tests inject a backend or use its PLASBENCH_OFFLINE / PLASBENCH_ASSUME_ONLINE switches; nothing here reaches the network).

  - every state of the contract (online, offline, dns_broken, limited, forced_offline, assumed_online) comes through /api/net/status in its shape; with the real netcheck PLASBENCH_ASSUME_ONLINE=1 is
    assumed_online and PLASBENCH_OFFLINE=1 is forced_offline; a failing check never raises; the services, states, default timeout and command table are netcheck's;
  - require / require_any / services_for_job: a download run needs NCBI and a read source (SRA or ENA); a fully local run (--local-inputs, a stage list without 1, the metagenomics track, reads already
    on disk) needs nothing and still starts offline; install, update and discovery commands name their services;
  - offline, POST /api/jobs for a network command, a git network operation, the update check and the sign-in answer 503 {error: offline, service, state, advice, message} and start nothing;
  - offline never blocks local things: the workspace, settings, studies, the folder tree and docs keep answering;
  - the page: every control that needs the internet carries data-needs, the indicator, gating with aria-description, the re-check at the click, and a 503 handler.
"""
import json
import os
import re
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
os.environ.pop("PLASBENCH_OFFLINE", None)
from plasbench import netgate, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


class NoInternet(Exception):
    def __init__(self, service, state, advice, message):
        super().__init__(message)
        self.service, self.state, self.advice, self.message = service, state, advice, message


def backend(state, down=()):
    class B:
        @staticmethod
        def check(services=None, timeout=3.0):
            names = services or ["internet", "github", "ncbi", "sra", "ena"]
            return {"online": state in ("online", "assumed_online", "limited"), "state": state, "checked": time.time(),
                    "services": {n: {"ok": n not in down and state in ("online", "limited", "assumed_online"), "ms": 12, "error": "" if n not in down else "dns failure", "kind": "" if n not in down else "dns"} for n in names},
                    "advice": [] if state == "online" else ["Check your connection."]}

        @staticmethod
        def require(service, action=""):
            names = [service] if isinstance(service, str) else list(service)
            bad = [n for n in names if n in down or state in ("offline", "dns_broken", "forced_offline")]
            if bad:
                raise NoInternet(bad[0], state, ["Check your connection."], f"Needs the internet: {bad[0]} is unreachable.")
    return B


def main():
    print("states")
    for state in ("online", "offline", "dns_broken", "limited", "forced_offline", "assumed_online"):
        netgate.set_backend(backend(state))
        out = netgate.status()
        check(f"{state}: the contract's shape", out["state"] == state and isinstance(out["services"], dict) and isinstance(out["advice"], list) and "checked" in out and "online" in out, out)
    netgate.set_backend(None)
    os.environ["PLASBENCH_ASSUME_ONLINE"] = "1"
    check("the real netcheck, assumed online: nothing blocked", netgate.status()["state"] == "assumed_online" and netgate.require("github") is None)
    os.environ.pop("PLASBENCH_ASSUME_ONLINE")
    os.environ["PLASBENCH_OFFLINE"] = "1"
    check("PLASBENCH_OFFLINE=1 with the real netcheck: forced_offline, and require refuses", netgate.status()["state"] == "forced_offline" and netgate.status()["online"] is False)
    try:
        netgate.require("ncbi", "download")
        forced = False
    except netgate.Offline as exc:
        forced = exc.state == "forced_offline" and exc.payload()["error"] == "offline"
    check("forced offline names the setting", forced)
    os.environ.pop("PLASBENCH_OFFLINE")
    from plasbench import netcheck
    check("the adapter's services are the catalogue's (config/network_services.tsv)", set(netgate.SERVICES) == {r["service"] for r in netcheck.load_catalogue(ROOT / "config" / "network_services.tsv")} and "ncbi" in netgate.SERVICES)
    seen = []
    class Probe:
        @staticmethod
        def check(services=None, timeout=None):
            seen.append(timeout)
            return {"online": True, "state": "online", "checked": 0, "services": {}, "advice": []}
    netgate.set_backend(Probe)
    netgate.status()
    check("the default timeout is netcheck's (5 s), not the adapter's own", seen == [None] and netcheck.DEFAULT_TIMEOUT == 5.0, seen)
    unknown = sorted({s for v in netgate.NET_COMMANDS.values() if v for s in v} | {s for d in netgate.SUBCOMMAND_NET.values() for v in d.values() for s in v} | {s for _, v in netgate.FLAG_NET.values() for s in v} - set(netcheck.SERVICES))
    check("every service the command tables name is a catalogue service", not [s for s in unknown if s not in netcheck.SERVICES], unknown)
    check("the command table is the one `plasbench <command>` uses", all(netgate.NET_COMMANDS.get(c) is not None or c in netgate.SUBCOMMAND_NET or (c, sub) in netgate.FLAG_NET for (c, sub) in netcheck.command_table()))

    class Broken:
        @staticmethod
        def check(*a, **k):
            raise RuntimeError("boom")

        @staticmethod
        def require(*a, **k):
            raise RuntimeError("boom")
    netgate.set_backend(Broken)
    check("a failing check never raises and never blocks local work", netgate.status()["state"] == "assumed_online" and netgate.require("github") is None)

    print("what needs what")
    netgate.set_backend(backend("offline"))
    run = ["run", "--cohort", "public-v4"]
    check("a download run needs ncbi plus a read source (sra or ena)", netgate.services_for_job(run) == {"all": ["ncbi"], "any": ["sra", "ena"]}, netgate.services_for_job(run))
    check("READ_SOURCE=ena needs ena only", netgate.services_for_job(run, {"READ_SOURCE": "ena"})["any"] == ["ena"])
    for label, argv, env in (("--local-inputs", ["run", "-s", "x.tsv", "--local-inputs"], {}), ("LOCAL_INPUTS_ONLY=1", run, {"LOCAL_INPUTS_ONLY": "1"}), ("the metagenomics track", ["run", "--mode", "meta", "-s", "x.tsv"], {}), ("stages 5 and 6 only", ["run", "5", "6"], {}), ("a report", ["report", "--study", "s"], {})):
        check(f"{label}: needs nothing", netgate.services_for_job(argv, env) == {"all": [], "any": []}, label)
    check("reads already on disk: needs nothing", netgate.services_for_job(run, reads_present=lambda: True) == {"all": [], "any": []})
    check("reads missing: a download", netgate.services_for_job(run, reads_present=lambda: False)["all"] == ["ncbi"])
    check("install, update and discovery commands name their services", netgate.command_services(["install-tools", "all"]) == ["conda", "github", "pypi"] and netgate.command_services(["upgrade"]) == ["github"] and netgate.command_services(["discover-cohort"]) == ["ncbi", "ncbi_datasets"]
          and netgate.command_services(["tools", "install", "x"]) == ["conda"] and netgate.command_services(["tools", "list"]) == [] and netgate.command_services(["check"]) == [])
    check("git: github.com remotes need github, others need the internet", netgate.git_services("https://github.com/o/r.git") == ["github"] and netgate.git_services("git@github.com:o/r.git") == ["github"] and netgate.git_services("https://gitlab.example.org/o/r") == ["internet"])
    netgate.set_backend(backend("online", down=("sra",)))
    check("require_any: reads can still come from ENA when only SRA is down", netgate.require_job(run, {}, reads_present=lambda: False) is None)
    netgate.set_backend(backend("online", down=("sra", "ena")))
    try:
        netgate.require_job(run, {}, reads_present=lambda: False)
        both = False
    except netgate.Offline as exc:
        both = exc.service in ("sra", "ena")
    check("require_any: refused when neither SRA nor ENA is reachable", both)

    print("routes, offline")
    netgate.set_backend(backend("offline"))
    (tmp / "ws").mkdir(exist_ok=True)
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    started = []
    jobs.start = lambda *a, **k: started.append(a) or {"id": "x"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(path, body=None, token=True):
        h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
    code, body = call("/api/net/status")
    check("GET /api/net/status: the state, the services, the advice and the command table", code == 200 and body["state"] == "offline" and "services" in body and body["advice"] and "install-tools" in body["commands"], body.keys())
    check("it needs the token", call("/api/net/status", token=False)[0] == 403)
    code, body = call("/api/net/status?services=github,ncbi")
    check("services can be asked for by name", code == 200 and set(body["services"]) == {"github", "ncbi"}, body["services"])
    netgate.set_backend(None)
    os.environ["PLASBENCH_OFFLINE"] = "1"
    code, body = call("/api/net/status")
    direct = netcheck.check()
    check("/api/net/status agrees with netcheck.check: same state, same service names (the catalogue's), same advice", code == 200 and body["state"] == direct["state"] == "forced_offline" and set(body["services"]) == set(direct["services"]) and body["advice"] == direct["advice"], (body["state"], direct["state"]))
    code, body = call("/api/update-check")
    check("with the real netcheck, forced offline: the update check answers 503 naming the state", code == 503 and body["state"] == "forced_offline" and body["service"] == "github", body)
    os.environ.pop("PLASBENCH_OFFLINE")
    netgate.set_backend(backend("offline"))
    for label, route, payload in (("a cohort run", "/api/jobs", {"argv": ["run", "--cohort", "public-v4"]}), ("install-tools", "/api/jobs", {"argv": ["install-tools", "core"]}), ("upgrade", "/api/jobs", {"argv": ["upgrade"]}),
                                  ("discover-cohort", "/api/jobs", {"argv": ["discover-cohort"]}), ("a git push", "/api/git", {"op": "clone", "url": "https://github.com/o/r.git", "dest": str(tmp / "c")}), ("the update check", "/api/update-check", None)):
        code, body = (call(route, payload) if payload is not None else call(route))
        check(f"{label}: 503 {{error: offline, service, state, advice}}", code == 503 and body["error"] == "offline" and body["service"] and body["state"] == "offline" and isinstance(body["advice"], list) and body["message"], (code, body))
    check("nothing was started", not started, started)
    sheet = tmp / "s.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\nA\tGCF_1.1\tSRR1\n", encoding="utf-8")
    code, body = call("/api/jobs", {"argv": ["run", "-s", str(sheet), "--local-inputs", "--write-script", str(tmp / "o.sh")]})
    check("a fully local run still starts offline", code == 200 and started, (code, body))
    data = tmp / "data"
    (data / "A").mkdir(parents=True)
    (data / "A" / "A_1.fastq.gz").write_bytes(b"x")
    (data / "A" / "A_2.fastq.gz").write_bytes(b"x")
    (data / "A" / "ref.fna").write_bytes(b"x")
    started.clear()
    code, body = call("/api/jobs", {"argv": ["run", "-s", str(sheet), "--data-dir", str(data), "--write-script", str(tmp / "o2.sh")]})
    check("a run whose reads and reference are already in the data folder starts offline", code == 200 and started, (code, body))
    started.clear()
    (data / "A" / "A_2.fastq.gz").unlink()
    code, body = call("/api/jobs", {"argv": ["run", "-s", str(sheet), "--data-dir", str(data), "--write-script", str(tmp / "o3.sh")]})
    check("with the reads incomplete the same run is refused offline", code == 503 and not started, (code, body))
    for path in ("/api/info", "/api/workspace", "/api/settings", "/api/cohorts", "/api/fs/list?path=", "/api/schema", "/api/tools", "/api/docs"):
        check(f"offline: {path} still answers", call(path)[0] == 200, path)
    server.shutdown()
    netgate.set_backend(None)

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the Online / Offline indicator in the top bar with a tooltip and a re-check", 'id="netind"' in html and "showNetDialog" in html and "Check again" in html and "setInterval(() => { if (!document.hidden && !uiBusy([])) netRefresh(); }, 30000)" in html)
    check("gating: disabled-with-a-reason, still focusable, aria-description", 'setAttribute("aria-description", why)' in html and 'setAttribute("aria-disabled", "true")' in html and ".needs-net-off" in html and "Needs the internet:" in html)
    check("the click re-checks at that moment and shows a dialog if still unreachable", 'await netRefresh(true);' in html and "showOfflineDialog(q)" in html and 'closest("[data-needs], [data-run]")' in html)
    check("a 503 from the server shows the same dialog", 'r.status === 503 && data.error === "offline"' in html and "showOfflineDialog({service: data.service" in html)
    check("the indicator uses the keyed-patch helper (no flicker)", "setIfChanged(b," in html)
    needs = set(re.findall(r'data-needs="([a-z]+)"', html))
    check("controls are marked with their service", "github" in needs, needs)
    for ident in ("g_fetch", "g_pull", "g_push", "gc_go", "gd_fetch", "gd_pull", "gd_push", "gd_gh", "g_ghcreate", "updcheck", "gh_create", "gh_clone", "gh_newpr", "gh_prs", "gh_checks", "gh_issues", "gh_releases"):
        check(f"{ident} is marked data-needs", re.search(r'id="' + ident + r'"[^>]*data-needs="|data-needs="[^"]*"[^>]*id="' + ident + '"', html) is not None, ident)
    check("buttons that run network commands are gated through the command table", "netNeedsFor" in html and "S.netCommands" in html)
    check("no browser confirm / prompt / alert", not re.search(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", html.split("let DLG_N = 0;")[0] + html.split("/* ---- help tooltip: an (i) button")[1]))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
