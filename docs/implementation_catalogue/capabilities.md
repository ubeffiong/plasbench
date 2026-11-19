## 3. What was implemented, capability by capability

Each block answers the same five questions: what it does, why it exists, where it lives, what checks it, and what it does not do.

### 3.1 Ground truth and the reference standard

- **What.** Every reference sequence of an isolate is labelled plasmid or chromosome from the NCBI sequence report, never from a tool under test. Each
  truth assembly gets a **reference tier** (how it was built and polished), an **independence class** (independent, partially independent, dependent,
  unknown: whether the truth shares evidence with the tools), and a **structured evidence record** of six fields (assembly technology, circularity,
  read support, replicon evidence, structural integrity, independent validation). The headline ranking uses only independent references of tier 2 or
  better; if none qualifies, the primary analysis is reported as unavailable rather than quietly using weaker truth.
- **Why.** A benchmark is only as reliable as its truth. A short-read-first truth shares repeat-resolution errors with the tools it judges; a truth polished
  with the benchmark's own reads favours tools that use those reads.
- **Also checks.** Tandem multimers in the truth (`detect_dimers.py`: dimers up to six copies, collapsed or flagged), three labelling schemes compared
  (`label_schemes.py`), labels screened against replicon and MOB evidence (`audit_truth_labels.py`, `label_truth_evidence.py`), overlap between the databases
  that labelled the truth and the tools' own databases (`truth_marker_overlap.py`), k-mer repeat content (`repeat_content.py`) and read-depth anomalies
  (`truth_depth_anomalies.py`) of the truth.
- **Reference evidence audit (new).** `reference_evidence_audit.py` joins all of the above into one row per isolate: strong, usable with caveats or weak, with
  every reason in words (`benchmark.reference_evidence_audit.tsv`, report section *Reference evidence*). A missing input can only lower the status.
- **Where.** `python/make_truth.py`, `truth_provenance.py`, `collect_truth_provenance.py`, `reference_evidence_audit.py`; stage 2 and stage 6; `docs/METHODS.md`
  ("Ground truth", "Research design"). **Tests.** `test_make_truth.py`, `test_collect_truth_provenance.py`, `test_reference_evidence_audit.py`.
- **Limits.** Tiers rest on NCBI free text and sheet declarations, not on independent confirmation. A reference that is independent but wrong cannot be detected.

### 3.2 Scoring: what is measured for every tool on every isolate

PlasBench projects each tool's predicted sequence onto the isolate's reference with minimap2 and scores it in layers. The layers answer different
questions and are never merged into one number.

| Layer | Question | Module |
|---|---|---|
| Base-level confusion (precision, recall, F1) | How many plasmid bases were recovered, and how many chromosome bases were wrongly included? | `score_plasmids.py` |
| Masked nucleotide accuracy and missing regions | How accurate is the sequence where the truth can support a statement, and which plasmid regions are absent? | `alignment_accuracy.py`, `mask_accuracy.py`, `scorable_truth.py` |
| Bin matching and length-weighted binning F1 | For tools that group contigs, how well do the groups match the true plasmids (globally optimal one-to-one matching)? | `score_bins.py`, `matching.py` |
| CPRR (correct plasmid reconstruction rate) | What fraction of true plasmids is reconstructed to the stated coverage, identity and contamination limits? | `score_plasmids.py`, `plasbench_common.py` |
| Structure and feature preservation | Are genes and features kept, and in the right order (NGOC)? Are structural discordances present? | `feature_preservation.py`, `call_structural_variants.py` |
| Bin quality | How many bins reach each quality tier; homogeneity and completeness | `bin_quality.py` |
| Contig-level classification | Per-contig precision, recall, F1 and MCC, with an independent second scorer as a cross-check | `contig_classification.py`, `contig_crosscheck.py` |
| Burden of unverified sequence | How much predicted sequence has no reference support? | `score_plasmids.py` (leaderboard column) |

