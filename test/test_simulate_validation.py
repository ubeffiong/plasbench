#!/usr/bin/env python3
"""
The statistics simulation (python/simulate_validation.py) and where it is wired.

  - simulate(): repeatable for a seed; study sizes balanced or unbalanced; missing observations are dropped; no study effect when tau is 0;
  - run_scenario(): the row has every column; too few studies give 'not estimable' (an interval needs 5, a test 6); with 6 to 12 studies the test is exact;
    a large true effect is almost always detected and no effect is rarely detected (power and type-I error are separate readings); the interval verdict
    never rounds a shortfall up: 'consistent with 95%' exactly when coverage + 2 SE reaches 0.95, otherwise 'below nominal';
  - the command writes the TSV with the documented columns, in smoke mode, quickly;
  - the report: a 'Statistical validation (simulation)' section with the table, an explicit Not run empty state that says how to run it, and a tab in the Sensitivity group;
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
            cov, se = float(r["ci_coverage"]), float(r["ci_coverage_se"])
            consistent = r["ci_verdict"] == "consistent with 95%"
            honest &= consistent == (cov + 2 * se >= 0.95) and (consistent or r["ci_verdict"].startswith("below nominal"))
    check("the interval verdict never rounds a shortfall up (consistent only when coverage + 2 SE reaches 0.95)", honest)

    print("the command")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "benchmark.stats_validation.tsv"
        done = subprocess.run([sys.executable, str(ROOT / "python" / "simulate_validation.py"), "--mode", "smoke", "--replicates", "12", "--out", str(out)], capture_output=True, text=True)
        rows = list(csv.DictReader(open(out, newline="", encoding="utf-8"), delimiter="\t")) if out.is_file() else []
        check("smoke mode writes one row per scenario and effect with the documented columns",
              done.returncode == 0 and len(rows) == len(sv.SMOKE) * len(sv.SETTINGS["smoke"]["effects"]) and list(rows[0]) == list(sv.FIELDS), done.stderr[-300:])
        check("it says whether any scenario shows a calibration shortfall", "calibration shortfall" in done.stderr or "no calibration shortfall" in done.stderr, done.stderr)
        prefix = str(Path(tmp) / "benchmark")
        nav, sections = rd.render(prefix, html.escape, lambda p: os.path.basename(p))
        check("the report section with the table", "id='stats-validation'" in sections and "Statistical validation (simulation)" in sections and "Interval coverage" in sections
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
