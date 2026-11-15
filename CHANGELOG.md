# Changelog

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

The v0.1.x series was renumbered on 2026-09-09 from an earlier, denser
v0.1.0-v0.2.8 sequence (19 tags) down to 5 milestone releases. Each entry
below folds in every change from the tags it supersedes -- nothing from that
history is lost, only the numbering is cleaner. See
[docs/releases/](docs/releases/) for the full per-version notes.

## [Unreleased]

### Added -- complete statistics simulation study, results by number of studies
- `simulate_validation.py` now simulates dominant and heavy studies, within-study correlation, missing outputs, resource failures (per isolate and whole studies), a dominant species (stratified functions) and Holm over many comparisons; results are summarised by number of independent studies (`benchmark.stats_validation_by_studies.tsv`) with a status that stays provisional unless a full run supports it. `--workers` runs scenarios in parallel.
- Full run (86 rows, all three interval methods) committed in `docs/stats_validation/` and written up in `docs/STATS_VALIDATION.md`: tests and Holm are calibrated; cluster-t (the default) covers 94-96% with balanced or moderately unbalanced studies but only 64-79% with a dominant study or two heavy studies; the percentile bootstrap under-covers elsewhere. The statistics stay provisional.

### Changed -- reference independence is its own classification (review of the reference standard)
- `truth_provenance.py` records two separate things per reference: `reference_quality` (validated / partially validated / provisional, the tier) and `evaluation_independence` (independent / partially independent / dependent / unknown, with `independence_reason`). Appended columns; the tier stays.
- The primary analysis needs a reference that is within `HEADLINE_MAX_REFERENCE_TIER` AND independent (`HEADLINE_INDEPENDENCE`, default `independent`), from at least `HEADLINE_MIN_CLUSTERS` independent clusters counted over the qualifying references only. Dependent and unknown references never enter it. Before, a tier-2 reference polished with the benchmark's own reads counted as primary; it is now partially independent and a sensitivity analysis. The pre-registration row `headline_independence` is marked proposed.
- Sensitivity populations: sensitivity 1 adds partially independent references, sensitivity 2 is every reference (`independent_references_only` and `independent_or_partial_references` cohort variants in the rank-sensitivity table; `benchmark.reference_independence.tsv`; per-class table and the two columns in the report's Headline design tab). README and the Scientific guide state the full rule.

### Fixed -- AMR placement forced one record per plasmid on classifiers
- `score_amr_placement.py` matched every tool's records to plasmids one-to-one, so a classifier that reported two contigs of one plasmid had the second contig marked wrong. It now takes `--task` (the registry's `evaluation_task`; stage 5 and the demo pass it): binners stay one-to-one; classifiers and reassemblers attribute each record to the plasmid it overlaps most.
- AMR-PRR and the pairs-kept-together figure are blank for classifiers (no plasmid-level reconstruction claim); the report says "not applicable (classifier)" and explains the rule. New columns `evaluation_task` and `attribution` (appended). Regression test `test/test_amr_placement_by_task.py`: one plasmid, two resistance genes on two contigs.

