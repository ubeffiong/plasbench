# PlasBench User Guide

## What PlasBench Is

PlasBench is a reproducible bioinformatics benchmark for answering a practical
question: **which plasmid-reconstruction method performs best for a given set
of bacterial samples?**

Different tools report plasmids in different ways. Some classify assembled
contigs as plasmid or chromosome, while others assemble a separate set of
putative plasmid sequences. PlasBench makes their output comparable by mapping
every predicted-plasmid FASTA back to a complete reference assembly and scoring
the same reference bases for every tool.

The benchmark compares, on the short-read track, MOB-suite `mob_recon`,
Platon, plasmidSPAdes, optional classifier-backed gplas2 modes, the ML
classifiers geNomad, PLASMe, plASgraph2, RFPlasmid, PlasmidHunter and Plasmer, and the
species-gated (E. coli/Klebsiella only) Centrifuge classifier PlaScope; and,
on the long-read and hybrid
tracks, `flye_mob_recon`, `hybracter_long`, `trycycler_mob_recon`,
`plassembler` and `hybracter_hybrid`. Everything beyond the short-read core is
off by default and switched on per tool. Every isolate needs a complete
long-read or hybrid reference from the same isolate; the long-read track
additionally needs reads independent of that reference (see COHORTS.md).

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
./install.sh
conda activate plasbench
plasbench check
plasbench test
plasbench demo
```

The installer records a stable shared directory for downloaded FASTQs, truth
references, and databases: `~/.local/share/plasbench/data` by default (or
`$XDG_DATA_HOME/plasbench/data`). Code can therefore live in versioned release
directories without duplicating multi-gigabyte inputs. Choose another location
on the first install with:

```bash
PLASBENCH_DATA_DIR=/mnt/fast-disk/plasbench-data ./install.sh --tools
```

Upgrade from inside an installed release with either command below. The first
upgrade from an older release moves its local `data/` directory once into the
shared location and leaves a compatibility link; later upgrades reuse it.

```bash
./update.sh
plasbench upgrade
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

A gap it cannot fix automatically (the base Python/unzip packages, which come
from `env/setup_conda.sh` itself) is reported with a pointer instead. Since a
freshly installed tool is not on
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

The window (`plasbench ui`) is for your own computer: it listens on 127.0.0.1 only and opens that computer's folder window. Inside a container it has no desktop, so Browse uses the built-in
browser at the mounted folders; see "The folder window does not open" above for **Add another folder** and **Run in Docker instead**.

### Installing Docker from the tools setup

Docker is optional. The **Tools** page has a *Docker* card (and the Workflow view an optional *Docker (container engine)* item under *Check and install*) with a live state label (not installed, Docker Desktop installed but not started, Docker Desktop starting, WSL integration off, installed with the daemon stopped, permission needed, ready), a four-step checklist (installed, running, engine answering with the licence accepted, WSL integration; hover a step to see what was found), one primary button for the next action (**Install Docker**, **Start Docker Desktop**, **Open WSL integration settings**, then **I enabled it**, or **Re-check**) and **Open the Docker guide**. **Start Docker Desktop** and the integration helper ask first; PlasBench only starts the program and opens the page: it never accepts the Docker licence or changes Docker Desktop's settings. **Install Docker** lists exactly what will run, who approves it and the Docker Desktop licence note before anything starts; on Windows (and WSL 2) it runs `winget install -e --id Docker.DockerDesktop` on the Windows side and Windows asks you to approve the installer, on macOS `brew install --cask docker-desktop`. Where only you can act (sudo, the licence, WSL integration) it shows the steps and a copyable script, and the job ends as *Waiting for you to finish in ...* (exit 20, not an error) until you press **Re-check**. The same thing from a terminal: `plasbench install-tools docker [--yes] [--start] [--open-integration] [--wait SECONDS] [--dry-run]`; once Docker Desktop is installed the plan says what is left and skips the installer. The *Run in Docker instead* button of the folder chooser and Settings shows *Install Docker first* when Docker is not ready. `scripts/docker_run.sh` prints the same diagnosis when Docker is missing. Details per platform: INSTALL.md, "Installing Docker".

### Installing the tools

Tools install with your consent, each in its own isolated environment, from a pinned release or an exact commit: `plasbench install-tools NAME --yes` (a first install of a source-built tool
shows its plan and stops without `--yes`), `plasbench install-tools a,b --yes`, `plasbench install-tools all --yes`, or `plasbench check --yes` for exactly what your enabled tools need.
`plasbench run --install-missing-tools` (or `INSTALL_MISSING_TOOLS=1`) installs missing enabled tools before the run; without it a run with a missing enabled tool stops at its first check,
naming each one and the command. In the window, the Tools page has Install and Update buttons per tool, **Install all enabled tools** (one confirmation dialog) and a progress strip; the Workflow
cards show the same state, and starting a run offers to install missing enabled tools first. Exit codes 20 (a manual step; plsMD and PPR-Meta) and 21 (consent needed) are information, not
errors. The per-tool table is `docs/TOOL_INSTALL_AUDIT.md`.

## The window at a glance

`plasbench ui` opens the window in your browser. The left-hand list follows the order you work in:

| Group | Pages | What you do there |
|---|---|---|
| Overview | Home | See whether this computer is ready; start the offline demo |
| Set up | Set up this computer | Check and fix every dependency; Conda or Docker; NCBI access; tool profiles |
| Benchmark | Workspace & studies, Cohorts, Your own isolates, New benchmark | Choose where studies live, pick or add the isolates, then start a run |
| Results | Runs & reports, Jobs | Open reports, resume interrupted runs, read job logs |
| Tools & rules | Tools, Add your own tool, Scoring decisions | Switch tools on or off, add your own, see the fixed scoring rules |
| Advanced | Version control, All commands | Git for your work; every command as a form |
| Settings & help | Settings, Guides | Every setting with its default; the README and the guides |

The top bar keeps the few things you need all the time: the folder tree and job panel (**Panel**), the internet indicator, the **Console** and **Quit**. Help for the page (F1), reloading the page and the light or dark theme are in the **More** menu (the three dots).

**Where did the explanation text go?** Pages show a title, one line saying what they are for, and the controls. What a control means, what an option does and how a page works is in the small green **?** next to the label: hover it, tab to it with the keyboard, or tap it on a phone; press **Escape** to close it. The same text is kept in one place, `plasbench/ui_help.py`. Anything you must act on or know before a costly step stays on the page: warnings, errors, offline or blocked reasons, disk-space notes, and the reminder that closing the window does not stop runs.

### The Terminal tab: which shells, and why

The shell list depends on where the window runs. **Windows:** each Ubuntu (WSL) distribution, Git Bash (when Git for Windows is installed), PowerShell and Command Prompt (cmd). **Ubuntu (WSL), where `plasbench ui` runs inside WSL:** your Ubuntu shell, labelled with the distribution (for example *Ubuntu-24.04 (Bash)*) and still the default, plus **Windows PowerShell** (`pwsh.exe` when installed, else `powershell.exe`), **Windows Command Prompt (cmd)** and **Git Bash (Windows)** when Git for Windows is installed. They are Windows programs started through WSL interop, so they need interop on (the default). With interop off (`[interop] enabled=false` in `/etc/wsl.conf`, or a restart with `wsl --shutdown` needed) the three entries are greyed and their tooltip gives the reason. **Linux and macOS:** your login shell (Bash, Zsh) and PowerShell if `pwsh` is installed. Nothing is started to build the list when the page loads: it is found once in the background the first time you open the Terminal tab.

Running Windows shells from Ubuntu: the folder you are in is translated for Windows (`wslpath -w`: `/mnt/c/Users/me` becomes `C:\Users\me`, a folder inside Ubuntu becomes `\wsl.localhost\<distro>\...`). PowerShell and Git Bash accept that network-style folder, but some Windows programs do not and start in `C:\Windows`; the Terminal says so once, and `cd` to a folder under `/mnt/c` to run them there. **Command Prompt cannot start in such a folder at all**, so PlasBench enters it with `pushd` (a temporary drive letter). The `plasbench` command works in every shell: in Windows shells started from Ubuntu it is a small shim (a PowerShell function, a temporary `plasbench.cmd` that is deleted after the command, a Git Bash function) that calls back into your Ubuntu distribution with `wsl.exe -e`, using the same Python, the same PlasBench folder and the window's PATH. A Windows shell started from Ubuntu cannot see the Ubuntu tools (conda environments, `samtools`): use the Ubuntu shell for those. In Command Prompt, `plasbench` runs in the folder the Terminal was in when the command started, and a line is run as typed (`%VAR%` expands); its built-in commands show only characters of the console code page. Output is shown as UTF-8; the Terminal also reads UTF-16 and the old Windows code pages. A command that runs longer than the time limit is stopped together with everything it started (`taskkill /T /F`).

Each shell keeps its own history (Up and Down). Commands run as you, with no new rights, and still need the window's session key.
**The installing toast.** While any install, pull, build or update is running (a tool or a profile, Docker, conda, the PlasBench image, tool databases, or **Upgrade PlasBench**) a small card stays at the bottom right of every page, so you can move around and still see that it is going. It shows what is being installed, how long it has been running and the latest line of its log. **View log** opens the live log in the console; **Cancel** stops that install after you confirm (what is already installed is kept); **Hide** folds the card into a small **Installing** chip with a spinner and a count in the top bar, and clicking the chip brings the card back. Several installs at once share one card with a count and a list. The card follows the job, not the page: it is still there after a reload or in a second window, and an install started from the terminal appears too. It turns to **Waiting for you to finish in Docker Desktop** (with **Re-check**), **Consent needed**, **Manual step needed** or **Stalled?** when that is true, **Failed** (red, with the reason, until you dismiss it), or **Done** (green, gone after about eight seconds). If installs finished while the window was closed, one **Finished while you were away** note lists them once.

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

When no such assembly was ever deposited (some cohort sources only submit reads),
`assembly_accession` may instead stay blank/`NA` if the row declares
`truth_source=self_assembled_hybrid` plus `long_read_sra_run` -- PlasBench then builds
the truth reference itself from that isolate's own long+short reads. See
`docs/COHORTS.md`'s `truth_source`/`long_read_sra_run` section for the full workflow.

The opposite case is also supported: `truth_source=simulated` keeps a REQUIRED, real
`assembly_accession` as truth, but generates `sra_run`'s reads locally (InSilicoSeq +
Badread) at a depth/seed/error-model you choose, instead of downloading a real sequencing
run -- useful for controlled comparisons a real deposited run cannot give you. See
`docs/COHORTS.md`'s `truth_source=simulated` section for the full column reference.

### Read and reference formats

PlasBench's default input is **paired short-read FASTQ**. Expected local
filenames are `<sra_run>_1.fastq.gz` and `<sra_run>_2.fastq.gz`; uncompressed
`.fastq` files should be compressed before running. The reference is a completed
FASTA (`reference.fna`) generated using long reads or hybrid sequencing.
ONT/PacBio FASTQs serve that reference role on every run, and are additionally a
native reconstruction input for the long-read and hybrid tools when staged as
`data/<sample>/long_reads.fastq.gz` -- those tools are off by default, and a
sample is only eligible for them when the cohort declares its truth independent
of those reads. Online cohort validation obtains
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

### Cohort QC anomaly flagging

Complements `plasbench validate-cohort`'s rule-based checks (missing fields,
mismatched accessions, unlinked BioSample/BioProject -- specific, nameable
violations) with a statistical layer for isolates that pass every rule but
are numerically unusual relative to the rest of the accepted cohort: an
assembly whose N50, contig count, GC%, or plasmid count is a robust outlier.
Stats are computed fresh from each sample's downloaded `reference.fna` at
stage 2 (`data/<sample>/assembly_stats.tsv`), then compared cohort-wide at
stage 6 using robust (median/MAD) modified z-scores -- not mean/stdev, which
breaks down on the small, skew-prone cohorts this benchmark typically has.

This is **advisory only and on by default** (unlike every optional tool
above): it never blocks, excludes, or rejects a sample -- an outlier isolate
might be the most scientifically interesting one in the cohort, not a bad
one. Below `COHORT_QC_MIN_COHORT_SIZE` samples (default 8), detection is
withheld rather than computed on too little data to be meaningful, the same
"withhold, don't guess" policy `benchmark.recommendation_validation.tsv`
already uses. Results land in `results/benchmark.cohort_qc_flags.tsv` and a
"Cohort QC flags" section of the HTML report. Disable entirely with
`COHORT_QC_FLAGS_ENABLED=0` in `config/config.sh`.

### Read-quality ladder

The long-read/hybrid track's analog to the depth ladder: long-read plasmid
recovery is at least as sensitive to read length and quality (R9 vs R10
chemistry) as to depth, and deserves the same rigor before a long-read
leaderboard is trusted. Uses `filtlong` to apply absolute length/quality
thresholds ("rungs") -- a deterministic filter, not a random subsample, so
there is no `--seed`. `filtlong` ships in the `long-read` profile
(`plasbench install-tools long-read`), so anyone already set up for the
long-read track has it; installing it alone also works
(`plasbench install-tools filtlong`).

```bash
plasbench read-quality-ladder --samples cohorts/public-v1.tsv --data-dir data \
  --out-dir read-quality-ladder --rungs 1000:8,5000:10,20000:15
plasbench run --samples read-quality-ladder/read_quality_ladder.samples.tsv \
  --data-dir read-quality-ladder/data --results-dir read-quality-ladder/results \
  --local-inputs --flye-mob-recon on

plasbench read-quality-report --scores read-quality-ladder/results/scores.tsv \
  --manifest read-quality-ladder/read_quality_ladder.manifest.tsv \
  --out-prefix read-quality-ladder/results/read_quality_ladder
```

