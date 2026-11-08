# PlasBench FAQ: hard questions, evidence-based answers

These are the questions a reviewer, funder or new user is most likely to ask. Every
answer cites the code, test or data file that supports it. Where the evidence showed a
gap, the gap is either fixed (with a test) or stated as open, with the reason it
cannot be fixed in software.

**Status labels**

| Label | Meaning |
|---|---|
| **Verified** | A test in `test/` exercises it, or the number was computed from a file in this repository. |
| **Fixed here** | The evidence exposed a gap; the fix and its test were added alongside this FAQ. |
| **Fixed on audit branch** | Fixed and tested on `tmp/audit-all` / `fix/audit-followthrough` (see the Scientific Guide). Confirm it is on `main` before relying on it. |
| **Documented** | Stated in the docs, not enforced or tested by code. |
| **Open** | Not done. The reason is given (usually: it needs real data, not code). |

A companion file, [docs/FAQ_QUESTION_BANK.md](docs/FAQ_QUESTION_BANK.md), answers the longer reviewer question bank and
cross-references the question numbers here.

Evidence basis: [docs/INDEPENDENT_REVIEW.md](docs/INDEPENDENT_REVIEW.md) (independent review and audit), the source files named in
each answer, and the test suite. A full run of `test/run_tests.sh` is the check on the
"Verified" claims; see Q24 for its result. Nothing here has been checked against a
real-cohort run, because none exists yet (Q22).

---

## A. Scope

### Q1. What is PlasBench, and what is it not?
**Answer.** PlasBench benchmarks plasmid reconstruction and classification tools. It maps
each tool's predicted-plasmid FASTA onto a complete reference with minimap2 and scores
per reference base: plasmid bases covered are TP, chromosome bases covered are FP,
plasmid bases missed are FN (`python/score_plasmids.py`, `scripts/05_score.sh`). It is
**not** a plasmid identification tool.
**Evidence.** README "How scoring works (at a glance)"; Scientific Guide section 1.3 ("What it is not").
**Status.** Verified. The scope statement is in the docs.

### Q2. Is the scorer checked against an independent evaluator?
**Answer.** Partly. PlasEval (Mane et al., *BMC Bioinformatics* 2024) is a framework for evaluating plasmid binning that is
aware of contig length and of repeats. PlasBench can import a PlasEval run as a labelled, non-ranking cross-check
(`plasbench import-external-benchmark`) but does not run it, and a one-off script compares the minimap2 scoring with a BLASTN
scoring (`python/compare_scoring_methods.py`).
**Evidence.** `docs/METHODS.md`, "External evaluator cross-checks"; `python/compare_scoring_methods.py`.
**Status.** Cross-check import done; a first-class PlasEval adapter is **Open** (it needs the external tool and real data to
validate).

---

## B. Truth

### Q3. Where does truth come from, and can a mislabelled sequence go unnoticed?
**Answer.** Truth is the submitter's `assigned_molecule_location_type` for NCBI assemblies
(`python/make_truth.py`), so a chromid, an integrated plasmid or a mislabelled record is
treated as certain. Until now nothing cross-checked the label.
**Fix.** `python/audit_truth_labels.py` compares each truth sequence with replicon/MOB
evidence in `truth_features.tsv` and writes `benchmark.truth_label_audit.tsv`
(run by `scripts/06_aggregate.sh`, shown in the HTML report's "Truth-label audit" section, and available as
`plasbench audit-truth-labels`). Findings: `consistent`,
`chromosome_with_plasmid_markers`, `plasmid_without_markers`, `not_evaluated`. It never edits
`truth.tsv` and never changes a score.
**Evidence.** `test/test_audit_truth_labels.py`. The test checks the part that matters
most for honesty: absence of a marker on a plasmid is reported only when *both* the
replicon and MOB callers ran (per `annotation_provenance.json`); otherwise the finding
is `not_evaluated`, never "consistent".
**Status.** Fixed here. Limits: it is a screen against databases, so a cryptic plasmid
without a known replicon is flagged for review, not declared wrong. Read-depth support for
each truth replicon is **Open** (needs the reads and a long-read mapping step).

### Q4. What if the "complete" reference missed a small plasmid, or collapsed a repeat?
**Answer.** Then a tool that finds it is penalised. The docs say so.
**Evidence.** `docs/METHODS.md`, "Known limitations / honest caveats" (Reference completeness).
**Status.** Documented. Not fixable in software: it needs independent confirmation of each
truth replicon.

### Q5. What happens to a truth sequence nobody classified?
**Answer.** Earlier behaviour defaulted it to CHROMOSOME with only a printed counter.
**Evidence.** `python/make_truth.py` now has an `--allow-default` opt-in (6 references) and
`scripts/02_truth.sh` passes it through; `test/test_make_truth.py`.
**Status.** Fixed on audit branch (differs from `main` for `make_truth.py`).

### Q6. Is truth ever built from the same reads a tool is scored on?
**Answer.** For the long-read track, self-assembled hybrid truth is barred by schema.
**Evidence.** `test/test_self_assembled_hybrid_schema.py`, `test/test_long_read_truth_eligible.sh`.
**Status.** Verified.

---

## C. Scoring

