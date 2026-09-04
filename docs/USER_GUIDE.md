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
plasmidSPAdes, and optional classifier-backed gplas2 modes. It is designed for bacterial isolates
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

`plasbench check` reports every missing tool and database (only those actually
switched on in `config/config.sh`) -- NCBI Datasets, SRA Toolkit, fastp,
minimap2, SPAdes/plasmidSPAdes, MOB-suite, Platon, Flye, Bakta/Prokka, and the
Platon/MOB-suite/Bakta databases -- and, for every gap an `install-tools`
profile or database script can fix, offers to install it right there:

```bash
plasbench check           # asks before installing anything
plasbench check --yes     # installs every fixable gap without asking (CI/scripted use)
```

A gap it cannot fix automatically (gplas, which installs outside conda; the
base Python/unzip packages, which come from `env/setup_conda.sh` itself) is
reported with a pointer instead. Since a freshly installed tool is not on
this shell's `PATH` until you `conda activate plasbench` again (or open a new
shell after a conda bootstrap), `plasbench check` always exits non-zero after
attempting a fix and asks you to re-run it to confirm -- it never assumes an
install it just started actually finished.

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
long-read or hybrid, reference assembly. `sra_run` must be a matched paired-end Illumina
run for the same isolate. The pipeline validates missing fields, duplicate IDs,
and an empty sheet before starting a data stage.

### Read and reference formats

PlasBench reconstructs plasmids from **paired short-read FASTQ** input. Expected
local filenames are `<sra_run>_1.fastq.gz` and `<sra_run>_2.fastq.gz`; uncompressed
`.fastq` files should be compressed before running. The reference is a completed
FASTA (`reference.fna`) generated using long reads or hybrid sequencing. ONT/PacBio
FASTQs are not a native reconstruction input in the current version; their role is
to establish an independent complete reference. Online cohort validation obtains
`sequencing_tech` and `assembly_method` from NCBI Datasets v2 and rejects truth
assemblies without explicit long-read evidence.

`sample_origin` is deliberately free text: use the labels meaningful to your
programme, such as `clinical`, `environmental`, `wastewater`, or `livestock`.
`read_depth_x` is an optional positive numeric fold coverage. The report derives
true plasmid size from the reference truth table, so it does not rely on a
manually entered size.

Two ready-to-run, metadata-verified panels ship with PlasBench.
`cohorts/public-v1.tsv` is a frozen ten-isolate seed panel where every row is
tier A (evidence verified and publication reviewed); use it for reproducible
headline results. `cohorts/public-v2.tsv` adds 22 tier-B isolates for broader
organism and geographic coverage — evidence verified, publication review
pending. Run `plasbench validate-cohort --samples <panel> --online` before
downloading; `cohorts/README.md` documents scope, tiers, and sources.

Choose reference and read pairs carefully: an assembly and read set from
different isolates invalidates the benchmark. See `docs/FINDING_DATA.md` for
curation guidance.

### Local/offline inputs

Use `--local-inputs` when the reference and reads are already on your machine.
This mode never calls NCBI or SRA clients. Keep a normal sample sheet, then
place these files under the selected data directory before stages 1--6:

```text
data/<sample_id>/reference.fna
data/<sample_id>/truth.tsv                 # OR sequence_report.jsonl
data/<sample_id>/<sra_run>_1.fastq.gz
data/<sample_id>/<sra_run>_2.fastq.gz
```

For example: `plasbench run --samples local.tsv --data-dir ./data --local-inputs`.
Stage 1 verifies the reference, paired FASTQs, and either an NCBI sequence report
or a user-supplied three-column `truth.tsv` (`sequence_id`, `molecule_type`,
`length`). Stage 2 records observed depth from the staged FASTQs; this is the
depth used by the ladder rather than an unverified hand-entered value.

## Commands

### Depth ladder

Create a reproducible local-input cohort at fixed target depths after staging
the original paired reads. Run stage 2 first: the ladder uses measured depth
from `observed_depth.tsv`, rejects a declared depth differing by more than 20%,
and every target must not exceed observed source depth:

