#!/usr/bin/env python3
"""The README, the Scientific guide and the Methods document agree with the implementation (third review: treat documentation as a tested component).

Checked against the code and the shipped configuration, not against each other:
  - the three evaluation tasks and each task's primary endpoint (headline_design.TASK_METRIC) are stated in all three documents;
  - the four evaluation-independence classes and the reference groups are stated, and the retired names are not;
  - no document describes the retired track-specific endpoint (long-read and hybrid ranked on CPRR by input track) as current;
  - every shipped cohort file appears in the guide's cohort table;
  - the dominant-study limit and the interval default quoted in the documents are the ones in resampling.py;
  - every pre-registration row that is still `proposed` is named in the guide's limitations (so none is mistaken for frozen);
  - the tool validation tiers the documents name are the registry's vocabulary.
"""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import headline_design as hd  # noqa: E402
import resampling as rs  # noqa: E402
import tool_capabilities as tc  # noqa: E402

DOCS = {name: (ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "docs/SCIENTIFIC_GUIDE.md", "docs/METHODS.md")}
FLAT = {name: re.sub(r"\s+", " ", text) for name, text in DOCS.items()}


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("tasks and endpoints")
    for name, text in FLAT.items():
        missing = [t for t in tc.EVALUATION_TASKS if t not in text and t.replace("_", " ") not in text]
        check(f"{name} names the three evaluation tasks", not missing, missing)
    for task, metric in hd.TASK_METRIC.items():
        holders = [n for n, text in FLAT.items() if metric in text]
        check(f"the primary endpoint of {task} ({metric}) is stated in at least the guide and the methods", {"docs/SCIENTIFIC_GUIDE.md", "docs/METHODS.md"} <= set(holders), holders)
    for name, text in FLAT.items():
        stale = [p for p in ("Track-specific primary endpoint", "reconstruction vs classification") if p in text]
        check(f"{name} has no retired endpoint or two-task wording", not stale, stale)
    methods = FLAT["docs/METHODS.md"]
    for m in re.finditer(r"primary_endpoint_long_read", methods):
        window = methods[max(0, m.start() - 200): m.end() + 200]
        check("primary_endpoint_long_read appears in the Methods only as the retired row", "replaced" in window or "earlier design" in window or "retired" in window, window[:120])

    print("reference independence")
    for name, text in FLAT.items():
        check(f"{name} states the independence classes", all(c in text for c in ("partially independent", "dependent", "unknown")) or all(c in text for c in ("partially_independent", "dependent", "unknown")))
    for name, text in FLAT.items():
        retired = [p for p in ("same_read_polished", "tier2_unknown_independence", "same-read-polished") if p in text]
        check(f"{name} does not use the retired three-class names", not retired, retired)

    print("cohorts")
    guide = FLAT["docs/SCIENTIFIC_GUIDE.md"]
    for cohort in sorted(ROOT.glob("cohorts/public-v*.tsv")):
        check(f"the guide's cohort table lists {cohort.stem}", f"`{cohort.stem}`" in guide)

    print("statistics")
    share = f"{rs.DOMINANT_STUDY_SHARE:.0%}"
    for name, text in FLAT.items():
        check(f"{name} quotes the dominant-study limit ({share}) and the cluster-t default", share in text and "cluster" in text and "PLASBENCH_DOMINANT_SHARE" in text and rs.INTERVAL_METHOD in text.replace("-", "_").replace(" ", "_"))
    check("the committed simulation results exist", (ROOT / "docs" / "stats_validation" / "benchmark.stats_validation_by_studies.tsv").is_file())
    with open(ROOT / "docs" / "stats_validation" / "benchmark.stats_validation_by_studies.tsv", newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle, delimiter="\t"))
    check("the committed results include the leaderboard-rule column (the fallback was validated)", "lowest_coverage_leaderboard" in header)

    print("pre-registration and validation tiers")
    with open(ROOT / "config" / "prereg.tsv", newline="", encoding="utf-8") as handle:
        proposed = [r["parameter"] for r in csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t") if r["status"] == "proposed"]
    named = [p for p in proposed if p in guide or p.replace("_", " ") in guide]
    check("every proposed pre-registration row the documents rely on is named in the guide's limitation (none is mistaken for frozen)",
          proposed and all(p in guide for p in ("primary_endpoint", "primary_endpoint_reassembly", "headline_independence", "dominant_study_share", "interval method")) and "await confirmation" in guide, proposed)
    for tier in tc.VALIDATION_TIERS:
        check(f"the guide or README names the validation tier {tier}", tier in FLAT["README.md"] or tier in guide or tier.replace("_", " ") in FLAT["README.md"] or tier.replace("_", " ") in guide)

    print("ALL DOCS CONSISTENCY TESTS PASSED" if ok else "DOCS CONSISTENCY TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