### Q7. Does the scorer return the right number, and how would we know?
**Answer.** Hand-computed examples existed (`test/test_scoring.py`), but there were no
control predictions with analytically known answers. `test/test_scoring_controls.py`
now checks six: oracle (F1 = 1), empty prediction (recall 0, precision blank, F1 = 0),
predict-the-whole-genome (recall 1, precision 0.2 on a 2,000 / 10,000 bp reference),
chromosome-only (F1 0), half-oracle (precision 1, recall 0.75), and a plasmid-free
isolate (recall and F1 blank, FP counted). All pass.
**Status.** Fixed here.

### Q8. Does the scorer behave the same with the real aligner as with the hand-written PAFs?
**Answer.** Every earlier scoring test fed the scorer a hand-written PAF, so the minimap2
invocation the pipeline uses was never exercised in tests, and CI installs with
`--no-deps` (no aligner).
**Fix.** `test/test_scoring_real_minimap2.py` builds seeded sequences, aligns with
`minimap2 --secondary=no -c -x asm5`, and scores with the pipeline filter defaults. It
skips cleanly when minimap2 is absent. `.github/workflows/ci.yml` now installs minimap2.
**Evidence.** Run against minimap2 2.26-r1175 in WSL: all five checks passed (an exact
4,000 bp plasmid copy scored precision 1 and recall 0.667; an unrelated 2,000 bp
prediction stayed unmapped and was not counted as FP).
**Status.** Fixed here. The CI step itself has not run yet (needs a push).

### Q9. Is precision optimistic?
**Answer.** Yes, by design. Predicted bases with no retained alignment (unmapped, or
removed by the length / identity / MAPQ / query-coverage filters) are neither TP nor FP.
A tool emitting chimeric or repeat-rich contigs that fail MAPQ 20 pays no precision
penalty on the headline metric.
**Evidence.** `score_plasmids.py` reports `unmapped_pred_bp`, `off_truth_pred_bp` and
`strict_precision` separately (lines 26-29, 130-134, 239-247). Pipeline filters are
MAPQ 20, identity 0.90, length 200, query coverage 0.20 (`config/config.sh:415-418`); the
scorer's own CLI defaults are permissive (0 / 0 / 1 / 0).
**Mitigation.** `python/rank_sensitivity.py` re-scores every PAF on disk with one filter
changed at a time, re-ranks under strict F1 and per-plasmid recovery, and writes
`benchmark.rank_robustness.tsv` (Kendall tau, top-tool change); it is called by
`scripts/06_aggregate.sh`. Tests: `test/test_rank_sensitivity.py`,
`test/test_scoring_adversarial.py`. The HTML report shows it in the "Ranking robustness" section
(`test/test_report_robustness_audit.py`).
**Status.** Fixed on audit branch (measured, not removed). Note that on `main` (#7) binning-capable tools are
ranked on the length-weighted binning F1 (`ranking_score`) with CPRR as the secondary endpoint, and `mean_f1`
remains the base-level F1 for every tool; the sensitivity analysis re-ranks under strict F1 and per-plasmid
recovery, whichever metric is the headline.
Whether the real-cohort ranking is stable is **Open** (no real run).

### Q10. Do large plasmids dominate the score?
**Answer.** In pooled base-level F1, yes: a 150 kb plasmid outweighs five 5 kb ones 30:1.
**Evidence.** Per-plasmid recovery (`--per-plasmid-out`, `plasmid_recall`, the ≥50% / ≥90%
bands) is reported next to F1; the sensitivity analysis in Q9 re-ranks by per-plasmid
recovery.
**Status.** Documented and measurable; the ranking metric is unchanged by design.

### Q11. Are duplicated or multimeric predictions rewarded?
**Answer.** No: intervals are merged, so a duplicate earns no extra TP and no penalty.
`redundant_pred_bp` reports it. A multimer-collapsing tool and a multimer-emitting tool tie.
**Evidence.** `test/test_redundant_coverage.py`; [docs/INDEPENDENT_REVIEW.md](docs/INDEPENDENT_REVIEW.md).
**Status.** Verified. Reported, not penalised.

### Q12. How is an isolate with no plasmids scored?
**Answer.** Recall and F1 are blank (undefined), never 0; `isolate_specificity` and
`chromosome_fp_bp` carry the signal. An empty prediction on an isolate with plasmids is
F1 = 0 with blank precision.
**Evidence.** `test/test_zero_plasmid_isolate_scoring.py`; `test/test_scoring_controls.py`.
**Status.** Verified. No plasmid-free isolate is in the shipped cohorts, so this is
exercised by tests, not by data (Open, needs cohort additions).

### Q13. What if a tool crashes or is unsupported?
**Answer.** Failure counts as F1 = 0 on the shared-sample ranking, so abstaining cannot
game the leaderboard. An all-fail tool still appears, ranked last, in its own track.
Out-of-memory and timeout exits (124, 137) are classed as resource failures, and skipped
runs no longer raise the failure rate.
**Evidence.** `aggregate_results.py` (`n_failed_resource`, line 383);
`test/test_aggregate_failures.py`, `test/test_failed_tool_exit_code.sh`.
**Status.** Fixed on audit branch.

---

## D. Statistics and cohort

### Q14. Are the samples independent, and is the cohort large enough to rank tools?
**Answer.** Resampling is by cluster (bioproject, falling back to `source_study`;
`aggregate_results.py:55-97`), and an interval or test is withheld with fewer than 5
independent clusters (`aggregate_results.py:506, 522`). Counts computed from the cohort files:

| Cohort | Samples | Bioprojects | Largest bioproject | Blank `source_study` |
|---|---|---|---|---|
| `public-v1` | 10 | 4 | 7 samples (PRJNA636382) | 0 |
| `public-v2` | 32 | 15 | 7 samples (PRJNA636382) | 22 |

`public-v1`: 9 *E. coli*, 1 *Salmonella*. `public-v2`: 17 *E. coli*, 5 *K. pneumoniae*,
6 *Salmonella*, 3 *A. baumannii*, 1 *S. aureus*.
**Reading.** With `public-v1`, 4 clusters is below the 5-cluster minimum, so no
confidence interval is reported. `public-v2` clears it, but 17 of 32 are *E. coli* and one project
supplies 7 samples, so species-level claims beyond *E. coli* are not supported.
**Status.** Verified (counts). A formal power calculation (the smallest F1 difference this
cohort can detect) has **not** been done: **Open**.

### Q15. How is multiple testing handled?
**Answer.** Sign-flip permutation tests with Holm correction, applied per analysis track
(not across every comparison in the run; the docs previously said otherwise and were corrected).
**Evidence.** `docs/METHODS.md`; `test/test_leaderboard_significance.py`.
**Status.** Documented and corrected on audit branch.

### Q16. Can tools be tuned to, or trained on, the truth genomes?
**Answer.** Possibly: most database-based tools ship databases built from the same public
plasmids that serve as truth. `python/flag_database_overlap.py` compares truth release date
with each tool's database release date. `config/tool_database_releases.tsv` now has dates for the databases that are
installed or pinned (8 of its 19 rows); the rest, for tools whose databases are not installed here, are still blank
and are reported as `unknown` rather than guessed. A sequence-level screen now exists as well:
`python/database_containment.py` aligns each truth plasmid to a tool's own database FASTA (MOB-suite's is found
automatically; others via `TOOL_DATABASE_FASTAS`) and the leaderboard splits recovery into plasmids inside and outside
that database.
**Evidence.** The registry file itself; `test/test_leakage_visibility.py` (the report says "not assessed" instead of
showing "0"); `test/test_metric_rubric.py` and `test/test_stage_contig_metrics.sh` for the containment split.
**Status.** Date screen: done for installed databases, **Open** for the rest (the dates come from each tool's
maintainers, and inventing them would be worse than leaving them blank). Sequence screen: done where a database FASTA is
on disk; a tool whose database is not installed is not checked.