```bash
plasbench depth-ladder --samples cohorts/public-v1.tsv --data-dir data \
  --out-dir depth-ladder --depths 20,40,80,160 --seed 20260901
plasbench run --samples depth-ladder/depth_ladder.samples.tsv \
  --data-dir depth-ladder/data --results-dir depth-ladder/results \
  --local-inputs

# Summarise the recovery curve and create a portable SVG for reports.
plasbench depth-report --scores depth-ladder/results/scores.tsv \
  --manifest depth-ladder/depth_ladder.manifest.tsv \
  --out-prefix depth-ladder/results/depth_ladder
```

`depth-report` writes `depth_ladder.summary.tsv` (tool, target depth, number
scored, and mean precision/recall/F1/plasmid recall) and
`depth_ladder.recovery.svg`. The SVG is a standalone, data-derived recovery
versus coverage plot; it does not replace per-sample results or uncertainty
analysis. Compare depths only within the same source cohort, seed, tool version,
and configuration.

The generated manifest records the parent isolate, sampling fraction, target
depth, and seed. It never overwrites the original reads or cohort. Do not run a
headline leaderboard on a depth-ladder sheet: subsamples share parent genomes;
PlasBench blocks this and `depth-report` is the valid analysis path.

### Install dependency tools

After installing the lightweight PlasBench command, install only the optional
bioinformatics groups required for your planned stages. The command uses
micromamba, mamba, or conda and installs into `plasbench` by default:

```bash
plasbench install-tools core
plasbench install-tools assembly
plasbench install-tools reconstruction
plasbench install-tools long-read
plasbench install-tools annotation
plasbench install-tools annotation-prokka
plasbench install-tools all
plasbench install-tools --env myenv mob_suite
```

`core` installs NCBI download, QC, and minimap2 tools; `assembly` installs
SPAdes/Unicycler; `reconstruction` installs MOB-suite/Platon. Install `gplas`
separately with its documented dependencies. `RUN_GPLAS2_MOB=1` then seeds
gplas with deterministic MOB-recon membership from the same assembly graph and
writes a provenance JSON; these seed values are hard labels, not calibrated
probabilities. `RUN_GPLAS2_EXTERNAL=1` accepts a validated external classifier
TSV instead. Run `plasbench install-tools --help` for the exact syntax.

### Optional Protein Names And Functional Tracks

Raw FASTA contains nucleotide bases, not protein names. To add standardized
protein labels to the interactive report, install Bakta (recommended) and set
the following before `plasbench run`:

```bash
plasbench install-tools annotation
export RUN_PROTEIN_ANNOTATION=1
export PROTEIN_ANNOTATION_ENGINE=bakta
# Set this when Bakta has no configured default database.
export PROTEIN_ANNOTATION_DATABASE=/path/to/versioned/bakta_db
```

PlasBench then annotates the reference and every standardized predicted-plasmid
FASTA using one engine, caches results by normalized sequence checksum, and
records annotation provenance. The viewer displays gene/product names,
functional categories, coordinates, and projected nucleotide-coordinate
recovery. This projection is useful for locating named genes such as `blaCTX-M`,
`repA`, or `traI`, but is **not** protein identity, orthology, frameshift, or
closure validation. Missing Bakta/Prokka is reported as `not evaluated`; it
does not change DNA-level scores or mean F1.

For reproducible cached Bakta annotations, provide
`PROTEIN_ANNOTATION_DATABASE`; an implicit/default Bakta database is allowed
for exploration but is intentionally not reused from the persistent cache.

Use `PROTEIN_ANNOTATION_ENGINE=prokka` only as a compatible fallback. Do not
mix engines in one headline comparison. Online BLASTx remains appropriate for
manual investigation of a small number of sequences, not automated benchmark
annotation, because database state and results are not reproducibly pinned.

Run `plasbench --help` for the concise command list and `plasbench run --help`
for all run options.

