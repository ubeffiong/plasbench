# Independent verification of the PlasBench audits

**Reviewed object:** `main` at commit `17c9936` (17 November 2026), which includes the public-v4 cohort (#98).
**Audits challenged:** [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md) (written at `52f3b2a`), [reviews/SECOND_REVIEW_RESPONSE.md](reviews/SECOND_REVIEW_RESPONSE.md), [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md) and [EXTERNAL_REVIEW_LOG.md](EXTERNAL_REVIEW_LOG.md).
**Stance:** the question is whether PlasBench is ready for independent research use, not whether the earlier audits look complete.

## 0. What this verification is and is not

Every row below says how it was checked. Three levels are used:

- **Ran:** I executed code against `main` and read the output (commands are in section 8).
- **Read:** I read the code or data but did not execute it.
- **Delegated:** a subagent ran the experiment and reported; I did not repeat it.

**Not done:** the demo before/after byte comparison, a new run on real reads, any real plasmid tool run by me, install in a clean environment, the browser behaviour of the report. A finding marked "Requires additional evidence" was not examined or could not be settled with what I ran.

## 1. Verdict

**PlasBench is ready for a pilot and for external methodological review. It is not ready to be cited as evidence that one plasmid tool is better than another**, for three reasons that are independent of the quality of the code:

1. The only real-data run in the repository (`results_real_cohort1`, 10 isolates, PlasBench 0.2.3, three real tools) has a headline that rests on one Tier-2 isolate, so it shows the pipeline works on real reads but cannot rank tools. The first version of this document said no real-data result existed; that was wrong, see the correction below.
2. The metrics have verified blind spots that can rank a tool above where it belongs (section 4).
3. Only 15% of the 7,227 public-v4 isolates have truth that is independent of the benchmark's own reads (section 5).

The framework is honest about most of its weaknesses and several of the first audit's findings have since been fixed. The remaining gaps are specific and fixable.

## 2. The first audit's findings, challenged

| # | Claim in the first audit | Class | How | Evidence |
|---|---|---|---|---|
| 1 | No real-data result exists. | **True when the audit was written (8 November); not true now** | Read, Ran | `results_real_cohort1` (renamed from `benchmark.report_cohort1`) is a real run produced on 14 November with PlasBench 0.2.3: 10 public isolates, `mob_recon`, `platon`, `plasmidspades` and a baseline, all 40 runs completed. Its run tables are consistent (checked with the new `run_consistency.py`). Limits: 1 of the 10 references is Tier 2 and 9 are Tier 3, so the headline basis is one isolate and the interval is "< 5 independent units". My first version of this row said "Confirmed" because I looked for a results folder by its usual name and missed this one. |
| 2 | Truth independence is poor (0 of 98 Tier 1). | **Confirmed, and larger now** | Ran | public-v4: only 1,099 of 7,227 rows (15%) are `long_read_only` with polish `none`. 4,975 (69%) are `same_as_benchmark`; 1,153 (16%) are `unknown`. |
| 3 | Cohort column `truth_quality_tier` is misleading. | **Partially confirmed** | Ran, Read | It is a curation grade (`A` = a reviewed publication or collection names the study; `B` = complete but not curator-approved; `python/validate_cohort.py:121`), not a measure of how good the truth is. All 7,227 public-v4 rows are `B` because none was curator-reviewed, including 2,522 short-read-first rows. The name invites the misreading. It also caps the provenance tier: `python/truth_provenance.py:243-250` gives Tier 1 only to grade `A`, so no public-v4 isolate can be Tier 1. That does not change the headline, which already takes Tiers 1 and 2. My first version said the column "carries no information"; it carries this cap. |
| 4 | No plasmid-free isolates. | **Confirmed** | Ran | public-v4: 0 rows with a plasmid count of 0. |
| 5 | A minimum of 5 clusters makes p < 0.05 unreachable. | **Confirmed at the time, now fixed** | Read, Ran | `python/resampling.py:47-48`: `MIN_CLUSTERS_TEST = 6`. Simulated type-I error under a true null: 0.027 (6 clusters), 0.047 (8), 0.053 (12), 0.050 (20). Calibrated. |
| 6 | The statistics were never checked by simulation. | **Incorrect now** | Read, Ran | `python/simulate_validation.py` and [STATS_VALIDATION.md](STATS_VALIDATION.md) exist. The audit's underlying worry is still right (item 7). |
| 7 | (implied) Reported 95% intervals are trustworthy. | **Not supported** | Ran | My simulation (clustered, skewed scores; 300 repeats per row, so about ±2 points): the percentile cluster bootstrap covered 81% (5 clusters), 86% (8), 89% (12), 88% (20), 94% (40). The cluster-t interval covered 87%, 88%, 91%, 88%, 94%. Ignoring clusters covered only 53–65%. The repository's own validation already records under-coverage, so this is disclosed, not hidden. |
| 8 | The headline silently falls back to all samples. | **Confirmed, then fixed** | Delegated | Report shows "Primary analysis unavailable ... PROVISIONAL ranking ... must not be quoted as one" (`build_html_report.py:596-610`). |
| 9 | Unmapped or off-truth predicted bases are never false positives. | **Confirmed** | Ran, Read | `score_plasmids.py:90-222` and the experiments in section 4. |
| 10 | A mixed plasmid/chromosome bin is still matched and "the headline cannot see an assembly-error bin". | **Partially confirmed** | Ran | Chromosome bases a bin aligns to **do** count against length-weighted precision: one bin holding both plasmids plus 50 kb of chromosome scored precision 0.50, F1 0.57; a contig of 90 kb plasmid plus 10 kb chromosome scored 0.93. What is invisible is sequence that aligns nowhere (N1). |
| 11 | No real plasmid tool runs in any test. | **Confirmed, with nuance** | Read (delegated survey) | No PR-gating test runs a real tool. A weekly, advisory workflow runs three on pBR322, with the pass floor at 0 (N4). |
| 12 | Thresholds (200 bp, 0.90, bands, CPRR 0.95/0.95/0.99) have no derivation. | **Requires additional evidence** | – | Not re-examined. |
| 13 | Date-only leakage screen on `main`. | **Requires additional evidence** | – | Not re-examined; the sequence-level check was reported merged in #12. |
| 14 | Install pipeline inconsistent (fixed in #15). | **Requires additional evidence** | – | Not re-examined. |
| 15 | Performance figures in the performance audit. | **Partially confirmed** | Ran | The rectangular matching speed-up reproduces (2,000 bins × 30 plasmids matched in 0.015 s). The 645.9 s → 179.7 s demo timing and the other timings were not repeated (section 7). |

## 3. What the audits missed or got wrong (new findings)

| ID | Finding | Severity | How |
|---|---|---|---|
| N1 | **A bin can be padded with sequence that aligns nowhere at no cost.** **Fixed in this change** (strict columns, section 12). | High | Ran |
| N2 | **The report accepts inconsistent inputs silently** (missing runs, stale rows, duplicate rows). **Fixed in this change** (section 12); re-ranking on the shared subset is by design and still shown only as "on N shared". | High | Delegated |
| N3 | Public-v4 cluster key is the BioProject; clonal relatedness across BioProjects is not handled. | Medium | Read (cohort), unverified effect |
| N4 | The weekly real-tool check cannot fail on bad output: `min_plasmid_share` is 0 for all three tools (`test/real_tools/expected.tsv`). **Partly fixed**: a share of zero now fails; a real floor still needs a reviewed first run. | Medium | Read |
| N5 | A test exists that nothing runs: `test/test_reference_groups.py` is in neither `test/run_tests.sh` nor any workflow. It passes when run by hand. **Fixed in this change** (registered). | Low | Ran |
| N6 | The HTML report never says the data is synthetic or demo, and nothing stopped synthetic and real samples sharing a report. **Fixed in this change** (section 12). | Medium | Delegated |
| N7 | A documented command fails: `plasbench plaseval-replication` (`FAQ.md:384`, `docs/PLASEVAL_REPLICATION.md:14,58`) exits 2. The working form is `plasbench analysis plaseval-replication`. **Fixed in #101.** | Medium | Ran |
| N8 | The Galaxy wrapper pins `TOOL_VERSION` 0.2.4 (`galaxy/macros.xml:5`); the package is 0.4.1 and the 0.2.x tags were removed. Whether conda can resolve it was not checked. **Pin synced and drift test added in this change; conda resolution still unchecked.** | Medium | Read |
| N9 | `test/run_demo.sh` ends several analyses with `|| true` (lines 99, 105, 107, 189-194, 249), so a broken optional analysis leaves the demo green. **Six of them fixed in this change.** | Low–Medium | Read (delegated survey) |
| N10 | 69 non-`RUN_` configuration keys are documented nowhere; `GPLAS_THREADS` is dead; `ASSEMBLER_SENSITIVITY_NAME` is read but undeclared. | Low | Delegated |
| N11 | A cohort's "older" arm is 5,688 of 7,227 isolates (79%). Older isolates are more likely to be in a tool's own database, so the leakage exposure of public-v4 is probably higher than public-v3's. The size of the effect was not measured. | Medium | Read (cohort), effect unverified |

### N1 in detail (the main new result)

`python/score_bins.py` defines bin purity and length-weighted precision over **aligned** bases. I built a truth set with a 4 Mb chromosome and plasmids of 100 kb and 50 kb, then scored these predictions with the project's own script:

| Case | Length-weighted F1 | Count-based bin F1 | Correct plasmid reconstruction |
|---|---|---|---|
| Ideal: two bins, one per plasmid | 1.00 | 1.00 | both yes |
| **Plasmid bin plus one contig of 5 Mb that aligns nowhere** | **1.00** | **1.00** | **both yes** |
| **Plasmid bin plus 20 contigs of 250 kb that align nowhere** | **1.00** | **1.00** | **both yes** |
| Everything in one bin (both plasmids plus 50 kb of chromosome) | 0.57 | 0.00 | both no |
| One contig: 90 kb of plasmid and 10 kb of chromosome | 0.93 | 1.00 | plasmid 1 no |
| Plasmid 1 predicted as 40 duplicate bins | 0.07 | 0.09 | plasmid 1 no (split) |
| Empty prediction | 0.00 | 0.00 | both no |

The rows that count against a tool behave as intended. The two bold rows are the problem: a tool that bundles large amounts of foreign, novel or contaminating sequence into a bin keeps a perfect score on every binning metric, including the headline.

**Why it matters in practice.** Truth is a single isolate's finished genome. Anything a tool puts in a bin that is not in that genome (contamination, a plasmid the truth record lacks, assembly junk, host sequence from a mixed sample) cannot align and is therefore never counted. The `assembly_aware` columns are blank without the contig coverage table and address a different question (what the assembly could have achieved).

**Recommendation.** Add a bin-level unaligned share (unaligned bases ÷ all bases in the bin) beside purity; include unaligned bases in the denominator of a second, stricter length-weighted precision; show both in the leaderboard; add the seven cases above as a regression test.

### N2 in detail

A delegated experiment on a copy of the demo (`test/run_demo.sh`, then mutated inputs and a rebuild of the aggregation and report). I did not repeat it.

| Mutation | What the report did | Verdict |
|---|---|---|
| Run marked failed or timed out | Scored as F1 = 0, counted in "Failed", flagged in the Summary and Run health | Safe |
| Run completed but its score row removed | Tool still ranked #1 with "Scored 5, Completed 6"; only the count mismatch hints at it | Misleading |
| Run absent from both status and scores | No warning; tool ranked normally | Misleading |
| Tool absent from 3 of 6 samples | Whole track re-ranked on the 3 shared samples; "on 3 shared" is the only signal | Misleading |
| A stale duplicate score row added | Mean precision, recall and bin F1 polluted; "7 / 6 completed" is the only hint; an unknown sample appeared in menus | Misleading |
| NaN or text in a numeric cell | Crash with a traceback (`aggregate_results.py:~217`) | Rejected, but not with a message |
| Truncated `scores.tsv` | Crash with `IndexError` (`aggregate_results.py:~211`); the previous HTML is left in place | Rejected, stale report remains |
| Sample with no true plasmids | Metrics blank and sample excluded; shown only as "on 5" | Safe |

**Recommendation.** Make aggregation fail loudly when the score table and the status table disagree (a run completed with no scores, a score without a status, a duplicate run key, a sample outside the cohort), write a run identifier into every table and show it in the report, and delete or mark the old HTML when a build fails.

## 4. Metric definitions re-examined

| Metric | Result |
|---|---|
| Base-level TP, FP, FN | Matches its definition (reference-projected; primary alignments only; coverage capped at length). Predicted bases that do not align never count as FP, and a duplicated plasmid earns no penalty (reported only as a diagnostic). Both are documented choices, not bugs, but they favour tools that over-predict. |
| Rectangular Hungarian matching | Independent of the first audit: `test_matching` (1,373 instances with a unique optimum identical, 8 tied instances with equal total weight) passes. Ties are broken differently from the earlier code in 8 of 1,381 instances, so a published result could change by a tie-break. |
| Length-weighted binning F1 | Correct for aligned bases, blind to unaligned bases (N1). |
| CPRR | Gates on coverage, share, split and identity as documented; split and merge cases behave correctly in my cases; inherits N1 through "share". |
| Wilcoxon and sign-flip tests | Hand-derived exact p-values pass (`test_wilcoxon`); the sign-flip test is calibrated in my simulation. |
| Confidence intervals | Under-cover (finding 7). |
| NGOC, Holm, feature preservation, accuracy layers | **Not re-derived.** |

## 5. Ground truth and sequencing independence

- Truth independence by strategy and polish, public-v4 (Ran): `long_read_only`/`none` 1,099; `long_read_first_hybrid`/`same_as_benchmark` 2,453; `short_read_first_hybrid`/`same_as_benchmark` 2,522; `unknown`/`unknown` 1,153.
- The strategy and polish values are inferred from NCBI free text by pattern matching (the first audit's point, not re-tested here). Whether the 1,153 `unknown` rows are mostly independent or mostly not cannot be told from the cohort file.
- 11.3% of cells in the cohort file are blank; 794 isolates have no sample origin.
- Clusters are BioProjects (1,821 clusters, largest 6.0% of isolates). Isolates from different BioProjects can be the same lineage; the cluster-aware statistics assume they are not. This is a limit on the independence the intervals assume, not a measured error.

## 6. Tests that give false confidence

From a delegated read of `test/`, the workflows and `run_tests.sh`; items marked (Ran) I repeated.

- **Skips that never trigger in CI.** Real-minimap2 tests skip silently without the binary and CI installs it, so locally a missing dependency is green. The PlasEval cross-check, the one independent oracle for the bin-agreement code, skips without its source and CI has no copy.
- **Fixtures instead of tools.** Mash, samtools, BLAST, genomad and abricate tests monkeypatch the binary. They check parsing and the "missing tool gives a blank" path, not that the real binary produces what the parser expects.
- **Re-implementation tests.** `test_resampling_equivalence` compares the code to verbatim copies of its predecessor with the same seeds. It guards refactors; it cannot catch an error both versions share. `test_scoring_adversarial` pins current behaviour, including the known optimism. Neither would have caught N1.
- **Existence tests.** About 49 report tests check that strings appear in the HTML.
- **Unregistered test (N5), advisory real-tool floor of 0 (N4), `|| true` in the demo (N9).**
- **Good tests:** `test_wilcoxon` (hand-derived), `test_simulate_validation` (smoke mode only, loose bounds), `test_contig_crosscheck` (two independent labellers), `test_script_wiring` (finds dead scripts), `test_real_tool_checks`.

## 7. Performance and resource estimates

- **Measured and reproducible by harness:** the timings in `PERFORMANCE_AUDIT.md` come from `test/bench/` on one machine. One reproduced here (matching).
- **Not repeated:** the demo's 645.9 s → 179.7 s, the aggregation timings and the download timings. Treat them as measured once, on one machine.
- **Not in the repository:** per-tool run-time and memory estimates. Those were only given in conversation, were estimates, and the planned pilot to measure them was never run. No document in the repository should be read as a measured per-tool resource figure.

## 8. Fixes that may have introduced regressions

- **Found:** the documentation I added for the PlasEval replication named a command that does not exist (N7). Fixed here.
- **Tested, none found:** after the performance work, `test_matching`, `test_resampling_equivalence`, `test_scoring_adversarial`, `test_wilcoxon`, `test_bin_matching` and `test_reference_groups` pass on Windows. The matching tie-break change is documented.
- **Not tested:** whether any fix after the first audit changed scores on the demo (the full before/after comparison was not repeated).

## 9. Disconnected modules, duplicates, incomplete workflows

- **Modules:** 171 of 174 `python/*.py` files are reachable from a stage script, the CLI or another reachable module. Three are hand-run maintenance tools (`build_guide_toc`, `build_implementation_catalogue`, `build_publication_cohort_candidates`) named only in the catalogue (Read, delegated). Nine more are loaded dynamically (`report_fig_*`, `report_collapse`).
- **Tools:** 22 of 27 registered tools have an adapter or builtin and an installer row; 5 are demo-only synthetic tools. Wiring was read, not executed. Several tools are `automated=planned`.
- **CLI:** 58 subcommands, `--help` exits 0 for all of them; one documented command is wrong (N7); 3 subcommands are in no document.
- **Report:** the registry lists 201 outputs, none marked not surfaced; two registered sections (`learn-refaudit`, `learn-stability`) appear only when their inputs exist.
- **Not found:** duplicate scoring implementations. Not searched exhaustively.

## 10. Prioritised unresolved issues

| Rank | Issue | Why it ranks here |
|---|---|---|
| 1 | A real-data run large enough to rank: `results_real_cohort1` has 10 isolates and one Tier-2 reference. The public-v4 independent subset (1,099 isolates, 211 clusters) is the obvious next run. | Without it no tool ranking can be quoted. |
| 2 | N1: unaligned bases in a bin are free. | A verified way to keep a perfect binning score; fixable in one script. |
| 3 | N2: inconsistent or stale inputs produce a normal-looking report. | A silent wrong ranking from an incomplete run. |
| 4 | Independence of truth: 15% of public-v4 is independent; the sensitivity analysis must be shown beside every headline. | Limits what the headline can claim. |
| 5 | Intervals under-cover (81–94% for a nominal 95%). | Overstates certainty about close rankings. |
| 6 | N11 and leakage: measure the effect of database overlap on public-v4; confirm the sequence-level check on this cohort. | Could inflate tools trained on older data. |
| 7 | N3: relatedness across BioProjects. | Assumed away by the statistics. |
| 8 | N4, N5, N9: tests that cannot fail or never run. | False assurance. |
| 9 | N6: label synthetic data inside the HTML. | A synthetic report can be mistaken for a result. |
| 10 | N7 (fixed), N8, N10: documentation and wrapper drift. | Users hit them first. |
| 11 | Thresholds, install wiring and leakage details not re-examined (rows 12–14). | Unknown, not shown to be wrong. |

## 11. Commands run

All from the repository root of a worktree at `17c9936`; scratch scripts were kept outside the repository.

- Module reachability scan of `python/*.py` against `python/`, `scripts/`, `plasbench/`, `adapters/`, `config/`, `galaxy/`, `env/`, `Makefile`, `install.sh`, `update.sh`, `.github/`, `Dockerfile` and `pyproject.toml`.
- Cohort counts: a short script over `cohorts/public-v4.tsv` (strategy, polish, tier, origin, BioProject, blank cells, plasmid-free rows).
- Interval and test calibration: a simulation calling `resampling.bootstrap_ci`, `resampling.cluster_t_ci` and `resampling.paired_permutation_pvalue` on clustered, beta-distributed data (5–40 clusters, 300 repeats).
- Binning cases: `python/score_bins.py` run on seven constructed truth/prediction sets (table in section 3).
- Tests: `test_reference_groups`, `test_matching`, `test_resampling_equivalence`, `test_scoring_adversarial`, `test_wilcoxon`, `test_bin_matching`.
- Command check: the `plasbench` entry point with `plaseval-replication` (exit 2) and `analysis plaseval-replication`.
- Delegated: report failure-state experiments (N2, N6), the test-suite survey (section 6) and the interface survey (sections 9, N8, N10).

## 12. What changed in response (this PR)

| Finding | Change | Where | Test |
|---|---|---|---|
| Real-data result was missed | Folder renamed `benchmark.report_cohort1` to `results_real_cohort1`, a README states what it is and is not, corrections above | `results_real_cohort1/README.md` | – |
| N1 unaligned bases in a bin | `score_bins.py` takes `--pred-fasta` and writes `bin_unaligned_bp`, `bin_unaligned_fraction`, `lw_bin_precision_strict`, `lw_bin_f1_strict`; stage 5 passes the predicted sequences; the columns reach `scores.tsv` and the leaderboard as `mean_lw_bin_f1_strict` and `mean_bin_unaligned_fraction`. The headline is unchanged on purpose: the strict value sits beside it | `python/score_bins.py`, `merge_bin_metrics.py`, `aggregate_results.py`, `scripts/05_score.sh` | `test/test_bin_unaligned.py` |
| N2 inconsistent inputs | `python/run_consistency.py` finds duplicate runs, completed runs with no score and no recorded failure, and scores with no status (errors), and samples outside the sheet (a warning only: the sheet in use is often not the run's own). Aggregation stops on an error with a message unless `ALLOW_INCONSISTENT_RUNS=1`; then the report carries a banner. A malformed or truncated score table now stops with the file, line and value instead of a traceback | `python/run_consistency.py`, `aggregate_results.py`, `build_html_report.py` | `test/test_run_consistency.py` |
| N6 synthetic data | `python/data_nature.py`: a run mixing synthetic (`sample_origin = synthetic`) and real samples is refused by aggregation and by the report builder (`ALLOW_SYNTHETIC_WITH_REAL=1` overrides, for engine tests only); an all-synthetic report carries a "Demonstration data" banner | `python/data_nature.py`, `aggregate_results.py`, `build_html_report.py` | `test/test_run_consistency.py` |
| N4 real-tool floor | A share of zero fails | `test/real_tools/check_real_tool.py` | `test/test_real_tool_checks.py` |
| N5 unregistered test | `test_reference_groups.py` registered | `test/run_tests.sh` | – |
| N9 `\|\| true` | Removed from the six optional demo analyses (lines 189-194) | `test/run_demo.sh` | demo end to end |
| N8 Galaxy pin | `TOOL_VERSION` 0.2.4 to 0.4.1; a drift test compares it with `pyproject.toml` | `galaxy/macros.xml` | `test/test_doc_versions.py` |

**Not changed, and why**

- **Truth independence (15% independent).** A property of the public data, not of the code. The report already shows the independent-truth sensitivity; the way to improve it is to run the 1,099 `long_read_only` isolates. No subset cohort file was created in this change.
- **No plasmid-free isolates.** Also a property of the cohort. The scorer already supports plasmid-free isolates (`isolate_specificity`, `n_zero_plasmid_isolates`); none is in public-v4.
- **Cohort column `truth_quality_tier`.** A required schema field with a real function (it gates Tier 1). Renaming it means migrating every cohort file and lock; left as a documented name problem.
- **Unaligned predicted bases never false positives (base-level).** The base-level scorer is unchanged; the new columns cover the binning layer only.
- **Confidence intervals under-cover.** Disclosed in `STATS_VALIDATION.md`; no method change.
