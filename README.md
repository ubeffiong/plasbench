# PlasBench

A reproducible, Ubuntu-first pipeline that **benchmarks how well plasmid-reconstruction
tools recover plasmids from short reads**, using complete (long-read) assemblies as
ground truth.

**Read support:** the current reconstruction workflow consumes paired-end short-read
FASTQ files (`*_1.fastq.gz`, `*_2.fastq.gz`), normally Illumina. Long-read data
(ONT/PacBio) is supported as evidence for the completed reference truth assembly,
not as a native long-read FASTQ reconstruction input in this release.

For each isolate the pipeline:

1. downloads a **complete reference assembly** (long-read/hybrid → ground truth) and the
   **matched Illumina reads** from NCBI/SRA;
2. labels every reference sequence **plasmid vs chromosome** from the NCBI sequence report;
3. QC-trims and assembles the short reads;
4. runs each plasmid tool (**mob_recon, Platon, plasmidSPAdes**, gplas optional);
5. maps each tool's predicted-plasmid sequence back onto the reference and computes
   **base-level precision / recall / F1**;
6. aggregates all samples into a **leaderboard** (TSV + Markdown) for the pitch.

> **One metric, every tool.** Classification tools and re-assembly tools are made
> comparable by projecting each tool's predicted-plasmid sequence onto the reference and
> asking, per reference base: *did the tool correctly call this base as plasmid?*
> `recall` = completeness (fraction of true plasmid recovered); `precision` = 1 −
> chromosomal contamination.

---

## 0. Clone and run

### Native Linux / WSL2 installation

Use Ubuntu or WSL2 with Git, Conda/Mamba (Miniforge recommended), and at least
20-40 GB of free disk space. On Windows, run these commands **inside Ubuntu WSL**,
not PowerShell.

```bash
# 1. Download the source code.
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench

# 2. Create the reproducible bioinformatics environment (once).
bash env/setup_conda.sh          # creates the 'plasbench' conda env
conda activate plasbench
python -m pip install --no-deps . # installs the `plasbench` terminal command

# Next: choose and install the tool group you need into the same environment.
plasbench install-tools core           # download, QC, and scoring tools
plasbench install-tools assembly       # SPAdes and Unicycler
plasbench install-tools reconstruction # MOB-suite and Platon
plasbench install-tools long-read      # Flye and MOB-suite for ONT/PacBio inputs
plasbench install-tools all            # all standard profiles

# 3. Confirm the scoring/report engine works. No downloads or bio-tools needed.
plasbench test
plasbench demo

# 4. Install the Platon database if Platon is enabled in config/config.sh.
bash env/download_platon_db.sh   # one-time Platon database download

# 5. Add matched complete-assembly and Illumina accessions to config/accessions.tsv,
# then run the full benchmark.
plasbench run
```

The final interactive report is `results/benchmark.report.html`. Run
`plasbench --help` or `plasbench run --help` to see available commands and options.
The complete terminal-accessible guide is available with `plasbench docs`; for
example, use `plasbench docs --topic outputs` or `plasbench docs --topic troubleshooting`.
For a non-technical project overview for research partners and funders, see
[`docs/CONCEPT_NOTE.md`](docs/CONCEPT_NOTE.md), or run `plasbench concept-note`.

## Ownership, Citation, And Branding

PlasBench is open-source software under the [MIT License](LICENSE), copyright
2026 Ubokobong Effiong. Please cite the version and benchmark cohort used in
research outputs; citation metadata is in [`CITATION.cff`](CITATION.cff).
The PlasBench name and branding may not be used to imply endorsement or an
official release of a modified version. See [`NOTICE`](NOTICE) and
[`TRADEMARKS.md`](TRADEMARKS.md).

## Acknowledgements

PlasBench acknowledges the International Research Center of Excellence at the
Institute of Human Virology Nigeria (IHVN) as the professional organisation of
project lead Ubokobong Effiong. This acknowledgement does not by itself imply
institutional ownership, funding, endorsement, or approval. See
[`ACKNOWLEDGMENTS.md`](ACKNOWLEDGMENTS.md).

### Docker installation

Docker avoids a host Conda installation. Build the image from the cloned repository:

```bash
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench
docker build -t plasbench:local .

# Verify the scoring and HTML-report path.
docker run --rm plasbench:local plasbench demo

# Run real data while keeping outputs on the host machine.
docker run --rm \
  -v "$PWD/config:/work/config:ro" \
  -v "$PWD/data:/work/data" \
  -v "$PWD/logs:/work/logs" \
  -v "$PWD/results:/work/results" \
  -e DATA_DIR=/work/data \
  -e LOG_DIR=/work/logs \
  -e RESULTS_DIR=/work/results \
  -e PLATON_DB=/work/data/db/platon/db \
  plasbench:local plasbench --project-root /opt/plasbench run \
  --samples /work/config/accessions.tsv
```

If Platon is enabled, mount its versioned database at
`/work/data/db/platon/db`, or disable Platon with `RUN_PLATON=0`. The container
does not bundle this large database.

---

## 1. What you need

| Requirement | Why | Where it's covered |
|---|---|---|
| Ubuntu 20.04+ (or WSL2 on Windows) | the scripts are bash | — |
| `conda`/`mamba` (Miniforge recommended) | installs all bio-tools | `INSTALL.md` |
| ~20–40 GB free disk | assemblies + reads + intermediates | — |
| Internet access to NCBI/SRA | downloads data | — |
| Python ≥ 3.9 | CLI and scoring scripts | installed by the Conda environment |

You do **not** need to know how every tool works to run this. The only script worth
reading closely is `python/score_plasmids.py` — that is the benchmark's logic.

---

## 2. Repository layout

```
plasbench/
├── README.md                 <- this file
├── INSTALL.md                <- environment + tool installation
├── docs/
│   ├── FINDING_DATA.md       <- how to find matched complete-assembly + Illumina pairs
│   └── METHODS.md            <- the scoring model, for your write-up / methods section
├── config/
│   ├── config.sh             <- EDIT THIS: paths, threads, which tools to run
│   └── accessions.tsv        <- EDIT THIS: your sample sheet (isolate → accessions)
├── env/
│   ├── environment.yml       <- conda environment definition
│   ├── setup_conda.sh        <- creates the env
│   └── download_platon_db.sh <- one-time Platon DB download
├── scripts/                  <- numbered bash stages + run_all.sh orchestrator
│   ├── lib.sh 00_setup.sh 01_download.sh 02_truth.sh
│   ├── 03_assemble.sh 04_run_tools.sh 05_score.sh 06_aggregate.sh
│   └── run_all.sh
├── adapters/                 <- convert each tool's output to a standard FASTA
├── python/                   <- make_truth.py, score_plasmids.py, aggregate_results.py
├── test/                     <- run_demo.sh (offline), test_scoring.py (unit test)
├── data/                     <- created at runtime (per-sample downloads)
├── results/                  <- created at runtime (per-sample outputs + leaderboard)
└── logs/                     <- created at runtime (one log per tool per sample)
```

---

## 3. Step-by-step (full run)

### Step 1 — Install (once)
Follow **`INSTALL.md`**. In short:
```bash
bash env/setup_conda.sh
conda activate plasbench
bash env/download_platon_db.sh
```

### Step 2 — Verify the engine offline (recommended)
```bash
python3 test/test_scoring.py     # unit test: asserts the metric math is correct
bash    test/run_demo.sh         # end-to-end on synthetic data → prints a leaderboard
```
If these pass, the analysis logic is sound and any later problem is environmental
(a tool or a download), which is much easier to debug.

### Step 3 — Build your sample sheet
Edit `config/accessions.tsv`. One isolate per row:
```
sample_id	assembly_accession	sra_run
ecoli_01	GCF_012345678.1	SRR12345678
kpneu_01	GCF_023456789.1	SRR23456789
```
`assembly_accession` must be a **complete** genome (built from long reads/hybrid);
`sra_run` must be the **matched Illumina** run for the *same isolate*.
**How to find these pairs is the real curation task** — see `docs/FINDING_DATA.md`.
Aim for 10–20 isolates for a hackathon-scale v1.

### Step 4 — Configure
Edit `config/config.sh`: set `THREADS`, `MEMORY_GB`, and toggle tools
(`RUN_MOB_RECON`, `RUN_PLATON`, `RUN_PLASMIDSPADES`, `RUN_GPLAS2_MOB`, `RUN_GPLAS2_EXTERNAL`). Turn a tool off if
you haven't installed it yet — the pipeline just skips it.