Each rung is `MIN_LENGTH:MIN_MEAN_Q` (minimum read length in bp, minimum mean
Phred quality); reads failing either threshold are dropped. This ladder
targets the long-read/hybrid tools (`flye_mob_recon`, `plassembler`,
`hybracter_long`, `hybracter_hybrid`, `trycycler_mob_recon`) -- run it with
one or more of those enabled, not the short-read tools. Same correlated-sample
protection as the depth ladder: the generated sheet's `parent_sample_id`
column makes PlasBench refuse a headline leaderboard on it, directing you to
`read-quality-report` instead.

### ML/graph-based classifiers and the PR-curve

Unlike the classical tools (Platon, mob_recon, ...), which are scored as one
hard-inclusion point, an ML classifier that exposes a per-contig probability
(geNomad's `plasmid_score`, and any future tool following the same contract)
is additionally scored with a precision-recall-curve sweep across every
distinct probability value it emits, since threshold choice materially
changes an ML tool's apparent performance in a way it never does for a
classical tool. This is entirely additive: a tool with no probability output
is scored exactly as it always has been.

```bash
plasbench install-tools genomad
bash env/download_genomad_db.sh
plasbench run --genomad on
```

PLASMe (alignment+transformer classifier) follows the same contract from a
different score source -- its `_report.csv`'s `score` column covers every
contig it aligned, not just the ones passing its own hard-call threshold.
It is not installable via `plasbench install-tools plasme` (no bioconda
package exists); see `INSTALL.md` section 6 for the manual git-clone setup.

```bash
bash env/download_plasme_db.sh
plasbench run --plasme on
```

plASgraph2 (GNN classifier over the assembly graph) follows the same
contract too, scored from its own per-node `plasmid_score` column -- it
needs the same `assembly_graph.gfa` gplas2 uses (set `ASSEMBLER=unicycler`
for the cleanest graphs), and its output has no separate hard-call FASTA of
its own: PlasBench derives the hard call from its `label == "plasmid"` rows.
It is not installable via `plasbench install-tools plasgraph2` (no bioconda
package exists, and its pretrained model ships inside its own git checkout);
see `INSTALL.md` section 6 for the manual git-clone setup.

```bash
plasbench run --plasgraph2 on --plasgraph2-model-dir /path/to/plASgraph2/model/ESKAPEE_model
```

RFPlasmid (random forest over single-copy marker genes, plasmid genes, and
kmers) follows the same contract from its own `prediction.csv`'s "votes
plasmid" column. It IS installable via `plasbench install-tools rfplasmid`
(a real bioconda package), but bundles CheckM as a transitive dependency,
and CheckM always needs its own reference data directory configured once
post-install (`checkm data setRoot`), regardless of install method -- see
`INSTALL.md`.

```bash
plasbench install-tools rfplasmid
plasbench run --rfplasmid on
```

PlasmidHunter (Diamond+Prodigal gene-content classifier over one
species-agnostic Naive Bayes model, unlike RFPlasmid's per-species/genus
choice) follows the same contract from its own `predictions.tsv`'s
"Probability of 1" column. It is not a bioconda package -- install it via
`plasbench install-tools plasmidhunter`, which installs its `diamond`/
`prodigal` dependencies through conda and then runs `pip install
plasmidhunter` into the same environment.

```bash
plasbench install-tools plasmidhunter
plasbench run --plasmidhunter on
```

Plasmer (a kmer-db/Prodigal/HMMER/BLAST/Infernal/Diamond/Kraken2 ensemble
feeding an R random-forest model) follows the same contract from its own
`predProb.tsv`'s "plasmid" probability column -- but only for contigs that
actually went through the random-forest step; contigs excluded by its own
length rules (too short, or long enough to be hard-called chromosome) have
no probability at all, and are correspondingly absent from both
`.candidates.fasta` and `.scores.tsv`, not scored as 0. It IS installable
via `plasbench install-tools plasmer`, but from its own custom conda channel
(`-c iskoldt`), needs a separately downloaded database (Zenodo/Google Drive,
not bundled -- point `PLASMER_DB` at it), and documents a real 32GB
system-RAM minimum for its kmer-db step; see `INSTALL.md`.

```bash
plasbench install-tools plasmer
plasbench run --plasmer on
```

Per sample/tool, this writes `<tool>.pr_curve.tsv` (`threshold, precision,
recall, tp_bp, fp_bp, fn_bp`) and `<tool>.pr_summary.tsv` (`pr_auc,
pr_n_thresholds`) under `results/<sample>/`; `mean_pr_auc`/`n_pr_scored`
appear as supplementary leaderboard columns in
`benchmark.leaderboard.tsv` -- never a ranking replacement, and gracefully
absent (not zero) for every tool that doesn't expose a probability. See
`adapters/SCORES.md` for the full adapter contract behind this.

PlaScope (Centrifuge-based hard classification against a species-specific
database) does NOT follow the PR-curve contract above -- it exposes no
continuous score, only a chromosome/plasmid/unclassified call, so it is
scored as one hard-inclusion point like Platon/`mob_recon`, never PR-curve
swept. It also needs a species-specific database that only exists pre-built
for *E. coli* and *Klebsiella*; every other organism is skipped with a
`"no PlaScope database for organism <X>"` reason in `tool_status.tsv`,
distinct from a generic "command unavailable" skip.

```bash
plasbench install-tools plascope
bash env/download_plascope_db.sh
plasbench run --plascope on
```

### Install dependency tools

After installing the lightweight PlasBench command, install only the optional
bioinformatics groups required for your planned stages. The command uses
micromamba, mamba, or conda and installs into `plasbench` by default:

```bash
plasbench install-tools core
plasbench install-tools assembly
plasbench install-tools metagenomics
plasbench install-tools reconstruction
plasbench install-tools long-read
plasbench install-tools annotation
plasbench install-tools annotation-prokka
plasbench install-tools gplas
plasbench install-tools all
plasbench install-tools --env myenv mob_suite
```

`core` installs NCBI download, QC, and minimap2 tools; `assembly` installs
SPAdes/Unicycler; `metagenomics` installs the tested baseline runtime for
metaSPAdes and geNomad; `reconstruction` installs MOB-suite/Platon; `gplas` installs
gplas. `RUN_GPLAS2_MOB=1` then seeds
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
plasbench run --cohort public-v1 --threads 8
plasbench run 3 4 5 6 --platon off --assembler unicycler
plasbench report --results-dir results
plasbench --project-root /path/to/plasbench demo
```

## Run Options

### Inputs and outputs

```text
--samples PATH          Sample-sheet TSV; default: config/accessions.tsv.
--cohort NAME           Shorthand for --samples cohorts/NAME.tsv (e.g. --cohort
                       public-v1); mutually exclusive with --samples.
--write-script FILE     Write the exact resolved commands to FILE instead of
                       running them, so you can review or edit them before
                       running it yourself with bash.
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
--flye-mob-recon on|off  Optional long-read reconstruction (Flye + MOB-Recon). Default: off.
--plassembler on|off     Optional hybrid (long+short) Plassembler assembly. Default: off.
--hybracter-long on|off  Optional long-read-only Hybracter assembly. Default: off.
--hybracter-hybrid on|off Optional hybrid (long+short) Hybracter assembly. Default: off.
--trycycler-mob-recon on|off Optional Trycycler consensus long-read assembly plus MOB-Recon. Default: off.
--genomad on|off         Optional geNomad ML classification (assembly contigs). Default: off.
--plasme on|off          Optional PLASMe ML classification (assembly contigs). Default: off.
--plasgraph2 on|off      Optional plASgraph2 GNN classification (assembly graph). Default: off.
--rfplasmid on|off       Optional RFPlasmid random-forest classification (assembly contigs). Default: off.
--plasmidhunter on|off   Optional PlasmidHunter gene-content Naive Bayes classification (assembly contigs). Default: off.
--plasmer on|off         Optional Plasmer ensemble classification (assembly contigs; requires ~32GB RAM). Default: off.
--plascope on|off        Optional PlaScope Centrifuge classification (E. coli/Klebsiella only). Default: off.
--force-rerun-tools      Delete completed tool outputs and run them again.
```

The CLI options override `config/config.sh` for that invocation only. Edit the
config file when you want a persistent local default. `--gplas2-mob on`
requires gplas, a successful MOB-recon result, and an assembly graph. It fails
safely if MOB and graph contig identifiers do not agree.

The five long-read/hybrid options (`--flye-mob-recon`, `--plassembler`,
`--hybracter-long`, `--hybracter-hybrid`, `--trycycler-mob-recon`) are
independent of each other and of every short-read tool -- enable any
combination you want, and each is scored under its own analysis track (see
[Long-Read Reconstruction](#long-read-reconstruction)). Each is also subject
to the circularity guard: a sample is skipped unless its long reads are
declared independent of its truth assembly, or the tool's own
`*_ALLOW_CIRCULAR_TRUTH` override is set (see `docs/COHORTS.md`).

**Your own tool in the window.** On *Add your own tool*, the **Task** box takes one or more tasks (the first is the primary; a binner can also be scored as a classifier, and the Check box says per task whether it is native, derived from another output, or not possible). **Source** says where the tool comes from: already installed, conda or pip, a download from an https address (give its SHA-256 so a changed file is refused), a file or folder on this computer (copy records a checksum; link follows the file), or your own install script. PlasBench runs code you download or point to, so only use sources you trust; nothing is downloaded or run until you press *Save & install*. Small scripts and adapters (up to 5 MB) can be uploaded from your computer; a large tool is located or downloaded, never uploaded. A tool may list several **outputs** (or *Detect automatically* with candidate file patterns). The Tools page and the benchmark wizard show one chip per task and where each of your tools comes from.

### Run reliability, timing and run-state settings (new in 0.5.0)

All are optional; the defaults are safe. Set them in the environment or in `config/local.env`.

| Setting | Default | What it does |
|---|---|---|
| `ALLOW_ALL_TOOLS_FAILED` | `0` | Stage 4 exits with code **4** when every tool run failed (there is nothing to score). `1` continues with a warning. A run where only some tools failed always continues, and ends with "completed with warnings". |
| `TOOL_TIMEOUT_SECONDS` | blank (no limit) | Stops a tool that runs longer than this per isolate. The default is no limit because a limit changes which runs complete, and so the scores. A start-of-run notice says when it is unset. |
| `PLASBENCH_TOOL_TIMEOUT_PRESET` | unset | `generous` sets `TOOL_TIMEOUT_SECONDS=172800` (two days). An explicit `TOOL_TIMEOUT_SECONDS` wins; an unknown preset name is an error. |
| `PLASBENCH_STALL_SECONDS` | `600` | The window shows a running job as `stalled` after this many seconds without output (`0` turns it off). |
| `PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS` | `21600` (6 h) | Time limit for every helper subprocess in `python/` (`0` or `off` removes it). |
| `MIN_FREE_DISK_GB` | `20` | A warning (never a stop) before stage 1 when the drive has less free space (`0` turns it off). |
| `PLASBENCH_SKIP_DISK_CHECK` | `0` | `1` skips the disk figures of the resource check made before stages 0, 2 and 3 and the rolling guard before each isolate (the check otherwise stops with exit 6 only when the first isolates cannot fit at once; a whole cohort that will not fit is a warning). |
| `PLASBENCH_DISK_RESERVE_GB` | `5` | The rolling guard stops stage 1 or 3 cleanly (exit 6) before an isolate when the free space where it writes is below that isolate's estimate plus this many GB. |
| `PLASBENCH_VDISK_MIN_GB` | `2` | WSL: when the study, data and temporary folders are on a mounted Windows drive, the Windows drive holding Ubuntu's virtual disk stops the run only below this many GB free (under 10 GB warns). |
| `PLASBENCH_SKIP_RESOURCE_CHECK` | `0` | `1` skips the whole resource check (disk, memory, CPUs, writable folders). |
| `CAP_THREADS_TO_CPUS` | `1` | `THREADS` above the CPUs this process can use (affinity, container quota, WSL `processors=`) is lowered to them and the decision is printed; `0` keeps your number. |
| `ASSEMBLER_AUTO_RETRY` | `1` | A SPAdes failure from lack of memory (or a stale output folder) is retried once, with fewer threads and a budget that fits the free memory; `0` never retries. |
| `ANNOTATION_CACHE_DIR` | `<data>/.annotation_cache` | Finished reference annotations, keyed by the reference's SHA-256 and the annotation tools' versions, reused by later studies of the same isolate (empty turns it off). |
| `PLASBENCH_LOCK_HEARTBEAT_SECONDS`, `PLASBENCH_LOCK_STALE_SECONDS` | `5`, `60` | A run holds `RESULTS_DIR/.run.lock` and touches `.run.lock.heartbeat`. A second run is refused while the holder is alive; a lock whose heartbeat is older than the stale limit is taken over even if its process id is alive (covers a killed run and a reused id). |
| `ALLOW_INCONSISTENT_RUNS` | `0` | Aggregation stops when the run tables disagree (missing columns, non-finite values, a status that contradicts a score). `1` continues and still prints the count. |
| `ALLOW_INPUT_MISMATCH` (or `--allow-input-mismatch`) | `0` | The report builder refuses a leaderboard that was not ranked from the scores it is given. `1` builds anyway. |
| `SHARED_MIN_FRACTION`, `SHARED_MIN_SAMPLES` | `0.5`, `5` | A shared-sample set smaller than this fraction of the largest tool's samples, or than this count, is flagged on the leaderboard (`ranking_warning`). The ranking itself is unchanged. |
| `PLASBENCH_REQUIRE_CHECKSUMS` | `0` | `1` refuses a database download that has no pinned SHA-256 (environment variable such as `MOBSUITE_DB_SHA256`, or a row in `config/download_checksums.tsv`). Without it, a download with no pin prints a notice with the observed checksum and records it. |
| `RUN_TRUTH_EXCLUSION_SENSITIVITY` | `1` | `0` skips the stage-6 table that reports the headline with and without the replicon-database exclusion. |
| `REQUIRE_NO_SKIPS` (test runner) | `0` | `1` makes `test/run_tests.sh` fail when any check was skipped. The runner always prints how many were. |

New files in a results folder: `.run.lock` and `.run.lock.heartbeat` (while a run is active), `.completed_with_warnings`, `stage_timing.tsv` (seconds per stage, including failed stages), `tool_run_resources.tsv` (threads, seconds per attempt and peak memory per tool run), `download_provenance.jsonl` (observed checksums of downloaded databases), `benchmark.input_fingerprint.json` (which scores and tools the leaderboard was ranked from), `benchmark.truth_exclusion_sensitivity.tsv` and `benchmark.truth_exclusion_sensitivity_reconstruction.tsv`, and a `recovered_shards` folder in the log directory when a killed run left work behind.

Exit codes of a stage: `0` success, `3` an adapter found no output from its tool, `4` every tool run failed. The window shows these as `failed`, `completed_with_warnings`, `stalled` and `retrying`.

### Add isolates from a folder

See also `plasbench intake scan` / `intake stage` ([Input guide](INPUT_GUIDE.md)): the sheet-first route to the same placement, which stays available.

The AI help pane can do this for you through the same intake: press **Set up my isolates from a folder**, choose the folder, review the card (each isolate's reads, its reference and how sure the match is, the organism, the truth status, the warnings, and the sample sheet before and after), press **Stage**, and follow the quick test to the `plasbench run` card. It is the same plan as `plasbench intake stage --dry-run`; nothing goes to the assistant unless you press Share ([AI help](AI_HELP.md#your-isolates-through-the-intake)).

If your reads and reference genomes are in one folder (with sub-folders, and other files mixed in), you do not have to name each file. In the window, **Your own isolates > Scan a folder**; on the command line:

```
plasbench scan-isolates /path/to/folder                 # look; changes nothing
plasbench scan-isolates /path/to/folder --json          # the same, for scripts
plasbench scan-isolates /path/to/folder --write-sheet config/local.tsv    # also place the complete isolates
```

The result is a table: for each isolate, the reads (1 and 2), the reference, a confidence (high, medium, low) and what needs attention. The exit code is 0 when every isolate is complete and 3 when some need attention. **Scanning never modifies the folder.** `--write-sheet` calls the same function as `plasbench init-local` for each isolate (so `--link copy|symlink|hardlink` behaves the same); isolates with an error are never placed, and isolates that only need review (for example lanes to be joined) are placed only with `--yes` or when you confirm in the window.

What is recognised:

- **Paired reads:** `_R1/_R2`, `_1/_2`, `.1/.2`, `-1/-2`, `_R1_001/_R2_001`, SRA style `SRR..._1.fastq.gz`; `.fastq` or `.fq`, any letter case. Illumina lanes (`S1_L001`, `S1_L002`) are one isolate, listed and flagged; they are joined by gzip concatenation (nothing is decompressed) only after you confirm. A missing mate is an error. Reads must be gzipped.
- **Reference:** a plain FASTA of the complete genome. Chosen by how close it is to the isolate (same folder, the isolate's folder, the sample name in the file name) and by evidence in the file (an NCBI accession such as `NZ_`/`NC_`/`CP` in the header, the words complete genome, plasmid or chromosome, a few sequences, genome-sized length, a folder or file name such as reference, truth, complete, closed, hybrid). Each choice shows its reasons ("Why these files") and the runners-up as alternatives you can switch to.
- **Never a reference:** `contigs.fasta`, `scaffolds.fasta`, assembly graphs, anything in a SPAdes, Unicycler, Flye, Shovill, SKESA, MEGAHIT or similar folder, FASTA with `NODE_` or `depth=` headers.
- **Also used:** `sequence_report.jsonl` and a `truth.tsv` that sit with the isolate.
- **Ignored and counted:** BAM/SAM, documents, spreadsheets, logs, hidden folders, `.git`, `__pycache__`, `node_modules`, `results`, `logs`, symbolic-link folders (loops are never followed), online-only cloud files (never opened), unreadable folders (a warning), and unpaired or long-read FASTQ (not used by `init-local`).
- **Limits:** `--max-depth` (default 6 levels) and `--max-files` (default 200000).

It never guesses silently: two equally good references, two read pairs with one name, a missing reference, a reference that looks like a draft or is under 20 kb, two samples sharing a reference, and ids that had to be changed (only letters, digits, `.`, `_`, `-` are allowed; ids that differ only in capital letters are made unique) are all shown as issues. The matching uses folder and file names and the first part of each file, so it can be wrong: a reference in the right folder but belonging to another strain looks right. Check every isolate marked "check", and run the quick test (`plasbench intake check`) before a long run.

### Downloads: sizes, progress and the SRA Toolkit

Stage 1 downloads each isolate's reference assembly and its paired reads.

- **Before it starts**, PlasBench prints what it is about to fetch. For a sheet with no lock file it asks ENA for each run's exact compressed size, so the total is real and the **largest read set** is named; a set above `WARN_RUN_DOWNLOAD_GB` (default 5) is flagged as very large.
- **While it runs**, the run log gets one progress line a minute per active download (`DOWNLOAD_PROGRESS_SECONDS`, 0 turns it off), for example `SRR123: mate 1 74.7%, mate 2 66.2% (7.1 of 9.5 GB)`. The reads come from the SRA Toolkit first and from ENA when that fails (`READ_SOURCE`). After `PREFETCH_FAIL_LIMIT` isolates in a row where the toolkit failed and ENA worked, the rest of the run goes to ENA first, and the log shows the toolkit's own last line as the reason.
- **How downloads work.** Reads come from ENA first (checksum-verified, in 32 MiB resumable chunks; a dropped connection costs one chunk, not the file, and a later `plasbench run` continues from what is on disk) and from the SRA Toolkit only when ENA has no paired FASTQ for the run or fails (`READ_SOURCE`). The run log stays quiet: one line when a download starts (`SRR123: starting, 9.5 GB to download`), then at most one line per 10% and per 5 minutes (`SRR123: 34% of 9.5 GB, 3.4 MB/s, about 31 min left`), and a line when something changes (a retried chunk, a stall, a lower connection budget, a restart, the checksum step); `DOWNLOAD_PROGRESS_SECONDS` (default 30, 0 = no lines) is how often it looks. The live detail (bytes received, rate now and average, state) is in `results/download_progress.json`, which `plasbench status` and the window show. Every attempt is kept in `logs/<sample>.ena.log`. Stage 1 ends with a one-line summary.
- **Read-depth cap (`READ_DEPTH_CAP_X`, default 150; `plasbench run --read-depth-cap off|N`).** A run of an 8.8 Mb genome with a 9.5 GB read set is several hundred x deep: hours of download, trimming and assembly (and gigabytes of memory) for no benefit beyond about 100 to 150x. For a short paired Illumina run deeper than the cap, stage 1 downloads only the first read pairs of both mates that give that depth over the reference size (a prefix of each file, cut at a complete record), and prints `SRR36114699: 9.5 GB available, 150x cap needs about 1.1 GB, fetching the first 2.2 M pairs (the full set stays on ENA)`. The reads of an ENA FASTQ are in sequencer output order, so a prefix is a good sample of a bacterial isolate, **but it is not a random sample**, and it has no whole-file MD5 (record structure, equal pair counts and read-name pairing are checked instead). This is recorded in `<run>.ena_provenance.json`, the run manifest and the report's Run metadata; scoring does not use read depth. Long-read and unpaired runs, runs within the cap, and isolates without a reference size are always fetched whole. **`READ_DEPTH_CAP_X=off` (or `--read-depth-cap off`, also `0`, `none`, `false`) downloads whole files, MD5-verified.** The choice is recorded for the study. Across runs: reads that are a capped prefix are fetched again when the cap is now off or higher (one line says so); whole files already on disk are never deleted or shrunk when a cap is set (they are used as they are, and the manifest says so); an isolate set with a mix of capped and whole reads is flagged in Run metadata.
- **No isolate is skipped for its size.** `MAX_RUN_DOWNLOAD_GB` is an opt-in limit you can set yourself (blank by default); only then is an isolate whose download is above it skipped, recorded as failed with the reason and retried when you raise the limit. A very deep run is instead cut by `READ_DEPTH_CAP_X` (see below).
- **A file that is not a cohort.** `plasbench run --cohort NAME` refuses a file that is certainly not a cohort (the accession ledger, or a table with no `sample_id` column), once and before a study folder is made. Whether a sheet has the curated columns is stage 0's check (REQUIRE_CURATED_METADATA, which `config/local.env` can switch off): it names the first three bad rows and counts the rest.

| Setting | Default | What it does |
|---|---|---|
| `READ_SOURCE` | `auto` | `auto`: ENA first, the SRA Toolkit only when ENA has no paired FASTQ or fails. `sra`: toolkit only. `ena`: ENA only, MD5-verified. |
| `MAX_RUN_DOWNLOAD_GB` | blank | Opt-in: skip an isolate whose download exceeds this many GB. Blank = never skip. |
| `READ_DEPTH_CAP_X` | `150` | Download only the first read pairs of a short paired run deeper than this many x over the reference (0 or `off` = whole files). |
| `WARN_RUN_DOWNLOAD_GB` | `5` | Warn above this size (0 = never). |
| `PREFETCH_FAIL_LIMIT` | `2` | Go to ENA first after this many toolkit failures in a row (0 = always try the toolkit first). |
| `DOWNLOAD_PROGRESS_SECONDS` | `60` | How often a progress line is logged (0 = none). |
| `ENA_DOWNLOAD_CONNECTIONS` | `4` | Parallel connections per ENA file. |
| `DOWNLOAD_CONFIRM` | `1` | Show the estimate and ask before downloading (never asked without a terminal). |
| `ENA_SIZE_LOOKUP` | `1` | `0` skips the ENA size lookup for the estimate. |
| `ENA_PORTAL_URL` | ENA's file-report address | Point the lookup at a mirror. |

**Run status in the window.** Every ongoing run on the Runs page, and the panel that appears under the console when a run has printed nothing for a while, has a Run status panel: a chip (Running / Finished / Stopped: cut off / Not running), what the run is doing now (stage, isolate, step and how long that command has run), CPU and memory of the run's processes, this computer's free memory, swap and disk, the progress counts, the newest log with its age and last line, and a "What this means" list of plain-words hints with the evidence behind each (shown as a warning only when they mention memory or disk). It refreshes every 5 seconds while it is on screen. Buttons: Refresh, Copy diagnosis (a text to paste into a message), Open the console log and Open run_events.jsonl. The "Downloads and reliability" card of New benchmark has a checkbox, on by default, to keep a console log of the run in the study (`logs/run_*.log`; `RUN_CONSOLE_LOG=0` when unchecked) and a field for how many are kept (`LOG_RETENTION_RUNS`, default 20).

### Signing in to GitHub from the window

On **Version control** the GitHub card has **Sign in to GitHub**. It opens a small pop-up window of the PlasBench window (not your normal browser tab) at github.com and shows a one-time code in large type: type or paste it there and approve. When GitHub confirms, the pop-up closes, the window says "Signed in as <user>", and `git push` and `git pull` use the sign-in (PlasBench runs `gh auth setup-git`). If the browser blocks the pop-up, the window shows the address with an Open button; if you close it by mistake, **I closed it by mistake: open again** opens it again. The sign-in uses GitHub's device flow through the GitHub CLI (`gh`), so there is no app to register, and the page never sees a token. If `gh` is not installed the window says so, shows the install command for your system (`winget install --id GitHub.cli`, `brew install gh`, `conda install -c conda-forge gh` or `sudo apt install gh`) and offers **Use a token**: a personal access token (scopes `repo`, and `workflow` if you push workflow files) is sent once, over standard input, to `gh auth login --with-token`; it is not stored or logged. **Sign out** and **Switch account** are on the same card.

### Publishing and pull requests from the window

The same card covers the everyday GitHub work: **Create repository on GitHub** (owner or organisation, public or private, description; it adds `origin` and pushes the first branch), **Clone from GitHub** (list or search), **Branches** (switch, push with upstream, delete a merged local branch, delete a branch on GitHub), **New pull request** (title, description, base, head, draft, reviewers, labels; it offers to push the branch first), **Pull requests** (open, closed, merged; view state, checks, reviews, mergeability, changed files and comments; check out, mark ready, close, reopen, comment, merge by merge commit, squash or rebase, optionally deleting the branch or waiting for checks), **Checks** (workflow runs of the branch, with failing names and addresses, and re-run of the failed ones), **Issues** (list, create, comment, close) and **Releases** (list, create a tag and push it, create a release from a tag). Reading shows a dialog; changing something runs as a job in the console with its command line as the first line (tokens removed). Nothing is force-pushed. Deleting a branch, closing a pull request and merging ask first and say what will happen; merging with failing checks, conflicts or a requested change names the risk and asks you to confirm it. Failures are explained in plain sentences (not signed in opens the sign-in dialog; no permission; branch protection; conflicts; no remote).

### Offline

The top bar shows **Online**, **Limited**, **DNS problem** or **Offline** (and "Offline (forced)" when `PLASBENCH_OFFLINE=1`). Hover for each service's state and the advice, click to check again; it re-checks every 30 s while the window is visible. A control that needs the internet (sign in, push, pull, clone, check for updates, installs, discovery, downloading runs) looks disabled with the reason when its service is unreachable, and clicking it checks again at that moment before it says no. The server refuses such a job with a clear message instead of starting it. A run whose reads and references are already on disk (or `--local-inputs`, or the metagenomics track) still starts offline. Scoring, reports, studies, the folder tree, settings and documents never need the internet.

### Updating PlasBench from the window

**Set up this computer, Updates** is the window's version of `plasbench upgrade`. It runs that very command (one implementation) as a job, so what you see there is what a terminal would print.

- **Check for updates** asks GitHub's public release list whether a newer release exists and shows the installed version, the latest release, its date, the first lines of its release notes (plain text) and a link to the full notes. The answer is
  remembered, with the time it was checked. A newer release is never mistaken for an older one: if your installation is ahead of the latest published release the card says so and offers nothing. While the window is open it also looks by itself when it
  starts and then at most once a day, only to put a small dot on the top bar's **More** button when a newer release exists. Set `UPDATE_CHECK=off` in Settings to stop that; **Check for updates** still works. `PLASBENCH_OFFLINE=1` stops every check, and with
  no internet the card says why. Only GitHub's public release list is asked; nothing about you or this computer is sent.
- **Download and install** opens a dialog that lists exactly what will happen: the version change, the file and its size, where it comes from (github.com, https only), that its checksum is verified against the release's `.sha256` file **before anything is replaced**,
  the folder it installs into, that your studies, settings, databases and tools are kept, and that the window needs a restart afterwards. The card then shows the phases (check, download, verify, replace the program files, update the environment, finished) and the log.
- **A run is going?** An update replaces the program files, so while any job or any benchmark started in a terminal is running the update does not start. The dialog lists what is running; **Wait** is the default, and **Update anyway** (shown in red) starts it knowing that
  a stage that starts or a report that is written during the update can fail or mix versions.
- **Install from a file I already downloaded** takes a release file `plasbench-<version>.tar.gz` (choose it with **Browse** or paste its path). It needs no internet; the `.sha256` beside the file is used when it is there (otherwise the log prints the file's SHA-256 for you to
  compare with the release page). It runs `plasbench upgrade --archive FILE` and has the same dialog, phases and restart. A file older than the installed version is a downgrade and asks you to confirm it.
- **Restart window.** When the update has finished the card says so and shows **Restart window** (the same machinery as the stale-window banner: runs keep going, the window opens again at its new address). Where PlasBench cannot restart itself the dialog gives the manual steps
  (Quit, then start PlasBench again).
- **When an update fails** the card names the reason and the next step: no internet, a checksum that does not match, a full disk, a program folder it cannot write to, no conda, a file that is not a PlasBench release, or another update already running. A failure before the
  "replace the program files" phase changed nothing; a failure after it says so.
- **Rollback.** Before replacing anything an update saves the release it is about to replace, as a file of its own release files, in `.plasbench-rollback/` inside the PlasBench folder (only the latest one is kept). **Roll back** (or `plasbench upgrade --rollback`) installs it again, announced as a
  downgrade; your studies, settings, databases and tools are untouched either way. A rollback does not undo changes a newer release made to your data folders. Without a saved copy you can still install an older release file with **Install from a file**.

From a terminal: `plasbench upgrade --check-only` (only look), `plasbench upgrade` (latest), `plasbench upgrade --version X.Y.Z`, `plasbench upgrade --archive FILE`, `plasbench upgrade --rollback`; add `--yes` to skip questions. Only one update can run in a folder at a time.
The README's section "I already downloaded the release file" covers the first installation from a downloaded file.

### Choosing where tools run: Conda or Docker

PlasBench's tools (the assemblers, MOB-suite, Platon and the rest) can run from the `plasbench` conda environment on this computer (**Conda**, the default) or inside a container
of the PlasBench image (**Docker**). Choose on **Set up this computer**, in the **Environment** card at the top, or from a terminal with `plasbench runtime use conda|docker`.
The setting is `PLASBENCH_RUNTIME` in `config/local.env`; one run can differ with `plasbench run --runtime docker` (the run wizard has the same choice). The window itself always
runs on this computer: the window listens on 127.0.0.1 only, so a container cannot host it. In Docker mode every command that needs the tools (`run`, `report`, `check`,
`install-tools`, `tools install`) is started by the host-side `plasbench` as `docker run --rm`, from the detached job runner, so closing the window does not stop a run and Cancel
stops the container (it is named `plasbench-<job id>`).

**What is shared.** Your study folder, the data folder, the logs, the temporary folder, the database folder (`~/.plasbench/databases`), the sample sheet and `config/local.env`
are mounted into the container at the same absolute paths (WSL `/mnt/d/x` stays `/mnt/d/x`), so every path in `run_events.jsonl`, the manifest and the report is valid on this
computer too. Files are written as you (`--user`), not as root. Nothing else on the computer is visible to the container. On native Windows a container has no `D:\`, so `D:\x`
is mounted at `/mnt/d/x` and the container's own messages use that spelling; a network share (`\\server\share`) is refused with the reason (map it to a drive letter).

**When to prefer which.** Conda: fastest file access and no image to download. Docker: every tool at its pinned version without installing conda, and the same environment on every
computer; it costs an image download (not measured), Docker's own disk space, and slower file access when the folders are on a Windows drive (`/mnt/c`, `/mnt/d`): keep the
workspace on WSL's own disk (under `/home`) for speed. Apple Silicon runs the amd64 image emulated (slow).

**The image.** Default `ghcr.io/ubeffiong/plasbench:v<this version>` (never `latest`); `PLASBENCH_DOCKER_IMAGE` names another, `PLASBENCH_DOCKER_PULL` is `missing` (default),
`always` or `never`. The image's PlasBench version must equal this one, otherwise the run is refused and the matching image is named. If the image is not on the computer and cannot be
pulled (not published for this version, no access, offline, wrong architecture) PlasBench offers to **build it here** from the Dockerfile (`plasbench runtime build`, the
**Build the image** button): it needs the internet, several GB of disk and a long time (not measured; from half an hour to hours), asks first (`--yes` agrees), shows the build log
with a "still working" line, and on failure says which step failed and why (disk full, name lookup, registry refusal, platform mismatch). The build is recorded as `built-locally`.

**Tools and databases that are not in the image.** The image is never changed. `plasbench check --yes`, `plasbench install-tools ...` and `tools install` run inside a container
with a persistent folder mounted (`~/.plasbench/docker/<version>/extras`, or `PLASBENCH_DOCKER_EXTRA`): extra conda environments and tool wrappers land there and are put on PATH
in every later container; databases land in the shared database folder. **Make everything ready** in the Environment card runs `plasbench check --yes` this way. A tool that needs a
licence or a manual step stays exit 20, exactly as with conda. The extras (tool names and install provenance) are recorded in `run_manifest.json` under `runtime`, with the image, its
source (`pulled` or `built-locally`), the Docker version and the mounts, and the report's Run metadata says where the tools ran. Installs go to one overlay environment, `<extras>/envs/extras`, created fresh (the image's environments are read-only for the host user and are never written to; a read-only
prefix is refused at once with the path and the fix). PATH in a container is `<extras>/bin`, the image's tools, then `<extras>/envs/extras/bin`. MOB-suite's database is used from the
database folder with `-d`. A real install of a small conda package as a non-root user, and its use from a second container, is exercised in CI (`test/test_docker_extras_e2e.py`); real bioconda installs
of each large tool inside the container have not been validated: if one fails, the log says why, and the supported fallbacks are a derived
image (`FROM` the PlasBench image, install the tool, set `PLASBENCH_DOCKER_IMAGE`) or Conda for that tool.

**Switching back.** `plasbench runtime use conda`, or **Use Conda**. Conda stays installed; runs already going keep the runtime they started with. The study record (`study.json`) says which
runtime each run used.

**Troubleshooting.** `plasbench runtime check` (the **Test Docker setup** button) tests Docker step by step, PASS or FAIL each: Docker answers, the image is here, `plasbench --version` inside
it equals this version, a container writes a file in a mounted folder and this computer reads it, a path survives the mapping. Docker states the card shows: not installed (Tools page, **Install Docker**),
daemon stopped (start Docker Desktop or the service), permission needed (add yourself to the `docker` group), WSL integration off (Docker Desktop, Settings, Resources, WSL integration).
On Windows with WSL2: install Docker Desktop with the WSL backend and switch your Ubuntu distribution on, open PlasBench from Ubuntu, run `plasbench runtime check`, then **Use Docker**.

**Docker health.** Before it pulls, builds or starts a container, PlasBench checks that the engine is fit: it answers, it can write (a test volume is created and removed; no network, nothing pulled), and its disk has room (a warning below 10 GB, a stop below 2 GB for a pull or build; a build is *estimated* from the Dockerfile, and Docker Desktop's own disk cannot be measured from outside, so the card points to Settings > Resources). If the engine is unhealthy PlasBench stops **before** any pull or build, so a build that would run for hours and then fail is never started, and shows what it found (the error's own words), safe steps and commands to copy. The Environment card's **Run health check** button (and `plasbench runtime doctor`, exit 0 healthy, 3 problems, `--json` available) runs the checks on demand, about 15 seconds, and shows the environment (Docker Desktop on Windows/WSL 2 or macOS, Docker Engine on Linux, rootless), versions, root directory, free space, storage driver, the proxies Docker uses and a numbered plan; the result is remembered for 30 seconds. The page never runs it by itself. A pull that fails because a layer is corrupted or the network broke is retried (`PLASBENCH_DOCKER_PULL_RETRIES`, default 2); PlasBench builds the image locally **only** when the image really is unavailable (not published, private, wrong architecture) and you agree; after an engine, disk, corruption, network or unknown error it stops with the diagnosis. Commands that delete or move Docker data (`docker system prune`, `docker image rm`, moving `/var/lib/docker`, Clean / Purge data, `wsl --unregister docker-desktop`) are shown last, with what they destroy, and are never run for you. Error text, meaning and safe steps per environment: INSTALL.md, "Docker troubleshooting".

### Where your data and studies live

Two different things are stored on disk, and each can be placed where you want.

**Downloaded reads and assemblies (the "data").** By default every study uses ONE shared folder: `DATA_DIR` in `config/config.sh` (when PlasBench was installed with
`install.sh` this is `~/.local/share/plasbench/data`, which under WSL is a Linux folder that Windows shows as `\\wsl.localhost\<distro>\home\<you>\.local\share\plasbench\data`).
It is reused by every study, so nothing is downloaded twice, and it is kept when a study is deleted. For one run you can choose differently:

| Choice | Command line | Window (New benchmark, step Options) | What it means |
|---|---|---|---|
| Shared folder | nothing (default) | Shared folder | Reused by every study; kept if a study is deleted. |
| Inside the study | `--keep-data-in-study` | Inside this study folder | `<study>/data`; git-ignored; deleted together with the study. |
| Another folder | `--data-dir PATH` | Another folder | Any folder on this computer or a connected drive. |

The study remembers the choice (`data_location` and `data_dir` in its `study.json`), so Resume and later runs of the same study find the reads without repeating the flag; a flag
given again overrides it. **Manage study → Delete downloaded data only** removes `<study>/data` and keeps the results.

**The study folder itself (results, logs, the record).** It is `<workspace>/<name>` unless you say otherwise: `--study-location PARENT_DIR` creates `PARENT_DIR/<name>` (the folder
must already exist), and the window's Study folder card and New study dialog have a Location choice. PlasBench remembers where an outside study is in a hidden list in the workspace,
so `--study NAME`, the Workspace page and the folder tree find it. **Add an existing study folder** registers a folder that already holds a `study.json`. A study on a drive that is
disconnected is listed as "not available" with Remove from list; nothing is created in its place. Rename, copy and archive are offered only for studies inside the workspace.

**Choosing folders: the Explorer window and the built-in browser.** Every Browse button (and "Choose a folder", "Choose file") opens **the computer's own folder window**: on Windows
(also when PlasBench runs in WSL) the real Explorer-style dialog with This PC, every drive including USB sticks and network drives, Quick access, search and the real capacity bars;
on macOS the Finder dialog; on Linux zenity, kdialog or yad. The window is opened by PlasBench on this computer's desktop (it may appear behind the browser: the waiting dialog has
**Bring it to front** and **Cancel**), and the folder you choose is put in the field and checked (does it exist, can it be written, is it a slow or cloud-synced drive).
Where no folder window can open (no desktop session, SSH, a headless server, WSL without `powershell.exe` interop) PlasBench says why in one line and uses **the built-in browser**
instead; you can also choose it yourself ("Use the built-in browser") and switch back with "Use the Explorer window"; the choice is remembered.

*Quick pick without any dialog:* in Explorer click the address bar and copy the path, or hold Shift, right-click the folder and choose **Copy as path**, then paste it into the field.
Pasted text is cleaned for you: `"D:\data\x"` (with quotes), `D:\data\x`, `\wsl.localhost\Ubuntu\home\me`, `file:///D:/data/x` and `This PC\Data (D:)\x` all work. **Open in Explorer**
next to the field shows the current path in the real Explorer (also for a `/mnt/<drive>` folder, a `\wsl.localhost` path and a drive that is plugged in but not mounted in Ubuntu).

*The built-in browser* has the places you use (Home, Desktop, Documents, Downloads, the Windows ones under WSL, the workspace, the data folder, recent folders), every Windows drive with
its real size and free space as Windows reports it (units: GB = 2^30 bytes, as Explorer), Back / Forward / Up / Refresh, a breadcrumb for every folder, a path box (`~`, Windows paths and
pasted Explorer paths), a filter, sort by name / size / modified, hidden files, New folder, and the keys Alt+Left / Alt+Right / Backspace / `/`.

**Windows drives from Ubuntu (WSL).** A USB drive or network drive plugged in after WSL started is not mounted in Ubuntu. The built-in browser lists it anyway (letter, label,
type, size) marked "not mounted in Ubuntu yet" with the exact command and a Copy button: for drive E, `sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e` in the Terminal tab
(PlasBench never runs it for you). The folder window of Windows can show every drive, but a drive Ubuntu has not mounted still needs that command before PlasBench can read it; a
network share (`\server\share`) cannot be mounted automatically: map it to a drive letter in Windows and mount that letter. Click Refresh (or return to the window) after plugging a
drive in; a new drive is marked "new". Older versions showed the size of Ubuntu's own virtual disk for a leftover empty `/mnt/e` folder as if it were the drive; sizes now come from
Windows itself and an unmounted folder shows none.

**Frequently asked.** *Why does Browse not show my USB drive in the built-in browser?* Plugged in after WSL started: mount it as above. *Why does the folder window open behind the browser?*
Windows may refuse to raise it: click Bring it to front or find it in the taskbar. *Can the page use the real Explorer without a dialog?* A web page cannot receive a real path from
the browser, so PlasBench opens the dialog itself; Open in Explorer only shows a folder.

**The folder window does not open (Browse).** Run `plasbench picker-check` (or Settings, **Test the folder window**): it checks the chain step by step, prints `PASS` or `FAIL` for each
step with the exact error, opens a test window that closes itself after two seconds, and ends with what Browse will do. Add `--interactive` to leave the window open, choose a folder and see the
path PlasBench receives. Paste the report if it still fails. Whatever fails, Browse never does nothing: when the window does not say it is open within 8 seconds (or fails) a dialog gives the reason, a
**Why?** fold with the diagnostics, **Copy diagnostics**, **Keep waiting** and **Use the built-in browser**. The checklist per computer:

- *WSL (Ubuntu on Windows).* The folder window is Windows' own, started through `powershell.exe`. `plasbench picker-check` shows **WSL interop** (needs `[interop] enabled` not `false` in `/etc/wsl.conf`
  and `WSLInterop` enabled: `wsl --shutdown` from Windows restarts it), **powershell.exe is found** (PlasBench looks on PATH, in `/mnt/c/Windows/System32/WindowsPowerShell/v1.0`, in any
  `/mnt/<drive>/Windows` and asks `cmd.exe` for `%SystemRoot%`, so `appendWindowsPath=false` does not matter), and whether PowerShell is locked down (Constrained Language Mode, a company policy). If the
  Explorer-style window cannot be compiled, the older Windows folder window and then `Shell.Application` are tried before the built-in browser. The window may open behind the browser: it is made
  top-most and brought forward, and **Bring it to front** is in the waiting dialog; if Windows refuses, its taskbar button flashes. The first start can take several seconds.
