# PlasBench User Guide

PlasBench benchmarks plasmid-reconstruction tools against complete reference
assemblies. It converts each tool's plasmid prediction into a common base-level
comparison: reference plasmid bases are the positive class and reference
chromosome bases are the negative class.

Run this guide from a source checkout with `plasbench docs`, or print one
section with `plasbench docs --topic <name>`.

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
with one isolate per row:

```text
sample_id	assembly_accession	sra_run
ecoli_01	GCF_012345678.1	SRR12345678
```

`sample_id` must be unique. `assembly_accession` must be a complete, preferably
long-read or hybrid, reference assembly. `sra_run` must be a matched Illumina
run for the same isolate. The pipeline validates missing fields, duplicate IDs,
and an empty sheet before starting a data stage.

Choose reference and read pairs carefully: an assembly and read set from
different isolates invalidates the benchmark. See `docs/FINDING_DATA.md` for
curation guidance.

## Commands

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
    precision, recall, and F1.

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
