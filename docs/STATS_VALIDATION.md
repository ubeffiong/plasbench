# Statistics validation by simulation

Written for: maintainers and reviewers who need to know how far PlasBench's intervals and tests can be trusted. Produced by `python/simulate_validation.py --mode full --workers 6` (35 minutes on 6 processes); the raw tables are `docs/stats_validation/benchmark.stats_validation.tsv` (one row per scenario and effect) and `benchmark.stats_validation_by_studies.tsv` (summary by number of independent studies). Seed 20261114, 1,000 replicates per scenario row, 1,000 bootstrap resamples, 10,000 permutations, real functions from `python/resampling.py` and `python/aggregate_results.py`.

## What was simulated
Paired differences d = effect + study effect + isolate noise. Structures: 5, 6, 8, 12, 20 and 30 balanced studies; unbalanced study sizes (1, 2 or 6 isolates); one dominant study (60% of isolates); two heavy studies (80%); within-study correlation (icc 0, 0.5, 0.8); 10% and 30% missing outputs (excluded); 10% resource failures scored 0 (difference +-0.7, symmetric), per isolate and as whole studies failing; three species with one dominant (70% of studies), using the species-stratified functions; Holm over 6 and 15 comparisons (independent comparisons, none or a third real). Effects 0, 0.05 and 0.10.

## Findings (86 scenario rows, three interval methods; 49 minutes on 6 processes)
| Question | Result |
|---|---|
| Are the sign-flip tests valid (type-I error at 0.05 with no effect)? | Yes in every structure that can be tested (6+ studies). |
| Does Holm control the family-wise error? | Yes, over 6 and 15 comparisons at 12 and 20 studies. |
| Balanced studies, 5-30 | Cluster t 94-96%, studentised bootstrap 93-96%, percentile 82-94% (82% at 5 studies, 94% at 30). |
| Moderate imbalance (study sizes 1, 2 or 6), 10-30% missing outputs, within-study correlation up to icc 0.8 | Cluster t 92-96%; percentile 87-92%. |
| Resource failures | Per isolate: cluster t 94-96%. Whole studies failing: cluster t 98%, studentised 89-91%, percentile 89-91%. |
| **One dominant study (60% of isolates)** | **Cluster t 72% (12 studies), 64% (20 studies)**; studentised 82%, 79%; percentile 90%, 91%. |
| **Two heavy studies (80% of isolates)** | **Cluster t 79%, 69%**; studentised 85%, 81%; percentile 88%, 87%. |
| One dominant species of 3 (stratified), 12 and 24 studies | Cluster t 88%, 93%; percentile 74%, 86%. |

## What this means for the report
- The tests and Holm-adjusted tests can be read as calibrated for 6 or more independent studies under these structures.
- The cluster-t interval is the best method for balanced and moderately unbalanced cohorts and the worst when one or two studies hold most of the isolates. No method is adequate everywhere.
- A cohort where one study holds roughly a third or more of the isolates should have its intervals read as optimistic, or be analysed with the percentile bootstrap (`PLASBENCH_CI_METHOD=percentile`), which is the least bad there.
- The procedures stay **provisional** (`simulate_validation.overall_status()` says so, per number of studies).
- Not changed here: an automatic fallback to the percentile bootstrap when one study dominates would be a separate decision.

## Limits of this study
Monte Carlo error is about 0.007 for a rate near 0.05 and 0.011 near 0.9 with 1,000 replicates; the Holm comparisons are independent (real tool pairs share tools, which makes Holm more conservative); species effects were equal across species; the simulated structures are not the shipped cohorts, so a conclusion about a particular cohort needs a run with its own number of studies and structure.