- *Windows.* The same route without WSL. A locked-down PowerShell or a security product that blocks `Add-Type` makes the older windows or the built-in browser take over, and `picker-check` says which step failed.
- *macOS.* `osascript` must run and the desktop session must be the one the terminal belongs to; `picker-check` starts the dialog and closes it after the test time.
- *Linux desktop.* Install `zenity`, `kdialog` or `yad` and start `plasbench ui` from a terminal inside the desktop session (`DISPLAY` or `WAYLAND_DISPLAY` set).
- *Linux without a desktop, SSH, a server.* No window can open on your screen: the built-in browser is used, by design. Forward the port (`ssh -L 8770:127.0.0.1:8770 you@server`) and open the address locally.
- *Docker.* See the next section.

Only the WSL route had to be rewritten: Windows (`powershell`), macOS (`osascript`) and Linux desktops (`zenity`/`kdialog`/`yad`) each use their own system dialog, and the other computers fall back to the built-in browser
by design.

**PlasBench and Docker.** Inside a container there is no desktop, so no folder window can open, and the container sees only the folders that were mounted into it. A window running inside Docker therefore
sends Browse straight to the built-in browser, which starts at the mounted folders (read from `/proc/self/mountinfo`: bind mounts with the host folder when Docker reveals it, volumes by name) and says that
folders outside the mounts are not visible. To use another folder, **Add another folder** takes a path on your computer (`D:\data`, `/home/me/data`) and writes the exact `docker run ... -v <folder>:/mnt/<name>` command
(and a `docker compose` snippet) that restarts the container with it mounted; paths are converted for the shell (`/mnt/d/data` for WSL and Linux, `D:\data` for PowerShell), spaces and unicode are quoted, a network share
(`\\server\share`) is refused with the reason. The command is shown and copied, never run. The image's default command is the command line, and the window listens on 127.0.0.1 only, so PlasBench does not
claim to host the window in a container: run the window on your computer and the pipeline in Docker.
From a window on the computer itself, **Run in Docker instead** (the folder chooser and Settings) appears only when `docker info` answers (checked in the background, never while a page loads) and
`scripts/docker_run.sh` exists. It writes the command that runs `plasbench run` in the image with your data folder and studies folder mounted (`PLASBENCH_DATA_DIR`, `PLASBENCH_WORKSPACE`), tells you the
steps, and again does not run it: the window does not stop itself or start containers. The tools run inside the image and results are written to the mounted folders.