### Step 5 — Run
```bash
conda activate plasbench
python -m pip install --no-deps .
plasbench run
```
Or run stages individually (handy while iterating):
```bash
bash scripts/run_all.sh 0        # dependency check only
bash scripts/run_all.sh 1 2      # download + truth
bash scripts/run_all.sh 3 4      # assemble + run tools
bash scripts/run_all.sh 5 6      # score + leaderboard
```
Every stage is **resumable**. Stage 4 reuses a completed tool result only when both its
prediction FASTA and completion marker exist; set `FORCE_RERUN_TOOLS=1` to rerun tools
after changing their version or settings. Failed tools are recorded and excluded from
scoring rather than being treated as a zero-score prediction.

### Step 6 — Read the results
```
results/scores.tsv                  # one row per (sample, tool): TP/FP/FN, precision, recall, F1
results/tool_status.tsv              # completed/reused/failed/skipped state and failure locations
results/benchmark.leaderboard.tsv   # per-tool means/medians, ranked by mean F1
results/benchmark.leaderboard.md    # final Markdown table, including scored/completed/failed counts
results/benchmark.report.html       # offline dashboard, including linked heatmap and alignment explorer
results/<sample>/visualization/alignment_blocks.json # bounded PAF evidence for recovery tracks
results/benchmark.recommendations.tsv # coverage-gated operational method recommendations
results/<sample>/selected_candidate/ # copied best already-produced candidate + selection_report.json
```

Open `results/benchmark.report.html` in a browser for the final detailed report. It includes
the ranked table, per-sample score drill-down, execution status, scoring definitions, and a
tree explorer with direct download links for files under `results/`, `logs/`, and `data/`.
The visual-quality explorer links a sample-by-tool heatmap to zoomable
per-plasmid recovery tracks; see [visual quality](docs/VISUAL_QUALITY.md).
See [operational selection](docs/OPERATIONAL_SELECTION.md) for the strict distinction
between a benchmark winner, a reusable per-isolate candidate, and validated biology.

The pipeline validates that `config/accessions.tsv` has at least one complete,
uniquely named sample before starting any data stage; the checked-in sheet is a
template and must be populated first.

---

## 4. How scoring works (short version)

For each sample and tool:
- `minimap2 --secondary=no -x asm5 reference.fna pred_<tool>.plasmid.fasta > <tool>.paf`
- The reference's true plasmid/chromosome labels come from the NCBI sequence report.
- Every reference base **covered** by a predicted-plasmid alignment is a base the tool
  "claimed" as plasmid. Then:
  - **TP** = true-plasmid bases covered · **FP** = chromosome bases covered ·
    **FN** = true-plasmid bases *not* covered
  - `precision = TP/(TP+FP)`, `recall = TP/(TP+FN)`, `f1` = harmonic mean.

Overlapping alignments are merged so bases are never double-counted (unit-tested).
Secondary mappings are excluded so repetitive sequence is assigned from each
predicted contig's best reference hit rather than counted on multiple replicons.
An optional all-mappings diagnostic reports predicted bases with both plasmid and
chromosome placements without changing F1.
Predicted sequence that doesn't map to the reference at all is reported separately as
`unmapped_pred_bp` rather than silently punished. Full rationale in `docs/METHODS.md`.

---

## 5. Extending it (good hackathon sprints)

- **Add a tool**: write a one-file adapter in `adapters/` that emits a predicted-plasmid
  FASTA, add a block in `scripts/04_run_tools.sh`, add a `RUN_*` flag. Scoring is automatic.
- **Add bin-level metrics** (did the tool get the *right number* of distinct plasmids?)
  alongside the base-level metric.
- **Stratify** results by plasmid size, replicon type (Inc group), or AMR-gene carriage.
- **Vary read depth** (subsample with `seqtk`) to chart recovery vs coverage.
- **Wrap in Nextflow/Snakemake** for cluster-scale runs (the stages map 1:1 to processes).

---

## 6. Reproducibility notes

- Regenerate the explicit lock with `bash env/lock_environment.sh`; do not overwrite it with `conda env export`.
- Record tool versions per run (add `--version` calls to a manifest — a nice sprint task).
- Deposit your curated sample sheet + truth tables on **Zenodo** for a citable dataset —
  this is the actual publishable artifact PlasBench asks for.

## 7. License
MIT — see `LICENSE`.
