#!/usr/bin/env python3
"""performance_drivers.py: a study-clustered multivariable regression of per-plasmid completeness, tested on data with known effects."""

import csv
import json
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import performance_drivers as pdv  # noqa: E402

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


class Args:
    min_plasmids = 30
    min_clusters = 5
    bootstrap = 300
    seed = 7


def build(tmp, n_studies=20, samples_per_study=6, plasmids_per_sample=3, seed=1):
    """Plasmids with known structure. Tool A: completeness falls with size, not with repeats. Tool B: no effect. Tool C: study-level noise. Tool D: its own."""
    rng = random.Random(seed)
    res, data = tmp / "res", tmp / "data"
    sheet_rows, repeat_rows = [], []
    plasmids = []  # (sample, seq, log_size, repeat, study)
    for s in range(n_studies):
        study_effect = rng.gauss(0, 1)
        for k in range(samples_per_study):
            sample = f"st{s}_s{k}"
            species = "Escherichia coli" if s % 2 == 0 else "Klebsiella pneumoniae"
            sheet_rows.append([sample, species, f"PRJ{s}", "120", "recent" if s % 3 == 0 else "older"])
            feats = []
            for q in range(plasmids_per_sample):
                log_size = rng.uniform(3.3, 5.6)
                seq = f"{sample}_p{q}"
                repeat = rng.random()  # independent of size
                plasmids.append((sample, seq, log_size, repeat, s, study_effect))
                repeat_rows.append([sample, seq, "PLASMID", str(int(10 ** log_size)), "100", f"{repeat:.4f}", "0.0", "0.0", "no", "ok"])
                feats.append([seq, "replicon", "IncF" if rng.random() < 0.5 else "ColRNAI"])
            write_tsv(data / sample / "truth_features.tsv", ["sequence_id", "feature_type", "label"], feats)
    write_tsv(tmp / "sheet.tsv", ["sample_id", "organism", "bioproject", "read_depth_x", "selection_arm"], sheet_rows)
    write_tsv(res / "benchmark.repeat_content.tsv", ["sample", "sequence_id", "molecule_type", "length", "n_kmers", "internal_repeat_fraction",
                                                       "chromosome_shared_fraction", "shared_with_other_plasmids_fraction", "repeat_rich", "status"], repeat_rows)
    mean_size = sum(p[2] for p in plasmids) / len(plasmids)
    sd_size = math.sqrt(sum((p[2] - mean_size) ** 2 for p in plasmids) / (len(plasmids) - 1))
    tools = {
        "tool_a": lambda p: 0.7 - 0.12 * (p[2] - mean_size) / sd_size + rng.gauss(0, 0.04),
        "tool_b": lambda p: 0.6 + rng.gauss(0, 0.04),
        "tool_c": lambda p: 0.6 + 0.10 * p[5] + rng.gauss(0, 0.02),   # a study-level shift: independent-looking but clustered
        "tool_d": lambda p: 0.5 + rng.gauss(0, 0.04),
    }
    by_sample = {}
    for p in plasmids:
        by_sample.setdefault(p[0], []).append(p)
    for sample, plist in by_sample.items():
        for tool, fn in tools.items():
            rows = []
            for p in plist:
                comp = max(0.0, min(1.0, fn(p)))
                rows.append([sample, tool, "short_read", p[1], str(int(10 ** p[2])), "0", f"{comp:.4f}", "1" if comp >= 0.9 else "0"])
            write_tsv(res / sample / f"{tool}.per_plasmid.tsv", ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"], rows)
    return res, data, tmp / "sheet.tsv", mean_size, sd_size


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    res, data, sheet, mean_size, sd_size = build(tmp)
    print("a known size effect is recovered; null effects are not claimed")
    out = pdv.run(str(res), str(data), str(sheet), str(res / "benchmark.repeat_content.tsv"), str(res / "benchmark.performance_drivers"), Args)
    by = {r["tool"]: r for r in out}
    a = {t["driver"] + ":" + t["term"]: t for t in by["tool_a"]["terms"]}
    size = next(t for t in by["tool_a"]["terms"] if t["driver"] == "size")
    check("tool A: the size effect is negative, near the true -0.12 per SD", -0.16 < size["estimate"] < -0.08, size["estimate"])
    check("tool A: the size effect is supported (interval excludes 0, sign stable)", size["status"] == "supported" and size["sign_stability"] >= 0.95, size)
    check("tool A: the interval contains the truth", size["ci_low"] < -0.12 < size["ci_high"], (size["ci_low"], size["ci_high"]))
    rep = next(t for t in by["tool_a"]["terms"] if t["driver"] == "repeats")
    check("tool A: repeats, which have no effect, are not claimed", rep["status"] == "unclear" and rep["ci_low"] < 0 < rep["ci_high"], rep)
    check("tool A: size explains most of the explained variance", size["delta_r2_without"] > 0.3 and size["delta_r2_without"] > (rep["delta_r2_without"] or 0) * 5, (size["delta_r2_without"], rep["delta_r2_without"]))
    b_terms = by["tool_b"]["terms"]
    check("tool B (no effect): nothing is supported", all(t["status"] == "unclear" for t in b_terms), [(t["term"], t["estimate"]) for t in b_terms if t["status"] == "supported"])
    check("every tool and track gets its own model", set(by) == {"tool_a", "tool_b", "tool_c", "tool_d"} and all(r["status"] == "estimated" for r in out))
    check("species, replicon family and arm are in the model", {"species", "replicon_family", "arm", "size", "repeats"} <= {t["driver"] for t in by["tool_a"]["terms"]},
          {t["driver"] for t in by["tool_a"]["terms"]})
    rep_term = [t for t in by["tool_a"]["terms"] if t["driver"] == "replicon_family"]
    check("replicon terms name their reference (the most frequent category when 'untyped' is absent)", rep_term and all(t["reference"] in ("inc", "col") for t in rep_term), rep_term)
    check("a substituted reference is announced", any("preferred reference" in w for w in by["tool_a"]["warnings"]), by["tool_a"]["warnings"])
    check("the model has a meaningful R2", by["tool_a"]["r2"] and by["tool_a"]["r2"] > 0.4, by["tool_a"]["r2"])

    print("study-level noise widens the interval (the clusters matter)")
    cw = next(t for t in by["tool_c"]["terms"] if t["driver"] == "arm")
    dw = next(t for t in by["tool_d"]["terms"] if t["driver"] == "arm")
    check("the recent-arm interval of the study-shifted tool is wider than the independent-noise tool's", (cw["ci_high"] - cw["ci_low"]) > 2 * (dw["ci_high"] - dw["ci_low"]),
          ((cw["ci_high"] - cw["ci_low"]), (dw["ci_high"] - dw["ci_low"])))

    print("the t distribution and standard errors")
    check("t quantile for 19 degrees of freedom is 2.093", abs(pdv.t_ppf(0.975, 19) - 2.0930) < 1e-3, pdv.t_ppf(0.975, 19))
    check("t quantile for 4 degrees of freedom is 2.776", abs(pdv.t_ppf(0.975, 4) - 2.7764) < 1e-3, pdv.t_ppf(0.975, 4))
    check("t distribution function is 0.5 at 0 and symmetric", abs(pdv.t_cdf(0, 10) - 0.5) < 1e-9 and abs(pdv.t_cdf(1.5, 10) + pdv.t_cdf(-1.5, 10) - 1) < 1e-9)
    print("determinism and outputs")
    out2 = pdv.run(str(res), str(data), str(sheet), str(res / "benchmark.repeat_content.tsv"), str(res / "second"), Args)
    check("the same seed gives the same intervals", [(t["ci_low"], t["ci_high"]) for t in out2[0]["terms"]] == [(t["ci_low"], t["ci_high"]) for t in out[0]["terms"]])
    rows = list(csv.DictReader(open(res / "benchmark.performance_drivers.tsv", encoding="utf-8"), delimiter="\t"))
    check("the TSV has one row per term with the columns", rows and set(pdv.OUT_FIELDS) == set(rows[0]) and len(rows) == sum(len(r["terms"]) for r in out))
    data_json = json.loads((res / "benchmark.performance_drivers.json").read_text(encoding="utf-8"))
    check("the JSON states the model, seed and each tool's size effect", data_json["seed"] == 7 and data_json["tools"][0]["size_effect"]["driver"] == "size" and "OLS" in data_json["model"])

    print("not estimable, never a coefficient")
    few = tmp / "few"
    res2, data2, sheet2, *_ = build(few, n_studies=4, samples_per_study=6)
    out3 = pdv.run(str(res2), str(data2), str(sheet2), str(res2 / "benchmark.repeat_content.tsv"), str(res2 / "o"), Args)
    check("fewer than 5 studies: not estimable, with the reason, and no terms", all(r["status"] == "not_estimable" and "studies" in r["reason"] and not r["terms"] for r in out3), [r["reason"] for r in out3])
    tiny = tmp / "tiny"
    res3, data3, sheet3, *_ = build(tiny, n_studies=6, samples_per_study=1, plasmids_per_sample=2)
    out4 = pdv.run(str(res3), str(data3), str(sheet3), str(res3 / "benchmark.repeat_content.tsv"), str(res3 / "o"), Args)
    check("fewer than 30 plasmids: not estimable, with the reason", all(r["status"] == "not_estimable" and "scored plasmids" in r["reason"] for r in out4), [r["reason"] for r in out4])

    print("drivers the data cannot support are left out and listed")
    sparse = tmp / "sparse"
    res4, data4, sheet4, *_ = build(sparse)
    for path in (sparse / "res").glob("*/*.per_plasmid.tsv"):
        pass
    import os
    os.remove(res4 / "benchmark.repeat_content.tsv")
    out5 = pdv.run(str(res4), str(data4), str(sheet4), str(res4 / "benchmark.repeat_content.tsv"), str(res4 / "o"), Args)
    left = {x["driver"]: x["reason"] for x in out5[0]["left_out"]}
    check("without a repeat table, repeats are left out with the reason (not imputed)", "repeats" in left and "not available" in left["repeats"], left)
    check("the model still runs on the drivers that remain", out5[0]["status"] == "estimated" and all(t["driver"] != "repeats" for t in out5[0]["terms"]))

    print("collinear drivers are flagged")
    col = tmp / "col"
    res5, data5, sheet5, *_ = build(col)
    rep_rows = list(csv.reader(open(res5 / "benchmark.repeat_content.tsv", encoding="utf-8"), delimiter="\t"))
    head, body = rep_rows[0], rep_rows[1:]
    for r in body:
        r[5] = f"{(math.log10(int(r[3])) - 3.3) / 2.3:.4f}"   # repeat fraction becomes a function of size
    write_tsv(res5 / "benchmark.repeat_content.tsv", head, body)
    out6 = pdv.run(str(res5), str(data5), str(sheet5), str(res5 / "benchmark.repeat_content.tsv"), str(res5 / "o"), Args)
    check("size and repeats correlated above 0.8 produce a warning", any("correlated" in w for w in out6[0]["warnings"]), out6[0]["warnings"])

    print("the command line")
    done = subprocess.run([sys.executable, str(ROOT / "python" / "performance_drivers.py"), "--results-dir", str(res), "--data-dir", str(data), "--sample-sheet", str(sheet),
                           "--bootstrap", "100", "--out-prefix", str(res / "cli")], capture_output=True, text=True)
    check("it runs and reports how many models were estimated", done.returncode == 0 and "4 of 4" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, "-m", "plasbench", "analysis", "performance-drivers", "--help"], cwd=ROOT, capture_output=True, text=True)
    check("it is reachable as plasbench analysis performance-drivers", done.returncode == 0 and "multivariable" in done.stdout, done.stdout[-200:] + done.stderr[-200:])

print("ALL PERFORMANCE DRIVER TESTS PASSED" if not failures else "PERFORMANCE DRIVER TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