---

## E. Stratification, AMR and structure

### Q17. Can recovery be broken down by plasmid type, size and resistance-gene carriage?
**Answer.** Yes: `python/stratify_recovery.py` joins per-plasmid recovery to the `replicon` and
`mob` labels, to a size band (<10 kb, 10-50 kb, >50 kb) and to resistance-gene carriage, and writes
`benchmark.recovery_by_replicon.tsv`, shown in the report's "Recovery by plasmid type" section. Each
group reports the mean and the **median with interquartile range**, because per-plasmid recovery is
heavy-tailed. Rules, all tested:
- size needs no annotation, so it is always available;
- ARG carriage comes from the curated `truth_amr.tsv` when present (authoritative: a plasmid absent from
  it carries no resistance gene), otherwise from annotation callers; `no_arg_detected` is only claimed when an
  AMR caller reported ok in `annotation_provenance.json`, never from an empty table;
- a plasmid with no label is `untyped`; a sample with no annotation file is skipped, not called untyped;
- groups with fewer than 5 plasmids are flagged `underpowered` (5 is a convention, not a derived threshold);
- a plasmid with **several** replicons counts once in **each** group, so group sizes can sum to more than the number of plasmids (now pinned by `test/test_stratify_multilabel.py`).
**Evidence.** `test/test_stratify_recovery.py`, `test/test_stratify_multilabel.py`, `test/test_demo_end_to_end.py`
(the offline demo populates every group type and the HTML section).
**Status.** Fixed here (multi-replicon behaviour was unstated and untested; size, ARG and median/IQR are new). It is
descriptive only: it never ranks tools.

### Q18. Is AMR gene recall meaningful?
**Answer.** Only against independent truth. `python/derive_amr_truth.py` can draft AMR truth from
AMRFinderPlus calls on the *reference* (not on predictions, so it is not circular for the
prediction), with database name and version recorded and `evidence_tier = auto_derived`. It refuses to
write `truth_amr.tsv`; a person must review and promote it. It is reachable as `plasbench derive-amr-truth` and,
opt-in, from stage 2 (`DERIVE_AMR_TRUTH_DRAFT=1` writes `data/<sample>/truth_amr.draft.tsv`; default off).
**Evidence.** `test/test_derive_amr_truth.py`, `test/test_amr_truth.py`, `test/test_script_wiring.py`.
**Status.** Verified. AMR recall is still blank on any cohort without curated truth. A tool
that uses the same database as the truth caller would still be favoured; that is stated, not removed.

### Q19. Does the benchmark see structural errors (splits, merges, rearrangements)?
**Answer.** Base-level F1 does not. Separate layers do: bin split/merge metrics, alignment-derived
structural calls (`python/call_structural_variants.py`, deliberately `validated: false`), and optional
QUAST diagnostics (`RUN_QUAST_DIAGNOSTICS`, off by default), now shown in the HTML report.
None affect the ranking.
**Evidence.** `test/test_report_replicon_quast.py`, `test/test_run_quast_diagnostics.py`.
**Status.** Verified as diagnostics. A structural metric that feeds the ranking is **Open** by design.

---

## F. Reproducibility and engineering

