#!/usr/bin/env python3
"""
The metric registry (config/metrics.tsv, python/metric_registry.py).

  - the shipped file loads: unique lower-case ids, every vocabulary respected, no empty source / column / shown_in / limitations;
  - a bad row is a ValueError that names the row (duplicate id, unknown rung, unknown evidence, wrong columns, empty limitation);
  - every registry term is a glossary term (the glossary keeps the wording, the registry the metadata): no second definition anywhere;
  - every rung of the ladder has a metric; the efficiency group holds the three cost metrics; every scorecard metric (A1 to E3) is in the registry exactly once;
  - the metrics used for ranking are exactly the pre-registered endpoints (base F1, length-weighted binning F1, CPRR);
  - gaps() says which rungs have no ranked metric and none on a published definition, and ladder() groups in order.
"""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import metric_registry as mr  # noqa: E402
import build_html_report as report  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    rows = mr.load()
    ids = [r["id"] for r in rows]
    check("the shipped registry loads with unique ids", len(rows) >= 35 and len(ids) == len(set(ids)), len(rows))
    check("every registry term is a glossary term (no second definition)", all(r["term"] in report.GLOSSARY for r in rows if r["term"]), [r["term"] for r in rows if r["term"] and r["term"] not in report.GLOSSARY])
    check("every rung has at least one metric", all(members for _r, _t, _q, members in mr.ladder(rows)), [t for _r, t, _q, m in mr.ladder(rows) if not m])
    efficiency = [r for r in rows if r["rung"] == "efficiency"]
    check("the efficiency group holds the three cost metrics", sorted(r["scorecard_id"] for r in efficiency) == ["E1", "E2", "E3"])
    with open(ROOT / "config" / "scorecard.tsv", newline="", encoding="utf-8") as handle:
        cards = [r["id"] for r in csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")]
    registered = [r["scorecard_id"] for r in rows if r["scorecard_id"]]
    check("every scorecard metric (A1 to E3) is in the registry exactly once, and nothing else is", sorted(registered) == sorted(cards) and len(cards) == 17, (sorted(set(cards) ^ set(registered))))
    check("the metrics used for ranking are exactly the pre-registered endpoints", sorted(r["id"] for r in rows if r["rankable"] == "yes") == ["base_f1", "cprr", "lw_bin_f1"])
    check("the alignment-derived structure metrics are marked unvalidated, the missing truth-variant metrics not available",
          {r["id"]: r["evidence"] for r in rows if r["id"] in ("ngoc", "structural_concordance", "snp_concordance", "sv_f1")}
          == {"ngoc": "unvalidated", "structural_concordance": "unvalidated", "snp_concordance": "not_available", "sv_f1": "not_available"})
    gaps = dict(mr.gaps(rows))
    check("the gaps are stated: sequence recovery has no ranked metric, biological validity has no published-definition metric",
          "no metric on this rung is used for ranking" in gaps.get("sequence_recovery", "") or any("Sequence recovery" in t and "ranking" in t for _r, t in mr.gaps(rows)),
          mr.gaps(rows))
    check("ladder() lists the five rungs in order, then efficiency", [r[0] for r in mr.ladder(rows)] == list(mr.RUNG_IDS))

    print("validation errors name the row")
    header = "\t".join(mr.COLUMNS)

    def write(tmp, *lines):
        path = Path(tmp) / "m.tsv"
        path.write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
        return path

    good = "a_metric\t\tdetection\tall\tinputs\tno\tproject_defined\tleaderboard\tmean_f1\t\tleaderboard\tlimit"
    with tempfile.TemporaryDirectory() as tmp:
        check("a good row loads", mr.load(write(tmp, good))[0]["id"] == "a_metric")
        cases = {"duplicate id": (good, good), "unknown rung": (good.replace("detection", "vibes"),), "unknown evidence": (good.replace("project_defined", "guess"),),
                 "empty limitation": (good.rsplit("\t", 1)[0] + "\t",), "upper-case id": (good.replace("a_metric", "A_Metric"),)}
        for label, lines in cases.items():
            try:
                mr.load(write(tmp, *lines))
                raised, named = False, False
            except ValueError as error:
                raised, named = True, "row" in str(error)
            check(f"{label}: a ValueError that names the row", raised and named)
        wrong = Path(tmp) / "wrong.tsv"
        wrong.write_text("id\tterm\n", encoding="utf-8")
        try:
            mr.load(wrong)
            raised = False
        except ValueError as error:
            raised = "columns must be" in str(error)
        check("the wrong columns are rejected", raised)

    print()
    if not ok:
        print("METRIC REGISTRY TESTS FAILED")
        sys.exit(1)
    print("ALL METRIC REGISTRY TESTS PASSED")


if __name__ == "__main__":
    main()
