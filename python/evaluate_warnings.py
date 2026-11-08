#!/usr/bin/env python3
"""
evaluate_warnings.py -- does each operational warning actually predict a failed
recommendation? (scoring specification, section 10)

A recommendation failed on an isolate when its regret (evaluate_recommender.py,
F1 profile) exceeds --failure-regret (RECOMMENDATION_FAILURE_REGRET, 0.10).
For every warning:

  firing rate   fired isolates / evaluated isolates
  PPV           failed among fired
  sensitivity   fired among failed
  could not be applied   isolates where the warning's validity limit applies
                (e.g. the cohort was too small for outlier detection); they are
                counted, never scored as "not fired"

Warnings come from existing outputs only -- no new warning logic is invented:
  * cohort_outlier:<field>   flag_cohort_outliers.py (benchmark.cohort_qc_flags.tsv);
                             when the cohort was too small every isolate is
                             "could not be applied"
  * assembly_qc:<reason>     assembly_qc_gate.py (benchmark.assembly_qc.tsv), when present
  * --warnings               any extra TSV with sample, warning, fired (yes/no),
                             validity_limit_applies (yes/no)

Writes <prefix>.warnings.tsv (the long table) and <prefix>.warning_eval.tsv.
Standard library only.
"""

import argparse
import csv
import os
from collections import defaultdict

EVAL_FIELDS = ["warning", "n_evaluated", "n_fired", "n_failed", "n_fired_and_failed", "firing_rate", "ppv",
               "sensitivity", "n_could_not_be_applied", "status", "note"]
WARNING_FIELDS = ["sample", "warning", "fired", "validity_limit_applies"]


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def warnings_from_cohort_qc(rows, samples):
    out = []
    too_small = any(not r.get("sample_id") and not r.get("field") for r in rows)
    if too_small:
        return [{"sample": s, "warning": "cohort_outlier", "fired": "no", "validity_limit_applies": "yes"}
                for s in sorted(samples)]
    for r in rows:
        if r.get("sample_id") and r.get("field"):
            out.append({"sample": r["sample_id"], "warning": f"cohort_outlier:{r['field']}",
                        "fired": "yes" if r.get("flagged") == "true" else "no", "validity_limit_applies": "no"})
    return out


def warnings_from_assembly_qc(rows):
    out = []
    for r in rows:
        if not r.get("sample"):
            continue
        reasons = [x for x in (r.get("reasons") or "").split(";") if x]
        for check in ("assembly_size", "gc_spread"):
            fired = any(x.startswith(check) for x in reasons)
            out.append({"sample": r["sample"], "warning": f"assembly_qc:{check}", "fired": "yes" if fired else "no",
                        "validity_limit_applies": "yes" if r.get("status") == "not_evaluable" else "no"})
    return out


def evaluate(warnings, failed_by_sample):
    groups = defaultdict(list)
    for w in warnings:
        groups[w["warning"]].append(w)
    rows = []
    fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
    for name, items in sorted(groups.items()):
        applicable = [w for w in items if w["validity_limit_applies"] != "yes" and w["sample"] in failed_by_sample]
        cannot = sum(w["validity_limit_applies"] == "yes" for w in items)
        fired = [w for w in applicable if w["fired"] == "yes"]
        failed = [w for w in applicable if failed_by_sample[w["sample"]]]
        both = [w for w in fired if failed_by_sample[w["sample"]]]
        if not applicable:
            status, note = "could_not_be_applied", "validity limit applies to every isolate, or no isolate was evaluated"
        else:
            status, note = "assessed", ""
        rows.append({"warning": name, "n_evaluated": len(applicable), "n_fired": len(fired), "n_failed": len(failed),
                     "n_fired_and_failed": len(both),
                     "firing_rate": fmt(len(fired) / len(applicable) if applicable else None),
                     "ppv": fmt(len(both) / len(fired) if fired else None),
                     "sensitivity": fmt(len(both) / len(failed) if failed else None),
                     "n_could_not_be_applied": cannot, "status": status, "note": note})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regret", required=True, help="evaluate_recommender.py <prefix>.recommender_regret.tsv")
    ap.add_argument("--cohort-qc-flags", help="flag_cohort_outliers.py output")
    ap.add_argument("--assembly-qc", help="assembly_qc_gate.py output")
    ap.add_argument("--warnings", help="extra warnings TSV (sample, warning, fired, validity_limit_applies)")
    ap.add_argument("--failure-regret", type=float,
                    default=float(os.environ.get("RECOMMENDATION_FAILURE_REGRET", 0.10)))
    ap.add_argument("--out-prefix", required=True)
    args = ap.parse_args()

    failed_by_sample = {}
    for r in read_tsv(args.regret):
        if r.get("profile", "f1") == "f1" and r.get("regret"):
            failed_by_sample[r["sample"]] = float(r["regret"]) > args.failure_regret
    warnings = (warnings_from_cohort_qc(read_tsv(args.cohort_qc_flags), set(failed_by_sample))
                + warnings_from_assembly_qc(read_tsv(args.assembly_qc))
                + [{k: r.get(k, "") for k in WARNING_FIELDS} for r in read_tsv(args.warnings)])
    for path, fields, rows in ((f"{args.out_prefix}.warnings.tsv", WARNING_FIELDS, warnings),
                               (f"{args.out_prefix}.warning_eval.tsv", EVAL_FIELDS, evaluate(warnings, failed_by_sample))):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"[evaluate_warnings] {len(warnings)} warning row(s) over {len(failed_by_sample)} evaluated isolate(s) "
          f"({sum(failed_by_sample.values())} failed recommendations) -> {args.out_prefix}.warning_eval.tsv")


if __name__ == "__main__":
    main()
