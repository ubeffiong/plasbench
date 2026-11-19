#!/usr/bin/env python3
"""The window's load path is cached, and the caches stay correct (plasbench/loadcache.py, docs/WINDOW_PERFORMANCE.md).

No wall-clock thresholds (they are flaky): the tests COUNT work. subprocess spawns, shutil.which calls and file opens are counted with injected counters, and the second
call of a load-path route must do none of it. Each cache is also checked for invalidation: a changed file, a changed setting, a created study and a forced refresh all show.
"""
import builtins
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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


class Counters:
    """Counts subprocess spawns, shutil.which calls and opens of chosen files while active."""

    def __init__(self, watch=()):
        self.spawn = self.which = 0
        self.opens = {}
        self.watch = watch

    def __enter__(self):
        self._run, self._popen, self._which, self._open = subprocess.run, subprocess.Popen, shutil.which, builtins.open
        me = self

        def run(*a, **k):
            me.spawn += 1
            return me._run(*a, **k)

        class Popen(subprocess.Popen):
            def __init__(self, *a, **k):
                me.spawn += 1
                super().__init__(*a, **k)

        def which(*a, **k):
            me.which += 1
            return me._which(*a, **k)

        def opened(file, *a, **k):
            name = str(file)
            for w in me.watch:
                if name.endswith(w):
                    me.opens[w] = me.opens.get(w, 0) + 1
            return me._open(file, *a, **k)
        subprocess.run, subprocess.Popen, shutil.which, builtins.open = run, Popen, which, opened
        return self

    def __exit__(self, *exc):
        subprocess.run, subprocess.Popen, shutil.which, builtins.open = self._run, self._popen, self._which, self._open


