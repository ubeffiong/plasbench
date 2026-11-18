#!/usr/bin/env python3
"""The synthetic QC generator for the offline demo (python/make_demo_readqc.py): deterministic, marked synthetic, a spread of decisions, decisions that
follow from the figures by the pipeline's own rule, and it REFUSES to run when any sample is real, when the sheet is missing, or when a real QC table is there.
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import short_read_qc as qcmod  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


def tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sheet(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("sample_id\tsample_origin\n" + "".join(f"{s}\t{o}\n" for s, o in rows))


def digest(folder):
    return {n: hashlib.sha256(open(os.path.join(folder, n), "rb").read()).hexdigest() for n in sorted(os.listdir(folder))}


def run(folder, sheet_path):
    return subprocess.run([sys.executable, os.path.join(ROOT, "python", "make_demo_readqc.py"), "--results-dir", folder, "--sample-sheet", sheet_path],
                          capture_output=True, text=True)


DEMO = ["ecoli_a", "ecoli_b", "kpneu_a", "kpneu_b", "abauma_a", "abauma_b"]
with tempfile.TemporaryDirectory() as tmp:
    a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
    for d in (a, b):
        os.makedirs(d)
        sheet(os.path.join(d, "samples.tsv"), [(s, "synthetic") for s in DEMO])
    ra, rb = run(a, os.path.join(a, "samples.tsv")), run(b, os.path.join(b, "samples.tsv"))
    check("it runs on the six synthetic demo isolates and says SYNTHETIC", ra.returncode == 0 and "SYNTHETIC" in ra.stdout, ra.stderr)
    da, db = digest(a), digest(b)
    da.pop("samples.tsv"), db.pop("samples.tsv")
    check("it is deterministic: two runs write identical bytes", da == db and len(da) == 4, list(da))
    qc = tsv(os.path.join(a, "short_read_qc.tsv"))
    check("one QC row per isolate, in the pipeline's column order", [r["sample"] for r in qc] == DEMO and list(qc[0]) == qcmod.FIELDS)
    statuses = {r["qc_status"] for r in qc}
    check("there is a spread of PASS, WARN and REJECT", statuses == {"PASS", "WARN", "REJECT"}, statuses)
    thresholds, policy, sha = qcmod.read_thresholds(qcmod.DEFAULT_THRESHOLDS)
    again = True
    for r in qc:
        m = {k: float(r[k]) for k in ("read_pairs_total", "estimated_depth_x", "mean_quality", "q30_fraction", "median_read_length", "adapter_fraction",
                                      "duplication_fraction", "n_fraction", "pair_mismatch_fraction")}
        m["read_pairs"] = m["read_pairs_total"]
        m.update(integrity="ok", gc_deviation=None)
        again &= qcmod.decide(m, thresholds)[0] == r["qc_status"]
    check("each decision follows from its figures by short_read_qc.decide and the shipped thresholds", again)
    check("the policy and hash are the real thresholds' (so the report can compare them)", {r["thresholds_sha"] for r in qc} == {sha} and {r["policy_status"] for r in qc} == {policy})
    check("depth is read pairs x read length x 2 / genome size", all(abs(float(r["estimated_depth_x"]) - float(r["read_pairs_total"]) * 2 * float(r["median_read_length"])
                                                                      / (float(r["genome_size_mb"]) * 1e6)) < 0.02 for r in qc))
    check("the figures look real: Phred 25 to 40, Q30 between 0.5 and 1, GC 35 to 60", all(25 < float(r["mean_quality"]) < 40 and .5 < float(r["q30_fraction"]) < 1
                                                                                      and 35 < float(r["gc_percent"]) < 60 for r in qc))
    check("an estimated total and an assumed genome size each appear once, to show the marks", sum(r["pairs_basis"] == "estimated" for r in qc) == 1
          and sum(r["genome_size_assumed"] == "yes" for r in qc) == 1)
    prov = json.load(open(os.path.join(a, "short_read_qc.provenance.json")))
    check("the provenance file says synthetic and names the generator", prov["synthetic"] is True and prov["generator"] == "python/make_demo_readqc.py")
    cands = tsv(os.path.join(a, "assembly_candidates.tsv"))
    check("three candidates per isolate, exactly one selected", len(cands) == 18 and all(sum(r["selected"] == "yes" for r in cands if r["sample"] == s) == 1 for s in DEMO))
    check("a candidate that fails the rule is ineligible with the reason, and is never selected", any(r["eligible"] == "no" and "read support" in r["reasons"] for r in cands)
          and any(r["eligible"] == "no" and "total length" in r["reasons"] for r in cands) and not any(r["eligible"] == "no" and r["selected"] == "yes" for r in cands))
    check("the selection is the quality policy's choice (highest N50 among the eligible)", all(
        max((r for r in cands if r["sample"] == s and r["eligible"] == "yes"), key=lambda r: int(r["n50"]))["selected"] == "yes" for s in DEMO))
    status = tsv(os.path.join(a, "short_read_qc_status.tsv"))
    check("a status file with the action per sample is written", [r["sample"] for r in status] == DEMO and any("flagged" in r["action"] for r in status))
    check("it may be re-run over its own output", run(a, os.path.join(a, "samples.tsv")).returncode == 0)

    print("refusals")
    for i, (label, rows) in enumerate((("a real sample among them", [(s, "synthetic") for s in DEMO[:5]] + [("real1", "")]), ("only real samples", [("real1", "clinical")]),
                                       ("an unmarked sample", [("ecoli_a", "synthetic"), ("ecoli_b", "")]))):
        d = os.path.join(tmp, f"r{i}")
        os.makedirs(d)
        sheet(os.path.join(d, "samples.tsv"), rows)
        r = run(d, os.path.join(d, "samples.tsv"))
        check(f"refused for {label}, exit 2, nothing written", r.returncode == 2 and "refused" in r.stderr and os.listdir(d) == ["samples.tsv"], r.stderr)
    d = os.path.join(tmp, "nosheet")
    os.makedirs(d)
    r = run(d, os.path.join(d, "samples.tsv"))
    check("refused with no sample sheet", r.returncode == 2 and os.listdir(d) == [])
    d = os.path.join(tmp, "realqc")
    os.makedirs(d)
    sheet(os.path.join(d, "samples.tsv"), [(s, "synthetic") for s in DEMO])
    open(os.path.join(d, "short_read_qc.tsv"), "w").write("sample\tqc_status\nx\tPASS\n")
    r = run(d, os.path.join(d, "samples.tsv"))
    check("a QC table it did not write is never replaced", r.returncode == 2 and open(os.path.join(d, "short_read_qc.tsv")).read().startswith("sample\tqc_status\nx"), r.stderr)
    d = os.path.join(tmp, "other")
    os.makedirs(d)
    sheet(os.path.join(d, "samples.tsv"), [("someone_else", "synthetic")])
    check("refused when none of the sheet's samples is a demo isolate", run(d, os.path.join(d, "samples.tsv")).returncode == 2)

print()
src = open(os.path.join(ROOT, "test", "run_demo.sh"), encoding="utf-8").read()
check("test/run_demo.sh calls the generator after the demo data are written and before the report is built", 0 < src.index("demo_dataset.py") < src.index("make_demo_readqc.py") < src.index("build_html_report.py"))
scripts = os.path.join(ROOT, "scripts")
check("and no stage script of a real run calls it", not any("make_demo_readqc" in open(os.path.join(scripts, f), encoding="utf-8", errors="replace").read() for f in os.listdir(scripts) if f.endswith(".sh")))
if not ok:
    print("DEMO READQC TESTS FAILED")
    sys.exit(1)
print("ALL DEMO READQC TESTS PASSED")
