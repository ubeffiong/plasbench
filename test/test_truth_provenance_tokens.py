#!/usr/bin/env python3
"""truth_provenance.classify_method on the REAL wording found in the cohorts, against an independently written oracle, and the cohort sheets against classify_method.

The audit of 17 November 2026 found that the word-boundary patterns missed OXFORD_NANOPORE, IlluminaMiSeq and the Illumina polishers, so 218 genuine short-read-first
assemblies were 'unknown' and nine Illumina-polished ones were 'independent'. The older test used hand-written strings; this one uses every distinct (assembly method,
sequencing technology) pair of the shipped cohorts.
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import truth_provenance as tp  # noqa: E402

TAB = chr(9)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


# ---- 1. the audit's examples ----
cases = [
    ("Unicycler v0.4.7", "Hybrid: Illumina and OXFORD_NANOPORE", ("short_read_first_hybrid", "same_as_benchmark")),
    ("Unicycler v0.4.7", "IlluminaMiSeq; PacBio", ("short_read_first_hybrid", "same_as_benchmark")),
    ("Uniclycler v0.4", "Illumina; ONT", ("short_read_first_hybrid", "same_as_benchmark")),
    ("Unicycler", "Illumina; PromethION", ("short_read_first_hybrid", "same_as_benchmark")),
    ("Polypolish v0.5; Flye", "Oxford Nanopore", ("long_read_first_hybrid", "same_as_benchmark")),
    ("Pilon v1; Flye", "PACBIO_SMRT", ("long_read_first_hybrid", "same_as_benchmark")),
    ("Trycycler+Medaka+Polypolish v. JUL-2022", "Oxford Nanopore MinION", ("long_read_first_hybrid", "same_as_benchmark")),
    ("HGAP v. 2.3.0", "PacBio, IlluminaMiSeq", ("long_read_first_hybrid", "same_as_benchmark")),
    ("RS_HGAP_Assembly.3 v. 2.3.0", "PacBio RS II", ("long_read_only", "none")),
    ("Flye v. 2.4.1-geb89c9e; Unicycler_polish v. 0.4.8", "PacBio RSII; Illumina MiSeq", ("long_read_first_hybrid", "same_as_benchmark")),
    ("Flye v. 2.9", "Oxford Nanopore", ("long_read_only", "none")),
]
for method, tech, want in cases:
    got = tp.classify_method(method, tech)[:2]
    check(f"{method!r} + {tech!r} -> {want[0]}/{want[1]}", got == want, got)


# ---- 2. an independent oracle over every distinct pair in the shipped cohorts ----
def squash(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


LONG_ASM = ("flye", "canu", "raven", "trycycler", "trycyler", "autocycler", "dragonflye", "hybracter", "miniasm", "necat", "nextdenovo", "wtdbg", "hifiasm", "smartdenovo", "hgap", "falcon")
SHORT_ASM = ("unicycler", "uniclycler", "masurca", "spades")
ILLUMINA = ("illumina", "miseq", "hiseq", "nextseq", "novaseq", "miniseq", "iseq", "bgiseq", "dnbseq", "mgiseq", "polypolish", "pilon", "pypolca", "polca", "nextpolish", "unicyclerpolish")
LONG_TECH = ("nanopore", "pacbio", "smrt", "minion", "gridion", "promethion", "sequel", "revio", "hifi", "rsii")


def oracle(method, tech):
    m, t = squash(method), squash(tech)
    both = m + t
    ill = any(k in both for k in ILLUMINA)
    m_short = m.replace("unicyclerpolish", "")
    long_asm = any(k in m for k in LONG_ASM)
    short_asm = any(k in m_short for k in SHORT_ASM)
    if long_asm and not short_asm:
        return ("long_read_first_hybrid", "same_as_benchmark") if ill else ("long_read_only", "none")
    if short_asm and not long_asm:
        return ("short_read_first_hybrid", "same_as_benchmark") if (ill and (any(k in t for k in LONG_TECH) or "ont" in re.split(r"[^a-z0-9]+", (tech or "").lower()))) else ("unknown", "unknown")
    return None                              # ambiguous for the oracle: not compared


def sheet_rows(path):
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


pairs = {}
for name in ("public-v4.tsv", "negative-controls-v1.tsv"):
    for row in sheet_rows(os.path.join(ROOT, "cohorts", name)):
        method, tech = row.get("assembly_method", ""), row.get("assembly_sequencing_technology", "")
        if method or tech:
            pairs[(method, tech)] = pairs.get((method, tech), 0) + 1
compared = disagree = 0
examples = []
for (method, tech), n in pairs.items():
    want = oracle(method, tech)
    if want is None:
        continue
    compared += n
    got = tp.classify_method(method, tech)[:2]
    if got != want:
        disagree += n
        if len(examples) < 12:
            examples.append((method[:50], tech[:40], got, want))
check(f"classify_method agrees with the independent oracle on {len(pairs)} distinct real (method, technology) pairs ({compared} rows compared)", disagree == 0, (disagree, examples))
check("most of the cohort is decided by the oracle (the check is not vacuous)", compared > 0.8 * sum(pairs.values()), (compared, sum(pairs.values())))

# ---- 3. the shipped sheets carry the labels classify_method gives ----
for name in ("public-v4.tsv", "negative-controls-v1.tsv"):
    bad = 0
    for row in sheet_rows(os.path.join(ROOT, "cohorts", name)):
        method, tech = row.get("assembly_method", ""), row.get("assembly_sequencing_technology", "")
        if method or tech:
            s, p, _ = tp.classify_method(method, tech)
            bad += (row["truth_assembly_strategy"], row["truth_polish_reads"]) != (s, p)
    check(f"{name}: every row's strategy and polish are what classify_method gives now (python/relabel_cohort_provenance.py rewrites the sheet and its lock hash)", bad == 0, bad)

print("ALL TRUTH PROVENANCE TOKEN TESTS PASSED" if ok else "TRUTH PROVENANCE TOKEN TESTS FAILED")
sys.exit(0 if ok else 1)
