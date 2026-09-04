# Operational selection and reusable candidates

## What PlasBench selects

PlasBench makes two deliberately different outputs after stage 6:

1. **Benchmark evidence.** `benchmark.leaderboard.tsv` ranks methods across the
   supplied truth-set cohort. It is an evaluation result, not a claim that the
   first row is structurally correct for every isolate.
2. **Reusable per-isolate candidate.** For each sample, PlasBench copies the
   highest-quality *already generated* standardised prediction to
   `results/selected_candidates/<sample>/`. This avoids a second reconstruction
   run and retains the exact source FASTA, bins, maps, and selection rationale.
   Every candidate file is prefixed with its sample id, so the whole cohort's
   candidates can be gathered into one directory without name collisions.

No consensus sequence is fabricated and no external tool is rerun. The copied
sequence remains a computational candidate, not a confirmed plasmid sequence.

## Files produced

```text
results/benchmark.recommendations.tsv
results/benchmark.stratified.tsv
results/selected_candidates/<sample>/<sample>.candidate.plasmid.fasta
results/selected_candidates/<sample>/<sample>.candidate.bins.tsv          # when emitted
results/selected_candidates/<sample>/<sample>.candidate.pred_vs_ref.paf   # truth-set runs
results/selected_candidates/<sample>/<sample>.candidate.pred_vs_ref.all.paf # ambiguity diagnostic, when enabled
results/selected_candidates/<sample>/<sample>.candidate.bin_matches.tsv   # binning tools
results/selected_candidates/<sample>/<sample>.selection_report.json
```

`<sample>.selection_report.json` identifies the selected tool, metrics available for the
truth-set sample, operational recommendation, copied files, rejected tool
candidates, and reasons long-read confirmation is required. For an unknown
sample without truth, the report records an `operational_method_recommendation`
only; it cannot invent a score or structural validation.

## Decision policy

Per-sample truth-set candidates use a transparent quality function balancing
base F1, plasmid recovery, bin F1 where a method genuinely emits bins,
precision, recall, and penalties for unmapped sequence, chromosome
contamination, split/merge diagnostics, and plasmid/chromosome mapping
ambiguity. It is a reproducible prioritisation, not a biological truth oracle.

Operational recommendations are calculated overall and for available strata:
organism, truth technology, sample origin, truth-derived plasmid-size band, and
read-depth band. A method is withheld unless it meets both configured evidence
gates:

```bash
RECOMMENDATION_MIN_SAMPLES=5
RECOMMENDATION_MIN_COVERAGE=0.80
```

The report uses a multi-objective score only *after* these gates. Therefore a
method tested on a small subset cannot become an operational recommendation.
Change the gates in `config/config.sh` only with a documented study rationale.

## Structural and confidence limits

PlasBench reports **circular-truth recovery**, which means a circular reference
plasmid was sufficiently covered. It does **not** prove that the predicted
sequence is closed or circular. Base F1 likewise does not prove plasmid
architecture. Confirm candidates with long reads, hybrid assembly, assembly
graph inspection, read-support evidence, or targeted laboratory validation when
the selection report says `requires_confirmation`, especially for AMR,
carbapenemase, outbreak, or novel-plasmid claims.

The default short-read workflow uses a primary-only minimap2 PAF for stable
base metrics. When `REPORT_MAPPING_AMBIGUITY=1`, a secondary-mapping PAF also
reports query bases that align to both plasmid and chromosome reference
sequence. This is an ambiguity warning only; it does not change TP, FP, FN, or
F1.

## AMR and long-read tracks

AMR recovery is enabled only when a curator supplies a versioned, coordinate
validated `data/<sample>/truth_amr.tsv`. It must not be inferred from a generic
AMR database scan of the same prediction being evaluated. The current release
is a paired short-read reconstruction benchmark; long-read and hybrid values in
the selection schema identify analysis scope but are not native ONT/PacBio FASTQ
reconstruction modes. Do not compare those tracks until adapters and a
pre-specified truth policy have been validated.

## Stand-alone command

Stage 6 runs selection automatically. Re-run it after editing an existing
score table without rerunning reconstruction:

```bash
plasbench select-candidates \
  --scores results/scores.tsv \
  --samples config/accessions.tsv \
  --results-dir results \
  --tool-status results/tool_status.tsv \
  --out-prefix results/benchmark
```

## Reconstructing a new, truth-unknown sample

A sample outside the benchmark cohort -- one arriving for real operational
use, with no complete-reference truth to score it against -- does not need
every benchmarked tool run against it; running the full stage-4 tool set
turns a single-method reconstruction into an N-method one for no evidential
benefit, since there is no truth to compare the extra tools against anyway.
`plasbench reconstruct` runs only ONE method: the evidence-gated
`benchmark.recommendations.tsv` choice for the sample's organism or Gram
group (falling back to the overall recommendation), or an explicit
`--tool` override.

```bash
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678 \
  --organism "Klebsiella pneumoniae" --gram-group Gram_negative
```

Internally this builds a one-row, truth-less sample sheet for just that
sample and runs stage 1 (reads only -- no reference/sequence-report
download), stage 3 (QC and assembly, unchanged), then stage 4 with
`ONLY_TOOL` set to the chosen tool, which overrides every `RUN_*` flag for
that one invocation. It never touches, rebuilds, or rescans any other
sample's sheet or results, so an already-benchmarked sample's reconstruction
is never repeated by this path. The recommendation lookup itself is also
available stand-alone once a prediction already exists (for example, one
produced by a bespoke pipeline outside PlasBench):

```bash
plasbench select-unknown --recommendations results/benchmark.recommendations.tsv \
  --sample-id new_isolate_01 --results-dir results \
  --organism "Klebsiella pneumoniae" --gram-group Gram_negative
```

Open `results/benchmark.report.html` and use **Operational method
recommendations**, **Sample drill-down**, and the artifact explorer to inspect
or download each retained candidate.
