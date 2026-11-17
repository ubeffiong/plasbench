# External review and validation log

This is the register of every review PlasBench has received, what each asked, how it was answered, and what independent evidence now
supports the answer. It exists so that a reader can see what has been challenged and what has not, instead of taking the project's own
account on trust.

## How to read it

Every review is labelled with its **source type**, because they are not equal evidence and this log does not present one as another:

| Type | Meaning |
|---|---|
| **Human reviewer** | A person or panel outside the code base gave the feedback (as reported to the project lead). |
| **Question bank** | A list of questions put to the project, answered item by item. |
| **AI-assisted** | An analysis produced by an AI system, supplied or commissioned by the project lead. Useful as a sceptical read, but not peer review, and checked here against the code and the sources before anything was changed. |
| **Automated** | A test, simulation or CI job that anyone can re-run. |

**What this log does not show.** Reviewer names, affiliations and the original wording of human reviews are not stored in the repository. Add them
with each reviewer's consent. None of this is journal peer review of a publication, and no third party has independently re-run a PlasBench
benchmark (see "Not yet done").

## Reviews received

| ID | Date | Source | Type | What it examined | Where it was answered |
|---|---|---|---|---|---|
| R1 | 2026-11-08 to 11-10 (v0.2.0) | Reviewer question bank (108 questions, later 500) | Question bank | Research problem, biology, sequencing, binning, similarity, AMR, databases, statistics, comparators, engineering, governance, publication | `docs/FAQ_QUESTION_BANK.md`; tracker `docs/REVIEW_TRACKER.tsv` |
| R2 | 2026-11-08 (v0.2.0) | Panel examination, rounds 1 to 5 and the edge-case laboratory, with Scoring Specification v0.1 | Human reviewer (panel) | Scope, scoring, truth, pre-registration, outcome states, recommender | `docs/PANEL_ALIGNMENT.md`; `docs/PREREGISTRATION.md` |
| R3 | 2026-11-08 | Independent scientific, technical and innovation review (16 parts, 17-domain scorecard) | AI-assisted | The idea and the implementation, sceptically | `docs/INDEPENDENT_REVIEW.md` (historical; superseded by R4 where they overlap) |
| R4 | 2026-11-15 | Second external scientific and technical review (a static review of `main`; the reviewer did not run the pipeline) | Human reviewer | Task classification, reference independence, interval calibration, AMR placement, recommender validation | `docs/reviews/SECOND_REVIEW_RESPONSE.md`; v0.4.0 |
| R5 | 2026-11-16 | Third review | Human reviewer (as recorded in the changelog) | Task derivation, intervals for dominated cohorts, documentation consistency | `CHANGELOG.md`, "third review"; `test/test_docs_consistency.py` |
| R6 | 2026-11-16 | Comparison of PlasBench with the PlasEval paper (Mane et al. 2024) and a recommendation to adopt its framework | AI-assisted (supplied by the project lead) | Whether PlasBench captures PlasEval's bin dissimilarity, repeat-aware matching and error decomposition | FAQ Q2 and Q31; `docs/PLASEVAL_REPLICATION.md`; PRs #87 and #91 |
| R7 | 2026-11-16 | Reviewers' three questions: can the assembly be chosen; is there QC of the short reads and a rejection policy; how is noise picked up when a tool reports several sequences for one plasmid | Human reviewers, with an AI-assisted analysis and plan supplied by the project lead | Input control and ambiguous reconstruction output | FAQ Q32 to Q35 |
| R8 | 2026-11-15 to 11-16 | Field testing by the project lead on two Windows computers using WSL: first install, launch, upgrade, git use | Human (project lead, as user) | Whether it installs and starts on a machine that is not the developer's | v0.4.1 and `docs/PLASEVAL_REPLICATION.md` |
| R9 | 2026-11-16 | Scientific reviewer interrogation: a 215-question bank in 15 domains, twelve oral-defence questions, a roadmap (PB-01 to PB-12) and a four-test assessment (truth, attribution, scoring and generalisation validity) | AI-assisted, supplied by the project lead; it states it did not inspect the live repository | Whether the metrics, references, inputs and statistics support the conclusions | [`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md), FAQ Q36 to Q42 |
| R10 | 2026-11-16 | Literature and public-data review (PlasEval, Teixeira 2025, plsMD 2026, MOB-suite) with published AMR-context and relatedness figures | AI-assisted, supplied by the project lead; it states it could not run the code | Which public cohorts and evaluation dimensions to adopt; which published visual designs to adopt | [`cohorts/candidates/PUBLICATION_COHORTS.md`](../cohorts/candidates/PUBLICATION_COHORTS.md), FAQ Q43 |

## What each review found, what was done, and what remains

### R1. Reviewer question bank
All 500 question numbers are covered by 32 tracker rows. Four sections (about clustering, relatedness, database search and phylogeny) concern functions
outside a benchmarking pipeline and are marked out of scope, not answered. The questions drove most of the additional metrics (nucleotide accuracy,
feature preservation, bin quality, contig-level classification, performance, power) and the FAQ. **Open items** are listed in the FAQ's "What is still
open" and the README's table of the same name.

### R2. Panel examination
Decisions were frozen in `docs/PREREGISTRATION.md`: the NCBI label is the primary truth, outcome states distinguish a tool failure from an
infrastructure failure, and recommendation is evaluated out of sample. Two parameters were left `TO_FIX` until the panel decided; they were later
resolved or marked `unavailable` (see R4).

### R3. Independent review (AI-assisted)
Verdict: promising but requires methodological refinement. Its main findings were no real-data result, truth that is only partly independent of the reads
the tools are scored on, leakage controlled by date, a significance test that could not reach p below 0.05 with five clusters, and unjustified scoring
thresholds. The statistics and truth-independence items were taken up in R4's response (a six-unit minimum for a test, intervals chosen by simulation,
reference independence recorded beside quality, a primary analysis that reports itself unavailable instead of falling back). **Still open:** a real-data
run, threshold derivation, and an independent audit of references. Every claim in it cites a file and line, checked by `test/test_independent_review_ledger.py`.

### R4. Second external review
Every P0 and P1 item was addressed in v0.4.0 and is tabulated, with its test and status, in `docs/reviews/SECOND_REVIEW_RESPONSE.md`. The interval
simulation (1,000 replicates per design) shows the cluster-robust t interval close to 95% for balanced designs and **below nominal for unbalanced study
sizes**, which is reported as a limitation, not hidden (`docs/STATS_VALIDATION.md`, `docs/validation/stats_validation_full.tsv`). The review's later-phase
items (run `public-v3`, broaden species, a difficult-plasmid panel) are **open**.

### R5. Third review
Task derivation is strict, so a reassembler is never treated as a classifier; a cohort dominated by one study uses the percentile interval; the manifest
records the interval and independence settings; and a consistency test checks the documentation against the code. Source text of the review is not in the
repository.

### R6. PlasEval paper comparison (AI-assisted)
The analysis recommended adopting PlasEval's repeat-aware dissimilarity as a binning diagnostic, not as a replacement for PlasBench's endpoints. Checking it
against the paper's full text and the code showed several of its "missing" claims were already implemented (normalised dissimilarity, the four components,
tool-versus-tool agreement, a configurable length exponent). The real gap, repeat-aware pairing of repeated contigs, is now implemented and **agrees with
the original program on 59 constructed and random cases (44 with repeats)**. The 53-isolate cohort and the paper's published bins ship; a gate compares PlasBench
with the original program wherever it is installed. **The comparison on the paper's real bins is done**: PlasBench agreed with the original within 0.001
on 210 of the 211 pairs the original finished, with no disagreement (the one difference, 0.003, is a capped-search upper bound); see `docs/PLASEVAL_REPLICATION.md`.

### R7. Reviewers' three questions
| Question | Answer in one line | Status |
|---|---|---|
| Can the assembly be chosen? | Yes, by a declared policy from assembly-side evidence only; every candidate is kept; nothing is silently substituted | Implemented; running every tool on every alternative is open |
| Is there short-read QC and a rejection policy? | Yes: a PASS/WARN/REJECT gate before assembly; integrity failures always reject, thresholds are provisional | Implemented; thresholds to be frozen on pilot data |
| How is noise picked up when a tool gives several sequences for one plasmid? | Every predicted record is accounted for: best versus combined (union) coverage, redundancy, and a relationship per candidate | Implemented on constructed cases; real cohort not yet run |

Suggested wording for a reply to these reviewers: PlasBench already had fastp trimming, input checks, an advisory post-assembly size and GC flag, a one-to-one bin
match, split and merge diagnostics, CPRR and predicted-sequence burden. In response to your comments it now has a pre-assembly short-read eligibility gate
(PASS, WARN, REJECT, with reasons), a declared assembly-selection policy that never uses benchmark results, and a candidate-level multiplicity analysis that
separates the best single reconstruction from combined non-redundant coverage and labels duplicate, fragmented, chimeric, off-target and unmapped output. The
quality thresholds are provisional and will be frozen on pilot data before the main benchmark; the default mode reports and flags rather than excludes
(except unreadable files) until then. Not yet done: running every tool on each alternative assembly, taxonomic contamination screening, and a run of the
multiplicity analysis on a real cohort.

### R8. Field testing
Problems found on two machines were fixed in v0.4.1: the launcher exited on a conda activation script, `install-tools all` failed as a whole when one large
optional environment ran out of memory, a failed download did not say why, and the window's browser profile and session-key page were unclear. A further problem
with the desktop icon not opening the window is open and is being handled by the project lead.

### R9. The 215-question assessment: what was found and done

The review judged PlasBench a substantially developed framework whose strongest claims still need real-data evidence, and named input integrity,
reconstruction multiplicity and independent real-data validation as the next priorities. Input integrity and multiplicity were already closed in R7.
Checked against the code, the genuinely missing pieces were: leave-one-study/species-out and equal-study-weighted rankings
(`python/ranking_stability.py`), an assembler-sensitivity comparison (`python/assembler_sensitivity.py`), and a single per-isolate reference
evidence audit (`python/reference_evidence_audit.py`); each is built, tested and wired into the report. The assessment of all 215 questions is in
[`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md): 77 satisfied, 86 partially satisfied, 51 needing validation, 1 major gap (a novel
plasmid cannot be told from an incorrect reconstruction). The matrix is the project's own reading of its code, not an independent review. Not done:
a seven-step tool validation ladder beyond what exists (FAQ Q40), a real multi-assembler run, and real independent cohorts.

