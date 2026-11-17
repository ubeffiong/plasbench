# results_real_cohort1: a real-data PlasBench run (10 isolates)

This folder is the output of a real run, not the bundled demo. It was renamed from `benchmark.report_cohort1`.

| | |
|---|---|
| Produced | 14 November 2026, PlasBench 0.2.3 (`run_manifest.json`) |
| Data | 10 public isolates with downloaded reads and deposited reference assemblies: `upec_ecpf5`, `upec_ecpf7`, `upec_ecpf14`, `upec_ecpf15`, `upec_ecpf16`, `upec_ecpf18`, `upec_ecpf40` (urinary *E. coli*), `arbank_0346`, `arbank_0349`, `tahini_salmonella` |
| Track | short read, reconstruction and classification |
| Tools run | `mob_recon`, `platon`, `plasmidspades`, and the `baseline_coverage` baseline (all 10 completed on all 10 isolates; `baseline_reference` was skipped) |
| Not run | geNomad, PLASMe, plasgraph2, plsMD and the long-read tools (switched off in the settings recorded in the manifest) |
| Open first | `benchmark.report.html`; the tables are the `benchmark.*.tsv` files, the per-run scores are `scores.tsv` |

## Which code built it

Everything here, including `benchmark.report.html` and `benchmark.leaderboard.*`, was built with **PlasBench 0.2.3** and **ranks on 1 isolate** (the one Tier 2 reference; the headline ranking is therefore not a result, see below). It was **not rebuilt with later code**: the report needs the sample sheet and the per-sample data folder of the original run, which are not part of this folder, so a rebuild from these files alone would not be the same report. Consequences of the version: its leaderboard lacks the shared-sample warning columns, the run-table consistency table and the input fingerprint added later, and its report card and summary tiles are those of 0.2.3 (the 1000% "runs completed" and "Methods compared 1" it shows were corrected in later versions). To get a current report, rerun stage 6 on this folder's `scores.tsv` and `tool_status.tsv` with the sample sheet and data folder of the run.

## What it supports, and what it does not

- **Supports:** that the pipeline runs end to end on real reads and real references, and a descriptive look at three real tools on ten isolates.
- **Does not support a ranking.** Only 1 of the 10 references reaches reference Tier 2 (long-read-first, polished with the benchmark's own reads) and the other 9 are Tier 3 (8 short-read-first, 1 unknown), so the headline ranking rests on one isolate and its interval is reported as "< 5 independent units". The numbers by tier are in `benchmark.reference_tiers.tsv`.
- **Tier 3 numbers** (9 isolates, provisional): length-weighted binning F1 0.82 for `mob_recon`, with 9 of 20 plasmids correctly reconstructed; base-level F1 0.91 for `platon`, 0.60 for `plasmidspades`, 0.45 for the coverage baseline.
- **Tier 2 number** (1 isolate): `mob_recon` binning F1 0.84 and 0 of 2 plasmids correctly reconstructed.
- The run predates two later checks: the unaligned-sequence columns of the binning score and the run-table consistency check, so those are not in its tables.

The manifest and logs contain the paths of the machine that produced the run.