**Speed and sync folders.** A Windows drive seen from Ubuntu is slower than Ubuntu's own disk for many small files and for git; a cloud-sync folder (OneDrive, Dropbox) can lock
or re-upload large files mid-run; an external or network drive stops the run if it disconnects (running again continues from the finished steps). The folder check shows these
warnings, and the free space, under the path before you choose it.

### Watching a run: status, diagnose and the logs

A long run is quiet by nature, so PlasBench writes down what it is doing as it goes.

- **`plasbench status`** says whether the run is running, finished or was cut off; the stage, isolate and step it is in and for how long; progress from the status tables; the CPU and memory of the run's processes; the machine's free memory, swap and disk; the newest log of that isolate; and hints that follow from those figures. `plasbench diagnose` adds the busiest processes. Both take `--study NAME` or `--results-dir DIR` (default: the most recently updated study), `--json` for scripts, and `--watch SECONDS` to repeat.
- **Heartbeats.** Every long command prints `still working: <isolate> / <step> (N s elapsed; cpu=... rss=...; mem_avail=... swap_used=... disk_free=...; its log last changed N s ago: "<last line>")` after `HEARTBEAT_DELAY_SECONDS` (180) and then every `HEARTBEAT_INTERVAL_SECONDS` (60). That covers trimming, assembly and the stage-4 tools; downloads log their own progress line (see above). A warning is added when less than 300 MB of memory is available, or when the command has used almost no CPU and written nothing to its log for ten minutes.
- **Files.** In the study: `logs/run_<date>-<time>.log` (everything the run printed; `logs/run.latest.log` points at the newest; the newest `LOG_RETENTION_RUNS` = 20 are kept; `RUN_CONSOLE_LOG=0` turns it off), `logs/<isolate>.<step>.log` (each tool's own output) and `results/run_events.jsonl` (one JSON line per stage start and end, isolate step, command start and end with exit code and seconds, heartbeat and warning; names and numbers only, never environment variables or commands). `results/stage_timing.tsv` has the seconds per stage.
- **A run that was cut off** (the terminal, WSL or the computer ended it) shows as *stopped* with the hint that re-running resumes: finished isolates and tool results are reused.

### Rebuilding a report's figures from an old run

The report's newer figures (synteny ribbons, plasmid maps, the presence/absence matrix, plasmid-level facets, fingerprints, the read-QC panel) draw from small per-sample files, not from the top-level tables: `<sample>/visualization/alignment_blocks.json`, the truth tables (`truth.tsv`, `truth_features.tsv`, `truth_amr.tsv`), `short_read_qc.tsv` and each tool's predictions and alignments. A results folder that kept only `scores.tsv` and the `benchmark.*` tables (a published or trimmed copy, or a run from before 0.3) shows those sections as "Not available in this run". `docs/REPORT_INPUTS.md` lists every file the report reads, which script writes it and what it can be rebuilt from.

1. **Look first.** `plasbench check-results RESULTS_DIR` (add `--samples SHEET` and `--data-dir DIR` when you have them) prints the sections that can and cannot draw, the files behind each, and for every missing file whether it can be regenerated. It writes nothing. Exit code 0 means every section can draw; 3 means at least one cannot.
2. **Rebuild what can be rebuilt.** `plasbench regenerate-visuals RESULTS_DIR --data-dir DIR --samples SHEET` shows the same plan, asks, then rebuilds in place: truth tables from `sequence_report.jsonl` and `reference.fna`, alignments with minimap2 from kept predictions, `alignment_blocks.json` and the structural files from those, read QC from the read pairs, and copies of the small truth tables from the data folder. These are the scripts the pipeline stages call, with the run's recorded settings, so the files are byte-identical to what a fresh run on the same inputs writes. `--dry-run` only shows the plan, `--yes` skips the question, `--only alignments,qc` limits it, `--report` rebuilds the HTML report afterwards.
3. **It never rewrites what the run measured.** `scores.tsv` and the `benchmark.*` tables are not touched, an existing file is skipped ("present") unless you pass `--force`, and everything written is recorded in `regenerated_inputs.json` (what, when, versions, a hash of the inputs). The report then says in Run metadata that those files were regenerated after the run.
4. **What cannot be rebuilt** is said precisely: a prediction that was not kept needs the tool re-run (reads, the tool and its database) or the original results folder (`--predictions-dir`, checked against `scores.tsv` first); a reference FASTA that is gone needs a download from ENA or NCBI (internet access; the accession is in the sample sheet); reads that are gone need the same; a curated AMR truth table is written by a person (`plasbench promote-amr-truth`), never generated.
5. **So it does not happen again.** From this version, stage 5 keeps the small inputs in the results folder (`KEEP_REPORT_INPUTS=1`, a per-sample budget `KEEP_REPORT_INPUTS_MAX_KB=2048`): the truth tables and a record/length/hash summary of each tool's predictions, never reads, assemblies or reference FASTAs. The measured size cost is in `docs/COHORT1_REBUILD_STATUS.md`. A results folder copied to another machine then rebuilds its alignment blocks and figures with `plasbench regenerate-visuals RESULTS_DIR --yes`.

## The workflow at a glance

The window shows the whole run as one chain, in order, so you can see what each step does, what you can add to it and what it costs. Open it on **Tools** (what runs by default on this computer) or on **New benchmark**, step *Tools* (what runs this time), and choose **Workflow** at the top; **List** is the plain list. Both views change the same settings, so they always agree.

```text
0 Check and install -> 1 Download -> 2 Reference truth -> 3 QC, trim and assemble -> 4 Run the tools
  -> 5 Score -> 6 Aggregate and report -> 7 Long-read and hybrid tools -> 8 Operational reconstruction
  (and, separately, the Metagenomics track)
```

Each step is a card. Inside it every item says what it does in one line and shows a switch:

- **Always on** items are the core of the stage and cannot be switched off. **Optional** steps (extra analyses) and **alternative tools** have a switch.
- **On** is green with a tick; **Off** is plum with a cross and a dashed outline. The word is always written, so colour is never the only cue. **An item at its default shows its default state in that state's colour**: a tool that is off by default shows *Off* until you switch it on. An item you changed from its default also carries a **changed** tag, and a small *default* link puts it back (on New benchmark it is *use saved*). Green help marks, amber warnings and red errors keep their own meaning.
- **Badges** show what an item needs: a database, the internet (always, or only the first time), an earlier step, or an input such as long reads.
- Turning on something that needs an earlier step that is off offers to turn that on too; turning off a step others need warns you and offers to turn them off as well. Nothing is changed until you choose.
- **What can I add here?** under each card lists the optional items that are off, with their cost and a *Turn on* button. **Enabled extras** at the top lists what you have switched on beyond the default chain (and what you switched off).
- Your own tools (added with a manifest) appear under *Run the tools*, marked *your tool*.

**The estimate.** The bar at the top says, for example, *this selection adds about 14.4 min, 4.4 GB peak memory and 630 MB disk per isolate, estimated*, and recalculates on every change; choose *Per 10 isolates* to scale it. Time and disk add up over the items that are on; memory is the largest single tool (they run one after another unless you raise the parallel settings); a one-off database download is shown separately. Every figure says where it comes from:

- **measured**: taken from a real run in this repository (`results_real_cohort1`, 10 isolates). At present these are assembly (median 5.9 min), MOB-recon (0.9 min, 2.95 GB peak), Platon (1.0 min, 4.4 GB), plasmidSPAdes (median 6.6 min, mean 12.7 min, 3.8 GB) and the coverage baseline (under a second);
- **documented**: a stated requirement or size, not re-measured (the 630 MB per isolate and the 2.9 GB and 2.7 GB databases in the README, the 32 GB memory floor Plasmer documents);
- **not measured**: no figure exists. The field is blank, the item is listed under the total as *not measured*, and the total says *at least*; it is never counted as zero.

Treat the numbers as a guide for planning time and disk. They depend on read depth (a very deep isolate can take many times the median) and on your computer. Where the window says *not measured*, run one isolate and look at `tool_status.tsv`, which records `runtime_seconds` and `peak_rss_kb` for every tool. The chain and its figures live in `config/workflow_steps.tsv`, one row per item, and `plasbench/workflow_steps.py` reads it; a test fails if a tool in the registry, a stage script or a setting is missing from it, so adding a tool means adding its row.

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

## MultiQC and the built-in QC panel: which to use

PlasBench does **not** use MultiQC to make its QC: read quality is measured by fastp and `python/short_read_qc.py`, and the report's **Short-read QC** panel is PlasBench's own, modelled on MultiQC's layout. Real MultiQC is an optional companion.

- **Built-in panel.** PlasBench's thresholds (PASS, WARN, REJECT with the reason), the assembly selection outcome and the answers to a reviewer's questions, offline in the one report file. It shows only the metrics PlasBench computes.
- **MultiQC.** The community-standard view of the same fastp (and QUAST) files, with more plots (per-base quality, adapter content, duplication). It needs a separate install (`plasbench install-tools multiqc`), is a separate file (`results/multiqc/multiqc_report.html`, linked from the panel, never embedded) and knows nothing of PlasBench's thresholds.
- **Setting.** `MULTIQC_REPORT=auto|on|off` (default `auto`: run it only when `multiqc` is installed; `on` warns when it is missing; `off` never). `MULTIQC_TIMEOUT_SECONDS` (600) limits it. A MultiQC problem never fails a run: it is a warning in `run_events.jsonl` and a note in the panel.
- **If they differ.** Both read the same files, so a figure both show should agree closely; the panel measures the first read pairs of the raw files, fastp reports every read it processed, so small differences are expected. If they differ a lot, check they were made from the same run and sample, then read `results/short_read_qc.tsv` and the sample's `fastp.json`: the files are the record.

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
MOB, closure, or `ml_probability` evidence using `record_id`, `evidence_type`,
and `evidence_value`. They are shown in the selection card but are not
treated as independent structural proof. `ml_probability` is purely
informational -- a tool's own stated confidence, shown to a human choosing an
operational method -- and is unrelated to the PR-curve/PR-AUC mechanism
above (`adapters/SCORES.md`), which scores leaderboard rows directly and
never reads this file.

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

### Decision-support recommendation model (optional, off by default)

`benchmark.recommendations.tsv` above ranks tools using a fixed, hand-picked
multi-objective weighting of each stratum's *mean* F1/precision/recall/
plasmid recovery. Enabling `RUN_RECOMMENDATION_MODEL=1` replaces those two
mean-based terms (F1 and plasmid recall only -- every other term is
unchanged) with a small, hand-rolled (pure Python, no new dependency) ridge
regression predicting them directly from an isolate's own continuous
features instead of a coarse stratum bucket. Those features are the
isolate's read depth, plus its GC content, N50, contig count and assembly
size from the stage-2 `data/<sample>/assembly_stats.tsv` -- the same
per-isolate statistics the advisory cohort-QC flagger uses -- and its organism
and Gram group. Every one is knowable for an isolate that has no reference.
The truth's plasmid size and count and its AMR annotation are **not** used: they
exist only in a retrospective benchmark, and a model trained on them would learn
the answer. A model file fitted with an earlier release (which used them) is not
served; refit it with `python/fit_recommendation_model.py`. A sample missing any of them (an operational
isolate has no reference assembly, so no stats) has that feature imputed with
the training mean rather than being unusable:

```bash
plasbench run --samples config/accessions.tsv  # RUN_RECOMMENDATION_MODEL=1 in config/config.sh
```

This is a **descriptive recommendation, not a scoring change, and not
validated beyond the cohorts it was fit on** -- the identical caveat this
project already applies to `operational_method_recommendation` and
`truth_set_best_candidate` elsewhere in this guide. It is fit and leave-
one-study-out validated fresh every run (`benchmark.recommendation_model.json`)
and writes a human-readable `benchmark.recommendation_model.card.md` alongside
it. The card records exact input checksums, observed organisms/tracks/studies,
thresholds, validation results, scope, and limitations for release review.

At the default nested-validation threshold (60 score rows and 5 independent
source studies), lambda selection happens only within each outer training fold;
the held-out study is used only once for evaluation. Below that threshold,
PlasBench uses an explicitly labeled **approximate LOSO** fallback because a
nested split would be too data-starved. Its reported improvement may be
optimistic and must not be described as unbiased validation. Both the JSON and
model card carry this validation label. The model is only ever used when it
demonstrably beats the plain per-tool mean under its declared folds
(`RECOMMENDATION_MODEL_MIN_STUDIES`,
`RECOMMENDATION_MODEL_MIN_SAMPLES`, `RECOMMENDATION_MODEL_MIN_IMPROVEMENT` in
`config/config.sh`) -- never "ready" on a technicality that is actually
worse than the mean. When it isn't ready, every downstream script behaves
exactly as if this feature did not exist; when it is, `reason` fields in
`benchmark.recommendations.tsv` and `.stratified.tsv` gain a `(model-fitted)`
tag so the provenance of any given number is always visible -- no new
columns, same schema either way.

**Note on scope.** A separate cohort-growth planning exercise (see
`cohorts/README.md`'s dedup ledger and `python/validate_recommendations.py`'s
per-stratum leave-one-study-out validation) concluded the public cohorts'
current study diversity did not yet justify *building* this model, and
scoped that round of work to the model's rules-only prerequisites instead.
This code was nonetheless already written and merged by the time that
conclusion was reached. The two are not actually in conflict in practice:
`RUN_RECOMMENDATION_MODEL` defaults to `0`, and `model_ready` requires
clearing `RECOMMENDATION_MODEL_MIN_STUDIES` independent `source_study`
groups with a genuine leave-one-study-out improvement over the plain
per-tool mean -- the same bar that planning exercise's own analysis used, so
the model stays inactive on today's cohorts regardless of which piece of
work reached the repository first. Re-run the fit once the cohort's study
diversity actually clears that bar; until then, treat any output this
produces on the shipped cohorts (`public-v1`/`public-v2`) as not yet
meaningful, gate or no gate.

The model is also used for `plasbench reconstruct`'s live per-isolate
recommendation (a genuinely new isolate has its own exact read depth/
organism/Gram group *before* any tool has run on it, so predicting directly
from those features is more informative than a discrete stratum lookup):

```bash
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678 \
  --organism "Klebsiella pneumoniae" --gram-group Gram_negative \
  --read-depth-x 62
```

`--recommendation-model` defaults to `<results-dir>/benchmark.recommendation_model.json`
when `RUN_RECOMMENDATION_MODEL=1`; omit `--read-depth-x` and it is imputed
with the training-set mean. Only tools already eligible in
`benchmark.recommendations.tsv`'s `overall` scope are ever considered --
the model never live-recommends a tool nobody validated.

## When You Are Offline

PlasBench checks for the internet before anything that needs it, and says so in one plain sentence before it does any work (`plasbench net` shows the same check: which services answer, and advice).

**Works offline:** scoring, aggregation and the HTML report (`plasbench report`, `report-pdf`), the demo, runs on files already on disk (`plasbench run ... --local-inputs`, or any run whose reference and reads are already downloaded: stage 1 asks for the internet only for what it has to fetch), `import-contributed-cohort`, `plasbench tools list/validate/new` and adding a tool from a folder, viewing studies in the window, and every tool that is already installed.

**Needs the internet:** stage 1 downloads (NCBI Datasets, SRA, ENA), `install-tools`, `check --yes` when something is missing, database downloads (Zenodo, PLSDB, Figshare), `upgrade`, the update check, `validate-cohort --online`, `discover-*`, `resolve-contributed-cohort`, `curate-cohort`, `prepare-contribution`, adding a tool from a URL, and GitHub sign-in in the window.

The message names the service and the reason: no network at all; DNS not working (in WSL run `wsl --shutdown` in PowerShell, check the VPN, or set a DNS server); one service down while the rest work; a sign-in page, proxy or certificate error in the way. A download that starts online and then loses the connection pauses and resumes by itself.

Settings (environment variables, also in the window's Settings): `PLASBENCH_OFFLINE=1` refuses every online-only action at once, on purpose (for an offline session or a metered link); `PLASBENCH_ONLINE_TIMEOUT` is the seconds to wait for each service (default 5); `PLASBENCH_ASSUME_ONLINE=1` skips the check altogether (tests, or a network that only reaches a local mirror). The services and which commands use them are listed in `config/network_services.tsv`.

## AI help

The **AI help** drawer (the **AI help** button in the top bar, or Alt+Shift+H; it takes the place of the side panel, and **Panel** brings the side panel back) answers questions about PlasBench from PlasBench's own guides, settings, command line and failure signatures, cites its sources, and proposes commands with the place to run each: PlasBench's Terminal tab, Windows PowerShell (not inside Ubuntu), your Ubuntu (WSL) terminal. It uses free models only; the provider switch offers OpenRouter (sign up or sign in in a small pop-up), Hugging Face (when `AI_HF_CLIENT_ID` is set) and a model on your own computer (Ollama or LM Studio, nothing leaves the computer).

- Nothing is sent before you sign in, read the notice and ask. A question sends the question, a few guide excerpts and a short setup line; never paths, your user name, e-mail address or data. Command output is sent only when you press **Send result**, after you have seen the redacted text.
- A suggested command is a card with **Run in PlasBench** (only when the checks pass; it opens the usual confirmation with the exact command and never runs by itself), **Copy** and **Open Terminal tab**. Commands that install, upgrade or stop get one more confirmation.
- Settings: `AI_HELP_ENABLED`, `AI_PROVIDER`, `AI_MODEL`, `AI_DAILY_TOKEN_CAP`, `AI_BRIEF`, `AI_FREE_FALLBACK`, `AI_HF_CLIENT_ID`, `AI_LOCAL_BASE`. On the command line: `plasbench ask "question"`, `plasbench ai status`, `plasbench ai signout`.

Everything about it (what is sent, where the key is stored, free-model limits, the providers considered, the safety checks) is in [AI_HELP.md](AI_HELP.md).

## Console Messages

Console output is timestamped. It announces selected stages, each active stage,
sample/tool execution, warnings, output locations, and the final leaderboard.
Long-running runs do not yet estimate total completion time; use log timestamps
and `results/tool_status.tsv` to monitor progress.

### Console colours: what each colour means, and why so few

The console (Job output, Terminal, Session log) and a `.log` file opened in the window use one scheme. **Colour marks what needs you; the output itself stays plain.**

| Type | How it is shown | Decided by |
|---|---|---|
| Error | the whole line red, a cross marker, the status word bold; a Python traceback and its frames are red too | the program's own red, PlasBench's `ERROR:`, `Traceback`, `...Error:`, `FAILED`, a non-zero `[exit N]` |
| Warning | an amber triangle and the status word amber | the program's own yellow, `WARNING:`, `warning:`, skipped, cancelled |
| Success | a green tick and the status word green | the program's own green, `PASS`, `ok`, `[ok]`, complete(d), `[exit 0]` |
| Note | a blue dot and the word blue | PlasBench's `NOTE:` / `INFO:` and the runner's own lines |
| Heading | bold, accent colour | `=== ... ===`, `### ...`, `>>>>> STAGE N :` |
| Detail | grey italic | "What to do:", "Hint:", "Why:", a line in parentheses; timestamps are grey (not italic) |
| Output | the console's normal text, in the program's own colours if it uses any | everything else |

Explicit signals decide first (the producer's colour, a PlasBench level word, an exit code), then cautious patterns; a line that matches nothing stays plain, never red by guess.
Why not colour every line by type: a run prints thousands of output lines, and when most of the screen is coloured, colour stops pointing at anything; italic is kept for the
short explanatory lines because it is harder to read in a monospaced font. The markers mean colour is never the only signal (red and green also differ in shape and weight,
for colour-blind readers); every colour reads at 4.5:1 or more on the console (7:1 when the system asks for more contrast), and Windows high-contrast mode keeps the markers.

**Colours** in the console header switches between *Headers and status* (the default, above), *Full by type* (whole lines coloured: warnings amber, successes green, notes
blue) and *Off* (plain text), with a legend. The choice is kept in this browser. Programs' own colour codes are shown (16, 256 and 24-bit colours, bold, italic, underline);
other terminal codes (cursor moves, erasing, window titles) are removed, a progress bar that rewrites its line shows its last state, and nothing in a log is ever treated as
HTML. **Copy** and **Save** (the job's whole output) give plain text without codes or markers. In a terminal, PlasBench colours its own warnings and errors only when
the output is a terminal; `NO_COLOR=1` or `PLASBENCH_COLOR=0` turns that off, `PLASBENCH_COLOR=1` forces it.

## My run looks stuck

First look, in a second terminal: `plasbench status` (add `--study NAME` for another study) says the state (RUNNING, FINISHED, STOPPED), the stage, the isolate and the step it is in
("now: stage 2, isolate X, step reference annotation (running for 11 min, typical 11 min)"), the CPU and memory of the run's processes, and a hint when something is off.
`plasbench diagnose` adds the busiest processes. The window's Run panel shows the same fields.

What is normal, and how long it can take (the figures are estimates for a 6-CPU laptop, from config/step_typical.tsv; measured where the table says so):

- Stage 1 download: minutes per isolate (a 400 MB read set took about 5 minutes); the log shows percentages. It resumes if interrupted.
- Stage 2 reference annotation: about 11 minutes per isolate on a 4 Mbp genome, almost all of it ISEScan. The log lists which callers are still running and, past twice the usual time, says so.
- Stage 3 fastp: seconds to a couple of minutes. SPAdes: 10 to 30 minutes for a 4 Mbp isolate; the heartbeat names SPAdes's own phase (read error correction, then K=21 ... K=77, then repeat resolution).
- A step that runs 3 times its typical time (`STEP_SLOW_FACTOR`, 0 turns it off) gets one "still running" note and a `slow_step` event; nothing is stopped. If its log has not changed and the CPU is near 0% it may be stuck: `plasbench diagnose`.

The SPAdes memory message. `ERROR K-mer Counting ... The reads contain too many k-mers to fit into available memory. You need approx. 5.24277GB of free RAM` means SPAdes was given a
smaller memory budget (`-m`) than this read set needs. PlasBench now reads the number, and retries ONCE with -m = need + 15% when that fits in 85% of the memory free now (or the need rounded up when
that fits in 92%); otherwise it stops that isolate, says the exact need and what is free, and goes on with the other isolates. To raise it yourself: `plasbench run ... --memory-gb 7` (or MEMORY_GB), close other
programs, or give Ubuntu more memory (WSL: `memory=` in `C:\Users\<you>\.wslconfig`, then `wsl --shutdown`). The default budget is 85% of the memory available now minus 512 MB, rounded down to whole GB between 2 and 64 (6.9 GB free gives 5 GB); the setup output prints the rule.

Resources adapt by themselves (`AUTO_RESOURCES=1`, the default; `0` restores fixed behaviour). When a tool says what it needs, or is killed for memory, runs out of temporary space, hits the open-files limit or a thread limit, PlasBench chooses ONE safe response from an ordered ladder (raise the memory budget, halve threads, move the work folder to a roomier disk, raise `ulimit -n` up to the hard limit, extend a timeout only when the tool is still making progress, else skip that isolate with the exact need and what is free), logs one plain line ("spades needs about 5.2 GB for this isolate; raising memory from 4 to 6 GB (6.9 GB are free) and retrying"), writes a `resource_adjust` event that `plasbench status` and the window show, and remembers the need per isolate in `results/resource_profile.tsv` (keyed by a checksum of the reads) so a resume starts right. Scientific parameters are never changed; `--only-assembler` is tried only with `ASSEMBLER_ALLOW_ONLY_ASSEMBLER=1` and recorded as a different assembly mode. `run_manifest.json` and the report's run metadata list the final memory/threads/mode per isolate and every adjustment. The signatures are data (`config/resource_signatures.tsv`); see docs/RESOURCE_ADAPTATION.md.

One failed isolate does not stop the others: a failure of memory, reads or one tool is recorded for that isolate and the stage goes on ("complete WITH WARNINGS: 2 of 3 assembled"). Only causes that belong to the
computer (disk full, broken Python environment, unsupported CPU, an unwritable folder) stop the stage, and every isolate not reached is recorded as `not attempted (stopped early: <cause>)`.

Annotation tools that are present but not ready. `plasbench check` now asks AMRFinderPlus for its database (`amrfinder --database_version`), abricate for its database list and ISEScan whether its clustering step works,
and says `[MISS] ... installed but not ready` with the fix: `amrfinder -u` (once, about 100 MB), or `plasbench install-tools reference-annotation --yes`, which also pins `fastcluster<1.3` (1.3.0 breaks ISEScan beside NumPy 1.x). A caller that
is not ready is skipped in seconds and recorded as not evaluated. A caller that hangs is stopped at its limit (`ANNOTATION_TIMEOUT_SECONDS`: blank = max(300 s, 150 s per Mbp), ISEScan three times that; a number; 0 or off = no limit) and recorded
as `timed_out`; failed and timed-out annotations are never cached.

Slow data folder. When the data folder is on a Windows drive seen from WSL (`/mnt/c`, `/mnt/f`), NTFS/exFAT, a network share or a cloud-synced folder, SPAdes runs in a scratch folder under `~/.plasbench/scratch/<study>` and the finished results are moved back
(`WORK_DIR=auto`, the default; `WORK_DIR=data` turns it off; `WORK_DIR=<folder>` picks one). The log says `assembly work folder: <path> (fast local disk ...)`. A crash leaves a scratch folder behind; the next run removes it and says so.
The stage 2 and 3 loops print one summary line for isolates whose reference or reads are not downloaded yet, not one warning per row.

## Speed, sleep and run profiles

* **The computer going to sleep.** A laptop that sleeps pauses the run. While a run is active PlasBench asks the operating system not to sleep (the screen may still turn off; nothing outside the run is changed; no administrator
  rights): the run log says "keeping this computer awake while the run is active; it can still turn the screen off". `KEEP_AWAKE=0` turns it off. If the computer sleeps anyway, `plasbench status` says "The computer was asleep from
  00:46 to 03:33 (2 h 47 min); the run was paused, not slow", that time is left out of every step's time, and no tool is stopped or called slow because of it. In WSL without Windows interop it says it cannot prevent sleep and names
  `powercfg /change standby-timeout-ac 0`.
* **Where did the time go?** `plasbench profile-run` (or `--json`) prints a per-stage, per-step and per-isolate table, the annotation callers' own times, the sleeps and the five biggest costs with a suggestion for each. A run ends with a short "Time spent" list.
* **Insertion sequences on the chromosome.** `ISESCAN_SCOPE=plasmids` (default) searches only the replicons labelled plasmid in the truth; the report then says "not evaluated (chromosome not searched)", never "none found". `all` searches everything.
* **Profiles.** `plasbench run --profile fast|standard|thorough` (or `RUN_PROFILE`, the window's Settings, the assistant). `fast` switches off optional analyses that never change the leaderboard (ISEScan, the ranking-stability and rank-sensitivity sweeps, performance drivers,
  the recommender evaluation, per-dimension tables, bin agreement, candidate multiplicity, MultiQC) and prints what it turned off and what that saves; `thorough` turns extras on. The profile is in the run manifest and the report's run metadata. The table is `config/run_profiles.tsv`; a setting you set yourself always wins.
* **CPU figures** in `plasbench status` and the window are shown as cores ("about 4.8 of 6 CPU cores busy (79% of this computer)"); the raw summed percentage (100% = one core) is in the JSON (`cpu_percent`, with `cores_busy`, `cpu_cores`, `cpu_share_of_computer`).

## Stopping PlasBench: closing the window, Quit, Quit everything, `plasbench stop`

Closing the window vs quitting PlasBench. These are different things, and closing a window never stops anything.

| What you do | What happens |
|---|---|
| **Close the window** (the window's X, Alt+F4, closing the app window or the browser tab) | Nothing is stopped. PlasBench (the server) and your runs keep going. Start `plasbench ui` or click the desktop icon: you get the same server back. A window that closes only lowers the "windows open" count; PlasBench never exits because no window is open. |
| **Quit** (top right) | Ends this PlasBench server. If a run is going you choose Cancel, **Stop and quit** (cancels the run first) or **Quit and keep running** (the default; the run goes on in the background). |
| **Quit, then "Stop all PlasBench on this computer..."** (Quit everything) | Ends every PlasBench server of your account on this computer, including stale ones left on other ports. Runs keep going unless you switch on the red "Also stop N running runs/jobs". |
| **Quit everything and "Quit and restart WSL (wsl --shutdown)"** (WSL only) | Also runs `wsl --shutdown` from Windows: it ends everything in WSL. See below. |

`plasbench stop` does the same from a terminal and works when a window cannot reach its server:

```bash
plasbench stop --dry-run          # show exactly what would end and what is skipped; changes nothing
plasbench stop                    # list it, ask y/N, then stop every recorded PlasBench window server
plasbench stop --runs             # also cancel active runs and jobs (finished work is kept; you can resume)
plasbench stop --windows          # also close the app windows PlasBench opened
plasbench stop --yes --json       # no question; machine-readable result
```

What it ends and what it never touches:
- Only servers PlasBench itself recorded (`~/.plasbench/ui/server.json`, `servers/*.json`, other UI homes), and only after checking that the process is really a PlasBench server (its command line, and that the process start time agrees with the record, so a reused process id is never mistaken for one).
- It asks each server politely first (the same quit as the Quit button, keeping runs going), then sends a stop request, and force-kills only after a grace period (10 s) if the same verified process is still there. On Windows the same steps use `taskkill` without, then with, `/F`.
- A program that holds a PlasBench port (for example the WSL relay, Docker, or any other program) is never killed by its port number: it is reported ("port 8770 is held by another program (name, pid)") and left alone. Nothing runs with sudo, other users' processes are never touched, and `plasbench stop` never ends itself.
- Runs and jobs keep going unless you add `--runs`. Terminal-started runs are found through their run lock; each is listed with its name, how long it has run and its last step. A stopped run is recorded (`stopped_by_user`).
- `--windows` closes only browser windows whose command line carries the address of a PlasBench server and PlasBench's own app-window profile. Other Edge or Chrome windows are never touched. Windows normally close themselves when their server ends ("PlasBench has stopped").
- Everything it ends is written to `~/.plasbench/ui/stop.log` and to the session log. Exit codes: 0 nothing left running (or only runs you chose to keep), 3 something could not be ended (listed), 2 usage.

`wsl --shutdown` (`plasbench stop --wsl-shutdown --yes [--runs]`, or the checkbox in the Stop all dialog) is the most destructive choice and is never the default. It exists only when PlasBench runs inside WSL and Windows interop lets it start `wsl.exe`; otherwise it is shown disabled with the reason and the exact command to run in Windows PowerShell. It ends **every** WSL distribution, the Docker Desktop engine (Docker Desktop restarts its WSL backend), every terminal open in WSL (anything unsaved there is lost), every PlasBench server, this window and, if you also switch on the red runs switch, the running runs. With a run active it is blocked until you do. The window asks twice: a list of everything it ends, then you type `SHUT DOWN WSL` and press **Shut down WSL now**. PlasBench first stops its servers and runs, then starts `wsl --shutdown` from Windows after a short delay (so the page can say "WSL is shutting down"). Finished work and files are kept and runs can be resumed. You typically need it after changing `C:\Users\<you>\.wslconfig` (memory, processors, swap), after being added to the `docker` group, or to recover a stuck WSL. Afterwards reopen Ubuntu or run `plasbench ui`; the next WSL start takes a few seconds and PlasBench windows must be reopened.

## Troubleshooting

### My downloads are slow or restart

Stage 1 logs a download when it starts, then about one short line per 10% (`SRR123: 34% of 9.5 GB, 3.4 MB/s, about 31 min left`) and a line when something changes; `plasbench status` shows the live figures (3.4 MB/s now, 3.1 MB/s average, bytes received) from `results/download_progress.json`. What to check, in this order:

1. **Where the data folder is.** A Windows drive seen from WSL (`/mnt/c`, `/mnt/f`, 9p), NTFS/exFAT, a network share or a synced folder is slow for the many small writes of a download and for reading a 9 GB file back for the checksum (about five minutes from `/mnt/f`). PlasBench then downloads and checks in `~/.plasbench/downloads/<study>` on the local disk and moves the verified file (`DOWNLOAD_TMP_DIR`; `data` turns that off; the log says which it used). A data folder on Ubuntu's own disk (`~/...`) needs no such step.
2. **ENA or the SRA Toolkit.** `READ_SOURCE=auto` uses ENA first. If the SRA Toolkit fails with `Failed to create TLS stream`, the log explains it once (a proxy, the system CA certificates, `vdb-config`) and ENA is used; the failure is remembered for 24 hours (`~/.plasbench/prefetch_history.json`) so it is not retried on every isolate.
3. **Connections.** ENA limits each connection, so speed grows with the number of connections up to a point. `ENA_MAX_CONNECTIONS` (default 16, hard maximum 24) is the total for both mates. `plasbench net-bench` measures 1, 4, 8 and 16 connections with small reads and recommends a figure; run it twice, single measurements are noisy (one link gave 0.61 MB/s with 4 connections, 3.10 with 8, 4.25 with 16). More is not always better: very high numbers can get an address throttled, and when ENA answers 429 or 503 PlasBench lowers its own budget for the rest of the run. To try two isolates at once set `MAX_PARALLEL_DOWNLOADS=2` (the budget is split) and compare the MB/s.
4. **A download that "restarts".** It should not: finished chunks are kept in `<file>.part.state` and a failed chunk is retried alone. After a failure, run the same `plasbench run ...` command again; the log says `N of M chunks were already on disk from an earlier attempt`. Only a changed file on the server, a damaged state file or a wrong final MD5 start a file again, and the log says which. Every attempt is kept in `logs/<sample>.ena.log`.
5. **A very deep run.** `READ_DEPTH_CAP_X` (default 150) downloads only the first read pairs of a run deeper than that; `off` downloads whole files.

**Reporting an issue.** When a step fails and nothing below fits: copy the complete error text (Ctrl+Shift+C in a Linux or Windows Terminal, Cmd+C on a Mac, or the **Copy** button of the
console in the window), run `plasbench issue-report` (or **More > Report an issue > Prepare diagnostics** in the window), and open a
[New issue](https://github.com/ubeffiong/plasbench/issues/new/choose). The README section [Reporting an issue](../README.md#reporting-an-issue) lists exactly what to send, with a
template and three worked examples; [SUPPORT.md](../SUPPORT.md) is the short version.

```text
Too many windows or servers (several PlasBench windows, ports 8770 and 8771 both in use, a pop-up that keeps coming back)
    1. `plasbench stop --dry-run` lists every PlasBench server and what would be ended; nothing changes.
    2. `plasbench stop` ends them all (runs keep going; add `--runs` to stop those too). If a window shows the bar
       "This window belongs to an older PlasBench session", its Stop all... button shows this command with a Copy button.
    3. `plasbench ui` starts one clean server and window. Closing a window never stops PlasBench by itself.
```

```text
Pop-ups say "This window needs to be reopened", or "PlasBench's program files changed while this window was open"
    These came from two faults in 0.5.5 (a check in the page that always said "older server", and an old window
    that kept using the key of an earlier run); both are fixed. If they still appear, probably an old window is open:
    1. Close EVERY PlasBench window (look in the taskbar; a window of an earlier run does not report in).
    2. Run `plasbench ui` once. If a window is already open it says "PlasBench is already open" and brings it
       to the front instead of opening another; otherwise it opens one.
    3. Run `plasbench ui-state`. It lists every PlasBench server on this computer (port, pid, version, start
       time; keys are never shown), how many windows reported in, and anything else listening on the same port,
       and warns when more than one server or window is open.
    A window that really belongs to an older session shows one bar, "This window belongs to an older PlasBench
    session", with Close this window, Open the current window and Check again. It does not repeat.
    Restart window keeps this window and its address; it no longer opens a second window or moves to another port.
```

```text
The banner says "This window is running an older version of PlasBench than the page"
    Open Details in the banner: it lists what the window runs (version and folder), the PlasBench folder, the window's
    pid and port, and any program file that really changed. Run `plasbench ui-state` for the same in the terminal.
    Case 1, "PlasBench was updated (X -> Y) while this window was open": press Restart window (runs keep going).
    A second `plasbench ui` or the desktop icon now replaces a window older than the command.
    Case 2, "PlasBench is installed in two places with different versions": Restart cannot help. In a terminal:
        conda activate plasbench && cd ~/PlasBench && python -m pip install --no-deps .
    (or `plasbench upgrade`, which verifies the installed program against the folder and repairs it), then start
    PlasBench again. Touched files, caches and files the window never loaded no longer raise the banner.
    "Dismiss for this server run" hides it until the situation changes (a new server, or a different kind).

`plasbench` from another folder says it cannot find the PlasBench folder
    The folder is looked for in this order: --project-root, PLASBENCH_HOME, the current folder (or a parent), the
    folder recorded at install time (~/.plasbench/install.json), the checkout plasbench was imported from, ~/PlasBench.
    When it was not the current folder it says which one it used. Otherwise: cd into the folder, pass --project-root
    /path/to/PlasBench, or run ./install.sh there (it records the folder). The installer also writes ~/.local/bin/plasbench
    so the command works outside the conda environment (PLASBENCH_NO_LAUNCHER=1 skips it; a file there that PlasBench
    did not write is never replaced).

Empty sample sheet
    Add valid data rows to config/accessions.tsv or pass --samples PATH.

Missing executable
    Activate the plasbench Conda environment, then run plasbench check.

"Resources check stopped my run" (exit code 6) or "I have enough disk space but it says there is not"
    Read the block top to bottom. The headline says whether the run CANNOT START or only has warnings, and names the cause (disk space, an unwritable folder);
    memory and CPUs are reported on the same line with the rule that was applied ("memory: 5 GB assembler budget <= 7.0 GB available: ok").
      Measured:  each folder, the drive it is really on, the free bytes and how they were read. Under WSL it also prints the evidence for Ubuntu's virtual disk:
                 the distribution (the one you are in, found by its exact name; docker-desktop is never used), the ext4.vhdx file, the Windows volume and its free bytes.
                 "unknown" means the lookup failed: no number is shown then. To check it yourself, in Windows or from Ubuntu:
                     powershell.exe -NoProfile -Command "(Get-PSDrive C).Free/1GB"          (use your drive letter)
      Needed:    the "working set" (what the first isolates need AT ONCE) and the whole run (what every isolate leaves on disk: reads, trimmed reads and the assembler
                 folder are kept), whether it was measured (reads on disk, the cohort's lock) or sampled (ENA sizes of up to 20 isolates) or only a typical isolate, and
                 the assumptions. All of it is an estimate and says so.
      Only the working set can BLOCK a run (the first isolates cannot fit, or the Windows drive under Ubuntu's disk is under 2 GB free). A whole cohort that will not
      fit is a WARNING: "this run will fill the drive after about N isolates". Add `--max-isolates N` (the message suggests a number), free space or use a bigger
      drive, or just start: a guard before each isolate's download and assembly stops the run cleanly (exit 6) when the next isolate no longer fits plus a reserve
      (`PLASBENCH_DISK_RESERVE_GB`, default 5). Finished isolates are kept; free space and run the same `plasbench run ...` command again to continue.
    Under WSL, where the folders are decides what matters. On a mounted Windows drive (/mnt/e) only small things go to Ubuntu's own disk (conda environments, logs), so only a
    floor (`PLASBENCH_VDISK_MIN_GB`, default 2) blocks and under 10 GB warns. On Ubuntu's own disk, the Windows drive holding ext4.vhdx is the limit even when `df` shows more.
    "E: is not mounted: /mnt/e is just a folder on Ubuntu's disk" means /mnt/e is not the E: drive: files would go to Ubuntu's disk. Mount it (PlasBench never runs this):
        sudo mkdir -p /mnt/e && sudo mount -t drvfs E: /mnt/e
    `PLASBENCH_SKIP_DISK_CHECK=1` turns the disk figures and the guard off when you know the estimate is wrong for your data. `python3 python/preflight_resources.py vdisk`
    and `plasbench picker-check` print the Ubuntu-disk evidence on their own.

The run stopped in stage 3: SPAdes failed
    Stage 3 now reads the assembler's log, names the cause and says what to do, in one block:
      "SPAdes failed for <isolate>: <cause> (<the log line>). What to do: ... Log: <path>"
    The same cause and advice are in results/assembly_status.tsv (columns cause and advice),
    in `plasbench status` / `plasbench diagnose`, and in the window's run panel. A cause that
    belongs to the computer (disk full, a broken Python, a CPU feature, no writable folder)
    would repeat for every isolate, so stage 3 stops at the first one with exit code 5 and the
    rest are recorded as "not attempted". To continue after the fix, run the same
    `plasbench run ...` command again: finished isolates, downloads and trimmed reads are
    reused (there is no separate --resume option).

    Cause                    What the log shows                          Check                     Fix
    disk full                "No space left on device", Errno 28         df -h . ; df -h $TMPDIR   Free space. Under WSL the
                                                                                                   Windows drive holding
                                                                                                   Ubuntu's virtual disk (often
                                                                                                   C:) must have room too.
    out of memory            std::bad_alloc, "Out of memory", exit 137   free -h ; dmesg | tail    Retried once automatically
                             or "OS return value: -9"                                              with half the threads and a
                                                                                                   budget that fits the free
                                                                                                   memory. Else lower THREADS /
                                                                                                   ASSEMBLY_MEMORY_GB; WSL:
                                                                                                   memory= in .wslconfig, then
                                                                                                   wsl --shutdown.
    SPAdes memory limit      "Memory limit ... exceeded"                 grep -i memory <log>      Same retry; raise --memory-gb.
    too many threads         pthread_create, "Resource temporarily       nproc ; ulimit -a         plasbench run --threads N
                             unavailable"                                                          (N = your CPUs; PlasBench
                                                                                                   also caps THREADS to the
                                                                                                   usable CPUs).
    Python / distutils       ModuleNotFoundError, SyntaxError            spades.py --test          plasbench install-tools, or
                                                                                                   SPAdes 4 on Python 3.12.
    illegal instruction      "Illegal instruction", exit 132             uname -m ; lscpu          Re-install the tool here.
    truncated / bad reads    "unexpected end of file", gzip errors       gzip -t <reads>           Delete the reads and run the
                                                                                                   same command: stage 1 fetches
                                                                                                   them again (the message gives
                                                                                                   the exact rm command).
    empty or too short       "no reads", k-mer larger than read length   zcat <reads> | head       Check MIN_READ_LEN, FASTP_EXTRA.
    read-only / no TMPDIR    "Read-only file system", "Permission        ls -ld <folder>           Use a writable folder; avoid
                             denied", "No usable temporary directory"                              studies on /mnt or synced
                                                                                                   folders.
    stale output folder      "output_dir is not empty", --continue       ls <data>/<isolate>/      Removed and retried once.
    not recognised           anything else                               tail -30 <log>            The message quotes the last
                                                                                                   15 lines; nothing is guessed.
    Before stages 0, 2 and 3 a resource check (python/preflight_resources.py) looks at free disk
    (study, data and temporary folders; under WSL also the Windows drive holding Ubuntu's disk),
    memory, usable CPUs and writable folders, and prints "Resources check: ok" or the warnings.
    Only a shortage that stops the FIRST isolates stops the run (exit code 6); a whole cohort that will not fit is a warning, and a guard before each isolate stops the run
    cleanly when space runs out (see "Resources check stopped my run"). Set PLASBENCH_SKIP_DISK_CHECK=1 to try anyway.
    WSL limits (memory, processors, swap) are set in C:\Users\<you>\.wslconfig and change only
    after `wsl --shutdown`.

The window shows an old "installed" answer, or a tool you just installed as "not found"
    The window remembers what it found on this computer for 30 seconds and refreshes it
    in the background. Press Check again on Set up (or restart the window) to clear that
    memory; nothing is stored on disk, so there is no cache folder to delete. See
    docs/WINDOW_PERFORMANCE.md.

The window is slow to open its pages
    Keep the workspace on the computer's own disk (under /home in WSL, not /mnt/c or a
    OneDrive folder) and keep PATH short; see docs/WINDOW_PERFORMANCE.md for what is
    cached and why.

I updated PlasBench and the window shows errors like "no such API: workflow"
    The window was open while PlasBench was updated: the page is the new one, the program
    behind it is the old one. A banner at the bottom says so ("PlasBench was updated ...").
    Press Restart window: a new PlasBench starts and the window moves to it; your runs are
    detached and keep going. If the dialog says it cannot restart by itself, choose Quit
    (Quit and keep running if a run is going) and start PlasBench again from its desktop
    icon or with: plasbench ui. If a page only looks stuck or out of date, use Reload page
    (clear cache) in the top bar, or press Ctrl+Shift+R (Cmd+Shift+R on a Mac).

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

## Metagenomic Plasmid Benchmarking

For mixed-community work, use the separate `plasbench meta` route rather than
an isolate benchmark. It supports graph/bin reconstruction scoring and a
separate three-class contig-classification contract, retains uncertain calls,
and can import MAP-compatible mobilome evidence without treating that evidence
as truth. Follow [`METAGENOMICS.md`](METAGENOMICS.md) for the complete manifest,
PPR-Meta/PlasmidHunter normalization, MAP import, and experimental-tool rules.

Metagenomic communities are not treated as large isolates. Use the separate
community/bin contract when several organisms or strains are present:

```bash
plasbench metagenomics validate --manifest meta_samples.tsv
plasbench metagenomics score \
  --manifest meta_samples.tsv \
  --predictions-dir predictions_meta \
  --out-dir results_meta
```

The manifest declares sample grouping, information regime, truth status, graph
files, and optional independent linkage evidence. Tool adapters must emit
`<tool>/<community>.bins.tsv` records with bin membership, path/orientation,
confidence, plasmid score, and ambiguity status. The resulting dedicated
`metagenomics.report.html` reports global bin matching, split/merge events,
and separate chromosome/virus contamination. It does not create host
assignments, circularity claims, or clinical confirmation. Use
`plasbench run -m metagenomics --samples meta_samples.tsv --predictions-dir
predictions_meta --results-dir results_meta` as an equivalent score-and-report
shortcut. Full schemas and interpretation rules are in `docs/METAGENOMICS.md`.

## Orthogonal Validation Evidence

Benchmark scores measure computational agreement with a declared reference;
they do not prove that an AMR gene is plasmid-borne, transferable, closed, or
clinically significant. Preserve optional independent laboratory or technology
evidence with a separate, reviewable table:

```bash
plasbench validate-orthogonal-evidence \
  --evidence orthogonal_evidence.tsv \
  --out results/orthogonal_validation.summary.json
```

Supported evidence includes independent long reads, hybrid assembly, targeted
PCR, plasmid extraction, conjugation, Hi-C, and optical mapping. Each record
requires a reference and is labelled confirmed, supportive, inconclusive, or
contradicted. The summary is downloadable from the report artifact explorer;
it never changes benchmark scores or upgrades a candidate to a biological
claim. See `docs/ORTHOGONAL_VALIDATION.md` for the schema.

## Long-Read Reconstruction

PlasBench can optionally run native ONT or PacBio FASTQ reconstruction through
Flye followed by MOB-Recon. Install the profile, stage one file per sample as
`data/<sample>/long_reads.fastq.gz`, enable the tool, and run the pipeline
normally -- stage 7 is part of the default stage list (it no-ops harmlessly
for any sample with no long-read file staged), and each tool is scored under
its own track from `config/tool_capabilities.tsv` in the same pass as every
short-read tool, so no separate scoring invocation is needed:

```bash
plasbench install-tools long-read
plasbench run --flye-mob-recon on --flye-read-type nano-hq
```

`--analysis-track TRACK` restricts a `run`/`report` invocation to scoring
only tools declared under that track (each tool's own track is still stamped
correctly regardless) -- useful for a single-track study like the depth
ladder, not needed for a normal mixed short/long-read run.

Use `nano-raw`, `nano-hq`, `pacbio-raw`, or `pacbio-hifi` to match the source
reads. Flye assembly is not itself called a plasmid reconstruction: MOB-Recon
must complete successfully before PlasBench emits a predicted-plasmid FASTA.
The long-read track is reported separately and cannot be mixed with short-read
or hybrid conclusions.

For hybrid (long+short) input, two independent tools are available --
Plassembler and Hybracter's hybrid mode -- and for long-read-only input,
Hybracter's long mode is a second path alongside Flye+MOB-Recon, since
assembler choice materially affects plasmid completeness on ONT data:

```bash
plasbench install-tools plassembler   # Plassembler + shared PLSDB database
bash env/download_plassembler_db.sh
plasbench run --plassembler on              # hybrid
plasbench install-tools hybracter
plasbench run --hybracter-hybrid on         # hybrid, via Hybracter instead
plasbench run --hybracter-long on           # long-read-only, via Hybracter instead of Flye+MOB-Recon
```

Hybracter's two modes are independently selectable -- enabling one never runs
the other -- and both reuse the same Plassembler database rather than a second
copy of it.

For long-read-only input, Trycycler+MOB-Recon is a third path alongside
Flye+MOB-Recon and Hybracter's long mode: it reconciles several independent
Flye assemblies of the same reads into one consensus per replicon before
handing the result to MOB-Recon, which makes it substantially slower (roughly
`TRYCYCLER_ASSEMBLY_COUNT`x a single Flye run) but more robust to a single
misassembled replicon:

```bash
plasbench install-tools trycycler
plasbench run --trycycler-mob-recon on --trycycler-assembly-count 4
```
A single cluster that fails to reconcile is dropped and the sample still
completes on whichever clusters survive (recorded in `tool_status.tsv`'s
reason as e.g. "dropped 1 of 4 cluster(s)"); only a sample where every cluster
fails to reconcile is recorded as failed.

All five long-read/hybrid tools (`flye_mob_recon`, `plassembler`,
`hybracter_long`, `hybracter_hybrid`, `trycycler_mob_recon`) are subject to
the same circularity guard (`docs/COHORTS.md`: `truth_independent_of_long_reads`).

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

## Reproducibility and Citation

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