```text
plasbench demo
    Offline synthetic two-sample benchmark. Creates results_demo/ and requires
    no downloads or bioinformatics executables.

plasbench test
    Run the complete offline regression suite (all unit tests plus the
    synthetic end-to-end adapter check) -- no downloads or bioinformatics
    executables needed.

plasbench check [--yes]
    Dependency preflight (stage 0): reports every missing tool/database and
    offers to install what it can (conda itself, install-tools profiles,
    the Platon/MOB-suite/Bakta databases). --yes skips the confirmation.

plasbench install-conda [--yes] [--prefix DIR]
    Check for conda/mamba/micromamba; offer to install Miniforge if none is found.

plasbench validate-cohort --samples PATH [--online]
    Validate cohort schema. With --online, verify complete plasmid-containing
    assembly metadata plus exact SRA BioSample/BioProject linkage and paired
    Illumina library metadata. Use --write-lock PATH to save the evidence.

plasbench run [STAGE ...] [OPTIONS]
    Run all stages by default, or only the listed stage numbers.

plasbench report [OPTIONS]
    Rebuild stage 6 outputs from an existing scores.tsv and tool_status.tsv.

plasbench reconstruct --sample ID --sra RUN [--tool TOOL] [OPTIONS]
    Reconstruct plasmids for one new, truth-unknown operational sample using
    only ONE method -- the benchmark's evidence-gated recommendation, or an
    explicit --tool override -- instead of every benchmarked tool. See
    "Operational Selection" below.

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
--gplas2-external-predictions-dir PATH
                       Directory containing one validated <sample>.tsv classifier table per sample.
```

### Resources and assembly

```text
--threads INTEGER          CPU threads per tool. Default: 4.
--memory-gb INTEGER        plasmidSPAdes memory limit in GB. Default: 16.
--parallel-samples INTEGER Samples to download/assemble/reconstruct/score concurrently.
                           Default: 1 (sequential, the safe starting point).
--parallel-tools INTEGER   Independent stage-4 tools to run concurrently per sample
                           (mob_recon, platon, plasmidspades, gplas2_external;
                           gplas2_mob still always waits for that sample's mob_recon).
                           Default: 1 (sequential).
--assembler NAME        spades or unicycler. Default: spades.
--min-read-len INTEGER  Minimum retained read length after fastp. Default: 50.
--minimap2-preset NAME  Assembly alignment preset. Default: asm5.
```

Every stage still behaves exactly as before at the defaults (1, 1): one sample, one
tool, at a time, and a failure aborts the run immediately. Raising either only changes
wall-clock time, never the science -- the same tools run with the same inputs and
produce the same scores, just overlapped. Stage 4's `THREADS` is shared by every tool
unless you set `MOB_RECON_THREADS`, `PLATON_THREADS`, `PLASMIDSPADES_THREADS`, or
`GPLAS_THREADS` individually (each defaults to `THREADS`); once several tools run at
once, giving each of them the full thread count oversubscribes the CPU and can make
the run slower, not faster. A preflight warning fires (but never blocks) when the
requested concurrency's total threads or memory clearly exceeds the host.

Downloads (stage 1) are network-bound and usually tolerate the most concurrency;
assembly (stage 3, SPAdes/Unicycler) is memory-hungry and should be raised the most
conservatively; scoring (stage 5) is lightweight and cheap to parallelize. Start
conservatively (`--parallel-samples 2`), watch `results/tool_status.tsv` for
`runtime_seconds`/`peak_rss_kb`, and raise it only after confirming the host has
headroom -- back off if it starts swapping.

Above `--parallel-samples 1`, one sample's download or assembly failure no longer
aborts sibling samples already in flight (concurrency means work already started
keeps going), but every failure is still collected, named in the log, and the run
still exits non-zero -- nothing fails silently.

### Tool selection

```text
--mob-recon on|off       Enable or disable MOB-suite. Default: on.
--platon on|off          Enable or disable Platon. Default: on.
--plasmidspades on|off   Enable or disable plasmidSPAdes. Default: on.
--gplas2-mob on|off      Run gplas with same-graph MOB-recon hard-label seeds.
--gplas2-external on|off Run gplas with validated external classifier TSVs.
--force-rerun-tools      Delete completed tool outputs and run them again.
```

The CLI options override `config/config.sh` for that invocation only. Edit the
config file when you want a persistent local default. `--gplas2-mob on`
requires gplas, a successful MOB-recon result, and an assembly graph. It fails
safely if MOB and graph contig identifiers do not agree.

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
    gene and circular-plasmid recovery metrics. When bin membership is supplied,
    this also includes bin precision/recall/F1, matched/unmatched bins, missed
    plasmids, split/merge event counts, and bins with chromosome-aligned
    contamination.

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

results/benchmark.recommendations.tsv
    Coverage-gated, multi-objective primary-method recommendations overall and
    by available organism, truth-technology, origin, plasmid-size, and
    read-depth strata. A small or incompletely covered tool is not promoted.

