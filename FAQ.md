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
| **Fixed on audit branch** | Fixed and tested on `tmp/audit-all` / `fix/audit-followthrough` (see `REVIEW.md`, "Remediation status"). Confirm it is on `main` before relying on it. |
| **Documented** | Stated in the docs, not enforced or tested by code. |
| **Open** | Not done. The reason is given (usually: it needs real data, not code). |

A companion file, [docs/FAQ_QUESTION_BANK.md](docs/FAQ_QUESTION_BANK.md), answers the longer reviewer question bank and
cross-references the question numbers here.

Evidence basis: `REVIEW.md` (independent review and audit), the source files named in
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
**not** a plasmid identification, PLSDB-search, clustering, subcommunity or relatedness
tool.
**Evidence.** README "How scoring works (at a glance)"; `REVIEW.md` Part 1 ("What it is not").
**Status.** Verified. The scope statement is in the docs; there is no code for the
relatedness ambitions, and none is implied.

### Q2. Why not use Pling or a community/relatedness tool for scoring?
**Answer.** Scoring compares a prediction with a truth genome of the same isolate. Pling
compares plasmids with each other, needs complete plasmids and gives community-level
results that this cohort size cannot support. It could help *cohort QC* (spotting
near-identical plasmids that inflate apparent sample count), which is a different job.
**Evidence.** My description of Pling is from memory and was not checked against its
documentation; verify before citing it.
**Status.** Open as an idea (cohort redundancy screening); not needed for scoring.

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
**Evidence.** `test/test_redundant_coverage.py`; `REVIEW.md` §5.2.
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
**Evidence.** `docs/METHODS.md`; `REVIEW.md` finding D7; `test/test_leaderboard_significance.py`.
**Status.** Documented and corrected on audit branch.

### Q16. Can tools be tuned to, or trained on, the truth genomes?
**Answer.** Possibly: most database-based tools ship databases built from the same public
plasmids that serve as truth. `python/flag_database_overlap.py` compares truth release date
with each tool's database release date, but `config/tool_database_releases.tsv` has
**15 rows marked `uses_reference_database = yes` and 0 filled dates**, so every pair is currently `unknown`.
**Evidence.** The registry file itself; `test/test_leakage_visibility.py` pins that the
report now says so (stderr, Markdown warning, `n_unknown_overlap`) instead of showing "0".
**Status.** Visibility fixed on audit branch. The dates themselves are **Open**: they come from
each tool's maintainers, and inventing them would be worse than leaving them blank. A
sequence-level overlap screen is also Open.

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
**Gap found.** The database release dates are blank (Q16) and tool databases live inside conda environments.
**Status.** Partly verified; database provenance is Open.

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
**Answer.** The `test` job previously failed at the shellcheck install step, so no tests ran, and `main`
was already red. The apt-based shellcheck install is commit `5d9e28d` (audit branch, not yet on `main`).
This change also installs minimap2 so the golden test runs.
**Status.** Fixed on audit branch plus here; not confirmed until a pushed run goes green.

### Q24. Does the full test suite pass?
**Answer.** Not yet confirmed end to end. What was actually run on this change:
- `test/run_tests.sh` under Git Bash on Windows: every test passed up to
  `test_update_script.sh`, which needs symlinks that Git Bash on Windows does not provide
  (it passes when run alone under Linux/WSL). The script stops at the first failure, so
  the tests after it did not run there.
- `test/run_tests.sh` under WSL against the Windows checkout: stopped at
  `test_operational_reconstruct.sh`, whose CRLF line endings (from `autocrlf=true`)
  break `set -o pipefail` on Linux.
- The three new tests, `test_audit_truth_labels.py`, `test_scoring_controls.py` and
  `test_stratify_multilabel.py`, pass; `test_scoring_real_minimap2.py` passes against real
  minimap2 2.26 in WSL.
A clean LF checkout on Linux is the right place for a full run; CI provides it.
**Status.** Open until CI (or a Linux run) goes green.

---

## G. Adjacent questions (outside the current scope)

| Question | Class | Note |
|---|---|---|
| Could the benchmark extend to metagenomic assemblies? | Partly done | A separate metagenomic bin-scoring track exists (`docs/METAGENOMICS.md`). |
| Could near-identical plasmids be screened out of the cohort? | Adjacent opportunity | The Pling-style redundancy idea in Q2. |
| Plasmid relatedness, PLSDB search, communities | Outside scope | Would be a separate project with its own validation (`REVIEW.md` Part 12, item 19). |
| Outbreak or surveillance inference | Outside scope | PlasBench evaluates reconstruction, not epidemiology. |
| Phage-plasmids, virulence plasmids, host range | Outside scope | Not evaluated. |

---

## What is still open (summary)

1. No real-data run (Q22). Everything about ranking stability and generalisation depends on it.
2. Database release dates (Q16) and a sequence-level leakage screen.
3. Read-depth support for truth replicons (Q3, Q4).
4. A power analysis for the cohort size (Q14).
5. Plasmid-free isolates in the shipped cohorts (Q12).
6. Stale per-tool result files (Q21).
7. The audit-branch fixes (Q5, Q9, Q13, Q15, Q16, Q23) must be merged to `main`.
