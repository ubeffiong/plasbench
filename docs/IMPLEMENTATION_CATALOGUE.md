# PlasBench implementation catalogue

**What this is.** One document that lists everything PlasBench implements: what each capability does, why it exists, which files hold it, which setting
turns it on, which output it writes, where the HTML report shows it, which test checks it, and what it does *not* do. It is written for a reviewer, a
funder, a collaborator or a new user who has not read the code and should not have to.

**Why it exists.** Reviewers repeatedly asked for things PlasBench already did, because the work was spread over a README, a FAQ, a scientific guide,
a methods file, a changelog and the code. This catalogue is the index to all of them. It does not replace them: each section links to the document that
explains the method in depth.

**Size at the time of writing:** 201 analysis modules, 28 registered tools and baselines (20 real tools), 216 registered
outputs, 54 run switches, 426 test files and 91 merged pull requests. Sections 5 to 9 are generated from the repository itself, and a
test (`test/test_implementation_catalogue.py`) fails if a module, a tool or an output is missing from them, so they cannot silently go out of date.

## 1. How to read this document

**Status words** (the same meanings as in the FAQ and in [the reviewer assessment matrix](REVIEWER_ASSESSMENT_MATRIX.md)):

| Word | Meaning |
|---|---|
| **Implemented and tested** | The code exists and a test in `test/` exercises it. |
| **Implemented, not validated on real data** | It works on constructed or synthetic cases; no real-cohort result exists yet. |
| **Provisional** | A setting or threshold that is a stated convention, not derived from data. It is recorded with every run. |
| **Open** | Not done. The reason is given. |

**What "tested" does and does not mean.** A test shows the code does what its author intended on the cases the test builds. It does not show that the
scientific claim holds on real data. The one thing that has been checked against an independent reference implementation is the PlasEval-style binning
dissimilarity (section 3.8). No real-data run of the whole tool set has been made yet; that is the largest open item and it is stated again in section 11.

**Descriptive versus scoring.** Many analyses here are *descriptive*: they add a table or a figure and never change a score or a ranking. Where that is
true the section says so. The scores and rankings come from a small, fixed core (sections 3.2 to 3.4).

**Where to start, by question**

