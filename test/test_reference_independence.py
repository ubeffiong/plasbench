#!/usr/bin/env python3
"""Reference quality and evaluation independence are two separate classifications (python/truth_provenance.py, headline_design.py).

  - provenance records both: reference_quality (validated / partially validated / provisional = tier 1 / 2 / 3) and evaluation_independence
    (independent / partially independent / dependent / unknown) with a reason; the older columns keep their order;
  - the primary analysis needs independence AND the tier limit; a tier-2 reference can be independent and then qualifies; unknown is never assumed independent;
  - the real aggregate_results.py writes benchmark.reference_independence.tsv and honours --headline-independence;
  - rank_sensitivity adds the primary and sensitivity-1 populations as cohort variants;
  - the setting is in the shipped configuration, the pre-registration table and the manifest.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import truth_provenance as tp  # noqa: E402
import rank_sensitivity as rs  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the classification")
    cases = {("long_read_only", "none"): "independent", ("long_read_first_hybrid", "independent"): "independent",
             ("long_read_first_hybrid", "same_as_benchmark"): "partially_independent", ("long_read_only", "unknown"): "partially_independent",
             ("short_read_first_hybrid", "same_as_benchmark"): "dependent", ("short_read_first_hybrid", "none"): "dependent",
             ("unknown", "none"): "unknown", ("", ""): "unknown"}
    wrong = {k: tp.independence(*k)[0] for k, v in cases.items() if tp.independence(*k)[0] != v}
    check("independence follows the assembly strategy and the polishing reads (unknown is never independent)", not wrong, wrong)
    row = {"sample_id": "s1", "truth_assembly_strategy": "long_read_first_hybrid", "truth_polish_reads": "same_as_benchmark", "truth_quality_tier": "A"}
    derived = tp.derive(row, None)
    check("derive records quality and independence separately, with a reason",
          derived["reference_tier"] == "2" and derived["reference_quality"] == "partially_validated" and derived["evaluation_independence"] == "partially_independent"
          and "benchmark reads" in derived["independence_reason"], derived)
    tier_b = tp.derive({"sample_id": "s2", "truth_assembly_strategy": "long_read_only", "truth_polish_reads": "none", "truth_quality_tier": "B"}, None)
    check("quality and independence differ: a tier-2 reference (cohort tier B) can be fully independent",
          tier_b["reference_tier"] == "2" and tier_b["evaluation_independence"] == "independent", tier_b)
    check("the new columns are appended last", tp.FIELDS[-3:] == ["reference_quality", "evaluation_independence", "independence_reason"])

    print("aggregation and sensitivity populations")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        header = ["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "unmapped_pred_bp", "precision", "recall", "f1", "bin_precision", "bin_recall", "bin_f1",
                  "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events", "contaminated_bins"]
        with open(tmp / "scores.tsv", "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(header)
            for sample, f1 in (("s1", "0.9"), ("s2", "0.7"), ("s3", "0.5")):
                writer.writerow([sample, "tool_a", 100, 80, 20, 20, 0, "0.8", "0.8", f1, "0.5", "0.5", "0.5", 1, 1, 1, 2, 3, 4])
        (tmp / "prov.tsv").write_text("sample\treference_tier\tevaluation_independence\ns1\t1\tindependent\ns2\t2\tpartially_independent\ns3\t3\tdependent\n", encoding="utf-8")

        def run(*extra):
            subprocess.run([sys.executable, str(ROOT / "python" / "aggregate_results.py"), "--scores", str(tmp / "scores.tsv"), "--tool-status", str(tmp / "none.tsv"),
                            "--out-prefix", str(tmp / "b"), "--truth-provenance", str(tmp / "prov.tsv"), "--headline-min-clusters", "1", *extra], check=True, capture_output=True)
            return list(csv.DictReader(open(tmp / "b.leaderboard.tsv", newline="", encoding="utf-8"), delimiter="\t"))[0]
        primary = run()
        check("default: only the independent reference is in the headline (one sample), status available", primary["primary_status"] == "available" and primary["n_samples"] == "1", primary)
        widened = run("--headline-independence", "independent,partially_independent")
        check("--headline-independence widens the population (two samples)", widened["n_samples"] == "2", widened)
        table = list(csv.DictReader(open(tmp / "b.reference_independence.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        got = {r["evaluation_independence"]: (r["n_samples"], f"{float(r['mean_metric']):.1f}") for r in table}
        check("benchmark.reference_independence.tsv has one row per class with its n and mean", got == {"independent": ("1", "0.9"), "partially_independent": ("1", "0.7"), "dependent": ("1", "0.5")}, got)
        groups = rs.sample_groups(None, None, {"s1", "s2", "s3"}, str(tmp / "prov.tsv"))
        check("rank sensitivity: the primary and sensitivity-1 populations are cohort variants",
              groups["independent_references_only"] == {"s1"} and groups["independent_or_partial_references"] == {"s1", "s2"}, groups)

    print("configuration")
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    prereg = (ROOT / "config" / "prereg.tsv").read_text(encoding="utf-8")
    check("setting in config.sh, pre-registration (proposed), stage 6 and the manifest",
          'HEADLINE_INDEPENDENCE="${HEADLINE_INDEPENDENCE:-independent}"' in config and any(l.startswith("headline_independence\t") and "\tproposed\t" in l for l in prereg.splitlines())
          and "HEADLINE_INDEPENDENCE" in (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8") and "HEADLINE_INDEPENDENCE" in (ROOT / "python" / "write_manifest.py").read_text(encoding="utf-8"))
    print("ALL REFERENCE INDEPENDENCE TESTS PASSED" if ok else "REFERENCE INDEPENDENCE TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
