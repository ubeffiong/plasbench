# PlasBench User Guide

## What PlasBench Is

PlasBench is a reproducible bioinformatics benchmark for answering a practical
question: **which plasmid-reconstruction method performs best for a given set
of bacterial short-read samples?**

Different tools report plasmids in different ways. Some classify assembled
contigs as plasmid or chromosome, while others assemble a separate set of
putative plasmid sequences. PlasBench makes their output comparable by mapping
every predicted-plasmid FASTA back to a complete reference assembly and scoring
the same reference bases for every tool.

The current benchmark can compare MOB-suite `mob_recon`, Platon,
plasmidSPAdes, and experimental gplas. It is designed for bacterial isolates
with matched Illumina reads and a complete long-read or hybrid reference from
the same isolate.

Run this guide from a source checkout with `plasbench docs`, or print one
section with `plasbench docs --topic <name>`.

## What It Does

For every sample, PlasBench:

1. Retrieves a complete reference assembly and matched Illumina reads, or uses
   data that has already been prepared in its expected locations.
2. Reads the NCBI sequence report to label each reference sequence as plasmid
   or chromosome.
3. Quality-trims and assembles the short reads.
4. Runs every enabled plasmid-reconstruction tool.
5. Standardizes each tool's output to a predicted-plasmid FASTA.
6. Aligns each prediction to the complete reference with minimap2.
7. Computes base-level precision, recall/completeness, F1, chromosome
   contamination, and unaligned predicted sequence.
8. Produces per-sample results, a coverage-aware leaderboard, and an offline
   interactive HTML report with drill-downs and downloadable artifacts.

## How It Works

The complete reference is the truth source. A base is considered a positive
reference base when its sequence is labelled `PLASMID`; a chromosome base is a
negative reference base. When a tool claims sequence is plasmid, PlasBench asks
where that sequence aligns on the reference:

```text
Predicted plasmid aligns to reference plasmid   -> true positive (TP)
Predicted plasmid aligns to reference chromosome -> false positive (FP)
Reference plasmid not covered by a prediction    -> false negative (FN)
```

This base-level projection is important: it avoids treating a classifier's
contig labels and a reassembler's plasmid contigs as incomparable output types.
Precision measures how much of a claimed plasmid sequence maps to chromosome;
recall measures how much true plasmid sequence was recovered; F1 balances both.

Tool execution failures are not falsely converted into zero F1. PlasBench
records them in `tool_status.tsv`, excludes them from score aggregation, and
shows completed, failed, skipped, and scored counts in the leaderboard.

## When To Use It

Use PlasBench when you need to choose a plasmid-reconstruction method for a
study, compare methods on local isolates, prepare benchmark evidence for a
publication or poster, or validate a method configuration against trusted
complete assemblies.

Do not use it as a clinical diagnostic, as proof that an individual predicted
plasmid is biologically correct, or to compare samples whose reads and complete
reference are not from the same isolate. A high score shows agreement with the
selected reference and parameters; it does not replace laboratory validation or
broader epidemiological interpretation.

## Requirements and Limits

The full workflow needs a matched reference/read pair for each sample, enough
compute for assembly, and reliable source metadata. Complete-reference labels
depend on the NCBI sequence report. Ambiguous, incomplete, contaminated, or
mismatched reference data can bias every downstream metric.

The default `asm5` mapping preset assumes low divergence between prediction and
reference, which is appropriate for the same isolate. Change it only when the
biological relationship warrants it and document that choice. gplas remains
experimental because its output layout varies by release.

## Simulated End-to-End Research Example

This example is deliberately synthetic. It demonstrates the complete scoring,
aggregation, and reporting workflow without downloading research data or
claiming a real biological finding.

### Research question

> For two hypothetical bacterial isolates with complete references, how do
> three hypothetical plasmid-reconstruction behaviours compare when scored
> against the known plasmid bases?

The demo models two isolates, `sample1` and `sample2`, and three simulated
tools:

```text
good   Recovers all plasmid bases without chromosome contamination.
leaky  Recovers all plasmid bases but includes chromosome sequence.
shy    Avoids contamination but misses part of the plasmid sequence.
```

### Run the simulation

From the cloned PlasBench repository with the environment activated:

```bash
plasbench test
plasbench demo
```

