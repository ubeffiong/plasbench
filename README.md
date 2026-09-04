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

## 0. Get PlasBench

Three ways in. **Most users want Option A or B and never need the source code.**

| You are… | Use | What you need installed |
|---|---|---|
| a lab running the benchmark | **A — release archive** | conda (or Miniforge) |
| a lab that would rather not install anything | **B — container** | Docker only |
| modifying, extending or citing exact source | **C — source checkout** | git + conda |

---

### Option A — Download the release archive (recommended)

A complete terminal walkthrough, from a machine with nothing installed to a finished
benchmark. Copy each block in turn.

> **Which terminal?**
> **Linux or macOS** — open Terminal and continue.
> **Windows** — install WSL2 first: open PowerShell **as administrator**, run
> `wsl --install`, reboot, then open the **Ubuntu** app. Every command below goes in that
> Linux shell, **not** in PowerShell or CMD.

#### Step 1 — Get conda, once *(optional)*

**You can skip this entirely.** If no conda is found, `./install.sh` in Step 3 detects that
and offers to install Miniforge for you. Do it here only if you would rather install conda
yourself first, or if `install.sh` reports that conda landed but is not yet on your `PATH`
(open a new terminal and re-run it in that case).

Skip this if `conda --version` already answers.

```bash
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-$(uname)-$(uname -m).sh -b
~/miniforge3/bin/conda init bash
exec bash
```

*Expected:* `conda --version` now prints a version. Miniforge is the recommended
distribution; it defaults to conda-forge and carries no commercial licensing conditions.

#### Step 2 — Download PlasBench

```bash
curl -fL -O https://github.com/ubeffiong/plasbench/releases/download/v0.1.6/plasbench-0.1.6.tar.gz
curl -fL -O https://github.com/ubeffiong/plasbench/releases/download/v0.1.6/plasbench-0.1.6.tar.gz.sha256
sha256sum -c plasbench-0.1.6.tar.gz.sha256      # must print: OK
```

*Expected:* `plasbench-0.1.6.tar.gz: OK`.

**The `-f` matters.** Without it, `curl` treats a missing release as success and writes
GitHub's short "Not Found" page *into* the file, leaving you with a 9-byte
`plasbench-0.1.6.tar.gz` and the confusing error
`sha256sum: no properly formatted checksum lines found`. With `-f`, curl fails loudly and
writes nothing. If you see `curl: (22) The requested URL returned error: 404`, the release
has not been published yet — see the note at the end of this section.

If the checksum does not match, delete the file and download it again — do not install it.
Sanity check: the archive is roughly 700 KB. If `ls -l` shows a handful of bytes, you
downloaded an error page, not PlasBench.

#### Step 3 — Install

```bash
tar -xzf plasbench-0.1.6.tar.gz
cd plasbench-0.1.6
./install.sh --tools
```

*Arguments:* `--tools` also installs the bioinformatics tools (SPAdes, MOB-suite, Platon,
minimap2 …). Drop it for just the environment and the `plasbench` command; add `--yes` to
skip prompts; `--help` lists options.
*Time:* 10–40 minutes, mostly downloading and solving the environment.
*If it stops immediately* saying no conda was found, you skipped Step 1.

#### Step 4 — Check it works, offline

Do this before downloading any data. It needs no network.

```bash
conda activate plasbench
plasbench test
plasbench demo
```

*Expected:* `test` ends with `ALL PLASBENCH TESTS PASSED`; `demo` prints a small
leaderboard and writes `results_demo/benchmark.report.html`. If either fails, fix the
installation before going further — nothing downstream will be meaningful.

#### Step 5 — Run a benchmark

```bash
plasbench run --cohort public-v2
```

*Expected:* the stages run in order (download → truth → assemble → tools → score →
aggregate), and the interactive report lands at **`results/benchmark.report.html`**.
*Time:* roughly 30–60 minutes per isolate; run a real cohort overnight.

