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

Two separate questions about a reference (the tier above mixes them; both are now recorded as their own columns, and the tier stays for reporting):
  reference_quality       validated | partially_validated | provisional      how far the reference itself can be trusted (tier 1 / 2 / 3)
  evaluation_independence independent | partially_independent | dependent | unknown   whether the reference is independent of the evidence the benchmarked tools use
      independent            long-read-only or long-read-first truth, polished with no reads or reads independent of the benchmark: structure AND bases do not depend on the benchmark's
                             Illumina data or assembly graph.
      partially_independent  long-read-first structure, but polished with the benchmark's own reads (or polishing unrecorded): structure is independent, bases are not, so identity-based
                             criteria are not applied and the claim is weaker.
      dependent              short-read-first hybrid: truth and tools resolve repeats on the same Illumina graph (circular evaluation).
      unknown                assembly strategy not recorded or not recognisable; never assumed independent.
The primary analysis uses independent references only (HEADLINE_INDEPENDENCE); sensitivity analyses add partially independent ones, then every reference. Dependent and unknown references
never enter the primary analysis. Quality and independence are separate: a tier-2 reference (cohort tier B, labels not checked) can still be independent, and is then eligible.

Evidence record (additive; every field is kept, the tier is derived from them and never replaces them). For each reference, six pieces of evidence are recorded,
each as `declared` (a sample-sheet column), `inferred` (from NCBI metadata or the truth-label table) or `unknown`; an unknown value NEVER demotes a reference:
  assembly_technology      long_read | hybrid | short_read | unknown            (sheet: truth_technology; else inferred from NCBI sequencingTech)
  circularity_evidence     independent | reported | uncertain | unknown         (sheet: truth_circularity_evidence)
  read_support             supported | partial | none | unknown                 (sheet: truth_read_support; else inferred from the long-read depth in truth_labels.tsv)
  replicon_evidence        markers_all | markers_partial | marker_free | unknown (inferred from truth_labels.tsv: replicon / MOB markers on the plasmids)
  structural_integrity     resolved | unresolved_repeats | unknown              (sheet: truth_structural_integrity)
  independent_validation   none | long_read_reassembly | pcr | hic | other | unknown (sheet: truth_independent_validation)
Only an explicit ADVERSE value (read_support none, structural_integrity unresolved_repeats) caps a Tier-1 reference at Tier 2, and says so in tier_reason.
`evidence_recorded` counts the fields that are not unknown ("3 of 6") and `evidence_sources` says declared / inferred / unknown for each.

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

TECHNOLOGY = ("long_read", "hybrid", "short_read", "unknown")
CIRCULARITY = ("independent", "reported", "uncertain", "unknown")
READ_SUPPORT = ("supported", "partial", "none", "unknown")
REPLICON_EVIDENCE = ("markers_all", "markers_partial", "marker_free", "unknown")
STRUCTURAL = ("resolved", "unresolved_repeats", "unknown")
VALIDATION = ("none", "long_read_reassembly", "pcr", "hic", "other", "unknown")
EVIDENCE_FIELDS = ("assembly_technology", "circularity_evidence", "read_support", "replicon_evidence", "structural_integrity", "independent_validation")
ADVERSE = {"read_support": "none", "structural_integrity": "unresolved_repeats"}
QUALITY = {"1": "validated", "2": "partially_validated", "3": "provisional"}
INDEPENDENCE = ("independent", "partially_independent", "dependent", "unknown")
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
    rows = label_rows(data_dir, sample)
    evaluated = bool(rows) and all(row.get("evidence_status") == "evaluated" for row in rows)
    ambiguous = sum(row.get("source_label") == "PLASMID" and row.get("final_label") == "AMBIGUOUS" for row in rows)
    marker_free = sum(row.get("marker_free") == "yes" for row in rows)
    return evaluated, ambiguous, marker_free


