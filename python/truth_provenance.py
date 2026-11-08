#!/usr/bin/env python3
"""
truth_provenance.py -- how was each truth assembly built, and how far can it
be trusted as a reference?

Two research-design rules (docs/METHODS.md, "Reference standard") need this:

1. Truth structure must come from long reads. A short-read-first hybrid
   (Unicycler's default mode, or PlasBench's own self-built Unicycler truth)
   resolves repeats on the same Illumina assembly graph the benchmarked
   tools use, so truth and tools share repeat-resolution errors -- circular
   evaluation. Such truth is Tier 3 (provisional) and stays out of the
   headline.
2. Truth polished with the SAME Illumina reads the tools are benchmarked on
   is acceptable for contig labelling (plasmid vs chromosome), but not for
   base-level accuracy (identity) metrics. base_level_metrics_valid records
   this; the CPRR identity criterion is applied only where it is "yes".

Reference tiers
  1  validated: long-read-only or long-read-first truth, polishing reads
     independent of the benchmark (or none), curated cohort tier A, and
     evidence-based replicon labels were evaluated.
  2  high-confidence: long-read-first truth that fails a Tier-1 condition
     (e.g. polished with the benchmark's own reads, cohort tier B, labels
     not evidence-checked).
  3  provisional: short-read-first hybrid, unknown assembly strategy, or
     cohort tier C. Exploratory only; reported as a sensitivity analysis.

Sources, in priority order: the sample sheet's truth_assembly_strategy /
truth_polish_reads columns; PlasBench's own truth_source (self-built hybrid
truth is Unicycler, i.e. short-read-first); NCBI's assembly_data_report.jsonl
(assemblyInfo.assemblyMethod / sequencingTech, saved by stage 1). Derived
values are heuristics and say so in `provenance_source`; set the sheet
columns to override them.

Standard library only.
"""

import argparse
import csv
import glob
import json
import os
import re
import sys

STRATEGIES = ("long_read_only", "long_read_first_hybrid", "short_read_first_hybrid", "unknown")
POLISH = ("none", "independent", "same_as_benchmark", "unknown")

# "tryc(?:yc|y)ler" also matches "Trycyler", a misspelling found in real NCBI
# assembly records (e.g. an E. coli Trycycler + Medaka + Polypolish assembly).
LONG_READ_ASSEMBLERS = re.compile(
    r"\b(flye|canu|raven|tryc(?:yc|y)ler|autocycler|dragonflye|hybracter|miniasm|necat|nextdenovo|"
    r"wtdbg2?|hifiasm|smartdenovo|hgap|falcon|ra)\b", re.IGNORECASE)
CONSENSUS_LONG_READ = re.compile(r"\b(tryc(?:yc|y)ler|autocycler|hybracter)\b", re.IGNORECASE)
SHORT_READ_FIRST = re.compile(r"\b(unicycler|masurca|spades)\b", re.IGNORECASE)
ILLUMINA = re.compile(r"\b(illumina|miseq|hiseq|nextseq|novaseq|iseq|bgiseq|dnbseq|mgiseq)\b", re.IGNORECASE)
LONG_READ_TECH = re.compile(r"\b(nanopore|ont|minion|gridion|promethion|pacbio|sequel|rs ii|hifi)\b",
                            re.IGNORECASE)


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def assembly_info(data_dir, sample):
    """(assemblyMethod, sequencingTech) from the saved NCBI assembly report."""
    if not data_dir:
        return "", ""
    sample_dir = os.path.join(data_dir, sample)
    paths = [os.path.join(sample_dir, "assembly_data_report.jsonl")]
    paths += sorted(glob.glob(os.path.join(sample_dir, "ncbi", "**", "assembly_data_report.jsonl"), recursive=True))
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    info = (json.loads(line) or {}).get("assemblyInfo") or {}
                except json.JSONDecodeError:
                    continue
                method = info.get("assemblyMethod") or info.get("assembly_method") or ""
                tech = info.get("sequencingTech") or info.get("sequencing_tech") or ""
                if method or tech:
                    return method, tech
    return "", ""


def classify_method(method, tech):
    """Return (strategy, polish, reason) from NCBI's free-text assembly fields."""
    if not method and not tech:
        return "unknown", "unknown", "no assembly method or sequencing technology recorded"
    has_illumina = bool(ILLUMINA.search(tech) or ILLUMINA.search(method))
    long_assembler = bool(LONG_READ_ASSEMBLERS.search(method))
    consensus = bool(CONSENSUS_LONG_READ.search(method))
    short_first = bool(SHORT_READ_FIRST.search(method))
    if consensus or (long_assembler and not short_first):
        strategy = "long_read_first_hybrid" if has_illumina else "long_read_only"
    elif short_first and not long_assembler:
        strategy = "short_read_first_hybrid" if (has_illumina and LONG_READ_TECH.search(tech)) else "unknown"
        if strategy == "unknown":
            return strategy, "unknown", f"assembler '{method}' without recorded long-read technology"
    else:
        return "unknown", "unknown", f"cannot tell long-read-first from short-read-first: '{method}'"
    if strategy == "long_read_only":
        polish = "none"
        reason = f"long-read assembler, no Illumina recorded ('{method}'; '{tech}')"
    elif strategy == "long_read_first_hybrid":
        # The benchmark's Illumina run is validated to share the truth
        # assembly's BioSample, so an Illumina polishing step almost certainly
        # used that same library unless the sheet says otherwise.
        polish = "same_as_benchmark"
        reason = (f"long-read-first with Illumina recorded ('{method}'; '{tech}'); assumed polished with "
                  "the benchmark's own Illumina run (same BioSample) -- set truth_polish_reads to override")
    else:
        polish = "same_as_benchmark"
        reason = f"short-read-first hybrid assembler ('{method}'; '{tech}')"
    return strategy, polish, reason