### Q20. Can someone reproduce a run?
**Answer.** A run manifest records inputs, versions and hashes (`python/write_manifest.py`); cohort
lock files carry SHA-256; the scorer is standard-library only.
**Gap found.** Database release dates are still blank for tools whose databases are not installed (Q16), and tool databases live inside conda environments.
**Status.** Partly verified; database provenance is Open for those tools.

### Q20b. Is every script, input and output actually reachable?
**Answer.** `test/test_script_wiring.py` fails if any `python/*.py` script is referenced by no stage script, CLI
command, adapter or module, except three documented one-offs: `compare_scoring_methods.py` (a hand-run BLASTN
cross-check), `audit_three_class_scoring.py` (its helper) and `parse_teixeira2025_supplement.py` (a one-time cohort
migration). It also drives `derive-amr-truth` and `audit-truth-labels` through the real CLI, checks that stage 6 passes
every input the report accepts, and that `plasbench analysis --list` reaches the standalone scripts
(`stratify-recovery`, `rank-sensitivity`, `flag-database-overlap`, `flag-cohort-outliers`, `validate-truth-table`,
`call-structural-variants`, `run-quast-diagnostics`, `compare-scoring`, `audit-three-class-scoring`).
`test/test_demo_end_to_end.py` runs the offline demo and asserts each layer reaches its table and its HTML section.
**Status.** Fixed here. Before this, `derive_amr_truth.py` was reachable only from tests.

### Q21. Is the per-plasmid side file safe against stale results?
**Answer.** It is rewritten on each scoring run, but a tool removed from a later run leaves its old
`*.per_plasmid.tsv` behind, and the stratifier globs the results directory. `scores.tsv` has the same
property. This is a known limitation of the results-directory design, not yet fixed.
**Status.** Open (low severity): clear `results/` between runs that change the tool set.

### Q22. Has any of this been run on real data?
**Answer.** No. `results/` is empty in this checkout and `data/` holds only `db/`. The demo
results (`results_demo/`, `results_audit/`) come from synthetic tools. Every claim about ranking
stability, leakage or per-species performance is therefore unsupported until a `public-v2` run exists.
**Status.** **Open.** This is the largest gap, and it needs compute and data, not code.

### Q23. Is CI actually checking anything?
**Answer.** It now does. The `test` job used to fail at the shellcheck install step, so no tests ran; the apt-based install and a
warnings-only shellcheck gate landed on `main` in #8, and this change adds a `minimap2` install so the real-aligner golden test runs
instead of skipping. CI passed on #8 and #9, including the container job.
**Status.** Fixed (on `main`); the new `minimap2` step is confirmed only when this change's own CI run finishes.

### Q24. Does the full test suite pass?
**Answer.** Yes, on the final state of this change: a clean Linux (WSL, Ubuntu) export of the branch, rebased on `main` at the time,
ran `test/run_tests.sh` to completion, exit code 0, "ALL PLASBENCH TESTS PASSED", with real minimap2 2.26 installed so
`test_scoring_real_minimap2.py` and `test_stage_dimensions.sh` ran against the real aligner. Two environment notes: on Windows Git
Bash the suite stops at `test_update_script.sh` (no symlinks), and a checkout with CRLF line endings breaks the shell tests on Linux;
use a Linux checkout or CI for a full run.
**Status.** Verified for that run. It does not say anything about real data (Q22).

---

## G. Adjacent questions (outside the current scope)

| Question | Class | Note |
|---|---|---|
| Could the benchmark extend to metagenomic assemblies? | Partly done | A separate metagenomic bin-scoring track exists (`docs/METAGENOMICS.md`). |
| Could near-identical isolates be screened out of the cohort? | Adjacent opportunity | Redundant samples inflate the apparent sample count; the clonal-group analysis already groups them for the statistics. |
| Outbreak or surveillance inference | Outside scope | PlasBench evaluates reconstruction, not epidemiology. |
| Phage-plasmids, virulence plasmids, host range | Outside scope | Not evaluated. |

---

## Part 2. The reviewer question bank, section by section

