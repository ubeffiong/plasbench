#!/usr/bin/env python3
"""
reference_evidence_audit.py -- one row per isolate: how far can its truth assembly be trusted, and why?

The headline ranking is only as good as the reference it is scored against. The evidence about each reference is recorded in
separate tables (truth provenance, repeat content, depth anomalies, multimer and ambiguity checks); this script reads them
together and writes one auditable row per isolate, so the question "what supports this reference?" has one place to look:

  benchmark.reference_evidence_audit.tsv
    reference_tier, reference_quality, evaluation_independence        from benchmark.truth_provenance.tsv
    evidence_recorded, circularity_evidence, read_support, ...        the six evidence fields, with "unknown" kept as unknown
    flags: same_read_polish, short_read_first, no_independent_validation, repeat_rich_plasmids, depth_anomaly_regions,
           ambiguous_plasmids, marker_free_plasmids
    headline_eligible                                                 tier <= --max-tier AND evaluation_independence in --independence
    audit_status                                                      strong | usable_with_caveats | weak
    audit_reasons                                                     every reason, in words

audit_status: weak when the isolate is not headline-eligible, the reference is dependent or unknown, or fewer than half of the
six evidence fields are recorded; strong when it is eligible, independent, has an independent validation and none of the other
flags; otherwise usable_with_caveats. A missing input table lowers what can be said ("not recorded"), it never raises it.
Descriptive only: it changes no score and no ranking.

Usage:
  python python/reference_evidence_audit.py --results-dir results --out results/benchmark.reference_evidence_audit.tsv
"""

import argparse
import csv
import os
from collections import defaultdict

TAB, NL = chr(9), chr(10)
EVIDENCE = ("assembly_technology", "circularity_evidence", "read_support", "replicon_evidence", "structural_integrity", "independent_validation")
COLUMNS = ["sample", "reference_tier", "reference_quality", "evaluation_independence", "truth_assembly_strategy", "truth_polish_reads",
           "evidence_recorded", *EVIDENCE, "same_read_polish", "short_read_first", "no_independent_validation", "repeat_rich_plasmids",
           "depth_anomaly_regions", "ambiguous_plasmids", "marker_free_plasmids", "headline_eligible", "audit_status", "audit_reasons"]


def read(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((x for x in handle if x.strip() and not x.startswith("#")), delimiter=TAB))


