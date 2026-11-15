# Statistics validation by simulation

Written for: maintainers and reviewers who need to know how far PlasBench's intervals and tests can be trusted. Produced by `python/simulate_validation.py --mode full --workers 6` (35 minutes on 6 processes); the raw tables are `docs/stats_validation/benchmark.stats_validation.tsv` (one row per scenario and effect) and `benchmark.stats_validation_by_studies.tsv` (summary by number of independent studies). Seed 20261114, 1,000 replicates per scenario row, 1,000 bootstrap resamples, 10,000 permutations, real functions from `python/resampling.py` and `python/aggregate_results.py`.

## What was simulated
Paired differences d = effect + study effect + isolate noise. Structures: 5, 6, 8, 12, 20 and 30 balanced studies; unbalanced study sizes (1, 2 or 6 isolates); one dominant study (60% of isolates); two heavy studies (80%); within-study correlation (icc 0, 0.5, 0.8); 10% and 30% missing outputs (excluded); 10% resource failures scored 0 (difference +-0.7, symmetric), per isolate and as whole studies failing; three species with one dominant (70% of studies), using the species-stratified functions; Holm over 6 and 15 comparisons (independent comparisons, none or a third real). Effects 0, 0.05 and 0.10.

## Findings
| Question | Result |
|---|---|
| Are the sign-flip tests valid (type-I error at 0.05 with no effect)? | Yes in every structure that can be tested (6+ studies): 0.034 to 0.062, all within the Monte Carlo tolerance. |
| Does Holm control the family-wise error? | Yes: 0.036 to 0.047 over 6 and 15 comparisons at 12 and 20 studies, against 0.24 to 0.53 unadjusted. |
| Do the 95% cluster-bootstrap intervals cover 95%? | **No.** 5 studies 0.82-0.86; 6 studies 0.85; 8 studies 0.87; 12 studies 0.74-0.92 (lowest with a dominant species); 20 studies 0.87-0.92; 24 studies with a dominant species 0.84-0.86; 30 balanced studies 0.93-0.94. |
| Is the shortfall worse for unequal study sizes, dominant studies, failures? | Slightly: two heavy studies and a dominant species are the worst; failures, missing outputs and within-study correlation change coverage by a few points around the same level. |
| Does the number of studies matter more than the number of isolates? | Yes: coverage improves with studies (0.82 at 5, 0.94 at 30) and barely with isolates per study. |

## What this means for the report
- The tests and the Holm-adjusted tests can be read as calibrated for 6 or more independent studies under these structures.
- This run measured the percentile cluster bootstrap only, and it under-covers (a "95% interval" behaves like roughly 80-90% below about 30 studies).
- After this run, the leaderboard interval became the cluster-robust t interval (`PLASBENCH_CI_METHOD=cluster_t`); the percentile and studentised cluster bootstraps stay selectable and are measured beside it by the current `simulate_validation.py`. The second-review simulation (`docs/validation/stats_validation_full.tsv`) found cluster t covers 94-97% with balanced studies.
- **Not yet measured:** cluster t under the structures added here (a dominant study, two heavy studies, resource failures, a dominant species). Re-run `python python/simulate_validation.py --mode full --workers 6 --out ... --by-studies-out ...` (about an hour with all three methods) and replace the files in this folder. Until then the procedures stay **provisional** (`simulate_validation.overall_status()`).

## Limits of this study
Monte Carlo error is about 0.007 for a rate near 0.05 and 0.011 near 0.9 with 1,000 replicates; the Holm comparisons are independent (real tool pairs share tools, which makes Holm more conservative); species effects were equal across species; the simulated structures are not the shipped cohorts, so a conclusion about a particular cohort needs a run with its own number of studies and structure.
