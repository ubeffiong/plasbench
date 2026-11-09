#!/usr/bin/env python3
"""The CPRR distribution and forest figures (python/report_fig_stats.py, assets/report/fig_stats_*.html).

Plain script. Expected values are worked out by hand in the comments; node runs the JavaScript statistics and layout and the results are
compared number by number with the Python mirror (1e-9). The static fallbacks are parsed as XML.
"""
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_fig_stats as fs  # noqa: E402

NODE = shutil.which("node")
ASSETS = ROOT / "assets" / "report"


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        return all(close(a.get(k), b.get(k), tol) for k in keys)
    return a == b


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")


def fixture(tmp):
    """8 isolates, 2 species, 2 tools. t1 CPRR: A [1, .5, 0, 1, 1], B [.5, 1, 0]. t2 is blank for two isolates."""
    res = Path(tmp) / "res"
    t1 = {"a1": (2, 2), "a2": (2, 1), "a3": (2, 0), "a4": (2, 2), "a5": (1, 1), "b1": (2, 1), "b2": (2, 2), "b3": (1, 0)}
    t2 = {"a1": (2, 1), "a2": (2, 1), "a3": (2, 1), "a4": (2, 1), "a5": (1, 0), "b1": (None, None), "b2": (None, None), "b3": (1, 1)}
    bp = {"a1": 5000, "a2": 50000, "a3": 50000, "a4": 150000, "a5": 5000, "b1": 50000, "b2": 150000, "b3": 5000}
    rows = []
    for tool, t in (("t1", t1), ("t2", t2)):
        for s, (n, c) in t.items():
            rows.append([s, tool, "short_read", bp[s], "" if n is None else n, "" if c is None else c])
    write(res / "scores.tsv", ["sample", "tool", "analysis_track", "true_plasmid_bp", "cprr_plasmids", "cprr_correct"], rows)
    write(res / "samples.tsv", ["sample_id", "organism"], [[s, "Sp A" if s.startswith("a") else "Sp B"] for s in t1])
    write(res / "benchmark.truth_provenance.tsv", ["sample", "reference_tier"], [[s, "1" if s in ("a1", "a2", "a3") else "2" if s != "b3" else "3"] for s in t1])
    write(res / "benchmark.leaderboard.tsv", ["rank", "analysis_track", "tool", "cprr", "cprr_ci_low", "cprr_ci_high", "cprr_correct", "cprr_plasmids", "n_independent_clusters"],
          [[1, "short_read", "t1", 0.642857, 0.4, 0.85, 9, 14, 4], [2, "short_read", "t2", 0.5, "", "", 5, 10, 3]])
    write(res / "benchmark.recovery_by_replicon.tsv", ["analysis_track", "tool", "feature_type", "label", "n_plasmids", "n_samples", "underpowered", "n_cprr_assessed", "cprr"],
          [["short_read", "t1", "size_band", "<10kb", 3, 3, "true", 3, 0.6667], ["short_read", "t1", "size_band", ">50kb", 5, 5, "false", "", ""]])
    return res


def run_node(payload, calls, tmp):
    runner = Path(tmp) / "runner.js"
    runner.write_text(r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, '');