`plasbench test` checks the scoring equations on a hand-built case. `plasbench
demo` then creates synthetic truth tables, predicted FASTAs, and alignments;
scores every sample/tool pair; aggregates the benchmark; and generates the HTML
dashboard. It does not use NCBI, SRA, or installed plasmid tools.

### Inspect the results

```bash
plasbench docs --topic outputs
```

Open the final report in a browser:

```text
results_demo/benchmark.report.html
```

The simulated leaderboard is expected to rank the behaviours as follows:

```text
Tool    Mean F1   Interpretation
good    1.000     Complete recovery with no chromosome contamination.
leaky   0.927     Complete recovery, but reduced precision from chromosome bases.
shy     0.697     Clean predictions, but lower recall because plasmid bases are missed.
```

The exact per-sample TP, FP, FN, precision, recall, F1, and unmapped-base
values are in `results_demo/scores.tsv`. `results_demo/tool_status.tsv` records
that all synthetic tools completed. The dashboard lets you filter those rows,
sort tables, inspect a tool across samples, inspect tools within a sample, and
download each generated artifact.

### Translate the example to a real study

After validating the installation with the demo, replace the synthetic data
with a curated sample sheet:

```bash
plasbench run --samples config/accessions.tsv --threads 8
```

The real sample sheet must link each matched Illumina run to a complete
reference assembly from the same isolate. Do not expect the simulated ranking
to predict your real-data ranking: read quality, assembly fragmentation,
plasmid size, repeat content, and database coverage can change the outcome.

## Install

### Native Linux or WSL2

PlasBench is tested as a Bash-first workflow on Ubuntu. Windows users should
use Ubuntu WSL2. You need Git, Conda/Mamba (Miniforge recommended), internet
access to NCBI/SRA, and typically 20-40 GB free disk space per active run.

```bash
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench
bash env/setup_conda.sh
conda activate plasbench
python -m pip install --no-deps .
plasbench check
plasbench test
plasbench demo
```

Install the Platon database only when Platon is enabled:

```bash
bash env/download_platon_db.sh
```

`plasbench check` reports missing tools without changing data. A real run needs
NCBI Datasets, SRA Toolkit, fastp, minimap2, SPAdes/plasmidSPAdes, MOB-suite,
Platon, and the Platon database when their corresponding tools are enabled.

### Docker

Docker supplies the Conda environment inside an image. The Platon database is
not embedded because it is large and versioned separately.

```bash
docker build -t plasbench:local .
docker run --rm plasbench:local plasbench demo
```

For a real Docker run, mount `config`, `data`, `logs`, and `results`, then set
`DATA_DIR`, `LOG_DIR`, `RESULTS_DIR`, and `PLATON_DB` to their mounted paths.
The exact copy-paste command is in the README.

## Inputs

The default sample sheet is `config/accessions.tsv`. It is a tab-separated file
with one isolate per row. The eight curation columns are required; the final two
are optional but enable cohort dashboard filters:

```text
sample_id	assembly_accession	sra_run	organism	truth_technology	truth_quality_tier	biosample	bioproject	sample_origin	read_depth_x
ecoli_01	GCF_012345678.1	SRR12345678	Escherichia coli	hybrid	A	SAMN123	PRJNA123	clinical	80
```

`sample_id` must be unique. `assembly_accession` must be a complete, preferably
long-read or hybrid, reference assembly. `sra_run` must be a matched Illumina
run for the same isolate. The pipeline validates missing fields, duplicate IDs,
and an empty sheet before starting a data stage.

`sample_origin` is deliberately free text: use the labels meaningful to your
programme, such as `clinical`, `environmental`, `wastewater`, or `livestock`.
`read_depth_x` is an optional positive numeric fold coverage. The report derives
true plasmid size from the reference truth table, so it does not rely on a
manually entered size.

Choose reference and read pairs carefully: an assembly and read set from
different isolates invalidates the benchmark. See `docs/FINDING_DATA.md` for
curation guidance.

## Commands

### Install dependency tools

After installing the lightweight PlasBench command, install only the optional
bioinformatics groups required for your planned stages. The command uses
micromamba, mamba, or conda and installs into `plasbench` by default:

