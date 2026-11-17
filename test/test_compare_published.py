#!/usr/bin/env python3
"""compare-published: PlasBench's results beside a publication's outcomes, matched by BioSample, studies apart, nothing scored as zero."""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import compare_published as cp  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def write_tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


PUB_COLS = ["study", "subset", "paper_sample", "biosample", "tool", "metric", "item", "value", "n_items", "size_bp", "size_class", "replicon"]
META_A = {"study": "paperA", "citation": "Author A 2026", "what_it_is": "per-plasmid recall", "tool_map": {"plsMD": "plsmd", "MOB-suite": "mob_recon", "gplas": "gplas2_mob", "OnlyThere": None},
          "metrics": [{"published_metric": "plasmid_recall", "label": "Per-plasmid recall", "plasbench_metric": "completeness", "level": "per_plasmid", "comparability": "similar", "tolerance": 0.05, "note": "n"}],
          "caveats": ["A caveat that must be shown."]}
META_B = {"study": "paperB", "citation": "Author B 2025", "what_it_is": "contig F1", "tool_map": {"ToolX": "genomad"},
          "metrics": [{"published_metric": "contig_f1_count", "label": "Contig F1", "plasbench_metric": "contig_f1_count", "level": "per_isolate", "comparability": "similar", "tolerance": 0.05, "note": "n"}],
          "caveats": ["B caveat."]}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    pub = tmp / "published"
    pub.mkdir()
    rows_a = []
    plasmid_values = {  # (item, plsMD, MOB, gplas) published
        "CP001.1": (1.0, 0.9, 0.5), "CP002.1": (0.9, 0.8, 0.4), "CP003.1": (1.0, 1.0, 1.0), "CP004.1": (0.95, 0.9, 0.2), "CP005.1": (0.8, 0.7, 0.1), "CP006.1": (0.9, 0.9, 0.9)}
    for item, vals in plasmid_values.items():
        for tool, value in zip(("plsMD", "MOB-suite", "gplas"), vals):
            rows_a.append(["paperA", "filtered", "RUN1", "SAMN1", tool, "plasmid_recall", item, value, 1, 5000, "Small", "IncF"])
    rows_a.append(["paperA", "filtered", "RUN1", "SAMN1", "OnlyThere", "plasmid_recall", "CP001.1", 0.5, 1, 5000, "Small", "IncF"])
    rows_a.append(["paperA", "filtered", "RUN9", "SAMN9", "plsMD", "plasmid_recall", "CP900.1", 0.5, 1, 5000, "Small", "IncF"])  # isolate not in the cohort
    write_tsv(pub / "paperA.published.tsv", PUB_COLS, rows_a)
    (pub / "paperA.meta.json").write_text(json.dumps(META_A), encoding="utf-8")
    rows_b = [["paperB", "", "RUN1", "SAMN1", "ToolX", "contig_f1_count", "i1", 0.60, 10, "", "", ""], ["paperB", "", "RUN2", "SAMN2", "ToolX", "contig_f1_count", "i2", 0.70, 10, "", "", ""]]
    write_tsv(pub / "paperB.published.tsv", PUB_COLS, rows_b)
    (pub / "paperB.meta.json").write_text(json.dumps(META_B), encoding="utf-8")

    sheet = tmp / "cohort.tsv"
    write_tsv(sheet, ["sample_id", "biosample", "organism"], [["s1", "SAMN1", "E. coli"], ["s2", "SAMN2", "E. coli"]])
    res = tmp / "res"
    # PlasBench per-plasmid completeness for sample s1 (note: versioned accession differs, NZ-free); CP006 is absent from PlasBench's truth
    def per_plasmid(tool, values):
        write_tsv(res / "s1" / f"{tool}.per_plasmid.tsv", ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"],
                  [["s1", tool, "short_read", acc, 1000, 0, v, 1] for acc, v in values.items()])
    per_plasmid("plsmd", {"NZ_CP001.2": 1.0, "CP002.1": 0.92, "CP003.1": 1.0, "CP004.1": 0.93, "CP005.1": 0.82})
    per_plasmid("mob_recon", {"CP001.1": 0.5, "CP002.1": 0.3, "CP003.1": 0.4, "CP004.1": 0.4, "CP005.1": 0.3})
    # gplas2_mob not run at all
    write_tsv(res / "scores.tsv", ["sample", "tool", "analysis_track", "contig_f1_count", "precision", "recall", "f1"],
              [["s1", "genomad", "short_read", 0.62, "", "", ""], ["s2", "genomad", "short_read", 0.55, "", "", ""], ["s1", "mob_recon", "short_read", 0.9, "", "", ""]])

    print("matching and arithmetic")
    report = cp.run(str(res), str(sheet), str(res / "scores.tsv"), str(res / "benchmark.published_comparison"), str(pub), str(res / "p.html"))
    studies = {s["study"]: s for s in report["studies"]}
    check("both studies with isolates in the cohort are compared, separately", set(studies) == {"paperA", "paperB"}, list(studies))
    check("an isolate not in the cohort is not counted", studies["paperA"]["isolates_in_cohort"] == 1 and studies["paperA"]["isolates_published"] == 2)
    summ = {(r["tool"], r["stratum"]): r for r in studies["paperA"]["summary"]}
    plsmd = summ[("plsmd", "all")]
    check("plsMD: 5 plasmids matched ignoring the accession version (NZ_CP001.2 against CP001.1: version and RefSeq prefix ignored)", plsmd["n_pairs"] == 5, plsmd["n_pairs"])
    check("the plasmid PlasBench's truth lacks is published-only, not zero", plsmd["n_published_only"] == 1, plsmd["n_published_only"])
    check("published and PlasBench means are the means of the matched pairs only", abs(plsmd["published_mean"] - 0.93) < 1e-9 and abs(plsmd["plasbench_mean"] - 0.934) < 1e-9, (plsmd["published_mean"], plsmd["plasbench_mean"]))
    check("small gap is consistent", plsmd["verdict"] == "consistent", plsmd["verdict"])
    check("a large gap is reported as differs", summ[("mob_recon", "all")]["verdict"] == "differs")
    gp = summ[("gplas2_mob", "all")]
    check("a tool PlasBench did not run keeps a row with 0 pairs and no PlasBench mean, never a zero", gp["n_pairs"] == 0 and gp["n_published_only"] == 6 and gp["plasbench_mean"] is None and gp["verdict"] == "too few pairs", gp)
    check("a published tool with no counterpart is listed as published only", "OnlyThere" in studies["paperA"]["published_only_tools"])
    check("size strata are reported", ("plsmd", "Small") in summ)
    check("per-isolate metric is compared by sample", [r for r in studies["paperB"]["summary"] if r["tool"] == "genomad"][0]["n_pairs"] == 2)
    gen = [r for r in studies["paperB"]["summary"] if r["tool"] == "genomad"][0]
    check("per-isolate mean difference", abs(gen["mean_difference"] - (0.02 - 0.15) / 2) < 1e-9, gen["mean_difference"])
    check("correlation is undefined under 3 pairs, not zero", gen["correlation"] is None)
    check("fewer than 5 pairs is 'too few pairs', not a verdict", gen["verdict"] == "too few pairs")
    verdicts = {v["metric"]: v for v in studies["paperA"]["verdicts"]}
    check("study status counts tools with enough pairs", verdicts["plasmid_recall"]["tools_with_enough_pairs"] == 2 and verdicts["plasmid_recall"]["status"] == "PARTLY", verdicts["plasmid_recall"])
    check("tool order needs 3 tools before it is compared", "rank_correlation" not in verdicts["plasmid_recall"])

    print("outputs")
    for name in ("benchmark.published_comparison.tsv", "benchmark.published_comparison_pairs.tsv", "benchmark.published_comparison.json", "p.html"):
        check(f"{name} is written", (res / name).is_file())
    pairs = list(csv.DictReader(open(res / "benchmark.published_comparison_pairs.tsv", encoding="utf-8"), delimiter="\t"))
    check("every pair row keeps both values", all(r["published"] and r["plasbench"] for r in pairs if r["study"] == "paperA" and r["tool"] == "plsmd" and r["plasbench"]))
    page = (res / "p.html").read_text(encoding="utf-8")
    check("the page shows the citation, caveat and the not-a-ranking statement", "Author A 2026" in page and "A caveat that must be shown." in page and "never pooled" in page)
    check("the page draws a scatter with a diagonal", "<svg" in page and "stroke-dasharray" in page)
    data = json.loads((res / "benchmark.published_comparison.json").read_text(encoding="utf-8"))
    check("the JSON carries the verdicts and no per-row summary", data["studies"][0]["verdicts"] and "summary" not in data["studies"][0])

    print("rank agreement with three tools")
    pub2 = tmp / "pub2"
    pub2.mkdir()
    meta = dict(META_B, study="paperC", tool_map={"T1": "genomad", "T2": "plasme", "T3": "platon"})
    (pub2 / "paperC.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    prow, srow = [], []
    for i in range(6):
        sid, bs = f"c{i}", f"SAMNC{i}"
        for tool, pbtool, pv, sv in (("T1", "genomad", 0.9, 0.8), ("T2", "plasme", 0.7, 0.6), ("T3", "platon", 0.5, 0.4)):
            prow.append(["paperC", "", sid, bs, tool, "contig_f1_count", sid, pv, 5, "", "", ""])
            srow.append([sid, pbtool, "short_read", sv, "", "", ""])
    write_tsv(pub2 / "paperC.published.tsv", PUB_COLS, prow)
    sheet2 = tmp / "c.tsv"
    write_tsv(sheet2, ["sample_id", "biosample"], [[f"c{i}", f"SAMNC{i}"] for i in range(6)])
    write_tsv(res / "scores_c.tsv", ["sample", "tool", "analysis_track", "contig_f1_count", "precision", "recall", "f1"], srow)
    rep = cp.run(str(res), str(sheet2), str(res / "scores_c.tsv"), str(res / "c"), str(pub2))
    v = rep["studies"][0]["verdicts"][0]
    check("with 3 tools the tool order is compared (identical order: Spearman 1, same leader)", abs((v.get("rank_correlation") or 0) - 1.0) < 1e-9 and v.get("same_leader") is True, v)
    check("a consistent study is called CONSISTENT only when every tool is within tolerance", v["status"] == "DIFFERENT", v["status"])

    print("no matching isolates, and the command line")
    other = tmp / "other.tsv"
    write_tsv(other, ["sample_id", "biosample"], [["z", "SAMNZ"]])
    rep = cp.run(str(res), str(other), str(res / "scores.tsv"), str(res / "none"), str(pub))
    check("a cohort with no published isolates says NO_DATA", rep["status"] == "NO_DATA" and rep["studies"] == [])
    done = subprocess.run([sys.executable, str(ROOT / "python" / "compare_published.py"), "--results-dir", str(res), "--samples", str(other), "--published-dir", str(pub)],
                          capture_output=True, text=True)
    check("the CLI explains there is nothing to compare", done.returncode == 0 and "nothing to compare" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, str(ROOT / "python" / "compare_published.py"), "--results-dir", str(res), "--samples", str(sheet), "--published-dir", str(pub),
                           "--out-prefix", str(res / "cli")], capture_output=True, text=True)
    check("the CLI prints each metric's status", done.returncode == 0 and "Per-plasmid recall: PARTLY" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, "-m", "plasbench", "compare-published", "--results-dir", str(res), "--samples", str(other)], cwd=ROOT, capture_output=True, text=True)
    check("plasbench compare-published is a command", done.returncode == 0 and "nothing to compare" in done.stdout, done.stdout[-200:] + done.stderr[-200:])