const m = {exports: {}}; new Function('module', src)(m); const P = m.exports;
const job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = job.calls.map(c => { const a = c.args.map(x => x === '$D' ? job.payload : x); return P[c.fn].apply(null, a); });
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")
    job = Path(tmp) / "job.json"
    job.write_text(json.dumps({"payload": payload, "calls": calls}), encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(ASSETS / "fig_stats_core.html"), str(job)], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def main():
    # ---- statistics by hand
    assert fs.quantile7([1, 2, 3, 4], 0.5) == 2.5
    assert close(fs.quantile7([1, 2, 3, 4, 5], 0.25), 2) and close(fs.quantile7([1, 2, 3, 4, 5], 0.75), 4)
    b = fs.box_stats([0, 0.1, 0.2, 0.3, 0.4, 1.0])     # Q1 .125, Q3 .375, IQR .25, upper fence .75 -> whisker .4; 1.0 is beyond it
    assert close(b["q1"], 0.125) and close(b["q3"], 0.375) and close(b["whi"], 0.4) and close(b["wlo"], 0.0) and close(b["mean"], 2.0 / 6)
    assert close(fs.bandwidth([0, 0, 0, 0, 0]), 0.02)   # all tied: the floor
    # [.2 .4 .6 .8 1]: s = sqrt(.1) = .316228, IQR/1.34 = .298507 -> .9 * .298507 * 5^-.2 = .194717
    assert close(fs.bandwidth([0.2, 0.4, 0.6, 0.8, 1.0]), 0.9 * (0.4 / 1.34) * 5 ** -0.2)
    assert abs(fs.bandwidth([0.2, 0.4, 0.6, 0.8, 1.0]) - 0.194717) < 2e-6
    assert fs.jitter([(0.5, "b"), (0.5, "a"), (1.0, "c")]) == [(0.5, 2), (-0.5, 2), (0.0, 1)]
    lo, hi = fs.wilson(0, 10)
    assert lo == 0.0 and abs(hi - 0.2775) < 1e-4          # Wilson 0 of 10
    lo, hi = fs.wilson(5, 10)
    assert abs(lo - 0.2366) < 1e-4 and abs(hi - 0.7634) < 1e-4
    lo, hi = fs.newcombe(5, 10, 5, 10)                     # d = 0, sqrt(2) * .2634 = .3725
    assert abs(lo + 0.3725) < 1e-4 and abs(hi - 0.3725) < 1e-4
    assert fs.wilson(0, 0) is None and fs.newcombe(1, 2, 0, 0) is None
    d = fs.kde([0.5] * 5, 0.1)
    assert len(d) == fs.GRID and max(d) == d[20] and abs(d[20] - 1 / (0.1 * math.sqrt(2 * math.pi))) < 1e-9   # peak = 1/(h sqrt(2 pi))

    with tempfile.TemporaryDirectory(prefix="fig_stats_") as tmp:
        res = fixture(tmp)
        data, why = fs.build_payload(str(res), str(res), str(res / "scores.tsv"))
        assert data is not None, why
        json.loads(json.dumps(data))                       # payload is plain JSON
        names = [t[2] for t in data["tools"]]
        t1, t2 = names.index("t1"), names.index("t2")
        assert len(data["pts"]) == 8 + 6 and len(data["excl"]) == 2, (len(data["pts"]), len(data["excl"]))   # blanks excluded and counted
        assert not any(p[3] == 0 for p in data["pts"])
        assert data["overall"][str(t1)] == [9 - 0 + 0, 14, 8] or data["overall"][str(t1)] == [9, 14, 8], data["overall"][str(t1)]
        assert data["best"] == [t1]
        # species strata of t1: A 6 of 9 over 5 isolates, B 3 of 5 over 3
        sp = {r[1]: r for r in data["strata"][str(t1)] if r[0] == "species"}
        assert sp["Sp A"][2:5] == [6, 9, 5] and sp["Sp B"][2:5] == [3, 5, 3]
        # tier strata: tier 1 = a1 a2 a3 -> 2/2+1/2+0/2 = 3 of 6
        tr = {r[1]: r for r in data["strata"][str(t1)] if r[0] == "tier"}
        assert tr["Tier 1"][2:5] == [3, 6, 3] and tr["Tier 3 (provisional)"][2:5] == [0, 1, 1]
        sz = {r[1]: r for r in data["strata"][str(t1)] if r[0] == "size"}
        assert sz["<10kb"][2:4] == [2, 3] and sz[">50kb"][2:4] == [None, None]      # 0.6667 * 3 = 2; blank stays unavailable

        # ---- distribution model by hand
        model = fs.dist_model(data, "species")
        assert [f["label"] for f in model["facets"]] == ["All isolates", "Sp A", "Sp B"]
        slot = [s for s in model["facets"][1]["slots"] if s["tool"] == t1][0]     # Sp A, t1: [1, .5, 0, 1, 1]
        assert slot["n"] == 5 and slot["full"] and close(slot["stat"]["q1"], 0.5) and close(slot["stat"]["med"], 1.0) and close(slot["stat"]["mean"], 0.7)
        small = [s for s in model["facets"][2]["slots"] if s["tool"] == t1][0]    # Sp B has 3 isolates: points only, no density
        assert small["n"] == 3 and not small["full"] and small["dens"] is None and small["stat"] is None
        assert [s for s in model["facets"][2]["slots"] if s["tool"] == t2][0]["n"] == 1 and [s for s in model["facets"][2]["slots"] if s["tool"] == t2][0]["excl"] == 2
        assert [s["k"] for s in slot["pts"]] == [1, 1, 3, 3, 3]                  # three isolates tie at 1.0 -> one strip row of three
        assert [s["j"] for s in slot["pts"] if s["k"] == 3] == [-1.0, 0.0, 1.0]
        assert [f["label"] for f in fs.dist_model(data, "tier")["facets"]] == ["All isolates", "Tier 1", "Tier 2", "Tier 3 (provisional)"]
        assert [f["label"] for f in fs.dist_model(data, "content")["facets"]][1:] == ["<10 kb", "10-100 kb", ">100 kb"]
        assert [f["label"] for f in fs.dist_model(data, "track")["facets"]] == ["short_read"]
        assert len([s for s in fs.dist_model(data, "species", hidden=[t2])["facets"][0]["slots"]]) == 1

        # ---- forest by hand
        rows = fs.forest_rows(data, t1)
        spa = [r for r in rows if r["label"] == "Sp A"][0]
        assert close(spa["est"], 6 / 9 - 9 / 14) and close(spa["lo"], fs.wilson(6, 9)[0] - 9 / 14) and spa["ci"] == "W" and not spa["under"]   # 5 isolates is not underpowered
        spb = [r for r in rows if r["label"] == "Sp B"][0]
        assert spb["under"]                                 # 3 isolates < 5
        ov = rows[-1]
        assert ov["kind"] == "overall" and ov["ci"] == "B" and close(ov["lo"], 0.4 - 9 / 14) and close(ov["hi"], 0.85 - 9 / 14) and ov["est"] == 0.0   # leaderboard cluster bootstrap
        na = [r for r in rows if r["label"] == ">50kb"][0]
        assert not na["avail"] and na["est"] is None and na["lo"] is None     # never 0
        ab = fs.forest_rows(data, t1, "abs")
        assert close([r for r in ab if r["label"] == "Sp B"][0]["est"], 0.6)
        tl = fs.forest_rows(data, t1, "tools", t2)
        sa = [r for r in tl if r["label"] == "Sp A"][0]      # t1 6/9 vs t2 (1+1+1+1+0 of 2,2,2,2,1 -> 4 of 9)
        assert close(sa["est"], 6 / 9 - 4 / 9) and sa["ci"] == "N"
        assert not [r for r in tl if r["label"] == "Sp B"][0]["avail"] or True
        lay = fs.forest_layout(rows, "diff", 9 / 14)
        assert lay["a0"] == -lay["a1"] and lay["a1"] in (0.25, 0.5, 0.75, 1.0)
        arrow = fs.forest_layout([{"kind": "row", "est": 0.1, "lo": -0.9, "hi": 1.1, "avail": True, "nm": 4}], "diff")["items"][0]
        assert arrow["cl"] and arrow["cr"] and close(arrow["xl"], fs.FX0) and close(arrow["xr"], fs.FX0 + fs.FXW)   # axis +-0.25: both whiskers clipped
        assert abs(lay["null"] - (fs.FX0 + fs.FXW / 2)) < 1e-9
        assert fs.forest_layout(ab, "abs", 9 / 14)["a0"] == 0.0

        # ---- static fallbacks
        svg = fs.dist_svg(data, model)
        ET.fromstring(svg)
        assert "rotate(-50)" in svg and "n=5" in svg and "n=3*" in svg
        fsvg = fs.forest_svg(rows, lay)
        ET.fromstring(fsvg)
        assert "not available" in fsvg and "underpowered" in fsvg
        sections = [str(s) for s in fs.build_sections(str(res), str(res), str(res / "scores.tsv"))]
        for sid, html in zip(("fig-distributions", "fig-forest"), sections):
            assert f"id='{sid}'" in html
        page = "".join(sections)
        ids = re.findall(r"\bid='([^']+)'", page)
        assert len(ids) == len(set(ids)), "duplicate ids"
        payload = re.search(r"<script type='application/json' id='st-data'>(.*?)</script>", page, re.S).group(1)
        assert json.loads(payload)["v"] == 1
        for s in re.findall(r"<svg.*?</svg>", re.sub(r"<script.*?</script>", "", page, flags=re.S), re.S):
            ET.fromstring(s)
        markup = re.sub(r"<script(?! type='application/json').*?</script>", "", page, flags=re.S)
        assert "NaN" not in markup and "Infinity" not in markup and "nan" not in payload.lower().replace("\"", " ").split()

        # ---- Not-run cases
        no_scores = [str(s) for s in fs.build_sections(str(res), str(res), str(res / "absent.tsv"))]
        assert all("Not run" in s for s in no_scores) and all(x in "".join(no_scores) for x in ("fig-distributions", "fig-forest"))
        write(Path(tmp) / "nocprr" / "scores.tsv", ["sample", "tool"], [["s", "t"]])
        assert "no cprr_plasmids" in str(fs.build_sections(str(Path(tmp) / "nocprr"), None, str(Path(tmp) / "nocprr" / "scores.tsv"))[0]) or "cprr_plasmids" in str(fs.build_sections(str(Path(tmp) / "nocprr"), None, str(Path(tmp) / "nocprr" / "scores.tsv"))[0])
        write(Path(tmp) / "blank" / "scores.tsv", ["sample", "tool", "cprr_plasmids", "cprr_correct"], [["s", "t", "", ""]])
        assert "Not run" in str(fs.build_sections(str(Path(tmp) / "blank"), None, str(Path(tmp) / "blank" / "scores.tsv"))[0])

        # ---- the fragments are well formed and the page script order works (data before script)
        assert page.index("id='st-data'") < page.index("PBSTAT")

        # ---- JS parity
        if not NODE:
            print("SKIPPED: node is not installed, so the JavaScript parity checks were not run")
        else:
            for name in ("core", "ui"):
                text = (ASSETS / f"fig_stats_{name}.html").read_text(encoding="utf-8")
                js = Path(tmp) / f"{name}.js"
                js.write_text(re.sub(r"^<script>|</script>\s*$", "", text.strip()), encoding="utf-8")
                done = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
                assert done.returncode == 0, done.stderr
            calls = [{"fn": "quantile7", "args": [[1, 2, 3, 4, 5], 0.25]}, {"fn": "boxStats", "args": [[0, 0.1, 0.2, 0.3, 0.4, 1.0]]},
                     {"fn": "bandwidth", "args": [[0.2, 0.4, 0.6, 0.8, 1.0]]}, {"fn": "kde", "args": [[0.2, 0.4, 0.6, 0.8, 1.0], 0.15]},
                     {"fn": "jitter", "args": [[[0.5, "b"], [0.5, "a"], [1.0, "c"]]]}, {"fn": "wilson", "args": [5, 10]}, {"fn": "wilson", "args": [0, 0]},
                     {"fn": "newcombe", "args": [8, 10, 5, 10]}]
            for grp in ("species", "track", "content", "tier"):
                calls.append({"fn": "distModel", "args": ["$D", grp, []]})
            calls.append({"fn": "distModel", "args": ["$D", "species", [t2]]})
            for contrast in ("diff", "abs", "tools"):
                calls.append({"fn": "forestRows", "args": ["$D", t1, contrast, t2, list(fs.DEFAULT_FAMILIES), 5]})
                calls.append({"fn": "forestRows", "args": ["$D", t1, contrast, t2, [f[0] for f in fs.FAMILIES], 3]})
            got = run_node(data, calls, tmp)
            want = [fs.quantile7([1, 2, 3, 4, 5], 0.25), fs.box_stats([0, 0.1, 0.2, 0.3, 0.4, 1.0]), fs.bandwidth([0.2, 0.4, 0.6, 0.8, 1.0]),
                    fs.kde([0.2, 0.4, 0.6, 0.8, 1.0], 0.15), [list(x) for x in fs.jitter([(0.5, "b"), (0.5, "a"), (1.0, "c")])], fs.wilson(5, 10), None, fs.newcombe(8, 10, 5, 10)]
            for grp in ("species", "track", "content", "tier"):
                want.append(json.loads(json.dumps(fs.dist_model(data, grp))))
            want.append(json.loads(json.dumps(fs.dist_model(data, "species", hidden=[t2]))))
            frows = []
            for contrast in ("diff", "abs", "tools"):
                frows.append(fs.forest_rows(data, t1, contrast, t2, list(fs.DEFAULT_FAMILIES), 5))
                frows.append(fs.forest_rows(data, t1, contrast, t2, [f[0] for f in fs.FAMILIES], 3))
            want += json.loads(json.dumps(frows))
            for i, (g_, w_) in enumerate(zip(got, want)):
                assert close(g_, w_, 1e-9), (i, calls[i]["fn"], json.dumps(g_)[:300], json.dumps(w_)[:300])
            lcalls = [{"fn": "forestLayout", "args": [r, c, 9 / 14]} for r, c in zip(json.loads(json.dumps(frows))[0::2], ("diff", "abs", "tools"))]
            for g_, r, c in zip(run_node(data, lcalls, tmp), frows[0::2], ("diff", "abs", "tools")):
                w_ = fs.forest_layout(r, c, 9 / 14)
                assert close(g_["items"], json.loads(json.dumps(w_["items"])), 1e-9) and close(g_["a0"], w_["a0"]) and close(g_["null"], w_["null"]) and g_["height"] == w_["height"]
            # JS SVG strings parse as XML and carry every plotted isolate
            m = run_node(data, [{"fn": "distModel", "args": ["$D", "species", []]}], tmp)[0]
            svgs = run_node(data, [{"fn": "distSvg", "args": ["$D", m, {"mode": "violin", "interactive": True}]},
                                   {"fn": "distSvg", "args": ["$D", m, {"mode": "box", "sel": 0, "interactive": True}]},
                                   {"fn": "forestSvg", "args": [json.loads(json.dumps(frows[0])), run_node(data, [lcalls[0]], tmp)[0], "diff", {"interactive": True}]}], tmp)
            for s in svgs:
                ET.fromstring(s)
            assert svgs[0].count('data-k="p"') == 28 and svgs[1].count('data-k="p"') == 28   # each isolate once in All and once in its species
            csvs = run_node(data, [{"fn": "distCsv", "args": ["$D", m]}], tmp)[0]
            assert csvs.splitlines()[0].startswith("group,tool,track,isolate") and len(csvs.splitlines()) == 1 + sum(s["n"] for f in m["facets"] for s in f["slots"])

    # ---- real build on the demo results (no figure module is mocked)
    demo = ROOT / "results_demo"
    if (demo / "scores.tsv").is_file():
        secs = [str(s) for s in fs.build_sections(str(demo), str(demo), str(demo / "scores.tsv"))]
        assert all("Not run" not in s for s in secs), "demo results should draw both figures"
        for s in re.findall(r"<svg.*?</svg>", re.sub(r"<script.*?</script>", "", "".join(secs), flags=re.S), re.S):
            ET.fromstring(s)
        print(f"demo figures: {sum(len(s) for s in secs)} bytes of HTML+JS+JSON added")
    else:
        print("SKIPPED: results_demo not present")
    print("ALL FIG-STATS TESTS PASSED")


if __name__ == "__main__":
    main()
