# External Evidence And Candidate-Quality Datasets

## Purpose

PlasBench distinguishes its native benchmark evidence from published external
evidence. Native scores use PlasBench's declared reference labels, mapping
thresholds, and provenance rules. Published tables can be valuable for history,
comparison and scenario design, but they must not be silently merged into the
native leaderboard or recommendation model when their truth definitions differ.

## Archive A Published Benchmark

Download a tagged release or commit of the source project yourself, then import
the published table with its immutable revision and citation:

```bash
plasbench import-external-benchmark \
  --predictions external/predictions.xlsx \
  --ani external/ani.tsv \
  --out-dir evidence/broad-plasmid-detection \
  --source-repository https://github.com/broadinstitute/plasmid-detection-benchmark \
  --source-revision <reviewed-tag-or-commit> \
  --citation "Source project's recommended citation"
```

The command copies the raw files, writes SHA-256 digests, converts the first
worksheet (or CSV/TSV) to a source-schema TSV, and records an interpretation
manifest. It **does not** alter `scores.tsv`, the native leaderboard, or a
recommendation model. A reviewed metric mapping, compatible truth definition,
and split policy are required before that can happen.

## Candidate-Quality Dataset

Stage 6 now writes these artifacts automatically:

```text
results/benchmark.candidate_features.tsv
results/benchmark.candidate_labels.tsv
results/benchmark.candidate_dataset.card.json
```

They can also be regenerated without rerunning reconstruction:

```bash
plasbench candidate-dataset \
  --scores results/scores.tsv --samples config/accessions.tsv \
  --results-dir results --tool-status results/tool_status.tsv \
  --out-prefix results/benchmark
```

Features are deliberately truth-independent where possible: organism, Gram
group, study, geography, origin, track, read depth, runtime, memory and tool
status. Aggregate labels remain attached only to the whole tool output. If an
adapter emits bins but no validated bin-specific truth label, those bin rows
are present with `label_scope=unavailable_for_bin`; PlasBench never copies a
tool-level F1 onto every bin.

These tables are for future model research and validation, not for clinical
decision-making. Any learned selector must use held-out study validation and
the existing confirmation safeguards before it can influence an operational
recommendation.

## Synthetic And Metagenomic Scenarios

For isolate simulation, PlasBench already supports a `truth_source=simulated`
cohort: it retains a real complete reference as truth and generates short and
long reads with InSilicoSeq and Badread. Install those existing dependencies
with `plasbench install-tools simulate`. This remains separate from real-read
leaderboards.

Community/metagenomic simulations (for example PlasmidSim/CAMI-shaped inputs)
are a future, separately scoped track. They require community-level truth and
multi-sample evaluation; they must not be forced into the one-isolate native
leaderboard. Likewise, a GPL or research-code tool such as PlasX should run in
an isolated upstream runtime once its exact input/output contract has been
validated, rather than being bundled or represented as a completed adapter.
