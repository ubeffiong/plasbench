# `results_audit/` is synthetic demo output, not real evidence

Every file in this directory was produced by `plasbench demo` /
`test/run_demo.sh` against synthetic, fabricated inputs — it exists so the
reporting/aggregation/selection stages have a small, committed, offline
example to run against and diff.

None of it reflects a real plasmid-reconstruction benchmark run:

- `samples.tsv`'s two samples ("Demo bacterium", `source_study` = "Demo study
  A"/"Demo study B") do not exist in any real cohort.
- `scores.tsv`'s tools ("good", "leaky", "gplas_like", "platon_like",
  "weak_like", ...) are synthetic stand-ins, not the real tool adapters
  (`mob_recon`, `platon`, `plasmidspades`, ...).
- `benchmark.recommendation_validation.tsv`'s rows are computed from this
  same fabricated data and must never be cited as a real
  leave-one-study-out result.

Real benchmark results live under `results/` (gitignored — regenerate them
yourself with `plasbench run`) or, for released cohort evidence, under
`cohorts/<name>.scores.tsv` and `cohorts/<name>.tool_status.tsv` once a
cohort has contributed isolates (see
[`CONTRIBUTING.md`](../CONTRIBUTING.md)).