def label_summary(data_dir, sample):
    """(evidence evaluated?, ambiguous source-plasmids, marker-free plasmids) from truth_labels.tsv."""
    if not data_dir:
        return False, 0, 0
    path = os.path.join(data_dir, sample, "truth_labels.tsv")
    if not os.path.isfile(path):
        return False, 0, 0
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    evaluated = bool(rows) and all(row.get("evidence_status") == "evaluated" for row in rows)
    ambiguous = sum(row.get("source_label") == "PLASMID" and row.get("final_label") == "AMBIGUOUS" for row in rows)
    marker_free = sum(row.get("marker_free") == "yes" for row in rows)
    return evaluated, ambiguous, marker_free


def tier(strategy, polish, quality, labels_evaluated):
    quality = (quality or "").strip().upper()
    if strategy in ("short_read_first_hybrid", "unknown"):
        return "3", f"{strategy.replace('_', ' ')} truth is provisional"
    if quality == "C":
        return "3", "cohort truth_quality_tier C"
    reasons = []
    if polish not in ("none", "independent"):
        reasons.append(f"polishing reads: {polish}")
    if quality != "A":
        reasons.append(f"cohort truth_quality_tier {quality or 'not recorded'}")
    if not labels_evaluated:
        reasons.append("replicon labels not evidence-checked")
    if reasons:
        return "2", "long-read-first; " + "; ".join(reasons)
    return "1", "long-read-first, independent of benchmark reads, tier A, evidence-checked labels"


def grade(reference_tier, same_extraction):
    """Truth quality grade A/B/C (scoring specification, WP2).

    A  reference tier 1 AND the sample sheet declares that the truth and the
       benchmark reads come from the same DNA extraction (same_extraction=yes).
    B  tier 1 without that declaration, or tier 2.
    C  tier 3 (short-read-first or unknown provenance, or cohort tier C).
    Grade A is never inferred: without the explicit field an isolate is at most B.
    """
    same = (same_extraction or "").strip().lower()
    if reference_tier == "3":
        return "C", "reference tier 3"
    if reference_tier == "1" and same == "yes":
        return "A", "tier 1 and same DNA extraction declared"
    if reference_tier == "1":
        return "B", "tier 1, same extraction not declared" if same != "no" else "tier 1, different extraction"
    return "B", "reference tier 2"


def derive(row, data_dir):
    sample = row["sample_id"]
    strategy = (row.get("truth_assembly_strategy") or "").strip()
    polish = (row.get("truth_polish_reads") or "").strip()
    source, reason = "sample_sheet", "declared in the sample sheet"
    if strategy and strategy not in STRATEGIES:
        raise ValueError(f"{sample}: truth_assembly_strategy must be one of {STRATEGIES}")
    if polish and polish not in POLISH:
        raise ValueError(f"{sample}: truth_polish_reads must be one of {POLISH}")
    truth_source = (row.get("truth_source") or "").strip()
    if not strategy:
        if truth_source == "self_assembled_hybrid":
            strategy, derived_polish = "short_read_first_hybrid", "same_as_benchmark"
            source, reason = "plasbench_self_built", "self-built Unicycler hybrid truth (short-read-first)"
        else:
            method, tech = assembly_info(data_dir, sample)
            strategy, derived_polish, reason = classify_method(method, tech)
            source = "ncbi_assembly_report" if (method or tech) else "unknown"
        if truth_source == "simulated" and derived_polish == "same_as_benchmark":
            # Benchmark reads are simulated FROM the truth, never used to build it.
            derived_polish = "independent"
            reason += "; benchmark reads are simulated, so they did not polish the truth"
        polish = polish or derived_polish
    polish = polish or "unknown"
    evaluated, ambiguous, marker_free = label_summary(data_dir, sample)
    reference_tier, tier_reason = tier(strategy, polish, row.get("truth_quality_tier"), evaluated)
    quality_grade, grade_reason = grade(reference_tier, row.get("same_extraction"))
    return {
        "sample": sample, "truth_assembly_strategy": strategy, "truth_polish_reads": polish,
        "provenance_source": source,
        "base_level_metrics_valid": "yes" if polish in ("none", "independent") else "no",
        "labels_evidence_checked": "yes" if evaluated else "no",
        "reference_tier": reference_tier, "tier_reason": tier_reason, "provenance_reason": reason,
        "ambiguous_plasmids": ambiguous, "marker_free_plasmids": marker_free,
        "truth_quality_grade": quality_grade, "grade_reason": grade_reason,
    }


FIELDS = ["sample", "truth_assembly_strategy", "truth_polish_reads", "provenance_source",
          "base_level_metrics_valid", "labels_evidence_checked", "reference_tier", "tier_reason",
          "provenance_reason", "ambiguous_plasmids", "marker_free_plasmids", "truth_quality_grade", "grade_reason"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--data-dir", help="DATA_DIR holding <sample>/assembly_data_report.jsonl and truth_labels.tsv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = [row for row in read_rows(args.sample_sheet) if row.get("sample_id")]
    try:
        derived = [derive(row, args.data_dir) for row in rows]
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(derived)
    counts = {}
    for row in derived:
        counts[row["reference_tier"]] = counts.get(row["reference_tier"], 0) + 1
    summary = ", ".join(f"tier {k}={v}" for k, v in sorted(counts.items())) or "no samples"
    sys.stderr.write(f"[truth_provenance] {summary} -> {args.out}\n")


if __name__ == "__main__":
    main()