| If you want to know... | Open |
|---|---|
| What PlasBench claims and does not claim | [`SCIENTIFIC_GUIDE.md`](SCIENTIFIC_GUIDE.md) |
| How every score is computed | [`METHODS.md`](METHODS.md) |
| The answer to a specific reviewer question | [`../FAQ.md`](../FAQ.md) and [`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md) |
| Who reviewed the project and what validated each answer | [`EXTERNAL_REVIEW_LOG.md`](EXTERNAL_REVIEW_LOG.md) |
| A sceptical outside view of the weaknesses | [`INDEPENDENT_REVIEW.md`](INDEPENDENT_REVIEW.md) |
| How to install and run it | [`../README.md`](../README.md) |
| What changed in each release | [`../CHANGELOG.md`](../CHANGELOG.md) |

## 2. The pipeline in one table

PlasBench benchmarks tools that reconstruct or classify plasmids from sequencing data. For each isolate it has a **complete reference genome of the same
isolate** (the truth), runs the tools on a short-read assembly built from the isolate's reads, and scores each tool's predicted plasmid sequence against
the truth. It never compares one isolate's plasmids with another's, and it is not a diagnostic or an epidemiological tool.

| Stage | Script | What happens | Main outputs |
|---|---|---|---|
| 0 | `scripts/00_setup.sh` | Create folders, check required tools and databases, offer to install what is missing | `results/` layout |
| 1 | `scripts/01_download.sh` | Download each isolate's complete reference and matched Illumina reads; a failed download is recorded and skipped, not fatal | `data/<sample>/`, `download_status.tsv` |
| 2 | `scripts/02_truth.sh` | Label every reference sequence plasmid or chromosome; annotate replicons, MOB, IS elements and AMR genes; detect multimers; measure repeat content and depth anomalies | `truth.tsv`, `truth_features.tsv`, label-scheme and audit tables |
| 3 | `scripts/03_assemble.sh` | **Short-read QC gate**, quality trimming, assembly, assembly measurement and **assembly selection policy** | `short_read_qc.tsv`, `assembly_candidates.tsv`, `assembly_status.tsv` |
| 4 | `scripts/04_run_tools.sh` | Run each enabled tool; skip samples rejected by QC or without an eligible assembly, saying why; write one standard predicted-plasmid FASTA per tool | `<sample>/pred_<tool>.plasmid.fasta`, `tool_status.tsv` |
| 5 | `scripts/05_score.sh` | Map each prediction to the reference with minimap2 and score it at every layer; export bins; analyse candidate multiplicity | `scores.tsv`, per-plasmid tables, bin tables, multiplicity tables |
| 6 | `scripts/06_aggregate.sh` | Combine everything into the leaderboard, statistics, robustness analyses, audits, the PlasEval comparison gate and the HTML report | `benchmark.leaderboard.*`, `benchmark.*.tsv`, the report |
| 7 | `scripts/07_long_read_reconstruct.sh` | Optional native long-read and hybrid reconstruction (Flye, Plassembler, Hybracter, Trycycler) | long-read and hybrid predictions |
| 8 | `scripts/08_operational_reconstruct.sh` | For one new isolate with no truth, run only the single method the benchmark recommends | operational reconstruction and selection report |

`scripts/run_all.sh` runs the stages in order (`bash scripts/run_all.sh 3 4 5` runs only those). The same pipeline can be driven from a window
(`plasbench ui`, section 3.18) or from the command line (`python -m plasbench run`).

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


## 5. The tools

The registry (`config/tool_capabilities.tsv`) lists 28 entries: 20 real tools and 8 baselines and stand-ins used to calibrate the scores (a baseline is a trivial predictor every real tool should beat). Each tool is bound to one evaluation task, and that task, not its output format, decides which endpoint ranks it.

| Tool | Method class | Track | Evaluation task | Validation status |
|---|---|---|---|---|
| `mob_recon` | binning | short_read | binning_reconstruction | adapter_tested |
| `platon` | classification | short_read | classification | adapter_tested |
| `plasmidspades` | reassembly | short_read | sequence_reassembly | adapter_tested |
| `gplas2_mob` | binning | short_read | binning_reconstruction | adapter_tested |
| `gplas2_external` | binning | short_read | binning_reconstruction | adapter_tested |
| `flye_mob_recon` | binning | long_read | binning_reconstruction | adapter_tested |
| `plassembler` | reassembly | hybrid | sequence_reassembly | untested |
| `hybracter_long` | reassembly | long_read | sequence_reassembly | adapter_tested |
| `hybracter_hybrid` | reassembly | hybrid | sequence_reassembly | adapter_tested |
| `trycycler_mob_recon` | binning | long_read | binning_reconstruction | adapter_tested |
| `genomad` | ml_classification | short_read | classification | adapter_tested |
| `plasme` | ml_classification | short_read | classification | adapter_tested |
| `rfplasmid` | ml_classification | short_read | classification | adapter_tested |
| `plasmidhunter` | ml_classification | short_read | classification | adapter_tested |
| `plasmer` | ml_classification | short_read | classification | adapter_tested |
| `plascope` | classification | short_read | classification | adapter_tested |
| `plasgraph2` | ml_classification | short_read | classification | adapter_tested |
| `plsmd` | reassembly | short_read | sequence_reassembly | adapter_tested |
| `plasbin_flow` | binning | short_read | binning_reconstruction | adapter_tested |
| `plasmidec` | classification | short_read | classification | adapter_tested |
| `mob_like` | binning | short_read | binning_reconstruction | not_applicable |
| `platon_like` | classification | short_read | classification | not_applicable |
| `spades_like` | reassembly | short_read | sequence_reassembly | not_applicable |
| `gplas_like` | binning | short_read | binning_reconstruction | not_applicable |
| `weak_like` | classification | short_read | classification | not_applicable |
| `baseline_coverage` | baseline | short_read | classification | not_applicable |
| `baseline_reference` | baseline | short_read | classification | not_applicable |
| `baseline_replicon` | baseline | short_read | classification | not_applicable |

## 6. Every module

201 modules in `python/`. Every one has a header that says what it is for; the one-line summary below is taken from it.

### Truth, references and cohorts

| Module | What it does |
|---|---|
| `audit_truth_labels.py` | Screen truth labels (PLASMID / CHROMOSOME) against replicon and MOB evidence. |
| `build_accession_ledger.py` | Regenerate the cross-cohort accession ledger from every released lock file. |
| `build_hybrid_truth.py` | Build a truth reference in-house via hybrid (long+short read) assembly, |
| `build_plasmid_reference_set.py` | One-time build step for classify_operational_plasmid.py's small, curated |
| `characterise_dataset.py` | Characterise each isolate of the cohort in one table: benchmark.dataset_features.tsv (plan C1). |
| `collect_truth_provenance.py` | record how each cohort truth assembly was built, |
| `compute_assembly_stats.py` | Compute per-sample reference-assembly stats for cohort QC anomaly flagging. |
| `compute_difficulty_features.py` | Compute per-isolate DIFFICULTY features from the truth reference (and, |
| `curate_cohort.py` | Turn candidate assembly/SRA pairs into a strict, reviewable PlasBench cohort. |
| `detect_dimers.py` | find truth plasmids that are tandem multimers of themselves (dimers, trimers and higher, up to 6 copies) and, |
| `discover_design_cohort.py` | find NCBI isolates that satisfy the headline |
| `discover_ncbi_cohort.py` | Discover strict candidate pairs from NCBI for one or more organism names. |
| `discover_plasmid_free.py` | Find plasmid-free negative controls: complete genomes with a single replicon, a long-read truth and a paired Illumina run. |
| `estimate_download.py` | Estimate what stage 1 is about to download, before it downloads it. |
| `fetch_ena_reads.py` | download a paired-end run's FASTQ from ENA, the European |
| `import_contributed_cohort.py` | turn the contributed RefSeq/SRA candidate pool |
| `import_external_benchmark.py` | Archive external benchmark evidence without merging it into PlasBench scores. |
| `init_local_sample.py` | Scaffold one local isolate: file layout, truth-table template, sheet row. |
| `label_schemes.py` | every truth replicon's label under the three labelling |
| `label_truth_evidence.py` | confirm each truth replicon's plasmid/chromosome |
| `long_read_support.py` | mean long-read depth per truth replicon. |
| `make_depth_ladder.py` | Create deterministic paired-read depth-ladder inputs for PlasBench. |
| `make_read_quality_ladder.py` | Create deterministic long-read read-quality-ladder inputs for PlasBench. |
| `make_truth.py` | turn an NCBI 'sequence_report.jsonl' (from `datasets download |
| `materialize_bmock12_truth.py` | Materialize the independently released BMock12 contig-level gold standard. |
| `measure_depth.py` | Measure paired-read coverage against the labelled reference length. |
| `measure_read_quality.py` | Measure mean per-base Phred quality for a long-read FASTQ. |
| `parse_teixeira2025_supplement.py` | One-time migration: turn Teixeira et al. 2025's Supplementary Table S1 |
| `prepare_contribution.py` | Validate a new-isolate contribution and stage it on a local git branch. |
| `read_pairing.py` | Pair paired-end FASTQ files in a directory by common naming conventions. |
| `reference_evidence_audit.py` | one row per isolate: how far can its truth assembly be trusted, and why? |
| `repeat_content.py` | Per-replicon k-mer repeat content of the truth reference (descriptive only). |
| `resolve_ncbi_accessions.py` | Resolve BioSample-only candidates to assembly_accession/sra_run via NCBI. |
| `review_candidate_cohort.py` | Create evidence-preserving candidate and balanced-shortlist tables. |
| `scorable_truth.py` | which true-plasmid bases CAN a prediction be scored on? |
| `simulate_reads.py` | Simulate short+long reads from a REAL, complete reference assembly, for |
| `summarize_depth_ladder.py` | Summarize PlasBench score rows from a deterministic depth-ladder experiment. |
| `summarize_read_quality_ladder.py` | Summarize PlasBench score rows from a deterministic read-quality-ladder |
| `truth_depth_anomalies.py` | Advisory truth QC: coverage-anomaly regions from benchmark-read depth. |
| `truth_exclusion_sensitivity.py` | the headline with and without the evidence-based truth exclusion (audit AU-051). |
| `truth_marker_overlap.py` | which tools share a database with the evidence that labelled the truth? |
| `truth_provenance.py` | how was each truth assembly built, and how far can it |
| `validate_cohort.py` | Validate a PlasBench cohort locally and against linked NCBI metadata. |
| `validate_local_inputs.py` | Check every local input before a run spends hours on it. |
| `validate_truth_table.py` | Check a truth table against the reference it describes, before scoring uses it. |

### Input control and assembly

| Module | What it does |
|---|---|
| `assembler_sensitivity.py` | does the tool ranking depend on the assembly the tools were given? |
| `assembly_adequacy.py` | Per-sample assembly adequacy: can the assembly support plasmid reconstruction at all? |
| `assembly_qc_gate.py` | flag assemblies that look mixed or contaminated before a |
| `assembly_selection.py` | Assembly selection policy: which short-read assembly the tools are run on, chosen by a declared rule and never by benchmark score. |
| `run_quast_diagnostics.py` | Optional QUAST supplementary diagnostics for ONE tool's predicted-plasmid |
| `short_read_qc.py` | Short-read QC and eligibility gate: PASS, WARN or REJECT before a sample is assembled or any tool is run. |

### Scoring (per sample and tool)

| Module | What it does |
|---|---|
| `alignment_accuracy.py` | Nucleotide-level accuracy and missing-region counts for one (sample, tool). |
| `baseline_predictors.py` | trivial reference points that every benchmarked |
| `bin_agreement.py` | Contig-level bin agreement in the spirit of PlasEval (BMC Bioinformatics 2024). |
| `bin_quality.py` | Quality-tier bin yield and homogeneity / completeness for one (sample, tool). |
| `call_structural_variants.py` | Call structural discordances between predicted records and truth replicons. |
| `candidate_multiplicity.py` | Candidate multiplicity and redundancy: what happens when a tool reports several sequences for one plasmid. |
| `contig_classification.py` | contig-level plasmid/chromosome classification |
| `contig_crosscheck.py` | an independent second scorer for the contig layer. |
| `copy_number.py` | Plasmid copy-number (PCN) concordance: tool-estimated vs truth, descriptive only. |
| `derive_amr_truth.py` | Draft an AMR truth table from reference annotation output (opt-in, NOT curated). |
| `feature_preservation.py` | Biological feature preservation and gene-order conservation (NGOC) for one (sample, tool). |
| `import_mobilome_evidence.py` | Import MAP-style mobilome annotations as non-scoring PlasBench evidence. |
| `mask_accuracy.py` | Blank nucleotide-accuracy rates where the truth cannot support them. |
| `matching.py` | maximum-weight one-to-one matching (rectangular Hungarian). |
| `mob_to_gplas_classifier.py` | Convert MOB-recon plasmid membership into a validated gplas classifier TSV. |
| `normalize_metagenomic_classifier.py` | Normalize probability-bearing contig classifiers for the PlasBench meta track. |
| `plasbin_flow_adapter.py` | Adapt a pre-computed PlasBin-flow output TSV to PlasBench's standard form. |
| `plaseval_gate.py` | Comparison gate: does PlasBench agree with the original PlasEval program on this run's bins? |
| `plaseval_replication.py` | Score the PlasEval paper's published plasmid bins with PlasBench, and compare with the original program. |
| `promote_amr_truth.py` | Promote a REVIEWED AMR truth draft to the curated truth_amr.tsv (plan B4): a deliberate human step, with a record of who took it. |
| `score_amr_placement.py` | does a tool put each AMR gene copy on the right plasmid? |
| `score_bins.py` | Globally optimal predicted-bin versus true-plasmid matching from PAF. |
| `score_plasmids.py` | base-level scoring of plasmid-reconstruction predictions. |
| `validate_amr_truth.py` | Validate curated, versioned plasmid AMR truth annotations. |
| `validate_gplas_classifier.py` | Validate a gplas classifier TSV against the exact eligible GFA nodes. |
| `validate_orthogonal_evidence.py` | Validate an auditable optional orthogonal-validation evidence table. |
| `validate_structural_evidence.py` | Validate source-backed structural evidence without inferring biological closure. |

### Aggregation, statistics and robustness

| Module | What it does |
|---|---|
| `aggregate_results.py` | combine per-sample score rows into a per-tool |
| `clonal_groups.py` | group near-identical (clonal) isolates. |
| `compare_published.py` | Compare a PlasBench run with the outcomes a publication reported for the same isolates. |
| `compare_runs.py` | Reproducibility: do repeated runs of the same benchmark give the same answer? |
| `compare_scoring_methods.py` | One-off BLASTN-vs-minimap2 scoring cross-check (Phase E, Part 15 of the |
| `composite_score.py` | Optional, descriptive five-dimension view of each tool, with gates and weight sensitivity. |
| `database_containment.py` | is each truth plasmid already inside a tool's own |
| `database_provenance.py` | Tool and database provenance (plan E2 and E3): which database version and source stand behind each tool, and how far the tool has been validated. |
| `evaluate_warnings.py` | does each operational warning actually predict a failed |
| `flag_cohort_outliers.py` | Advisory-only statistical outlier flagging over a cohort's assembly stats. |
| `flag_database_overlap.py` | flag sample x tool pairs where the truth genome |
| `freeze_prereg.py` | freeze and verify the pre-registered scoring parameters. |
| `headline_design.py` | the benchmark's pre-specified headline design. |
| `leave_taxon_out.py` | does the recommender transfer to a genus or phylum it never |
| `merge_bin_metrics.py` | Join per-sample bin summaries into the canonical PlasBench score table. |
| `merge_pr_metrics.py` | Join per-sample PR-curve summaries into the canonical PlasBench score |
| `merge_tables.py` | Merge per-run shard TSVs (same header) into one table, in a stable order. |
| `metric_registry.py` | the one place that says what each metric is FOR. |
| `performance_summary.py` | Computational performance per tool: speed, memory, reliability, efficiency and scaling. |
| `plasbench_common.py` | Small helpers shared by the python/ scripts. |
| `power_analysis.py` | How large a difference between two tools can this cohort actually detect? |
| `rank_sensitivity.py` | how much does the leaderboard depend on scoring choices? |
| `ranking_stability.py` | does the leaderboard survive removing a study or a species? |
| `resampling.py` | exact means, cluster bootstrap and sign-flip permutation tests. |
| `scenario_tags.py` | Tag each isolate with a benchmark scenario and report tool performance per scenario. |
| `simulate_validation.py` | does PlasBench's cluster-aware statistics do what it claims? |
| `stratify_recovery.py` | Stratify per-plasmid recovery by replicon, mobility (MOB), size and AMR carriage. |
| `study_groups.py` | Shared source_study grouping for leave-one-study-out validation. |
| `tool_capabilities.py` | Read the versioned PlasBench tool-capability registry. |
| `tool_installer_registry.py` | Inspect and validate the install contract for every supported adapter. |
| `user_tool_adapter.py` | Convert a user tool's output into PlasBench's prediction files, driven by its manifest's [output] mapping. |
| `user_tool_detect.py` | Recognise what a user tool wrote, by CONTENT, for `[output] format = auto` (docs/ADDING_TOOLS.md, "Auto-detect"). |
| `user_tool_source.py` | Where a user tool comes from: download it (https only), or locate it on this computer (docs/ADDING_TOOLS.md, "Where the tool comes from"). |
| `user_tools.py` | User-added tools: declare a plasmid tool in one manifest and PlasBench installs, runs, scores and reports it. |
| `write_manifest.py` | Write a portable, machine-readable provenance manifest for a PlasBench run. |
| `write_operational_override_report.py` | Write a selection report for an explicit --tool override. |

### Recommender and operational path

| Module | What it does |
|---|---|
| `build_candidate_quality_dataset.py` | Build an auditable candidate-quality training dataset from a PlasBench run. |
| `classify_operational_plasmid.py` | Nearest-reference screen for the OPERATIONAL (no-truth) path. |
| `evaluate_recommender.py` | does recommending a tool per isolate beat simply using |
| `fit_recommendation_model.py` | Fit (and leave-one-study-out validate) the decision-support recommendation |
| `recommendation_model.py` | Shared pure-stdlib toolkit for the decision-support recommendation model. |
| `select_operational_method.py` | Create conservative method recommendations and reusable per-isolate candidates. |
| `select_unknown_sample.py` | Select an already-produced candidate for an operational sample without truth. |
| `validate_recommendations.py` | Leave-one-study-out validation of simple benchmark method rankings. |

### Metagenomics

| Module | What it does |
|---|---|
| `audit_metagenomic_cohort.py` | Audit a community manifest for comparability, coverage, and leakage risks. |
| `design_synthetic_communities.py` | Build a deterministic, truth-labelled community simulation design. |
| `metagenomics.py` | Validate, score, and report graph-aware metagenomic plasmid predictions. |
| `validate_metagenomic_intake.py` | Validate a candidate external tool/dataset before it enters PlasBench work. |

### HTML report

| Module | What it does |
|---|---|
| `build_enterprise_view.py` | Map measured PlasBench results into the enterprise dashboard's data model. |
| `build_explorer_view.py` | Map measured benchmark output into the reconstruction evidence explorer. |
| `build_guide_toc.py` | keep the Scientific Guide's contents lists in step with its |
| `build_html_report.py` | Build the self-contained HTML dashboard emitted after benchmark aggregation. |
| `build_implementation_catalogue.py` | write docs/IMPLEMENTATION_CATALOGUE.md. |
| `build_visualization_data.py` | Create bounded, reference-coordinate data for the offline visual explorer. |
| `export_report_pdf.py` | save the HTML report as one PDF with a headless Edge or Chrome. |
| `refresh_sample_report.py` | every generated demo report replaces the sample report in the repository. |
| `report_3d.py` | the server side of the three interactive 3D views in the report. |
| `report_aliases.py` | Legacy report section ids and where they live now. |
| `report_amr_regions.py` | resistance-region comparison: does each tool keep the AMR genes AND the mobile context around them, on the right plasmid? |
| `report_collapse.py` | fold the tables that a figure now draws into closed <details>, in one place. |
| `report_common.py` | shared building blocks for the report modules added in the HTML overhaul. |
| `report_compare_apply.py` | turn the report's metric-by-tool tables into comparison tables (python/report_compare_table.py), keeping each original table. |
| `report_compare_table.py` | the comparison table: a QUAST-style grid of metrics (rows, in groups) by tools (columns) that opens into a side panel. |
| `report_condense.py` | shorten the report page from the inside: sub-tabs, windowed long tables, consistent table typography. |
| `report_dimensions.py` | HTML sections for the further benchmark dimensions, built from stage-6 tables. |
| `report_fig_binerrors.py` | Binning error profile: why a binner scores as it does, not only how much. |
| `report_fig_complexity.py` | FIGURE 'Does isolate complexity explain performance?' (section fig-complexity). |
| `report_fig_facets.py` | stratified small-multiples heatmaps: tools across, strata down, one panel per metric, one shared 0-1 colour bar. |
| `report_fig_fingerprint.py` | FIGURE 'Fingerprint of each tool' (section fig-radar), compact small-multiples version. |
| `report_fig_heatmap.py` | FIGURE 'Performance of every tool across every metric' (section fig-heatmap). |
| `report_fig_ladder.py` | the reconstruction ladder: from contigs to a verified plasmid, and which score judges each step. |
| `report_fig_landscape.py` | the 3D landscape figure: accuracy, completeness and structural fidelity (section id fig-landscape). |
| `report_fig_pr.py` | the interactive precision-recall figure (section `fig-pr`). |
| `report_fig_presence.py` | a clustered presence/absence matrix of the truth plasmids and their features, with prevalence bars and a tool overlay. |
| `report_fig_radar.py` | FIGURE 'Fingerprint of each tool' (section fig-radar): a radar chart per analysis track, one polygon per tool. |
| `report_fig_stats.py` | two statistical figures of the report: CPRR distributions and a forest plot of CPRR differences. |
| `report_fig_synteny.py` | the redesigned synteny view (section learn-synteny): one comparison at a time, truth plasmid on top, one tool's records below. |
| `report_figures.py` | the figure modules of the report, injected in one place. |
| `report_help.py` | a "?" help button on every section and every tab of the report, opening one shared help dialog. |
| `report_help_text.py` | the words behind the "?" help button on every section and tab of the HTML report. |
| `report_info.py` | move the report's explanatory notes into hover/focus "info" popovers. |
| `report_isolates.py` | the isolate filter, and "which tool recovered which plasmid". |
| `report_layout.py` | the report's page shell: top bar, left rail of views, one view at a time, analytics in story order. |
| `report_learnings.py` | HTML sections for the evaluation additions learned from PlasEval, plsMD and GAEMR. |
| `report_maps.py` | CGView / Proksee-style circular plasmid maps for the PlasBench report. |
| `report_merge.py` | fold related analyses into one container section with tabs, deleting nothing. |
| `report_names.py` | reader-facing tool names, applied when the report is built. |
| `report_post.py` | the post-processing steps that reshape the finished report page, in one fixed order. |
| `report_prune.py` | a section or tab that holds only a "Not run" notice is not shown; what was not run is listed once, in Run metadata. |
| `report_question_bank.py` | HTML report sections that answer reviewer |
| `report_readqc_panel.py` | The short-read QC panel: a MultiQC-style, interactive view of the QC gate, with a side panel for every sample. |
| `report_recommend_evidence.py` | the evidence panel under the operational recommendation (plan D5). |
| `report_reviewers.py` | Three dashboards for the report: short-read QC, assembly selection and reconstruction multiplicity. |
| `report_scorecard.py` | a weighted benchmark SCORECARD shown beside the existing composite. |
| `report_scoring_spec.py` | HTML report sections for the scoring specification and |
| `report_surfaces.py` | the registry of every pipeline output and its place in the report. |
| `report_svg.py` | small, dependency-free SVG toolkit for the PlasBench report. |
| `report_synteny.py` | synteny ribbons: how each tool's records sit on a truth plasmid, in order and orientation. |
| `report_wiring.py` | wires pipeline outputs that the report did not show into HTML, and used to group the navigation (now python/report_layout.py). |
| `report_workflow.py` | the PlasBench workflow figure, drawn once as docs/images/workflow.svg for the README. |

### Protein and annotation

| Module | What it does |
|---|---|
| `annotate_proteins.py` | Create provenance-aware bacterial protein annotations for a FASTA file. |
| `annotate_reference.py` | Derive replicon, MOB, IS, and AMR annotations for a reference by calling |

### Other

| Module | What it does |
|---|---|
| `audit_three_class_scoring.py` | One-off three-class scoring audit (Phase E, Part 14 of the sibling-repo |
| `build_publication_cohort_candidates.py` | Build CANDIDATE ledgers for three published plasmid-reconstruction cohorts. |
| `build_publication_cohorts.py` | Build the publication cohorts: the isolates a published benchmark used, as runnable PlasBench cohorts. |
| `build_published_outcomes.py` | Turn the supplementary data of published plasmid benchmarks into long-format "published outcome" tables. |
| `build_selection_report.py` | write cohorts/<name>.selection.json: how a cohort was selected. |
| `check_prediction_fasta.py` | Stage-4 well-formedness check of a tool's prediction FASTA (audit AU-035). |
| `data_nature.py` | Is this run made of synthetic (demo) data, real data, or a mix? A mix is refused, and a synthetic run says so inside its report. |
| `download_progress.py` | How far a read download has got, for the run log. |
| `intake.py` | Bring your own isolates: get the sheet right, point at your folders, check that PlasBench can see and use what you have. |
| `make_demo_readqc.py` | SYNTHETIC short-read QC and assembly-candidate tables for the six isolates of the offline demonstration. Never for real data. |
| `multiqc_note.py` | The one plain-language note on MultiQC versus PlasBench's own QC panel, shared by every place that shows it. |
| `performance_drivers.py` | What drives per-plasmid reconstruction accuracy? A multivariable, study-clustered regression per tool. |
| `plsdb_novelty.py` | How novel is each truth plasmid against PLSDB, and does recovery depend on it? |
| `prereg_admin.py` | read, confirm and change PlasBench's pre-registered scoring decisions, and keep a record of who decided what and when. |
| `qc_pilot.py` | A short-read QC pilot on real reads: the first part of each run's paired FASTQ files, measured with short_read_qc.py. |
| `relabel_cohort_provenance.py` | Recompute a cohort sheet's truth_assembly_strategy and truth_polish_reads from the sheet's own assembly_method and assembly_sequencing_technology columns. |
| `resolve_contributed_cohort.py` | verify importer candidates against NCBI, run the |
| `run_consistency.py` | Do the run tables agree before anything is ranked? |
| `run_multiqc.py` | Optional MultiQC companion: run `multiqc` over the fastp (and QUAST) outputs of a run into results/multiqc/. Never fails the run. |
| `run_status.py` | What is this run doing right now, and why might it look stuck? |
| `setting_ranges.py` | The one table of what each numeric Scoring-decision setting accepts (config/setting_ranges.tsv), and the checks built on it. |


## 7. Every output file and where the report shows it

216 registered pipeline outputs, each with the module that writes it and where the report shows it. `shown` means the report draws or tabulates it; `partly` means it is available as a download or is summarised.

| Output | Written by | Report section | Shown | What it holds |
|---|---|---|---|---|
| `assembly_candidates.tsv` | assembly_selection.py | learn-assembly | shown | Assembly candidates and the selection: Per candidate assembly: contigs, N50, length, GC, read support, eligibility, and which was selected and why. |
| `assembly_status.tsv` | 03_assemble.sh | health | partly | How each assembly ended: Failures are counted in the health summary. |
| `benchmark.accuracy.masked.tsv` | mask_accuracy.py | accuracy-dimension | partly | Accuracy with low-confidence truth masked: Quoted beside the accuracy table. |
| `benchmark.accuracy.tsv` | alignment_accuracy.py | accuracy-dimension | shown | Nucleotide accuracy: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.amr_placement.tsv` | score_amr_placement.py | amr-placement | shown | AMR placement: Per-tool correct-plasmid rate bars beside the 3D ring tower; table collapsed under the view. |
| `benchmark.assembler_sensitivity.tsv` | assembler_sensitivity.py | learn-stability | partly | Assembler sensitivity: Per task: does the leader change with the assembly? Written only when ASSEMBLER_SENSITIVITY_RUNS is set. |
| `benchmark.assembly_adequacy.tsv` | assembly_adequacy.py | learn-adequacy | shown | Assembly adequacy: Table. |
| `benchmark.assembly_qc.tsv` | assembly_qc_gate.py | assembly-quality | shown | Assembly quality gate, all samples: The gate result of every sample is tabulated. |
| `benchmark.bin_quality.tsv` | bin_quality.py | bin-quality | shown | Bin quality tiers: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.candidate_intervals.tsv` | candidate_multiplicity.py | learn-multiplicity | shown | Where each candidate lies on each plasmid: Drawn as tracks of candidates against the reference plasmid. |
| `benchmark.candidate_multiplicity.tsv` | candidate_multiplicity.py | learn-multiplicity | shown | Candidates per plasmid: Per truth plasmid: candidates, best and combined coverage, redundancy, outcome. |
| `benchmark.candidates.tsv` | candidate_multiplicity.py | learn-multiplicity | shown | Every predicted record: Per candidate: relationship to the others, chimera partners, off-target and unmapped bases. |
| `benchmark.clonal_groups.tsv` | clonal_groups.py | cohort-qc | shown | Clonal groups of isolates: The groups and their members are listed under the cohort QC flags. |
| `benchmark.cohort_qc_flags.tsv` | flag_cohort_outliers.py | cohort-qc | shown | Cohort QC flags: Table. |
| `benchmark.composite.tsv` | composite_score.py | composite | shown | Five-dimension composite: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.composite_sensitivity.tsv` | composite_score.py | composite | shown | Composite weight sensitivity: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.contig_crosscheck.tsv` | contig_crosscheck.py | contig-layer | shown | Contig cross-check: Marker on each 3D bar, per-tool rows in the detail panel (CSV export), full table collapsed under the view. |
| `benchmark.copy_number.tsv` | copy_number.py | learn-copynumber | shown | Copy number: Table. |
| `benchmark.cprr_threshold_sweep.tsv` | aggregate_results.py | leaderboard | partly | CPRR threshold sweep: Only the area under the sweep (cprr_auc) is shown, in the leaderboard; the per-threshold table is a downloadable file. |
| `benchmark.database_containment.tsv` | database_containment.py | database-membership | shown | Recovery inside and outside tool databases: Table. |
| `benchmark.database_overlap.tsv` | flag_database_overlap.py | database-membership | shown | Truth plasmids present in tool databases: Table. |
| `benchmark.database_provenance.tsv` | database_provenance.py | database-membership | shown | Tool and database provenance: Validation tier, database version, source, release date and checksum of each tool, in Truth plasmids in tool databases. |
| `benchmark.dataset_features.tsv` | characterise_dataset.py | isolate-difficulty | shown | Dataset characteristics: One row per isolate; every column marked as knowable without a reference or not (Isolate difficulty tab). |
| `benchmark.feature_preservation.tsv` | feature_preservation.py | feature-preservation | shown | Feature preservation: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.headline_design.tsv` | headline_design.py | headline-design | shown | Headline design (units of analysis): Table. |
| `benchmark.input_consistency.tsv` | run_consistency.py | leaderboard | partly | Run tables that disagree: Empty when the tables agree; otherwise a banner above the ranking and this list. |
| `benchmark.input_fingerprint.json` | aggregate_results.py | leaderboard | partly | Input fingerprint: Which score table and tool set the leaderboard was ranked from; the report refuses a leaderboard paired with different scores. |
| `benchmark.label_scheme_summary.tsv` | label_schemes.py | label-schemes | shown | Labelling scheme summary: Table. |
| `benchmark.label_schemes.tsv` | label_schemes.py | label-schemes | shown | Labelling schemes, merged: Table. |
| `benchmark.leaderboard.md` | aggregate_results.py | files | shown | Leaderboard as Markdown: Linked from the Run files panel. |
| `benchmark.leaderboard.tsv` | aggregate_results.py | leaderboard | shown | Leaderboard: Ranked table. |
| `benchmark.leave_taxon_out.tsv` | leave_taxon_out.py | taxon-transfer | shown | Leave-taxon-out transfer: Table. |
| `benchmark.manifest.json` | write_manifest.py | method | partly | Benchmark manifest: Settings appear in the method section. |
| `benchmark.metadata_completeness.tsv` | aggregate_results.py | metadata-completeness | shown | Metadata completeness: Table. |
| `benchmark.missing_regions.tsv` | alignment_accuracy.py | accuracy-dimension | shown | Missing regions: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.ngoc.tsv` | feature_preservation.py | feature-preservation | shown | Gene order conservation: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.outcome_states.tsv` | aggregate_results.py | outcome-states | shown | Run outcome states: Table. |
| `benchmark.paired_comparisons.tsv` | aggregate_results.py | statistics | shown | Paired tool comparisons: Table. |
| `benchmark.performance.tsv` | performance_summary.py | performance | shown | Computational performance: Comparison table (python/report_compare_table.py): metrics by tools shaded by rank, with a side panel; the plain table is kept in a closed fold. |
| `benchmark.performance_drivers.json` | performance_drivers.py | learn-drivers | shown | Performance-drivers models: Per tool: plasmids, studies, R2, the size effect, drivers left out and warnings; or why it was not estimable. |
| `benchmark.performance_drivers.tsv` | performance_drivers.py | learn-drivers | shown | Performance drivers: Per tool and term: effect on per-plasmid recovery, 95% interval, status and the variance the driver explains. |
| `benchmark.plaseval_gate.json` | plaseval_gate.py | learn-agreement | shown | PlasEval gate verdict: PASS, FAIL, PARTIAL, NOT_RUN or NO_DATA, with the tolerance, the original's commit and the counts. |
| `benchmark.plaseval_gate.tsv` | plaseval_gate.py | learn-agreement | shown | Comparison with the original PlasEval program: Per isolate and tool: PlasBench's dissimilarity and best-match F1 against the original program's. |
| `benchmark.plsdb_novelty.json` | plsdb_novelty.py | learn-novelty | shown | PLSDB novelty summary: PLSDB file and provenance, thresholds, class counts and caveats. |
| `benchmark.plsdb_novelty.tsv` | plsdb_novelty.py | learn-novelty | partly | PLSDB novelty per truth plasmid: Best PLSDB record, coverage, identity and class (known, related, novel) for each truth plasmid; summarised by tool in the novelty table. |
| `benchmark.plsdb_novelty_recovery.tsv` | plsdb_novelty.py | learn-novelty | shown | Recovery by PLSDB novelty: Per tool and class: plasmids, studies, mean completeness, recovered share, and the gap to known with a study-clustered interval. |
| `benchmark.power.tsv` | power_analysis.py | power | shown | Statistical power: Table. |
| `benchmark.published_comparison.json` | compare_published.py | learn-published | shown | Published-comparison verdict: Per study and metric: the status, tool-order agreement, tools with no counterpart and the caveats. |
| `benchmark.published_comparison.tsv` | compare_published.py | learn-published | shown | Comparison with published outcomes: Per tool, metric and stratum: matched pairs, published mean, PlasBench mean, difference, correlation, agreement. |
| `benchmark.published_comparison_pairs.tsv` | compare_published.py | learn-published | partly | Every matched published pair: Each isolate or plasmid with the published value and PlasBench's; summarised in the comparison table. |
| `benchmark.rank_robustness.tsv` | rank_sensitivity.py | rank-robustness | shown | Rank robustness: Table. |
| `benchmark.ranking_stability.tsv` | ranking_stability.py | learn-stability | shown | Ranking stability: Per task: does the leader or the order change when one study or species is removed, or every study weighs the same. |
| `benchmark.recommendation_model.card.md` | fit_recommendation_model.py | recommendations | partly | Recommendation model card: Quoted in the recommendations. |
| `benchmark.recommendation_model.json` | fit_recommendation_model.py | recommendations | partly | Recommendation model: Described by its model card. |
| `benchmark.recommendation_validation.tsv` | validate_recommendations.py | validation | shown | Recommendation validation: Table. |
| `benchmark.recommendations.tsv` | select_operational_method.py | recommendations | shown | Recommendations: Table. |
| `benchmark.recommender_arms.tsv` | evaluate_recommender.py | recommender-eval | shown | Recommender: three ways of choosing a tool: Single best vs organism vs feature-conditioned, with calibration and abstention, in the detail tab. |
| `benchmark.recommender_eval.tsv` | evaluate_recommender.py | recommender-eval | shown | Recommender evaluation: Profile selector and summary beside the 3D strategy scene; table in a detail tab. |
| `benchmark.recommender_feature_correlation.tsv` | evaluate_recommender.py | recommender-eval | partly | Recommender: feature correlation: Used for the correlated-feature warning; the table is not tabulated. |
| `benchmark.recommender_holdouts.tsv` | evaluate_recommender.py | recommender-eval | shown | Recommender: holdout designs: Isolate, study, clonal-group, study-and-clonal and species holdouts, with verdicts, in the detail tab. |
| `benchmark.recommender_knn.tsv` | evaluate_recommender.py | recommender-eval | partly | Recommender: nearest-neighbour detail: Per-recommendation uncertainty and abstention feed the evidence panel; the detail table is not tabulated. |
| `benchmark.recommender_regret.tsv` | evaluate_recommender.py | recommender-eval | shown | Recommender regret per isolate: Each isolate is a column of bars in the 3D strategy scene (recommender, single best, oracle) with regret gaps; rows in the detail panel. |
| `benchmark.recommender_sensitivity.tsv` | evaluate_recommender.py | recommender-eval | partly | Recommender: sensitivity to K, scaling and features: Summarised in the evaluation verdict; the table is not tabulated. |
| `benchmark.recommender_verdict.json` | evaluate_recommender.py | recommender-eval | shown | Recommender verdict: Verdict text. |
| `benchmark.recovery_by_replicon.tsv` | stratify_recovery.py | replicon-recovery | shown | Recovery by replicon type: Table. |
| `benchmark.reference_evidence_audit.tsv` | reference_evidence_audit.py | learn-refaudit | shown | Reference evidence audit: Per isolate: how far the truth assembly can be trusted, with every reason. |
| `benchmark.reference_independence.tsv` | aggregate_results.py | headline-design | shown | Reference independence: Per tool and evaluation-independence class. |
| `benchmark.reference_tiers.tsv` | aggregate_results.py | headline-design | partly | Reference tiers: Tier counts are shown. |
| `benchmark.repeat_content.tsv` | repeat_content.py | learn-truthqc | shown | Repeat content of the truth: Table. |
| `benchmark.report.html` | build_html_report.py | None | shown | This report: The report itself. |
| `benchmark.reproducibility_tools.tsv` | compare_runs.py | reproducibility | shown | Reproducibility across runs: Table. |
| `benchmark.scenario_performance.tsv` | scenario_tags.py | scenarios | shown | Performance by scenario: Table. |
| `benchmark.scenarios.tsv` | scenario_tags.py | scenarios | partly | Scenario tags: Used to group the scenario table. |
| `benchmark.scoring_spec.md` | report_scoring_spec.py | files | shown | Scoring specification (text): Linked from the Run files panel. |
| `benchmark.species.tsv` | aggregate_results.py | headline-design | partly | Species of the cohort: Species counts are shown. |
| `benchmark.species_sensitivity.tsv` | ranking_stability.py | learn-stability | shown | Leave-one-species-out rankings: Table. |
| `benchmark.stats_validation.tsv` | simulate_validation.py | stats-validation | shown | Statistical validation by simulation: Table. |
| `benchmark.stats_validation_by_studies.tsv` | simulate_validation.py | stats-validation | shown | Statistical validation by number of studies: Table. |
| `benchmark.stratified.tsv` | select_operational_method.py | stratified | shown | Performance by stratum: Table. |
| `benchmark.study_sensitivity.tsv` | ranking_stability.py | learn-stability | shown | Leave-one-study-out rankings: Table. |
| `benchmark.tool_agreement.tsv` | bin_agreement.py | learn-agreement | shown | Tool-versus-tool dissimilarity: Matrix. |
| `benchmark.truth_depth_anomalies.tsv` | truth_depth_anomalies.py | learn-truthqc | shown | Depth anomalies of the truth: Table. |
| `benchmark.truth_exclusion_sensitivity.tsv` | truth_exclusion_sensitivity.py | truth-label-audit | shown | Headline with and without the truth exclusion: Table. |
| `benchmark.truth_label_audit.tsv` | audit_truth_labels.py | truth-label-audit | shown | Truth-label audit: Table. |
| `benchmark.truth_marker_overlap.tsv` | truth_marker_overlap.py | truth-label-audit | shown | Truth-marker databases shared with tools: Table. |
| `benchmark.truth_provenance.tsv` | truth_provenance.py | headline-design | shown | Truth provenance: Tier shown with the design. |
| `benchmark.warning_eval.tsv` | evaluate_warnings.py | recommender-eval | shown | Evaluation of the warnings: Tab in the recommender detail panel (CSV export), table collapsed under the view. |
| `benchmark.warnings.tsv` | evaluate_warnings.py | recommender-eval | partly | Warnings issued per isolate: Counted in the warning evaluation. |
| `benchmark.{track}.leaderboard.md` | aggregate_results.py | files | shown | Per-track leaderboard as Markdown: Linked from the Run files panel. |
| `benchmark.{track}.leaderboard.tsv` | aggregate_results.py | leaderboard | shown | Per-track leaderboard: One table per track. |
| `download_status.tsv` | 01_download.sh | health | partly | How each download ended: Failures are counted in the health summary. |
| `multiqc/multiqc_data/{any}` | run_multiqc.py | learn-readqc | partly | MultiQC data folder: MultiQC's own parsed data, kept beside its report and listed in the Artifact explorer. |
| `multiqc/multiqc_report.html` | run_multiqc.py | learn-readqc | shown | MultiQC report (optional companion): Linked from the QC panel as the Full MultiQC report (never embedded); written only when multiqc is installed and MULTIQC_REPORT is not off. |
| `multiqc/multiqc_run.json` | run_multiqc.py | learn-readqc | shown | MultiQC step status: Whether the optional MultiQC step ran, its version and any failure; the QC panel's MultiQC note reads it. |
| `orthogonal_validation.summary.json` | validate_orthogonal_evidence.py | orthogonal-evidence | shown | Orthogonal-evidence summary: Summarised. |
| `quast_diagnostics.tsv` | run_quast_diagnostics.py | quast-diagnostics | shown | QUAST diagnostics, merged: Table. |
| `run_manifest.json` | write_manifest.py | method | shown | Run manifest (versions, settings): Method and reproducibility section. |
| `samples.tsv` | curate_cohort.py | samples | shown | Sample sheet: Sample metadata drives the strata and the drill-down. |
| `score_failures.tsv` | 05_score.sh | outcome-states | shown | Runs that could not be scored: Listed with the reason. |
| `scores.tsv` | score_plasmids.py | scores | shown | Scores, one row per sample and tool: Table with filters and download. |
| `selected_candidates/{any}` | select_unknown_sample.py | selected | shown | Selected candidate downloads: Linked from the selection cards. |
| `short_read_qc.provenance.json` | make_demo_readqc.py | learn-readqc | shown | Marker: the QC tables are synthetic: Written only by the offline demo's generator; the QC panel then carries a Synthetic note. |
| `short_read_qc.tsv` | short_read_qc.py | learn-readqc | shown | Short-read QC metrics: The QC panel (MultiQC-style): General statistics with inline bars, per-metric distributions with the threshold lines, a side panel per sample with each metric as a gauge against its threshold, and the earlier table under All values. Not measured in this run is said when the table is absent. |
| `short_read_qc_status.tsv` | short_read_qc.py | learn-readqc | shown | Short-read QC decision: PASS, WARN or REJECT per sample and the action taken: Decisions and reasons in the QC panel. |
| `tool_outcomes.tsv` | aggregate_results.py | outcome-states | partly | Outcome of each tool run: Folded into outcome states. |
| `tool_status.tsv` | 04_run_tools.sh | outcome-states | shown | How each run ended: Every run's status and reason. |
| `{any}.log` | scripts/*.sh | None | partly | Run logs: Kept for debugging. It is listed in the Artifact explorer only. |
| `benchmark.leaderboard.tsv::Base-level accuracy` | aggregate_results.py | leaderboard | shown | Leaderboard columns: Base-level accuracy: Mean and interval columns of the leaderboard, as a comparison table (per-isolate values in its side panel) with the plain table folded; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Bins` | aggregate_results.py | bin-diagnostics | shown | Leaderboard columns: Bins: Mean bin F1 and clustering agreement are shown; the counts are in the download; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Calibration` | aggregate_results.py | baselines-calibration | shown | Leaderboard columns: Calibration: Shown for tools that give probabilities; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Contig layer` | aggregate_results.py | contig-layer | shown | Leaderboard columns: Contig layer: Compared with the reference layer; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Database leakage` | aggregate_results.py | database-membership | shown | Leaderboard columns: Database leakage: Recovery inside and outside the tool database; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Plasmid recovery` | aggregate_results.py | leaderboard | shown | Leaderboard columns: Plasmid recovery: Recall, circular and perfect recovery and CPRR are in the leaderboard and graded-tiers comparison tables (the plain tables are folded under them); every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Predicted-sequence burden` | aggregate_results.py | robustness-main | shown | Leaderboard columns: Predicted-sequence burden: Unmapped, off-truth and multi-mapped shares and the precision gap, in Ranking confidence; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Rank and basis` | aggregate_results.py | leaderboard | shown | Leaderboard columns: Rank and basis: Rank, basis and significance are columns of the leaderboard; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Run counts` | aggregate_results.py | leaderboard | shown | Leaderboard columns: Run counts: Completed and failed runs are shown; the failure sub-counts are in the download; every column is under More columns of the leaderboard. |
| `benchmark.leaderboard.tsv::Zero-plasmid isolates` | aggregate_results.py | zero-plasmid | shown | Leaderboard columns: Zero-plasmid isolates: The negative-control section; every column is under More columns of the leaderboard. |
| `scores.tsv::Agreement` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Agreement: Best-match F1 and dissimilarity are shown as means; the cost components are in the download; every column is in the column-group table under All scores. |
| `scores.tsv::Bins` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Bins: Bin F1, splits and merges are shown; the other bin columns are in the download; every column is in the column-group table under All scores. |
| `scores.tsv::Calibration` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Calibration: PR-AUC, Brier score and calibration error are shown for tools that give probabilities; every column is in the column-group table under All scores. |
| `scores.tsv::Confusion and abstention` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Confusion and abstention: MCC, F2, F0.5 and abstention are shown as means; per-row values are in the download; every column is in the column-group table under All scores. |
| `scores.tsv::Contig layer` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Contig layer: Contig F1 and MCC are shown; the contig counts are in the download; every column is in the column-group table under All scores. |
| `scores.tsv::Core` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Core: Base counts, precision, recall and F1 are columns of the score table; every column is in the column-group table under All scores. |
| `scores.tsv::Diagnostics` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Diagnostics: Unmapped and ambiguous predicted bases are shown; alignment counts are in the download; every column is in the column-group table under All scores. |
| `scores.tsv::Graded recovery` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Graded recovery: Mean recall at 50 and 90 percent and the outcome totals are shown; per-row counts are not; every column is in the column-group table under All scores. |
| `scores.tsv::Identity` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Identity: Sample, tool and track label every row; every column is in the column-group table under All scores. |
| `scores.tsv::Recovery` | score_plasmids.py and the merge scripts | scores | shown | scores.tsv columns: Recovery: Recall, AMR and circular recovery are shown; the counts behind them are in the download only; every column is in the column-group table under All scores. |
| `{sample}/annotation_provenance.json` | annotate_reference.py | replicon-recovery | partly | Annotation database versions: Database versions are not repeated in the report. It is listed in the Artifact explorer only. |
| `{sample}/assembly.fasta` | 07_long_read_reconstruct.sh | None | partly | Long-read or hybrid assembly: Input of long-read tools. It is listed in the Artifact explorer only. |
| `{sample}/assembly_data_report.jsonl` | 01_download.sh | None | partly | NCBI assembly data report: Source of truth metadata. It is listed in the Artifact explorer only. |
| `{sample}/assembly_qc.tsv` | assembly_qc_gate.py | assembly-quality | shown | Assembly quality gate: The pass or fail of each assembly and its reasons are tabulated. |
| `{sample}/assembly_stats.tsv` | compute_assembly_stats.py | assembly-quality | shown | Assembly statistics (N50, contigs, GC): Size, contigs, N50 and GC of each assembly are tabulated. |
| `{sample}/contig_labels.kmer.tsv` | contig_crosscheck.py | contig-layer | shown | Contig labels by k-mer (independent scorer): Compared with the alignment labels in the cross-check. |
| `{sample}/contig_labels.tsv` | contig_classification.py | contig-layer | shown | Truth label of each contig: The contig layer scores against it; excluded contigs are counted. |
| `{sample}/contigs.fasta` | 03_assemble.sh | samples | partly | Short-read assembly: Contigs appear in the sequence and bin views. |
| `{sample}/contigs_vs_ref.paf` | 05_score.sh | contig-layer | partly | Contigs mapped to the reference: Gives contig labels; alignments are not listed. |
| `{sample}/difficulty_features.tsv` | compute_difficulty_features.py | isolate-difficulty | shown | Isolate difficulty features: Listed per isolate. |
| `{sample}/fastp.html` | 03_assemble.sh | None | partly | Read trimming report (HTML): Trimming log. It is listed in the Artifact explorer only. |
| `{sample}/fastp.json` | 03_assemble.sh | None | partly | Read trimming report: Trimming log. It is listed in the Artifact explorer only. |
| `{sample}/label_schemes.tsv` | label_schemes.py | label-schemes | shown | Label under each labelling scheme: Merged into the labelling-scheme table. |
| `{sample}/observed_depth.tsv` | measure_depth.py | isolate-difficulty | partly | Observed read depth: Gives the depth stratum; not listed. |
| `{sample}/observed_read_quality.tsv` | measure_read_quality.py | isolate-difficulty | partly | Observed read quality: Gives the quality stratum; not listed. |
| `{sample}/plasmid_assembly_coverage.tsv` | assembly_adequacy.py | learn-adequacy | partly | How much of each truth plasmid the assembly contains: Summarised as assembly adequacy; the per-plasmid coverage is not listed. |
| `{sample}/plasmid_similarity.tsv` | compute_difficulty_features.py | isolate-difficulty | partly | Similarity between truth plasmids: Summarised as a difficulty signal. |
| `{sample}/reference.fna` | 01_download.sh | samples | partly | Truth plasmid sequences: Drawn in the sequence view. |
| `{sample}/reference.full.fna` | 01_download.sh | samples | partly | Complete reference genome: Used by the sequence view and scoring. |
| `{sample}/selected_candidate/{any}` | select_unknown_sample.py | selected | shown | Selected candidate sequence: Download link on the selection card. |
| `{sample}/selection_report.json` | select_unknown_sample.py | selected | shown | Operational selection report: Each card translates it into a decision. |
| `{sample}/sequence_report.jsonl` | 01_download.sh | None | partly | NCBI sequence report: Source of truth molecule types. It is listed in the Artifact explorer only. |
| `{sample}/simulation_provenance.json` | simulate_reads.py | None | partly | Read simulation provenance: Present only for simulated reads. It is listed in the Artifact explorer only. |
| `{sample}/structural_events.tsv` | call_structural_variants.py | samples | partly | Structural events versus the truth: Counts appear in the drill-down; the events are listed there per tool. |
| `{sample}/structural_summary.tsv` | call_structural_variants.py | samples | shown | Structural summary: Shown in the drill-down. |
| `{sample}/truth.corrections.tsv` | detect_dimers.py | label-schemes | shown | Dimer and multimer corrections to the truth: Every correction is listed with the dimers section. |
| `{sample}/truth.nonchromosomal.tsv` | label_schemes.py | label-schemes | partly | Truth, non-chromosomal labelling scheme: Counted in the labelling-scheme comparison; rows are not listed. |
| `{sample}/truth.scored.tsv` | label_truth_evidence.py | label-schemes | partly | Truth after evidence labelling (ambiguous removed): Counted in the labelling-scheme comparison; rows are not listed. |
| `{sample}/truth.tsv` | make_truth.py / build_hybrid_truth.py | samples | shown | Truth table (molecule labels): Sample drill-down and every score are computed from it; label audit summarises it. |
| `{sample}/truth_amr.draft.tsv` | derive_amr_truth.py | None | partly | Auto-derived AMR truth draft: A draft for curation, never scored. It is listed in the Artifact explorer only. |
| `{sample}/truth_amr.scored.tsv` | 05_score.sh | None | partly | AMR truth restricted to scored plasmids: Intermediate of the scorer. It is listed in the Artifact explorer only. |
| `{sample}/truth_amr.tsv` | validate_amr_truth.py | fig-presence | shown | Curated truth AMR genes: Drawn as the AMR gene-class and gene blocks of the feature matrix (prevalence bars, per-plasmid table); gene counts and placement also appear in AMR placement. |
| `{sample}/truth_circular.scored.tsv` | 05_score.sh | None | partly | Circular truth restricted to scored plasmids: Intermediate of the scorer. It is listed in the Artifact explorer only. |
| `{sample}/truth_circular.tsv` | make_truth.py | scores | partly | Truth circular plasmids: Appears as circular-truth recovery in the score table. |
| `{sample}/truth_depth.tsv` | 02_truth.sh | None | partly | Read depth of the truth: Input of the depth-window step. It is listed in the Artifact explorer only. |
| `{sample}/truth_depth_anomalies.tsv` | truth_depth_anomalies.py | learn-truthqc | shown | Depth-anomaly regions on the truth: The regions are marked on the depth strip; the per-replicon summary is tabulated. |
| `{sample}/truth_depth_anomaly_summary.tsv` | truth_depth_anomalies.py | learn-truthqc | shown | Depth-anomaly summary per replicon: Merged into the depth-anomaly table. |
| `{sample}/truth_depth_windows.tsv` | truth_depth_anomalies.py | learn-truthqc | shown | Read-depth windows along the truth: Drawn as a depth strip per sample with the anomalous regions marked. |
| `{sample}/truth_features.tsv` | annotate_reference.py | fig-presence | shown | Annotated features of the reference: Drawn as the replicon, MOB and other feature blocks of the feature matrix (with a per-plasmid table); the labels also feed recovery by plasmid type (replicon-recovery) and the strata of the facet heatmaps. |
| `{sample}/truth_labels.tsv` | label_truth_evidence.py | truth-label-audit | partly | Evidence label per truth replicon: Evidence-label counts are summarised; the per-replicon rows are not. |
| `{sample}/truth_long_read_depth.tsv` | 02_truth.sh | learn-copynumber | partly | Long-read depth of truth replicons: Gives the truth copy number; the depths are not listed. |
| `{sample}/truth_long_reads.paf` | 02_truth.sh | None | partly | Long reads mapped to the truth: Intermediate. It is listed in the Artifact explorer only. |
| `{sample}/truth_plasmid_windows.paf` | 02_truth.sh | None | partly | Window alignments on truth plasmids: Intermediate. It is listed in the Artifact explorer only. |
| `{sample}/truth_proteins.provenance.json` | annotate_proteins.py | None | partly | Truth protein annotation provenance: Recorded for reproducibility. It is listed in the Artifact explorer only. |
| `{sample}/truth_proteins.tsv` | annotate_proteins.py | feature-preservation | partly | Truth proteins: Used as the reference for feature preservation; proteins are not listed. |
| `{sample}/truth_provenance.json` | build_hybrid_truth.py | headline-design | partly | Truth provenance (how the truth was built): Summarised as the truth-provenance tier in the headline design. |
| `{sample}/truth_reads.bam` | 02_truth.sh | None | partly | Reads mapped to the truth: Intermediate. It is listed in the Artifact explorer only. |
| `{sample}/truth_reads.bam.bai` | 02_truth.sh | None | partly | Index of the truth read mapping: Intermediate. It is listed in the Artifact explorer only. |
| `{sample}/truth_repeat_content.tsv` | repeat_content.py | learn-truthqc | shown | Repeat content of the truth: Merged into the repeat-content table. |
| `{sample}/truth_repeat_regions.tsv` | repeat_content.py | plasmid-maps | shown | Repeat regions of the truth: Drawn as the repeat track of the circular plasmid maps. |
| `{sample}/truth_scorable.provenance.json` | scorable_truth.py | None | partly | Scorable-truth provenance: Provenance. It is listed in the Artifact explorer only. |
| `{sample}/truth_scorable.tsv` | scorable_truth.py | learn-adequacy | partly | Which truth bases the assembly can reach: Gives the recall ceiling; the table is not listed. |
| `{sample}/visualization/alignment_blocks.json` | build_visualization_data.py | samples | shown | Alignment blocks for the sequence view: Drawn; the Synteny ribbons section joins each truth plasmid to each tool's records in order and orientation. |
| `{sample}/visualization/structural_calls.json` | call_structural_variants.py | samples | shown | Structural calls for the sequence view: Drawn. |
| `{sample}/visualization/structural_metrics.tsv` | build_visualization_data.py | samples | partly | Structural metrics for the sequence view: Drawn as marks, not listed. |
| `{sample}/{sample2}.mob_classifier.provenance.json` | mob_to_gplas_classifier.py | None | partly | MOB classifier provenance: Provenance. It is listed in the Artifact explorer only. |
| `{sample}/{sample2}.mob_classifier.tsv` | mob_to_gplas_classifier.py | None | partly | MOB classifier table (gplas2 seed): Intermediate. It is listed in the Artifact explorer only. |
| `{sample}/pred_{tool}.bins.tsv` | 04_run_tools.sh | bin-diagnostics | partly | Predicted bins (contig to bin): Scored as bin metrics; membership shown in the bin view. |
| `{sample}/pred_{tool}.candidates.fasta` | 04_run_tools.sh | baselines-calibration | partly | Scored candidate sequences: Source of the PR curve. |
| `{sample}/pred_{tool}.evidence.tsv` | 04_run_tools.sh | orthogonal-evidence | partly | Structural evidence supplied by the tool: Validated, summarised. |
| `{sample}/pred_{tool}.plasmid.fasta` | 04_run_tools.sh | samples | partly | Standardised plasmid prediction: Compared against the truth in the sequence view; sequences are not tabulated. |
| `{sample}/pred_{tool}.scores.tsv` | 04_run_tools.sh | baselines-calibration | partly | Per-record probability: Gives PR-AUC and calibration. |
| `{sample}/pred_{tool}.structural_evidence.validation.json` | validate_structural_evidence.py | orthogonal-evidence | partly | Validation of the supplied structural evidence: Summarised. |
| `{sample}/{tool}.accuracy.tsv` | alignment_accuracy.py | accuracy-dimension | partly | Nucleotide accuracy: Merged into benchmark.accuracy. |
| `{sample}/{tool}.amr_placement.tsv` | score_amr_placement.py | amr-placement | shown | AMR gene placement: Every gene copy is a marker on that tool's ring in the 3D ring tower, with a detail panel and CSV export; the AMR regions section draws each resistance region with its mobile context and one lane per tool. |
| `{sample}/{tool}.bestmatch.tsv` | bin_agreement.py | learn-agreement | partly | Best-match precision and recall: Merged into scores and summarised. |
| `{sample}/{tool}.bin_matches.tsv` | score_bins.py | bin-diagnostics | shown | Bin to plasmid matches: Drawn as the bin flow. |
| `{sample}/{tool}.bin_quality.tsv` | bin_quality.py | bin-quality | partly | Bin quality tier: Merged into benchmark.bin_quality. |
| `{sample}/{tool}.bin_summary.tsv` | score_bins.py | bin-diagnostics | partly | Bin summary: Counts appear in the bin diagnostics. |
| `{sample}/{tool}.calibration.tsv` | score_plasmids.py | baselines-calibration | shown | Calibration bins: Pooled into the calibration view. |
| `{sample}/{tool}.candidates_vs_ref.paf` | 05_score.sh | baselines-calibration | partly | Candidates mapped to the reference: Source of the PR curve. |
| `{sample}/{tool}.contig_classification.tsv` | contig_classification.py | contig-layer | partly | Contig-level classification: Scored; contigs are not listed. |
| `{sample}/{tool}.copy_number.tsv` | copy_number.py | learn-copynumber | partly | Copy number per matched bin: Merged into the copy-number table. |
| `{sample}/{tool}.cprr.tsv` | score_bins.py | bin-diagnostics | partly | Correct plasmid reconstruction per plasmid: Rate and counts shown; per-plasmid rows are not. |
| `{sample}/{tool}.dissim.tsv` | bin_agreement.py | learn-agreement | partly | Bin dissimilarity: Merged into scores and summarised. |
| `{sample}/{tool}.feature_preservation.tsv` | feature_preservation.py | feature-preservation | partly | Feature preservation: Merged into benchmark.feature_preservation. |
| `{sample}/{tool}.missing_regions.tsv` | alignment_accuracy.py | accuracy-dimension | partly | Truth regions the tool missed: Merged into benchmark.missing_regions. |
| `{sample}/{tool}.ngoc.tsv` | feature_preservation.py | feature-preservation | partly | Gene order conservation: Merged into benchmark.ngoc. |
| `{sample}/{tool}.per_plasmid.tsv` | score_plasmids.py | per-plasmid-detail | shown | Result for each truth plasmid: One row per truth plasmid and tool, with filters. |
| `{sample}/{tool}.plaseval.{any}` | bin_agreement.py | None | partly | PlasEval export files: For the external PlasEval tool. It is listed in the Artifact explorer only. |
| `{sample}/{tool}.plasmid_outcomes.tsv` | score_bins.py | per-plasmid-detail | shown | Outcome class of each truth plasmid: The outcome class of each truth plasmid is a column of the per-plasmid table. |
| `{sample}/{tool}.pr_curve.tsv` | score_plasmids.py | samples | shown | Precision-recall curve: Drawn in the drill-down. |
| `{sample}/{tool}.pr_summary.tsv` | score_plasmids.py | baselines-calibration | partly | Precision-recall summary: PR-AUC is merged into scores. |
| `{sample}/{tool}.pred_vs_ref.all.paf` | 05_score.sh | rank-robustness | partly | All prediction alignments, unfiltered: Re-scored for ranking robustness. |
| `{sample}/{tool}.pred_vs_ref.paf` | 05_score.sh | samples | partly | Prediction mapped to the reference: Drawn as alignment blocks. |
| `{sample}/{tool}.proteins.provenance.json` | annotate_proteins.py | None | partly | Predicted protein provenance: Provenance. It is listed in the Artifact explorer only. |
| `{sample}/{tool}.proteins.tsv` | annotate_proteins.py | feature-preservation | partly | Predicted proteins: Compared with the truth proteins. |
| `{sample}/{tool}.quast_diagnostics.tsv` | run_quast_diagnostics.py | quast-diagnostics | partly | QUAST diagnostics: Merged into quast_diagnostics. |
| `{sample}/{tool}.replicon_hits.tsv` | 04_run_tools.sh | None | partly | Replicon marker hits (baseline): Input of the replicon baseline. It is listed in the Artifact explorer only. |

## 8. Every run switch

These `RUN_*` settings in `config/config.sh` turn an analysis on or off (1 = on). Other settings (thresholds, paths, thread counts) are documented in the same file.

| Switch | Default | What it controls |
|---|---|---|
| `RUN_TRUTH_LABEL_EVIDENCE` | `1` | see the comment block above it in config/config.sh |
| `RUN_DIMER_DETECTION` | `1` | see the comment block above it in config/config.sh |
| `RUN_RECOMMENDER_EVAL` | `1` | see the comment block above it in config/config.sh |
| `RUN_AMR_PLACEMENT` | `1` | see the comment block above it in config/config.sh |
| `RUN_ASSEMBLY_QC_GATE` | `1` | see the comment block above it in config/config.sh |
| `RUN_TRUTH_EXCLUSION_SENSITIVITY` | `1` | see the comment block above it in config/config.sh |
| `RUN_MOB_RECON` | `1` | see the comment block above it in config/config.sh |
| `RUN_PLATON` | `1` | see the comment block above it in config/config.sh |
| `RUN_PLASMIDSPADES` | `1` | see the comment block above it in config/config.sh |
| `RUN_GPLAS2_MOB` | `0` | see the comment block above it in config/config.sh |
| `RUN_GPLAS2_EXTERNAL` | `0` | see the comment block above it in config/config.sh |
| `RUN_GENOMAD` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASME` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASGRAPH2` | `0` | see the comment block above it in config/config.sh |
| `RUN_RFPLASMID` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASMIDHUNTER` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASMER` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASCOPE` | `0` | see the comment block above it in config/config.sh |
| `RUN_FLYE_MOB_RECON` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASSEMBLER` | `0` | see the comment block above it in config/config.sh |
| `RUN_HYBRACTER_LONG` | `0` | see the comment block above it in config/config.sh |
| `RUN_HYBRACTER_HYBRID` | `0` | see the comment block above it in config/config.sh |
| `RUN_TRYCYCLER_MOB_RECON` | `0` | see the comment block above it in config/config.sh |
| `RUN_RECOMMENDATION_MODEL` | `0` | see the comment block above it in config/config.sh |
| `RUN_SCORABLE_TRUTH` | `1` | see the comment block above it in config/config.sh |
| `RUN_REFERENCE_ANNOTATION` | `1` | see the comment block above it in config/config.sh |
| `RUN_DIMENSION_ANALYSES` | `1` | see the comment block above it in config/config.sh |
| `RUN_DIFFICULTY_FEATURES` | `0` | see the comment block above it in config/config.sh |
| `RUN_QUAST_DIAGNOSTICS` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASMID_NOVELTY_CLASSIFICATION` | `0` | see the comment block above it in config/config.sh |
| `RUN_CONTIG_CLASSIFICATION` | `1` | see the comment block above it in config/config.sh |
| `RUN_CONTIG_CROSSCHECK` | `1` | see the comment block above it in config/config.sh |
| `RUN_DATABASE_CONTAINMENT` | `1` | see the comment block above it in config/config.sh |
| `RUN_BASELINE_COVERAGE` | `1` | see the comment block above it in config/config.sh |
| `RUN_BASELINE_REFERENCE` | `1` | see the comment block above it in config/config.sh |
| `RUN_BASELINE_REPLICON` | `0` | see the comment block above it in config/config.sh |
| `RUN_PROTEIN_ANNOTATION` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLSMD` | `0` | see the comment block above it in config/config.sh |
| `RUN_BIN_AGREEMENT` | `1` | see the comment block above it in config/config.sh |
| `RUN_CANDIDATE_MULTIPLICITY` | `1` | see the comment block above it in config/config.sh |
| `RUN_REFERENCE_EVIDENCE_AUDIT` | `1` | per-isolate reference evidence audit (python/reference_evidence_audit.py) |
| `RUN_RANKING_STABILITY` | `1` | leave-one-study/species-out ranking stability (python/ranking_stability.py) |
| `RUN_PLASEVAL_GATE` | `auto` | see the comment block above it in config/config.sh |
| `RUN_COPY_NUMBER` | `1` | see the comment block above it in config/config.sh |
| `RUN_ASSEMBLY_ADEQUACY` | `1` | see the comment block above it in config/config.sh |
| `RUN_REPEAT_CONTENT` | `1` | see the comment block above it in config/config.sh |
| `RUN_TRUTH_DEPTH_ANOMALIES` | `0` | see the comment block above it in config/config.sh |
| `RUN_PLASBIN_FLOW` | `0` | see the comment block above it in config/config.sh |
| `RUN_STATS_VALIDATION` | `0` | see the comment block above it in config/config.sh |
| `RUN_RANK_SENSITIVITY` | `1` | see the comment block above it in config/config.sh |
| `RUN_PUBLISHED_COMPARISON` | `auto` | see the comment block above it in config/config.sh |
| `RUN_PLASMIDEC` | `0` | see the comment block above it in config/config.sh |
| `RUN_PERFORMANCE_DRIVERS` | `1` | see the comment block above it in config/config.sh |
| `RUN_PLSDB_NOVELTY` | `auto` | see the comment block above it in config/config.sh |

## 9. History: every merged change

91 merged pull requests, in order. Each is a reviewed, tested change; the title says what it did.

| PR | Merged | What it did |
|---|---|---|
| #5 | 2026-11-08 | Fix leaderboard ranking fairness and add robustness diagnostics |
| #6 | 2026-11-08 | feat(diagnostics): AMR truth drafting, recovery by replicon/MOB, QUAST report section |
| #7 | 2026-11-08 | Research design: binning-F1 headline, CPRR, reference tiers, evidence labels, species balance |
| #8 | 2026-11-08 | fix(audit): truth labelling, ranking integrity, leakage visibility, rank robustness; Scientific Guide |
| #9 | 2026-11-08 | fix(report): list a tool that failed on every sample in benchmark.species.tsv |
| #10 | 2026-11-08 | Close the review gaps: accuracy, feature preservation, bin quality, performance, power, scenarios, optional composite; FAQ for the 500-question bank |
| #11 | 2026-11-08 | Question-bank gaps, verified database dates, and the public-v3 cohort |
| #12 | 2026-11-08 | Metric rubric: contig-level classification with MCC, ARI, assembly-aware binning, micro averaging, database membership |
| #13 | 2026-11-08 | docs: remove capabilities that are not part of the benchmarking pipeline |
| #14 | 2026-11-08 | Panel examination and scoring specification: NCBI-label primary, pre-registration, outcome states, recommender evaluation |
| #15 | 2026-11-08 | fix(install): wire mash, samtools, barrnap and the annotation callers into the install pipeline |
| #16 | 2026-11-08 | perf: faster exact statistics, shared helpers, leaner report builder |
| #17 | 2026-11-08 | Contig cross-check scorer, ENA read fallback and demo coverage |
| #19 | 2026-11-08 | plsMD adapter, replicon baseline, bin agreement and truth-QC analyses (PlasEval/GAEMR learnings) |
| #20 | 2026-11-08 | Finish the plsMD/PlasEval/GAEMR follow-ups: PlasBin-flow adapter, PlasEval cross-check, ISFinder evidence, repeat_rich fix |
| #21 | 2026-11-08 | Track-specific endpoints, CPRR robustness, README evaluation framework |
| #22 | 2026-11-09 | Re-point review ledger rows after #21 |
| #23 | 2026-11-09 | docs(readme): make the step-by-step lab guide findable again |
| #24 | 2026-11-09 | HTML report overhaul: plasmid maps, weighted scorecard, workflow figure, data inventory and wiring fixes |
| #25 | 2026-11-09 | Interactive plasmid map viewer, 3D views for contig layer, recommender and AMR placement, collapsed tables, workflow figure in the README |
| #26 | 2026-11-09 | Report overhaul: left-rail views, merged analytics, figure gallery, info tooltips, full PDF export |
| #27 | 2026-11-09 | Performance audit fixes: faster matching, exact statistics, streaming, parallel downloads |
| #28 | 2026-11-09 | Keep downloads for future runs; catch tools that cannot start |
| #29 | 2026-11-09 | MOB-suite in its own pinned environment; databases kept once per machine |
| #30 | 2026-11-09 | Load the two interactive explorers when first shown (page opens about 3x faster) |
| #31 | 2026-11-10 | Report order for readers who are deciding: recommendation second, one set of numbers, phone menu, explorers out of the Appendix, display names at build time |
| #32 | 2026-11-10 | Section review: one home per result, reconstruction-only recommendation, Not-run sections listed once |
| #34 | 2026-11-10 | Out-of-memory failures are resource failures; PDF export from WSL |
| #35 | 2026-11-10 | Help "?" button on every section and tab, and the 3D-chart fix |
| #36 | 2026-11-10 | Add a sample report (offline demo data) and link it from the README |
| #37 | 2026-11-10 | Per-isolate FASTA download button in the plasmid matrix; matrix and report-card notes as tooltips |
| #38 | 2026-11-10 | Every generated demo report replaces the sample report |
| #39 | 2026-11-10 | Release v0.2.0 |
| #40 | 2026-11-15 | README: link to open the sample report, directly under the title |
| #41 | 2026-11-13 | Isolated environments for PlaScope, Plasmer and PlasmidHunter; release v0.2.1 |
| #42 | 2026-11-13 | Trycycler and Medaka in their own environment; release v0.2.2 |
| #43 | 2026-11-13 | Resumable database downloads, Platon auto-download, CheckM fix, README Step 7d; release v0.2.3 |
| #44 | 2026-11-13 | Fix the doubled size in the download resume message |
| #45 | 2026-11-13 | Quiet the fake server's disconnect tracebacks in test_fetch_ena_parallel |
| #46 | 2026-11-13 | v0.3.0: bring your own tool, and the PlasBench window (plasbench ui) |
| #47 | 2026-11-14 | Ship the plasbench ui page (plasbench/data/ui.html was gitignored) |
| #48 | 2026-11-14 | Reference figures folder (local images, tracked README) |
| #49 | 2026-11-14 | Recommendation model: truth-free features only |
| #50 | 2026-11-14 | Strict eligibility: primary analysis unavailable when no reference qualifies |
| #51 | 2026-11-14 | PlasBench window: desktop icon, studies, one install folder, terminal, session log, help, cohort details |
| #52 | 2026-11-14 | Structured evidence record for every reference |
| #53 | 2026-11-15 | chore: keep sample-level data out of git by default |
| #54 | 2026-11-15 | fix(git): keep per-sample folders, sequence and clinical files out of study repositories |
| #55 | 2026-11-15 | Pre-registration: proposed values, draft state and a strict freeze |
| #56 | 2026-11-15 | Git: never track heavy files; edit .gitignore from the window |
| #57 | 2026-11-15 | Statistics core: six-unit minimum and exact permutation tests (stacked on #55) |
| #58 | 2026-11-15 | Statistics validated by simulation (stacked on #57) |
| #59 | 2026-11-15 | Crash-safe stage 3; faster, parallel, timed and resumable stage 2 |
| #60 | 2026-11-15 | Console colours: warnings yellow, errors red |
| #61 | 2026-11-15 | Runs never stop silently: every stop is reported on the console |
| #62 | 2026-11-15 | Rank sensitivity covers alignment length, headline endpoints and CPRR thresholds (stacked on #58) |
| #63 | 2026-11-15 | More truth audits: flags, higher multimers, marker-database overlap (stacked on #62) |
| #64 | 2026-11-15 | Metric registry and the evaluation ladder (stacked on #63) |
| #65 | 2026-11-15 | B2: burden of unverified predicted sequence in the leaderboard and report |
| #66 | 2026-11-15 | B3: SV-PRR beside CPRR |
| #67 | 2026-11-15 | C1: dataset characteristics (truth-free vs truth-derived columns) |
| #68 | 2026-11-15 | C2: single best vs organism vs feature-conditioned recommender |
| #69 | 2026-11-15 | D1: numeric heatmap gains SV-PRR and burden columns |
| #70 | 2026-11-15 | D2-D7: radar, complexity, outcome matrix, recommendation evidence, map identity and resistance brackets, TP/FP encodings |
| #71 | 2026-11-15 | README: document the features merged in #61-#70 |
| #72 | 2026-11-15 | Window: show and reuse what is already installed (databases, data and study folders) |
| #73 | 2026-11-15 | Make main green; AMR context, real-binary check, provenance and tiers, integration audit, and the end-to-end review fixes |
| #74 | 2026-11-15 | Release v0.4.0 |
| #75 | 2026-11-15 | Three explicit evaluation tasks: classification, binning reconstruction, sequence reassembly |
| #76 | 2026-11-15 | Second external review: P0 and P1 fixes |
| #77 | 2026-11-15 | AMR placement by output type, reference independence, full statistics simulation |
| #78 | 2026-11-15 | Full interval-method simulation results and write-up |
| #80 | 2026-11-15 | Release v0.4.0: changelog and release notes |
| #81 | 2026-11-16 | fix(install): explain a DNS or network failure and add an offline --archive install |
| #82 | 2026-11-16 | fix(launcher): do not abort on conda activate scripts that read unset variables |
| #83 | 2026-11-16 | fix(ui): open the window in its own clean browser profile and explain the session-key page |
| #84 | 2026-11-16 | fix(install): an optional tool that cannot install no longer fails install-tools all |
| #85 | 2026-11-16 | Release v0.4.1 |
| #86 | 2026-11-16 | feat(ui): check for updates and one-click upgrade in the window |
| #87 | 2026-11-16 | feat(bins): repeat-aware PlasEval dissimilarity, checked against the original; FAQ updated |
| #88 | 2026-11-16 | Window: persistent animated toast while a benchmark is running |
| #89 | 2026-11-16 | Run sessions: runs survive disconnects; list, follow, resume and open every run |
| #90 | 2026-11-16 | Third review: strict task derivation, dominated-cohort interval fallback, documentation sync |
| #91 | 2026-11-16 | feat(bins): the PlasEval-paper cohort, binning error-profile charts and a comparison gate against the original program |
| #92 | 2026-11-16 | Window: fix random disconnects, make Retry work, make the icon always open a window |
| #93 | 2026-11-16 | Record the confirmed scoring decisions; a way to change them; lock |
| #94 | 2026-11-16 | feat: short-read QC gate, assembly selection policy, candidate multiplicity analysis and an external review log |
| #95 | 2026-11-16 | Contributed RefSeq/SRA candidate pool and a seeded, cluster-aware cohort importer |
| #96 | 2026-11-16 | Configurable leakage screen (cutoff policy, fixed date, date basis), settable in plasbench ui |
| #97 | 2026-11-16 | feat: ranking stability, assembler sensitivity, reference evidence audit, 215-question assessment and the implementation catalogue |
| #99 | 2026-11-16 | Your own isolates: template, folder scan, quick test, and a plain way out of every error |

## 10. Tests and how to run them

The suite lives in `test/` (script-style Python tests, shell stage tests with stand-in tools, and real-binary checks). Run all of it with `python -m plasbench test` or
`bash test/run_tests.sh`; run one with `python test/test_<name>.py`. It runs on every pull request in CI (the `test` job and a container build). Shell stage tests need
Linux (WSL on Windows) and minimap2.

| Kind | What it proves | Examples |
|---|---|---|
| Unit and adversarial scoring | Each metric against hand-computed values and degenerate predictions | `test_scoring.py`, `test_scoring_adversarial.py` |
| Stage tests | A stage produces the right tables from stand-in tools | `test_stage_dimensions.sh`, `test_short_read_qc_stage.sh`, `test_assembly_selection_stage.sh` |
| Cross-checks | Agreement with an independent implementation | `test_plaseval_crosscheck.py`, `test_plaseval_gate.py`, `test_plaseval_cohort.py`, `test_scoring_real_minimap2.py` |
| Wiring and drift | Every script, tool and output is connected; nothing is declared but not installed | `test_script_wiring.py`, `test_install_wiring.py`, `test_report_surfaces.py` |
| Documentation | Documents agree with the code and each other | `test_guide_docs.py`, `test_independent_review_ledger.py`, `test_external_review_log.py`, `test_reviewer_matrix.py`, `test_implementation_catalogue.py` |

A passing test is not scientific validation (section 1). The independent evidence is listed in [`EXTERNAL_REVIEW_LOG.md`](EXTERNAL_REVIEW_LOG.md).

## 11. What is not implemented

Stated plainly so no one has to find it by looking. Full detail and a status for every reviewer question: [`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md).

- **A real-data run of the whole tool set.** Nothing about ranking or generalisation is demonstrated on real data until one exists. This is the largest open item.
- **Independent third-party re-run** and an **external validation cohort**.
- **Frozen, platform-specific thresholds** for QC, assembly eligibility, candidate relationships and the CPRR limits, set from pilot data.
- **Evidence beyond NCBI metadata** for most references, and plasmid-free, hard-structure and taxonomically broader isolates in the released cohorts.
- **Telling a novel plasmid from an incorrect reconstruction** (the one major gap in the 215-question assessment).
- **A seven-step tool validation ladder.** The registry has four states; output-validated, benchmark-validated and real-data-validated tools are not claimed.
- **A real multi-assembler comparison and a real-cohort ranking-stability result**; the modules exist and are tested on constructed cohorts.
- **A measured resource pilot** on the target hardware; the resource figures in the README are estimates.
- **A comparison with the figures printed in the PlasEval paper**, and the one isolate-tool pair the original program could not finish.
- **Resolving the publication candidate cohorts** (assembly accessions, truth independence, read pairing) and a **performance-drivers analysis** (a regression of per-plasmid recovery on plasmid size, repeat content, assembly fragmentation and database membership, as in the Teixeira analysis repository); both are specified, not built.
- **Out of scope by design:** plasmid clustering, communities, database search, relatedness, backbone/accessory analysis, phylogeny, and any diagnostic or epidemiological inference.

## 12. Keeping this document true

Sections 5 to 9 are generated from the repository and checked by `test/test_implementation_catalogue.py`: adding a module, a registered tool or an output without listing it here
fails the test. Sections 3 and 4 are written by hand; the test also checks that every `python/`, `test/`, `config/`, `docs/`, `scripts/` and `cohorts/` path they name exists. When you
add a capability: write its section in 3, regenerate the indexes with `python python/build_implementation_catalogue.py`, and add the change to the changelog.