Failure is scored as zero and tools are ranked on the isolates all of them share, so a tool cannot gain by failing on hard isolates. The metric registry
(`metric_registry.py`, `config/metrics.tsv`) states what each metric is *for*, so a metric is not applied to a task it does not suit.

- **Tests.** `test_scoring.py`, `test_scoring_adversarial.py` (oracle, empty, whole-genome, chromosome-only and plasmid-free predictions, hand-computed
  expectations), `test_mask_accuracy.py`, `test_feature_preservation.py`, `test_bin_quality.py`, `test_zero_plasmid_isolate_scoring.py`.
- **Limits.** The alignment filters (200 bp, identity 0.90, query coverage 0.20, MAPQ 20) and the CPRR limits (95% coverage, 99% identity, 5%
  contamination) are provisional conventions. Their effect on the ranking is measured (3.5) but they are not expert-validated. By default a predicted base
  that never aligns is not counted as a false positive; the strict-F1 variant counts it.

### 3.3 Three evaluation tasks, three endpoints

- **What.** Each tool belongs to one task and is ranked only against tools of the same task: *classification* (labels sequence as plasmid or not; endpoint
  base-level F1), *binning reconstruction* (groups existing contigs; endpoint length-weighted binning F1) and *sequence reassembly* (produces new
  sequence; endpoint isolate-level CPRR). Task comes from the registry (`config/tool_capabilities.tsv`), not from the tool's output format.
- **Why.** Ranking a classifier and a reassembler on one number rewards the wrong behaviour. Strict derivation of the task was added after the third review.
- **Where.** `python/headline_design.py`, `tool_capabilities.py`; PRs #75, #90. **Tests.** `test_evaluation_task.py`, `test_tool_capabilities_registry.py`.

### 3.4 Statistics

- **What.** Exact means, a cluster-aware bootstrap and exact sign-flip permutation tests. The unit of resampling is the independent cluster (BioProject,
  clonal group), not the isolate, so many isolates from one study count once. A minimum number of clusters is enforced, and when one or two studies
  dominate a cohort the interval method falls back to a safer one and says so. Multiple comparisons are controlled with Holm correction.
  `power_analysis.py` states how large a difference the cohort could detect.
- **How it was checked.** `simulate_validation.py` measures interval coverage and the false-positive rate of the tests under the actual cluster structure;
  results are in `docs/STATS_VALIDATION.md`. The default cluster-robust interval can under-cover when one or two studies dominate: that is documented, not hidden.
- **Where.** `python/resampling.py`, `aggregate_results.py`, `simulate_validation.py`, `power_analysis.py`; PRs #57, #58, #77, #78, #90.
  **Tests.** `test_resampling_equivalence.py`, `test_aggregate.py`, `test_power_analysis.py`, `test_leaderboard_significance.py`.
- **Limits.** With fewer than six independent clusters a permutation test cannot reach p < 0.05. Real cohorts have not yet been used to validate coverage.

### 3.5 How fragile is a ranking?

- **Scoring choices (`rank_sensitivity.py`, `benchmark.rank_robustness.tsv`).** Re-ranks under changed alignment filters, minimum contig length, three labelling
  schemes, strict F1, per-plasmid recovery, micro versus macro averaging, cohort subsets (without lower-tier or partly dependent references) and the CPRR threshold
  sweep. Reports Kendall tau and whether the leader changes.
- **Cohort composition (new, `ranking_stability.py`).** Re-ranks after leaving out each study, then each species, and with every study weighted equally;
  reports the largest study's and species' share of the cohort, whether the leader changes and a verdict (stable, fragile, not assessed). Files:
  `benchmark.ranking_stability.tsv`, `.study_sensitivity.tsv`, `.species_sensitivity.tsv`; report section *Ranking stability*; switch `RUN_RANKING_STABILITY`.
- **Assembly (new, `assembler_sensitivity.py`).** Given the scores of two or more runs of the same cohort that differ only in the assembly, re-ranks the tools
  on the shared isolates and says whether the leader depends on the assembler. Switch: `ASSEMBLER_SENSITIVITY_RUNS`; optional standalone HTML.