def count_of(value):
    text = (value or "").strip()
    if not text or text.lower() in ("none", "na", "n/a", "-", "0"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        return len([p for p in text.replace(",", ";").split(";") if p.strip()])


def tier_number(value):
    text = (value or "").strip().lower().replace("tier", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def audit(prov, repeats, depth, max_tier=2, independence=("independent",)):
    by_repeat, by_depth = defaultdict(int), defaultdict(int)
    for r in repeats or []:
        if (r.get("repeat_rich") or "").strip().lower() in ("yes", "true", "1") and (r.get("molecule_type") or "plasmid") != "chromosome":
            by_repeat[r.get("sample", "")] += 1
    for r in depth or []:
        by_depth[r.get("sample", "")] += count_of(r.get("n_high_regions")) + count_of(r.get("n_low_regions"))
    rows = []
    for p in prov:
        sample = p.get("sample", "")
        indep = (p.get("evaluation_independence") or "unknown").strip()
        strategy = (p.get("truth_assembly_strategy") or "").strip()
        polish = (p.get("truth_polish_reads") or "").strip()
        tier = tier_number(p.get("reference_tier"))
        recorded = sum(1 for f in EVIDENCE if (p.get(f) or "unknown").strip() not in ("", "unknown"))
        same = polish == "same_as_benchmark"
        short_first = indep == "dependent" or "short" in strategy.lower()
        no_val = (p.get("independent_validation") or "unknown").strip() in ("none", "unknown", "")
        ambiguous, marker_free = count_of(p.get("ambiguous_plasmids")), count_of(p.get("marker_free_plasmids"))
        repeat_n = by_repeat.get(sample, 0) if repeats is not None else ""
        depth_n = by_depth.get(sample, 0) if depth is not None else ""
        eligible = tier is not None and tier <= max_tier and indep in independence
        reasons = []
        if tier is None:
            reasons.append("reference tier not recorded")
        elif tier > max_tier:
            reasons.append(f"reference tier {tier} is above the headline limit {max_tier}")
        if indep not in independence:
            reasons.append(f"evaluation independence is {indep}")
        if same:
            reasons.append("truth was polished with the same Illumina reads the tools use (bases are not independent)")
        if short_first:
            reasons.append("short-read-first assembly: truth and tools share repeat-resolution errors")
        if no_val:
            reasons.append("no independent validation recorded")
        if recorded * 2 < len(EVIDENCE):
            reasons.append(f"only {recorded} of {len(EVIDENCE)} evidence fields recorded")
        if repeat_n:
            reasons.append(f"{repeat_n} repeat-rich plasmid(s): structure may be uncertain")
        if depth_n:
            reasons.append(f"{depth_n} read-depth anomaly region(s) on the truth")
        if ambiguous:
            reasons.append(f"{ambiguous} ambiguous plasmid label(s)")
        if marker_free:
            reasons.append(f"{marker_free} plasmid(s) without a replicon or mobility marker")
        if repeats is None:
            reasons.append("repeat content not recorded")
        if depth is None:
            reasons.append("depth anomalies not recorded")
        weak = (not eligible) or indep in ("dependent", "unknown") or recorded * 2 < len(EVIDENCE)
        clean = eligible and indep == "independent" and not no_val and not (same or short_first or repeat_n or depth_n or ambiguous or marker_free)
        status = "weak" if weak else ("strong" if clean and repeats is not None and depth is not None else "usable_with_caveats")
        rows.append({"sample": sample, "reference_tier": p.get("reference_tier", ""), "reference_quality": p.get("reference_quality", ""),
                     "evaluation_independence": indep, "truth_assembly_strategy": strategy, "truth_polish_reads": polish,
                     "evidence_recorded": f"{recorded} of {len(EVIDENCE)}", **{f: p.get(f, "") for f in EVIDENCE},
                     "same_read_polish": "yes" if same else "no", "short_read_first": "yes" if short_first else "no",
                     "no_independent_validation": "yes" if no_val else "no", "repeat_rich_plasmids": repeat_n, "depth_anomaly_regions": depth_n,
                     "ambiguous_plasmids": ambiguous, "marker_free_plasmids": marker_free, "headline_eligible": "yes" if eligible else "no",
                     "audit_status": status, "audit_reasons": "; ".join(reasons)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--provenance")
    ap.add_argument("--repeat-content")
    ap.add_argument("--depth-anomalies")
    ap.add_argument("--max-tier", type=int, default=2)
    ap.add_argument("--independence", default="independent", help="comma-separated evaluation_independence values accepted for the headline")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    d = a.results_dir
    prov = read(a.provenance or os.path.join(d, "benchmark.truth_provenance.tsv"))
    if prov is None:
        print("reference evidence audit: benchmark.truth_provenance.tsv is missing, so no reference can be audited")
        return 2
    rows = audit(prov, read(a.repeat_content or os.path.join(d, "benchmark.repeat_content.tsv")),
                 read(a.depth_anomalies or os.path.join(d, "benchmark.truth_depth_anomalies.tsv")), a.max_tier,
                 tuple(x.strip() for x in a.independence.split(",") if x.strip()))
    with open(a.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=TAB, lineterminator=NL)
        writer.writeheader()
        writer.writerows(rows)
    counts = {k: sum(1 for r in rows if r["audit_status"] == k) for k in ("strong", "usable_with_caveats", "weak")}
    print(f"reference evidence audit: {len(rows)} isolate(s): {counts['strong']} strong, {counts['usable_with_caveats']} usable with caveats, "
          f"{counts['weak']} weak; {sum(1 for r in rows if r['headline_eligible'] == 'yes')} headline-eligible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
