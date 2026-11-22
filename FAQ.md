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

The 215-question reviewer assessment is [docs/REVIEWER_ASSESSMENT_MATRIX.md](docs/REVIEWER_ASSESSMENT_MATRIX.md) (Q36-Q43). Everything implemented, with where to find it and what checks it, is in [docs/IMPLEMENTATION_CATALOGUE.md](docs/IMPLEMENTATION_CATALOGUE.md). A companion file, [docs/FAQ_QUESTION_BANK.md](docs/FAQ_QUESTION_BANK.md), answers the longer reviewer question bank and
cross-references the question numbers here.

Evidence basis: [docs/INDEPENDENT_REVIEW.md](docs/INDEPENDENT_REVIEW.md) (independent review and audit; every review and what validated it is
listed in [docs/EXTERNAL_REVIEW_LOG.md](docs/EXTERNAL_REVIEW_LOG.md)), the source files named in
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
**Answer.** Partly, and more than before. PlasEval (Mane et al., *BMC Bioinformatics* 2024) is a framework for comparing plasmid bin sets
that is aware of contig length and of repeats. PlasBench computes the same quantities itself, reimplemented from the published definitions
(no PlasEval code is used): best-match precision, recall and F1, and the normalised dissimilarity with its four parts (extra, missing,
splits and joins), including the paper's repeat-aware pairing of repeated contigs. `test/test_plaseval_crosscheck.py` runs both programs
on the same inputs. Run on Linux against the original program (`github.com/acme92/PlasEval`, commit 8238356) it agreed on best-match
P/R/F1 and on the normalised dissimilarity in all 59 cases, 44 of them with repeated contigs (hand-built and seeded random bin sets, and
PlasEval's own examples). It runs only when `PLASEVAL_SRC` points at a PlasEval checkout, so CI skips it. A PlasEval run can also be
imported as a labelled, non-ranking cross-check (`plasbench import-external-benchmark`), and a one-off script compares the minimap2 scoring
with a BLASTN scoring (`python/compare_scoring_methods.py`).
**Evidence.** `python/bin_agreement.py`; `test/test_plaseval_crosscheck.py`; `test/test_bin_agreement.py` (hand-computed repeat cases and a
capped search); `docs/METHODS.md`, "External evaluator cross-checks".
**Status.** Verified on constructed and random cases. The paper's 53 *E. coli* isolates ship as a cohort with the paper's published bins, and a
comparison gate (Q31) repeats the check against the original program on real bins wherever it is installed; **Result:** on the 53-isolate cohort 210 of 211 pairs agree within 0.001 and none disagree (Q31). **Open:** a first-class adapter that runs the original as the scorer. The dissimilarity is a secondary endpoint: it compares which contigs are in
which bin, says nothing about sequence accuracy, and does not apply to tools that output reassembled sequences.

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
None affect the ranking. The PlasEval-style dissimilarity (Q2) adds the split and join costs, and the extra and missing costs, per tool
and sample (`dissim_split_cost`, `dissim_join_cost`, `dissim_extra_cost`, `dissim_missing_cost`), so a binner that over-merges plasmids can
be told apart from one that over-fragments them even when their F1 is similar. The report draws all four parts as charts (an error profile by tool, a tool-by-part grid, precision against recall, F1 against agreement
with the truth, error composition per isolate, an isolate-by-tool grid and a tool-agreement matrix), beside the table of split and join costs.
**Evidence.** `test/test_report_replicon_quast.py`, `test/test_run_quast_diagnostics.py`, `test/test_bin_agreement.py`, `test/test_report_fig_binerrors.py`.
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

### Q20c. Can I add my own tool, one that does several tasks, or one I only have as a download or a folder?

Yes, with one manifest (`plasbench tools new`, [docs/ADDING_TOOLS.md](docs/ADDING_TOOLS.md)). `task = classification, binning_reconstruction`
declares a tool that does several: the command runs once per sample and the same output is converted for each task, so the tool
appears in each task's own leaderboard (labelled with the task) and is never ranked across tasks. A task is only offered when the
declared output can honestly produce it: bins give classification, labels give binning only as one flagged bin per plasmid contig,
and a plasmid FASTA gives sequence reassembly only; anything else is a validation error that says what to add. The tool can come
from conda, pip, an **https** URL (`method = url`, optionally pinned with a sha256; archives are extracted safely, nothing runs
at validation) or a file or folder on this computer (`method = local`, copied with a recorded checksum by default). `format = auto`
recognises the tool's output files by their content and fails loudly, listing what it saw, rather than guessing.

### Q20d. What does each optional step or tool add, and how do I see the whole chain?
**Answer.** On **Tools** and on **New benchmark** (step *Tools*), the **Workflow** view lays the run out as ordered steps (download, truth, assemble, tools, score, report, long-read tools, operational). Each tool or optional step has an On/Off switch, a one-line description, badges for what it needs (database, internet, an earlier step) and its added time, memory and disk per isolate; a bar at the top totals the selection and says *estimated*. Switching something that needs a disabled step offers to switch that on too. The figures are labelled: *measured* (real runs in `results_real_cohort1`: assembly, MOB-recon, Platon, plasmidSPAdes), *documented* (README or config.sh) or *not measured*, which is shown as such and left out of the total, never counted as zero. Off is plum with a cross and On is green with a tick; an item at its default shows its default state's colour and a *changed* tag marks what you altered.
**Status.** Implemented here (`plasbench/workflow_steps.py`, `config/workflow_steps.tsv`; `test/test_workflow_steps.py`, `test/test_workflow_ui.py`). Most optional analyses have no timing yet.

### Q20e. Where did the explanation text in the window go?
**Answer.** Into the small green **?** next to each label. Each page now shows a title, one line of purpose and the controls; what a control means, what its options do and how the page works open when you hover the **?**, move to it with the Tab key, or tap it on a phone, and close with Escape. Warnings, errors, offline or blocked reasons, disk-space notes and decisions you must make stay on the page. Nothing was deleted: the words moved to `plasbench/ui_help.py`, and the guides (**Guides** page, F1 for the page's own help) still hold the long form.
**Status.** Implemented (`plasbench/ui_help.py` `PAGE`, `test/test_ui_cleanup.py`, a word budget per page so the clutter cannot return).

### Q20f. How do I know an install is still running?
**Answer.** A card at the bottom right of every page says "Installing ..." with the time it has been running and the latest log line, for as long as any install, pull, build or update is going. **View log** opens the live log, **Cancel** stops it after you confirm, **Hide** folds it into an Installing chip in the top bar (click the chip to bring it back). It is drawn from the job list, so it is still there after a reload, in another window, and for an install started from the terminal. A step that waits for you (Docker Desktop), a missing consent, a manual step, a stall and a failure each say so and stay until you dismiss them; Done goes away by itself after about eight seconds.
**Status.** Implemented (`plasbench/jobs_labels.py`, the toast in `plasbench/data/ui.html`, `test/test_install_toast.py`).

### Q21. Is the per-plasmid side file safe against stale results?
**Answer.** It is rewritten on each scoring run, but a tool removed from a later run leaves its old
`*.per_plasmid.tsv` behind, and the stratifier globs the results directory. `scores.tsv` has the same
property. This is a known limitation of the results-directory design, not yet fixed.
**Status.** Open (low severity): clear `results/` between runs that change the tool set.

### Q22. Has any of this been run on real data?
**Answer.** Yes, on a small scale; a run large enough to rank tools is not yet published. `results_real_cohort1/` holds a real-data run made with PlasBench 0.2.3: 10 public
isolates (`arbank_0346`, `arbank_0349`, `tahini_salmonella` and seven `upec_ecpf` isolates), three real tools (MOB-recon, Platon, plasmidSPAdes) and a coverage baseline, 40 score
rows, with the run manifest recording the tool versions. It shows that the pipeline works on real reads. It cannot rank tools: its headline rests on one Tier-2 reference
(`docs/INDEPENDENT_VERIFICATION.md`), only the run-level tables were kept, not the per-isolate files (`docs/COHORT1_REBUILD_STATUS.md`), and it predates version 0.5. The maintainer has
also started runs on larger cohorts (`public-v4`); their results are not in this repository, so nothing here relies on them. The demo results (`results_demo/`, `results_audit/`)
come from synthetic tools. Claims about ranking stability, leakage or per-species performance stay unsupported until a run large enough to rank is published with its manifest.
**Evidence.** `results_real_cohort1/scores.tsv`, `results_real_cohort1/run_manifest.json`, `docs/COHORT1_REBUILD_STATUS.md`.
**Status.** **Partly done.** A small real run exists; the large, published one is the largest open item and needs compute and data, not code.

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

## H. Installing, upgrading and first launch (v0.4.1)

### Q25. The installer says "Could not resolve host". Is PlasBench broken?
**Answer.** No: this computer's DNS is not working, which is common in WSL2 and behind a VPN. `install_latest.sh` now says so and gives the
fixes (`wsl --shutdown` in PowerShell, turning a VPN off or on, or setting a DNS server by hand). With no internet in that terminal, download
`plasbench-<version>.tar.gz` and its `.sha256` from the Releases page on another computer, extract the archive and run
`bash plasbench-<version>/scripts/install_latest.sh --archive <path to the .tar.gz>`; the checksum beside the file is verified.
**Evidence.** `scripts/install_latest.sh`; `test/test_install_latest.sh` (a DNS failure is explained and leaves no install; `--archive` installs
offline; a tampered archive is refused).
**Status.** Fixed in v0.4.1. The first command in the README downloads the script from GitHub, so it still needs working DNS.

### Q26. `plasbench install-tools all` ended with "killed (SIGKILL)". Did the install fail?
**Answer.** One optional tool failed; the rest installed. The Trycycler environment (Trycycler, Flye and Medaka's PyTorch stack) is a very
large solve and the system kills it on a PC with little memory (exit 137). Since v0.4.1 the base profiles (core, assembly, mobsuite,
reconstruction) are required, every other tool that cannot install is listed with how to retry (`plasbench install-tools trycycler`), and the
command exits 0. A kill prints how to give WSL more memory (`memory=8GB` and `swap=8GB` in `C:\Users\<you>\.wslconfig`, then `wsl --shutdown`),
and a warning appears before the Trycycler solve when under about 8 GB is free. `env/install_tools.sh` is also executable in git now; its
`all` loop re-runs itself, which failed with "Permission denied" in a plain git checkout.
**Evidence.** `env/install_tools.sh`; `test/test_install_all_optional.sh`; `test/test_install_wiring.py`.
**Status.** Fixed in v0.4.1.

### Q27. Why did the desktop icon do nothing?
**Answer.** The launcher ran with `set -u`, and conda's own activation scripts (for gcc and others) read variables they never set, so the
shell exited with `SYS_SYSROOT: unbound variable` before the window started. The log is `~/.plasbench/ui/launcher.log`. `set -u` is now
relaxed only around the activation step. Every start creates a new session key, which the window reads from the link; the icon starts
`plasbench ui` exactly as typing it does.
**Evidence.** `scripts/plasbench_launcher.sh`; `test/test_desktop_window.py` (a fake conda whose activation reads an unset variable).
**Status.** Fixed in v0.4.1. To work around it on an older install: `sed -i 's/^activate_env || true$/set +u; activate_env || true; set -u/' ~/PlasBench/scripts/plasbench_launcher.sh`.

### Q28. The window says "This address needs the session key". And why did advertising sites open?
**Answer.** The page appears when the address is opened without the `?t=...` part: the key is new at every start, so an old tab or bookmark
stops working. Run `plasbench ui` again; if PlasBench is already running it prints the full link and reopens the window (the link is also in
`~/.plasbench/ui/server.json`). PlasBench's page loads nothing from the internet and the program opens one window, so advertising pages that
open alongside it come from the browser or the computer (an extension, a hijacked start page or adware), not from PlasBench. Since v0.4.1 the
window opens in its own browser profile with extensions, sync and notifications off, or in a private window when no separate profile can
be made, and never in the everyday profile. Check Edge or Chrome for extensions you do not recognise and run a Windows Security scan.
**Evidence.** `plasbench/appwindow.py` (`app_args`); `plasbench/webui.py`; `test/test_desktop_window.py`.
**Status.** Fixed in v0.4.1 as far as PlasBench controls it; the flags are tested, not exercised in a real browser.

### Q29. How do I upgrade, and can PlasBench tell me an update exists?
**Answer.** `plasbench upgrade` (or `./update.sh`) replaces the release files in place and keeps your studies, settings, databases and tools.
In the window, **Setup, Maintenance, Check for updates** asks GitHub whether a newer release exists, only when you press it, and offers
**Upgrade to <version>**, which runs the same confirmed upgrade; close and reopen PlasBench afterwards. The button is on `main` and
reaches users with the release after v0.4.1.
**Evidence.** `plasbench/updatecheck.py`; `test/test_update_check.py` (a fake release lookup: newer, same, ahead, DNS failure; the route needs
the session key; the window never checks by itself); `test/test_update_script.sh`.
**Status.** Verified on `main`; not in v0.4.1.

### Q30. Can sample data or patient details end up in git?
**Answer.** PlasBench puts each study folder under its own git repository, tracking the study record, the study-level tables, the report and
the logs. Since v0.4.1 its managed `.gitignore` also keeps out per-sample folders (`results/*/`), `data/`, `reads/`, `assembly/`,
`predictions*/`, `metadata/`, `clinical/`, anything named for patient, clinical or line-list data, and sequence, alignment and variant
files. The commit scan blocks the same files if someone forces them in, and blocks columns for patient name, patient id, medical record
number, NHS number, ward, bed number and similar. Age, sex and collection date are not blocked, because cohorts need them, but together they
can identify a person; use de-identified metadata. Files committed before the upgrade stay tracked until `git rm --cached`.
**Evidence.** `plasbench/gitops.py`; `test/test_study_git_data_rules.py`.
**Status.** Fixed in v0.4.1. This is a safety net, not a substitute for governance of patient data.

---

## I. The PlasEval cohort and the comparison gate

### Q31. How does PlasBench know its PlasEval-style scores match the original program on real data?
**Answer.** It checks, wherever the original is installed, and says plainly when it has not. PlasBench's best-match scores and repeat-aware
dissimilarity are reimplemented from the paper (the PlasEval repository has no licence, so none of its code is used or shipped). Three pieces
test them against the original: the 59-case cross-check (Q2); the **`plaseval-ecoli53` cohort**, the paper's 53 *E. coli* isolates with their
accessions and the paper's published ground truth and tool bins (`cohorts/plaseval_ecoli53/bins`, CC BY 4.0), scored by
`plasbench analysis plaseval-replication`; and the **comparison gate** (`python/plaseval_gate.py`, `RUN_PLASEVAL_GATE`), which in stage 6 runs the original
on every pair of exported bins and compares dissimilarity and best-match precision, recall and F1. The verdict (PASS, FAIL, PARTIAL, NOT_RUN or
NO_DATA) is written to `benchmark.plaseval_gate.json` and shown in the report. With `RUN_PLASEVAL_GATE=auto` (the default) it compares when the
original is found and otherwise records NOT_RUN; with `on`, a missing original or a disagreement stops the run. It never changes a score.
**What has and has not been measured.** PlasBench's own numbers on the paper's real bins exist (mean dissimilarity 0.253 MOB-recon, 0.316 gplas2,
0.370 PlasBin-flow, 0.479 HyAsP at alpha 0.5; `docs/PLASEVAL_REPLICATION.md`). **Result against the original program (reference run, 16 Nov 2026, PlasEval commit 8238356, alpha 0.5):** on the paper's 53 isolates and four tools (212 isolate-tool pairs) the original finished 211 pairs and PlasBench's dissimilarity **agreed within 0.001 on 210 of them** (gplas2, HyAsP and MOB-recon on all 53 isolates each, differences 0.000000; PlasBin-flow on 51 of 52). There were **no disagreements**. One pair, EC_9226_3S1_D with PlasBin-flow (26 repeat families), differs by 0.003 (PlasBench 0.5415, original 0.5385): PlasBench's repeat search hit its call cap there, so its value is a stated upper bound, not an error. One pair, EC_9226_C5_H with PlasBin-flow, did not finish in the original within 900 s and is not compared. The original's answers are kept in `cohorts/plaseval_ecoli53/original_reference.tsv`. The tool order depends on the length exponent. **Confirm it yourself.** `python python/plaseval_replication.py --out-dir out` re-scores the cohort and writes `out/plaseval_replication.html`; its section *Comparison with the original PlasEval program* shows the verdict, a per-tool table, the agreement scatter and the pairs not compared. Without a PlasEval checkout it compares with the recorded reference run (and says so on the page); with `--plaseval-src` it re-runs the original. The finished page from the reference run is `cohorts/plaseval_ecoli53/replication_report.html`.
**Evidence.** `python/plaseval_gate.py`; `test/test_plaseval_gate.py` (every verdict, strict exit codes, the capped case, discovery);
`test/test_plaseval_cohort.py` (cohort sheet consistent with the shipped data; replication on real bins); `docs/PLASEVAL_REPLICATION.md`.
**Status.** Gate and cohort built and tested; gate result on real bins **Open**. The cohort is schema-validated only: its online NCBI check has not
been run, its truth is a Unicycler hybrid built on the same reads (reference tier 3), and it covers one species.

---

## J. Reviewer questions on inputs and outputs (16 November 2026)

Three questions came from reviewers about how PlasBench controls input quality, chooses an assembly and treats a tool that reports several
sequences for one plasmid. The answers below say what already existed, what was added, what is provisional and what is still open. The full
register of reviews and what validated each is in [docs/EXTERNAL_REVIEW_LOG.md](docs/EXTERNAL_REVIEW_LOG.md).

### Q32. Can you choose the assembly?
**Answer.** "The assembly" means two different things. **The reference assembly** (the truth) is chosen by evidence, not by preference: reference
tiers, polish independence and evidence-checked labels decide whether it enters the primary analysis (Q3, Q6). **The input assembly** (what the
tools run on) was chosen only by the `ASSEMBLER` setting (`spades` or `unicycler`). It is now chosen by a declared policy from evidence about the
assembly itself, never from the truth or a score (`python/assembly_selection.py`, stage 3):
- every candidate is measured and kept (contigs, N50, L50, largest contig, total length, GC, bases in contigs of 1 kb and 10 kb or more, and, when
  minimap2 and reads are available, the share of sampled reads that map to it) in `results/assembly_candidates.tsv`;
- a candidate is **eligible** only if its total length is plausible for a bacterium plus plasmids (1 to 10 Mb by default) and, when measured, its
  read support is at least 0.80;
- policy `fixed` (default) selects the configured assembler if it is eligible; policy `quality` selects, among the eligible, the highest N50, then the
  fewest contigs. When nothing is eligible **nothing is substituted silently**: the sample is reported as having no eligible assembly;
- `ASSEMBLY_SELECTION_MODE=report` (default) records the choice and acts on nothing; `enforce` makes the choice the assembly the tools run on
  and excludes a sample with no eligible assembly (status `rejected`, never scored as a tool failure); `ASSEMBLY_ALSO=unicycler` runs an extra
  assembler as an alternative candidate. The report shows a QUAST-style comparison table with the selected assembly marked.
**What this is not.** When assemblers are being *compared*, the right design is one input condition per assembler, not a selection. The
alternatives are retained, but running every tool on every alternative assembly (a sensitivity analysis by assembler) is **Open**.
**Evidence.** `python/assembly_selection.py`; `test/test_assembly_selection.py` (policies, no silent substitution, independence from any score
column, read support on real alignments); `test/test_assembly_selection_stage.sh` (report, enforce, fixed, nothing eligible, off).
**Status.** Implemented and tested. The size limits and the 0.80 read-support minimum are **provisional**: freeze them before the main
benchmark. The default is report-only with the `fixed` policy, so existing runs are unchanged.

### Q33. Is there QC of the short reads before the pipeline, and should poor reads be rejected?
**Answer.** Before this change the pipeline trimmed with fastp (`MIN_READ_LEN`, adapters), checked that both read files existed and were non-empty,
and flagged a mixed or oversized *assembly* afterwards (`assembly_qc_gate.py`, advisory). There was no decision about the reads themselves. Now
`python/short_read_qc.py` measures each raw read pair before stage 3 and decides **PASS, WARN or REJECT**, with the reason recorded:
- measured from a sample of the pairs (the total is exact for small files and an estimate, labelled, otherwise): file integrity, read pairs,
  estimated depth, mean quality and Q20/Q30 share, median read length, GC and N fraction, adapter-carrying reads, duplicate pairs, read-name
  synchrony between the two files, and a GC deviation when the expected GC is given;
- an unreadable, truncated, empty or malformed file, or files with unequal read counts, is **always** rejected; every other metric has a warn and a
  reject limit in `config/short_read_qc_thresholds.tsv`;
- `SHORT_READ_QC_MODE=report` (default) records the decision and flags the sample but excludes only an integrity failure; `enforce` also excludes a
  threshold REJECT (status `rejected`: not assembled, tools skipped as "short-read QC rejected", never scored as a tool failure); `off` skips it;
- outputs: `results/short_read_qc.tsv`, `short_read_qc_status.tsv` and, in the report, a MultiQC-style QC panel (`python/report_readqc_panel.py`): General statistics with inline bars and Copy table / Configure columns / Scatter plot / Violin plot / Export as CSV, distributions with the threshold lines, a side panel per sample (each metric as a gauge against its limit, why it passed, warned or was rejected, its assembly selection), the thresholds with their status and hash, and a "What the reviewer asked" box. A run without the table says *Not measured in this run* and gives the command; the offline demo shows clearly labelled SYNTHETIC QC (`python/make_demo_readqc.py`, refuses to run on real samples).
**Not done.** Taxonomic contamination screening (it needs a database; the table says `not_evaluated`). The with-and-without-flagged-samples check is
descriptive: the panel ranks the tools by mean F1 with and without the flagged samples when `scores.tsv` is beside the QC table, and says when it cannot.
**Evidence.** `python/short_read_qc.py`; `test/test_short_read_qc.py` (good, warning-level and reject-level reads, every integrity failure, the
shipped thresholds, and that every threshold row names a metric that is really measured); `test/test_short_read_qc_stage.sh` (stage 3 and stage 4
in all three modes).
**Status.** Implemented and tested. **The thresholds are provisional**: they are conservative starting points, not universal cut-offs. They must be set
from pilot data on the intended platform and then frozen (mark every row `frozen`; the file's hash is written to every QC row) before the main
benchmark. That is why `enforce` is not the default.

### Q33a. Does PlasBench use MultiQC? Which should I look at, MultiQC or the built-in QC panel?
**Answer.** No, PlasBench does not use MultiQC to make its QC (that is fastp plus `python/short_read_qc.py`). The report's QC panel is PlasBench's own, modelled on MultiQC's layout. Real MultiQC is an optional companion: `plasbench install-tools multiqc`, then `MULTIQC_REPORT=auto` (default) runs it in stage 6 over the fastp and QUAST outputs into `results/multiqc/`, and the panel links to the report (it is never embedded). The built-in panel has PlasBench's thresholds, decisions and selection outcome and works offline in one file; MultiQC has more plots, is a separate file and knows nothing of the thresholds. Both read the same files, so shared figures should agree closely (the panel measures the first read pairs; fastp counts every read); if they differ a lot, compare the files. A MultiQC failure never fails a run.
**Evidence.** `python/run_multiqc.py`, `python/multiqc_note.py`, `test/test_run_multiqc.py` (a fake `multiqc` on PATH). **Not verified** against a real MultiQC install in this repository's tests.

### Q34. How is noise picked up when a tool reports more than one sequence for a plasmid?
**Answer.** Already present: a one-to-one bin match (Hungarian), split and merge outcomes, per-plasmid recovery states, CPRR, and the predicted-sequence
burden (`redundant_pred_bp`, unmapped and off-truth bases). What was missing was a candidate-level account. `python/candidate_multiplicity.py` (stage 5,
descriptive) now accounts for **every predicted record**, using the scorer's own alignment filters. For each truth plasmid it separates
- **best-candidate coverage** (the single best record),
- **combined coverage** (the union of all records' alignments, so reference bases are counted once; it equals the base-level recall), and
- **redundancy** (candidate-aligned bases that other candidates already cover, and its share);
and it labels each candidate **primary**, **complementary fragment** (adds at least 10% new bases), **redundant** (adds almost nothing: a duplicate or an
alternative reconstruction), **chimeric** (two replicons each carry at least 1 kb and 10% of its aligned bases), **off-target** (mostly chromosome)
or **unmapped**, with an outcome per plasmid (single, fragmented, duplicated, fragmented and duplicated, missed). A worked case: three candidates of 60,
35 and 30 kb on a 100 kb plasmid give 60% best coverage and 100% combined coverage, not 125%, with 35 kb redundant. The report draws each candidate as
a track against the reference with a strip separating reference covered once, covered by several candidates, and not represented, and shows where
each tool's predicted sequence went (unique plasmid, redundant, chromosome, unmapped).
**It cannot be gamed.** The primary score is untouched: extra candidates do not raise it, and this table is where they show up.
**Limits.** A candidate here is a predicted sequence record, so for a binner the bin-level view stays with the bin metrics. "Redundant" cannot tell
a duplicate from an alternative reconstruction (alignment shows the overlap, not which). The 10%, 1 kb and 10% limits are provisional.
**Evidence.** `python/candidate_multiplicity.py`; `test/test_candidate_multiplicity.py` (fragment, duplicate, alternative, chimera, off-target and
unmapped candidates with hand-worked numbers; a tool that predicted nothing); `test/test_stage_dimensions.sh` (stages 5 and 6 on real alignments).
**Status.** Implemented and tested on constructed cases and a stage run; not yet run on a real cohort.

### Q35. What is done and what is open across the three?
| Phase | Deliverable | Status |
|---|---|---|
| 1 Input QC | Short-read gate, thresholds file, QC tables, report table, pipeline enforcement | **Done** (default report-only; thresholds provisional) |
| 2 Assembly | Candidate metrics, declared policy, selection recorded, alternatives kept | **Done**; running every tool on every alternative **Open** |
| 3 Multiplicity | Candidate table, best versus combined versus redundancy, relationships, chimeric/off-target/unmapped | **Done** on constructed cases; real cohort **Open** |
| 4 Reporting and validation | Three dashboards, synthetic fixtures, existing scores unchanged | **Done**; a documented with-and-without-flagged-samples analysis **Open** |
Nothing here was tuned against which tool wins; freeze the thresholds before the main benchmark.

## K. The 215-question reviewer assessment (16 November 2026)

A second reviewer bank of 215 questions, grouped into 15 scientific domains, was put to PlasBench. Every question is recorded with its status,
the evidence in the repository and what is still needed in [docs/REVIEWER_ASSESSMENT_MATRIX.md](docs/REVIEWER_ASSESSMENT_MATRIX.md) (table:
[REVIEWER_ASSESSMENT_MATRIX.tsv](docs/REVIEWER_ASSESSMENT_MATRIX.tsv)). **That matrix is the project's own reading of its code and tests, not an
independent review.** The answers below cover what the review added.

### Q36. Where does PlasBench stand against the 215 questions?
Of 215: 77 satisfied (a capability exists and a test exercises it), 86 partially satisfied, 51 need validation on real data, 1 is a major gap, none is
out of scope. *Satisfied* does not mean validated on real cohorts: the biggest single limit is still that no real-data run of the full tool set large enough to rank exists (a 10-isolate run exists, Q22)
exists (Q22). The review's four tests are answered like this. **Truth validity:** tiers, independence classes and a per-isolate audit (Q39) exist; an
independently validated subset does not. **Attribution validity** (reads, assembly, classification, binning): QC gate (Q33), assembly policy (Q32),
assembly adequacy and the sensitivity script (Q38) exist; a real multi-assembler result does not. **Scoring validity:** task-specific endpoints,
CPRR beside F1, multiplicity (Q34) and threshold sweeps exist; expert-reviewed thresholds do not. **Generalisation validity:** held-out-study
validation and ranking stability (Q37) exist; independent real studies do not. **Status: Verified** for the matrix itself
(`test/test_reviewer_matrix.py`); the statuses inside it are a self-assessment.

### Q37. Does the ranking survive removing one study or one species?
`python/ranking_stability.py` (stage 6, `RUN_RANKING_STABILITY`, report section *Ranking stability*) re-ranks the tools on each task's pre-registered
metric after leaving out each study, then each species, and after giving every study equal weight. It writes `benchmark.study_sensitivity.tsv`,
`benchmark.species_sensitivity.tsv` and `benchmark.ranking_stability.tsv` with the largest study's and species' share of the cohort, whether the leader
changes, Kendall tau against the full ranking and a one-line verdict (stable, fragile, or not assessed when there is no sample sheet). A cohort
dominated by one study is reported as fragile. It never changes the leaderboard. **Status: Verified** on constructed cohorts
(`test/test_ranking_stability.py`); its result on a real cohort is **Open**.

### Q38. If the assembler changes, does the best tool change?
`python/assembler_sensitivity.py` takes the `scores.tsv` of two or more runs of the same cohort that differ only in the assembly (set
`ASSEMBLY_SELECTION_MODE` or `ASSEMBLY_ALSO` and give each run its own results folder), re-ranks the tools on the isolates every run shares, and
reports per task the leader, Kendall tau, whether the leader changed and a verdict (robust, partly assembler-dependent, assembler-dependent). Use
`--html` for a standalone page. If the leader changes with the assembly, the ranking measures the assembler and tool together and must be reported
that way. **Status: Verified** on constructed runs (`test/test_assembler_sensitivity.py`); **Open:** running the real cohort under two assemblers
(it needs compute; see the resource estimate in the README).

### Q39. How is the trustworthiness of each reference audited?
`python/reference_evidence_audit.py` (stage 6, `RUN_REFERENCE_EVIDENCE_AUDIT`, report section *Reference evidence*) joins the truth provenance,
repeat-content, depth-anomaly and ambiguity tables into one row per isolate: tier, independence, how many of the six evidence fields are recorded,
flags (polished with the benchmark's own reads, short-read-first, no independent validation, repeat-rich plasmids, depth anomalies, ambiguous or
marker-free plasmids), whether it meets the headline rule, and `strong`, `usable_with_caveats` or `weak` with every reason in words. A missing input
table can only lower the status. The "headline reproduced on the strongest subset" test is the existing cohort variants in `rank_robustness`.
**Status: Verified** (`test/test_reference_evidence_audit.py`). **Open:** evidence beyond NCBI metadata for most isolates.

### Q40. How does PlasBench tell "installed" from "validated"?
`validation_status` in `config/tool_capabilities.tsv` has four values: `real_binary_checked` (the real program ran in a test), `adapter_tested`
(parser and adapter tested on fixtures), `untested`, `not_applicable` (baselines). A tool is never called validated because it ran. The review proposed
a seven-step ladder (registered, installed, adapter tested, execution tested, output validated, benchmark validated, real-data validated). The first
four map onto what exists; the last three need controlled datasets and independent real data and are **Open**, not claimed.

### Q41. What was deliberately not changed?
CPRR is not replaced: its thresholds are unvalidated, but nothing shows it fails to measure the intended outcome, and changing the endpoint now
would break comparison with earlier results. PlasEval is not the universal scorer: it evaluates binning, and is used for that, validated against the
original program (Q31). No composite score is the headline: classification, binning, reconstruction, structure and AMR placement measure different
things, so an opaque total would hide trade-offs. The recommender is not tuned until it has been evaluated on independent studies. Tools are not
added to enlarge the leaderboard.

### Q42. The twelve hardest questions, answered without the dashboard
1. **If the reference is wrong, is the correct tool penalised?** It can be. Every reference carries a tier, an independence class and an audit row (Q39); the headline uses only independent references, and the ranking is re-run without the weaker ones (`rank_robustness`). A wrong but independent reference is not detectable by PlasBench: **Open**.
2. **How are poor reads, assembly errors and the algorithm separated?** Read QC (Q33) records input quality before assembly; assembly adequacy records whether the assembly contains the plasmid at all; the assembler-sensitivity script (Q38) shows whether the assembly drives the ranking. A tool is blamed only for what remains. The assembler experiment on a real cohort is **Open**.
3. **95% of ten plasmids or 100% of eight?** They are different endpoints and PlasBench reports both: per-plasmid outcomes and CPRR count complete plasmids, base-level recovery counts bases. Which is "better" depends on the use; the benchmark does not merge them into one score.
4. **Can F1 be high with no complete plasmid?** Yes, and the report shows it: CPRR and the per-plasmid outcome classes sit beside F1.
5. **Can a tool gain by emitting many overlapping candidates?** Not unnoticed: combined coverage uses the union of aligned intervals, and redundancy, off-target and chimeric candidates are reported (Q34).
6. **Is the winner just the tool whose database resembles the cohort?** Database release dates, overlap flags and recovery on plasmids absent from a tool's database are reported; for tools whose database is not installed the overlap screen cannot run: **Open** for those tools.
7. **Is 99% identity correct if structure is wrong?** Structure is reported beside CPRR (gene order, feature preservation, split and merge events) but is not yet part of the CPRR verdict: **Documented**, not claimed as solved.
8. **Is the ranking driven by one species or study?** Q37 answers this per cohort; a ranking dominated by one study is labelled fragile.
9. **Is CPRR biologically meaningful?** Its thresholds are conventions with a published sweep, not derived and not expert-validated: **Needs validation**.
10. **Can it recommend for an unseen organism?** The recommender abstains when evidence is insufficient and is validated by holding out studies, but on synthetic data so far: **Needs validation** on real independent studies.
11. **What shows the scoring code is correct?** Constructed adversarial cases, and agreement with the original PlasEval program on 59 constructed cases and 210 of 211 real-bin pairs (Q31). That supports the binning dissimilarity, not every metric.
12. **What is the most important discovery so far?** None yet, and PlasBench does not claim one: the only real-data run (10 isolates, Q22) is too small to rank tools. What exists is a framework whose scoring, input and reference controls are tested and whose claims carry evidence labels.

### Q43. What did the literature and public-data review add, and what was not adopted?
A review of published plasmid benchmarks (PlasEval, Teixeira 2025, plsMD 2026, the MOB-suite benchmark) and of the published figures on resistance context and relatedness was checked against the code. **Already there:** the circular CGView-style plasmid maps with truth feature rings and a ring per tool, the PlasEval cohort, contig classification, AMR placement, flank context and NGOC, size, replicon and AMR strata (`stratify_recovery.py`), database-overlap screening and the depth and quality ladders.
**Added:** (1) an interactive *AMR regions* view (`python/report_amr_regions.py`) that draws each truth resistance region with its mobile context and a lane per tool showing, gene by gene, whether the gene is on the correct plasmid and whether its flank is covered, with a verdict per region and a table of where resistance information is lost; (2) interactive *synteny ribbons* (`python/report_synteny.py`) showing the order and orientation of each tool's records on a truth plasmid, so a plasmid that is fully covered but cut, shuffled or inverted is visible; (3) three publication cohorts adopted as *candidates* (plsMD filtered 80 isolates, plsMD novel 68, MOB-suite benchmark 133; `cohorts/candidates/PUBLICATION_COHORTS.md`). Both views are descriptive and change no score; both say "Not run" and why when their input is missing.
**Not adopted, by an earlier decision and on purpose:** phylogenetic trees, plasmid clustering and relatedness, pangenome analysis, host-range and transmission inference. They are analyses of plasmids, not measures of how well a tool reconstructs one, and the benchmark stays focused on reconstruction (README, Scientific Guide section 1.3). The one in-scope form of a relatedness figure, a ring per tool coloured by identity against the truth, is covered by the maps and the ribbons.
**Open:** the adopted cohorts are candidates only: assembly accessions are unresolved, truth independence is unverified, and 23 of the 68 novel runs were public before the stated sequencing date, so "novel" is the paper's claim, not checked here. A regression of recovery on plasmid size, repeat content, assembly fragmentation and database membership (the Teixeira analysis) is specified but not built. The views have been tested on constructed data and in the demo report; they have not been looked at on a real cohort. **Status: Verified** (`test/test_report_amr_regions.py`, `test/test_report_synteny.py`, `test/test_publication_cohort_candidates.py`) for what exists.

---

## L. Upgrading to v0.5.0 (18 November 2026)

### Q44. My scores changed after upgrading. Is something wrong?
**Answer.** No: v0.5.0 corrects scoring that the independent audit of 17 November 2026 showed to be too generous or inconsistent. The list is in
[docs/releases/v0.5.0.md](docs/releases/v0.5.0.md). The ones most likely to move a number: NMI, Variation of Information and ARI now penalise a
plasmid that no bin covers (before, one wholly missed plasmid scored a perfect 1.0, 0.0, 1.0); an AMR gene on a record that is in no bin is
`unassigned_contig` rather than `correct_plasmid`; a binner that bins nothing has blank precision; truth provenance now recognises the real NCBI
wording, so more references are short-read-first and some formerly "independent" Illumina-polished ones are not. Re-score older results before
putting them beside new ones.
**Status.** Fixed in v0.5.0; tests fail on the old code and pass on the new.

### Q45. What did the audit leave undone?
**Answer.** [docs/AUDIT_2026_11_17_STATUS.md](docs/AUDIT_2026_11_17_STATUS.md) lists all 53 findings: 42 fixed, 10 partial, 1 not fixed. The gaps that matter
to a user: only three tools have real-binary checks, the download-size and timing figures are estimates, only the gplas2 download checksum is pinned,
there is no default tool time limit (a preset is opt-in), and the window was not tested in a real browser for this release.
**Status.** Open, with each item and its reason in the status table.

### Q46. Is there a real-data result I can look at?
**Answer.** Yes, one small one: [`results_real_cohort1/`](results_real_cohort1/README.md), 10 public isolates scored for `mob_recon`, `platon` and `plasmidspades`
and a coverage baseline. It is a descriptive evaluation, not a ranking, because only 1 of the 10 references reaches reference Tier 2. The larger run on
the independent-truth subset of public-v4 is still to be done.
**Status.** Done for 10 isolates; open for the large panel.

## M. Downloads, long runs and the window (found in field use, 18 November 2026)

### Q47. `plasbench run --cohort accepted_accessions` stopped with a list of errors. Why?
**Answer.** `accepted_accessions` is not a cohort. `cohorts/accepted_accessions.tsv` is the accession ledger: the BioSamples that earlier cohort releases already used, so that a new cohort does not repeat them. It has five columns (`biosample`, `sample_id`, `assembly_accession`, `sra_run`, `source_cohort`). A run needs `organism`, `truth_technology`, `truth_quality_tier`, `biosample` and `bioproject` for every isolate, which the ledger does not carry. Use a real cohort sheet such as `public-v4` (the ledger's `source_cohort` column shows which cohort each row came from). Now the command says this once and stops before it creates a study folder, the cohort picker and the "no such cohort" message list only files a run can use (not the ledger or the metagenomic tables), and stage 0 reports the first three bad rows and a count instead of one identical line per isolate.
**Status.** Fixed after v0.5.0 (next release).

### Q48. The log says "prefetch failed; reads fetched from ENA instead". Is that an error?
**Answer.** No, it is a fallback that worked. `READ_SOURCE=auto` (the default) tries the SRA Toolkit's `prefetch` first and, when it fails, downloads the same run from ENA with MD5 checks. If it failed on every isolate, the toolkit on this computer cannot connect (a TLS, proxy or version problem), and each failed attempt costs about a minute. From the release after v0.5.0 the log shows the toolkit's own last line as the reason, and after `PREFETCH_FAIL_LIMIT` (default 2) isolates in a row where prefetch failed and ENA worked, stage 1 goes to ENA first for the rest of the run. `READ_SOURCE=ena` always does this; `READ_SOURCE=sra` never falls back; `PREFETCH_FAIL_LIMIT=0` always tries prefetch first.
**Status.** Fixed after v0.5.0 (next release).

### Q49. The run shows "stalled" while it downloads. Is it stuck? Does closing the window stop it?
**Answer.** Usually it is not stuck. "Stalled" means no new output in the run log for 10 minutes (`PLASBENCH_STALL_SECONDS`); a download writes to its own log, so a long transfer used to leave the run log silent. From the release after v0.5.0 stage 1 logs a progress line every minute while reads download (`DOWNLOAD_PROGRESS_SECONDS`), for example `SRR123: mate 1 74.7%, mate 2 66.2% (7.1 of 9.5 GB)`. Closing the window does **not** stop a run: runs are detached from it, and you find them again under Runs and reports. To stop one, press Cancel, or quit and choose to stop runs. In a terminal, a download's progress is not the size of its `.part` file when aria2c does the transfer (it preallocates the full size); look at the modification time, or run `python python/download_progress.py --data-dir <the isolate's data folder> --run <SRR...>`.
**Status.** Fixed after v0.5.0 (next release).

### Q50. One isolate in my "quick" 20-isolate run has 9.5 GB of reads. Can I avoid that?
**Answer.** Yes. Stage 1 now looks up each run's exact size at ENA before downloading, prints it, and warns above `WARN_RUN_DOWNLOAD_GB` (default 5): a read set that large is slow to download, needs about three times its size on disk, and is slow or memory-hungry to assemble (9.5 GB of reads for an 8.8 Mb genome is well over 1000-fold coverage). PlasBench does not skip such an isolate: it downloads it in resumable chunks, and for a short paired run deeper than `READ_DEPTH_CAP_X` (default 150x over the reference) it downloads only the first read pairs, which is all the depth the tools can use. (`MAX_RUN_DOWNLOAD_GB` exists as an opt-in limit if you want isolates above some size skipped; it is blank by default.) The summary printed before the download now also shows exact sizes and the largest read set even for a sheet with no lock file, where it used to say "size unknown".
**Status.** Fixed after v0.5.0 (next release). There is still no cap on read depth during assembly.

### Q51. What does `--no-report-prompt` mean?
**Answer.** When a run finishes, PlasBench can stop and ask "open the report?". `--no-report-prompt` removes that question: it prints the report path and exits, so the run can go unattended. It changes nothing about what is run or written. `--open-report` does the opposite, opening the report in your browser at the end without asking. The window always sets `--no-report-prompt`.
**Status.** Documented; the window has a checkbox for opening the report (see the User Guide).

### Q52. Why are my downloaded reads in `~/.local/share/plasbench/data` (or `\\wsl.localhost\...`), and can I change that?
**Answer.** That is the shared data folder (`DATA_DIR`, set by `install.sh`): every study reuses it, so the same reads are never downloaded twice, and it is kept when a study is deleted. Change it for one run with `--data-dir PATH` (the study remembers the folder for its later runs), or for everything with `DATA_DIR` on the Settings page. In the window, New benchmark → Options → "Where to keep downloaded reads and assemblies".
**Status.** Documented in the User Guide ("Where your data and studies live").

### Q53. Can I keep the data inside the study folder?
**Answer.** Yes: `plasbench run ... --keep-data-in-study` (the window's second radio). The reads go to `<study>/data`, which the managed `.gitignore` excludes (checked with `git check-ignore`), and they are deleted with the study. The study remembers the choice, so Resume finds them. **Manage study → Delete downloaded data only** frees the space and keeps the results.
**Status.** Done after v0.5.0 (next release).

### Q54. Can a study live on another drive, or outside the workspace?
**Answer.** Yes: `--study-location PARENT_DIR` (the folder must exist) or "Another folder" in the window's Study folder card or New study. PlasBench keeps a hidden list of where outside studies are, so they appear on the Workspace page and in `--study NAME`. If the drive is disconnected the study is shown as "not available" with Remove from list; nothing is created in its place. A Windows drive seen from WSL, or a cloud-sync folder, is slower or can lock files; the folder check warns.
**Status.** Done after v0.5.0 (next release); rename, copy and archive are only for studies inside the workspace.

### Q55. My drive is not listed in "Choose a folder". How do I select it?
**Answer.** Under WSL, Ubuntu lists only the Windows drives it has mounted. In the Terminal tab run, for drive E, `sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e`, then press Refresh in the chooser; or type the Windows path (`E:\data`) in the path box, which is converted. PlasBench never runs the mount command itself.
**Status.** Documented in the User Guide.

### Q56. Why is my cancelled run not in the Jobs list, when I can see its folder in the studies tree?
**Answer.** Two different reasons, both fixed. (1) A job started from the window is saved in a shared list; two windows (or a window and its background watcher) could overwrite each other's saves, and a deleted job could come back. The list is now saved under an exclusive lock, each job also keeps a small `<id>.meta.json` beside its log so the list can be rebuilt from the folder, deletions are written down, and a failed, interrupted or cancelled job is kept until you delete it or it is older than `PLASBENCH_JOB_RETENTION_DAYS` (default 180; 0 keeps them for ever). (2) A run you start in the Terminal tab or a shell is not a job of the window, so it never was in the Jobs list; the Runs page now shows the latest run of each study that was started outside the window, read-only and marked "started outside the window" (running, completed, or "interrupted or cancelled: it stopped without recording how it ended"), with Show in terminal and Open folder. The window cannot cancel such a run because it does not own the process.
**Status.** Fixed after v0.5.0 (next release).

### Q57. My run has been "stuck" for hours. How do I find out what it is doing?
**Answer.** Run `plasbench status` (or `plasbench diagnose` for the busiest processes too; add `--watch 30` to repeat, or `--study NAME` to pick a study). It reads the run's event log, its lock, the status tables, the processes under it and the machine's memory and disk, and says in plain words: whether it is running, finished, or was cut off; the stage, isolate and step it is in and for how long; progress so far; CPU and memory; the newest log of that isolate and when it last changed; and hints that follow from those figures (for example "this isolate's reads are 9.4 GB compressed", "180 MB of memory is available", "3100 MB of swap is in use"). It never guesses: each hint shows the figure behind it.
**What was wrong before.** The long steps of stage 3 (trimming with fastp, assembling with SPAdes or Unicycler) wrote only to their own logs, and the "still working" heartbeat existed only for the stage-4 tools, so a run could be silent in the run log for hours. Now every long command in stage 3 prints a heartbeat (elapsed time, CPU and memory of the command and what it started, memory, swap and disk of the machine, how long ago its own log last changed and that log's last line) and warns when memory is nearly gone or the command has used almost no CPU and written nothing for ten minutes.
**Status.** Fixed after v0.5.0 (next release).

### Q58. Where are the logs of a run?
**Answer.** In the study folder: `logs/run_<date>-<time>.log` is everything the run printed, including the heartbeats (`logs/run.latest.log` points at the newest; the newest 20 are kept, `LOG_RETENTION_RUNS`; `RUN_CONSOLE_LOG=0` turns it off); `logs/<sample>.<step>.log` is each tool's own output; `results/run_events.jsonl` has one JSON line per event (stage start and end, isolate steps, command start and end with exit code and seconds, heartbeats with CPU and memory, warnings), safe to read by machine; `results/stage_timing.tsv` has seconds per stage. Events carry names and numbers only, never environment variables or commands.
**Status.** New after v0.5.0.

### Q59. PlasBench says "needs the internet" but my browser works. What do I do?
**Answer.** Run `plasbench net`: it tests each service separately. "DNS is not working" with a working connection is common in WSL2 or behind a VPN (`wsl --shutdown` in PowerShell, turn the VPN off or on, or set a DNS server); one service down while others work means that service (NCBI, ENA, GitHub, conda) is down or blocked, and the message names a way round it (for example `READ_SOURCE=ena`, or `--local-inputs` with files you place yourself); a sign-in or certificate message points at a captive portal or proxy. To work offline on purpose set `PLASBENCH_OFFLINE=1`; scoring, reports and runs on files already on disk keep working. See the User Guide, "When You Are Offline".
**Status.** New after v0.5.0.

### Q60. Why does the window sign in with a pop-up and a code instead of taking me to GitHub?
**Answer.** It uses GitHub's device flow through the GitHub CLI: the window shows a one-time code and opens github.com in a small pop-up it controls, so you never leave PlasBench; approving there signs you in and closes the pop-up. No app has to be registered and the page never sees a token. If your browser blocks the pop-up, the window shows the address with an Open button. Without the GitHub CLI, install it (the window shows the command) or sign in with a personal access token, which is passed over standard input only.
**Status.** Done after v0.5.0 (next release); not exercised against a real account in the tests.

### Q61. A button is greyed out with "Needs the internet". Why, and can I still work?
**Answer.** The top bar checks the internet and each service (GitHub, NCBI, SRA, ENA, PyPI, conda, Zenodo, PLSDB). A control that needs an unreachable service looks disabled with the reason and advice; it stays focusable, and clicking it checks again at that moment. Local work (scoring, reports, studies, settings, a run whose reads are already on disk) never needs the internet. `PLASBENCH_OFFLINE=1` forces offline mode on purpose.
**Status.** Done after v0.5.0 (next release).

### Q62. My reads and reference genomes are in one big folder. Do I have to name every file?
**Answer.** No. Use **Your own isolates > Scan a folder** in the window, or `plasbench scan-isolates FOLDER` (add `--write-sheet config/local.tsv` to place what it finds). It looks through the sub-folders, pairs the reads by their names (`_R1/_R2`, `_1/_2`, lanes, SRA style), picks the complete reference for each isolate and tells you why, and ignores BAMs, logs, PDFs, spreadsheets and assembler output such as `contigs.fasta`. It changes nothing in your folder; whatever it is unsure of is shown as an issue with the alternatives, never chosen silently. **Limit.** It matches by folder and file names and the start of each file, so a reference sitting in the right folder but from another strain looks right; check every isolate marked "check" and run the quick test. See the guide section "Add isolates from a folder".
**Status.** New after v0.5.0.

### Q63. `plasbench install-tools gplas2 --yes` printed a note and then "ERROR ... failed with exit code 20". Did something break? Why are my tools not installed when I run?
**Answer.** Nothing broke, and the old behaviour was wrong in two ways. (1) Exit **20** means "a manual step is needed; nothing failed" and **21** means "consent is needed; nothing was changed". Every wrapper (the window's console and job state, the terminal page, `scripts/lib.sh`) now reports them as information, with no `ERROR` and no red, whatever command returned them. (2) The tools are now installed for you: gplas2, PLASMe, plASgraph2, PlasmidEC, PlasBin-flow and the Mobilome Annotation Pipeline install from a pinned commit into their own environment when you agree (`--yes`, `y`, the window's dialog, `INSTALL_MISSING_TOOLS=1`). Only plsMD and PPR-Meta stay manual, each with a verified reason and a recipe (INSTALL.md, "Tools that cannot be installed automatically"). A run with a missing enabled tool installs it first when you asked it to, and otherwise stops before any sample work naming every missing tool and the command that installs it; it never silently skips one. If a window or terminal still shows the old message, it is an old window server: restart the window.
**Evidence.** `python/source_install.py`, `config/source_tools.json`, `docs/TOOL_INSTALL_AUDIT.md`, `plasbench/exitcodes.py`; `test/test_source_install.sh`, `test/test_exit20_wrappers.py`, `test/test_tool_install_registry.py`, `test/test_setup_interactive.sh`.
**Status.** Fixed in v0.5.3. The installs were exercised with fake conda, pip and a local upstream; a real conda solve of each source tool is not part of the test suite.

### Q64. What do the numbers on the Scoring decisions page allow?
**Answer.** Each numeric decision shows its type (whole number, decimal, fraction, seconds), its minimum and maximum, its unit and its default, in a small label and in the tooltip, and the
edit box is a number input (with a slider when both bounds are enforced) that turns red outside the range. The ranges come from one table, `config/setting_ranges.tsv`, written from what the
code refuses: the decision editor accepts whole numbers of 0 or more and decimals of 0 or more, and the scorers refuse an identity or coverage outside 0 to 1 and a recovery threshold
outside above 0 up to 1. Where the code accepts anything, the label says **no maximum enforced** rather than inventing a bound. Saving a setting outside its range is refused with a plain sentence; a value that is
already saved is never rejected on a later save, and clearing a setting to its default always works.
**Evidence.** `python/setting_ranges.py`, `test/test_setting_ranges.py` (runs `score_bins.py` and the decision validator against the table).
**Status.** New after v0.5.0.

### Q65. The "This computer" card showed fewer CPUs and less memory than my machine has. Which numbers are right?
**Answer.** Both, for different things. Inside WSL2 the card now shows the Linux virtual machine's CPUs, memory (total and **available now**) and swap, then the Windows host (read through
PowerShell) and the `.wslconfig` limits, and says plainly that the VM's numbers are set by `C:\Users\<you>\.wslconfig` and change only after `wsl --shutdown`. It also reports a cgroup limit
or a CPU affinity when one is in force, and what a benchmark will use (threads = usable CPUs; assembler memory = 85% of what is available now minus 512 MB, rounded down to whole GB, between 2 and 64, as `config/config.sh` computes it). Units are GB = 2^30 bytes.
The **Drives** table lists every mounted drive with label, mount point (and the Windows letter under WSL), filesystem, used and free space, type (internal, removable, network, optical,
cloud-synced; "guess" where it can only be inferred from the mount point), read-only flag, which drive holds the data folder, the workspace and the current study, and the slow-drive and
cloud-sync warnings. **Refresh** looks again and marks drives plugged in since the last look as new and lists the ones removed. A Windows drive that is plugged in but not mounted in Ubuntu shows the
`sudo mount -t drvfs` command the folder chooser shows; PlasBench never runs it. A probe that fails reads "unknown".
**Evidence.** `plasbench/computer_info.py`; `test/test_computer_info.py` (sample /proc/meminfo, /proc/mounts, df, lsblk, PowerShell, wmic, sysctl, vm_stat and mount output for Linux, WSL, macOS and Windows).
**Status.** Fixed after v0.5.0 (next release). Not yet checked on a real Mac.

### Q66. I updated PlasBench and the window shows errors like "no such API: workflow". What is wrong?
**Answer.** The window you have open is an old program showing a new page. PlasBench re-reads its page from disk when it changes, but the server behind it is loaded once, when it starts; after an update (`plasbench upgrade`, `update.sh`, a git pull, a new release) the new page asks the old server for things it does not have. The window now notices: it compares the version it started from with the files on disk and shows a banner, "PlasBench was updated (0.5.1 -> 0.5.2) while this window was open", and any "no such API" error is replaced by "This window is running an older version of PlasBench than the page. Restart the window." (the original text is under Details). **Restart window** starts the new version and opens it at its new address; your runs are detached and keep going. Where PlasBench cannot restart itself, the dialog says exactly what to do: **Quit** (choose Quit and keep running if a run is going), then start PlasBench again from its desktop icon or with `plasbench ui`. If a page only looks stuck, **Reload page (clear cache)** (top bar, banner, or Ctrl+Shift+R, Cmd+Shift+R on a Mac) reloads it without restarting anything.
**Evidence.** `plasbench/server_state.py`, `GET /api/server-state`, `POST /api/server/restart`; `test/test_stale_server.py`.
**Status.** Fixed in v0.5.3. Not yet checked in a real browser or on a real desktop shortcut.

### Q66a. The banner says my window is older than the page, but I just updated and restarted. Is it wrong?
**Answer.** Two different things can be true, and the banner now tells them apart. (1) *The program this window loaded changed on disk* (an update ran while it was open, or a second `plasbench ui` or the desktop icon brought back a window started before the update): **Restart window** fixes it, and a second `plasbench ui` now replaces a window older than the command instead of reusing it. (2) *PlasBench is installed in two places with different versions*: a copy in the plasbench environment (made by `python -m pip install --no-deps .`) and your PlasBench folder. Restarting loads the same old copy and cannot help; run `conda activate plasbench && cd ~/PlasBench && python -m pip install --no-deps .` (or `plasbench upgrade`, which now checks and repairs this). The banner shows the evidence under **Details** (versions, both paths, pid and port, which modules changed with their hashes), can be dismissed for the current server run, and no longer appears for a file that was only touched (same content), a file the window never loaded, or caches. Run `plasbench ui-state` to get the same evidence in a block you can paste.
**Evidence.** `plasbench/server_state.py`, `plasbench/roots.py`, `plasbench ui-state`; `test/test_stale_false_positive.py`.
**Status.** Cause inferred from the code, not reproduced on the reporter's WSL machine; the fix is tested with temporary trees and fake servers, not in a real browser.

### Q66b. What is the difference between closing the window, Quit, Quit everything and wsl --shutdown?
**Answer.** Closing the window (X, Alt+F4, closing the app window or tab) stops nothing: PlasBench and your runs keep going, and `plasbench ui` or the desktop icon brings you back to the same server. **Quit** ends this server (with runs going you choose Cancel, Stop and quit, or Quit and keep running, the default). **Quit, then Stop all PlasBench on this computer...** (or `plasbench stop`) ends every PlasBench server of your account, including stale ones on other ports; runs keep going unless you also switch on "Also stop N running runs/jobs" (or `--runs`); only servers PlasBench recorded and verified are ended, a program that merely holds a PlasBench port is reported and left alone. In WSL only, **Quit and restart WSL** (`plasbench stop --wsl-shutdown --yes`) additionally runs `wsl --shutdown`: it ends every WSL distribution, the Docker Desktop engine and every WSL terminal, so it is blocked while runs are active unless you stop them, asks you to type `SHUT DOWN WSL`, and is never done by default. Finished work is always kept. **Evidence.** `plasbench/stopall.py`, `test/test_stop_all.py`. **Status.** Fakes and two real local servers; the Windows-from-WSL window closing and `wsl --shutdown` were never run for real in tests.

### Q66c. Pop-ups keep saying "This window needs to be reopened" or "program files changed", even right after Restart window. What is going on?
**Answer.** Two separate faults, both fixed in the version after 0.5.5. (1) *"PlasBench's program files changed while this window was open ... this server is older than the page"* appeared on every open of a healthy window: the page's own check for an older server contained the placeholder text the server fills in, so the server rewrote the check itself and it always said "older". Restart window could never clear it, and the banner then invited another restart. It is gone: the check no longer contains the placeholder, and a test now renders the page the way the server does and runs the served check. (2) *"This window needs to be reopened ... it cannot reconnect"* came back every few seconds: each restart makes a new key, and an OLDER window still open kept sending its old key although the browser already held the new one. The server now accepts the browser's own cookie when the key is old (the cookie is HttpOnly and same-site, and the Host and same-origin checks are unchanged), the window recovers silently, and a window that really belongs to an older session shows one bar with **Close this window** instead of a repeating pop-up. Opening PlasBench again now brings the window you already have to the front instead of opening another, and Restart window keeps the same address and the same window. If you still see the pop-ups after upgrading: close every PlasBench window (check the taskbar), run `plasbench ui` once, and run `plasbench ui-state`: it lists every PlasBench server on this computer, how many windows reported in, and anything else listening on the port.
**Evidence.** `plasbench/windowlife.py`, `plasbench/webui.py` (`token_ok`, `/api/window-ping`, `/api/reopen`), `plasbench/data/ui.html`; `test/test_window_stability.py`, `test/test_window_stability_browser.py`.
**Status.** The false banner was reproduced from the served page and fixed; the key handling and the single window are tested with real servers, node and (opt-in) a real headless Edge; a real Edge app window on WSL2 was not driven. The Windows-from-WSL "bring the window to the front" step uses PowerShell AppActivate and was tested with a fake PowerShell only.

### Q67. The run stopped in stage 3 with "SPAdes failed". What now?
Read the block it printed: it names the cause from the assembler's log ("the disk is full", "the computer ran out of memory", "a read file is truncated", and so on), quotes the log line it is based on, and says what to do. The same cause and advice are in `results/assembly_status.tsv` (columns `cause` and `advice`) and in `plasbench status`. A cause that belongs to the computer (a full disk, a broken Python, a CPU feature, a folder that cannot be written) would repeat for every isolate, so the stage stops at the first isolate (exit code 5) instead of spending minutes on each; fix it and run the same `plasbench run ...` command again, and finished work is reused (there is no separate `--resume`). Out of memory is retried once, automatically, with half the threads and a memory budget that fits what is free now. A log PlasBench does not recognise is reported as "not recognised" with its last lines; nothing is guessed. Under WSL a full Windows drive (usually C:, which holds Ubuntu's virtual disk) makes Ubuntu report "No space left on device" even when `df` inside Ubuntu shows room; the resource check before stage 3 looks at that drive. See the User Guide, Troubleshooting.

### Q68. Browse does not open the folder window (WSL, Windows, Linux, Docker). What do I do, and does it work in Docker?
Run `plasbench picker-check` (or Settings, Test the folder window). It prints PASS or FAIL for each step: what kind of computer this is, WSL interop, which `powershell.exe` is used, a minimal PowerShell
script, whether the Explorer-style window can be compiled, a real test window that closes itself after two seconds (`--interactive` leaves it open for you to choose a folder), the conversion to a Linux path, and
what Browse will do. When the window cannot open, Browse shows a dialog with the reason, a Why? fold, Copy diagnostics and the built-in browser; it never does nothing. Behind the report are the causes this
version handles: `powershell.exe` not on the WSL PATH (`appendWindowsPath=false`; PlasBench also looks in `/mnt/c/Windows` and asks `cmd.exe`), interop switched off, a script too long for the Windows
command line (it now travels as a short unpacker, a temp `.ps1` file or on stdin), `Add-Type` blocked (the older Windows windows and `Shell.Application` take over), a locked-down PowerShell (named as such),
a dialog that opened behind the browser (top-most owner, Alt-key and thread-input foreground trick, a flashing taskbar button, Bring it to front) and a slow first start (the page warns after 8 seconds and lets you keep
waiting). In Docker there is no desktop, so no folder window can open by nature: Browse is the built-in browser at the mounted folders, with a banner that other folders are not visible and an **Add another folder** helper that
writes the `docker run -v` command. From a window on your computer, **Run in Docker instead** appears only if Docker answers `docker info`; it only shows and copies the command.
**Evidence.** `plasbench/native_picker.py`, `plasbench/picker_check.py`, `plasbench/docker_helper.py`; `test/test_picker_diagnostics.py` (fakes for WSL and Docker; the real PowerShell route and a real folder window found with UI Automation on Windows); `test/test_picker_ui_browser.py` (opt-in, real browser).
**Status.** Fixed here. Verified on a real Windows computer (the window opens, comes to the front and closes); the WSL-specific steps (interop, `wslpath`, `\\wsl.localhost`) are tested with fakes, so run `plasbench picker-check` inside WSL to confirm on yours.

### Q69. I could not install Docker from the tools setup. What does PlasBench do now?
`plasbench install-tools docker` (or **Install Docker** on the Tools page) first works out what this computer is and what state Docker is in, then does the one thing a user-level program may and tells you the rest. On Windows and on WSL 2 it runs `winget install -e --id Docker.DockerDesktop` on the Windows side after you agree; **Windows asks you to approve the installer**, and afterwards you start Docker Desktop, accept its licence (PlasBench cannot accept it for you) and turn on Settings > Resources > WSL integration for your Ubuntu. On macOS it runs `brew install --cask docker-desktop` when Homebrew exists. On Linux, and for Docker Engine inside WSL without Docker Desktop, it prints the exact commands from docs.docker.com (with a check of the repository signing key) for you to run with your own sudo: PlasBench never runs sudo and never pipes a script to a shell. When it hands steps to you it exits **20** (the window shows *Waiting for you to finish in Docker Desktop*, not an error); press **Re-check** when you are done. If it says *permission needed*, add yourself to the docker group and log in again; *WSL integration off* is a Docker Desktop setting; *daemon stopped* means start Docker Desktop or `sudo systemctl start docker`.
**Evidence.** `python/docker_setup.py`, `env/install_tools.sh`; `test/test_docker_setup.py` (recorded `docker version` / `docker info` outputs for every state, each platform's plan, the winget and Homebrew argument lists with fake programs), `test/test_docker_install.sh` (the exit codes 0 / 20 / 21 / 1 with fake `winget.exe`, `brew`, `docker` and a `sudo` that must never be called).
**Status.** Implemented. Tested with fake programs only: no real Docker was installed or started by the tests. The Windows approval prompt and Docker Desktop's first launch are yours by design.

### Q70. How do I update PlasBench from the window, or install a release file I already downloaded?
**Answer.** Set up this computer, **Updates**. **Check for updates** shows the installed and latest versions, the release date and what changed; **Download and install** verifies the download against the release's checksum, replaces the program files, and offers **Restart window**; **Install from a file I already downloaded** does the same from `plasbench-<version>.tar.gz` with no internet; **Roll back** returns to the release saved by the last update. It is blocked while a run is going unless you choose **Update anyway**. If it fails the card names the reason (no internet, checksum mismatch, full disk, no conda, wrong file) and whether anything was changed. A first installation from a downloaded file is in the README, "I already downloaded the release file" (`bash install_latest.sh --archive plasbench-<version>.tar.gz`).
**Evidence.** `plasbench/updatecheck.py`, `plasbench/updater.py`, `update.sh`, `POST /api/updates/install`; `test/test_updates.py`, `test/test_upgrade_e2e.sh` (a fake GitHub and fake release files: a bad checksum, a misnamed or foreign file and a second update are refused with nothing replaced).
**Status.** Tested with fakes, not against a real release download from the window or a real WSL/conda upgrade; not checked in a real browser.

### Q71. Why does the Terminal only list Bash, and how do I get Windows PowerShell or Command Prompt there?

**Answer.** The Terminal lists shells according to where the window runs. A window that runs inside Ubuntu (WSL) used to offer only its Ubuntu shell. It now also offers Windows PowerShell, Windows Command Prompt (cmd) and Git Bash (Windows) while WSL interop is on; the Ubuntu shell stays the default and is labelled with the distribution (*Ubuntu-24.04 (Bash)*). If a Windows entry is greyed, hover it: the reason is usually that interop is off (`/etc/wsl.conf` `[interop] enabled=false`, or restart WSL with `wsl --shutdown`) or that Windows is not mounted. Git Bash appears only when Git for Windows is installed. On a Windows window the list is each Ubuntu (WSL), Git Bash, PowerShell and Command Prompt (cmd); on Linux and macOS, your login shell and `pwsh` if installed. `plasbench` works in each of them and runs the same PlasBench folder. Command Prompt cannot start in an Ubuntu folder (a `\wsl.localhost` path), so the Terminal uses a temporary drive letter (`pushd`); Windows shells cannot see Ubuntu's tools.
**Evidence.** `plasbench/terminal.py` (`available_shells`, `windows_side`, the shims); `test/test_terminal_shells.py`.
**Status.** The lists, argument lists, quoting of hostile text, folder translation, shims, kill path and output decoding are tested with fakes. On the developer's Windows 11 computer the Command Prompt, PowerShell and Git Bash entries ran real commands, and from a real Ubuntu 24.04 under WSL2 the Windows PowerShell, cmd and Git Bash entries ran real commands (a drive folder and an Ubuntu folder). Not tested: WSL with interop switched off, WSL 1, other distributions, a non-Western Windows code page, cancelling from the window (there is no cancel button yet; a timeout does stop the whole tree).

### Q72. PlasBench says Docker is installed but not ready. What is missing?
Docker Desktop needs four things, in order, and `plasbench install-tools docker` (or the Docker card on the Tools page) shows which one is next: **installed** on Windows, **running**, its **engine answering** (this needs the Docker licence accepted by you in Docker Desktop's window, and the first start can take a few minutes), and, in WSL 2, **WSL integration** switched on for your Ubuntu (Docker Desktop > Settings > Resources > WSL integration). PlasBench reads, read-only, the Windows-side files, whether `Docker Desktop.exe` is running, `docker.exe info` and Docker Desktop's settings file, so it can say *installed on Windows but not started* instead of *not installed*, *starting* (often the licence window waiting for you), or *integration is off for Ubuntu-24.04*. `The command 'docker' could not be found in this WSL 2 distro` means exactly that last case. What PlasBench can do for you, after asking: **Start Docker Desktop** (`plasbench install-tools docker --start`) and **Open WSL integration settings** (`--open-integration`), then check again every 5 seconds. What it never does: accept the licence, edit Docker Desktop's settings, or click in its window. The job ends with exit 20 (*Waiting for you*, not an error) until the missing step is done.
**Evidence.** `python/docker_setup.py`; `test/test_docker_post_install.py` (a fake Windows tree under `/mnt/c`, recorded `tasklist` / `winget list` / `docker info` outputs and `settings-store.json` shapes, the winget-then-detect sequence without the 90 s wait, the `--start` argument list with hostile paths).
**Group changes.** If you ran `sudo usermod -aG docker $USER` and `docker` works in your terminal but the window still says permission denied, the window is a running program that keeps the groups it started with. PlasBench compares the account's groups now (`/etc/group`) with this process's groups and says **Restart needed**: press **Restart window** (it relaunches itself with `sg docker` when `sg` exists, otherwise it tells you to run `newgrp docker` then `plasbench ui`, or `wsl --shutdown` and reopen Ubuntu). Someone who is not in the group yet still gets the plain *add yourself to the group* steps.
**Status.** Implemented. Checked read-only on a real Windows 11 machine with Docker Desktop installed and not running; the WSL 2 flow and the exact `docker-desktop://` settings link are not verified on a real WSL 2 computer (the link falls back to opening Docker Desktop's window).

### Q73. How do I report a problem?
Open a [New issue](https://github.com/ubeffiong/plasbench/issues/new/choose) and pick **Bug report**, **Feature request** or **Question**; search the existing issues first. For a bug send: what you were trying to do, what you expected and what happened; the exact command or buttons; the **complete** error text pasted as text (not a screenshot); `plasbench --version` and your system; and the output of `plasbench issue-report`, which collects the versions, the computer, Docker and conda, the study's run status and the last lines of the newest run log and of each failed assembler or tool log, with tokens, e-mail and IP addresses and your user name removed. Never post tokens, passwords, API keys or patient data; security problems go through [SECURITY.md](SECURITY.md), not a public issue. The full guide is the README section [Reporting an issue](README.md#reporting-an-issue); the short version is [SUPPORT.md](SUPPORT.md).
**Evidence.** `plasbench/issue_report.py`; `.github/ISSUE_TEMPLATE/`; `test/test_issue_report.py`.
**Status.** Implemented. The issue forms render only on GitHub after they are on the default branch; they were checked offline (YAML schema keys, ids, field parity with the README), not rendered.

### Q74. My pull or build failed: what now?
**Answer.** Read the diagnosis PlasBench printed (or press **Run health check** on the Environment card / run `plasbench runtime doctor`): it names the cause from the error's own words and lists safe steps. The causes it tells apart: a corrupted or incomplete layer (retried automatically; check proxies and the network, do not build), a read-only or full Docker disk, a damaged Docker Desktop install (`dockerd configuration error`), the engine not running or not allowed, a registry limit or login problem, a certificate or clock problem (corporate proxies), DNS and network failures, storage-driver errors, a build killed for memory. PlasBench builds the image locally **only** when the image truly is not available (tag not published, private and not readable yet, wrong CPU architecture); after any engine, disk, corruption, network or unrecognised error it stops and builds nothing, because a build needs the same engine and internet and takes hours. An error PlasBench does not recognise is reported as *unknown* with the last lines, never guessed. Commands are shown for you to run; PlasBench runs only read-only checks, and shows anything that deletes data (`docker system prune`, `docker image rm`, Clean / Purge data) last, with its consequence.
**Evidence.** `python/docker_diagnosis.py`, `plasbench/docker_health.py`, `plasbench/docker_runtime.py`; `test/test_docker_diagnosis.py` (every message of the brief, including the exact text of a production failure: corrupted layer, read-only metadata database, `dockerd configuration error`), `test/test_docker_health.py` (a scripted fake `docker`), `test/test_docker_runtime_e2e.py` (the doctor and the write test against the real Docker of the CI runner).
**Status.** Implemented. Message-level diagnosis only: the root cause of the production failure could not be inspected from here, and most message samples are written from knowledge of docker's formats, not captured logs. The real engine is exercised in CI only for a healthy engine; unhealthy engines are simulated.

### Q75. Why did a tool install fail in Docker mode ("Permission denied", "Could not open lockfile")?
In Docker mode the container runs as your own user, while the image's conda environments (`/opt/conda/envs/*`) belong to the image: they are read-only for you, so a solver that tries to write there fails with `Could not open lockfile ... conda-meta.lock` or `Permission denied` while unlinking packages. PlasBench installs into the persistent extras folder instead (`~/.plasbench/docker/<version>/extras/envs/extras`), never into the image, and stops at once, with the path it tried to write, if an install would write to a read-only environment; one failed profile is not retried in the same `plasbench check --yes`, and the summary at the end says which installs worked, failed or need a manual step (exit code 1 when a requested install failed). If you see this error, update PlasBench and the image (`plasbench runtime check`; the image must match the version), then run `plasbench check --yes` again. Look at what was installed with `ls ~/.plasbench/docker/<version>/extras/envs/extras/bin`; to start the extras over, remove that folder yourself (`rm -rf ~/.plasbench/docker/<version>/extras`: PlasBench never runs it, and the folder holds no results or databases).
**Evidence.** `env/install_tools.sh`, `python/install_diagnosis.py`, `test/test_docker_extras.sh`, `test/test_docker_extras.py`, `test/test_docker_extras_e2e.py` (a real non-root container with a root-owned environment, in CI). **Status.** Implemented; not verified on a Docker Desktop / WSL2 computer by the maintainers.

### Q76. My run has been quiet for hours. Is it stuck, and what changed?
Run `plasbench status` first: it names the stage, isolate and step and how long that step has run against its typical time (config/step_typical.tsv, estimates for a 6-CPU laptop). In one real run the status said "stage 1, step download" while stage 2 was annotating, so the stages now write their own start and end events. The same run had two real causes of lost hours: SPAdes stopped with `You need approx. 5.24277GB of free RAM` under a 4 GB budget (PlasBench now reads that number and retries once with enough, or says exactly why it cannot), and a stage loop that let a command read the sample list, so only the first isolate of a stage was handled (fixed in every stage; an isolate no step reached is now recorded as not attempted). ISEScan ran 11 minutes and then failed because `fastcluster` 1.3.0 does not work with NumPy 1.x; `plasbench check` now catches that in a second. Resources now adapt by themselves (`AUTO_RESOURCES=1`; see docs/RESOURCE_ADAPTATION.md). Settings: `MEMORY_GB`, `AUTO_RESOURCES`, `ASSEMBLER_ALLOW_ONLY_ASSEMBLER`, `WORK_DIR`, `ANNOTATION_TIMEOUT_SECONDS`, `STEP_SLOW_FACTOR`; see the USER_GUIDE section "My run looks stuck".

### Q77. Can I ask questions inside the window, and what does it send?
Yes: the **AI help** tab of the side panel (top-bar button, or Alt+Shift+H) and `plasbench ask "your question"` answer from PlasBench's own guides, with the sources as chips and the exact command to run, and the place to run it (PlasBench's Terminal tab, Windows PowerShell, your Ubuntu terminal). It uses **free** models only (OpenRouter, sign-in in a small pop-up; Hugging Face if the owner registered an app; or a model on your own computer, which sends nothing anywhere). Nothing is sent until you sign in, read the notice and ask; it sends your question, a few guide excerpts and a short setup line, never paths, your user name or e-mail address, or your data. It never runs a command by itself: a suggested command has a **Run in PlasBench** button that opens the usual confirmation with the exact command. Free models are limited by the provider and a provider may log prompts under its own policy, so read the notice. See [docs/AI_HELP.md](docs/AI_HELP.md); `AI_HELP_ENABLED=0` turns it off.

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
cross-check, and PlasBench computes the same dissimilarity itself, including the repeat-aware pairing of repeated contigs (Q2); the
first-class adapter and a run on real data are **Open**. **Answered / Open.**

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
only with enough samples across a real size range. No published figures exist yet (the only real-data run is 10 isolates, Q22), so claims about maximum
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

**26a. Can an old or published results folder redraw the new report figures?** Only if it still holds the per-sample files they read. `plasbench check-results RESULTS_DIR` says which sections cannot draw and why, and `plasbench regenerate-visuals RESULTS_DIR --data-dir DIR` rebuilds the cheap ones (alignment blocks, truth and QC tables, structural calls) with the pipeline's own scripts, byte-identical to a fresh run (`test_regenerate_visuals.py`). It never changes scores or the `benchmark.*` tables, never overwrites an existing file without `--force`, and records what it wrote in `regenerated_inputs.json`, which the report shows in Run metadata. What it cannot rebuild (tool predictions that were not kept, reference FASTAs that were deleted, reads, a curated AMR table) it names, with the command to run once those are supplied. The inputs of each report section are in `docs/REPORT_INPUTS.md`; new runs keep them in the results folder (`KEEP_REPORT_INPUTS=1`). **Verified.**

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

**30. Journal reviewer questions (Q456-470).** The most likely rejections: only a small real-data result (10 isolates, no ranking); truth is an assembly;
cohort small and taxonomically narrow; no independent validation of intervals or against an independent scorer. These are the
open items below. Code is accessible; reproducibility is addressed above. A resource or benchmark paper is the defensible fit.

**31. Funder and innovation questions (Q471-484).** The gap addressed is evidence-based tool choice for plasmid reconstruction,
including in under-sampled regions; the minimum useful version is the default-tool, short-read benchmark on a diverse cohort.
Risks: no real-data run large enough to rank (only 10 isolates so far, Q22), single-maintainer sustainability, a very large documentation and feature surface. The project concept
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

1. **No real-data run large enough to rank** (Q22; a 10-isolate run exists): needs compute and data. Everything about ranking stability and generalisation depends on it.
2. **Database release dates and database FASTAs for tools whose databases are not installed** (Q16): the dates come from each
   tool's maintainers; the sequence-level screen needs the database on disk.
3. **Independent audit of references, and read support for every truth replicon** (Q3, Q4): needs reads and curation.
4. **External validation cohort and a coverage simulation for the intervals** (Q14).
5. **Plasmid-free, hard-structure and taxonomically broader isolates** in the released cohorts (Q12, Part 2 section 18): data curation.
6. **The result of the PlasEval comparison gate on the 53-isolate cohort, and a first-class adapter** (Q2, Q31): the cohort, the paper's bins, the gate and the error-profile charts are built and tested; on the cohort the original program finished 211 of 212 pairs and PlasBench agreed within 0.001 on 210 with no disagreement (Q31). Remaining: the one pair the original could not finish, and the paper's own printed figures.
7. **Abstention rate, NGA50 and AMI**: no wrapped tool reports an explicit "unclassified" call, NGA50 needs contig-level
   misassembly breaks, and AMI's expected-information term is impractical over base counts. Contig-level classification
   (count-based and length-weighted precision, recall, F1 and MCC) is done; ambiguous contigs are excluded, not multi-assigned.
8. **A literature comparison establishing novelty** (Part 2 section 2).
9. **Stale per-tool result files** when the tool set changes between runs (Q21): clear `results/` between such runs.

### Can I run PlasBench's tools in Docker instead of conda, and switch between them?

Yes. Set up this computer, **Environment**, or `plasbench runtime use docker` / `plasbench runtime use conda`. The window stays on your computer; runs, checks and tool installs execute in a container
of the PlasBench image with your study, data and database folders mounted at the same paths, so every recorded path is valid on both sides. If the image is not on the computer and cannot be pulled,
PlasBench builds it from the Dockerfile after you agree (needs the internet, several GB, a long time, not measured). Tools and databases not in the image are installed into persistent storage
mounted into every container (the image is never changed); a tool that needs a licence is still a manual step. `plasbench runtime check` tests Docker step by step. **Evidence.** `plasbench/docker_runtime.py`,
`test/test_docker_runtime.py` (a recording fake Docker), `test/test_docker_runtime_e2e.py` (a real build and real containers in CI). **Status.** Verified with real Docker only in CI (Linux);
the Windows and WSL2 paths are tested with fakes, so run `plasbench runtime check` on your computer.