def main():
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "root"
    for d in ("config", "python", "cohorts", "docs", "adapters"):
        shutil.copytree(ROOT / d, root / d, ignore=shutil.ignore_patterns("__pycache__", "*.docx", "images", "implementation_catalogue", "sample_report", "releases", "reviews", "qa",
                                                                           "validation", "stats_validation"))
    shutil.copy(ROOT / "README.md", root / "README.md")
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "studies")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    os.environ["PLASBENCH_TOOLS_PATH"] = str(tmp / "tools")
    (tmp / "home").mkdir()
    import importlib
    from plasbench import loadcache, ui_schema
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"
    loadcache.reset_all()

    project = webui.Project(root)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(route, body=None, gz=False, raw=False):
        h = {"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN}
        if gz:
            h["Accept-Encoding"] = "gzip"
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
            h["Origin"] = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/{route}", data=data, headers=h)) as r:
            b = r.read()
            enc = r.headers.get("Content-Encoding")
        if raw:
            return b, enc
        return json.loads(gzip.decompress(b) if enc == "gzip" else b)

    def settle(route, done, tries=200):
        for _ in range(tries):
            r = call(route)
            if done(r):
                return r
            time.sleep(0.05)
        return r

    print("tools: filters come from the cache, the PATH probe runs once in the background")
    first = call("tools")
    check("the first call answers at once with every registry row", len(first["tools"]) >= 20, len(first["tools"]))
    done = settle("tools", lambda r: r["pending"] == 0)
    check("the probe finishes in the background (pending drops to 0)", done["pending"] == 0)
    check("rows with an executable have installed True/False once probed", all(isinstance(t["installed"], bool) for t in done["tools"] if t.get("executable")))
    watch = ("tool_capabilities.tsv", "tool_installers.tsv", "tool_database_releases.tsv", "config.sh", "local.env")
    with Counters(watch) as c:
        again = call("tools")
    check("a warm tools call spawns no process", c.spawn == 0, c.spawn)
    check("a warm tools call does not search PATH", c.which == 0, c.which)
    check("a warm tools call re-reads no registry or settings file", not c.opens, c.opens)
    check("a warm tools call returns the same rows", [t["tool"] for t in again["tools"]] == [t["tool"] for t in done["tools"]])
    check("tools() with block=True agrees with a direct shutil.which", all(t["installed"] == bool(shutil.which(t["executable"])) for t in project.tools() if t.get("executable")))

    print("tools: a changed registry file shows at once")
    caps = root / "config" / "tool_capabilities.tsv"
    text = caps.read_text(encoding="utf-8")
    lines = text.rstrip("\n").split("\n")
    header = next(i for i, l in enumerate(lines) if l and not l.startswith("#"))
    cols = lines[header].split("\t")
    sample = lines[header + 1].split("\t")
    new = dict(zip(cols, sample))
    new["tool"] = "zz_new_tool"
    time.sleep(0.6)   # a file's fingerprint is reused for loadcache.STAT_TTL (0.5 s)
    caps.write_text(text.rstrip("\n") + "\n" + "\t".join(new.get(c, "") for c in cols) + "\n", encoding="utf-8")
    names = [t["tool"] for t in call("tools")["tools"]]
    check("a tool added to config/tool_capabilities.tsv appears on the next call", "zz_new_tool" in names)
    time.sleep(0.6)
    caps.write_text(text, encoding="utf-8")
    check("and disappears when the file is restored", "zz_new_tool" not in [t["tool"] for t in call("tools")["tools"]])

    print("tools: a forced refresh probes again without blocking")
    r = call("tools?refresh=1")
    check("refresh=1 answers at once and marks rows checking", "pending" in r)
    settle("tools", lambda r: r["pending"] == 0)

    print("settings and env")
    s1 = call("settings")
    with Counters(watch) as c:
        call("settings")
    check("a warm settings call does not re-parse config.sh", not c.opens.get("config.sh"), c.opens)
    time.sleep(0.6)
    (tmp / "local.env").write_text("export THREADS=3\n", encoding="utf-8")
    s2 = call("settings")
    row = next(x for x in s2["settings"] if x["key"] == "THREADS")
    check("a saved setting (local.env changed) shows on the next call", row["override"] == "3", row.get("override"))
    check("the settings list is the same rows as before", [x["key"] for x in s1["settings"]] == [x["key"] for x in s2["settings"]])
    call("env")
    with Counters() as c:
        call("env")
    check("a warm env call spawns nothing and searches no PATH", c.spawn == 0 and c.which == 0, (c.spawn, c.which))

    print("platform: docker / wsl probes never block the page")
    p0 = call("platform")
    check("the first call answers at once (pending or ready)", p0.get("pending") is True or "info" in p0)
    p1 = settle("platform", lambda r: "info" in r)
    check("the probe result arrives", "info" in p1 and "plan" in p1)
    with Counters() as c:
        call("platform")
    check("a warm platform call spawns no process", c.spawn == 0, c.spawn)

    print("schema")
    b, enc = call("schema", raw=True)
    check("the schema is the same JSON the parser describes", json.loads(b) == json.loads(json.dumps(ui_schema.schema(), default=str)))
    s_before = loadcache.STATS["memo_miss"]
    call("schema")
    check("the second schema call builds nothing", loadcache.STATS["memo_miss"] == s_before)

    print("gzip")
    raw, enc = call("schema", gz=True, raw=True)
    check("a client that accepts gzip gets it, and it unpacks to the same JSON", enc == "gzip" and json.loads(gzip.decompress(raw)) == json.loads(call("schema", raw=True)[0]))
    raw2, enc2 = call("schema", raw=True)
    check("a client that does not ask for gzip gets plain JSON", enc2 is None and raw2[:1] == b"{")
    check("gzip is smaller", len(raw) < len(raw2) / 2, (len(raw), len(raw2)))

    print("runs, studies, cohorts")
    ws = tmp / "studies"
    for i in range(30):
        res = ws / f"s{i:02d}" / "results"
        res.mkdir(parents=True)
        (ws / f"s{i:02d}" / "study.json").write_text(json.dumps({"name": f"s{i:02d}", "runs": [{"started": "2026-01-01T00:00:00", "command": "plasbench run", "via": "window"}]}))
        (res / "benchmark.leaderboard.tsv").write_text("rank\ttool\ttask\tanalysis_track\tmean_f1\tmean_lw_bin_f1\n1\tmob_suite\tbinning_reconstruction\tshort_read\t0.9\t0.5\n")
        (res / "benchmark.report.html").write_text("<html></html>")
    r1 = call("runs")["runs"]
    check("30 study results folders are listed", sum(1 for r in r1 if r["study"]) == 30, len(r1))
    time.sleep(1.6)   # the 1.5 s sharing window of the studies list
    with Counters(("benchmark.leaderboard.tsv", "study.json")) as c:
        r2 = call("runs")["runs"]
    check("a warm runs call reads no leaderboard and no study.json", not c.opens, c.opens)
    check("and returns the same list", r1 == r2)
    lb = ws / "s03" / "results" / "benchmark.leaderboard.tsv"
    time.sleep(0.02)
    lb.write_text("rank\ttool\ttask\tanalysis_track\tmean_f1\tmean_lw_bin_f1\n1\tplaton\tbinning_reconstruction\tshort_read\t0.1\t0.1\n")
    time.sleep(1.6)
    r3 = {r["name"]: r for r in call("runs")["runs"]}
    check("a changed leaderboard shows (fingerprint: mtime and size)", r3["s03"]["leaders"][0]["tool"] == "platon", r3["s03"]["leaders"])
    created = call("studies/create", {"name": "fresh-study"})
    names = [s["name"] for s in call("workspace")["studies"]]
    check("a study created in the window is listed at once (the short-lived list is cleared on every change)", "fresh-study" in names, names[:5])
    c1 = call("cohorts")["cohorts"]
    with Counters() as c:
        c2 = call("cohorts")["cohorts"]
    check("cohorts: warm call identical", c1 == c2)
    big = root / "cohorts" / "zz_new.tsv"
    big.write_text("sample_id\torganism\n" + "".join(f"x{i}\te\n" for i in range(50)), encoding="utf-8")
    rows = {x["name"]: x for x in call("cohorts")["cohorts"]}
    check("a new cohort sheet shows with its row count", rows.get("zz_new", {}).get("rows") == 50, rows.get("zz_new"))
    time.sleep(0.6)
    big.write_text("sample_id\torganism\n" + "".join(f"x{i}\te\n" for i in range(70)), encoding="utf-8")
    rows = {x["name"]: x for x in call("cohorts")["cohorts"]}
    check("a grown cohort sheet shows its new row count", rows["zz_new"]["rows"] == 70, rows["zz_new"])

    print("page and static files")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/?t={webui.TOKEN}", headers={"Host": f"127.0.0.1:{port}", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req) as r:
        body, enc = r.read(), r.headers.get("Content-Encoding")
    check("the page is gzipped", enc == "gzip" and gzip.decompress(body).startswith(b"<!doctype html>") or gzip.decompress(body).lstrip().lower().startswith(b"<!doctype"))
    req = urllib.request.Request(f"http://127.0.0.1:{port}/logo.svg", headers={"Host": f"127.0.0.1:{port}"})
    with urllib.request.urlopen(req) as r:
        check("the logo may be cached by the browser for the version", "max-age" in (r.headers.get("Cache-Control") or ""))
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/info", headers={"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN})
    with urllib.request.urlopen(req) as r:
        check("API answers are never cached by the browser", r.headers.get("Cache-Control") == "no-store")

    print("loadcache units")
    loadcache.reset_all()
    n = []
    check("memo: computed once for one fingerprint", [loadcache.memo("k", 1, lambda: n.append(1) or 5) for _ in range(3)] == [5, 5, 5] and len(n) == 1)
    loadcache.memo("k", 2, lambda: n.append(1) or 6)
    check("memo: recomputed when the fingerprint changes", len(n) == 2)
    m = []
    loadcache.ttl("t", 60, lambda: m.append(1) or 1)
    loadcache.ttl("t", 60, lambda: m.append(1) or 1)
    check("ttl: shared inside the window", len(m) == 1)
    loadcache.clear(probes=False)
    loadcache.ttl("t", 60, lambda: m.append(1) or 1)
    check("ttl: clear() forgets it", len(m) == 2)
    val, ready = loadcache.swr("p", 60, lambda: (time.sleep(0.2), 7)[1], block=False)
    check("swr: with no answer yet and block=False returns (None, False) at once", (val, ready) == (None, False))
    for _ in range(100):
        val, ready = loadcache.swr("p", 60, lambda: 8, block=False)
        if ready:
            break
        time.sleep(0.05)
    check("swr: the background probe's answer arrives", (val, ready) == (7, True), (val, ready))
    loadcache.swr("q", 0.0, lambda: "old")
    val, ready = loadcache.swr("q", 0.0, lambda: (time.sleep(0.2), "new")[1])
    check("swr: an expired answer is returned at once (stale) while it refreshes", val == "old" and ready)
    time.sleep(0.5)
    check("swr: and the refreshed value follows", loadcache.swr("q", 60, lambda: "x")[0] == "new")
    a = loadcache.sig(tmp / "nope")
    check("sig: a missing file fingerprints as None", a == (None,))

    print("Tools filter component (node)")
    node = shutil.which("node")
    if node:
        done = subprocess.run([node, str(ROOT / "test" / "tool_filter_perf.js"), str(ROOT / "plasbench" / "data" / "ui.html")], capture_output=True, text=True, encoding="utf-8")
        print(done.stdout.rstrip())
        check("the filter renders 150 tools in one DOM write, debounced", done.returncode == 0, done.stderr[-300:])
    else:
        print("  SKIP: node is not installed (the filter-render check did not run)")

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("\nALL WINDOW LOAD TESTS PASSED")


if __name__ == "__main__":
    main()
