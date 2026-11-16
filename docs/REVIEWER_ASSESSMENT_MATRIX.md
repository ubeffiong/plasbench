# Reviewer assessment matrix (215 questions)

A 215-question reviewer bank was put to PlasBench (16 November 2026, AI-assisted review; not journal peer review; see
[`EXTERNAL_REVIEW_LOG.md`](EXTERNAL_REVIEW_LOG.md)). This matrix records, for every question, the PlasBench component that answers it,
the status, the evidence in the repository and what is still needed. The full table is
[`REVIEWER_ASSESSMENT_MATRIX.tsv`](REVIEWER_ASSESSMENT_MATRIX.tsv).

**This is the project's own assessment of its implementation, made by reading the code and tests. It is not an independent review.** A status of
*Satisfied* means a capability exists and a test exercises it; it does not mean the scientific claim has been validated on real data.

| Status | Meaning |
|---|---|
| Satisfied | The capability exists and a test in `test/` exercises it. |
| Partially satisfied | The capability exists but its validation or coverage is incomplete. |
| Needs validation | The method exists; the evidence that it works on real, independent data does not. |
| Major gap | A missing capability or an unresolved weakness. |
| Not applicable | Outside the benchmark's scope. |

## Totals

| Satisfied | Partially satisfied | Needs validation | Major gap | Not applicable |
|---|---|---|---|---|
| 77 | 86 | 51 | 1 | 0 |

## By section

| Section | Satisfied | Partially satisfied | Needs validation | Major gap |
|---|---|---|---|---|
| A. Scientific purpose and scope | 7 | 2 | 1 | 0 |
| B. Reference truth and biological validity | 2 | 10 | 2 | 0 |
| C. Sequencing data quality and input eligibility | 3 | 10 | 1 | 0 |
| D. Assembly selection and fairness | 4 | 5 | 1 | 0 |
| E. Tool selection, configuration and validation | 7 | 8 | 0 | 0 |
| F. Scoring methodology | 7 | 15 | 3 | 0 |
| G. Multiple candidate reconstructions and output noise | 14 | 5 | 0 | 0 |
| H. Difficult biological scenarios and generalisability | 0 | 3 | 18 | 1 |
| I. AMR and biological feature preservation | 7 | 6 | 0 | 0 |
| J. Statistical validity and strength of evidence | 9 | 2 | 7 | 0 |
| K. Dataset-conditioned recommendations | 9 | 0 | 6 | 0 |
| L. Metagenomic benchmarking | 0 | 14 | 0 | 0 |
| M. Reproducibility, computational performance and usability | 8 | 5 | 2 | 0 |
| N. Novelty and scientific contribution | 0 | 1 | 10 | 0 |

## What the review asked for and where it now lives

| Request | Where |
|---|---|
| Short-read QC and eligibility gate | `python/short_read_qc.py`, FAQ Q33 |
| Assembly selection policy | `python/assembly_selection.py`, FAQ Q32 |
| Assembler sensitivity (does the ranking depend on the assembly?) | `python/assembler_sensitivity.py`, FAQ Q38 |
| Candidate multiplicity and redundancy | `python/candidate_multiplicity.py`, FAQ Q34 |
| Reference evidence audit | `python/reference_evidence_audit.py`, `benchmark.reference_evidence_audit.tsv`, FAQ Q39 |
| Leave-one-study/species-out and equal-study-weighted ranking | `python/ranking_stability.py`, FAQ Q37 |
| Tool validation hierarchy | `config/tool_capabilities.tsv` `validation_status`, FAQ Q40 |
| Repeat-aware matching validated against the original | `python/bin_agreement.py`, `docs/PLASEVAL_REPLICATION.md` |

## The one major gap

Q127: PlasBench cannot tell a genuinely novel plasmid from an incorrect reconstruction without independent evidence. It reports recovery on
plasmids absent from a tool's own database, which approximates novelty, but it does not model it.

## Not changed on purpose

CPRR is not replaced, PlasEval is not made the universal scorer, no composite score is introduced, and the recommender is not tuned until it
has been evaluated on independent studies. The reasons are in FAQ Q41.