results/benchmark.stratified.tsv
    The complete per-tool stratified metric and eligibility table supporting
    those recommendations.

results/benchmark.recommendation_validation.tsv
    Leave-one-source-study-out release safeguard. It reports when an
    independent study test is unavailable rather than pretending validation.

results/benchmark.<track>.leaderboard.tsv
    Separate leaderboard for each declared short-read, long-read, or hybrid
    analysis track; conclusions from different tracks are not pooled.

results/benchmark.report.html
    Offline interactive final dashboard. It includes filters, sortable tables,
    tool and sample drill-downs, automated descriptive interpretation, metric
    glossary, status coloring, SVG metric chart, and a downloadable file tree.
    Score filters include organism, origin, truth technology/tier, truth-derived
    plasmid-size band, read-depth range, and recorded tool version; exported CSV
    contains the exact visible rows and these metadata columns.
    Its Bin reconstruction diagnostics table links to the record-level
    `<tool>.bin_matches.tsv` evidence for every bin-scored sample/tool pair.
    The Reconstruction evidence explorer opens one truth plasmid at a time with
    alignment tracks, structural navigation (mismatch, gap, inversion,
    breakpoint), a split/merge map, protein category filters, a nucleotide view
    where a CIGAR-bounded alignment exists, and TSV/JSON/BED/FASTA/PNG export.
    It follows the sample and plasmid selected in the report. Read coverage is
    never computed by projection scoring, so it reads "not measured" and exports
    as `NA` rather than 0; every structural call is alignment-derived and
    labelled unvalidated.
    The Visual reconstruction quality section adds a metric-switchable
    sample-by-tool heatmap, linked truth-plasmid recovery tracks, coordinate
    zoom, block-level PAF inspection, AMR markers, and JSON download.

results/<sample>/visualization/alignment_blocks.json
    Bounded reference-coordinate primary-alignment blocks and per-plasmid
    completeness for the offline explorer. This is visual evidence, not a
    nucleotide multiple alignment or proof of structural closure.

results/<sample>/
    Standardized prediction FASTAs, alignments, tool output, and completion markers.

results/selected_candidates/<sample>/
    The best already-produced truth-set candidate FASTA, any available bin/map
    evidence, and `<sample>.selection_report.json`. Every file is prefixed with
    the sample id so candidates stay identifiable once gathered together. This
    is copied after scoring and does not rerun reconstruction or fabricate a
    consensus sequence.

logs/
    Tool and minimap2 logs for diagnosis.
```

Open the HTML report locally in a browser. Its direct file links are designed
for a local run directory; Galaxy uses a separately packaged output layout.
See `docs/VISUAL_QUALITY.md` for interaction details, colour meanings, display
limits, and interpretation boundaries.

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

For AMR truth used in recommendations, use the stricter versioned schema:
`sequence_id`, `start`, `end`, `gene_name`, `gene_id`, `copy_id`, `database`,
and `database_version`. Validate it before a run with:

```bash
python python/validate_amr_truth.py --truth data/SAMPLE/truth.tsv \
  --amr-truth data/SAMPLE/truth_amr.tsv
```

Optional `pred_<tool>.evidence.tsv` files can carry source-reported replicon,
MOB, or closure evidence using `record_id`, `evidence_type`, and
`evidence_value`. They are shown in the selection card but are not treated as
independent structural proof.

## Operational Selection

Stage 6 automatically retains the best already-generated candidate for every
scored sample in `results/selected_candidates/<sample>/`. The choice is a
transparent, multi-objective prioritisation of F1, plasmid/bin recovery,
precision/recall, unmapped sequence, ambiguity, contamination, and split/merge
diagnostics. It is not proof of plasmid closure or biological correctness.

`benchmark.recommendations.tsv` is a separate operational-method suggestion
that is withheld until a method satisfies `RECOMMENDATION_MIN_SAMPLES` and
`RECOMMENDATION_MIN_COVERAGE`. It may be rerun without reconstruction:

```bash
plasbench select-candidates --scores results/scores.tsv \
  --samples config/accessions.tsv --results-dir results \
  --tool-status results/tool_status.tsv --out-prefix results/benchmark