### R10. The literature and public-data review: what was found and done

The review proposed seven evaluation domains and four phases and asked for the published cohorts and figures to be adopted. Checked against the code, most reconstruction, AMR
and structure dimensions already exist (FAQ Q43). Added: the AMR regions view, the synteny ribbons and an AMR information funnel (all interactive, descriptive), and the
cohorts of plsMD (filtered and novel) and the MOB-suite benchmark as candidates, with their supplement tables, ENA run metadata and the caveats found when adopting them (for
example 23 of the 68 plsMD novel runs were public before the stated sequencing date, so "novel" is the paper's claim). Not adopted: phylogeny, clustering and relatedness,
pangenome, host-range and transmission analyses, which are outside the benchmark by an earlier decision. Done afterwards (2026-11-17): the candidates were resolved at NCBI and built into runnable, verified publication cohorts with the papers' own outcomes and a
`compare-published` comparison (`docs/PUBLICATION_COMPARISON.md`); Teixeira's 245 isolates without a deposited assembly still need a rebuilt truth. The remaining gaps were then closed in code (2026-11-17): PlasmidEC is a registered tool (stand-in tested), PLSDB novelty and a
multivariable performance-drivers regression are stage-6 analyses with report sections, and `negative-controls-v1` provides 136 verified plasmid-free controls. Still open:
running any tool on these cohorts (nothing here has been run on real tool output), a real PLSDB download for the novelty analysis, and rebuilding Teixeira's hybrid truth.

## Validation evidence

| Evidence | What it shows | Status |
|---|---|---|
| Test suite (more than 300 test files) and CI on every pull request: the `test` job, the container build, real minimap2 for the aligner tests | Scoring, aggregation, adapters, stages and reports behave as specified on constructed data | Done; runs on every change |
| Scoring controls: oracle, empty, whole-genome, chromosome-only and plasmid-free predictions; hand-computed expectations | The scorer returns the right numbers on known inputs | Done |
| Statistics simulation (`docs/STATS_VALIDATION.md`) | Interval coverage and the type I error of the paired tests, by design | Done; unbalanced designs fall below nominal and are reported |
| Cross-check of the scoring against a BLASTN scoring (`python/compare_scoring_methods.py`) | The minimap2-based scoring is not an artefact of the aligner | Done once; not part of CI |
| PlasEval cross-check against the original program, 59 cases | PlasBench's best-match scores and repeat-aware dissimilarity equal the original's | Done on Linux; runs only with a PlasEval checkout |
| PlasEval replication on the paper's real bins (212 isolate-tool pairs) | PlasBench's numbers on real bins; agreement with the original on them | Done 16 Nov 2026: 211 of 212 pairs compared with the original program, **210 agree within 0.001, 0 disagree**, 1 capped-search upper bound (0.003), 1 original timeout; rerunnable by any user, see `docs/PLASEVAL_REPLICATION.md` |
| Short-read QC, assembly selection and candidate multiplicity tests, including stage-level tests with stand-in tools | Each gate, policy and table behaves as specified, including enforce, report and off | Done on constructed data |
| Ranking stability, assembler sensitivity, reference evidence audit and reviewer matrix tests | Each module on constructed cohorts, including a cohort whose leader changes when one study is removed; the matrix's 215 rows, statuses and file references | Done; real-cohort results **Open** |
| AMR regions, synteny ribbons and publication-cohort candidate tests | Both views on constructed data (well-formed SVG, valid script, escaping, caps, not-run states) and in the demo report; the candidate tables' counts against the papers | Done on constructed data; not yet looked at on a real cohort |
| Field install and upgrade on two Windows/WSL machines | It installs and starts on a machine other than the developer's | Done for v0.4.1; the desktop icon is open |

## Not yet done

- **Running tools on the publication cohorts** and reading the comparison with the papers; **rebuilding Teixeira's hybrid truth** for the 245 isolates with no deposited assembly; **looking at the new views on a real cohort**.
- A **real multi-assembler comparison** with `assembler_sensitivity.py`, and a **real-cohort ranking-stability** result.
- A **real-data run** of the benchmark on `public-v3`, published with intervals and the manifest. Nothing about ranking or generalisation is demonstrated until then.
- An **independent third-party re-run** of a benchmark, and an **external validation cohort**.
- **Frozen thresholds** for the short-read QC, assembly eligibility and candidate relationships, set from pilot data.
- An **independent audit of the references**, plasmid-free and hard-structure isolates, and taxonomic contamination screening.
- Reviewer names, affiliations and original text, with consent.

## Adding an entry

Add a row to the register with a date, the source, its type from the table above, what it examined and where it was answered; add a short section under "What each review
found"; and add any new validation to the evidence table with its honest status. `test/test_external_review_log.py` checks that every path cited here exists.
