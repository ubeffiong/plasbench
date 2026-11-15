# Response to the second scientific and technical review

**Review received:** 15 November 2026, a static review of `main` documentation and source (the reviewer did not execute the pipeline).
**Response:** PlasBench 0.4.0. Every P0 and P1 item of the review's implementation list (its section 15) is addressed below; items the
review placed in later phases are listed with their status so nothing is silently dropped.

Status: **done** (implemented and tested), **partly** (implemented, with the part still open named), **open** (not done in this
release, with the reason).

## P0: before the next formal benchmark

| Review point | What changed | Tests | Status |
|---|---|---|---|
| **Task classification** (section 3): a tool without bins was ranked as a contig classifier, so plasmidSPAdes shared a leaderboard with Platon | `config/tool_capabilities.tsv` declares `evaluation_task` (`binning_reconstruction`, `sequence_reassembly`, `classification`) and `output_unit` for every tool, from its output contract. `headline_design.py` ranks from it, with a third **reassembly** track (base-level sequence-recovery F1); older registries and user manifests fall back to `binning_capable` and `method_class`; an unknown value is an error. User tool manifests accept `task = reassembly`. Plassembler, Hybracter and plsMD stay on reconstruction because each output record is one plasmid (`output_unit = plasmid_records`). | `test_evaluation_task.py` | done |
| **Reference independence** (section 4): reference quality and independence were one variable | `truth_provenance.py` records `reference_independence` and `reference_group` beside the tier. By default (`HEADLINE_REFERENCE_INDEPENDENCE=independent`, pre-registered as *proposed*) only independent tier 1-2 references enter the primary analysis; same-read-polished and unrecorded ones go to the new **reference-independence sensitivity table** (`benchmark.reference_independence.tsv`: mean, rank and their change from the independent group, with sample and cluster counts), shown in the report. The headline design table states the composition. | `test_reference_independence.py` | done |
| **Statistical uncertainty** (issues 1 and 5A): the percentile cluster bootstrap under-covers with few studies | `resampling.py` adds a cluster-robust t interval (CR1, t on G−1 df; stratified form) and a studentized cluster bootstrap. `simulate_validation.py` measures all three on the same data, adds stratified scenarios and a Holm family-wise error scenario. The leaderboard and comparison intervals use the method the simulation supports (`PLASBENCH_CI_METHOD`, recorded in every output). See *Calibration result* below. | `test_simulate_validation.py`, `test_resampling_equivalence.py` | done |
| **AMR placement for non-binning tools** (section 7): one-to-one matching penalised a classifier whose two contigs both come from one plasmid | A tool without bins is scored by **contig attribution**: each gene-bearing record goes to the truth sequence it aligns to most, several records may share one plasmid. It is reported as plasmid-sequence attribution, not reconstruction: AMR-PRR and pairs kept together stay unavailable. The mode is recorded per gene copy and in the summary and report. | `test_amr_placement.py` (the review's fixture: one plasmid, two genes, two contigs; and the same contigs forced through one-to-one matching, to show the old penalty) | done |
| Regression fixtures for task mapping and AMR placement | As above | as above | done |

### Calibration result

CALIBRATION_TABLE

## P1: before claiming generalisable tool selection

| Review point | What changed | Tests | Status |
|---|---|---|---|
| Clonal-group-aware folds (6B) | `study_groups.group_samples` builds isolate, study, clonal-group, study-and-clonal and species holdouts. `evaluate_recommender.py` reports every arm under each (`benchmark.recommender_holdouts.tsv`); an arm is enabled only when it adds value under leave-one-study-out **and** the strictest design the run can build. Genus and phylum transfer stay in `leave_taxon_out.py`. | `test_recommender_validation_designs.py` | done |
| Taxonomy-aware nearest neighbours (6A) | Two new arms beside the numeric one: same-species neighbours, and species then genus then Gram group. All are compared with the single best tool, never assumed to help. | as above | done |
| Distance validation (6C, 3A): scaling, missingness, K, correlated features, distance-based confidence | Robust scaling (median, MAD); a penalty for a feature present on one side only; out-of-range isolates abstain instead of receiving a forced answer; each recommendation records the neighbours' score spread and study count (`benchmark.recommender_knn.tsv`); sensitivity to K (3, 5, 10), scaling, missingness, abstention and each feature left out (`benchmark.recommender_sensitivity.tsv`); Spearman correlation flags redundant features such as N50 and contig count (`benchmark.recommender_feature_correlation.tsv`). | as above | done |
| Recommender evaluation vs operational model; calibration (3D) | `fit_recommendation_model.py` is never ready without a recommender verdict showing that per-isolate choice beats the single best tool out of study (`--recommender-verdict`), and records out-of-study calibration (slope, intercept, 90% interval coverage); intervals covering under 80% keep it inactive. | `test_fit_recommendation_model.py` | done |
| Independent-reference reporting and endpoint eligibility in aggregation | `aggregate_results.py` applies the independence rule, prints and records the composition, and writes the sensitivity table. | `test_reference_independence.py` | done |
| Effect estimation and practical equivalence (5B) | Paired comparisons gain `effect_status` (equivalent / practically different / different, size unclear / inconclusive / not assessable) and `testable`; equivalence now requires an interval, so a small difference without one is `not_assessed`, never "equivalent". The report shows *what the difference supports* beside the p-values. | `test_wilcoxon.py`, `test_permutation_reporting.py` | done |
| Endpoint interpretation (issue 2) | Every markdown leaderboard says what its ranking metric measures (detection, grouping, complete recovery) and that binning F1 is not complete reconstruction; the report's reconstruction and reassembly blurbs say the same. | `test_evaluation_task.py` | done |
| `config/prereg.tsv`: proposed parameters and unavailable metrics | New status `unavailable` (decided: no defensible value exists). A4 (SNP concordance) and C2 (SV F1) are resolved as unavailable with no invented bands, so nothing is left `TO_FIX`. The remaining `proposed` values are **not** confirmed here: confirming them is the maintainer's or panel's decision, recorded with `freeze-prereg --strict`. | `test_prereg_freeze.py` | partly: awaiting the maintainer's confirmation of the proposed values |
| `config/metrics.tsv`: evaluation-task compatibility | `tool_types` names the tasks a metric can score (reconstruction, reassembly, classification, or all); `metric_registry.applies_to`. AMR placement applies to every task (attribution without bins). | `test_evaluation_task.py`, `test_metric_registry.py` | done |
| Scorecard comparability (11B) | Tools are ordered on the metrics every tool could be scored on; a per-tool overall renormalised over a different set is shown but never orders tools. The scorecard says it never ranks or recommends. | `test_report_scorecard.py` | done |
| Version synchronisation (13A) | The Scientific Guide names 0.4.0; `test_doc_versions.py` keeps it, the package, `CITATION.cff` and the changelog equal to `pyproject.toml`. | `test_doc_versions.py` | done |
| The first independent review (13B) | `docs/INDEPENDENT_REVIEW.md` is labelled historical and points here. | `test_independent_review_ledger.py` | done |
| Scientific Guide and Methods | Tasks, reference independence, intervals and calibration, effect status, recommender validation, settings and the validation-status table are updated. | `test_guide_docs.py` | done |

## Later phases in the review, not part of this release

| Review point | Status and reason |
|---|---|
| Run public-v3 as the next formal benchmark (section 9A) | **open.** It needs the real tools, databases and compute on the production machine; it is the next milestone, ahead of new metrics, as the review advises. The Scientific Guide says plainly that only *E. coli* reaches the 20-cluster species minimum. |
| Expand species representation; difficult-plasmid panel (9B, 9C) | **open.** Cohort curation (maintainer-owned). |
| Four validation levels V0-V3 tied to tool and database versions, with freshness (section 10) | **open.** The existing tiers (`untested`, `adapter_tested`, `real_binary_checked`) map to V0-V2; V3 needs expected biological outputs per tool, which come from the real-data run. The guide now says registered is not validated. |
| Three-category reading of predicted sequence with lower and upper precision bounds (section 8) | **open.** The unresolved burden (unmapped, off-truth, ambiguous) is already reported beside strict precision; the bounds are a reporting change planned with the public-v3 run. |
| Manual reference-disagreement adjudication table (section 12) | **open.** The truth-label audit already lists every disagreement; an adjudication table needs a reviewer and date per decision. |
| Split the README; developer guide; CI matrix (13C, 13D) | **open.** Documentation restructuring and CI layout, planned separately so this release stays reviewable. |
| Temporal and external-cohort holdouts (6B table) | **open.** They need collection dates and a second cohort; the holdouts table names them as not derivable. |