```

For high-consequence calls, structurally complex plasmids, mapping ambiguity,
or any report marked `requires_confirmation`, use long-read/hybrid or other
orthogonal confirmation. Circular-truth recovery means a circular reference was
covered; it does not prove a predicted sequence is circular. Full policy:
`docs/OPERATIONAL_SELECTION.md`.

### Two execution modes: benchmarking versus a new sample

PlasBench's stage 4 running every enabled tool is the actual benchmark
experiment: it is how the leaderboard and `benchmark.recommendations.tsv`
above get produced, and every sample already scored in that cohort keeps its
reconstructions in `results/<sample>/pred_<tool>.plasmid.fasta` -- rerunning
`plasbench run` reuses them (stage 4 skips a tool once its `.complete` marker
and prediction exist; `select-candidates`/`select-unknown` only ever copy an
already-produced prediction) rather than reconstructing the same sample again.

A genuinely new sample -- one with no complete-reference truth, arriving after
the benchmark already picked a method -- does not need every tool run against
it. `plasbench reconstruct` downloads its reads, assembles them, and runs only
ONE reconstruction tool: the benchmark's evidence-gated recommendation for the
sample's organism/Gram group (or overall, if neither has one), or an explicit
override:

```bash
# Let the benchmark recommendation decide which single tool to run.
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678 \
  --organism "Klebsiella pneumoniae" --gram-group Gram_negative

# Or force a specific tool, bypassing the recommendation lookup entirely.
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678 --tool mob_recon
```

This writes `results/new_isolate_01/pred_<tool>.plasmid.fasta` and
`results/new_isolate_01/selected_candidate/candidate.plasmid.fasta`, plus a
`selection_report.json` recording whether the tool came from the benchmark
recommendation or an explicit override -- always with `truth_available: false`
and `confidence_tier: confirmation_required`, since there is no reference to
score this sample against. Reserve `plasbench run` with every tool enabled for
building or extending the benchmark cohort itself, not for routine operational
samples.

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

## Long-Read Reconstruction

PlasBench can optionally run native ONT or PacBio FASTQ reconstruction through
Flye followed by MOB-Recon. Install the profile, stage one file per sample as
`data/<sample>/long_reads.fastq.gz`, then run stage 7 followed by scoring and
aggregation under a separate long-read track:

```bash
plasbench install-tools long-read
plasbench run 7 --flye-mob-recon on --flye-read-type nano-hq
plasbench run 5 6 --analysis-track long_read
```

Use `nano-raw`, `nano-hq`, `pacbio-raw`, or `pacbio-hifi` to match the source
reads. Flye assembly is not itself called a plasmid reconstruction: MOB-Recon
must complete successfully before PlasBench emits a predicted-plasmid FASTA.
The long-read track is reported separately and cannot be mixed with short-read
or hybrid conclusions. A native hybrid FASTQ adapter remains out of scope.

For source-backed structural evidence, optionally supply
`results/<sample>/pred_<tool>.evidence.tsv` with the columns `record_id`,
`evidence_type`, `evidence_value`, `evidence_source`, and `evidence_version`.
Closure rows also need a positive `supporting_reads` value and a `long_read`,
`hybrid_assembly`, or `assembly_graph` source. PlasBench validates the table
before displaying it; it never infers closure from a FASTA record alone.

For an unlabelled operational sample, use only a completed, independently
validated benchmark recommendation. The command copies an existing nominated
prediction when present but always marks the report confirmation-required:

```bash
plasbench select-unknown --recommendations results/benchmark.recommendations.tsv \
  --sample-id new_isolate --results-dir results \
  --organism "Klebsiella pneumoniae" --gram-group Gram_negative
```

Record the PlasBench version, command line, `config/config.sh`, input sample
sheet, tool versions, database versions, and final report alongside published
results. After a stable native installation, export the environment:

```bash
bash env/lock_environment.sh
```

Review `docs/METHODS.md` when writing methods. Use the citations for the tools
you enable, plus the appropriate NCBI/SRA data citations.

## Public Deployment

The repository includes Docker, GitHub Actions, Bioconda recipe scaffolding,
and an initial Galaxy scoring wrapper. See `docs/RELEASING.md` and `galaxy/`
before publishing a release. Public Galaxy deployment requires versioned
containers, preloaded tool databases, input limits, and wrappers for all stages.
