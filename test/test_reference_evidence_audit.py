#!/usr/bin/env python3
"""reference_evidence_audit.py: one auditable row per isolate, never raising trust above what is recorded."""

import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
import reference_evidence_audit as ra  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def prov(sample, tier, indep, polish="none", strategy="long_read_first", **ev):
    base = {f: "independent" if f != "independent_validation" else "long_read_reassembly" for f in ra.EVIDENCE}
    base.update(ev)
    return {"sample": sample, "reference_tier": str(tier), "reference_quality": "A", "evaluation_independence": indep, "truth_polish_reads": polish,
            "truth_assembly_strategy": strategy, "ambiguous_plasmids": "0", "marker_free_plasmids": "0", **base}


rows = ra.audit([prov("good", 2, "independent"),
                 prov("polished", 2, "partially_independent", polish="same_as_benchmark"),
                 prov("shortfirst", 3, "dependent", strategy="short_read_first"),
                 prov("sparse", 2, "independent", assembly_technology="unknown", circularity_evidence="unknown", read_support="unknown",
                      replicon_evidence="unknown"),
                 prov("repeaty", 2, "independent")],
                [{"sample": "repeaty", "molecule_type": "plasmid", "repeat_rich": "yes"}, {"sample": "good", "molecule_type": "plasmid", "repeat_rich": "no"}],
                [{"sample": "good", "n_high_regions": "0", "n_low_regions": "0"}, {"sample": "repeaty", "n_high_regions": "2", "n_low_regions": "1"}])
by = {r["sample"]: r for r in rows}
check("a tier-2 independent isolate with validation and no flags is strong", by["good"]["audit_status"] == "strong" and by["good"]["headline_eligible"] == "yes", by["good"])
check("a reference polished with the same reads as the tools is flagged and not strong", by["polished"]["same_read_polish"] == "yes"
      and by["polished"]["audit_status"] == "weak" and "polished with the same Illumina reads" in by["polished"]["audit_reasons"], by["polished"])
check("a short-read-first reference is weak and not headline-eligible", by["shortfirst"]["audit_status"] == "weak" and by["shortfirst"]["headline_eligible"] == "no")
check("fewer than half of the evidence fields recorded is weak, and says how many", by["sparse"]["audit_status"] == "weak" and "only 2 of 6" in by["sparse"]["audit_reasons"], by["sparse"])
check("repeat-rich plasmids and depth anomalies lower it to caveats and are counted", by["repeaty"]["audit_status"] == "usable_with_caveats"
      and by["repeaty"]["repeat_rich_plasmids"] == 1 and by["repeaty"]["depth_anomaly_regions"] == 3, by["repeaty"])
no_tables = {r["sample"]: r for r in ra.audit([prov("good", 2, "independent")], None, None)}
check("missing repeat and depth tables can never make a reference strong", no_tables["good"]["audit_status"] == "usable_with_caveats"
      and "repeat content not recorded" in no_tables["good"]["audit_reasons"])
check("the independence rule follows the headline setting", {r["sample"]: r for r in ra.audit([prov("p", 2, "partially_independent")], [], [], 2,
      ("independent", "partially_independent"))}["p"]["headline_eligible"] == "yes")

tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, "benchmark.truth_provenance.tsv"), "w", newline="", encoding="utf-8") as h:
    w = csv.DictWriter(h, fieldnames=list(prov("a", 2, "independent")), delimiter=TAB, lineterminator=NL)
    w.writeheader()
    w.writerow(prov("a", 2, "independent"))
out = os.path.join(tmp, "audit.tsv")
check("the command writes the table", ra.main(["--results-dir", tmp, "--out", out]) == 0 and os.path.isfile(out))
check("without the provenance table it refuses, not an empty pass", ra.main(["--results-dir", tempfile.mkdtemp(), "--out", os.path.join(tmp, "x.tsv")]) == 2)

print("ALL REFERENCE EVIDENCE AUDIT TESTS PASSED" if ok else "REFERENCE EVIDENCE AUDIT TESTS FAILED")
sys.exit(0 if ok else 1)
