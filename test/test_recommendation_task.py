#!/usr/bin/env python3
"""
Recommendations are made for ONE task (reconstruction), never across the reconstruction and classification tasks.

Fixture (hand-computed): three isolates; a binning tool "binA" (F1 0.80, binning-capable) and a classifier "clsB" (F1 0.95, not binning-capable). The headline
and every other ranking keep the two tasks apart; the old recommendation chose one overall winner across both, so the classifier won:
  - reconstruction_tools(registry, {"binA","clsB","other"}) == {"binA"} (binning_capable=yes only); an unreadable registry, or one in which no scored tool is
    binning-capable, gives None (the caller keeps every tool and records the task as 'all');
  - write_recommendations over ALL rows picks clsB (0.95 > 0.80): the old behaviour, kept for --task all;
  - write_recommendations over the reconstruction rows picks binA, and every written row carries task='reconstruction';
  - the task column is written to the TSV (last column);
  - the report states 'One task.' only when the recommendations carry task='reconstruction'.
"""
import csv
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import select_operational_method as som  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        registry = tmp / "caps.tsv"
        registry.write_text("tool\tmethod_class\tbinning_capable\tprimary_input\tdescription\tanalysis_track\trequires_independent_long_read_truth\n"
                            "binA\tbinning\tyes\tassembly\tbinner\tshort_read\tno\n"
                            "clsB\tclassification\tno\tassembly\tclassifier\tshort_read\tno\n", encoding="utf-8")
        print("the task of each tool")
        check("only binning-capable tools are reconstruction tools", som.reconstruction_tools(registry, {"binA", "clsB", "other"}) == {"binA"})
        check("no binning-capable tool among the scored tools gives None", som.reconstruction_tools(registry, {"clsB"}) is None)
        check("an unreadable registry gives None", som.reconstruction_tools(tmp / "missing.tsv", {"binA"}) is None)

        def rows_for(tool, f1):
            return [som.annotate({"sample": s, "tool": tool, "analysis_track": "short_read", "f1": f1, "precision": f1, "recall": f1}, {}) for s in ("s1", "s2", "s3")]
        every = rows_for("binA", "0.80") + rows_for("clsB", "0.95")
        statuses = {t: {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []} for t in ("binA", "clsB")}
        print("the recommendation")
        recs_all, _ = som.write_recommendations(every, statuses, 3, tmp / "all.tsv", 1, 0.1)
        check("across both tasks the classifier wins (the old behaviour, still available as --task all)", recs_all[("overall", "all")] == "clsB", recs_all.get(("overall", "all")))
        only = [r for r in every if r["tool"] in som.reconstruction_tools(registry, {r["tool"] for r in every})]
        recs, written = som.write_recommendations(only, statuses, 3, tmp / "rec.tsv", 1, 0.1, task="reconstruction")
        check("over the reconstruction task the binning tool is recommended", recs[("overall", "all")] == "binA", recs.get(("overall", "all")))
        check("the classifier is not in the recommendation at all", all(r["tool"] == "binA" for r in written))
        check("every row carries its task", all(r["task"] == "reconstruction" for r in written))
        with open(tmp / "rec.tsv", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            first = next(reader)
            header = reader.fieldnames
        check("the TSV has a task column, last", header[-1] == "task" and first["task"] == "reconstruction", header[-3:])

    print("the report")
    report = ROOT / "results_demo" / "benchmark.report.html"
    if not report.is_file():
        print("  SKIP: no results_demo report")
    else:
        text = report.read_text(encoding="utf-8")
        recs_tsv = ROOT / "results_demo" / "benchmark.recommendations.tsv"
        with open(recs_tsv, newline="", encoding="utf-8") as handle:
            demo = list(csv.DictReader(handle, delimiter="\t"))
        check("the demo recommendations are reconstruction-only", demo and all(r.get("task") == "reconstruction" for r in demo), {r.get("task") for r in demo})
        check("the report says so", "<strong>One task.</strong>" in text)
        check("the overall recommended method is a reconstruction tool (not the classification leader)",
              [r["tool"] for r in demo if r["scope"] == "overall" and r["recommendation"] == "primary"] == ["mob_like"])

    print()
    if not ok:
        print("RECOMMENDATION TASK TESTS FAILED")
        sys.exit(1)
    print("ALL RECOMMENDATION TASK TESTS PASSED")


if __name__ == "__main__":
    main()