- **Tests.** `test_rank_sensitivity.py`, `test_cprr_robustness.py`, `test_ranking_stability.py`, `test_assembler_sensitivity.py`.
- **Limits.** The two new analyses have run on constructed cohorts only. All three are descriptive and never change the leaderboard.

### 3.6 Leakage: can a tool have seen the answer?

- **What.** Each tool's own database release date is recorded and compared with the truth's release date, with a configurable cutoff policy (fixed date or date
  basis, settable in the window; PR #96). `flag_database_overlap.py` flags isolate-tool pairs where the truth may be in the tool's database;
  `database_containment.py` checks at the sequence level where the database is installed; recovery on plasmids absent from a tool's database is reported beside the headline.
- **Where.** `python/flag_database_overlap.py`, `database_containment.py`, `database_provenance.py`, `config/tool_database_releases.tsv`.
  **Tests.** `test_leakage_visibility.py`, `test_database_provenance.py`.
- **Limits.** For tools whose database is not installed the sequence-level screen cannot run and only the date screen applies. Not every tool publishes a date.

### 3.7 Pre-registration

- **What.** The scoring parameters that decide a ranking are written to `config/prereg.tsv`, can be proposed, edited as a draft and then frozen with a hash;
  a strict freeze refuses later change, and every run records the values it used.
- **Where.** `python/freeze_prereg.py`, `docs/PREREGISTRATION.md`; PRs #14, #55. **Tests.** `test_script_wiring.py` and the freeze checks in the preregistration tests.

### 3.8 Agreement with PlasEval (the binning evaluation framework)

- **What.** PlasBench computes the PlasEval-style normalised dissimilarity (extra, missing, split and join components) with **repeat-aware** pairing of contigs
  that sit in several bins (branch and bound, capped, with a stated upper bound when the cap is reached). The paper's 53 *E. coli* isolates ship as the
  `plaseval-ecoli53` cohort with the paper's published bins, and PlasBench's numbers were compared with the **original program** (github.com/acme92/PlasEval, commit
  8238356, never bundled).
- **Result.** On 59 constructed and random cases PlasBench and the original agree. On the paper's real bins the original finished 211 of 212 isolate-tool pairs
  and PlasBench agreed within 0.001 on 210, with no disagreement; one pair differs by 0.003 because PlasBench's search hit its cap there (an upper bound); one pair
  timed out in the original. See `docs/PLASEVAL_REPLICATION.md`.
- **Anyone can confirm it.** `python python/plaseval_replication.py --out-dir out` writes an HTML report with the comparison. It uses the original program if
  installed (`--plaseval-src`), otherwise the recorded reference run in `cohorts/plaseval_ecoli53/original_reference.tsv`, and says which. In a normal benchmark,
  stage 6 runs a **comparison gate** (`plaseval_gate.py`, `RUN_PLASEVAL_GATE`: auto, on, off) that compares every exported bin set with the original and writes a verdict
  (PASS, FAIL, PARTIAL, NOT_RUN, NO_DATA).
- **Where.** `python/bin_agreement.py`, `plaseval_gate.py`, `plaseval_replication.py`, `report_fig_binerrors.py`; `cohorts/plaseval_ecoli53/`; PRs #87, #91, #94.
  **Tests.** `test_bin_agreement.py`, `test_plaseval_crosscheck.py` (needs a PlasEval checkout), `test_plaseval_gate.py`, `test_plaseval_cohort.py`, `test_report_fig_binerrors.py`.
- **Limits.** This validates the binning dissimilarity, not every PlasBench metric. The paper's own printed figures have not been compared.

### 3.9 Input control: short-read QC and assembly selection

- **Short-read QC gate** (`short_read_qc.py`, stage 3, `SHORT_READ_QC_MODE`: off, report, enforce; default report). Before assembly each read pair is measured (file integrity,
  read count, estimated depth, read length, GC deviation) against thresholds in `config/short_read_qc_thresholds.tsv` and given PASS, WARN or REJECT with reasons.
  Integrity failures always reject. In *enforce* mode a REJECT is excluded from the primary analysis and stage 4 says why; in *report* mode nothing is excluded but every
  REJECT is flagged. Outputs: `short_read_qc.tsv`, `short_read_qc_status.tsv`; report section *Short-read QC*.
- **Assembly selection policy** (`assembly_selection.py`, `ASSEMBLY_SELECTION_MODE`: fixed or quality; `ASSEMBLY_ALSO` keeps alternative assemblers). Each candidate
  assembly is measured (contigs, N50, L50, length, GC, optional read support); the selection rule uses measured columns only, never the truth or any score, and nothing is
  silently substituted. An assembly outside the eligible size range is marked ineligible and its samples are skipped with the reason. Outputs: `assembly_candidates.tsv`;
  report section *Assembly selection*.
- **Assembly adequacy** (`assembly_adequacy.py`) separates "the assembly never contained the plasmid" from "the tool failed to find it".
- **Frozen thresholds** (`docs/THRESHOLD_FREEZE.md`). The ten short-read QC limits were frozen on 17 November 2026 from a real-read pilot (`qc_pilot.py`: the first read pairs of 40 real runs of
  public-v4, `docs/validation/short_read_qc_pilot.tsv`) and the ENA read counts of 7,129 runs; the file hash `0727af448900` is stored in every QC row. One value changed before freezing
  (`adapter_fraction` lost its reject limit: adapters are trimmed, and a good run had 66%). The assembly size limit (8.5 Mb) and GC spread limit (0.12) are frozen unchanged, with their evidence.
  Not frozen, with the reason: `MIN_ASSEMBLY_ADEQUACY` and the candidate-multiplicity limits need a real multi-tool run; `gc_deviation` is inert by default and not backed by the pilot.
- **Tests.** `test_short_read_qc.py`, `test_short_read_qc_stage.sh`, `test_assembly_selection.py`, `test_assembly_selection_stage.sh`, `test_assembly_adequacy.py`, `test_threshold_freeze.py`.
- **Limits.** The QC thresholds are not platform-specific (the pilot is Illumina paired reads from public runs). Running every tool on
  every alternative assembly is a separate run per condition (3.5).

- **Assembly failure diagnosis and resource check** (`assembler_diagnosis.py`, `preflight_resources.py`, stage 3, `ASSEMBLER_AUTO_RETRY`, `CAP_THREADS_TO_CPUS`, `PLASBENCH_SKIP_DISK_CHECK`). When fastp, SPAdes or Unicycler fails, the log is classified (disk full, out of memory,
  memory limit, threads, CPU feature, broken Python, truncated reads, mismatched mates, short or empty reads, read-only or missing files, stale output folder, missing tool, network, or "not recognised" with the last lines) and one block names the cause, the evidence line and the advice;
  `assembly_status.tsv` gains `cause` and `advice`. A cause that belongs to the computer stops stage 3 at the first isolate (exit 5); out of memory and a stale folder get one retry. Before stages 0, 2 and 3 free disk (including the Windows drive holding the WSL virtual disk),
  memory, usable CPUs and writable folders are checked against an estimate. Reference annotation is cached by reference checksum and tool versions (`ANNOTATION_CACHE_DIR`).
  **Tests.** `test_assembler_diagnosis.py` (fixtures written from knowledge of the message formats, not captured logs), `test_preflight_resources.py`, `test_stage3_failure_diagnosis.sh`, `test_annotation_cache.py`, `test_run_status.py`.
### 3.10 Candidate multiplicity: when a tool reports several sequences for one plasmid

- **What.** Every predicted record is kept and accounted for. Per true plasmid the report gives the candidate count, the best single candidate's coverage, the **combined
  coverage as the union of aligned intervals** (never the sum of lengths), redundancy, off-target bases, chimeric candidates and unmapped bases. Each candidate gets a
  relationship: primary, complementary fragment, redundant, chimeric, off-target or unmapped. A tool cannot improve its score by emitting many overlapping candidates without it showing.
- **Outputs.** `benchmark.candidate_multiplicity.tsv`, `benchmark.candidates.tsv`, `benchmark.candidate_intervals.tsv`; report section *Reconstruction multiplicity* with
  coverage tracks drawn against the reference. The existing scores are unchanged.
- **Where.** `python/candidate_multiplicity.py`, `report_reviewers.py`. **Tests.** `test_candidate_multiplicity.py` (complete, fragmented, duplicated, chimeric, off-target cases), `test_report_reviewers.py`.
- **Limits.** Alternative circular paths are not modelled; repeat-driven ambiguity is flagged, not resolved. No real-cohort run has been reviewed yet.

### 3.11 AMR placement, structure and biological features

- **What.** AMR truth is drafted from reference annotation (never from a tool), reviewed by a person and promoted deliberately (`derive_amr_truth.py`, `promote_amr_truth.py`).
  `score_amr_placement.py` scores each gene copy at its position: not recovered, shared contig, unassigned contig, on the wrong plasmid or correctly placed, by output type.
  `feature_preservation.py` reports full-length versus partial recovery of replicon, mobility, IS and AMR features and gene-order conservation. SV-PRR reports CPRR counting
  structural discordance, beside CPRR, as an unvalidated descriptive measure.
- **AMR regions view (new).** `report_amr_regions.py` draws every resistance region of the truth (genes coloured by class, with insertion sequences, integrase or integron, replicon, mobility, transfer and metal-resistance context around them) with one lane per tool showing, gene by gene, correct plasmid, wrong plasmid, shared or unassigned contig, or not recovered, plus whether the flank is covered, and a verdict per region (intact, partial, lost; "attributed" for tools that do not bin). A funnel table shows where resistance information is lost: recovered, on the correct plasmid, flank covered, region intact. Interactive: choose a region, show or hide tools and gene classes, zoom, hover or focus to highlight a gene across every lane, click to pin its details. It re-draws what `score_amr_placement.py` already scored and changes no score.
- **Where.** `python/score_amr_placement.py`, `report_amr_regions.py`, `feature_preservation.py`, `call_structural_variants.py`, `annotate_reference.py`, `stratify_recovery.py` (recovery by replicon,
  MOB, size and AMR carriage). **Tests.** `test_amr_truth.py`, `test_derive_amr_truth.py`, `test_feature_preservation.py`, `test_stratify_recovery.py`, `test_report_amr_regions.py`.
- **Limits.** Mobile-element context and gene-neighbourhood preservation go only as far as the element and order checks; per-plasmid consistency of replicon, MOB and AMR is not cross-checked.

### 3.12 The recommender and the operational path

- **What.** A decision-support model recommends a tool for an isolate from **truth-free** features only (assembly statistics, depth and similar measured before any
  reconstruction); truth-derived fields are excluded by an enforced list. It is validated by holding out whole studies, clonal groups or species, compared with the
  global-best and organism-best baselines, checked for calibration, and it abstains when evidence is insufficient. Stage 8 reconstructs one new isolate using only the method
  the benchmark recommends, with a selection report.
- **Where.** `python/fit_recommendation_model.py`, `evaluate_recommender.py`, `leave_taxon_out.py`, `validate_recommendations.py`, `recommendation_model.py`,
  `select_operational_method.py`, `scripts/08_operational_reconstruct.sh`; PRs #49, #68. **Tests.** `test_fit_recommendation_model.py`, `test_recommendation_model_features.py`, `test_recommendation_validation.py`.
- **Limits.** Evidence so far is synthetic or from the shipped cohorts; evaluation on independent real studies is open.

### 3.13 Long-read and hybrid tracks

- **What.** Separate analysis tracks (short-read, long-read, hybrid) so tools are not ranked across technologies. Stage 7 runs native long-read and hybrid reconstruction
  (Flye with MOB-recon, Plassembler, Hybracter, Trycycler). A long-read-only assembler is not treated as a plasmid caller, because that would label chromosome as plasmid.
- **Where.** `scripts/07_long_read_reconstruct.sh`, `config/tool_capabilities.tsv` (`analysis_track`). **Tests.** `test_read_quality_ladder.py`, `test_depth_ladder.py` for the depth and quality ladders.

### 3.14 Metagenomics

- **What.** A separate workflow for graph-aware metagenomic predictions with its own endpoints and a physical mock-community control: validation of community manifests and tool
  intake, scoring, a synthetic-community design generator, truth-status labels, and an audit of comparability and leakage.
- **Where.** `python/metagenomics.py`, `audit_metagenomic_cohort.py`, `design_synthetic_communities.py`, `validate_metagenomic_intake.py`, `docs/METAGENOMICS.md`, `cohorts/metagenomics-*.tsv`.
  **Tests.** `test_metagenomics.py`, `test_metagenomic_classification.py`, `test_metagenomic_adversarial.py`, `test_metagenomics_real_cohort.py`.
- **Limits.** Independent metagenomic truth is limited; host assignment is separate from sequence recovery and is only partly evaluated.

### 3.15 Cohorts and data

- **What.** Locked, versioned cohorts: `public-v1`, `public-v2`, `public-v3` (98 isolates with provenance recorded from NCBI evidence), the PlasEval cohort `plaseval-ecoli53`
  (53 isolates), a contributed RefSeq/SRA candidate pool with a seeded, cluster-aware importer (PR #95), and the metagenomic cohorts. Tools for discovering, curating, validating and
  locking cohorts, a cross-cohort accession ledger, and a path for contributing a new isolate on a local git branch.
- **Where.** `cohorts/`, `python/discover_ncbi_cohort.py`, `curate_cohort.py`, `validate_cohort.py`, `build_accession_ledger.py`, `import_contributed_cohort.py`, `prepare_contribution.py`.
  **Tests.** `test_cohort_validation.py`, `test_accession_ledger.py`, `test_import_contributed_cohort.py`.
- **Candidate cohorts from publications (new).** The cohorts of three publications are adopted as *candidates*, not released benchmarks: plsMD filtered (80 isolates, 244 plasmids), plsMD novel (68 isolates, 269 plasmids, reported absent from PLSDB) and the MOB-suite benchmark (133 closed genomes, 377 plasmids), with the raw supplement tables, ENA run metadata, and a per-isolate ground-truth summary from the Teixeira repository. Every unresolved field is blank, never guessed: assembly accessions are not resolved, truth independence is unverified, and the caveats found while adopting them are written down (the plsMD filtered set is a subset of the MOB-suite set; 23 of 68 novel runs were public before the stated sequencing date; the novel runs fall in only 6 BioProjects, so they need dependence-aware holdouts). Files: `cohorts/candidates/PUBLICATION_COHORTS.md`, `python/build_publication_cohort_candidates.py`. **Tests.** `test_publication_cohort_candidates.py`.
- **Limits.** Cohorts are small and taxonomically narrow, mostly Gram-negative, with no plasmid-free isolates in the released cohort. The adopted candidates have no resolved assemblies yet.

### 3.16 Bring your own tool

- **What.** A user declares a tool in one manifest; PlasBench installs it, runs it, converts its output to the standard prediction files, scores it and reports it, with the same
  evaluation task and track rules as built-in tools. Commands: `plasbench tools list|validate|show|new|add|install`.
- **Where.** `python/user_tools.py`, `user_tool_adapter.py`, `user_tool_detect.py`, `user_tool_source.py`, `docs/ADDING_TOOLS.md`; PR #46 (several tasks, URL/local sources and `format = auto` added afterwards). **Tests.** `test_user_tools_manifest.py`, `test_user_tool_adapter.py`, `test_user_tool_detect.py`, `test_user_tool_source.py`, `test_user_tool_multitask.py`, `test_user_tool_stage.sh`, `test_user_tool_multitask_stage.sh`.

### 3.17 The HTML report

- **What.** One self-contained page with a left rail of views, the headline and recommendation first, then analytics in story order. It includes: the leaderboard and scorecard,
  radar fingerprints, precision-recall, a heat table of every metric, CPRR distributions and a forest plot, circular plasmid maps and an interactive map viewer, 3D views, the
  plasmid matrix with per-isolate FASTA download, the binning error profile (PlasEval cohort), the MultiQC-style QC table, the QUAST-style assembly heat table and the Alvis-style
  candidate tracks (new), ranking stability and reference evidence (new), the interactive AMR regions view and synteny ribbons (new: how each tool's records sit on a truth plasmid in order and orientation, with forward and reverse blocks, identity shading, filters and a details panel), and a "?" help dialog on every section. Nothing is hidden: a section with nothing to show says "Not run" and
  why, and every output file is registered with the section that shows it (section 7). Export to PDF with headless Edge or Chrome; a sample report built from offline demo data is
  linked from the README.
- **Where.** `python/build_html_report.py` and the `report_*` modules (section 6), `report_surfaces.py` (the registry), `docs/images/`. PRs #24-#38, #70, #94, #97.
  **Tests.** `test_report_javascript.py`, `test_visual_report.py`, `test_report_surfaces.py`, `test_report_reviewers.py`, `test_report_amr_regions.py`, `test_report_synteny.py`, `test_stage_dimensions.sh`.

### 3.18 The PlasBench window

- **What.** `plasbench ui` opens a local window (own browser profile, session key) to configure and run a benchmark, see what is already installed (databases, data, study
  folders), follow and resume runs that survive disconnects, edit `.gitignore`, set the leakage cutoff, check for updates and upgrade in one click, and read cohort details and help.
  A desktop icon launches it. Runs are sessions that can be listed, followed, resumed and reopened.
- **Studies and the working directory.** Every benchmark is a study folder in the working directory (`studies.py`, `workspace.py`): a validated workspace picker with recent folders, a lazy folder tree in the
  side panel, and `git init` in the **working directory** (one repository for all studies, with a managed ignore block that reaches into every study; a study with a repository of its own is left out).
  `study_manage.py` adds notes and tags, rename, copy, archive and restore (nothing is deleted), delete with the files and bytes shown first and the study's name typed back, and zip bundles with a
  manifest and checksums (import refuses path traversal, oversized bundles and damaged files). Design ideas follow GenoSuv's working folder; rename, copy, archive and bundles go beyond it.
- **Where.** `plasbench/` (`webui.py`, `appwindow.py`, `desktop.py`, `jobrunner.py`, `runprogress.py`, `updatecheck.py`, `studies.py`, `study_manage.py`, `workspace.py`, `gitops.py`); PRs #46, #47, #51, #72, #83, #86, #88, #89, #92, #96.
  **Tests.** `test_webui.py`, `test_job_survival.py`, `test_update_check.py`, `test_desktop_window.py`, `test_workspace_studies.py`, `test_study_manage.py`.

### 3.19 Installation, environments and databases

- **What.** `plasbench install-tools` installs registered tool profiles, each tool in its own pinned environment where it conflicts with others (MOB-suite, PlaScope, Plasmer, PlasmidHunter,
  Trycycler and Medaka); tool databases are kept once per machine; downloads are resumable; an optional tool that cannot install no longer fails `install-tools all`; an offline
  `--archive` install and a clear message for a DNS failure. Mash, samtools, barrnap and the annotation callers are wired into the install pipeline, and a drift test fails if
  code needs a binary the pipeline does not install.
- **Where.** `env/`, `scripts/install_latest.sh`, `scripts/00_setup.sh`, `python/tool_installer_registry.py`, `config/tool_installers.tsv`; PRs #15, #28, #29, #41-#43, #81, #82, #84, #85.
  **Tests.** `test_install_wiring.py`, `test_tool_installer_registry.py`, `test_container_hygiene.py`, `test_readme_install_paths.py`.

### 3.20 Reproducibility and provenance

- **What.** A run manifest records tool versions, database versions and dates, settings that change a ranking and checksums of the inputs (`write_manifest.py`); a conda lock file and a
  container pin the environment; `compare_runs.py` checks that a repeated run gives the same answer; every study can be its own git repository, with run folders, sequence and
  patient-level files kept out of git by rule and heavy files never tracked (PRs #53, #54, #56).
- **Tests.** `test_compare_runs.py`, `test_study_git_data_rules.py`, `test_git_heavy_files.py`, `test_container_hygiene.py`.
- **Limits.** Databases and some tools are not lock-pinned; an independent third-party re-run has not been made.

### 3.21 Performance and resources

- **What.** Per tool: wall-clock and CPU time, peak memory, success rate, resource failures (timeouts and out-of-memory kills, counted apart from tool failures), efficiency and scaling
  (`performance_summary.py`). Faster exact statistics, streaming and parallel downloads (PRs #16, #27), crash-safe and resumable stages 2 and 3 (PR #59), and a thread budget.
  Resource *estimates* for a full run are in the README; a measured pilot on the target hardware is open.
- **Tests.** `test_performance_summary.py`, `test_thread_budget.sh`, `test_parallel_execution.sh`, `test_assemble_crash_safe.sh`.

### 3.21a Guards on the run tables and on synthetic data

- **What.** Before anything is ranked, `run_consistency.py` checks that the score, status and failure tables describe the same runs: duplicate runs, a completed run with no score and
  no recorded failure, a score for a sample the status table does not list for a tool it does list (errors that stop aggregation unless `ALLOW_INCONSISTENT_RUNS=1`, when the report
  carries a banner), and a sample missing from the sheet or a tool the status table does not cover (warnings). A malformed or truncated score table stops with the file, line and
  value. `data_nature.py` refuses a run that mixes synthetic (`sample_origin = synthetic`) and real samples, and puts a "Demonstration data" banner on an all-synthetic report.
  `score_bins.py --pred-fasta` also counts the bases of a bin's contigs that align nowhere (`bin_unaligned_bp`, `lw_bin_f1_strict`) beside the headline.
- **Where.** `python/run_consistency.py`, `data_nature.py`, `score_bins.py`, `aggregate_results.py`, `build_html_report.py`; `docs/INDEPENDENT_VERIFICATION.md` section 12.
  **Tests.** `test_run_consistency.py`, `test_bin_unaligned.py`.

### 3.22 Review, evidence and documentation

- **What.** The independent review (`INDEPENDENT_REVIEW.md`, every claim tied to a file and line, with a checking test), the external review log (R1 to R9: who reviewed, what
  was found, what validated each answer), the 215-question assessment matrix, the 500-question and 108-question banks answered in `FAQ.md` and `FAQ_QUESTION_BANK.md`, the Scientific
  Guide and Methods, and this catalogue.
- **Tests.** `test_independent_review_ledger.py`, `test_external_review_log.py`, `test_reviewer_matrix.py`, `test_guide_docs.py`, `test_doc_versions.py`.

## 4. Following one number from raw data to the report

Take the dissimilarity between MOB-recon's bins and the truth for one isolate.

1. Stage 1 downloads the isolate's complete reference and reads. Stage 2 labels each reference sequence plasmid or chromosome (3.1).
2. Stage 3 checks the reads (QC gate), trims and assembles them, measures the candidate assemblies and picks one by a declared rule (3.9).
3. Stage 4 runs MOB-recon on the chosen assembly and writes its bins as a standard file.
4. Stage 5 maps the assembly contigs to the reference, matches each predicted bin to a true plasmid by globally optimal one-to-one matching, and exports the bins in PlasEval's
   input form. The dissimilarity is computed with repeat-aware pairing (3.8) and written to `scores.tsv`.
5. Stage 6 ranks the tools on their task's endpoint over the shared isolates with cluster-aware intervals (3.3, 3.4), re-ranks under changed choices and cohort subsets (3.5),
   compares the dissimilarity with the original PlasEval program if it is installed (3.8), and builds the report.
6. In the report the number appears in the leaderboard, in the binning error profile and in the agreement table, each with the file it came from (section 7).