def label_rows(data_dir, sample):
    path = os.path.join(data_dir, sample, "truth_labels.tsv") if data_dir else ""
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def evidence_record(row, data_dir, tech_text=""):
    """({field: value}, {field: declared|inferred|unknown}, adverse reasons) for the six evidence fields; see the module doc."""
    sample = row["sample_id"]
    values, sources = {}, {}

    def declared(column, vocabulary):
        value = (row.get(column) or "").strip()
        if value and value not in vocabulary:
            raise ValueError(f"{sample}: {column} must be one of {vocabulary}")
        return value

    labels = label_rows(data_dir, sample)
    plasmids = [r for r in labels if r.get("source_label") == "PLASMID"]
    # assembly technology
    sheet = (row.get("truth_technology") or "").strip()
    sheet = sheet if sheet in TECHNOLOGY else ""
    if sheet:
        values["assembly_technology"], sources["assembly_technology"] = sheet, "declared"
    elif tech_text:
        long_read, short_read = bool(LONG_READ_TECH.search(tech_text)), bool(ILLUMINA.search(tech_text))
        inferred = "hybrid" if (long_read and short_read) else "long_read" if long_read else "short_read" if short_read else ""
        values["assembly_technology"], sources["assembly_technology"] = (inferred, "inferred") if inferred else ("unknown", "unknown")
    else:
        values["assembly_technology"], sources["assembly_technology"] = "unknown", "unknown"
    # circularity
    value = declared("truth_circularity_evidence", CIRCULARITY)
    values["circularity_evidence"], sources["circularity_evidence"] = (value, "declared") if value else ("unknown", "unknown")
    # read support: declared, else inferred from the long-read depth recorded per plasmid replicon
    value = declared("truth_read_support", READ_SUPPORT)
    if value:
        values["read_support"], sources["read_support"] = value, "declared"
    else:
        depths = []
        for r in plasmids:
            try:
                depths.append(float(r.get("long_read_depth")) if r.get("long_read_depth") not in (None, "") else None)
            except ValueError:
                depths.append(None)
        known = [d for d in depths if d is not None]
        if plasmids and known and len(known) == len(depths):
            inferred = "supported" if all(d > 0 for d in known) else "none" if not any(d > 0 for d in known) else "partial"
            values["read_support"], sources["read_support"] = inferred, "inferred"
        elif plasmids and known:
            values["read_support"], sources["read_support"] = "partial", "inferred"
        else:
            values["read_support"], sources["read_support"] = "unknown", "unknown"
    # replicon / MOB evidence, from the evidence-labelled truth
    evaluated = [r for r in plasmids if r.get("evidence_status") == "evaluated"]
    if plasmids and len(evaluated) == len(plasmids):
        free = sum(r.get("marker_free") == "yes" for r in plasmids)
        inferred = "marker_free" if free == len(plasmids) else "markers_partial" if free else "markers_all"
        values["replicon_evidence"], sources["replicon_evidence"] = inferred, "inferred"
    else:
        values["replicon_evidence"], sources["replicon_evidence"] = "unknown", "unknown"
    value = declared("truth_structural_integrity", STRUCTURAL)
    values["structural_integrity"], sources["structural_integrity"] = (value, "declared") if value else ("unknown", "unknown")
    value = declared("truth_independent_validation", VALIDATION)
    values["independent_validation"], sources["independent_validation"] = (value, "declared") if value else ("unknown", "unknown")
    adverse = [f"{name.replace('_', ' ')} {bad.replace('_', ' ')}" for name, bad in ADVERSE.items() if values.get(name) == bad]
    return values, sources, adverse


def tier(strategy, polish, quality, labels_evaluated, adverse=()):
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
    reasons += [f"evidence: {item}" for item in adverse]
    if reasons:
        return "2", "long-read-first; " + "; ".join(reasons)
    return "1", "long-read-first, independent of benchmark reads, tier A, evidence-checked labels"


def independence(strategy, polish):
    """(evaluation_independence, reason) from the truth assembly strategy and the polishing reads; see the module doc. An unrecognised strategy is 'unknown', never independent."""
    if strategy in ("long_read_only", "long_read_first_hybrid"):
        if polish in ("none", "independent"):
            return "independent", f"{strategy.replace('_', ' ')}; polishing reads {polish}"
        return "partially_independent", f"{strategy.replace('_', ' ')}; polishing reads {polish}, so the bases are not independent of the benchmark reads"
    if strategy == "short_read_first_hybrid":
        return "dependent", "short-read-first hybrid shares the benchmark's Illumina assembly graph"
    return "unknown", "assembly strategy not recorded or not recognised"


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
    _method, tech_text = assembly_info(data_dir, sample)
    evidence, evidence_sources, adverse = evidence_record(row, data_dir, tech_text)
    reference_tier, tier_reason = tier(strategy, polish, row.get("truth_quality_tier"), evaluated, adverse)
    quality_grade, grade_reason = grade(reference_tier, row.get("same_extraction"))
    eval_independence, independence_reason = independence(strategy, polish)
    recorded = sum(1 for name in EVIDENCE_FIELDS if evidence[name] != "unknown")
    return {
        "sample": sample, "truth_assembly_strategy": strategy, "truth_polish_reads": polish,
        "provenance_source": source,
        "base_level_metrics_valid": "yes" if polish in ("none", "independent") else "no",
        "labels_evidence_checked": "yes" if evaluated else "no",
        "reference_tier": reference_tier, "tier_reason": tier_reason, "provenance_reason": reason,
        "ambiguous_plasmids": ambiguous, "marker_free_plasmids": marker_free,
        "truth_quality_grade": quality_grade, "grade_reason": grade_reason,
        **evidence, "evidence_recorded": f"{recorded} of {len(EVIDENCE_FIELDS)}",
        "evidence_sources": "; ".join(f"{name}: {evidence_sources[name]}" for name in EVIDENCE_FIELDS),
        "reference_quality": QUALITY[reference_tier], "evaluation_independence": eval_independence, "independence_reason": independence_reason,
    }


FIELDS = ["sample", "truth_assembly_strategy", "truth_polish_reads", "provenance_source",
          "base_level_metrics_valid", "labels_evidence_checked", "reference_tier", "tier_reason",
          "provenance_reason", "ambiguous_plasmids", "marker_free_plasmids", "truth_quality_grade", "grade_reason",
          *EVIDENCE_FIELDS, "evidence_recorded", "evidence_sources", "reference_quality", "evaluation_independence", "independence_reason"]


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