```bash
plasbench install-tools core
plasbench install-tools assembly
plasbench install-tools reconstruction
plasbench install-tools all
plasbench install-tools --env myenv mob_suite
```

`core` installs NCBI download, QC, and minimap2 tools; `assembly` installs
SPAdes/Unicycler; `reconstruction` installs MOB-suite/Platon. `gplas` and
`gplas2` remain optional because their classifier/database setup must be
recorded separately. Run `plasbench install-tools --help` for the exact syntax.

Run `plasbench --help` for the concise command list and `plasbench run --help`
for all run options.

```text
plasbench demo
    Offline synthetic two-sample benchmark. Creates results_demo/ and requires
    no downloads or bioinformatics executables.

plasbench test
    Unit-test the scoring implementation on small hand-built examples.

plasbench check
    Run the dependency preflight only (stage 0).

plasbench run [STAGE ...] [OPTIONS]
    Run all stages by default, or only the listed stage numbers.

plasbench report [OPTIONS]
    Rebuild stage 6 outputs from an existing scores.tsv and tool_status.tsv.

plasbench docs [--topic TOPIC]
    Print this guide or one named section to the terminal.
```

Global option:

```text
--project-root PATH
    Source checkout containing scripts/run_all.sh. Put this before the command
    when running from another directory.
```

Examples:

```bash
plasbench run --samples my_samples.tsv --threads 8
plasbench run 3 4 5 6 --platon off --assembler unicycler
plasbench report --results-dir results
plasbench --project-root /path/to/plasbench demo
```

## Run Options

### Inputs and outputs

```text
--samples PATH          Sample-sheet TSV; default: config/accessions.tsv.
--data-dir PATH         Downloaded references, reads, and assemblies.
--results-dir PATH      Predictions, score tables, leaderboards, and HTML report.
--log-dir PATH          Per-stage, per-tool, and mapping logs.
--platon-db PATH        Installed Platon database directory.
```

### Resources and assembly

```text
--threads INTEGER       CPU threads per tool. Default: 4.
--memory-gb INTEGER     plasmidSPAdes memory limit in GB. Default: 16.
--assembler NAME        spades or unicycler. Default: spades.
--min-read-len INTEGER  Minimum retained read length after fastp. Default: 50.
--minimap2-preset NAME  Assembly alignment preset. Default: asm5.
```

### Tool selection

```text
--mob-recon on|off       Enable or disable MOB-suite. Default: on.
--platon on|off          Enable or disable Platon. Default: on.
--plasmidspades on|off   Enable or disable plasmidSPAdes. Default: on.
--gplas on|off           Enable or disable experimental gplas. Default: off.
--force-rerun-tools      Delete completed tool outputs and run them again.
```

The CLI options override `config/config.sh` for that invocation only. Edit the
config file when you want a persistent local default.

## Workflow

`plasbench run` runs stages 0-6. Select stages explicitly to resume or iterate:

```text
0  setup       Check executables and configured databases.
1  download    Retrieve complete assembly files and SRA reads.
2  truth       Build plasmid/chromosome labels from the NCBI sequence report.
3  assemble    Trim reads and assemble short-read contigs.
4  reconstruct Run enabled plasmid-reconstruction tools and standardize FASTA.
5  score       Align predictions to the reference and calculate base-level metrics.
6  aggregate   Build leaderboards and the interactive HTML report.
```

Examples:

```bash
plasbench run 0
plasbench run 1 2
plasbench run 3 4 5 6
plasbench run 4 --force-rerun-tools
```

Stages preserve completed outputs where safe. Stage 4 only reuses a tool result
when it has both a prediction FASTA and completion marker. Failed, skipped, and
reused states are written to `results/tool_status.tsv`.

## Outputs

The main outputs are written under `results/` unless `--results-dir` is set.