A 500-question examination bank (31 sections, grouped into Parts I-XVII, plus five foundational questions
and a tracking template) was put to PlasBench. Some of its questions assume a tool that identifies the plasmids
in a sample. PlasBench is a **benchmark of plasmid reconstruction and classification tools**
([Scientific Guide section 1.3](docs/SCIENTIFIC_GUIDE.md#13-what-it-is-not)), so each answer below says
whether the question applies, answers it where it does, and says plainly where it does not. Question numbers
refer to the bank. For depth, follow the Scientific Guide link; for the 108-question companion, see
[docs/FAQ_QUESTION_BANK.md](docs/FAQ_QUESTION_BANK.md). Bank sections 11-13 and 27 (Q155-203 and Q417-430) ask
about functions outside the benchmarking pipeline and are not answered here.

| Status | Meaning |
|---|---|
| **Answered** | The answer is in the code, a test or the Guide, cited. |
| **Implemented here** | The review exposed a gap and it was closed in this change, with a test. |
| **Out of scope** | The question concerns a function PlasBench does not have and does not claim. |
| **Open** | Not done. The reason is given: usually it needs data or compute, not code. |

### The five foundational questions

1. **What exactly is the tool?** A benchmark: it scores how well *other* tools reconstruct or classify plasmids, against a
   complete reference. It is not a caller, a classifier or a comparison tool. **Answered** (Guide 1.1, 1.3).
2. **What is the central innovation?** Not an algorithm. The contribution is the evaluation design: shared-sample ranking with
   failures scored as zero, cluster-aware intervals, reference tiers, evidence-checked truth labels, plasmid- and bin-level
   metrics next to base-level ones, leakage and robustness diagnostics. Independent evidence of novelty against other
   benchmarks has not been assembled: **Open** (needs a literature comparison, not code).
3. **What is biological truth?** A complete assembly, tiered by how independent it is of the benchmarked reads, with plasmid and
   chromosome labels confirmed by replicon markers, rRNA genes and long-read support; conflicting replicons are set aside.
   Reference errors remain possible and are stated as a limit. **Answered** (Guide 4.2-4.5, 9); a read-depth check of each
   truth replicon exists for long-read-supported truth (`python/long_read_support.py`).
4. **What is the endpoint?** Per task and track: length-weighted binning F1 for binning-capable tools, base-level F1 for
   classifiers, CPRR as secondary; detection, binning, accuracy, structure and features are reported as separate dimensions
   and never folded into the headline. **Answered** (Guide 8.1-8.2; README "Metric framework").
5. **What may it claim?** Computational recovery of a known reference by a tool. It does **not** claim transmission,
   outbreak or horizontal-gene-transfer inference, and its outputs are not diagnostic. **Answered** (Guide 1.3, 13.5, 18).

### Part I. Research problem and novelty (Q1-28)

**1. Research problem and objectives (Q1-15).** The problem is choosing between plasmid tools with evidence rather than anecdote.
The unit of analysis is the reference base, the plasmid, the bin and the isolate, scored at all four. A reconstructed plasmid is
a bin of contigs that stands for one reference plasmid; an identified plasmid is a single call about a contig. The endpoint and
what counts as success are pre-specified (Guide 8.2). The boundaries are in the scope matrix (Guide 18). **Answered.**

**2. Novelty and contribution (Q16-28).** See foundational question 2. PlasBench does not claim a better plasmid caller;
MOB-suite, Platon, plasmidSPAdes, geNomad and the others are the *subjects* of the benchmark, not rivals to it. If no tool
beat another, the benchmark would still be useful for the failure analysis it produces. **Answered**, with the literature
comparison **Open**.

### Part II. Plasmid biology (Q29-58)

**3. Plasmid identity and classification (Q29-44).** A truth sequence is a plasmid if the submitter's record says so and the
evidence labels do not contradict it (replicon markers, absence of rRNA, long-read support). A sequence with conflicting
evidence (chromid, integrated plasmid, marker-free or short-read-only plasmid) is `AMBIGUOUS` and excluded from scoring
(`python/label_truth_evidence.py`; Guide 4.3-4.5). A plasmid with several replicons counts under each in the stratified table
(Q17). Linear plasmids
and circular topology: circularity is read from a curated list when supplied and is never inferred (Guide 7.4).
**Answered.**

**4. Plasmid structure (Q45-58).** What exists: alignment-derived structural calls (inversions, relocations,
duplications, with `validated: false`), bin split and merge events, insertion-sequence landmarks from the reference annotation,
repeat-ambiguity and recall-ceiling diagnostics, and, **implemented here**, **NGOC** (gene-order conservation, strand and
circularity aware) and a missing-region count (`feature_preservation.py`, `alignment_accuracy.py`).

### Part III. Sequencing, assembly and reconstruction (Q59-110)

**5. Inputs (Q59-73).** Each tool declares its input in `config/tool_capabilities.tsv`: assembly, assembly graph, paired
reads, long reads or hybrid reads, ranked in separate tracks (Guide 4.1, 6). Short reads are the default; long-read and hybrid
benchmarking is opt-in behind a circularity guard. Depth and read-quality ladders vary the data deliberately. Contaminated
reads leave unmapped output, which is reported, not scored as a false positive. Mixed populations belong to the separate
metagenomic track (Guide 11). Unsuitable input is caught before analysis by `validate_truth_table.py`, `validate_cohort.py`
and `validate_local_inputs.py`. **Answered.**

**6. Assembly and reconstruction methods (Q74-92).** These are the **tools'** methods, not PlasBench's; PlasBench runs them
(Guide 6) and scores their output. The default assembler is SPAdes and results depend on it (Guide 17.4). Evidence for a
tool's contig assignment, its repeat resolution and its circularity call are the tool's to supply; PlasBench measures the
outcome (bin purity, split and merge events, complete circular recall against curated circular truth). A confidence score
exists only for tools that emit per-record probabilities: PR-AUC, and their calibration (Brier score, expected
calibration error, reliability diagram: `<tool>.calibration.tsv`). **Answered.**

**7. Reference assembly and ground truth (Q93-110).** Truth is tiered 1 to 3 by independence from the benchmark
(`python/truth_provenance.py`): long-read-first truth is preferred; short-read-first or unknown-provenance truth (tier 3) leaves
the headline and becomes a sensitivity analysis. Truth polished with the **same Illumina reads the tools are benchmarked on**
is acceptable for plasmid-versus-chromosome labels but **not** for base-level accuracy, because the truth would carry the
reads' own errors: the CPRR identity criterion is dropped there, and, **implemented here**, the nucleotide-accuracy rates are
blanked and marked not assessable (`python/mask_accuracy.py`; test `test_mask_accuracy.py`). Plasmid size alone no longer
labels self-built truth. A sample has one reference; conflicting references and reference errors are stated limits (Guide
17.4), and an independent audit of references is **Open**. **Answered.**

### Part IV. Detection and binning (Q111-136)

**8. Plasmid detection (Q111-120).** Detection is a tool's task. PlasBench reports each tool's base-level precision and
recall, chromosome bases wrongly claimed, plasmid bases missed and per-plasmid recovery, so false-positive and
false-negative behaviour is measured per tool and per isolate. Performance on plasmids absent from a tool's own database is
the leakage question: a date-based screen (dates filled for installed databases, `unknown` otherwise) and a
sequence-level check of each truth plasmid against the tool's own database FASTA, with recovery reported inside versus
outside it. A tool whose database is not installed is not checked: **Open** for those tools.

**9. Binning (Q121-136).** Binning is part of the primary reconstruction endpoint for binning-capable tools: the length-weighted
binning F1 from an ungated one-to-one Hungarian match, with CPRR per plasmid (Guide 7.5, 8.2). Conventional clustering
statistics (NMI, variation of information) are descriptive only, and, **implemented here**, homogeneity, completeness and
V-measure are reported beside them, base-pair weighted and clearly secondary. Contigs shared between similar plasmids and
contigs mixing plasmid and chromosome are visible as ambiguity and contamination. PlasEval is accepted as an imported
cross-check, not run: a first-class adapter is **Open** (it needs the external tool and real data to validate). Repeat-aware
*matching* is not implemented; repeat effects are reported as diagnostics. **Answered / Open.**

### Part V. Sequence similarity (Q137-154)

**10. Sequence similarity (Q137-154).** PlasBench compares a *prediction with its own truth* by local alignment (minimap2,
`asm5`, primary alignments only), merging aligned blocks on the reference. Coverage and identity are reported separately:
recall is coverage, and, **implemented here**, identity, mismatch, insertion and deletion rates come from the alignments'
CIGAR. Circular rotation and strand are handled by construction (blocks are merged on the reference, so a different origin or
the opposite strand costs nothing). A score measures agreement between a prediction and its own truth; it has no wider biological
interpretation. PlasBench's own thresholds (identity 0.90, MAPQ 20, minimum length 200, query coverage 0.20) are scoring
choices, not biological ones; the ranking-robustness table re-ranks under changed choices (`python/rank_sensitivity.py`).

### Part VII. AMR and function (Q204-232)

**14. Antimicrobial resistance (Q204-220).** Truth AMR genes come from a *curated* table; an auto-derived draft from
AMRFinderPlus on the reference can be produced but is never scored until a person promotes it (`plasbench derive-amr-truth`).
AMR gene recall counts a gene recovered at a configurable coverage threshold (default 0.90). Whether a tool keeps the AMR
genes on the right plasmid is visible per plasmid, and recovery is broken down by resistance-gene carriage
(`stratify_recovery.py`). Co-resistance, integron and transposon context, clinical gene classes (ESBL, carbapenemase, colistin)
and claims of plasmid-mediated dissemination are **not** analysed or claimed; per-class yield is a stated expansion
(README roadmap). **Answered / out of scope.**

**15. Functional annotation (Q221-232).** The reference is annotated by installed callers (MOB-typer, abricate replicon and
AMR, AMRFinderPlus, ISEScan, barrnap); a missing caller is recorded as *not evaluated*, never as absent. **Implemented here:**
feature preservation: each truth feature (replicon, mobility, AMR, insertion sequence, gene) is projected through the
alignments and called *full length*, *truncated* or *missed*, so a truncated gene is not counted as recovered
(`python/feature_preservation.py`). Virulence determinants, toxin-antitoxin systems and annotation-uncertainty modelling are
not covered. **Answered / Implemented here.**

### Part VIII. Databases (Q233-249)

**16. Databases and reference resources.** PlasBench has no reference database of its own for scoring; truth is the
sample's complete assembly. Tool databases are recorded in `config/tool_database_releases.tsv`: release dates are filled
for the installed or pinned databases and blank for the rest, which are then reported as not assessed, and
`database_containment.py` checks truth plasmids against any database FASTA on disk. Cohorts are staged locally, so a run can proceed offline once databases are installed; tool and
cohort versions go into the run manifest, and cohort lock files pin SHA-256 checksums. Taxonomic and geographic bias of public
records is a stated limit (Guide 4.7, 17.2). **Answered for installed databases; Open for the others.**

### Part IX. Benchmark design and statistics (Q250-321)

**17. Benchmark study design (Q250-265).** Detection (classification) and reconstruction are separate tasks within separate
input tracks and are never pooled (Guide 8.1). Failed runs and empty predictions on plasmid-bearing isolates score zero; skipped
runs are not failures; timeouts and out-of-memory kills are classed as resource failures (`--resource-failures`). Incomplete
reconstructions stay in the denominator. Multiple plasmids per isolate are scored per base, per plasmid and per bin. Tools run
at their defaults with identical inputs; tuning is not part of the benchmark. Blinding does not apply. Repeated runs: **implemented
here**, `python/compare_runs.py` reports reproducible, score-stable or variable per tool from two or more result directories
(it needs the repeated runs to exist). **Answered / Implemented here.**

**18. Cohort and diversity (Q266-281).** `public-v1` has 10 isolates from 4 BioProjects (9 *E. coli*); `public-v2` has 32 from
15 (17 *E. coli*, 5 *Klebsiella*, 6 *Salmonella*, 3 *Acinetobacter*, 1 *Staphylococcus*), one BioProject supplying 7 samples
(counts computed from `cohorts/*.tsv`). The species-balanced headline needs 20 independent clusters per species, so most
species fall back with the reason recorded. A broader, more balanced cohort, and plasmid-free and hard-structure isolates, are
**Open** (data curation). **Implemented here:** isolates are tagged simple, complex, annotated, challenging or plasmid-free from
facts on disk, and performance is reported per scenario, so a tool cannot look better because it met easier isolates
(`python/scenario_tags.py`).

**19. Metrics and scoring (Q282-304).** The five-dimension scorecard in the bank maps onto PlasBench as follows. **Accuracy:**
identity, mismatch, insertion and deletion rates (implemented here; not assessable where truth is not independent).
**Completeness:** reference coverage, missing bases and regions, per-plasmid completeness, plasmid recovery, CPRR.
**Structure:** bin split and merge, circular recall, NGOC (implemented here), proxy structural calls. **Biology:** feature
preservation and AMR recall (implemented here). **Performance:** runtime, memory, success rate, resource failures, cost per
recovered plasmid, CPU utilisation, scaling (implemented here, `python/performance_summary.py`). Failed runs score zero. The
proposed weighted composite is implemented **as an optional, descriptive view** (`python/composite_score.py`): weights are a
file (`config/composite_weights.tsv`, default 30/20/25/15/10, described as a proposal), a dimension is used only if every tool
has it, a tool below the accuracy or completeness gate is shown but not ranked, and a weight-sensitivity table (each dimension
left out, and 500 random reweightings) shows whether the ranking survives. It is not the headline, because arbitrary weights
trade one dimension against another; raw values and dimension scores always appear beside it. **Implemented here.**

**20. Statistics (Q305-321).** Resampling and permutation are by cluster (BioProject, then study); paired sign-flip permutation
tests are Holm-adjusted per track; a minimum of 5 independent clusters is required before an interval is reported; every
random step is seeded (Guide 8.4-8.5). Outlier isolates are flagged, not dropped. Missing results are reported, never
imputed. **Implemented here:** a power analysis gives the minimum detectable difference and the clusters needed per tool pair
(`python/power_analysis.py`), so "tool A beats tool B" can be checked against what the cohort can detect. An independent external
validation cohort is **Open**; a simulation that checks the nominal coverage of the intervals is **Open**.

### Part X. Comparators (Q322-338)

**21. Comparison with existing tools.** The tools in the registry are the benchmark's *subjects* (mob_recon, Platon,
plasmidSPAdes, gplas2, geNomad, PLASMe, RFPlasmid, PlasmidHunter, Plasmer, plasGraph2, PlaScope, Flye+MOB-recon, Trycycler,
Hybracter, Plassembler; Guide 6). PlasmidFinder and MOB-typer are used to *annotate truth*, not benchmarked as reconstructors.
Two trivial baselines are scored like tools (`baseline_coverage`, a depth rule, and
`baseline_reference`, a match to a plasmid reference set), and each tool reports whether it beats them
(`beats_best_baseline`). **Answered.**

### Part XI. Software engineering (Q339-368)

**22. Architecture (Q339-354).** Numbered, idempotent stage scripts that reuse completed work; one adapter contract per tool;
run manifest with tool and cohort versions; per-run logs and a failure table; parallel samples (`MAX_PARALLEL_SAMPLES`);
container and conda routes; output validation (the truth, cohort and local-input validators). It is Bash-orchestrated and
Linux-first (Windows needs WSL2), a stated adoption limit. Data security: it runs locally and uploads nothing; keep NCBI keys
out of synced folders. **Answered.**

**23. Performance and scalability (Q355-368).** **Implemented here:** per-tool runtime, memory, success rate, cost per recovered
plasmid, CPU utilisation (recorded beside peak memory in stage 4) and a log-log scaling exponent against reference size, shown
only with enough samples across a real size range. No published figures exist yet (no real-data run), so claims about maximum
dataset size or average time are **Open** until one is run. Interrupted runs resume at the stage level.

### Part XII. Outputs and applications (Q369-398)

**24. Outputs and visualisation (Q369-384).** The HTML report has sections for the leaderboard, statistics, bin diagnostics,
recovery by plasmid type, QUAST diagnostics, ranking robustness, truth-label audit, performance by stratum, orthogonal
evidence and, **new**, accuracy, feature preservation, bin quality, performance, power, scenarios, the optional composite and
reproducibility; every table can be downloaded as TSV, and each section says what it does and does not show. Alignment blocks
are explorable per sample; selected candidates are copied out. Uncertain or unassessable values are blank or labelled
(`not_evaluated`, `underpowered`, `unknown`), never zero.
**Answered.**

**25. Laboratory and public-health use (Q385-398).** PlasBench informs which tool to adopt, with an interval, and how each tool
fails (Guide 1.4). It is research software, not a diagnostic; it produces no epidemiological output, and similarity, a shared
resistance gene or replicon is not evidence of transmission (Guide 1.3, 13.5). Cross-hospital comparison, longitudinal
surveillance and interspecies-transfer investigation are **out of scope**. A per-sample table of missing consequential
metadata (`benchmark.metadata_completeness.tsv`) is written and shown in the report.

### Part XIII. Failure modes (Q399-416)

**26. Edge cases.** The behaviour table is in Guide 17.5 (multiple and near-identical plasmids, very large and very small
plasmids, divergent and fragmented plasmids, insertion-sequence-rich plasmids, integration and chromids, contaminated reads,
missing databases, out-of-memory). The scorer is exercised by control predictions with analytically known scores (oracle, empty,
whole genome, chromosome-only, half, plasmid-free) in `test_scoring_controls.py`, and by the real aligner in
`test_scoring_real_minimap2.py`. When PlasBench cannot answer it says so rather than forcing a value: `not_evaluated`,
`not_assessed`, `underpowered`, `unknown`, `no_close_reference`. **Answered.**

### Part XV. Reproducibility and governance (Q431-455)

**28. Reproducibility (Q431-445).** The run manifest records parameters, tool and cohort versions and image digests; cohort lock
files carry SHA-256 checksums; the scorer is standard-library only; bootstrap and permutation steps are seeded; logs and
`score_failures.tsv` give an audit trail; benchmarking scripts and cohorts are in the repository. Positive controls (oracle
predictions) and negative controls (empty and chromosome-only predictions) are tests; plasmid-free isolates are supported but
none ship in the cohorts (**Open**, data). **Implemented here:** `compare_runs.py` for repeated-run reproducibility.
Software updates are validated by the offline suite, the demo and the container build in CI.

**29. Ethics, governance and responsible use (Q446-455).** The shipped cohorts use public accession data; governance and
release rules are in [docs/GOVERNANCE.md](docs/GOVERNANCE.md) and [docs/COHORTS.md](docs/COHORTS.md). Software is GPL-3.0.
PlasBench runs locally and keeps nothing centrally, so deletion and retention are the user's. Its outputs are computational
candidates and must not be used to draw clinical or public-health conclusions without confirmation. Sensitive institutional
datasets are the user's to handle; no data-sharing agreement is built in. **Answered**, with licence and consent questions for a
specific institutional dataset **Open** by nature.

### Part XVI. Publication and funding (Q456-484)

**30. Journal reviewer questions (Q456-470).** The most likely rejections: no real-data results yet; truth is an assembly;
cohort small and taxonomically narrow; no independent validation of intervals or against an independent scorer. These are the
open items below. Code is accessible; reproducibility is addressed above. A resource or benchmark paper is the defensible fit.

**31. Funder and innovation questions (Q471-484).** The gap addressed is evidence-based tool choice for plasmid reconstruction,
including in under-sampled regions; the minimum useful version is the default-tool, short-read benchmark on a diverse cohort.
Risks: no real-data run, single-maintainer sustainability, a very large documentation and feature surface. The project concept
note is in [docs/CONCEPT_NOTE.md](docs/CONCEPT_NOTE.md). What would justify further investment: a published real-data run with
intervals, filled database dates, an independent truth audit and an external cohort.

### Part XVII. Additional research opportunities (Q485-500)

| Opportunity | Class | Where it stands |
|---|---|---|
| Clinical versus environmental plasmids; One Health; host associations (485-487) | Adjacent | Needs cohorts, not code; metadata columns exist. |
| Persistence, emerging resistance patterns, change over time (488-489, 493) | Adjacent | No temporal evaluation; needs dated cohorts. |
| Metagenomic plasmid analysis (490) | Partly done | Separate bin-scoring track exists (Guide 11). |
| Virulence, phage-plasmid interaction (491-492) | Out of scope | Not evaluated. |
| National surveillance integration, automated reporting, collaborative surveillance (495-497) | Adjacent | The run manifest and TSV outputs are the integration surface; no connectors exist. |
| Other mobile genetic elements (498) | Adjacent | Feature preservation is feature-kind generic, so insertion sequences are already covered as features. |
| Discoveries from the resulting dataset (500) | Adjacent | Depends on the real-data run. |

### Part XIX. Review tracking

Every bank section is tracked in [docs/REVIEW_TRACKER.tsv](docs/REVIEW_TRACKER.tsv) with the fields the bank asks for (domain,
expert perspective, rationale, evidence, limitation, action, priority, status). A question is marked *Validated* only where a
test or computed number supports it; otherwise *Answered*, *Unresolved* or *Out of scope*.

## What is still open (summary)

Closed in software (each with a test): contig-level classification, ARI and assembly-aware binning recall, micro versus macro averages, a sequence-level database check, probability calibration, trivial baselines, nucleotide-level accuracy (not assessable where truth is not independent),
missing regions, feature preservation and NGOC, bin quality tiers and homogeneity/completeness, performance and scaling,
power analysis, scenario tags, an optional gated composite with weight sensitivity, and a repeated-run comparison.

Still open, and why:

1. **No real-data run** (Q22): needs compute and data. Everything about ranking stability and generalisation depends on it.
2. **Database release dates and database FASTAs for tools whose databases are not installed** (Q16): the dates come from each
   tool's maintainers; the sequence-level screen needs the database on disk.
3. **Independent audit of references, and read support for every truth replicon** (Q3, Q4): needs reads and curation.
4. **External validation cohort and a coverage simulation for the intervals** (Q14).
5. **Plasmid-free, hard-structure and taxonomically broader isolates** in the released cohorts (Q12, Part 2 section 18): data curation.
6. **A first-class PlasEval adapter** (Part 2 section 9): needs the external tool and real data to validate.
7. **Abstention rate, NGA50 and AMI**: no wrapped tool reports an explicit "unclassified" call, NGA50 needs contig-level
   misassembly breaks, and AMI's expected-information term is impractical over base counts. Contig-level classification
   (count-based and length-weighted precision, recall, F1 and MCC) is done; ambiguous contigs are excluded, not multi-assigned.
8. **A literature comparison establishing novelty** (Part 2 section 2).
9. **Stale per-tool result files** when the tool set changes between runs (Q21): clear `results/` between such runs.
