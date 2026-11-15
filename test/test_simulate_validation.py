#!/usr/bin/env python3
"""
The statistics simulation (python/simulate_validation.py) and where it is wired.

  - simulate(): repeatable for a seed; study sizes balanced or unbalanced; missing observations are dropped; no study effect when tau is 0;
  - run_scenario(): the row has every column; too few studies give 'not estimable' (an interval needs 5, a test 6); with 6 to 12 studies the test is exact;
    a large true effect is almost always detected and no effect is rarely detected (power and type-I error are separate readings); the interval verdict
    never rounds a shortfall up: 'consistent with 95%' exactly when coverage reaches 0.95 minus two standard errors expected under the nominal rate, otherwise 'below nominal';
  - the command writes the TSV with the documented columns, in smoke mode, quickly;
  - the report: a 'Statistical validation (simulation)' section with the table, an explicit Not run empty state that says how to run it, and a tab in the Sensitivity group;
  - the extended structures: one dominant study, two heavy studies, resource failures (per isolate and a whole study), several species with one dominant, and Holm over many
    comparisons (family-wise error with and without the adjustment, power); results summarised by the number of independent studies, and a status that stays provisional
    unless a FULL run supports every number of studies it covered;
  - the wiring: the CLI command, stage 6 and its setting, the file registry, the pre-registration-free config variable, the demo.
"""
import csv
import html
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_dimensions as rd  # noqa: E402
import simulate_validation as sv  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the simulated data")
    a = sv.simulate(random.Random(1), 6, 3, 0.1, 0.1, 0.0, 0.0)
    b = sv.simulate(random.Random(1), 6, 3, 0.1, 0.1, 0.0, 0.0)
    check("repeatable for a seed; 6 studies of 3 isolates give 18 values in 6 groups", a == b and len(a[0]) == 18 and len(set(a[1])) == 6)
    values, groups = sv.simulate(random.Random(2), 40, None, 0.1, 0.1, 0.0, 0.0)
    sizes = {groups.count(g) for g in set(groups)}
    check("unbalanced studies have different sizes (1, 2 and 6)", sizes <= {1, 2, 6} and len(sizes) > 1, sizes)
    values, groups = sv.simulate(random.Random(3), 50, 4, 0.1, 0.1, 0.5, 0.0)
    check("missing observations are dropped (about half of 200)", 60 < len(values) < 140, len(values))
    flat, _ = sv.simulate(random.Random(4), 5, 20, 0.0, 0.0, 0.0, 0.25)
    check("with no study effect and no noise every value is the effect", set(flat) == {0.25})

    print("the extended structures")
    values, groups = sv.simulate(random.Random(5), 12, None, 0.05, 0.1, 0.0, 0.0, sizes="dominant")
    counts = sorted((groups.count(g) for g in set(groups)), reverse=True)
    check("a dominant study holds about 60% of the isolates", len(counts) == 12 and 0.55 <= counts[0] / len(values) <= 0.65, counts)
    values, groups = sv.simulate(random.Random(6), 12, None, 0.05, 0.1, 0.0, 0.0, sizes="heavy2")
    counts = sorted((groups.count(g) for g in set(groups)), reverse=True)
    check("two heavy studies hold about 80% of the isolates", 0.75 <= (counts[0] + counts[1]) / len(values) <= 0.85, counts)
    values, _groups = sv.simulate(random.Random(7), 40, 5, 0.0, 0.0, 0.0, 0.2, failure=0.2)
    failed = [v for v in values if abs(abs(v) - sv.FAILURE_MAGNITUDE) < 1e-9]
    check("resource failures are scored zero: a paired difference of +-0.7 in both directions, about 20% of observations, symmetric",
          0.12 <= len(failed) / len(values) <= 0.28 and min(failed) < 0 < max(failed), (len(failed), len(values)))
    values, groups = sv.simulate(random.Random(8), 20, 4, 0.0, 0.0, 0.0, 0.2, failure=0.3, clustered=True)
    whole = {g for g in set(groups) if all(abs(abs(v) - sv.FAILURE_MAGNITUDE) < 1e-9 for v, gg in zip(values, groups) if gg == g)}
    check("a clustered failure takes whole studies (every observation of a failed study is +-0.7)", 1 <= len(whole) < 20, len(whole))
    _v, _g, strata = sv.draw(random.Random(9), 20, 3, 0.05, 0.1, 0.0, 0.0, species=3)
    shares = {s: strata.count(s) / len(strata) for s in set(strata)}
    check("one dominant species holds about 70% of the studies", len(shares) == 3 and 0.6 <= max(shares.values()) <= 0.8, shares)
    spec = sv.run_scenario("species", 12, 3, 0.05, 0.1, 0.0, 0.0, 30, 100, 500, 11, "smoke", species=3, family="dominant species")
    check("the species-stratified functions are used (a row with a verdict)", spec["family"] == "dominant species" and spec["species"] == 3 and spec["ci_coverage"] != "", spec)
    holm = sv.run_holm(sv.S("holm", 8, family="holm", comparisons=6), 0.0, 40, 500, 13, "smoke")
    check("Holm: the family-wise error is reported with and without the adjustment, and the adjusted rate is not above the unadjusted one",
          holm["fwer_holm"] != "" and float(holm["fwer_holm"]) <= float(holm["fwer_unadjusted"]) and holm["comparisons"] == 6, holm)
    power = sv.run_holm(sv.S("holm", 8, family="holm", comparisons=6, tau=0.02), 0.3, 40, 500, 14, "smoke")
    check("Holm power is reported when some comparisons are real, and is not above the unadjusted power",
          power["power_holm"] != "" and float(power["power_holm"]) <= float(power["power_unadjusted"]) and float(power["power_unadjusted"]) > 0.5, power)
    rows = [{**sv.run_scenario("a", 12, 3, 0.02, 0.1, 0.0, e, 40, 100, 500, 21, "smoke"), "mode": "smoke"} for e in (0.0, 0.1)]
    table = sv.by_studies(rows)
    check("by_studies has one row per number of studies, and a smoke run is never 'supported'", [r["n_studies"] for r in table] == [12] and table[0]["status"] != "supported", table)
    full = [dict(r, mode="full", ci_verdict="consistent with 95%", test_verdict="valid (type-I error within tolerance)" if r["effect"] == 0.0 else "power 0.90") for r in rows]
    check("a full run with no shortfall is 'supported', and overall_status says supported at that number",
          sv.by_studies(full)[0]["status"] == "supported" and sv.overall_status(full).startswith("supported by the full simulation at 12 independent studies"), sv.overall_status(full))
    short = [dict(r, mode="full", ci_verdict="below nominal (86%): the interval is too narrow") for r in full]
    check("a full run with an interval shortfall is a shortfall, and the overall status stays provisional and names the scenario",
          sv.by_studies(short)[0]["status"] == "shortfall" and sv.overall_status(short).startswith("provisional") and "a" in sv.by_studies(short)[0]["limiting_scenarios"], sv.overall_status(short))
    check("no simulation at all is provisional", sv.overall_status([]).startswith("provisional"))

    print("the scenarios")
    def row(clusters, effect, per=3, replicates=60, tau=0.05, mode="smoke"):
        return sv.run_scenario("t", clusters, per, tau, 0.1, 0.0, effect, replicates, 100, 500, 7, mode)

    r = row(6, 0.0)
    check("the row has every documented column", set(r) == set(sv.FIELDS), set(sv.FIELDS) ^ set(r))
    few = row(4, 0.0)
    check("4 studies: neither an interval (needs 5) nor a test (needs 6) can be estimated", few["ci_verdict"].startswith("not estimable") and few["test_verdict"].startswith("not estimable")
          and few["rejection_rate"] == "" and few["ci_coverage"] == "", few)
    five = row(5, 0.0)
    check("5 studies: an interval but no test", not five["ci_verdict"].startswith("not estimable") and five["test_verdict"].startswith("not estimable"), five)
    six = row(6, 0.0)
    check("6 studies: the test is exact", six["test_method"] == "exact" and float(six["test_estimated"]) == 1.0, six)
    check("13 studies: Monte Carlo", row(13, 0.0, replicates=20)["test_method"] == "monte_carlo")
    power = row(12, 0.3, tau=0.02, replicates=60)
    null = row(12, 0.0, tau=0.02, replicates=60)
    check("a large true effect is almost always detected (power), no effect is rarely detected (type-I error)", float(power["rejection_rate"]) >= 0.9 and float(null["rejection_rate"]) <= 0.2,
          (power["rejection_rate"], null["rejection_rate"]))
    check("a null scenario reports a type-I verdict, an effect scenario a power", null["test_verdict"].split()[0] in ("valid", "anti-conservative") and power["test_verdict"].startswith("power"))
    honest = True
    for r in (six, five, null, power):
        if r["ci_coverage"]:
            cov = float(r["ci_coverage"])
            n = round(float(r["replicates"]) * float(r["ci_estimated"]))
            consistent = r["ci_verdict"].startswith("consistent with 95%")
            honest &= consistent == (cov >= 0.95 - 2 * (0.95 * 0.05 / n) ** 0.5) and (consistent or r["ci_verdict"].startswith("below nominal"))
    check("the interval verdict never rounds a shortfall up (consistent only when coverage reaches 0.95 minus two standard errors expected under the nominal rate)", honest)
    smoke = row(12, 0.0, tau=0.02, replicates=40)
    check("a smoke verdict says it is indicative", "indicative" in smoke["ci_verdict"] and "indicative" in smoke["test_verdict"], (smoke["ci_verdict"], smoke["test_verdict"]))
    import math
    check("a coverage of 0.90 over 100 replicates is below the line (0.95 - 2 x 0.0218 = 0.906); the old rule let it pass", 0.90 < 0.95 - 2 * math.sqrt(0.95 * 0.05 / 100) and 0.90 + 2 * math.sqrt(0.9 * 0.1 / 100) >= 0.95)

    print("the interval methods")
    import resampling as rs
    check("Student t quantiles", abs(rs.t_quantile(0.975, 5) - 2.570582) < 1e-5 and abs(rs.t_quantile(0.975, 1) - 12.706205) < 1e-4
          and abs(rs.t_quantile(0.025, 30) + 2.042272) < 1e-5)
    vals, grps = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], list("abcdef")
    low, high = rs.cluster_t_ci(vals, grps)
    # one value per cluster: CR1 reduces to the ordinary t interval, mean 3.5 +/- t(5) * sd / sqrt(6)
    se = (sum((v - 3.5) ** 2 for v in vals) / 5) ** 0.5 / 6 ** 0.5
    check("with one isolate per cluster the cluster t interval is the ordinary t interval",
          abs(low - (3.5 - 2.570582 * se)) < 1e-5 and abs(high - (3.5 + 2.570582 * se)) < 1e-5, (low, high))
    check("fewer than 5 clusters: no interval from any method", all(rs.interval([1.0, 2.0, 3.0, 4.0, 5.0], list("aabbc"), method=m) == (None, None) for m in rs.INTERVAL_METHODS))
    wide, _ = rs.cluster_t_ci([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.2, 0.8], list("aaabbbccde"))
    narrow, _ = rs.cluster_t_ci([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.2, 0.8], [str(i) for i in range(10)])
    check("clustering widens the interval (correlated isolates count less)", wide < narrow, (wide, narrow))
    bt = rs.bootstrap_t_ci(vals * 2, grps * 2)
    check("the bootstrap-t interval contains the mean and is repeatable", bt[0] < 3.5 < bt[1] and bt == rs.bootstrap_t_ci(vals * 2, grps * 2), bt)
    strat = rs.cluster_t_ci([0.1, 0.2, 0.15, 0.12, 0.9, 0.8, 0.85, 0.95, 0.11, 0.88], list("abcdefghij"), list("AAAABBBBAB"))
    check("a stratified interval is centred on the macro mean", abs((strat[0] + strat[1]) / 2 - (0.136 + 0.876) / 2) < 1e-9, strat)

    print("the command")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "benchmark.stats_validation.tsv"
        done = subprocess.run([sys.executable, str(ROOT / "python" / "simulate_validation.py"), "--mode", "smoke", "--replicates", "12", "--out", str(out), "--by-studies-out", str(Path(tmp) / "by.tsv")], capture_output=True, text=True)
        rows = list(csv.DictReader(open(out, newline="", encoding="utf-8"), delimiter="\t")) if out.is_file() else []
        check("smoke mode writes one row per scenario and effect with the documented columns",
              done.returncode == 0 and len(rows) == (sum(2 if sc.family == "holm" else len(sv.SETTINGS["smoke"]["effects"]) for sc in sv.SMOKE)
                            + len(sv.SETTINGS["smoke"]["stratified"]) * len(sv.SETTINGS["smoke"]["effects"]) + len(sv.SETTINGS["smoke"]["holm_pairs"])) and list(rows[0]) == list(sv.FIELDS), done.stderr[-300:])
        check("it says the status of the procedures (provisional after a smoke run)", "status: provisional" in done.stderr, done.stderr[-300:])
        check("it says whether any scenario shows a calibration shortfall", "calibration shortfall" in done.stderr or "no calibration shortfall" in done.stderr, done.stderr)
        by = list(csv.DictReader(open(Path(tmp) / "by.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        check("the summary by number of studies has the documented columns and one row per number", list(by[0]) == list(sv.BY_STUDIES_FIELDS) and [int(r["n_studies"]) for r in by] == sorted({int(r["n_clusters"]) for r in rows}))
        prefix = str(Path(tmp) / "benchmark")
        nav, sections = rd.render(prefix, html.escape, lambda p: os.path.basename(p))
        check("the report section with the table", "id='stats-validation'" in sections and "Statistical validation (simulation)" in sections and "Interval coverage" in sections and "By number of independent studies" in sections and "Status of the statistical procedures: provisional" in sections
              and rows[0]["scenario"] in html.unescape(sections) and "benchmark.stats_validation.tsv" in sections.replace("stats validation table", "benchmark.stats_validation.tsv"), sections[:200])
        out.unlink()
        nav, empty = rd.render(prefix, html.escape, lambda p: os.path.basename(p))
        i = empty.index("id='stats-validation'")
        check("without the table the section says 'Not run' and how to run it", "Not run: no simulation table" in empty[i:i + 2000] and "simulate-validation" in empty[i:i + 2000]
              and "RUN_STATS_VALIDATION=1" in empty[i:i + 2000])

    print("the wiring")
    merge = (ROOT / "python" / "report_merge.py").read_text(encoding="utf-8")
    check("a tab of Sensitivity, power and reproducibility", '("stats-validation", "Statistical validation")' in merge)
    check("the CLI command", '"simulate-validation": ("simulate_validation.py"' in (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8"))
    stage = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
    check("stage 6 runs it when RUN_STATS_VALIDATION=1", "RUN_STATS_VALIDATION" in stage and "simulate_validation.py" in stage and "stats_validation.tsv" in stage)
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    check("the settings are exported", 'export RUN_STATS_VALIDATION="${RUN_STATS_VALIDATION:-0}"' in config and 'export STATS_VALIDATION_MODE="${STATS_VALIDATION_MODE:-smoke}"' in config)
    check("the file is registered for the Artifact explorer", "benchmark.stats_validation.tsv" in (ROOT / "python" / "report_surfaces.py").read_text(encoding="utf-8"))
    check("the demo runs it in smoke mode", "simulate_validation.py" in (ROOT / "test" / "run_demo.sh").read_text(encoding="utf-8"))

    print()
    if not ok:
        print("SIMULATE VALIDATION TESTS FAILED")
        sys.exit(1)
    print("ALL SIMULATE VALIDATION TESTS PASSED")


if __name__ == "__main__":
    main()