```text
results/scores.tsv
    One row per scored sample/tool: true plasmid bp, TP, FP, FN, unmapped bp,
    base-level precision/recall/F1, plasmid-level recovery, and optional AMR
    gene and circular-plasmid recovery metrics.

results/benchmark.paired_comparisons.tsv
    Pairwise, shared-sample F1 differences with win/tie/loss counts. Use this
    with the leaderboard's deterministic bootstrap F1 interval; neither is a
    substitute for a pre-specified statistical analysis plan.

results/run_manifest.json
    Machine-readable provenance: input checksums, sample metadata, settings,
    available tool versions, platform/container/database identity, per-tool
    runtime and peak RSS where GNU time is available, and output checksums.

results/tool_status.tsv
    Per sample/tool execution state: completed, reused, failed, or skipped,
    with a failure reason or log location when available.

results/benchmark.leaderboard.tsv
    Per-tool mean/median metrics, ranked by mean F1, with coverage counts.

results/benchmark.leaderboard.md
    A portable Markdown rendering of the leaderboard.

results/benchmark.report.html
    Offline interactive final dashboard. It includes filters, sortable tables,
    tool and sample drill-downs, automated descriptive interpretation, metric
    glossary, status coloring, SVG metric chart, and a downloadable file tree.
    Score filters include organism, origin, truth technology/tier, truth-derived
    plasmid-size band, read-depth range, and recorded tool version; exported CSV
    contains the exact visible rows and these metadata columns.

results/<sample>/
    Standardized prediction FASTAs, alignments, tool output, and completion markers.

logs/
    Tool and minimap2 logs for diagnosis.
```

Open the HTML report locally in a browser. Its direct file links are designed
for a local run directory; Galaxy uses a separately packaged output layout.

## Metric Definitions

All quantities are base pairs (bp) projected onto the complete reference:

```text
TP  True plasmid-reference bases covered by a predicted-plasmid alignment.
FP  Chromosome-reference bases covered by a predicted-plasmid alignment.
FN  Plasmid-reference bases not covered by a predicted-plasmid alignment.
Precision = TP / (TP + FP). High precision means low chromosome contamination.
Recall = TP / (TP + FN). Also called completeness.
F1 = harmonic mean of precision and recall, from 0 to 1.
Unmapped predicted bp = predicted bases not aligned to any labelled reference.
```

Unmapped prediction is reported separately and is not added to FP. Tool failure
is not converted into a zero score; it is excluded from the leaderboard and
shown in execution coverage.

`plasmid_recall` is the fraction of true plasmid replicons recovered to at
least `PLASMID_RECOVERY_THRESHOLD` (default 0.90). Add curated optional truth
tables as `data/<sample>/truth_amr.tsv` (`sequence_id`, `start`, `end`; 0-based
half-open intervals) and `data/<sample>/truth_circular.tsv` (`sequence_id`) to
activate AMR-gene and circular-plasmid recovery metrics. PlasBench validates
that these entries refer to labelled plasmid reference sequences.

## Console Messages

Console output is timestamped. It announces selected stages, each active stage,
sample/tool execution, warnings, output locations, and the final leaderboard.
Long-running runs do not yet estimate total completion time; use log timestamps
and `results/tool_status.tsv` to monitor progress.

## Troubleshooting

```text
Empty sample sheet
    Add valid data rows to config/accessions.tsv or pass --samples PATH.

Missing executable
    Activate the plasbench Conda environment, then run plasbench check.

Platon database missing
    Install/mount the database and use --platon-db PATH, or run --platon off.

Tool failure on one sample
    Inspect logs/<sample>.<tool>.log and results/tool_status.tsv. Other tools
    and samples continue where possible.

Interrupted run
    Rerun the needed stages. Completed tool outputs are reused by default.

Need a fresh reconstruction
    Use --force-rerun-tools with stage 4, then rerun stages 5 and 6.

WSL or Bash issue on Windows
    Use Ubuntu WSL2. The CLI detects Git Bash when available, but the full
    bioinformatics environment is supported on Linux/WSL2.
```

## Reproducibility and Citation

Record the PlasBench version, command line, `config/config.sh`, input sample
sheet, tool versions, database versions, and final report alongside published
results. After a stable native installation, export the environment:

```bash
conda env export --name plasbench > env/environment.lock.yml
```

Review `docs/METHODS.md` when writing methods. Use the citations for the tools
you enable, plus the appropriate NCBI/SRA data citations.

## Public Deployment

The repository includes Docker, GitHub Actions, Bioconda recipe scaffolding,
and an initial Galaxy scoring wrapper. See `docs/RELEASING.md` and `galaxy/`
before publishing a release. Public Galaxy deployment requires versioned
containers, preloaded tool databases, input limits, and wrappers for all stages.