### Fixed -- classification, binning and reassembly were conflated (review of the task logic)
- The task of a tool was decided by `binning_capable` alone, so every tool that was not binning-capable was a classifier even when it reassembles plasmid sequences (plasmidSPAdes, and the demo's `spades_like`), while Plassembler, Hybracter and plsmd, which also reassemble, shared one reconstruction track with the binners. `config/tool_capabilities.tsv` now has an explicit `evaluation_task` column (`classification`, `binning_reconstruction`, `sequence_reassembly`) and the ranking code reads it (`headline_design.Design`, `tool_capabilities.evaluation_task`); `binning_capable` only says whether the output is a set of per-plasmid units that the bin metrics can score (yes for binning and reassembly, no for classification) and the registry reader refuses a row where the two disagree. A registry without the column keeps its old answers, telling a reassembler from a binner.
- Each task has its own pre-registered primary endpoint on every input track: base F1 (classification), length-weighted binning F1 (binning reconstruction), isolate-level CPRR (sequence reassembly). The track-specific exception that sent long-read and hybrid binners to CPRR is gone. `config/prereg.tsv`: `primary_endpoint` revised and `primary_endpoint_long_read` replaced by `primary_endpoint_reassembly`, both marked *proposed* until you confirm them (they were *fixed*).
- plasmidSPAdes and the demo's reassembler are now bin-scored (each reassembled record is its own bin, as `adapt_plasmidspades.sh` writes it), so they get a CPRR; the leaderboard shows three task groups.
- Recommendations are made for one task: `select_operational_method.py --task` takes `binning_reconstruction` (the default, as before minus the reassemblers), `sequence_reassembly`, `classification`, `all`, or the old `reconstruction` (= binning).
- A user tool's manifest states `task = binning_reconstruction`, `sequence_reassembly` or `classification`; the old `task = reconstruction` still means binning. The setup window lists and filters the three tasks. Results written before the split (task `reconstruction`) still render, labelled as older. `test/test_evaluation_tasks.py` is new.

## [0.4.0] - 2026-11-15

A feature release that also changes how tools are scored and ranked: **scores and rankings from v0.4.0 are not
directly comparable with v0.3.0 or earlier**. New: the correct plasmid reconstruction rate (CPRR) with SV-PRR and
AMR plasmid context, the burden of unverified predicted sequence, a metric registry and evaluation ladder, more truth
audits, a structured evidence record per reference, real-binary checks, database provenance and validation tiers,
new report figures, a three-way recommender comparison, study folders, and a window that reuses what is already
installed. Changed: permutation tests need six independent units, the primary analysis is reported unavailable
instead of silently falling back, the recommendation model uses truth-free features only, and (after the second
external review) tools are ranked in the task their output declares, references polished with the benchmark's own
reads leave the primary analysis, intervals use a cluster-robust t method chosen by simulation, and AMR placement no
longer penalises tools that do not bin. See the [release notes](docs/releases/v0.4.0.md) and
[docs/reviews/SECOND_REVIEW_RESPONSE.md](docs/reviews/SECOND_REVIEW_RESPONSE.md). Compare: [v0.3.0...v0.4.0](https://github.com/ubeffiong/plasbench/compare/v0.3.0...v0.4.0).

### Changed -- the second external review (P0 and P1)
- **Evaluation task per tool.** `config/tool_capabilities.tsv` declares `evaluation_task` (`binning_reconstruction`, `sequence_reassembly`, `classification`) and `output_unit` from each tool's output contract. A tool without bins was ranked as a contig classifier, so plasmidSPAdes shared a leaderboard with Platon; it now has a reassembly track ranked by base-level sequence-recovery F1. User manifests accept `task = reassembly`; an older registry falls back to `binning_capable`. Each metric in `config/metrics.tsv` lists the tasks it can score. Leaderboards say what their ranking metric measures (binning F1 is grouping, not complete reconstruction).
- **Reference independence beside reference quality.** `truth_provenance.py` writes `reference_independence` and `reference_group`. By default (`HEADLINE_REFERENCE_INDEPENDENCE=independent`, pre-registered as proposed) a tier 2 reference polished with the benchmark's own reads is a dependent reference: it leaves the primary analysis and appears in the new `benchmark.reference_independence.tsv` (mean, rank and their change from the independent group), shown in the report. The headline design records the composition. `any` restores the tier-only rule.
- **Intervals chosen by simulation.** The percentile cluster bootstrap under-covers with few studies. `resampling.py` adds a cluster-robust t interval (CR1, t on G−1 df, stratified form) and a studentized cluster bootstrap; `simulate_validation.py` measures all three, plus stratified scenarios and the Holm family-wise error. The leaderboard and comparison intervals use `PLASBENCH_CI_METHOD` (default `cluster_t`), recorded in every output.
- **Effect before significance.** Paired comparisons gain `effect_status` and `testable`; equivalence needs an interval (`not_assessed` without one), so a small difference with no interval is no longer called equal performance.
- **AMR placement for tools that do not bin** is contig attribution: several records may come from one plasmid, so one-to-one matching no longer penalises a classifier. It is sequence attribution, not reconstruction; AMR-PRR and pairs kept together stay unavailable for such tools.
- **Recommender validation.** Isolate, study, clonal-group, study-and-clonal and species holdouts (`benchmark.recommender_holdouts.tsv`); two taxonomy-aware nearest-neighbour arms; robust scaling, a missingness penalty, abstention outside the training range, per-recommendation uncertainty (`benchmark.recommender_knn.tsv`), sensitivity to K, scaling and each feature, and feature correlation. An arm is enabled only when it adds value under the strictest holdout. The ridge model needs that evidence and calibrated out-of-study intervals before it is activated.
- **Pre-registration, scorecard, documents.** A new `unavailable` status resolves the A4/C2 bands (no truth variant set; nothing invented); nothing is `TO_FIX`. The scorecard orders tools on the metrics every tool has. The Scientific Guide names 0.4.0 (`test_doc_versions.py` keeps versions in step); the first independent review is labelled historical.

### Changed -- the window shows and reuses what is already installed
- Database paths in the New benchmark wizard and the command forms are an optional fold, *Use a different database
  copy*, closed unless one is filled in. Each field shows whether the database is installed and where; an empty
  field uses the installed copy, resolved like `config/config.sh` does: an explicit setting, then the machine-wide
  store (`PLASBENCH_DB_DIR`, default `~/.plasbench/databases`), then a copy under `DATA_DIR/db`. Databases are
  downloaded once per computer and reused by every benchmark.
- Settings shows what a shell-code default means on this computer (the resolved path, with *Installed* or *Not
  installed yet*), and the data, results and log folder fields say what leaving them empty does.
  `test/test_webui_databases.py` covers it.

### Fixed -- smaller findings of the end-to-end review
- The ranked CPRR registry row pointed at the pooled rate (`cprr`); the ranking metric is the per-isolate CPRR, so it now points at `cprr_isolate_mean`. `test_metric_registry.py` now cross-checks the registry against the scorecard for source and column (it checked only the id sets), so the two cannot drift apart.
- `test_tool_validation_tiers.py` accepted any record file containing the tool's name and the text 'pass' (so 'bypass' counted); it now needs a row for the tool whose status is exactly `pass`. The real-binary checker catches a tool timeout and still writes its summary row. `database_registry` in the manifest survives a malformed registry row. The documentation says that 'recorded' means recorded in the registry, not that this run used that database.
- The recommendation evidence panel said 'Expected performance' for the cohort's in-sample mean F1 and did not say that the recommender evaluation had found no gain from recommending per isolate; it now says 'Observed performance (this cohort)' and names the verdict.
- The radar and the complexity figure repeated colours after eight tools; the ninth and later tools now differ by line dash or marker shape. The maps' legends say what they leave out (genes across the origin, identity from the 300 longest blocks in the viewer). `plasbench analysis` lists `characterise-dataset`, `truth-marker-overlap` and `database-provenance`, which could not be re-run standalone.
- The new settings are in the Scientific guide's settings tables and the README (they were in prose only).

### Fixed -- AMR context follows CPRR's identity rule and never mistakes a draft for curated truth (end-to-end review)
- AMR-PRR used the CPRR table's identity-inclusive verdict for every isolate; on isolates whose truth was polished with the benchmark's own reads it now uses the verdict without the identity criterion, like CPRR (`collect --truth-provenance`, new gene-copy column `plasmid_cprr_correct_no_identity`).
- The scorer read `truth_amr.tsv` by filename only, so `cp truth_amr.draft.tsv truth_amr.tsv` made auto-derived rows count as curated despite the promotion gate. Each gene copy now carries its `truth_evidence_tier`, a warning is printed, the summary counts `draft_truth_copies`, and the report shows an *Uncurated truth* caution above the AMR table. The report text no longer hard-codes '1 kb' for the flank: it names `AMR_FLANK_BP`.

### Fixed -- the burden columns (end-to-end review)
- `ambiguously_mapped_pred_bp` was written as 0 when the ambiguity alignment was not made (`REPORT_MAPPING_AMBIGUITY=0`, or the secondary alignment failed), so the leaderboard showed 0.0% 'multi-mapped' for bases nobody checked. It is now blank (an empty alignment file is still a real 0), so the leaderboard shows blank, the perfect-recovery label stays 'not assessed' instead of being awarded, and the drill-down treats a blank as 0 only for its sums.
- The metric was described as bases 'with an alternative placement' in the registry, glossary, heatmap and report, but it counts mapped bases that align to BOTH a plasmid and a chromosome; the report header also used predicted bases as its denominator while the code divides by mapped bases. All texts now say what is counted (the heatmap column is *Plasmid+chromosome share*), and the burden shares need all three parts (mapped, unmapped, off-truth) or are blank instead of silently shrinking the denominator.

### Fixed -- SV-PRR now follows CPRR's identity rule (end-to-end review)
- SV-PRR used the CPRR table's `correct` (identity criterion included) for every isolate, while the leaderboard's CPRR drops the identity criterion on isolates whose truth was polished with the benchmark's own reads; on those isolates SV-PRR fell below CPRR for a reason that had nothing to do with structure, and the two were printed side by side. The structural step now writes `sv_prr_correct_without_identity` too, and the aggregation chooses per isolate by the same rule as CPRR (`headline_design.cprr_counts`). Because structural calling can fail for an isolate that CPRR still includes, the leaderboard gains `sv_prr_isolates` and `cprr_on_sv_isolates` (CPRR over exactly the isolates SV-PRR covers), and the leaderboard line and the report cell print that comparison instead of an unmatched pair.

### Fixed -- the recommender comparison's verdict rule (end-to-end review)
- An arm 'added value' on any positive gain, however small, counting a study of one isolate like a study of fifty. It now needs a mean-regret drop of at least 0.01 (`MIN_IMPROVEMENT`), a majority of at least three studies that each have two or more held-out isolates, and, for the feature-conditioned arm, at least half of the held-out isolates actually placed by their neighbours (`MIN_FEATURE_SHARE`). With no dataset features at all the arm silently equalled the single best and read 'no better'; it is now 'not assessed' with the reason, and `recommender_arms.tsv` gains `n_feature_based` and `share_feature_based` (shown as *Placed by neighbours*). The arms table now has a Not-run state when the file is absent.

### Added -- the missing half of plan A9 (end-to-end review)
- Rank sensitivity gains the `audit_clean_only` cohort variant: the ranking with isolates the truth-label audit flagged anything in left out, using the same `audit_sample` function and size thresholds as the audit table (the plan asked for sensitivity with and without exclusion; only the audit existed). `multi_replicon_plasmid` is documented as the noisiest flag. A malformed `tool_database_pattern` in `config/truth_marker_databases.tsv` now stops with a message naming the marker instead of a traceback.

### Fixed -- rank sensitivity (end-to-end review)
- The scoring-setting sweeps re-score base-level F1, and the docstring called F1 the leaderboard's ranking; it now says what the sweeps cover (base level) and where the fragility of the reconstruction headline is read (`metric:lw_bin_f1`, `cprr@t`). The `cprr@t` rows were compared with a literal 0.95 and labelled pre-registered even when `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE` were set differently: the baseline is now the configured threshold, and no sweep is written when the configuration is not on the grid. A setting variant equal to the configured setting (`min_length=500` with `MIN_ALIGNMENT_LENGTH=500`) is skipped instead of repeating the baseline, and a baseline that silently fell back to another truth scheme now warns.

### Fixed -- the primary analysis and the settings behind it (end-to-end review)
- The primary analysis was 'available' with a single tier-1/2 isolate, which has no interval and no test. It now needs references from at least `HEADLINE_MIN_CLUSTERS` (default 5) independent clusters; below that it is unavailable with the reason named. `HEADLINE_MAX_REFERENCE_TIER`, `HEADLINE_MIN_CLUSTERS` and `ALLOW_PRIMARY_FALLBACK` now have pre-registration rows (they could be changed in the environment unnoticed) and are defined in `config/config.sh`.
- `run_manifest.json` now records `RUN_STATS_VALIDATION`, `STATS_VALIDATION_MODE`, `CHROMID_MIN_BP`, `LARGE_PLASMID_BP`, `AMR_FLANK_BP`, `RUN_RANK_SENSITIVITY`, `ALLOW_PRIMARY_FALLBACK` and `HEADLINE_MIN_CLUSTERS`, so a run that changed a headline, a flag or an AMR number can be reproduced from its manifest. `RUN_RANK_SENSITIVITY` was only defaulted inside a stage script, so the setup window and `local.env` could not show it; it is now in `config/config.sh`, with a comment for every new setting.

### Fixed -- statistics (end-to-end review)
- A NaN difference gave a permutation p-value of about 1e-4 (`abs(x) >= nan` is false for every permutation) while the table called it exact; a NaN now gives no p-value and no interval (`not_estimated`) in the paired, stratified, bootstrap and ratio-bootstrap functions, and `permutation_method` says `not_estimated` with it. The literal 5 minimums are now the named constants.
- `underpowered` could never fire (a floor of at least 0.03125 is never above 0.05) and ignored that significance is judged after Holm over all comparisons. It now uses the smallest Holm-adjusted p a comparison can reach, m times its floor, written as the new last column `holm_min_attainable_p` of `benchmark.paired_comparisons.tsv`; the report's note says it. Stale 'five units / five shared samples' texts now say six independent units for a test.

### Fixed -- the recommender's 'truth-free' assembly features came from the reference (end-to-end review)
- `assembly_stats.tsv` is measured on the REFERENCE (stage 2): its contig count is the number of replicons and its size includes the true plasmids, so GC, N50, contig count and size were truth-derived while documented as the isolate's own assembly. An operational isolate has no such file, so those features were imputed at prediction time. They are now measured on the isolate's own contigs (`data/<sample>/contigs.fasta`) and named `input_gc_percent`, `input_n50`, `input_contig_count`, `input_assembly_size_bp`; the reference-derived names are forbidden (`TRUTH_DERIVED_FIELDS`), so a model fitted on them is refused at load and must be refitted (`plasbench` says which feature). `recommendation_model.TRUTH_FREE_FEATURES` is now an allowlist that `fit_feature_spec` asserts, in addition to the forbidden list. `select_unknown_sample.py` gains `--assembly` (contigs FASTA). The dataset-characterisation table, the feature-conditioned arm and the complexity figure use the same truth-free columns, and a test checks that no truth-free column is read from a reference-derived file. `compute_assembly_stats.scan_fasta` counts bases with `str.count` (same numbers, several times faster).

### Changed -- integration audit (plan F)
- `test/test_integration_audit.py` checks, in one place, what the release added against what it must be wired to: every CLI command is in the setup window's categories and documented in the README; every config setting a pre-registration row names exists in `config/config.sh`; every figure has help text, a layout label and a place in the Figures order; every glossary term used by the registry exists; every new report feature is in the feature manifest; `plasbench ui` lists every command (it is generated from the parser).
- Gaps the audit found and this release fixes: `promote-amr-truth` was missing from the window's categories; `collect-truth-provenance`, `discover-design-cohort` and `candidate-dataset` were in no documentation; `AMR_FLANK_BP` had a pre-registration row but no `config/config.sh` setting; the new report features had no feature-manifest rows.

### Added -- real-binary checks, database provenance and tool validation tiers (plan E1-E3)
- **E1** `.github/workflows/real-tools.yml` (weekly and on request, never on a pull request) runs the REAL MOB-suite, Platon and plasmidSPAdes on a known plasmid and passes the output through the real adapters (`test/real_tools/check_real_tool.py`): exit codes, the adapter contract, contig naming (every predicted record and bin member must be a contig of the input, for tools whose output is a subset of it), the bins table, a missing database named before the tool runs, and a known-output floor (`test/real_tools/expected.tsv`, 0 = recorded, not yet enforced, until the first reviewed run). `test/test_real_tool_checks.py` tests all of it offline against stand-in output through the real adapters. Not run here: the real binaries; the first scheduled run will be their first test.
- **E2** `config/tool_database_releases.tsv` gains `database_version`, `source_url`, `database_checksum_sha256` (versions and sources only where the registry already named them; every checksum is blank until filled from a real download). `python/database_provenance.py` computes the provenance status (recorded, partly, unrecorded, not applicable), writes `benchmark.database_provenance.tsv` (stage 6), records the registries in `run_manifest.json` (`database_registry`) and prints a checksum of a database file or folder. The report shows *Tool and database provenance* in *Truth plasmids in tool databases*.
- **E3** `config/tool_capabilities.tsv` gains `validation_status` (real_binary_checked, adapter_tested, untested, not_applicable) and `validation_evidence`. `test/test_tool_validation_tiers.py` checks every claim against its evidence file and fails when a tool is added at the untested tier without being acknowledged, so no adapter ships unvalidated by accident (plassembler is the one acknowledged). The tier is shown beside the database in the report. `adapters/REGISTRY.md` documents the tiers and the interface a tool must meet.

### Added -- AMR plasmid context and a gated truth-promotion step (plan B4)
- `score_amr_placement.py` adds, beside the placement and never ranking a tool: **flank context** (share of the 1 kb either side of a recovered copy that the same record covers), **co-localisation** (recovered copies on one plasmid kept in the same bin) and **AMR-PRR** (plasmids with a curated AMR copy whose copies are all on the right plasmid and that were reconstructed correctly; `amr_complete_rate` is the same without the CPRR condition). New gene-copy columns `flank_covered`, `plasmid_cprr_correct`; new summary columns `n_amr_plasmids`, `amr_complete_rate`, `amr_prr`, `n_pairs`, `n_colocalised_pairs`, `colocalisation_rate`, `flank_context_rate`. Stage 5 passes `--cprr`; `AMR_FLANK_BP` sets the flank (pre-registration row `amr_flank_bp`, proposed).
- `python/promote_amr_truth.py` (`plasbench promote-amr-truth`): turns a reviewed `truth_amr.draft.tsv` into `truth_amr.tsv` only with `--reviewed-by`, `--confirm-reviewed` and the real `--database-version`; it validates the result, records reviewer, date and the draft's checksum, and refuses to overwrite without `--force`. `validate_amr_truth.py` now exposes `validate()` (same checks and messages).
- Report: five new columns in *AMR genes on the right plasmid*, registry rows, glossary terms and help text; without curated truth the section still says Not run.

### Added -- figures: complexity, outcome matrix, recommendation evidence, map identity and resistance brackets, TP/FP encodings (plan D3-D7)
- **D3** new figure `fig-complexity` (*Figures*): per analysis track, base F1 of each tool on each isolate against the isolate characteristics of `benchmark.dataset_features.tsv` (plasmids in the truth, largest repeat fraction, contigs, read depth), each marked as knowable without a reference or needing it; Spearman correlation per tool only with at least five isolates and some spread, otherwise 'not computed'.
- **D4** the plasmid matrix gains, under each track's coverage table, an outcome table (perfect, partial, fragmented, merged, fragmented and merged, missed; a tool that wrote no bins is 'not assessable', not a miss).
- **D5** the *Recommendations* section gains an evidence panel (`report_recommend_evidence.py`): expected performance, independent studies, reference quality, dataset similarity and whether choosing by similar isolates beat the single best, uncertainty, and the reason when nothing is recommended or the headline is provisional.
- **D6** the circular plasmid maps (static and the interactive viewer, kept in parity by `test/test_map_rings.py`) shade each tool ring's covered stretch by alignment identity (four blue bands) and bracket resistance regions (truth resistance genes within 5 kb) outside the scale; legends updated; the viewer payload gains `rz`. The viewer holds at most 300 blocks per tool and plasmid, so its identity can differ slightly from the static map when blocks were omitted.
- **D7** the 3D landscape can size and colour points by true-positive or false-positive bases (new run fields `tp_bp`, `fp_bp`), reading it as a true/false-positive scatter of the runs; no new 3D code.

### Added -- a radar fingerprint of each tool (plan D2)
- New figure `fig-radar` (*Figures*, beside the tool heatmap): one radar per analysis track, one polygon per tool, seven axes (accuracy F1, recovery, CPRR, SV-PRR, verified sequence = 1 - unmapped share, runtime score, reliability). It is a view over the heatmap's own data (`report_fig_radar.py` calls `report_fig_heatmap.build`, which is now kept for the report), validates its axes against `config/metrics.tsv`, skips an axis that is not available instead of drawing 0, and carries the numbers in a table. Help text, glossary term, layout, wiring and `test/test_report_fig_radar.py`.

### Added -- the numeric tool x metric heatmap carries the new metrics (plan D1)
- *Performance of every tool across every metric* (figure `fig-heatmap`, one block per analysis track, numbers in the cells) gains five leaderboard columns: SV-PRR, the unmapped, off-truth and multi-mapped predicted-base shares and the precision gap. The shares and the gap are marked lower-is-better (colour flipped); every column has a per-isolate drill-down derived from `scores.tsv`, and a blank stays 'not available', never 0. No new figure code: the existing heatmap reads the leaderboard.

### Added -- three-way recommender comparison (plan C2)
- `evaluate_recommender.py` now also compares, over the same leave-one-study-out folds, the single best tool, the organism recommender and a **feature-conditioned** arm (the best tool among the five most similar training isolates by the truth-free dataset features; a reference-derived column is refused). `benchmark.recommender_arms.tsv` reports per arm: regret, top-1 and near-optimal rates, improvement over the single best, the studies in which it beat it, calibration (error and bias), abstention and the regret when it would answer. An arm adds value only when it beats the single best on average and in most of at least three studies; the verdict JSON gains `arms` and `feature_conditioned_enabled`. The existing recommender outputs are unchanged. The arms table is in the *Recommendations* evaluation detail; `test/test_recommender_arms.py` is new.

### Added -- a dataset-characterisation table (plan C1)
- `python/characterise_dataset.py` composes the per-isolate measurements the pipeline already makes (assembly stats, read depth and quality, repeat content of the truth, difficulty signals, organism and Gram group) into `benchmark.dataset_features.tsv`; it measures nothing itself. Every column is marked truth-free (knowable for an isolate with no reference) or truth-derived (benchmark only); a value not measured is blank, never 0. `test/test_dataset_features.py` checks the truth-free columns never include a field the recommender forbids.
- Stage 6 builds it (an advisory job) and the report shows it as *Dataset characteristics* in the *Isolate difficulty* tab, with each column's basis in its header; file-explorer entry, help text and glossary term.

### Added -- SV-PRR, CPRR with the structural calls beside it (plan B3)
- `call_structural_variants.py` now counts, per tool and isolate, the CPRR-correct plasmids that no structural call touches (`sv_prr_correct` / `sv_prr_plasmids` in `structural_summary.tsv`); `merge_bin_metrics.py` carries them into `scores.tsv`; the leaderboard gains `sv_prr`, `sv_prr_correct`, `sv_prr_plasmids` (appended last). CPRR itself, its definition and every rank are unchanged; SV-PRR is reported, never ranked, and as unvalidated as the calls (no read or graph support).
- Report: the CPRR cell of the leaderboard shows SV-PRR; a glossary term, a registry row, a pre-registration row (`sv_prr_use`) and column groups in the explorer. `test/test_sv_prr.py` is new.

### Added -- the burden of unverified predicted sequence reaches the leaderboard and the report (review, plan B2)
- `score_plasmids.py` already wrote `unmapped_pred_bp`, `off_truth_pred_bp`, `mapped_pred_bp` and `ambiguously_mapped_pred_bp`, but the aggregation dropped them. The leaderboard gains (appended last, pooled over the isolates): `total_predicted_bp`, `total_unmapped_pred_bp`, `total_off_truth_pred_bp`, `total_ambiguous_pred_bp`, `unmapped_fraction`, `off_truth_fraction`, `ambiguous_fraction` (the multi-mapping burden) and `precision_gap` (permissive minus strict precision). A column the scores do not carry is blank, never 0. The ambiguity alignment is already on by default (`REPORT_MAPPING_AMBIGUITY=1`).
- Report: four columns in *Ranking confidence* (unmapped, off-truth, alternative placement, precision gap), four registry rows (`config/metrics.tsv`), a leaderboard column group in the file explorer, a glossary term and help text. `test/test_burden_columns.py` is new.

### Added -- a metric registry and the evaluation ladder (plan B1)
- `config/metrics.tsv` and `python/metric_registry.py`: every metric with its ladder rung (detection, sequence recovery, binning, sequence reconstruction, biological validity; computational efficiency beside it), the tool types it applies to, its inputs, whether it ranks tools, its evidence grade (published definition / defined by PlasBench / unvalidated estimate / not available), the table and column that hold it, its scorecard id and where it is shown. The glossary keeps the wording of each definition (no second copy); the registry is the metadata, cross-checked by tests.
- Report: the *Classification and reconstruction metrics* section carries the registry-driven **reconstruction evaluation ladder** and states its gaps (no ranked metric on the sequence-recovery or biological-validity rungs; nothing on biological validity rests on a published definition); the glossary table gains *Ladder rung* and *Use* columns; a help entry and a glossary term. `test/test_metric_registry.py` (validation, glossary, scorecard and endpoint cross-checks) and `test/test_metric_wiring.py` (the demo's leaderboard and scores columns, the report sections, the glossary, the ladder and the docs) are new.

### Added -- more truth audits (review H3, plan A9)
- `python/audit_truth_labels.py` adds a `flags` column (the `finding` column is unchanged): `integrated_plasmid_candidate`, `chromid_candidate`, `secondary_chromosome`, `large_plasmid`, `multi_replicon_plasmid`, `marker_free_plasmid`, `multimer_<k>x` (from `truth.corrections.tsv`) and `collapsed_repeat_candidate` / `low_depth_region` (from the depth-anomaly summary). The size thresholds are `CHROMID_MIN_BP` (350 kb) and `LARGE_PLASMID_BP` (500 kb), config variables and pre-registered as proposed.
- `python/detect_dimers.py` detects higher multimers (up to 6 tandem copies): a new `copies` column, a collapse keeps the first 1/k, and a tetramer is reported as 4, not 2.
- `python/truth_marker_overlap.py` writes `benchmark.truth_marker_overlap.tsv` from `config/truth_marker_databases.tsv` and `config/tool_database_releases.tsv`: which tools share a database with the evidence that labelled the truth (`yes` / `possible` / `no` / `unknown`; MOB-suite tools share the MOB-typing evidence). A name-level screen.
- Report: the *Truth labels* tab gets a Flags column, flagged-only rows and a *Marker databases shared with benchmarked tools* table (with a Not run state); help text, a glossary term, a file-explorer entry and feature-manifest rows. Stage 6 and the demo run the new steps. `test/test_truth_audits.py` is new.

### Changed -- the ranking-sensitivity analysis covers the headline endpoints and the alignment length (review C6 / H1, plan A8)
- `python/rank_sensitivity.py` adds: a minimum-alignment-length sweep (`min_length=100`, `min_length=500`; the pre-registered value is 200); the headline short-read endpoint (`metric:lw_bin_f1`) and the 50% recovery band (`metric:plasmid_recall_ge50`) as alternative rankings; and CPRR re-ranked at coverage/bin-share thresholds 0.80, 0.90, 0.95 and 0.99 (`cprr@...`, read from `benchmark.cprr_threshold_sweep.tsv`; compared with the pre-registered 0.95 ranking). The table gains a last column `compared_with` (the F1 `baseline`, or `cprr@0.95`), and the report's *Filter and metric sensitivity* table shows it. Existing columns and variants are unchanged. `test/test_rank_sensitivity.py` is extended.

### Fixed -- a run never stops silently
- **Every way a stage can stop is reported on the console, in red, and in `logs/run_errors.log`.**
  - A command failing under `set -e` without a message of its own now prints which script stopped, the command, the
    exit code and what it usually means. Before, the stage just ended.
  - A stage stopped by a signal says so: Ctrl+C, a closed terminal, Cancel in the window, or SIGTERM from the system.
  - A stage killed outright by SIGKILL, which is what the out-of-memory killer sends and cannot be caught, is
    reported by `run_all.sh`: `the run stopped in stage 3 (03_assemble.sh): killed (SIGKILL): usually out of memory,
    or WSL or the system ended it`. `run_all.sh` used to end without a word when a stage failed.
- **A run cut off with no chance to report** (WSL or the computer stopping) is reported by the next run: `the
  previous run stopped before it finished ... (started <time>, stage 3 ...)`, with a note that finished work is reused.
- **The `plasbench` command** explains a death by signal when the pipeline itself was killed. **The window**
  appends to the job's console how and why the command stopped, for example `killed (SIGKILL): usually out of
  memory`, so a failed job never ends on a blank line.

### Changed -- the sample report link is at the top of the README
- A link to open the sample HTML report (online preview; a relative path for a clone) now sits directly under the README title, not only in the report section. GitHub removes `target="_blank"` from README links, so the link says to Ctrl/Cmd-click or middle-click to open it in a new tab. `test/test_sample_report.py` keeps it there.


### Added -- statistics validated by simulation (review C4 / C6, plan A7)
- `python/simulate_validation.py` (also `plasbench analysis simulate-validation`) simulates paired differences with study effects, correlated isolates, unequal study sizes and missing observations and runs the real `resampling.bootstrap_ci` and `resampling.paired_permutation_pvalue` on them, writing `benchmark.stats_validation.tsv`: interval coverage (nominal 95%) with its standard error, the rejection rate at 0.05 (type-I error at effect 0, power above it), how often each could be estimated, the test method and a verdict that never rounds a shortfall up. `smoke` mode (100 replicates, seconds, indicative) and `full` mode (1,000 replicates and the production resampling counts, minutes) share one seed. Stage 6 runs it when `RUN_STATS_VALIDATION=1` (`STATS_VALIDATION_MODE`); the demo runs smoke mode. The report gets a *Statistical validation (simulation)* tab under Sensitivity, power and reproducibility (with an explicit Not run state), a help entry, a glossary term and a file-explorer entry. **First finding:** the percentile cluster bootstrap under-covers with few studies (coverage roughly 0.85 to 0.94 across the smoke scenarios, mostly below 0.95), so its intervals are optimistic for cohorts of that size; the sign-flip test kept type-I error near 0.05. `test/test_simulate_validation.py` covers the generator, the verdicts, the command, the report section and the wiring.

### Changed -- permutation tests need six independent units and are exact for small designs (review C4, plan A6)
- `python/resampling.py`: named thresholds `MIN_CLUSTERS_CI` (5), `MIN_CLUSTERS_TEST` (6) and `EXACT_MAX_UNITS` (12). A sign-flip test with five units can never report p below 0.0625, so it is no longer reported (six units give 0.03125). Up to 12 independent units every sign pattern is enumerated (an exact p-value in integer arithmetic, no random numbers; the stratified test enumerates the macro-mean the same way); above 12 the Monte Carlo estimate is unchanged, with the same random stream. `permutation_method` and `permutation_floor` expose which applies and the smallest attainable p. Bootstrap intervals still need five units.
- `benchmark.paired_comparisons.tsv` gains `permutation_method` (exact / monte_carlo / not_estimated), `min_attainable_p` and `p_status` (ok / underpowered / not_estimated), appended last. The report's paired-comparison table gets a *Permutation test* column ("exact, smallest attainable p 0.03125", "underpowered: cannot reach 0.05"). The thresholds are pre-registered rows. `test_resampling_equivalence.py` compares the exact path with an independent enumeration and keeps the Monte Carlo path bit-identical above 12 units; `test/test_permutation_reporting.py` is new.

### Changed -- the pre-registration is a draft until its proposed values are confirmed (plan A5)
- `config/prereg.tsv` gains a status, `proposed`: a value is proposed (rationale in the note) and awaits the maintainer's confirmation. The rows that were `TO_FIX` with a proposed default (the tool timeout, now proposed at 7200 s with its rationale; the integrated-element depth; the circular-path rule; the scorecard weights and bands; the scorecard minimum; the map size) are `proposed`; the A4/C2 bands, which have nothing to propose, stay `TO_FIX`. `min_alignment_length` (200) is now a pre-registered row.
- `freeze_prereg.py`: `proposed` and `TO_FIX` are *unfixed* and make the plan a **draft**; `--status` reports `proposed` and `draft`; a draft can be locked with `--write` (so a run records which draft it used) but `--strict` refuses to write it and fails `--verify` (`--require-fixed` now also fails on proposed rows). The manifest and the report's Pre-registration tab show the draft state ("frozen and unchanged, but a DRAFT: N value(s) ...") and list the proposed rows. `REQUIRE_PREREG=1` is unchanged in intent: it refuses a draft. `test/test_prereg_freeze.py` covers it. Nothing is frozen: confirming the values and freezing is the maintainer's decision.

### Changed -- stage 2 (truth) is faster, parallel, resumable and says where its time goes
- **Each sample's stage-2 steps are timed.** The times go to `data/<sample>/stage2_timing.tsv`, and the log names
  every step that took 10 s or more, for example `stage 2 for S1 took 21m05s: annotation 20m31s, repeat_content 14s`.
- **Samples run in parallel** with `MAX_PARALLEL_SAMPLES`, the same setting as stages 1, 3, 4 and 5. The default, 1,
  stays sequential. An unusable truth table still stops the stage, and the stop names the sample.
- **Reference annotation** (`RUN_REFERENCE_ANNOTATION=1`) runs its callers at the same time, instead of one after
  another, and gives them threads. ISEScan, the slowest by far, gets the whole `THREADS` allowance instead of 1;
  AMRFinderPlus gets half; MOB-typer, abricate and barrnap share a few.
- `measure_depth.py` counts both mates at the same time, decompresses with pigz/gzip in a separate process, and
  touches only the sequence lines, in C. That is about 2x faster on a 90x read pair, with identical counts.
- `repeat_content.py` slices k-mers in C instead of looping over every base in Python. That is 1.5x faster on a
  5 Mb genome, with identical output.
- `mash dist` (evidence labels) and `samtools sort` (depth anomalies) use `THREADS` instead of 1 and 2.
- **Re-runs reuse** repeat content and the depth-anomaly scan when their inputs have not changed, instead of
  recomputing them every time.

### Fixed -- a run cut off during assembly resumes cleanly
- **Stage 3 is crash-safe.** fastp now writes `*.trim.partial.fastq.gz` and renames the pair only when it succeeds;
  a `.fastp.complete` marker records a finished trim. Trimmed reads left by a run that was cut off (a full disk, WSL
  or the machine stopping) used to be taken for finished reads and assembled truncated; they are now trimmed again,
  with a log line saying so. An interrupted SPAdes/Unicycler folder is cleared before reassembling, and the contigs
  and graph are copied under `.partial` names first, so a half-copied `contigs.fasta` is never reused. Finished work
  is still reused, including samples trimmed and assembled by an earlier PlasBench.

### Changed -- warnings are yellow and errors red, in the window and in a terminal
- **The window's console** uses one colour code in all three tabs (Job output, Session log, Terminal): errors are
  red and bold, with a red bar in Job output, and warnings are yellow. A line PlasBench tags `WARNING:` (for example
  a tolerated `SPAdes failed for ...`) is yellow; `ERROR:`, tracebacks, `No space left on device`, `command not
  found` and non-zero exits are red. A success line that mentions a failure (`... -> PASS`) and zero counts such as
  `failed=0` are not flagged. The Terminal tab now colours command output, and the Session log shows failed jobs and
  terminal commands red, cancelled or interrupted ones yellow.
- **Runs in a terminal** print `WARNING:` lines yellow and `ERROR:` lines red (`scripts/lib.sh`), only when the
  output is a terminal, so log files stay plain. `NO_COLOR` or `PLASBENCH_COLOR=never` turns colour off, and
  `PLASBENCH_COLOR=always` forces it.

### Changed -- heavy files never go into git, and you can edit .gitignore from the window
- **One catalogue of heavy formats** (`plasbench/gitops.py`, `HEAVY`) drives both the managed `.gitignore` blocks and
  the commit check, so the two cannot drift apart. It covers:
  - reads (FASTQ, also bzip2/xz/zstd-compressed; SRA; nanopore FAST5/POD5/BLOW5);
  - alignments and their indexes (BAM, SAM, CRAM, BAI, CRAI, CSI, PAF);
  - variants (VCF, BCF, TBI);
  - coverage tracks (bigWig, bedGraph);
  - aligner indexes and tool databases (minimap2, Bowtie2, BWA, Kraken2, Mash, DIAMOND, BLAST, HMMER, SQLite, HDF5,
    model files);
  - archives (tar, zip, 7z, bz2, xz, zst);
  - in study repositories, assemblies and sequences (FASTA, GenBank, GFF, GFA).
  Previously SAM was missing from the developer rules, and VCF, CRAM/BAM indexes, nanopore signal, indexes, databases
  and archives were not covered at all.
- **Repositories set up by an earlier PlasBench get the new rules**: the managed block is brought up to date, and
  lines outside it are never touched.
- **Heavy files already committed** (before a rule covered them) are listed on Version control, with **Stop
  tracking** (`git rm --cached`: the files stay on disk).
- **Edit `.gitignore` in the window** (Version control > Ignored files). PlasBench's block is shown read-only. Your
  own rules are editable and come after it, so `!results/key_plasmids.fasta` brings back a file the block leaves
  out. **Test a path** shows whether a file is ignored and by which rule. A sequence file you keep with your own rule
  is a warning at commit time. Reads, alignments, variants, indexes and archives stay blocked whatever the rules say.

### Added -- a structured evidence record for every reference (review H3)
- `python/truth_provenance.py` records six evidence fields per reference, additively: assembly technology, circularity evidence, read support, replicon/MOB evidence, structural integrity and independent validation, each `declared` (new optional sample-sheet columns `truth_circularity_evidence`, `truth_read_support`, `truth_structural_integrity`, `truth_independent_validation`), `inferred` (NCBI metadata, `truth_labels.tsv`) or `unknown`; plus `evidence_recorded` and `evidence_sources`. The original columns keep their order. Unknown never demotes a reference; an explicit adverse value (read support none, unresolved repeats) caps Tier 1 at Tier 2 and says why. `validate_cohort.py` checks the new vocabularies; the headline design table gains an *Evidence recorded* column; the demo declares some evidence and now builds the provenance table before aggregating (so the headline and the report read the same references). `test/test_truth_evidence_record.py` covers it. The cohort `truth_quality_tier` column is kept for now: it still feeds the tier and replacing it needs the cohorts re-curated (maintainer-owned).

### Changed -- the primary analysis is unavailable, visibly, when no reference qualifies (review E27 / H4)
- `headline_design.Design.headline_selection` replaces the silent fallback to all samples. With no reference in tiers 1-2 (or no provenance table) the **primary analysis is unavailable**: the same numbers are computed on all samples but labelled provisional. New append-only leaderboard columns `primary_status` (`available` / `unavailable` / `fallback_allowed`) and `population`; `primary_status` in `benchmark.headline_design.tsv`; a PROVISIONAL banner in the markdown leaderboards; a stdout warning; and in the HTML a banner above the ranking, a "Leading method (provisional)" tile, a "Primary analysis unavailable" finding, and a Primary analysis column in the headline design table. `--allow-primary-fallback` / `ALLOW_PRIMARY_FALLBACK=1` (default off) keeps the numbers as the headline with the warning. An older leaderboard without the columns is read as available. `test/test_primary_eligibility.py` covers the design, the aggregation and the report; the review ledger rows (E26-E29) are re-pointed and E27 is marked fixed. **Public-v3 and the demo are in the unavailable state** (no Tier 1-2 reference / no provenance table).

### Fixed -- the recommendation model used truth-derived features
- `python/recommendation_model.py` fitted its ridge model on the truth's plasmid size and plasmid count and on the truth's AMR annotation, which are unknown for an isolate with no reference (they were imputed with the training mean there), so the model could learn the answer in a retrospective run. The inputs are now truth-free only: read depth, the isolate's own assembly statistics, tool, organism and Gram group. `TRUTH_DERIVED_FIELDS` lists what is barred, `assert_truth_free` enforces it when fitting, and `load_model` refuses a ready model whose spec used one (with the reason and the refit instruction); older specs still decode. `test/test_recommender_truth_free.py` covers it.

### Added -- reference figures folder (planning for v0.4.0)
- `docs/images/reference/README.md` (tracked) maps four third-party reference figures to the report features they inspire (map identity rings and resistance-region brackets, numeric heatmap, true/false-positive 3D scatter, radar fingerprint). The images are gitignored and not shipped. `test/test_reference_images.py` keeps the README and the ignore rules in place.

### Added
- **Study folders.** Every benchmark keeps everything it produces in its own folder, `<workspace>/<study>/`
  (results, report, logs, tmp and a `study.json` recording the sample sheet with its checksum, the cohort and every
  command). `plasbench run` names the study after the cohort or sample sheet, or `--study NAME`;
  `plasbench report --study NAME` rebuilds one. The workspace is `PlasBench/studies` by default, or
  `PLASBENCH_WORKSPACE`. Downloads, tool environments and databases stay shared between studies.
- **The window: Workspace & studies.** Choose and check the workspace (writable, free space, drive type, cloud-sync
  and long-path warnings; a missing chosen folder is reported, never silently replaced), recent workspaces, every
  study with its report and folder, and New study. The New benchmark wizard shows and names the study folder.
- **The window: Version control.** Git without the command line, after GenoSuv's design: status, staging, diffs,
  commit, branches, remote, fetch/pull/push (as console jobs) and history, for the PlasBench folder or the
  workspace. A managed `.gitignore` block keeps studies, results, downloads, reads and credentials out; every commit
  is scanned (reads and run folders, `config/local.env` with the NCBI API key, tokens, files over 100 MB); remote
  addresses may not carry credentials; nothing is force-pushed; AI co-author trailers are removed.
- **PlasBench starts like a desktop program.** The installer adds a PlasBench icon to the desktop and the
  applications/Start menu (`plasbench desktop-icon`; `--remove`, `--no-desktop`; `install.sh --no-icon` skips it).
  On Linux it is a `.desktop` entry, on macOS `~/Applications/PlasBench.app`, and on Windows, with PlasBench
  installed inside WSL2, a Windows shortcut that starts PlasBench in Ubuntu. Clicking it runs
  `scripts/plasbench_launcher.sh`, which activates the `plasbench` conda/mamba/micromamba environment and starts the
  window. A second click brings the running window back (one server per PlasBench folder, recorded in
  `~/.plasbench/ui/server.json`). The window opens as an app window (Edge/Chrome `--app`; `plasbench ui --tab` for a
  browser tab). **Quit** in the window stops PlasBench, and asks first if a job is still running.
- **The PlasBench logo and icon.** A plasmid map holding three rising benchmark bars (`plasbench/data/logo.svg`,
  `docs/images/plasbench-logo.svg`, `docs/images/plasbench-icon.svg`). It appears in the window's app bar, as its
  favicon, as the desktop icon (PNG/ICO/ICNS drawn from the same geometry, nothing downloaded) and at the top of the
  README.
- **A terminal in the window's console.** The console stays fixed at the bottom of the window and now has two tabs:
  **Job output** and **Terminal**, after GenoSuv's design. The Terminal runs your own commands in the PlasBench folder,
  confined to it and the studies workspace. It offers the login shell (Linux, macOS), Ubuntu (WSL) or PowerShell
  (Windows), keeps a command history, and records each command. `plasbench` there runs this PlasBench folder.
- **Set up this computer → This computer.** Operating system, WSL, architecture, CPUs and RAM, conda and the
  `plasbench` environment, Docker. It also gives the recommended way to run PlasBench there (the conda environment,
  or WSL2 on Windows), the steps still to do, the warnings (Apple Silicon, low RAM, `/mnt/c` speed) and Docker as the
  alternative, with its command. The checklist also checks for the `plasbench` environment.
- **Side panel and main-area tabs.** **Panel** (top bar) opens a right-hand panel as wide as the navigation rail,
  with three tabs. **Studies** (the default) is a folder tree of the workspace's studies: reports open in a report tab,
  and tables, logs and text files open as read-only tabs. **Jobs** shows running and recent jobs with cancel. **Git**
  (Ctrl+Shift+G) has changes with stage/unstage, commit, branches, remote, tracked files and history.
  The main area works like a browser. It opens with an Overview tab, and every page you open is its own tab. Reports
  (with **Open in browser**; Ctrl+click opens the browser directly), files, diffs (line numbers, Stage/Unstage) and
  commits (files changed, parents, patch) open in tabs next to the current one. Tabs close with × or a middle-click,
  and the last one closed brings back Overview.
- **Git history is colour-coded**: the commit you are on, pushed, not yet pushed, and merge commits, with branch and
  tag labels. Hovering a commit shows its author, date, labels and whether it is pushed; clicking it opens it in a tab.
- **Version control tracks your runs, not the program: one repository per study.** Each study folder is its own
  repository, with its own history and remote. Its managed `runs` `.gitignore` keeps the study's record, tables,
  reports, figures and logs, and leaves raw sequence data (reads, assemblies, FASTA, alignments), tmp folders and
  credentials out. Studies show whether they are tracked, with a Git button on Workspace & studies and in the side
  panel. A new repository can no longer be started in the
  PlasBench program folder, and a workspace inside a program checkout is no longer mistaken for that checkout.
- **`plasbench install-git`** (optional; Set up → Git → Install). On Windows it installs Git for Windows with Git Bash
  through winget, and you answer any prompt in the console. Elsewhere it installs conda-forge git into the plasbench
  environment, or prints the system command.
- **The Terminal lists each WSL distribution by name**, plus Git Bash (never the WSL launcher) and PowerShell, and runs
  `git` in every shell. When WSL does not respond, it says so and suggests `wsl --shutdown`.
- **Session log and run script.** The console has a third tab, **Session log**. It shows, one line per event, what
  happened in the session: commands started from the pages and how they ended, answers, cancels, terminal commands,
  settings, workspace and study changes. Earlier sessions can be chosen too. **Save as script** downloads the session
  as a bash script that repeats it, with failed commands, PowerShell commands and answers as comments. The log is
  `~/.plasbench/ui/sessions.jsonl`; secret settings are never written, and hidden answers are masked.
- **Help on every page.** A Help button on each page header, the **?** in the top bar, and F1 each explain the page:
  what it is for, the steps, what is good to know, and the command-line equivalent. **Add your own tool** has a full
  guide (**How it works**) covering the form's five sections, placeholders and output formats. Its worked example
  adds MOB-recon as a user tool, and **Load this example** fills the form with it.
- **Cohort details.** On the Cohorts page, **Details** describes each shipped cohort, from its sheet, its lock and
  `cohorts/README.md`: isolates and species, plasmids in the truth, read depth, BioProjects, Illumina read volume and
  the download estimate. Breakdowns cover organism, truth tier, truth technology and strategy, origin, country and
  plasmids per isolate. A searchable sample table has NCBI links and, from the lock, host, isolation source,
  collection date and how the reference was sequenced and assembled. It also says whether the lock still matches the
  sheet. Metagenomic sheets show their communities, regimes and truth status (`plasbench/cohort_info.py`).
- **The window's console answers questions.** A command that asks (for example "Install the missing items now?")
  shows the question in the console, which highlights it; answer in the reply box or with Yes/No.
- **Reference figures folder (planning for v0.4.0).** `docs/images/reference/README.md` (tracked) maps four third-party reference figures to the report features they inspire (map identity rings and resistance-region brackets, numeric heatmap, true/false-positive 3D scatter, radar fingerprint). The images are gitignored and not shipped. `test/test_reference_images.py` keeps the README and the ignore rules in place.

### Changed
- **One `PlasBench` folder, updated in place.** `install_latest.sh` installs into `~/PlasBench` (or
  `$PLASBENCH_INSTALL_DIR/PlasBench`), and `update.sh` / `plasbench upgrade` update that folder instead of creating
  `plasbench-<version>` folders. Only files the previous release installed are replaced (`scripts/release_sync.sh`
  keeps a checksummed list; an edited release file is backed up to `.plasbench-backup/`); studies, settings, own
  tools, downloads, tool environments and databases are kept. An older versioned install is carried in: its runs
  move to `PlasBench/studies/`, its settings and own tools are copied, its downloads move to the shared folder once,
  and the old folder is deleted after confirmation (`--yes`, or kept with `--keep-old`).
- Script prompts print their question explicitly, so it is visible when the command runs from the window.
- `scripts/docker_run.sh` mounts the studies workspace (`PLASBENCH_WORKSPACE`, default `./studies`) at
  `/work/studies`, so a run in the container lands in the same study folder as a native run. An explicit
  `RESULTS_DIR` in the environment is honoured like `--results-dir`.
- The console is open by default (a quarter of the window) and remembers its height and whether you closed it.
- The fixed console never hides the end of a page: the page keeps a bottom margin as tall as the console, and
  scrolling to a field stops above it. The body was `height:100%`, so that margin used to end at the first screen.
- `test_install_latest.sh` follows the installer into the one `PlasBench` folder.
- The Terminal's command box is an expandable text area: one line by default, it grows as you type (Shift+Enter for
  a new line) and can be dragged taller.

## [0.3.0] - 2026-11-13

A feature release: benchmark your own tools without changing PlasBench's code, and do everything from a window in your browser with `plasbench ui`. No scoring, ranking or report change for the built-in tools. See the [release notes](docs/releases/v0.3.0.md). Compare: [v0.2.3...v0.3.0](https://github.com/ubeffiong/plasbench/compare/v0.2.3...v0.3.0).

### Added
- **The PlasBench window: `plasbench ui`.** Everything the command line does, from a page in your browser: a setup
  checklist with one-click fixes, NCBI credentials, the tool catalogue with installs and default switches, a form
  that writes and installs your own tool's manifest, every setting with its default (saved to `config/local.env`),
  a five-step New benchmark wizard, your own isolates, cohorts, runs and reports (open, PDF, rebuild), a job console
  with live logs and cancel, and every `plasbench` command as a form generated from the CLI parser itself. It is
  served only to this computer, with a per-session key, a Host-header check and same-origin POSTs, and it runs
  nothing but `plasbench` commands that the real parser has accepted. No network resources; light and dark themes.
- **Bring your own tool.** Any plasmid reconstruction or classification tool can be benchmarked without changing
  PlasBench's code: a `plasbench-tool.ini` manifest declares its task and track, how to install it (conda, pip, a
  script, or nothing), how to run it per sample (a command with `{contigs}`, `{graph}`, `{reads_1}`, `{long_reads}`,
  `{outdir}`, ... placeholders) or where its existing outputs are, and how to read its output (contig-bin table,
  contig labels with probabilities, plasmid FASTA, a folder of FASTA files, or its own adapter). New commands:
  `plasbench tools new|validate|list|show|add|install`, `plasbench install-tools NAME` and `plasbench run --tool NAME`
  (`USER_TOOLS` in the config). User tools share the built-in tools' timeouts, retries, outcome states, result reuse,
  leakage check, long-read circularity rule, scoring, ranking and report, and their manifest, checksum and version
  are recorded in `run_manifest.json`. Guide: docs/ADDING_TOOLS.md; examples: tools.d/examples/.

## [0.2.3] - 2026-11-13

A patch release: database downloads resume, `plasbench check` fetches Platon's database itself, RFPlasmid's CheckM starts again, and `plasbench test` passes on a release install. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.3.md). Compare: [v0.2.2...v0.2.3](https://github.com/ubeffiong/plasbench/compare/v0.2.2...v0.2.3).

### Fixed
- **MOB-suite and Platon database downloads resume.** A new `resumable_download` helper (`scripts/lib.sh`) keeps every byte already received, continues with `curl -C -` after a dropped connection or a re-run, pauses while the internet is down instead of spending retries, checks the size, and only then renames the `.part` file. `mob_init` cannot resume (it truncates its archive on every attempt), so PlasBench downloads MOB-suite's archive itself and hands `mob_init` the finished file as a `file://` mirror; `mob_init` then only unpacks and builds.
- **`plasbench check` downloads Platon's database** from its documented Zenodo file (1,690,687,855 bytes, size-verified) instead of asking for a URL.
- **RFPlasmid / CheckM start again.** CheckM imports `pkg_resources`, removed in setuptools 81; the `rfplasmid` profile now pins `setuptools<81`.
- **`plasbench test` passes on a release install.** The review-ledger test no longer fails on `.github/` files, which release archives do not ship (still checked in a git checkout and CI).
- MOB-suite database paths no longer show conda-forge's `lib/python3.1` alias in messages.

### Added
- README **Step 7d**: one-time setup for AMRFinderPlus (`amrfinder -u`), RFPlasmid's CheckM data and Plasmer's database (links, checksums, default folder, RAM check). The installer's closing message points to it.

## [0.2.2] - 2026-11-13

A patch release: the `trycycler` install no longer stalls. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.2.md). Compare: [v0.2.1...v0.2.2](https://github.com/ubeffiong/plasbench/compare/v0.2.1...v0.2.2).

### Fixed
- **Trycycler and Medaka install into their own environment, `plasbench-trycycler`.** Solving Medaka's PyTorch stack into the large main environment ran for 45+ minutes without finishing during `install-tools all` / `install_latest.sh --tools`; in a fresh environment the same packages install in about 4 minutes. Wrappers for `trycycler`, `medaka` and `medaka_consensus` go into the main environment; the main environment's own `flye` is left untouched.

## [0.2.1] - 2026-11-13

A patch release: `plasbench install-tools all` now completes. No scoring, ranking or report change. See the [release notes](docs/releases/v0.2.1.md). Compare: [v0.2.0...v0.2.1](https://github.com/ubeffiong/plasbench/compare/v0.2.0...v0.2.1).

### Fixed
- **PlaScope, Plasmer and PlasmidHunter install into their own environments.** None could be solved into the python 3.12 main environment: PlaScope's pinned Centrifuge 1.0.3 is built only for python <= 3.6, Plasmer only for python 3.10, and every PlasmidHunter release requires python 3.10. Each now lives in `plasbench-plascope`, `plasbench-plasmer` or `plasbench-plasmidhunter`, with wrappers in the main environment, as MOB-suite already does. You still only activate `plasbench`.
- PlasmidHunter is pinned (1.4) with `setuptools<81`, which it needs for `pkg_resources`; the installer now proves each isolated tool starts instead of only checking that its file exists, and rebuilds an environment that does not.
- Plasmer no longer pulls Anaconda's commercial `defaults` channel.


## [0.2.0] - 2026-11-10

A minor release: rankings, the recommendation output and some column names differ from v0.1.5, and the HTML report is rebuilt. Read **Upgrading from v0.1.5** in the [release notes](docs/releases/v0.2.0.md) first; everything below is the detail behind them. Compare: [v0.1.5...v0.2.0](https://github.com/ubeffiong/plasbench/compare/v0.1.5...v0.2.0).

### Changed -- the sample report is replaced by every demo run
- `test/run_demo.sh` (so `plasbench demo` and the demo tests too) ends by running `python/refresh_sample_report.py`, which replaces `docs/sample_report/benchmark.report.html` with the demo report just built. It is skipped, with a printed reason, when `docs/sample_report/` is absent, `PLASBENCH_SAMPLE_REPORT=0`, or the report is incomplete or holds a local path, and it never fails the demo. `test/test_refresh_sample_report.py` covers it.


### Added -- a download button per isolate in the plasmid matrix
- In *Which tool recovered which plasmid* (one table per analysis track) every isolate has a small **FASTA** button that downloads that isolate's best reconstructed
  plasmid(s): the selected candidate, `selected_candidates/<isolate>/<isolate>.candidate.plasmid.fasta`. The button works when the report is open from its results
  folder. When the report has been copied away, so the file cannot be reached, the button is **greyed out** and says why; an isolate with no selected reconstruction is
  grey from the start. Over http(s) the check is a HEAD request; from a local file the browser forbids reading files, so the file is requested as a script (it loads when
  the file exists and fails when it does not; the browser may log one harmless parse error per file in its developer console).
- The notes under the Summary's sub-headings (the plasmid matrix, the report card) are now hover tooltips like every other section note; only the Summary's own lead
  stays visible.

### Added -- a sample report in the repository
- `docs/sample_report/benchmark.report.html` is the report built from the offline demo (synthetic data, about 11 MB), with a README that says what it is, how to regenerate it and what differs from a real run. The project README links to it, with an online preview link. `test/test_sample_report.py` keeps the link, the file and its contents honest.

### Added -- a "?" help button on every section and tab
- Every section and every tab of the report has a green **?** button beside its title. A click opens one help dialog that explains the analysis for a reader who is
  not a specialist, in the same six parts everywhere: *In plain words*, *Data used*, *How it was made*, *How to read it*, *Why it matters* and *Keep in mind*. Esc, the
  Close button or a click outside closes it; focus returns to the button; the button is hidden in print. The texts are in `python/report_help_text.py` (84 entries on
  the demo), injected by `python/report_help.py` as one JSON block, so the page grows by about 45 KB, not once per button.
- `test/test_report_help.py` fails when a section or tab has no entry or an entry leaves one of the six parts empty, so a new analysis cannot ship without its help.
  It sits beside the small "i" popovers, which still carry each section's own lead note on hover.

### Fixed -- 3D charts drawn flat
- Pruning a Not-run tab also removed the shared 3D engine script that was emitted after it, so the 3D landscape fell back to its flat static picture. Pruning now keeps
  script and style blocks, and a test checks the demo page carries the engine.

### Fixed -- out-of-memory failures counted as the tool's fault
- A run whose log shows "Cannot allocate memory", `std::bad_alloc`, `MemoryError` or "out of memory"
  is a **resource** failure, like exit 124/137: by default it still scores 0, but it is reported as
  `failed_resource`, and `--resource-failures exclude` drops it. Found on cohort 1, where plasmidSPAdes
  ran out of memory on one isolate (exit 250) and was counted as an ordinary tool failure.
- **PDF export from WSL**: a Windows Edge/Chrome found under `/mnt/c` is given Windows paths (`wslpath -w`)
  for the report, the PDF and its profile; it could not open Linux paths and wrote no PDF.

### Changed -- section review: duplicates, mixed tasks and not-run sections
- **Recommendations are made for one task.** `select_operational_method.py` now recommends among the reconstruction tools only (`binning_capable=yes` in
  `config/tool_capabilities.tsv`); classifiers are ranked separately and are no longer compared with reconstruction tools in one "recommended overall" line.
  `benchmark.recommendations.tsv` has a last column `task`; `--task all` keeps the old behaviour and warns. The report says "One task" above the recommendation.
- **One place for each result**: the Automated interpretation section (it repeated *Start here*) is gone; per-plasmid results live in Plasmid maps ("All per-plasmid
  results" is its tab); run outcomes are one table with a reason column; Assembly adequacy is a tab of Assembly quality; both database-leakage screens are one tab;
  the two truth-quality groups are one *Reference standard* group beside the Headline design (with the pre-registration); the contig layer no longer prints the
  independent second scorer twice.
- **Fewer views of the same data**: the scorecard and its by-scenario views and the five-dimension composite are one *Scorecard (exploratory)* view with tabs; the
  Overview keeps the result, its confidence and the findings, the rest moved to Detailed results and Methods; the per-isolate recommender evaluation is one
  *Recommender validation* card under Recommendation, closed by default.
- **Artifact explorer replaces the "Data in this report" table**: each of its files has a description (what it is, which step wrote it, where it is shown); empty
  Logs and Data folds are hidden.
- **Glossary**: the 40 key headings are one searchable table.
- **Not-run sections are listed once**: a section or tab that holds only a "Not run" notice is not shown; *Run metadata* lists it with its reason ("Not run in this
  run"), and the old section id still lands there. *Extended analyses and next steps* is one line in Run metadata unless results exist.
- **The interactive cohort dashboard is optional** (`--embed-dashboard` or `REPORT_EMBED_DASHBOARD=1`, default off): it repeats the heatmap and metric tables and
  adds about 1 MB (the 6.5 MB of evidence-explorer data is separate and stays, lazy-loaded). The evidence explorer is unaffected.
- Panels of the explorers no longer show two headings; "Selected reconstructions" says why a selection needs review. The feature manifest keeps an explicit
  `REMOVED_BY_DECISION` list (six rows, each with its reason and where the information went) so nothing is lost silently.

### Changed -- order and wording for readers who are deciding
- **View order**: Overview, Recommendation, Figures, Plasmid maps, Detailed results (was "Statistical diagnostics"), Data quality, Methods and limits, Scorecard
  (exploratory), Appendix. Menu labels equal view titles; section labels in the menu are two to four words. Figures run CPRR differences, CPRR distributions, heatmap,
  precision-recall, ladder, 3D landscape, then the interactive cohort dashboard; the dashboard (Figures) and the reconstruction evidence explorer (Plasmid maps, new
  section `evidence-explorer`) are no longer in the Appendix.
- **Banner**: the title only. The duplicate numbers (samples, tools, leader, execution issues) are gone; the Summary has them once, then *Start here*, the plasmid matrix,
  the report card and the scorecard overall. The eyebrow is no longer all capitals.
- **Phone top bar**: the isolate filter, palette, collapse all and print / save PDF sit behind one menu button; the search keeps the room.
- **Display names at build time** (`python/report_names.py`): tool ids in the page text become display names when the report is built (link text only when it is exactly
  one id; file names, attributes, options and code are left alone), so print, PDF and no-JavaScript readers see them too.

### Changed -- the two explorers load when first shown
- The interactive cohort dashboard and the reconstruction evidence explorer (7 to 8 MB each) were written into their iframes at page load even though they sit in the
  Appendix, which opens hidden. They are now written only when the frame first becomes visible (with a 400 px margin), when the reader presses *Load now*, or at once
  when printing or exporting a PDF (`?print=1`, `beforeprint`) or where `IntersectionObserver` is missing. The documents stay in the page (it is still one offline file).
  On the demo report the page finishes loading in about 1.5 s instead of 4.5 s. `test/test_lazy_frames.py` runs the loader in node against a stub DOM.

### Changed -- report layout, condensed analytics, full PDF
- **Page shell** (`python/report_layout.py`): fixed top bar and left rail, one view at a time (Overview, Scorecard, Figures, Plasmid maps, Diagnostics, Data quality,
  Recommendation, Methods, Appendix) in story order, compact title band, status-chip accordion for data quality, hash routing for every old id, no-JavaScript fallback
  (the full linear page). 73 top-level sections become 34.
- **Merged analyses** (`python/report_merge.py`): related sections become tabs of one container and keep their old id as the panel id (`python/report_aliases.py`
  resolves old links): Ranking confidence, Method ranking (chart, metric framework, MCC and F-beta, graded recovery, negative control, baselines), Cohort and truth
  quality, Run outcomes and cost, Bin diagnostics, Scorecard (composite as *Weights and sensitivity*), Recommendations, Recommender, All scores (by tool, by sample) and
  a Reference tables appendix. The duplicate paired-comparison table in the unseen-taxa section is gone (it was a second copy of the Paired tests table).
- **Isolate filter and plasmid matrix** (`python/report_isolates.py`): the Summary and the Scorecard used to show cohort-wide numbers only. The Summary now has a
  *Which tool recovered which plasmid* matrix (one row per truth plasmid, one column per tool, coverage with a tick, half circle or cross, the best tool starred, and
  per-tool counts of plasmids recovered and plasmids on which the tool was best; one table per analysis track). An **Isolate** filter in the top bar (default *All
  isolates*) swaps the report card, the scorecard overall, the whole Scorecard (every metric re-scored on that isolate alone) and the matrix to one isolate's own
  numbers; a scope label next to each heading says which isolate is shown, and the no-JavaScript and print views show all isolates. The run line under the title is
  removed (the run folder is in the top bar and the full run details are in *Run metadata*).
- **Content uses the full width; folds start open**: the right-hand "On this page" strip is gone and the list now sits at the bottom of the left rail (it follows the
  view on show and highlights the current section). Every fold (cards, folded tables, drill-downs) starts expanded and can be collapsed; the top-bar button reads
  *Collapse all* / *Expand all* according to the state of the view. Summaries written as "Show the X" read "The X".
- **Condensed tables** (`python/report_condense.py`): tables over 15 rows show 12 rows with a filter and *Show all*; consistent table typography.
- **Full PDF export** (the browser sandbox stays on; where it cannot start, e.g. a container, set `PLASBENCH_BROWSER_FLAGS=--no-sandbox` for that run): print stylesheet with cover and contents, one view per page, every fold open; `python/export_report_pdf.py` and `plasbench report-pdf`.
- **No feature lost**: `test/fixtures/report_feature_manifest.tsv` (254 features of the earlier report) is checked by `test/test_report_feature_manifest.py`.
- **Corrected statements**: the ranking metric is named where the ranking score is quoted; the claim that failed runs are excluded from means is replaced by the real rule
  (F1 = 0 for a failed run on a plasmid-bearing isolate); robustness column renamed; power table names its metric (`power_analysis.py --leaderboard`); scenario views share
  one definition; scorecard overall beside the report card; glossary covers CPRR, MCC, F2, scorecard terms and NGOC; `--scores` folder is the results directory.

### Added -- figure gallery
- **Reconstruction ladder** (`fig-ladder`, `docs/images/reconstruction_ladder.svg`): the five steps from contigs to a verified plasmid, the score layer that judges
  each, live values from the run, and three explicit distinctions (binning is not reconstruction, circular is not correct, 3D is illustrative), two of them quantified.
- **3D landscape** of accuracy, completeness and structural fidelity (`fig-landscape`), **tool-by-metric heatmap** with clustering (`fig-heatmap`), **CPRR distributions**
  and **forest plot** (`fig-distributions`, `fig-forest`), and an interactive **precision-recall** plot (`fig-pr`). Each has a side setup panel, tooltips, drilldown,
  a no-JavaScript fallback and SVG / PNG / CSV export. The shared 3D engine no longer uses `Math.random`.
- Plasmid viewer: linear **Reference versus reconstruction** pane and Alignment tab, linked to the circular map; per-tool alignment blocks in the payload.
- `python/report_collapse.py` folds the scorecard, accuracy, performance, stratified, replicon-recovery and graded-tier tables that a figure now draws into closed details
  (nothing is removed). `python/report_figures.py` wires the figure modules; a module that raises fails the build instead of leaving a silent gap.

### Added -- databases kept once per machine
- **`PLASBENCH_DB_DIR`** (default `~/.plasbench/databases`): every tool database default points
  there instead of `DATA_DIR/db`, so new checkouts, new `DATA_DIR`s and rebuilt environments reuse
  what is downloaded. A database still at the old `DATA_DIR/db` path is used until the store has it.
- **`env/preserve_databases.sh`** moves existing databases into the store and leaves a link at the
  old path; never deletes; reports duplicates.
- **MOB-suite's database** moves to the store and its environment folder becomes a link; setup and
  the MOB-suite installer link a rebuilt environment to the stored copy instead of downloading again.

### Fixed -- MOB-suite pandas incompatibility in local installs
- MOB-suite needs `pandas<=1.5.3`; in the main environment (pandas 3) `mob_recon` crashed at start
  and every run scored 0. `env/environment.yml` and its lock no longer include `mob_suite`;
  `env/install_tools.sh` installs it into its own environment, `<env>-mobsuite` (MOB-suite 3.1.9,
  the Dockerfile's pins), and writes `mob_recon`/`mob_typer`/`mob_cluster`/`mob_init` wrappers into
  the main environment. `setup_conda.sh` runs this step; `plasbench install-tools mobsuite` repairs
  an existing install. The MOB-suite database checks follow the wrapper (`scripts/lib.sh`
  `mobsuite_db_dir`), as does stage 6's database-containment step.

### Added -- downloads kept for future runs; broken tools caught early
- **Preserved downloads** (`PRESERVE_DOWNLOADS=1`): stage 1 writes `<sample>/downloads.sha256` for the
  reads and NCBI records and makes the reads read-only; a later run with the same `DATA_DIR` verifies
  them and downloads nothing, and re-fetches only a file that fails its checksum.
- **Tool smoke test at setup**: an enabled tool that is installed but cannot start (for example
  MOB-suite importing a name newer pandas removed) is reported as `[BROKEN]`, not `[ok]`.
- **Import failures are infrastructure failures**: a run whose log shows `ImportError`,
  `ModuleNotFoundError` or similar is never scored as the tool's F1 = 0; it is rerun after the fix.
- Download tests force `READ_SOURCE=sra`, so they never reach ENA over the network.

### Added -- interactive report views
- **Info popovers for explanatory notes** (`python/report_info.py`, `assets/report/info_script.html`): one post-processing step on the finished
  page moves section leads, "how to read" notes and figure captions into a circled "i" beside the heading that opens on hover, keyboard focus
  or tap (click pins, Esc closes, links inside stay usable, works inside collapsed sections). The plasmid viewer, the 3D views and the colour
  palette bar use the same icon for their hint lines. "Not run" notices, caution boxes, notes that carry a status or a value, and the Summary
  section stay on the page; the print view shows every note inline. Notes keep their original HTML and the page is shorter to read.
- **Interactive plasmid map viewer** (`assets/report/plasmid_viewer_*.html`, `python/report_maps.py`): one viewer with a side panel replaces the
  stack of static maps. Hover tooltips, click drilldown into a Detail tab, wheel zoom and drag rotate with labels re-laid out, region inputs,
  search, layer, class and tool filters, Tools / Features / Events tables as tabs, SVG, PNG and TSV export, shareable URL-hash state, keyboard
  and touch support. The static SVG maps stay as the no-JavaScript and print fallback.
- **3D views** (`python/report_3d.py`, `assets/report/viz3d_*.html`): rotatable SVG scenes (no libraries, offline) for the contig layer beside
  the reference layer (bars per tool and layer with the independent-scorer cross-check), the per-isolate recommender against the single best
  tool and the oracle (regret gaps and a verdict banner), and AMR genes on the right plasmid (a tower of rings, one per tool). A static server-
  rendered view is the no-JavaScript and print fallback; a test checks the JS and Python projections agree.
- Large tables are collapsed until opened: scorecard definitions, headline design and reference standard, classification and reconstruction
  metrics, interpretation limits, the per-plasmid table and the regret table (their rows are also in the viewer and 3D panels; nothing is removed).

### Added -- report overhaul: scorecard, maps, workflow, inventory
- **Workflow figure moved to the README**: it describes how the pipeline is built, not what one run produced, so the report no longer has a
  Workflow section. `python/report_workflow.py` now draws a static `docs/images/workflow.svg` (embedded in the README's "Benchmark workflow"
  section); a test fails if the committed file drifts from the generator.
- **Weighted scorecard** (`python/report_scorecard.py`, `config/scorecard.tsv`): 17 metrics A1-E3, piecewise-linear score (100/85/60/0), metric bands, overall
  bands (90/75/55), weights renormalised over scored metrics with the scored weight share, and non-exclusive scenarios (simple, complex, annotated,
  challenging) with an underpowered flag below `SCORECARD_MIN_SAMPLES` (5). Only the identity bands are `fixed`; the rest are `proposed` and registered in
  `config/prereg.tsv`. A4 and C2 are `undefined` (no truth variant set): no thresholds, excluded from the overall.
- **Circular plasmid maps** (`python/report_maps.py`): per truth plasmid, with truth genes, tool coverage rings, GC content and GC skew
  (`MAP_MAX_TOOLS` 8, `MAP_MAX_BP` 600000).
- **Data inventory** ("Data in this report", `python/report_surfaces.py`), per-plasmid detail, assembly-quality section, depth strip,
  grouped collapsible navigation, a column-group switch for the scores table, and links to `leaderboard.md` and `scoring_spec.md`.
- Corrected the paired-comparison table and the overlap wording.
- Docs: SCIENTIFIC_GUIDE 7.10, 13.3, 15, 17.4; METHODS; README. New variable `SCORECARD_MIN_SAMPLES`.

### Changed -- performance audit fixes ([docs/PERFORMANCE_AUDIT.md](docs/PERFORMANCE_AUDIT.md))
- **Bin matching is rectangular** (`python/matching.py`, shared by `score_bins.py`, `score_amr_placement.py` and
  `metagenomics.py`): O(r²c) instead of a padded O(max(B,P)³) square. Same optimal total weight; the same pairs
  wherever the optimum is unique (`test/test_matching.py`); 400 bins × 20 plasmids in 0.02 s.
- **Exact statistics without `Fraction` objects** (`python/resampling.py`): every mean, bootstrap interval and
  permutation p-value is bit-identical to before (`test/test_resampling_equivalence.py`), and resampling adds
  precomputed per-cluster integer sums. `headline_design` and `aggregate_results` no longer import each other.
- **Stage 4 reuses a tool result only when its fingerprint matches**: installed executable, adapter, database row,
  `<TOOL>_*` settings (thread counts excluded) and inputs are written into `.<tool>.complete`. An upgrade, a
  changed setting or a new assembly re-runs that tool. Markers from earlier releases re-run once
  (`REUSE_UNFINGERPRINTED=1` reuses them unchecked).
- **Capability registry read once per stage** (`tool_capabilities.py --dump`, `lib.sh load_capabilities`) instead
  of one `python3` launch per lookup (12.5% of the demo's wall time).
- **One minimap2 index per sample** in stage 5 (`.reference.<preset>.mmi`, deleted afterwards); byte-identical
  PAF across all 105 call shapes checked on the demo.
- **Stage 6 advisory analyses run as a bounded parallel group** (`STAGE6_PARALLEL_JOBS`, default 4; 1 restores
  the serial order).
- **`plasbench-score` applies the pre-registered alignment filters** the caller omits (`MIN_ALIGNMENT_*` when
  exported); a direct `score_plasmids.py` run without filters prints a note.
- **Shared, validated readers** in `plasbench_common.py` (`read_truth_table`, `read_bin_membership`, `iter_fasta`,
  `open_maybe_gz`, `union_length`) replace 20 local copies. `bin_quality.py` now applies the bin scorer's rules
  (a non-`PLASMID`/`CHROMOSOME` truth row, or a contig in two bins, is an error) instead of reading them differently.
- The leaderboard writer refuses a column/value count mismatch; `test/bench/` holds the timing harnesses.
- **Data-structure upgrades, results unchanged** (every output hash identical before and after,
  `test/bench/bench_dsa.py`): hash-map indexing in `bin_agreement.per_bin_rows` (64×) and hash-set dedup in
  `read_bins` (86×); hash sets for the matcher's live rows (6.8×); a bounded heap for the visualization top-k;
  a sliding window between N positions with bytes encoded once in `contig_crosscheck.sampled_kmers`; binary
  search in calibration bucketing; a `Counter` for duplicate checks; the permutation tests' fair-bit draw
  inlined (a bulk bit-decoding variant was measured slower and not kept).
- **Streaming reads**: `iter_fasta(path, wanted)` skips unwanted records without joining them; the database
  containment check no longer holds the chromosome (peak 12.7 → 0.4 MiB on a 5 Mb reference).
- **Parallel ENA downloads**: both mates at once and `ENA_DOWNLOAD_CONNECTIONS` (default 4) byte ranges per
  file of at least `ENA_SEGMENT_MIN_BYTES` (aria2c when installed; `ENA_USE_ARIA2=0` disables it), falling back
  to the resumable single stream and always MD5-verified (`test/test_fetch_ena_parallel.py`). 8.6 → 1.6 s for
  2 × 16 MiB at 4 MiB/s per connection.
- **Thread budget**: with `THREADS` unset, the cores are divided across `MAX_PARALLEL_SAMPLES × MAX_PARALLEL_TOOLS`
  instead of every job requesting every core (`test/test_thread_budget.sh`).
- Stage-4 fingerprints identify a tool's executable by path, size and modification time and never run it to ask
  its version (a tool that does not parse `--version` could otherwise start a real run).

### Fixed
- Leftover merge-conflict markers in this changelog.

### Changed -- track-specific endpoints and CPRR robustness
- **Long-read and hybrid reconstruction are now ranked on isolate-level CPRR** (`sample_cprr`); short-read reconstruction stays on
  length-weighted binning F1 with CPRR as the key secondary endpoint (`headline_design.ranking_metric()`; `config/prereg.tsv`
  `primary_endpoint`, `primary_endpoint_long_read`).
- **CPRR threshold sweep**: `score_bins.py` writes correct counts with coverage and bin share at 0.80-0.99; new
  `benchmark.cprr_threshold_sweep.tsv` and leaderboard `cprr_auc` (normalised area under the pooled curve).
- **Isolate-weighted CPRR** (`cprr_isolate_mean`, `cprr_isolates`) beside the pooled rate.
- **Stratified CPRR**: `cprr` and `n_cprr_assessed` per size band, replicon, MOB and AMR carriage in
  `benchmark.recovery_by_replicon.tsv` (identity rule via `--truth-provenance`), and pooled CPRR per reference tier.
- README evaluation framework and workflow sections; METHODS, PREREGISTRATION and the HTML report updated to match;
  `test/test_cprr_robustness.py` added.

### Added -- completing the plsMD, PlasEval and GAEMR follow-ups
- **PlasBin-flow output adapter** (`RUN_PLASBIN_FLOW`, `PLASBIN_FLOW_OUTPUTS_DIR`, `adapters/adapt_plasbin_flow.sh`): adapts the tool's own output
  (it needs a Gurobi licence, so PlasBench does not run it); a contig listed in several bins stays in the first and the rest are recorded.
- **Cross-check against the original PlasEval** (`test/test_plaseval_crosscheck.py`, optional, `PLASEVAL_SRC`): best-match precision, recall and F1
  agree on every case, and the normalised dissimilarity agrees on every case without repeated contigs.
- **Optional label evidence**: several Abricate replicon databases (`ANNOTATION_REPLICON_DB`) and BLAST-based ISFinder annotation (`ISFINDER_FASTA`).
- `env/download_plsdb.sh` now has an offline test and refuses a download that is not FASTA: the PLSDB address in plsMD's Dockerfile redirects to an HTML page.

### Fixed
- The `repeat_rich` scenario tag never fired on real annotation: it counted feature types `is` and `isescan`, while `annotate_reference.py` writes
  `insertion_sequence`.

### Added -- lessons from plsMD, PlasEval and GAEMR
- **plsMD wrapper** (`RUN_PLSMD`, `adapters/adapt_plsmd.sh`): an optional benchmarked reassembly tool, skipped with a recorded reason when
  its command, PLSDB index or Unicycler assembly is missing; PLSDB listed as its database for the leakage screens.
- **`baseline_replicon`**: a third trivial baseline (a replicon marker, with plsMD's Col-versus-Inc rule).
- **Bin agreement** (`python/bin_agreement.py`, PlasEval's published definitions reimplemented): best-match (non-one-to-one) precision, recall
  and F1, a split/join dissimilarity, a tool-vs-tool agreement matrix and a PlasEval-format export.
- **`CHIMERIC` contig label** and a `plasmids` column in the contig labels (GAEMR's misjoin idea).
- **Assembly adequacy**, **plasmid copy-number concordance**, **truth repeat content** and opt-in **truth depth anomalies**.
- **Origin-wrap fix**: a rotated circular plasmid is no longer reported as a tandem duplication by `call_structural_variants.py`.
- Local read pairing for `init-local --reads-dir` (`_1`, `_R1`, `_R1_001`), `env/download_plsdb.sh`, report sections for all of the above, and a README
  section on what PlasBench offers over the three projects, with where each is better.

### Added -- cross-check, ENA fallback, demo coverage
- **Independent second scorer for the contig layer** (`contig_crosscheck.py`): alignment-free k-mer
  labels and separately written metrics; per-run agreement table, report and validity statement.
- **ENA fallback for short reads** (`fetch_ena_reads.py`, `READ_SOURCE`): when `prefetch` fails (for
  example an old SRA Toolkit failing TLS), the same run is fetched from ENA and MD5-verified.
- The demo now has a synthetic assembly, so the contig layer, the cross-check, assembly statistics and
  the QC-gate warnings render with real values.

### Added -- scoring specification and panel examination
- **Pre-registration** (`config/prereg.tsv`, `freeze_prereg.py`): freeze/verify a SHA-256 lock; the
  manifest and report show the hash, lock state, `TO_FIX` items and departing settings;
  `REQUIRE_PREREG=1` gates stage 4.
- **Labelling schemes** (`label_schemes.py`, `TRUTH_LABEL_SCHEME`, default `ncbi`): the headline is
  now scored on NCBI labels (Scheme 3, decision E.15) instead of the evidence-checked truth; Scheme 1
  and the evidence scheme are rank-sensitivity variants. **Behaviour change:** set
  `TRUTH_LABEL_SCHEME=evidence` for the previous scoring.
- **Dimer collapse** (`detect_dimers.py`, `COLLAPSE_DIMERS`), **truth grades** A/B/C, optional cohort
  columns `same_extraction`, `split`, `genus`, `phylum`, `grade_source`, `collection_date`.
- **Scoring**: `TN_bp`, `mcc`, `f2`, `f0_5`, `abstention_rate`, `--min-contig-length`; per-plasmid
  outcome states (`score_bins.py --outcomes-out`); contig-level binning F1 and shared/unassigned
  lengths; AMR placement by gene class (`score_amr_placement.py`, `config/amr_gene_classes.tsv`).
- **Outcome states**: `infrastructure_failure` (never scored), `TOOL_RETRIES`, `TOOL_TIMEOUT_SECONDS`,
  `tool_outcomes.tsv`, `benchmark.outcome_states.tsv`; `tool_status.tsv` schema unchanged.
- **Statistics**: Wilcoxon signed-rank (exact n ≤ 25) with Holm, equivalence flag
  (`SMALLEST_DIFFERENCE`); new rank-sensitivity axes (schemes, min contig 500, micro, public/in-house,
  grade C excluded, MCC/F-beta/contig metrics).
- **Recommender evaluation** (`evaluate_recommender.py`, `evaluate_warnings.py`, `leave_taxon_out.py`):
  regret, near-optimal, gap closed, `benchmark_only` verdict, warning PPV/sensitivity, leave-taxon-out
  and a once-only holdout.
- **Panel items**: recommendation floor (`RECOMMENDATION_MIN_EXPECTED_SCORE`, D11); operational states
  `insufficient_sequence` and `ambiguous_between_references`; advisory assembly QC gate (D13); a
  "tools compared" reason table (D15).
- Ten new HTML report sections and `benchmark.scoring_spec.md`; the demo exercises all of them.
- Docs: `docs/PREREGISTRATION.md`, `docs/PANEL_ALIGNMENT.md`, the scientific guide, METHODS, and
  the question bank (clustering/relatedness answers cut to "outside this benchmark").

### Added -- metric rubric
- **Contig-level classification** (`contig_classification.py`): contigs labelled against truth
  (>= 95% identity over >= 80% of the contig; short, ambiguous and unplaced contigs excluded and
  counted); count-based and length-weighted precision, recall, F1 and **MCC** per tool.
- **ARI** (base-pair weighted) and **assembly-aware binning recall/F1** in `score_bins.py`.
- **Micro** (pooled-base) precision/recall/F1 beside the macro means.
- **Sequence-level database membership** (`database_containment.py`): truth plasmids checked against
  each tool's own database; recovery reported inside vs outside it.
- HTML sections "Classification and reconstruction metrics" and "Truth plasmids in tool databases";
  README metric tables updated, with a headline metric set.

### Added -- reviewer question bank
- **Trivial baselines** `baseline_coverage` and `baseline_reference`, scored like tools;
  leaderboard columns `is_baseline` and `beats_best_baseline`.
- **Probability calibration** for probability-exposing tools: Brier score, expected
  calibration error and a reliability table/diagram.
- HTML report sections **Baselines and calibration**, **Interpretation limits** and
  **Metadata completeness**; `benchmark.metadata_completeness.tsv`.
- `docs/FAQ_QUESTION_BANK.md` answers the 108-question reviewer bank.

### Fixed
- The run manifest now records every ranking-relevant setting added by recent releases.
- A duplicate `PLASMID_REFERENCE_SKETCH` default ignored `DATA_DIR`.
### Cohort and database data
- **`public-v3` panel** (98 isolates, locked): `public-v2` plus recorded truth provenance
  and 66 new long-read-first isolates, one per BioProject, across six species. All rows
  verified online; `accepted_accessions.tsv` regenerated; CI checks the v3 lock.
- `config/tool_database_releases.tsv`: release dates verified from each installed or pinned
  database's own record (MOB-suite DB v2.0.0 2020-05-04, Platon DB v1.5.0 2020-10-05,
  geNomad DB v1.9 2025-02-18, PlaScope 2018-07-13, RFPlasmid 0.0.18 models 2021-07-28);
  uninstalled databases left blank with the reason.
- New `python/collect_truth_provenance.py` and `python/discover_design_cohort.py`; the
  assembler pattern now tolerates NCBI's "Trycyler" misspelling.
### Added -- further benchmark dimensions (advisory; none changes the leaderboard)
- `python/alignment_accuracy.py`: nucleotide identity, mismatch, insertion and deletion rates decoded from the alignment CIGAR,
  and missing-region counts; `python/mask_accuracy.py` blanks the rates where the truth was polished with the benchmark's own
  reads (the same rule as the CPRR identity criterion). SNP concordance is not computed (no variant truth exists).
- `python/feature_preservation.py`: full-length, truncated and missed recovery per feature kind, and NGOC (gene or
  landmark-order conservation, strand and circularity aware), by projecting truth features through the alignments.
- `python/bin_quality.py`: high and medium quality-bin yield, homogeneity, completeness and V-measure, as secondary diagnostics.
- `python/performance_summary.py`: success rate, resource failures, runtime, memory, thread-seconds per recovered plasmid,
  CPU utilisation and scaling exponents. Stage 4 now records user and system CPU seconds beside peak memory.
- `python/power_analysis.py`, `python/scenario_tags.py`, `python/compare_runs.py`, and an optional gated composite with weight
  sensitivity (`python/composite_score.py`, `config/composite_weights.tsv`). The composite never changes the leaderboard.
- `python/stratify_recovery.py` also stratifies by size band and resistance-gene carriage and reports median and IQR;
  `python/audit_truth_labels.py` screens truth labels against replicon and MOB evidence; `plasbench derive-amr-truth`,
  `plasbench audit-truth-labels` and `plasbench analysis <name>` expose the standalone scripts.
- The HTML report gains sections for each of the above, with explicit empty states. `RUN_DIMENSION_ANALYSES=0` skips them.
- Tests: `test_alignment_accuracy.py`, `test_mask_accuracy.py`, `test_feature_preservation.py`, `test_bin_quality.py`,
  `test_performance_summary.py`, `test_power_analysis.py`, `test_scenario_tags.py`, `test_composite_score.py`,
  `test_compare_runs.py`, `test_audit_truth_labels.py`, `test_scoring_controls.py`, `test_scoring_real_minimap2.py`,
  `test_stratify_multilabel.py`, `test_script_wiring.py`, `test_demo_end_to_end.py`, `test_stage_dimensions.sh`.
- Docs: `FAQ.md` (evidence-backed answers, and the reviewer question bank answered section by section),
  `docs/REVIEW_TRACKER.tsv`, a METHODS section for the new dimensions, and the README metric-framework and roadmap section.
- CI installs minimap2 so the real-aligner golden test runs.

### Changed (breaking, experimental output only)
- **The Mash nearest-reference screen no longer claims novelty.** Its calls were renamed
  because they promised more than a Mash distance to 16 plasmids can show:
  `known_cluster` is now `close_reference_match`, `novel` is now `no_close_reference`, and
  the `confidence_score` column is now `distance_margin` (a linear margin to an uncalibrated
  threshold, not a probability). `plasmid_similarity.tsv` gains `mash_p_value` and
  `shared_hashes`. The default threshold is unchanged, but its documentation no longer calls
  it "roughly ANI >= 95%": for plasmids, two equal-size sequences sharing about 35% of their
  k-mers already reach it, and an exact piece under about 21% of a reference falls outside it.
  Anything that read the old labels or column must be updated. The feature remains off by
  default and unvalidated.
- **`make_truth.py` no longer guesses CHROMOSOME for a sequence it cannot label.** Such
  sequences are written as `REVIEW`, which `validate_truth_table.py` rejects, so stage 2 stops
  instead of silently biasing precision and recall. This now also covers location types other
  than Plasmid/Chromosome and reports that contradict themselves. `ALLOW_DEFAULTED_TRUTH=1`
  (or `--allow-default`) restores the old behaviour.
- A skipped tool run (command not installed, database missing, no assembly graph) no longer
  counts as a failure in the operational recommendation's `failure_rate`; it already lowers
  coverage, which gates eligibility.

### Added
- **`docs/SCIENTIFIC_GUIDE.md`**, a guide for domain experts: what PlasBench does, how and why,
  its scope, every metric and statistical procedure, the shipped cohorts, outputs and how to read
  them, reproducibility, how each kind of expert can check the claims, what has and has not been
  validated, and a scope matrix. It has a table of contents, a README section with its own
  contents list, and `python/build_guide_toc.py` keeps both in step with the headings.
  `test/test_guide_docs.py` checks the contents, every link, and that every configuration
  variable, command and `scores.tsv` column the guide names still exists in the code.
- `run_manifest.json` now lists selected candidates for a benchmark run. It looked only for the
  operational layout (`<sample>/selected_candidate/`), so an ordinary benchmark run listed none.
- `n_failed_resource` and `n_unknown_overlap` leaderboard columns; `--resource-failures
  {score-zero,exclude}` and `--tool-capabilities` on `aggregate_results.py`.
- A failed tool run's exit code is recorded in `tool_status.tsv`'s reason column
  (`exit_code=<n>`; the file's header is unchanged). Exit 124/137 is classed as a resource
  failure.
- The HTML report now shows the nearest-reference screen result in each sample's selection card,
  with its experimental caveat and support (p-value, shared hashes); reports from before the
  rename still display.
- `python/rank_sensitivity.py` and `benchmark.rank_robustness.tsv`: per-track sensitivity of the
  ranking to alignment filters (re-scored from the PAFs on disk) and to the metric (strict F1,
  per-plasmid recovery), with Kendall's tau and whether the top tool changes. Run from stage 6;
  `RUN_RANK_SENSITIVITY=0` skips it. It does not change the leaderboard.
- A leaderboard warning (stderr and the Markdown leaderboard) and a clearer HTML cell when the
  database-overlap screen could not judge any pair because `database_release_date` is blank.
- Tests: `test_scoring_adversarial.py`, `test_aggregate_failures.py`,
  `test_selection_undefined_metrics.py`, `test_study_groups.py`, `test_leakage_visibility.py`,
  `test_classifier_semantics.py`, `test_report_classifier_section.py`, `test_rank_sensitivity.py`, `test_failed_tool_exit_code.sh`.
### Changed -- research design (headline endpoints and reference standard)
- **Primary endpoint is now length-weighted binning F1** for binning-capable tools
  (`lw_bin_f1`, ungated Hungarian match; the count-based `bin_f1` is kept but not
  ranked). **CPRR** (Correct Plasmid Reconstruction Rate) is the secondary endpoint,
  with pre-specified `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE`/`CPRR_MIN_IDENTITY`.
  Classifier-only tools are ranked on a separate classification track by
  base-level F1. Leaderboards add `task`, `ranking_metric`, `ranking_score` (+ CI),
  `ranking_species_basis`, `cprr` (+ CI) and `mean_lw_bin_f1`.
- **Reference standard.** `truth_provenance.py` classifies how each truth was built
  (long-read-first vs short-read-first; polished with the benchmark's own reads or
  not) and assigns reference tiers 1-3. Short-read-first and unknown-provenance truth
  (tier 3) leave the headline and become a sensitivity analysis; the CPRR identity
  criterion is dropped for truth polished with the benchmark's reads.
- **Evidence-based truth labels.** `label_truth_evidence.py` confirms each replicon
  with plasmid markers, rRNA genes (new barrnap caller) and long-read support;
  conflicting replicons (chromids, marker-free or short-read-only plasmids) are
  AMBIGUOUS and excluded from scoring via `truth.scored.tsv`. Self-built truth is no
  longer labelled by size alone.
- **Species balance.** The ranking score averages per-species means over species with
  >= `MIN_SPECIES_CLUSTERS` independent clusters; clusters join shared BioProjects and
  clonal groups (`clonal_groups.py`), and CIs/permutation tests resample whole
  clusters within species. New `benchmark.species.tsv`,
  `benchmark.reference_tiers.tsv`, `benchmark.headline_design.tsv`.
- `validate_cohort.py` prints advisory composition warnings (species count, dominant
  species, species below the minimum) and validates the new optional sheet columns
  `truth_assembly_strategy`, `truth_polish_reads` and `clonal_group`.
- HTML report: leaderboards per task with ranking score, CI and CPRR; new "Headline
  design and reference standard" section with provenance, tiers, species balance and
  a tier-sensitivity chart.

### Fixed
- `benchmark.species.tsv` now lists a tool that failed on every sample (mean 0 over the plasmid-bearing
  samples), as the leaderboard already did. `species_table` called `shared_values` without the failed-only tool,
  so the two outputs disagreed. The tool list passed in comes from the same (track, task) group, so failures of
  other groups' tools are not counted.
- **A tool that failed on every sample no longer vanishes from the leaderboard.** It now ranks
  last with F1 = 0 on every plasmid-bearing sample, in its own track.
- Equal mean F1 now ranks by tool name instead of by row order in `scores.tsv`, which made the
  "runner-up" in the significance test arbitrary.
- The operational recommendation no longer averages an undefined F1, precision or recall (an
  isolate with no true plasmid) as 0.0.
- Leave-one-study-out validation no longer silently drops samples with a blank `source_study`:
  they join the study of any sample sharing their bioproject, else use the bioproject, and
  samples with neither are reported.
- The mash query sketch now uses the same sketch size as the reference (it used Mash's default
  of 1000 against a 10000-hash reference), and mash's p-value and shared-hash count are no
  longer discarded; a close but statistically unsupported hit is no longer a match.
- `make_truth.py`: the version-less accession fallback is no longer order-dependent, and a
  `chr_name` shared by several records no longer silently resolves to the last one.
- The scorer ignores secondary alignment rows (`tp:A:S`) in a supplied PAF and warns.
- `scorable_truth.py` reads truth with the scorer's own validation.
- Removed `write_track_leaderboards`, which nothing called.
- **Empty predictions no longer inflate mean F1.** On an isolate with true
  plasmid, a tool that predicts nothing now scores F1 = 0 (precision stays
  empty). Previously F1 was left empty and the sample was dropped from the
  tool's mean, so a tool that abstained on hard isolates could tie a perfect one.
- **Tools are ranked on the same samples.** `mean_f1`, its CI and median now use
  only samples shared by every ranked tool in the track; a failed tool run
  (`tool_status.tsv`) on a plasmid-bearing sample counts as F1 = 0 for that tool,
  in both the ranking and the paired comparisons. New leaderboard columns:
  `analysis_track`, `n_ranking_samples`, `ranking_basis`, `mean_f1_all_scored`,
  `n_f1_scored`, `n_failures_scored_zero`.
- **The combined leaderboard no longer ranks across input tracks.**
  `benchmark.leaderboard.tsv/.md` now hold each track's table ranked within that
  track, and `benchmark.paired_comparisons.tsv` only compares tools within a
  track (new `analysis_track` column). Previously the combined file ranked
  short-read, long-read and hybrid tools against each other.
- `make_truth.py` no longer claims that defaulting an unclassified sequence to
  CHROMOSOME "only ever creates false negatives": if it is really a plasmid, correct
  plasmid calls on it are scored as false positives. Its warnings now say so, and
  the plasmid-free note no longer suggests excluding negative-control isolates.
- The HTML report no longer says failed tool runs are excluded from F1 aggregation
  or never become zero scores; it now describes the failure-as-zero ranking rule.
- METHODS.md now states that `unmapped_pred_bp` includes predicted sequence whose
  alignments were all removed by the alignment filters, so it lowers neither
  precision nor F1.

### Added
- **Cluster-aware statistics.** Bootstrap CIs and paired permutation tests resample
  whole BioProject clusters (sample-sheet `bioproject`, else `source_study`), so
  same-study isolates are not counted as independent. New columns
  `n_independent_clusters` (leaderboard) and `paired_clusters` (comparisons).
  Unchanged results when no cluster column is present.
- **Recall-ceiling diagnostic** (`python/scorable_truth.py`, stage 5, on by default):
  `scorable_plasmid_bp`, `recall_ceiling` and `ceiling_adjusted_recall` show how much
  plasmid sequence (shared repeats, duplicate plasmids) no prediction can be credited
  for under the alignment filters. Config: `RUN_SCORABLE_TRUTH`,
  `SCORABLE_WINDOW_BP`, `SCORABLE_STEP_BP`.
- **Strict precision** (`strict_precision`, `mean_strict_precision`): also charges
  unmapped and filter-rejected predicted bases. Supplementary, never ranking.
- **Reference-database overlap screen** (`python/flag_database_overlap.py`, stage 6,
  `config/tool_database_releases.tsv`): flags truth genomes public before a tool's
  database; leaderboard adds `n_possible_db_overlap`, `n_after_database`,
  `mean_f1_after_database`; `EXCLUDE_DATABASE_OVERLAP=1` drops flagged rows before
  ranking. Stage 1 now keeps `assembly_data_report.jsonl` for the release date.
- **HTML report "Robustness diagnostics" section** with a table and three charts
  (recall vs ceiling, precision vs strict precision, F1 vs F1 after database);
  the leaderboard shows the shared-sample basis and the comparisons table shows
  cluster counts.
- `redundant_pred_bp` score column: reference bases claimed more than once by
  retained alignments (e.g. duplicate predicted records). Diagnostic only; it never
  changes TP, FP or F1.

## [0.1.5] - 2026-09-10

### Added

- Optional operational-mode novel-vs-known plasmid classification
  (`RUN_PLASMID_NOVELTY_CLASSIFICATION`, `python/classify_operational_plasmid.py`,
  `python/build_plasmid_reference_set.py`): Mash distance from a truth-unknown
  isolate's own reconstructed candidate to a small, curated reference plasmid
  set, independently reimplementing santirdnd/COPLA's own known-cluster-or-
  novel pattern with PlasBench's existing Mash dependency rather than COPLA's
  code or its `graph-tool`/nested-SBM machinery. Off by default -- a purely
  supplementary, operational-only signal never wired into
  `recommendation_model.py`'s training features, since a genuinely unknown
  isolate has no truth reference, the entire reason this signal exists.
  - `python/build_plasmid_reference_set.py` builds the reference Mash sketch
    and metadata once from a committed, curated accession list
    (`cohorts/reference_plasmids/curated_accessions.tsv`, 16 real NCBI
    plasmids spanning *E. coli*, *Salmonella enterica*, *Klebsiella
    pneumoniae*, *Acinetobacter baumannii*, and *Staphylococcus aureus*, each
    with a one-line provenance justification). The built sketch/metadata are
    real downloaded data, not tracked metadata, so -- the same convention as
    `PLATON_DB`/`GENOMAD_DB`/`PLASME_DB` -- they live under `DATA_DIR/db`,
    gitignored.
  - `python/classify_operational_plasmid.py` calls the built-in `mash dist`
    against that sketch and calls `known_cluster` when the nearest reference
    is within `PLASMID_NOVELTY_SIMILARITY_THRESHOLD` (default Mash distance
    0.05, roughly ANI >= 95%) AND that reference's cluster has at least
    `PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS` members (default 2); otherwise
    `novel`. A missing `mash` binary or reference set gives
    `insufficient_reference`, never a guess.
  - Wired into `scripts/08_operational_reconstruct.sh` (`plasbench
    reconstruct`); results land in `results/<sample>/plasmid_similarity.tsv`
    and under `plasmid_novelty` in `selection_report.json`. A failed or
    skipped classification never blocks reconstruction or the rest of the
    report -- it is supplementary, not a gate.
  - See `docs/OPERATIONAL_SELECTION.md`'s new "Novel-vs-known plasmid
    classification" section for the full usage walkthrough.

### Changed

- **Relicensed from MIT to the GNU General Public License, version 3
  (GPL-3.0-only)**, effective from this point forward. Releases v0.1.0
  through v0.1.4 remain published under the MIT License as distributed;
  this change is not retroactive. See `LICENSE`, `NOTICE`, and
  `CITATION.cff`.

### Documentation

- Recorded the two real, permanent Zenodo dataset DOIs minted by the
  existing `zenodo-upload.yml` workflow when the v0.1.3/v0.1.4 GitHub
  Releases were created during the v0.1.x renumbering
  ([10.5281/zenodo.22671309](https://doi.org/10.5281/zenodo.22671309),
  [10.5281/zenodo.22671314](https://doi.org/10.5281/zenodo.22671314)), in
  both release notes and `cohorts/README.md`, per `docs/RELEASING.md`'s own
  instruction. These are dataset-only DOIs (the archived `cohorts/*.tsv`),
  not a software citation.

### Removed

- **PyPI publishing.** `.github/workflows/release.yml`'s `pypa/gh-action-pypi-publish`
  step (and the now-unused `python -m build` step that only fed it) failed on
  every real attempt with `invalid-publisher` -- the trusted-publisher
  registration on PyPI's side never actually matched this workflow, and
  `plasbench` was never reachable at pypi.org/project/plasbench despite
  `continue-on-error` making every release job show green. A step that
  always fails silently is worse than no step: it lets a broken channel look
  configured. The GitHub Release archive remains the Python-package
  distribution; see `RELEASING.md` for how to re-add PyPI later with a
  verified trusted publisher.

## [0.1.4] - 2026-09-08

Supersedes the removed v0.2.5-v0.2.8 tags.

### Added

- A separately executable metagenomic community/bin scoring route:
  `plasbench metagenomics`, or `plasbench run --mode metagenomics`.
- Strict community manifests, three-class plasmid/chromosome/virus truth,
  normalized graph/bin tables, global one-to-one bin matching, split/merge
  and contamination diagnostics, a run manifest, and
  `metagenomics.report.html`.
- A metagenomics installer profile for the tested baseline runtime
  dependencies (`metaSPAdes` through SPAdes and geNomad).
- An auditable optional orthogonal-validation evidence validator for
  long-read, hybrid, PCR, plasmid-extraction, conjugation, Hi-C, and
  optical-mapping records. Evidence is preserved separately and cannot
  inflate a score.
- Public cohort release and governance standards, including two-reviewer,
  conflict-of-interest, versioning, representation, and annual-refresh
  rules.
- An `amr_context` decision profile that treats curated AMR-gene recovery,
  plasmid recovery, bin quality, and structural penalties as co-primary;
  it safely falls back when an AMR truth table is unavailable.
- A deterministic, offline metagenomic demonstration fixture covering bin
  recovery, merge and contamination trade-offs, three-class classifier
  calls, uncertainty, and non-scoring mobilome evidence.
- An auditable tool-installer registry covering every supported, non-demo
  adapter, with `plasbench install-tools list`, `plan`, and `validate`
  modes.
- An external-benchmark importer that preserves source data, checksums, and
  truth-definition boundaries instead of mixing external scores into native
  PlasBench results.
- A candidate-quality dataset builder for downstream research only.
  Aggregate tool scores are explicitly not converted into fabricated bin
  labels.
- Strict reference-recovery-rate metrics and nested-validation model cards.
- A complete user-facing release guide (`docs/RELEASES.md`), a reusable
  GitHub Release template, and version-specific release notes under
  `docs/releases/`.

### Changed

- Refreshed public project identity to **PlasBench: A Reproducible,
  Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction
  Tools** with the tagline *Benchmarking plasmid reconstruction from
  sequence to biological function.* The stable `plasbench` command is
  unchanged.
- The isolate and metagenomic HTML reports now carry the updated project
  identity, plus auto-sized reconstruction dashboard frames, balanced
  evidence panels, run labels, and a clearer heatmap/report handoff.
- Installation guidance defaults to the verified latest-release installer
  and separates normal laboratory use from recovery and troubleshooting.
- The CLI reports a clear recovery command when launched outside a
  PlasBench project directory.

### Fixed

- Reject duplicate or malformed BMock12 gold-standard memberships, fail
  clearly when truth-backed metagenomic scoring receives no normalized
  predictions, and safely escape cohort metadata embedded in a
  self-contained HTML dashboard.

### Safeguards

- Metagenomic and isolate reports/rankings are structurally separated.
  Candidate bins are never represented as host assignments, circular
  closure, or clinical confirmation without independent evidence.
- `gplas2` remains source-runtime-only until its upstream runtime and
  classifier provenance can be installed reproducibly. It is deliberately
  not misrepresented as a one-command package installation.

## [0.1.3] - 2026-09-07

Supersedes the removed v0.2.0-v0.2.4 tags. Nothing here is on by default --
an existing cohort run behaves exactly as before unless a new flag is
switched on.

### Added

- Three long-read/hybrid tools: `hybracter_long`, `hybracter_hybrid`, and
  `trycycler_mob_recon`, a second independent long-read assembly path
  alongside Flye+MOB-Recon and Plassembler (assembler choice materially
  affects plasmid completeness on ONT data). Hybracter reuses the
  Plassembler database.
- Three opt-in ML classifiers, all short-read-track contig classifiers, not
  binners: `genomad` (gene-based neural classifier), `plasme` (alignment +
  transformer hybrid), `plasgraph2` (GNN over assembly-graph nodes).
- A new `pr_auc` metric: where an adapter publishes a candidates universe
  plus per-record probabilities, scoring sweeps every distinct probability
  as a threshold and reports the area under the precision-recall curve.
  Ranking stays on `mean_f1`; PR-AUC is supplementary.
- A read-quality ladder, the long-read analog of the depth ladder, with
  combined length+quality `--rungs` cutoffs.
- A leave-one-study-out decision-support model and multi-track
  recommendation support.
- `./update.sh` / `plasbench upgrade` for one-command version upgrades that
  reuse shared data across releases, plus a latest-release bootstrap
  installer.

### Changed

- Each tool is now scored under its own declared `analysis_track`
  (`config/tool_capabilities.tsv`), so one run correctly scores short-read,
  long-read, and hybrid tools together instead of applying one global track
  to every tool. Stage 7 (long-read reconstruction) is now part of the
  default stage list, before scoring.
- **The circularity guard (truth independence from long reads) now applies
  to all five long-read/hybrid tools**, including retroactively to
  `flye_mob_recon`, which had no guard before. This is a real behavior
  change for existing cohorts: a sample lacking
  `truth_independent_of_long_reads=yes` is now correctly **skipped** where
  it previously ran; each tool has a `<TOOL>_ALLOW_CIRCULAR_TRUTH=1`
  override.
- `docs/COHORTS.md`/`docs/METHODS.md` now name all five guarded tools with
  their override variables, instead of the two they listed before.

### Fixed

- CI no longer lets a failed PyPI publish block the GHCR image/GitHub
  Release.
- An upgrade no longer re-fetches shared data it should reuse.

## [0.1.2] - 2026-09-05

Supersedes the removed v0.1.6-v0.1.9 tags.

### Added

- `plasbench init-local`, staging a user's own FASTQ reads and reference
  into the pipeline, writing the truth table and sample-sheet row.
  Unlabelled sequences are written as `REVIEW`, never guessed.
- Two input validators that run before any tool starts: staged reads
  (missing/empty/not actually gzipped, mates out of order) and the truth
  table (unmatched ids, unlabelled sequences, bad `molecule_type`, tabs vs.
  spaces, length mismatches).
- Cohort download-size estimation and confirmation before fetching.
- Plassembler support on the long-read/hybrid track, with a circularity
  guard.

### Changed

- `THREADS`/`MEMORY_GB` now default to 80% of the detected machine's
  cores/RAM (floor 2 GB) instead of a fixed value.
- Databases are checked for presence before being re-downloaded; a partial
  download is reported as **incomplete**, never mistaken for a working
  install. Re-downloading is opt-in via `--force`.

### Fixed

- A failed download no longer aborts the whole cohort: failures are
  recorded per sample in `results/download_status.tsv` with automatic
  linear-backoff retry (`NETWORK_RETRIES`, default 3); the stage aborts
  only when every sample fails.
- Two parallelism tests now assert that work genuinely overlaps, measured
  from the stubbed tools' own process logs, rather than comparing elapsed
  time.

## [0.1.1] - 2026-09-04

Supersedes the removed v0.1.1-v0.1.5 tags.

### Added

- The packaged install-archive distribution
  (`plasbench-<version>.tar.gz` + `.tar.gz.sha256`, installed with
  `./install.sh --tools`).
- Three Galaxy tool wrappers (align/score/aggregate) with a real bioconda
  recipe and `plasbench-score`/`plasbench-aggregate` PATH entry points.

### Fixed

- Release archives no longer ship CRLF line endings, which previously made
  `plasbench test` die with `set: pipefail: invalid option name`.
- The `public-v2` cohort lock was regenerated against LF content and
  re-verified online against NCBI (32/32 pairs).
- `plasbench run` with no stage numbers no longer exits 2 on Python <=
  3.12. `install.sh` now bootstraps Miniforge itself when no conda is
  present.
- A micromamba prefix-resolution bug that aborted `plasbench install-tools`
  with "No prefix found" against a working install. `install-tools all` no
  longer pulls the incompatible bioconda `gplas` package; the explicit
  `gplas` profile now warns and points at gplas2 instead.
- **Install-critical**: `env/setup_conda.sh` no longer destroys an existing
  environment (including MOB-suite's 450 MB database) when re-run against a
  working install -- an existing environment is detected and updated in
  place, non-destructively.

## [0.1.0] - 2026-09-01

Initial public release: the verified `public-v1` cohort, a reproducible
environment lock, capability-aware scoring metrics, and the depth-ladder
workflow.

## Release Reading Guide

- **GitHub Release assets** are the checksum-verified source distribution for
  terminal installations. There is no PyPI package (removed; see "Unreleased"
  above) -- external bioinformatics tools and databases are installed
  separately through the documented installer routes regardless.
- **GHCR** supplies the container image. Use an immutable version tag such as
  `ghcr.io/ubeffiong/plasbench:v0.1.5` for reproducible work, not `latest`.
- **Run manifests and cohort locks** are required companions when reporting or
  comparing scientific results; a software version alone is insufficient.
