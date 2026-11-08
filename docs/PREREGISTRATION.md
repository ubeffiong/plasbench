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
| `status` | `fixed`, or `TO_FIX` while the panel has not decided |

## Freezing and checking

```bash
plasbench analysis freeze-prereg --write      # lock the SHA-256 in config/prereg.lock.json
plasbench analysis freeze-prereg --verify     # fail if prereg.tsv changed after the freeze
plasbench analysis freeze-prereg --verify --require-fixed --check-env
```

- Every run manifest (`run_manifest.json`, key `preregistration`) records the
  hash, whether the lock matches, the parameters still `TO_FIX`, and every
  configuration variable whose value departs from the plan.
- The HTML report's **Pre-registration** section shows the same.
- With `REQUIRE_PREREG=1`, stage 4 refuses to run any tool until the lock
  matches, no parameter is `TO_FIX`, and no setting departs from the plan.

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

## Still `TO_FIX`

| Parameter | Proposed value | Why open |
|---|---|---|
| `tool_timeout_seconds` | unset (no limit) | Set after the pilot, from the slowest tool's runtime on the largest isolate |
| `integrated_element_min_depth` | 3× | Integrated-element / unverified-candidate stratum; needs real data |
| `unverified_candidate_requires_circular_path` | yes | Same stratum; provisional |

The values are the specification's proposed defaults and await the panel's
confirmation. Until they are fixed, `REQUIRE_PREREG=1` will refuse to run.

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
