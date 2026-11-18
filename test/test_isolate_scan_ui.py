#!/usr/bin/env python3
"""The window's 'Scan a folder': routes over real HTTP (token, progress, cancel, add), static HTML checks, and the pure UI helpers under node."""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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


def write_fq(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as h:
        h.write("".join(f"@r{i}\nACGTACGTAC\n+\nIIIIIIIIII\n" for i in range(4)))


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    (tmp / "local.env").write_text("", encoding="utf-8")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"

    folder = tmp / "reads"
    for sid in ("A1", "B2"):
        write_fq(folder / sid / f"{sid}_R1.fastq.gz")
        write_fq(folder / sid / f"{sid}_R2.fastq.gz")
        (folder / sid / f"{sid}.fasta").write_text(">NZ_CP000001.1 complete genome\n" + "ACGT" * 6000 + "\n")
    before = {str(p): p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()}

    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, tok=True):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if tok:
            h["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}") if e.headers.get("Content-Type", "").startswith("application/json") else {}

    print("routes")
    check("scan needs the token", call("/api/isolates/scan", {"path": str(folder)}, tok=False)[0] == 403)
    check("status needs the token", call("/api/isolates/scan/status?id=x", tok=False)[0] == 403)
    check("add needs the token", call("/api/isolates/add", {}, tok=False)[0] == 403)
    check("a missing folder is refused with a message", call("/api/isolates/scan", {"path": str(tmp / "nope")})[0] == 400)
    code, r = call("/api/isolates/scan", {"path": str(folder)})
    check("a scan starts and returns an id", code == 200 and r.get("id"), r)
    sid = r["id"]
    st = {}
    for _ in range(100):
        st = call(f"/api/isolates/scan/status?id={sid}")[1]
        if st["state"] != "running":
            break
        time.sleep(0.1)
    check("it finishes with progress and a result of two ready isolates", st["state"] == "done" and st["progress"]["files"] >= 6
          and [s["sample_id"] for s in st["result"]["samples"]] == ["A1", "B2"] and all(s["status"] == "ready" for s in st["result"]["samples"]), st)
    check("an unknown scan id is a 404", call("/api/isolates/scan/status?id=zzz")[0] == 404)

    big = tmp / "big"
    for i in range(3000):
        (big / f"d{i % 50}").mkdir(parents=True, exist_ok=True)
        (big / f"d{i % 50}" / f"f{i}.txt").write_text("x")
    code, r = call("/api/isolates/scan", {"path": str(big)})
    call("/api/isolates/scan/cancel", {"id": r["id"]})
    for _ in range(100):
        st2 = call(f"/api/isolates/scan/status?id={r['id']}")[1]
        if st2["state"] != "running":
            break
        time.sleep(0.1)
    check("a scan can be cancelled (or had already finished) and is never left running", st2["state"] in ("cancelled", "done"), st2["state"])

    print("add")
    data_dir, sheet = tmp / "data", tmp / "sheet.tsv"
    code, r = call("/api/isolates/add", {"scan_id": sid, "include": ["A1", "B2"], "selections": {"B2": {"new_id": "B2-renamed"}}, "data_dir": str(data_dir), "samples": str(sheet)})
    check("selected isolates are placed, with a per-sample result and a rename", code == 200 and [x["sample_id"] for x in r["results"]] == ["A1", "B2-renamed"] and len(r["staged"]) == 2, r)
    check("files landed under the data folder and the sheet exists", (data_dir / "B2-renamed" / "B2-renamed_1.fastq.gz").is_file() and sheet.is_file())
    code, r = call("/api/isolates/add", {"scan_id": sid, "include": ["A1"], "selections": {"A1": {"reference": "/etc/hostname"}}, "data_dir": str(tmp / "d2"), "samples": str(tmp / "s2.tsv")})
    check("a file the scan did not list is refused, nothing written", code == 200 and not r["staged"] and not (tmp / "d2" / "A1").exists(), r)
    code, r = call("/api/isolates/add", {"scan_id": "nope", "include": ["A1"]})
    check("an unknown scan is an error", code == 404)
    check("the scanned folder was not modified", before == {str(p): p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()})
    server.shutdown()

    print("static page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    block = html[html.index("BEGIN scan a folder (plasbench/isolate_scan.py) -->"):html.index("<!-- END scan a folder -->")]
    check("the section exists with its controls", all(i in block for i in ('id="sc_pick"', 'id="sc_go"', 'id="sc_cancel"', 'id="sc_out"', "What is recognised", "never changes your folder")))
    js = html[html.index("BEGIN scan a folder (plasbench/isolate_scan.py) ----"):html.index("END scan a folder ----")]
    check("no browser confirm/prompt/alert in the new code", not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js.replace("askConfirm(", "")), re.findall(r"(?<![.\w])(?:confirm|prompt|alert)\(", js))
    check("the picker, status polling, cancel and add routes are wired", all(x in js for x in ("pickPath(", "isolates/scan/status", "isolates/scan/cancel", "isolates/add", "askConfirm(")))
    check("dropdowns are wired to alternatives (reference and reads) and recorded without re-rendering", "\"scref\"" in js and "\"screads\"" in js and "alternatives.reference" in js and "alternatives.reads" in js
          and js.count("scnRender(") == 2)
    check("rows are keyed by sample id", 'data-sc="${esc(id)}"' in js)

    print("pure helpers under node")
    node = shutil.which("node")
    if not node:
        print("  skip  node not found")
    else:
        helpers = js[js.index("/* BEGIN isoscan helpers (pure) */"):js.index("/* END isoscan helpers */")]
        test = helpers + """
const assert = require('assert');
const S = [{sample_id:'A', issues:[], status:'ready', why:{reads:['r'],reference:['x','y'],sequence_report:[],truth:[]}},
           {sample_id:'B', issues:[{level:'warn'}], status:'review', why:{reads:[],reference:[],sequence_report:[],truth:[]}}];
let p = scnPayload(S, {A:{reference:'/r.fa', new_id:'A2', reads_1:''}}, {A:true, B:false});
assert.deepStrictEqual(p, {include:['A'], selections:{A:{reference:'/r.fa', new_id:'A2'}}});
assert.deepStrictEqual(scnPayload(S, {}, {A:true,B:true}), {include:['A','B'], selections:{}});
assert.strictEqual(scnNeedsConfirm(S, {A:true}), false);
assert.strictEqual(scnNeedsConfirm(S, {A:true,B:true}), true);
assert.strictEqual(scnBase('C:\\\\x\\\\y\\\\f.fq.gz'), 'f.fq.gz');
assert.deepStrictEqual(scnWhy(S[0]), [['Reads','r'],['Reference','x; y']]);
assert.deepStrictEqual(scnStatus('blocked'), ['bad','blocked']);
assert.ok(/12 files/.test(scnProgressText({files:12, folders:3})));
console.log('helpers ok');
"""
        f = tmp / "helpers.js"
        f.write_text(test, encoding="utf-8")
        done = subprocess.run([node, str(f)], capture_output=True, text=True)
        check("scnPayload, scnNeedsConfirm, scnWhy, scnBase, scnStatus, scnProgressText behave", done.returncode == 0 and "helpers ok" in done.stdout, done.stderr[-400:])

    print("ALL ISOLATE SCAN UI TESTS PASSED" if not FAILED else f"FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