Before a large run, set an NCBI API key ([Step 5 of the manual](#step-5--give-ncbi-your-credentials-recommended))
and check your disk and memory against [§3.0](#30-before-you-start--what-you-need).

---

> **If those download URLs do not resolve,** no release has been published yet. Until one
> is, either ask the maintainer for the `plasbench-<version>.tar.gz` archive and start at
> Step 3, or use [Option C](#option-c--source-checkout-contributors).
>
> **Maintainers — to publish a release.** Build the archive with `make dist` (it writes
> `dist/plasbench-<version>.tar.gz` and a matching `.sha256`), then either attach both
> files to a GitHub Release:
>
> ```bash
> gh release create v0.1.6 dist/plasbench-0.1.6.tar.gz dist/plasbench-0.1.6.tar.gz.sha256 \
>   --title "PlasBench 0.1.6" --notes "First public release"
> ```
>
> …or push the `v0.1.6` tag, which triggers `.github/workflows/release.yml` to publish the
> PyPI distribution and the GHCR container image. PyPI trusted publishing must be
> configured first — see [`docs/RELEASING.md`](docs/RELEASING.md).


### Option B — Container (nothing to install but Docker)

The image carries every tool and the MOB-suite database already built in.

```bash
# Published image:
docker pull ghcr.io/ubeffiong/plasbench:latest
docker run --rm ghcr.io/ubeffiong/plasbench:latest plasbench demo

# Or build it yourself from the release archive or a checkout:
docker build -t plasbench:local .
docker run --rm plasbench:local plasbench demo
```

Run a real benchmark, keeping every output on the host:

```bash
docker run --rm \
  -v "$PWD/config:/work/config:ro" \
  -v "$PWD/data:/work/data" \
  -v "$PWD/logs:/work/logs" \
  -v "$PWD/results:/work/results" \
  -e DATA_DIR=/work/data \
  -e LOG_DIR=/work/logs \
  -e RESULTS_DIR=/work/results \
  -e PLATON_DB=/work/data/db/platon/db \
  --env-file .ncbi.env \
  plasbench:local plasbench --project-root /opt/plasbench run \
  --samples /work/config/accessions.tsv
```

**Databases are not bundled.** Mount a Platon database at `/work/data/db/platon/db`, or
set `RUN_PLATON=0`. MOB-suite's database *is* baked into the image; if you build your own
image without it, mob_recon downloads ~1 GB on first use. Mount a persistent volume over
its default directory so it is not re-fetched on every run:

```bash
-v plasbench-mobsuite-db:/opt/conda/envs/mobsuite/lib/python3.10/site-packages/mob_suite/databases
```

…or set `RUN_MOB_RECON=0`.

For a provenance-bearing run, use `scripts/docker_run.sh` in place of plain `docker run`
(with the same mounts): it records the immutable image digest into `run_manifest.json`.

---

### Option C — Source checkout (contributors)

Use this only if you intend to modify PlasBench or cite an exact source state.

```bash
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench
bash env/bootstrap_conda.sh      # installs a conda manager if you have none (asks first)
bash env/setup_conda.sh          # creates the 'plasbench' environment
conda activate plasbench
python -m pip install --no-deps .
plasbench check --yes            # installs any missing tool or database
plasbench test && plasbench demo
```

---

### Where to go next

**[Section 3 is the full step-by-step manual](#3-user-manual--from-download-to-leaderboard)**
— resources, NCBI downloads, every stage's inputs and outputs, and how to read the
leaderboard honestly. `plasbench --help` and `plasbench run --help` list every option;
`plasbench docs --topic outputs` and `plasbench docs --topic troubleshooting` print the
same guide in the terminal. For a non-technical overview for partners and funders, see
[`docs/CONCEPT_NOTE.md`](docs/CONCEPT_NOTE.md) or run `plasbench concept-note`.


---

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

## 3. User manual — from download to leaderboard

This is the complete path a new user walks: obtain PlasBench, install it, prove it works
offline, fetch data from NCBI, run the benchmark, and read the result. Every step lists
what you give it, what it produces, roughly what it costs, and what to do next.

All timings below were **measured** on a 7-isolate African cohort using 6 CPU threads and
a 7 GB assembly cap. Treat them as order-of-magnitude guidance; your hardware and the
depth of your runs will move them.

### 3.0 Before you start — what you need

| Resource | Minimum | Comfortable | Why |
|---|---|---|---|
| CPU | 4 threads | 8–16 threads | Assembly and BLAST dominate; tools also run in parallel |
| RAM | 8 GB | 16–32 GB | SPAdes scales with **read count**, not genome size. A ~250x bacterial isolate needed **7.8 GB** for k-mer counting alone and failed under an 7 GB cap |
| Disk | 30 GB | 60–100 GB | ~630 MB per isolate (reads + reference + assembly), plus ~2.7 GB Platon database and a 3.2 GB container image |
| OS | Linux or WSL2 (Ubuntu) | — | On Windows, run inside WSL2 or use Docker. Do **not** run the shell stages from PowerShell |
| Network | required for stages 0–1 | — | Reference assemblies, SRA reads and tool databases are downloaded; scoring itself is offline |

**Time.** For 7 isolates on 6 threads: download ~2–25 min per isolate (SRA-dependent),
assembly ~9–28 min per isolate, then per isolate mob_recon ~1.7 min, Platon ~4.2 min,
plasmidSPAdes ~12.3 min. Scoring and aggregation for the whole cohort take under a
minute. Budget roughly **30–60 minutes per isolate** end to end, and run it overnight for
a real cohort.

> The pipeline is **idempotent**: every stage skips work that is already complete. A run
> interrupted by a reboot resumes exactly where it stopped — during development this run
> survived a full host restart and reused all 17 finished tool results.

---

### Step 1 — Get PlasBench

Pick **one** of three routes.

**Route A — release tarball (recommended if you just want to run it).** No git, no source
browsing.

```bash
# Download plasbench-<version>.tar.gz and its .sha256 from the Releases page, then:
sha256sum -c plasbench-0.1.6.tar.gz.sha256     # must print: OK
tar -xzf plasbench-0.1.6.tar.gz
cd plasbench-0.1.6
```

*Input:* the release archive. *Output:* a complete, runnable directory (~700 KB) holding
the pipeline, the shipped cohorts and `install.sh`. *Next:* Step 2, Route A.

**Route B — container (fewest moving parts).** Needs only Docker; no conda, no compilers.

```bash
docker pull ghcr.io/ubeffiong/plasbench:latest
docker run --rm ghcr.io/ubeffiong/plasbench:latest plasbench demo
```

*Output:* the offline demo leaderboard, proving the image works. *Next:* Step 3, then run
with bind mounts as shown in §0. *Note:* the image is ~3.2 GB and already contains every
tool plus the MOB-suite database; you still mount a Platon database (Step 4).

**Route C — git clone (contributors).** Use this if you intend to modify or cite exact
source state.

```bash
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench
```

*Maintainers:* `make dist` regenerates the Route A tarball and its checksum into `dist/`.

---

### Step 2 — Install

**Route A/C — one command.**

```bash
./install.sh              # creates the conda env and installs the `plasbench` command
./install.sh --tools      # the same, plus every tool the RUN_* flags in config/config.sh need
```

*Arguments:* `--tools` also installs the bioinformatics tools; `--yes` skips prompts;
`--help` prints usage. *Requires:* conda, mamba or micromamba on `PATH` — the installer
stops with instructions (Miniforge, or use the container) if none is found, rather than
half-installing. *Output:* a conda environment named `plasbench` and the `plasbench`
executable. *Time:* 5–20 minutes, mostly environment solving.

**Route B — nothing to install.** The image is the installation.

**Verify, whichever route:**

```bash
conda activate plasbench      # not needed for Docker
plasbench --version
```

*Expected:* a version string. If `plasbench: command not found`, you did not activate the
environment. *Next:* Step 3.

---

### Step 3 — Prove the engine works, offline

Do this **before** downloading anything. It needs no network and no bioinformatics tools,
and it isolates "is PlasBench broken?" from "is my data or tool install broken?".

```bash
plasbench test      # full regression suite over scoring, aggregation and reporting
plasbench demo      # synthetic end-to-end run: score -> aggregate -> leaderboard -> HTML
```

*Expected output:* `test` ends with `ALL PLASBENCH TESTS PASSED`. `demo` writes a small
leaderboard plus `results_demo/benchmark.report.html` and ranks three synthetic
predictors of known behaviour — a deliberately accurate one, a contaminating one and an
over-conservative one — so you can see the metric separate precision loss from recall
loss before trusting it on real data.

*If this fails,* stop and fix the installation; nothing downstream will be meaningful.
*Next:* Step 4.

---

### Step 4 — Install the tools and their databases

The benchmark itself is small; the tools and their reference databases are not.

```bash
plasbench install-tools core            # download, QC and scoring utilities
plasbench install-tools assembly        # SPAdes and Unicycler
plasbench install-tools reconstruction  # MOB-suite and Platon
plasbench install-tools all             # everything the enabled RUN_* flags need
```

Then the **databases**, which are not bundled:

```bash
bash env/download_mobsuite_db.sh        # fully automatic, ~450 MB
bash env/download_bakta_db.sh           # optional, for protein annotation
bash env/download_platon_db.sh          # prints instructions -- see below
```

`download_platon_db.sh` does **not** download by itself: Platon's Zenodo release is
periodically re-versioned, so the script refuses to pin a stale URL and instead prints the
current instructions. Fetch the live `db.tar.gz` link from
<https://github.com/oschwengers/platon> and either unpack it manually to `$PLATON_DB`, or
re-run with the URL supplied:

```bash
PLATON_DB_URL=<current_url> bash env/download_platon_db.sh
```

Budget ~1.7 GB of download and ~2.7 GB on disk. MOB-suite's database is already baked
into the container image.

> **gplas2 is optional, off by default, and needs care.** `plasbench install-tools gplas`
> installs bioconda's `gplas`, which is version **0.6.1** -- the older snakemake tool. The
> pipeline invokes `gplas -i <graph> -P <classifier>`, and the `-P/--prediction` flag
> exists only in **gplas2**, distributed from GitLab
> (<https://gitlab.com/mmb-umcu/gplas2>), not bioconda. Installing the bioconda package
> alone makes every `gplas2_mob` run **fail** rather than be cleanly skipped. Install
> gplas2 from its own repository, confirm `gplas --help` lists `-P`, and only then set
> `RUN_GPLAS2_MOB=1`.
>
> **gplas2 also requires `ASSEMBLER=unicycler`.** With the default SPAdes assembler the
> contigs are named `NODE_1_length_..._cov_...` while the GFA segments are bare numeric
> ids (`15`, `19`, ...), so the MOB labels cannot be mapped onto graph nodes and every
> `gplas2_mob` run fails with *"MOB plasmid FASTA identifiers do not match graph nodes"*.
> Unicycler emits matching identifiers in `assembly.fasta` and `assembly.gfa`. Because
> switching assembler changes the input for **every** tool, a cohort benchmarked with
> gplas2 must be assembled with Unicycler throughout — you cannot mix a SPAdes-based
> result for three tools with a Unicycler-based result for the fourth and still compare
> them. Note too that gplas2's environment pins ~200 packages to 2019
> builds, some served from Anaconda's `defaults` channel -- check that against your
> institution's licence position before depending on it.

**Confirm everything resolves before spending hours on data:**

```bash
plasbench check           # report what is missing
plasbench check --yes     # report AND install what is missing, without prompting
```

*Expected output:* an `[ok]` line for every required tool and for the Platon database,
ending in `Core dependency check PASSED.` This preflight is cheap and catches the common
failure — an enabled tool that was never installed. *Next:* Step 5.

---

### Step 5 — Give NCBI your credentials (recommended)

Stages 1 and the cohort tools query NCBI. Without an API key you are limited to ~3
requests/second; with one, ~10/second, and large cohort validations stop tripping rate
limits.

1. Create a free NCBI account, then **Account settings → API Key Management** and
   generate a key.
2. Put it in a local, git-ignored file at the repository root:

```bash
cat > .ncbi.env <<'EOF'
NCBI_API_KEY=your_key_here
NCBI_EMAIL=you@example.org
EOF
```

`NCBI_EMAIL` is the contact address E-utilities asks callers to supply. Never commit this
file; `.gitignore` and the release tarball both exclude it. Pass it to a container with
`--env-file .ncbi.env`. *Next:* Step 6.

---

### Step 6 — Choose your input

**Option 1 — run a cohort that ships with PlasBench** (fastest honest start). Verify it first,
then select it by name at run time with `--cohort`:

```bash
plasbench validate-cohort --samples cohorts/public-v2.tsv \
  --verify-lock cohorts/public-v2.lock.json
plasbench run --cohort public-v2          # same as --samples cohorts/public-v2.tsv
```

*Expected:* `COHORT VALIDATION PASSED`. The lock file carries the NCBI evidence and the
sheet's SHA-256, so you are re-verifying a published panel rather than trusting it.

**Option 2 — build your own sheet.** Edit `config/accessions.tsv`, one isolate per row.
Required columns: `sample_id`, `assembly_accession`, `sra_run`, `organism`,
`truth_technology`, `truth_quality_tier`, `biosample`, `bioproject`. Optional but
valuable for stratification: `sample_origin`, `read_depth_x`, `source_study`,
`gram_group`, `collection_country`.

**What makes a row admissible is not a matter of taste** — see
[Appendix A](#appendix-a--selection-criteria-what-makes-a-sequence-eligible) for the nine
NCBI evidence checks and [Appendix B](#appendix-b--cohort-criteria-what-makes-a-set-of-sequences-a-cohort)
for the cohort-level rules. Verify before running:

```bash
plasbench validate-cohort --samples config/accessions.tsv --online \
  --write-lock config/accessions.lock.json
```

*Expected:* `COHORT VALIDATION PASSED: N samples (NCBI-linked pair verified)`, plus a lock
file. Any row that fails is reported with the specific reason.

**Option 3 — let PlasBench find candidates for you:**

```bash
plasbench discover-cohort ...     # search NCBI for matched assembly/paired-Illumina pairs
plasbench curate-cohort ...       # screen candidates -> accepted.tsv + rejected.tsv
plasbench review-candidates ...   # build a balanced, non-release shortlist
```

`curate-cohort` writes a `rejected.tsv` recording *why* each candidate was excluded — the
audit trail a released cohort needs. *Next:* Step 7.

---

### Step 7 — Configure the run

Either edit `config/config.sh` or pass flags to `plasbench run` (flags win).

| Setting | Flag | Default | Guidance |
|---|---|---|---|
| CPU threads | `--threads` | 4 | Set to your core count |
| Assembly memory cap (GB) | `--memory-gb` | 16 | Must exceed SPAdes' need or the assembly fails; high-depth isolates want 8–16 GB |
| Samples in parallel | `--parallel-samples` | 1 | Raise cautiously — each concurrent assembly needs its own memory budget |
| Tools in parallel | `--parallel-tools` | — | Cheaper to raise than parallel samples |
| Assembler | `--assembler` | `spades` | `unicycler` gives cleaner assembly graphs, which gplas2 modes need, but is slower |
| Tool toggles | `--mob-recon`, `--platon`, `--plasmidspades`, `--gplas2-mob`, `--gplas2-external` | on/on/on/off/off | Turn off anything you have not installed |
| Sample sheet | `--samples` | `config/accessions.tsv` | Point at a shipped cohort to use one |
| Output locations | `--data-dir`, `--results-dir`, `--log-dir` | `data/`, `results/`, `logs/` | Put `data/` on a fast disk with room |

*Next:* Step 8.

---

### Step 8 — Run the benchmark

```bash
plasbench run                                   # all stages, config defaults
plasbench run --samples cohorts/public-v2.tsv --threads 8 --memory-gb 16
plasbench run 5 6                               # re-score and re-aggregate only
plasbench run --cohort public-v2 --write-script run_public_v2.sh   # emit commands, run nothing
```

`--write-script` is the dry run: it writes out the exact commands the run would execute,
so you can read, edit or submit them to a scheduler instead of running them immediately.

Stages are numbered and can be run individually. What each does:

| Stage | Name | Input | Output | Cost (6 threads) |
|---|---|---|---|---|
| **0** | setup | `config/config.sh` | `[ok]` lines per tool and database | seconds |
| **1** | download | sample sheet, network, NCBI key | `reference.fna`, `sequence_report.jsonl`, `<run>_1/2.fastq.gz` per sample | 2–25 min/isolate |
| **2** | truth | reference + sequence report | `truth.tsv` — every reference sequence labelled plasmid or chromosome | seconds |
| **3** | assemble | reads | `contigs.fasta`, `assembly_graph.gfa`, `assembly_status.tsv` | 9–28 min/isolate |
| **4** | reconstruct | contigs (+ graph) | `pred_<tool>.plasmid.fasta`, `pred_<tool>.bins.tsv`, `tool_status.tsv` | 2–13 min per tool per isolate |
| **5** | score | predictions + truth | `scores.tsv`, `*.pred_vs_ref.paf`, per-sample visualisation data | seconds |
| **6** | aggregate | scores | leaderboard, stratified tables, paired tests, `benchmark.report.html` | seconds |
| **7** | long-read *(optional)* | `long_reads.fastq.gz` | Flye assembly + MOB-recon bins | varies |

**Stage 2 is the one to watch.** It prints, per sample, how many sequences it labelled and
how many were *defaulted* — for example `3 plasmid, 1 chromosome sequences (0 defaulted)`.
Defaulted sequences are ones the report could not resolve, which fall back conservatively
to "chromosome". **A non-zero count means your truth-set is quietly biased**; investigate
before trusting recall.

**Failures do not stop the run.** A sample whose assembly fails is recorded in
`results/assembly_status.tsv` as `failed` and stage 4 marks its tools `skipped`; a tool
that fails is recorded in `results/tool_status.tsv` and excluded from scoring. The run
aborts only if *no* sample assembles. Check both files before reading the leaderboard.

*Next:* Step 9.

---

### Step 9 — Read the results

```
results/
├── benchmark.leaderboard.md / .tsv        ranked tools, the headline result
├── benchmark.report.html                  interactive report — start here
├── scores.tsv                             per sample x tool confusion matrix and metrics
├── benchmark.stratified.tsv               per organism, country, plasmid size, depth, AMR
├── benchmark.paired_comparisons.tsv       Holm-corrected paired permutation tests
├── benchmark.recommendations.tsv          operational advice, or why it was withheld
├── benchmark.recommendation_validation.tsv  leave-one-study-out check
├── assembly_status.tsv / tool_status.tsv  what ran, what was reused, skipped or failed
├── run_manifest.json                      tool versions and image digest for provenance
└── <sample>/                              predictions, alignments, bin matches per tool
```

**How to read the leaderboard honestly.**

- **Mean F1** ranks tools on *plasmid bases* recovered. It is the headline, not the whole
  story.
- **Plasmid recall** is the fraction of *individual plasmids* recovered to the
  `PLASMID_RECOVERY_THRESHOLD` (default 0.90). In practice this runs far below base-level
  recall: in the reference pilot the leading tools recovered ~84% and ~75% of plasmid
  bases but only **46% of intact plasmids**, and one isolate scored F1 0.910 while
  recovering *none* of its single plasmid at threshold. If your question is "do I have
  this whole resistance plasmid?", **plasmid recall is the number that answers it.**
- **95% CI and the paired tests** tell you whether a gap is real. Two tools whose interval
  overlaps and whose Holm-corrected p is near 1.0 are not distinguishable at your sample
  size, however different their means look.
- **Stratified rows marked ineligible** (below `RECOMMENDATION_MIN_SAMPLES`, default 5)
  are signals to investigate, not findings.
- **A withheld recommendation is a working safety gate, not an error.** PlasBench refuses
  to issue operational advice without leave-one-study-out validation, which needs at least
  two independent `source_study` groups.

*Next:* Step 10, or stop here if a leaderboard was all you needed.

---

### Step 10 — Put the benchmark to work

A leaderboard is evidence; these turn it into practice.

```bash
# Conservative, evidence-gated recommendations from a completed run
plasbench select-candidates --scores results/scores.tsv \
  --samples config/accessions.tsv --results-dir results --out-prefix results/benchmark

# Choose a method for a NEW, unlabelled sample using only benchmarked evidence
plasbench select-unknown --sample new_isolate_01

# Reconstruct plasmids for one operational sample with the selected method only
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678

# How does recovery decay with sequencing depth?
plasbench depth-ladder --samples config/accessions.tsv --depths 20,40,60,80
plasbench depth-report

# Regenerate the leaderboard and HTML report without re-running anything
plasbench report --results-dir results
```

`reconstruct` is the operational endpoint: it runs **one** method — the one your own
benchmark selected — rather than every tool, which is what a surveillance laboratory
actually wants day to day.

---

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `datasets: command not found` | environment not activated | `conda activate plasbench` |
| `unzip: command not found` in stage 1 | incomplete environment | reinstall the environment; `plasbench check` now tests for it |
| SPAdes fails, log says *"needs approx N GB"* | read depth exceeds your memory cap | raise `--memory-gb`, lower `--parallel-samples`, or subsample the reads and record that you did |
| A tool row says `skipped — command unavailable` | enabled but not installed | `plasbench install-tools all`, or turn it off |
| `truth.tsv` reports defaulted sequences | sequence report could not classify a sequence | inspect that reference before trusting recall |
| Recommendations all withheld | fewer than two independent `source_study` groups | expand the cohort across studies; the leaderboard is still valid |
| Downloads stall or time out | slow or rate-limited connection | set an NCBI API key (Step 5); stages resume where they stopped |
| Container cannot see your files | missing bind mounts | mount `config/`, `data/`, `logs/`, `results/` and the Platon database as shown in §0 |


---

### Appendix A — Selection criteria: what makes a sequence eligible

Not every complete assembly with reads attached can be benchmarked against. A row is
admissible only if it can support an *honest* measurement, and every rule below is
machine-enforced by `plasbench validate-cohort --online`
(`python/validate_cohort.py`) — not left to the curator's judgement.

#### Sheet-level checks (offline, no network)

| Check | Rule |
|---|---|
| Required columns | `sample_id`, `assembly_accession`, `sra_run`, `organism`, `truth_technology`, `truth_quality_tier`, `biosample`, `bioproject` |
| `sample_id` | present and unique across the sheet |
| `assembly_accession` | matches `^GC[AF]_\d+\.\d+$` |
| `sra_run` | matches `^(SRR|ERR|DRR)\d+$` |
| `truth_technology` | one of `long_read`, `hybrid` |
| `truth_quality_tier` | one of `A`, `B`, `C` |
| `read_depth_x` | numeric and greater than zero when supplied |

#### Evidence checks (online, against NCBI)

Each is a rule about whether the isolate can serve as ground truth at all:

| # | Check | Why it exists |
|---|---|---|
| 1 | Assembly status is **Complete Genome** — in both the Assembly summary and the Datasets v2 assembly level | A draft reference has fragmented plasmids, so it cannot define what "complete" means |
| 2 | Assembly **declares plasmid replicons** | An isolate with no plasmids cannot measure recall — only precision. Recall needs something to find |
| 3 | `sequencing_tech` names an explicit **long-read platform** (`nanopore`, `ont`, `pacbio`, `smrt`, `minion`, `promethion`, `sequel`, `revio`) | Ground truth must come from data that can close a plasmid. A short-read-only reference would make the benchmark circular |
| 4 | Declared `truth_technology` **matches that evidence** | Stops a row claiming `hybrid` when NCBI shows no long-read platform |
| 5 | Assembly BioSample **and** SRA BioSample both equal the row's `biosample` | The reference and the reads must be the *same isolate*. Without this you are scoring one strain's reads against another strain's genome |
| 6 | Row's `bioproject` appears in the assembly's BioProjects **and** equals the run's BioProject | Shared provenance, not a coincidental accession pairing |
| 7 | SRA platform is **ILLUMINA** | The benchmark measures plasmid recovery from routine short reads; that is the input under test |
| 8 | SRA layout is **PAIRED** | Paired-end is what the assembly stage consumes |
| 9 | Declared tier **matches the evidence-derived tier** | A curator cannot label a row `A` that the evidence only supports as `B` |

Any failure is a rejection, not a warning. `plasbench curate-cohort` applies the same
rules to a candidate table and writes `accepted.tsv` alongside a `rejected.tsv` that
records the reason for every exclusion — the curation audit trail a released cohort
needs.

#### Practical constraint: read volume

Admissibility is not the whole story. Assembly memory scales with read count, not genome
size, so a very deep run can exceed the RAM available: a ~250x *Salmonella* isolate needs
about 7.8 GB for SPAdes k-mer counting alone. When choosing among eligible isolates,
check `read_depth_x` against your assembly budget, or subsample deliberately and record
that you did — a documented depth is a defensible benchmark input; a silent OOM is not.

### Appendix B — Cohort criteria: what makes a *set* of sequences a cohort

Individually valid rows do not automatically make a usable benchmark cohort.

**1. Evidence tier.** Every row carries a curation-confidence grade, derived from the
evidence rather than asserted:

- **A** — all evidence checks passed **and** `source_study` names a reviewed publication
  or collection. Release-ready.
- **B** — all evidence checks passed, but `source_study` is empty or still a placeholder
  (matching `pending`, `needs_`, `unverified`, `unknown`, `tbd`, `candidate`). Complete,
  but not curator-approved.
- **C** — not yet verified online. Running `--online` always resolves a row to A or B.

**2. Independent studies.** Tool *recommendations* — as opposed to a leaderboard — require
leave-one-study-out validation, which needs at least **two** distinct `source_study`
groups. A cohort drawn from a single study can still be benchmarked and ranked, but
PlasBench will withhold every operational recommendation with the reason
`independent-study validation unavailable`. This is deliberate: a ranking is a
measurement, a recommendation is advice, and advice needs evidence that it generalises
beyond one collection.

**3. Enough samples, and enough coverage of them.** `RECOMMENDATION_MIN_SAMPLES`
(default 5) and `RECOMMENDATION_MIN_COVERAGE` (default 0.80) gate whether a tool has
enough independent evidence in a stratum to be recommended within it. Strata below the
threshold are reported but marked ineligible.

**4. Deliberate diversity, because the metrics are stratified.** Leaderboards are broken
down by organism, Gram group, collection country, sample origin, truth technology,
plasmid size band, plasmid count band, read-depth band and AMR carriage. A cohort should
therefore spread across the axes you intend to draw conclusions about — and in
particular should include plasmid-carrying isolates deliberately, so recall is
measurable, and both Gram groups if Gram-positive performance matters to you. A stratum
of one isolate is a signal to investigate, not a result.

**5. Versioned and locked.** A released cohort ships as `cohorts/<name>.tsv` plus a
`<name>.lock.json` holding the retrieved NCBI evidence and the sheet's SHA-256. Anyone
can re-verify with:

```bash
plasbench validate-cohort --samples cohorts/public-v2.tsv --verify-lock cohorts/public-v2.lock.json
```

This makes a cohort citable: the panel, the evidence behind it, and the checksum that
ties them together all travel with the release. See `cohorts/README.md` and
`docs/COHORTS.md` for the curation workflow, and `docs/FINDING_DATA.md` for how to find
matched pairs in the first place.

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
`unmapped_pred_bp` rather than silently punished; sequence that maps only to a reference
contig absent from truth is reported separately again as `off_truth_pred_bp`. Full
rationale in `docs/METHODS.md`.

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