print("the report section")
sys.path.insert(0, str(ROOT / "python"))
import report_learnings as rl  # noqa: E402

html_none = rl.published_section(None, None)
check("with no comparison the section says Not run and how to run it", "Not run" in html_none and "compare-published" in html_none and "id='learn-published'" in html_none)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    pub = tmp / "published"
    pub.mkdir()
    write_tsv(pub / "paperA.published.tsv", PUB_COLS, [["paperA", "", "R", "SAMN1", "plsMD", "plasmid_recall", f"CP{i}.1", 0.9, 1, 1, "Small", ""] for i in range(6)])
    (pub / "paperA.meta.json").write_text(json.dumps(META_A), encoding="utf-8")
    sheet = tmp / "c.tsv"
    write_tsv(sheet, ["sample_id", "biosample"], [["s1", "SAMN1"]])
    res = tmp / "res"
    write_tsv(res / "s1" / "plsmd.per_plasmid.tsv", ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"],
              [["s1", "plsmd", "short_read", f"CP{i}.1", 1, 1, 0.9, 1] for i in range(6)])
    write_tsv(res / "scores.tsv", ["sample", "tool", "analysis_track"], [["s1", "plsmd", "short_read"]])
    cp.run(str(res), str(sheet), str(res / "scores.tsv"), str(res / "benchmark.published_comparison"), str(pub))
    page = "<section id='recommendations'></section><a href='#recommendations'>Recommendations</a>"
    out = rl.inject(page, str(res), str(res / "scores.tsv"))
    check("inject adds the section and a nav link", "id='learn-published'" in out and "href='#learn-published'" in out)
    check("the injected section shows the compared tool", "plsmd" in out and "Author A 2026" in out and "CONSISTENT" in out)

print("ALL COMPARE PUBLISHED TESTS PASSED" if not failures else "COMPARE PUBLISHED TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
