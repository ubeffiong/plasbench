# Pre-registration and the scoring specification

PlasBench fixes its scoring decisions before results are seen. They live in
[`config/prereg.tsv`](../config/prereg.tsv), one row per decision:

| Column | Meaning |
|---|---|
| `parameter` | Name of the decision |
| `value` | The pre-registered value |
| `config_variable` | The `config/config.sh` variable that implements it, when there is one |
| `spec_section` | Section of the scoring specification it comes from |
| `revise_after_pilot` | Whether the pilot may change it (before the freeze only) |
| `status` | `fixed` (decided); `proposed` (a value is proposed, rationale in the note, awaiting the maintainer's confirmation); `TO_FIX` (no value yet); `unavailable` (decided: no defensible value exists, so the metric is reported as unavailable and excluded, never given an invented threshold). `proposed` and `TO_FIX` are *unfixed*: a plan with any is a **draft**; `unavailable` is resolved |

## Freezing and checking

```bash
plasbench analysis freeze-prereg --write      # lock the SHA-256 in config/prereg.lock.json
plasbench analysis freeze-prereg --verify     # fail if prereg.tsv changed after the freeze
plasbench analysis freeze-prereg --verify --require-fixed --check-env
plasbench analysis freeze-prereg --write --strict   # the real freeze: refuses while any row is proposed or TO_FIX
```

- Every run manifest (`run_manifest.json`, key `preregistration`) records the
  hash, whether the lock matches, the parameters still `proposed` or `TO_FIX` (the draft state), and every
  configuration variable whose value departs from the plan.
- The HTML report's **Pre-registration** section shows the same.
- With `REQUIRE_PREREG=1`, stage 4 refuses to run any tool until the lock
  matches, no parameter is `proposed` or `TO_FIX`, and no setting departs from the plan.

## Decisions recorded so far

| Decision | Value | Source |
|---|---|---|
| Primary endpoint (short-read) | Length-weighted binning F1 (reconstruction); base F1 (classification); CPRR key secondary | Research design (#7); kept after the endpoint review |
| Primary endpoint (long-read and hybrid) | Isolate-level CPRR (`sample_cprr`) for reconstruction tools; binning F1 secondary | Endpoint review: these tools aim to close whole plasmids |
| CPRR threshold robustness | Coverage and bin-share criteria swept 0.80-0.99 (step 0.01), summarised as a normalised AUC; descriptive only | Endpoint review |
| CPRR weighting | Pooled over plasmids and mean over isolates, both reported; CPRR also stratified by size, replicon, MOB, AMR carriage and reference tier | Endpoint review |
| Primary labelling scheme | **Scheme 3, NCBI labels** (`assigned_molecule_location_type`, report pinned by SHA-256) | Panel decision E.15 |
| Sensitivity schemes | Scheme 1 (non-chromosomal), evidence scheme | Panel E.15 |
| A tool crash or missing output | **F1 = 0**, counted in the ranking | Panel decision D6 |
| Infrastructure failure | Never scored; rerun | Scoring specification, outcome states |
| Recommendation floor | No tool is named when the best expected F1 < 0.40 | Panel D11 |
| Paired test | Sign-flip permutation (primary), Wilcoxon signed-rank beside it, Holm | Scoring specification |
| Equivalence margin | 0.05 | Scoring specification |
| Recommender value | `benchmark_only` when the oracle gap < 0.02 | Scoring specification |

## Still open: proposed values awaiting confirmation

The plan is a **draft** until every row below is confirmed (set `status` to `fixed`) and frozen with `--strict`. A draft can be locked (`--write`) so a run records
which draft it used, but `REQUIRE_PREREG=1` and `--strict` refuse it.

| Parameter | Proposed value | Rationale | Status |
|---|---|---|---|
| `tool_timeout_seconds` | 7200 (2 h) | Far above the minutes a short-read tool needs on a typical isolate; short enough to catch a hung run. Confirm from the slowest tool on the largest isolate, then set `TOOL_TIMEOUT_SECONDS` to the same value | proposed |
| `integrated_element_min_depth` | 3x | Integrated-element / unverified-candidate stratum; needs real data | proposed |
| `unverified_candidate_requires_circular_path` | yes | Same stratum | proposed |
| `scorecard_weights`, `scorecard_overall_bands`, `scorecard_bands_*`, `scorecard_min_samples`, `map_max_bp` | see `config/prereg.tsv` | Proposed defaults for the exploratory scorecard and map; the identity bands (A1) are fixed | proposed |
| `scorecard_bands_A4_C2` | none | No independent truth variant set exists: SNP concordance (A4) and structural variant F1 (C2) are reported as unavailable and excluded until one does, when their bands are pre-registered before results are seen | unavailable |
| `headline_reference_independence` | independent | A tier 1-2 reference enters the primary analysis only if it was not polished with the benchmark's own reads; dependent references are the reference-independence sensitivity analysis (second external review, section 4) | proposed |

## Not adopted from the specification

| Item | Reason |
|---|---|
| Plasmid-free isolates scored 0 in F1 averages | F1 is undefined there; PlasBench reports them in the negative-control table instead. |
| Summed assigned-contig length as the primary recall denominator | Kept as a contig-layer-only definition; the headline uses the reference. |
| A context model / contamination gate beyond the advisory assembly QC gate | Needs real data; the recommendation-model audit is still owed. |
| More than 100 in-house isolates | A data-collection task, not code. |

See [PANEL_ALIGNMENT.md](PANEL_ALIGNMENT.md) for how each panel question maps to
what was implemented, and [METHODS.md](METHODS.md#scoring-specification) for the
definitions.
