# PlasBench

A reproducible, Ubuntu-first pipeline that **benchmarks how well plasmid-reconstruction
tools recover plasmids**, using complete (long-read) assemblies as ground truth.

**Read support:** the default workflow consumes paired-end short-read FASTQ files
(`*_1.fastq.gz`, `*_2.fastq.gz`), normally Illumina, and that is what a plain
`plasbench run` benchmarks. Long reads (ONT/PacBio) serve two distinct roles:

- **As ground truth** — the complete reference assembly every tool is scored
  against is itself long-read or hybrid. This is true on every run.
- **As a reconstruction input**, for tools that take long reads natively:
  `flye_mob_recon`, `hybracter_long` and `trycycler_mob_recon` (long reads
  alone), and `plassembler` and `hybracter_hybrid` (long + short). Each is
  off by default and switched on individually — see
  [§4.9](#49-long-read-and-hybrid-tools-and-the-circularity-constraint).

Those two roles cannot be filled by the same reads: a tool handed the reads its
own truth was built from is scored against its own input. PlasBench refuses that
by default, which is why the long-read track needs a cohort declaring
independence rather than just a flag. §4.9 covers it in full.

Results are never pooled across these input tracks. Aggregation writes one
leaderboard per track — short-read, long-read and hybrid — and the HTML report
ranks within each, so a tool given long reads is never ranked against one given
only short reads.

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

## 0. Which route do I take?

| You are… | Go to | You need |
|---|---|---|
| a laboratory that wants to run the benchmark | **[Section 3 — step by step](#3-step-by-step-from-a-new-machine-to-your-first-leaderboard)** | a Linux machine, or Windows with WSL2 |
| someone who would rather install nothing | [Container](#container) below | Docker only |
| modifying PlasBench, or citing exact source | [Source checkout](#source-checkout) below | git and conda |

**If you are not sure, use [Section 3](#3-step-by-step-from-a-new-machine-to-your-first-leaderboard).**
It writes out every command, from a machine with nothing installed to a finished
leaderboard, and assumes no prior experience with conda or bioinformatics tooling.

The short version of that route is:

```bash
curl -fL -O https://github.com/ubeffiong/plasbench/releases/download/v0.2.0/plasbench-0.2.0.tar.gz
tar -xzf plasbench-0.2.0.tar.gz
cd plasbench-0.2.0
./install.sh --tools
conda activate plasbench
plasbench test
```

…but there are databases and an NCBI key to set up as well, so follow Section 3 rather
than only these six lines.

---

### Container

The image carries every tool and the MOB-suite database already built in.

```bash
docker pull ghcr.io/ubeffiong/plasbench:latest
docker run --rm ghcr.io/ubeffiong/plasbench:latest plasbench demo
```

Or build it yourself from a release archive or a checkout:

```bash
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

**The Platon database is not bundled.** Mount one at `/work/data/db/platon/db`
(see [step 7a](#step-7--install-the-two-reference-databases) for how to obtain it), or
set `RUN_PLATON=0`. MOB-suite's database *is* baked into the published image; if you
build your own image without it, mob_recon downloads ~450 MB on first use, so mount a
persistent volume over its default directory to avoid re-fetching it on every run:

```bash
-v plasbench-mobsuite-db:/opt/conda/envs/mobsuite/lib/python3.10/site-packages/mob_suite/databases
```

For a run that records the image digest into `run_manifest.json`, use
`scripts/docker_run.sh` in place of plain `docker run`, with the same mounts.

---

### Source checkout

Use this only if you intend to modify PlasBench or cite an exact source state.

```bash
git clone https://github.com/ubeffiong/plasbench.git
cd plasbench
bash env/bootstrap_conda.sh      # installs a conda manager if you have none
bash env/setup_conda.sh          # creates the 'plasbench' environment
conda activate plasbench
python -m pip install --no-deps .
plasbench check --yes            # installs any missing tool or database
plasbench test && plasbench demo
```

`make dist` rebuilds the release archive into `dist/`.

---

### Where else to look

- **[Section 3](#3-step-by-step-from-a-new-machine-to-your-first-leaderboard)** — every
  command, from a bare machine to a leaderboard, with what to do when a step fails.
- **[Section 4](#4-cohort-studies--every-manipulation-end-to-end)** — running and
  building cohort studies, and every option available.
- `plasbench --help`, `plasbench run --help` — the full option list.
- `plasbench docs --topic outputs`, `plasbench docs --topic troubleshooting` — the same
  guide in the terminal.
- [`docs/CONCEPT_NOTE.md`](docs/CONCEPT_NOTE.md) or `plasbench concept-note` — a
  non-technical overview for partners and funders.

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

## 3. Step by step: from a new machine to your first leaderboard

**Every command on this page is complete. Copy and paste it exactly as written.**
Nothing here is a placeholder, and you never have to go and look something up
elsewhere. Each step says what you should see when it works, and what to do when it
does not.

Work through the steps in order. Steps 1–9 are done once per machine. Step 10 onwards
is what you repeat for each study.

### What the machine needs

| | Minimum | Comfortable | Why |
|---|---|---|---|
| CPU | 4 cores | 8–16 cores | Assembly and BLAST dominate the run |
| RAM | 8 GB | 16–32 GB | SPAdes scales with **read count**. A 250× isolate needed **7.8 GB** for k-mer counting alone and failed under a 7 GB cap |
| Free disk | 30 GB | 60–100 GB | ~630 MB per isolate, plus 2.9 GB MOB-suite and 2.7 GB Platon databases |
| Internet | required for steps 3, 7, 8, 10 | | Scoring itself is offline |

**Time.** Steps 1–9 take 1–3 hours, mostly downloading. After that, budget roughly
30–60 minutes per isolate. A 10-isolate cohort is an overnight job.

---

### Step 1 — Open the right terminal

**On Linux or macOS:** open Terminal. Nothing else to do; go to step 2.

**On Windows:** you need WSL2. PlasBench does not run in PowerShell or CMD.

Open **PowerShell as Administrator** (right-click the Start button → *Terminal
(Admin)*) and run:

```powershell
wsl --install
```

Restart the computer when it asks. After restarting, open the **Ubuntu** app from the
Start menu. It will ask you to create a username and password the first time — this is
a Linux account inside Windows, unrelated to your Windows password.

Check you are in the right place:

```bash
uname -s
```

It must print `Linux`. If it prints anything else you are still in PowerShell — open
the Ubuntu app instead.

**Every remaining command in this document goes in that Linux shell.**

---

### Step 2 — Install conda

First check whether you already have it:

```bash
conda --version
```

If that prints a version number (for example `conda 26.5.3`), skip to step 3.

If it says `command not found`, install Miniforge:

```bash
cd ~
curl -fL -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash "Miniforge3-$(uname)-$(uname -m).sh" -b
~/miniforge3/bin/conda init bash
exec bash
```

That downloads about 120 MB. The last line restarts your shell, so your prompt will
change to start with `(base)`.

Confirm it worked:

```bash
conda --version
```

This must now print a version number before you continue.

---

### Step 3 — Download PlasBench

```bash
cd ~
curl -fL -O https://github.com/ubeffiong/plasbench/releases/download/v0.2.0/plasbench-0.2.0.tar.gz
curl -fL -O https://github.com/ubeffiong/plasbench/releases/download/v0.2.0/plasbench-0.2.0.tar.gz.sha256
sha256sum -c plasbench-0.2.0.tar.gz.sha256
```

The last command must print exactly:

```
plasbench-0.2.0.tar.gz: OK
```

If instead you see `curl: (22) ... 404`, the version number in the URL is wrong — check
<https://github.com/ubeffiong/plasbench/releases> for the current one and substitute it
in all three commands.

If you see `sha256sum: ... no properly formatted checksum lines found`, the download
failed and left an error page in place of the file. Delete both files and run the three
commands again:

```bash
rm -f plasbench-0.2.0.tar.gz plasbench-0.2.0.tar.gz.sha256
```

Now unpack it:

```bash
tar -xzf plasbench-0.2.0.tar.gz
cd ~/plasbench-0.2.0
```

---

### Step 4 — Install PlasBench and the bioinformatics tools

```bash
./install.sh --tools
```

This is the long step: **30–90 minutes**, downloading roughly 1 GB of tools. It prints
numbered phases so you can tell waiting from stuck:

```
[plasbench-install] ===== step 2/4: conda environment 'plasbench' =====
[plasbench-install] ===== step 3/4: the plasbench command =====
[plasbench-install] ===== step 4/4: bioinformatics tools and databases =====
```

Long silent pauses during step 2/4 are normal — conda is solving dependencies.

**Do not press Ctrl+C.** Interrupting this can leave a half-built environment. If it
does get interrupted, delete the environment and start step 4 again:

```bash
conda env remove -n plasbench -y
./install.sh --tools
```

---

### Step 5 — Activate the environment

```bash
conda activate plasbench
plasbench --version
```

You should see your prompt change to start with `(plasbench)`, and the version print:

```
plasbench 0.2.0
```

**You must run `conda activate plasbench` in every new terminal window** before using
PlasBench. If `plasbench` ever says `command not found`, this is almost always why.

---

### Step 6 — Check it works, before downloading any data

These two commands need no internet and no databases. Run them now, because if they
fail, nothing later will be meaningful.

```bash
plasbench test
```

Must end with:

```
ALL PLASBENCH TESTS PASSED
```

```bash
plasbench demo
```

This runs a complete synthetic benchmark and writes a report. It ranks three fake tools
of known behaviour — one accurate, one that over-claims, one that under-claims — so you
can see the scoring separate those before trusting it on real data.

---

### Step 7 — Install the two reference databases

PlasBench needs a database for Platon and one for MOB-suite. Together they are about
5.6 GB on disk. Do both.

#### 7a — Platon database

```bash
mkdir -p ~/plasbench-0.2.0/data/db/platon
cd ~/plasbench-0.2.0/data/db/platon
curl -fL -C - --retry 10 --retry-all-errors -o db.tar.gz https://zenodo.org/records/4066768/files/db.tar.gz
```

That is a 1.69 GB download. **`-C -` means it resumes**: if it stops partway, run the
exact same `curl` command again and it continues from where it stopped rather than
starting over.

Check you got the whole file before unpacking it:

```bash
ls -l db.tar.gz
```

The size must be **1690687855**. If it is smaller, run the `curl` command again.

Then unpack:

```bash
tar -xzf db.tar.gz
rm -f db.tar.gz
ls ~/plasbench-0.2.0/data/db/platon/db | wc -l
```

The last command should print **31**.

#### 7b — MOB-suite database

```bash
cd ~/plasbench-0.2.0
bash env/download_mobsuite_db.sh
```

Answer `y` when it asks. This downloads about 450 MB and then spends roughly 10 minutes
building indexes and a taxonomy database. The taxonomy step prints counters rather than
a percentage and can sit still for minutes — that is normal, not a hang.

If it is already installed, the script tells you so and does nothing:

```
[ok]   MOB-suite DB already present at /home/you/miniforge3/envs/plasbench/lib/python3.11/site-packages/mob_suite/databases
```

**If this download keeps failing**, see step 7c. Do not keep retrying it: MOB-suite's
downloader cannot resume, so every attempt restarts from zero.

#### 7c — If a database download will not complete

On a slow or unreliable connection the MOB-suite download may never finish. Both
databases are ordinary data files with no absolute paths inside them, so a copy from
another machine works. If a colleague has a working PlasBench install, ask them for the
two directories and copy them in.

Find where the MOB-suite database belongs on **your** machine — this command prints the
exact path, you do not need to work it out:

```bash
conda activate plasbench
python3 -c 'import os,mob_suite; print(os.path.join(os.path.dirname(os.path.abspath(mob_suite.__file__)),"databases"))'
```

Copy their `databases` directory into the path it printed, then copy their Platon `db`
directory into `~/plasbench-0.2.0/data/db/platon/db`. Confirm both:

```bash
MOB_DB="$(python3 -c 'import os,mob_suite; print(os.path.join(os.path.dirname(os.path.abspath(mob_suite.__file__)),"databases"))')"
ls "$MOB_DB" | wc -l                                    # expect 31
ls ~/plasbench-0.2.0/data/db/platon/db | wc -l          # expect 31
```

---

### Step 8 — Give NCBI your email and API key

PlasBench downloads reference genomes and sequencing reads from NCBI. Without a key you
are limited to about 3 requests per second and large cohorts hit rate limits.

1. Create a free account at <https://account.ncbi.nlm.nih.gov/>
2. Sign in, click your username (top right), choose **Account settings**
3. Scroll to **API Key Management** and click to create a key
4. Copy the key

Now write it into a file PlasBench reads. Replace the two values with your own, but keep
everything else exactly as shown:

```bash
cd ~/plasbench-0.2.0
cat > .ncbi.env <<'EOF'
NCBI_API_KEY=paste_your_key_here
NCBI_EMAIL=your.email@example.org
EOF
chmod 600 .ncbi.env
```

Check it saved:

```bash
cat .ncbi.env
```

This file is ignored by Git and is never included in a release archive. Do not share it.

---

### Step 9 — Confirm the whole installation

```bash
cd ~/plasbench-0.2.0
plasbench check
```

Every line should read `[ok]`, ending with:

```
Core dependency check PASSED.
```

If it offers to install something you have already installed, answer **`N`** and tell us
— that means the check is not finding it where you put it.

**Your installation is now complete.** Everything above is done once per machine.

---

### Step 10 — Run your first benchmark

Start with `public-v1`: 10 isolates, the smallest shipped cohort. First confirm the
cohort has not been altered:

```bash
cd ~/plasbench-0.2.0
plasbench validate-cohort --samples cohorts/public-v1.tsv --verify-lock cohorts/public-v1.lock.json
```

Expect:

```
COHORT LOCK VERIFIED: 10 evidence record(s)
COHORT VALIDATION PASSED: 10 samples (schema verified)
```

Now run it. Set `--threads` to your core count and `--memory-gb` to a little under your
RAM:

```bash
plasbench run --cohort public-v1 --threads 4 --memory-gb 7
```

Before anything is downloaded it shows you what it is about to fetch, and waits:

```
About to download from NCBI:
  reference assemblies :   10  ~115.4 MB
  Illumina read sets   :   10  ~3.5 GB  (2.8 GB - 3.8 GB)
  ESTIMATED TOTAL      :       ~3.6 GB
Download these files now? [y/N]
```

Answer `y` to continue. Samples already on disk are excluded from that total, so
re-running shows only what is still missing. There is no prompt when the run is not
attached to a terminal (under `nohup`, in CI, in a container) or when you set
`DOWNLOAD_CONFIRM=0`. Budget roughly three times the download size on disk, for
assemblies, trimmed reads and tool output.

**This takes several hours** — roughly 30–60 minutes per isolate. It downloads about
6 GB. You can stop it with Ctrl+C and start it again later with the same command:
finished work is reused, so it picks up where it left off.

To leave it running after closing your terminal:

```bash
nohup plasbench run --cohort public-v1 --threads 4 --memory-gb 7 > ~/plasbench-run.log 2>&1 &
```

Then watch progress with:

```bash
tail -f ~/plasbench-run.log
```

Press Ctrl+C to stop watching — that stops the *watching*, not the run.

The run works through seven stages, printed as it goes:

```
>>>>> STAGE 0 : 00_setup.sh        checks tools
>>>>> STAGE 1 : 01_download.sh     downloads genomes and reads from NCBI
>>>>> STAGE 2 : 02_truth.sh        labels each reference sequence plasmid or chromosome
>>>>> STAGE 3 : 03_assemble.sh     assembles the short reads
>>>>> STAGE 4 : 04_run_tools.sh    runs each plasmid tool
>>>>> STAGE 5 : 05_score.sh        scores each tool against the truth
>>>>> STAGE 6 : 06_aggregate.sh    builds the leaderboard
```

It finishes with `############ DONE ############`.

**Watch stage 2.** It prints a line per isolate like
`3 plasmid, 1 chromosome sequences (0 defaulted)`. The number in brackets must be
**0**. Anything else means a reference sequence could not be classified and was assumed
to be chromosome, which quietly inflates the scores.

---

### Step 11 — Look at the results

```bash
cd ~/plasbench-0.2.0
cat results/benchmark.leaderboard.md
```

That is the ranking. To open the full interactive report, from **Windows** run:

```bash
explorer.exe "$(wslpath -w results/benchmark.report.html)"
```

On Linux with a desktop, use `xdg-open results/benchmark.report.html`.

Check nothing failed silently:

```bash
cut -f1,2,3 results/tool_status.tsv
cat results/assembly_status.tsv
```

Every tool should say `completed` or `reused`. `failed` or `skipped` means that tool
produced no result for that isolate and was left out of the scoring.

**How to read the leaderboard.** `mean_f1` ranks tools on plasmid *bases* recovered.
`mean_plasmid_recall` is the fraction of *whole plasmids* recovered. These are very
different numbers and the second is usually far lower. If your question is "do I have
this entire resistance plasmid?", read `mean_plasmid_recall`. Also read the confidence
interval: two tools whose intervals overlap are not distinguishable at this sample size,
however different their averages look.

---

### Step 12 — When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `plasbench: command not found` | Environment not active | `conda activate plasbench` |
| `conda: command not found` | Step 2 not done, or shell not restarted | Run step 2, then `exec bash` |
| `sha256sum: no properly formatted checksum lines found` | Download returned an error page | `rm` both files, redo step 3 |
| `curl: (22) ... 404` | Wrong version in the URL | Check the Releases page for the current version |
| `set: pipefail: invalid option name` | Archive from before v0.1.3 | Download v0.2.0 (step 3) |
| `sample-sheet checksum differs from verification lock` | Cohort file altered, or from before v0.1.3 | Download v0.2.0 |
| SPAdes: `needs approx N GB` | Isolate too deep for your RAM | Raise `--memory-gb`, or use `--parallel-samples 1` |
| `[MISS] Platon DB not found` | Step 7a incomplete | Redo step 7a; the `curl` resumes |
| `command unavailable` for a tool | Tool not installed | `plasbench install-tools all` |
| `0 defaulted` is not 0 in stage 2 | A reference sequence was not classified | Inspect that reference before trusting recall |
| Download stops partway, repeatedly | Connection drops on large transfers | Step 7c — copy the databases from another machine |

To see what PlasBench is doing in more detail, every stage writes a log:

```bash
ls ~/plasbench-0.2.0/logs/
```


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

## 4. Cohort studies — every manipulation, end to end

A *cohort* is the panel of isolates a benchmark is measured on. Everything about the
credibility of a leaderboard traces back to it: which isolates, on what evidence, spread
across which strata, and pinned so someone else can re-verify it. This section covers the
whole lifecycle — discover, screen, balance, validate, lock, run, stratify, extend — and
the manipulations available at each stage.

The rules a row and a set must satisfy are in
[Appendix A](#appendix-a--selection-criteria-what-makes-a-sequence-eligible) and
[Appendix B](#appendix-b--cohort-criteria-what-makes-a-set-of-sequences-a-cohort). This
section is the *how*.

---

### 4.1 Run a cohort that ships with PlasBench

The fastest honest start. Verify it against its lock, then run it by name:

```bash
plasbench validate-cohort --samples cohorts/public-v2.tsv \
                          --verify-lock cohorts/public-v2.lock.json
plasbench run --cohort public-v2
```

`--cohort NAME` is shorthand for `--samples cohorts/NAME.tsv`. Shipped panels:

| Cohort | Isolates | Character |
|---|---:|---|
| `public-v1` | 10 | Tier-A seed panel: clinical *E. coli* and *Salmonella*, reviewed studies |
| `public-v2` | 32 | Adds African isolates (Egypt, Nigeria, South Africa, Tanzania, Kenya) across five species and both Gram groups |

`--verify-lock` re-checks the sheet's SHA-256 and the stored NCBI evidence, so you are
re-verifying a published panel rather than trusting it. A mismatch is a hard failure.

---

### 4.2 Build a cohort of your own

Four commands, in the order you would normally use them.

#### Discover candidates from NCBI

```bash
plasbench discover-cohort \
    --organism "Klebsiella pneumoniae" \
    --organism "Escherichia coli" \
    --country Nigeria \
    --max-assemblies 200 \
    --out-dir candidates/
```

| Option | Effect |
|---|---|
| `--organism` | Scientific name; **repeat** for each taxon |
| `--country` | Require the deposited BioSample `geo_loc_name` to contain this string |
| `--max-assemblies` | Cap the NCBI search, so a broad query cannot run away |
| `--email`, `--api-key` | Sent to E-utilities; default to `NCBI_EMAIL`/`NCBI_API_KEY` |

Searches for complete assemblies with a matched paired-Illumina run. The output is
candidates, **not** a cohort — nothing is accepted yet.

#### Screen candidates strictly

```bash
plasbench curate-cohort --candidates candidates/accepted.tsv --out-dir curated/
```

Applies every rule in Appendix A and writes two files:

- `curated/accepted.tsv` — rows that passed, in cohort schema, tier already derived
- `curated/rejected.tsv` — every rejected row **with its reason**

The rejected table is the curation audit trail. Keep it: it is the evidence that a
released cohort was screened rather than assembled by hand.

#### Balance the shortlist

```bash
plasbench review-candidates --candidates curated/accepted.tsv --out-dir shortlist/ \
    --max-per-bioproject 3 \
    --max-per-organism 8
```

Caps how much of the panel any single BioProject or organism can occupy. Without this a
search returns whatever a few large depositors happened to submit, and a leaderboard then
measures those studies rather than the tools. It writes three files into `shortlist/`:

- `balanced_shortlist.pending_review.tsv` — the capped shortlist, for you to review
- `candidates.enriched.tsv` — every candidate with the metadata used to balance them
- `study_dependence.tsv` — how many candidates each BioProject contributed

This is an **additive, non-release** shortlist, not a finished cohort. Copy the rows you
want into `cohorts/my-cohort.tsv` yourself, then validate and lock it below.

#### Validate and lock

```bash
plasbench validate-cohort --samples cohorts/my-cohort.tsv --online \
                          --write-lock cohorts/my-cohort.lock.json
```

| Option | Effect |
|---|---|
| *(none)* | Schema only: columns, accession formats, allowed tier and technology values |
| `--online` | Also verify against NCBI: assembly level, plasmid replicons, long-read evidence, BioSample/BioProject linkage, Illumina, paired |
| `--write-lock` | Record the retrieved evidence plus the sheet's SHA-256 (requires `--online`) |
| `--verify-lock` | Re-check an existing lock; fails if the sheet changed |
| `--email`, `--api-key` | E-utilities contact and key |

> **Generate the lock on the platform you release from.** The lock pins the SHA-256 of the
> sheet's bytes. A sheet checked out with CRLF line endings hashes differently from the LF
> copy Git stores, so a lock written on Windows fails on Linux with *"sample-sheet checksum
> differs from verification lock"*. `.gitattributes` forces LF for `*.tsv` and `*.json`
> precisely to keep this stable.

---

### 4.3 Run the study

```bash
plasbench run --cohort my-cohort                      # everything
plasbench run --cohort my-cohort --threads 8 --memory-gb 16
plasbench run 5 6 --cohort my-cohort                  # re-score and re-aggregate only
plasbench run --cohort my-cohort --write-script run.sh   # emit commands, run nothing
```

Manipulations worth knowing:

| Goal | How |
|---|---|
| Compare a different tool set | `--mob-recon on --platon on --plasmidspades off` |
| Change the assembler for everyone | `--assembler unicycler` (required for gplas2 modes) |
| Re-run one tool after upgrading it | `--force-rerun-tools` |
| Work offline from pre-staged reads | `--local-inputs` |
| Restrict scoring to one track only | `--analysis-track long_read` (or `hybrid`); not needed for a normal mixed run |
| Put outputs somewhere else | `--data-dir`, `--results-dir`, `--log-dir` |
| Use a Platon database elsewhere | `--platon-db ~/plasbench-0.2.0/data/db/platon/db` |
| Run more samples at once | `--parallel-samples N` — each concurrent assembly needs its own memory budget |
| Run more tools at once | `--parallel-tools N` — cheaper to raise than parallel samples |
| Inspect before committing | `--write-script run.sh`, then read or edit it |

Stages are numbered `0`–`7`; pass the ones you want. Re-running is safe: completed work is
reused, and a sample that fails is recorded and skipped rather than aborting the cohort.

---

### 4.4 Read the study, including the strata

Beyond `benchmark.leaderboard.tsv`:

```
benchmark.stratified.tsv            per-stratum leaderboards
benchmark.paired_comparisons.tsv    Holm-corrected paired permutation tests
benchmark.recommendations.tsv       operational advice, or the reason it was withheld
benchmark.recommendation_validation.tsv   leave-one-study-out check
```

Stratification axes, all derived from the cohort sheet — which is why the optional columns
are worth filling in:

| Axis | Column |
|---|---|
| organism | `organism` |
| Gram group | `gram_group` |
| collection country | `collection_country` |
| sample origin | `sample_origin` |
| truth technology | `truth_technology` |
| plasmid size band | derived from the truth labels |
| plasmid count band | derived from the truth labels |
| read-depth band | `read_depth_x` |
| AMR carriage | derived from annotation |

A stratum below `RECOMMENDATION_MIN_SAMPLES` (default 5) is reported but marked
**ineligible** — a signal to investigate, not a finding.

Regenerate the leaderboard and HTML report from existing scores without re-running
anything:

```bash
plasbench report --results-dir results
```

---

### 4.5 Recommendations, and why they are usually withheld

```bash
plasbench select-candidates --scores results/scores.tsv \
                            --samples cohorts/my-cohort.tsv \
                            --results-dir results \
                            --out-prefix results/benchmark \
                            --tool-status results/tool_status.tsv \
                            --min-samples 5 \
                            --min-coverage 0.80 \
                            --analysis-track short_read
```

A ranking is a measurement; a recommendation is advice, and advice has to generalise.
PlasBench withholds one unless leave-one-study-out validation can run, which needs at
least **two independent `source_study` groups**. A single-study cohort still produces a
valid leaderboard, and `benchmark.recommendations.tsv` will say
`independent-study validation unavailable` rather than guessing.

`--min-samples` and `--min-coverage` loosen or tighten the evidence gate. Loosening them
for a small cohort is a choice you should be able to defend in a methods section.

---

### 4.6 Apply the study to a new isolate

```bash
# Which method does the benchmark support for this kind of sample?
plasbench select-unknown --sample-id new_isolate_01 \
                         --organism "Klebsiella pneumoniae" \
                         --gram-group Gram-negative \
                         --recommendations results/benchmark.recommendations.tsv

# Reconstruct with that one method -- not every benchmarked tool
plasbench reconstruct --sample new_isolate_01 --sra SRR12345678 \
                      --recommendations results/benchmark.recommendations.tsv
```

`reconstruct` is the operational endpoint: a surveillance laboratory wants one method,
chosen on evidence, not a bake-off on every sample. Override the choice with
`--tool mob_recon` when you need to.

---

### 4.7 Depth-sweep: how far can you cut sequencing?

```bash
plasbench depth-ladder --samples cohorts/my-cohort.tsv \
                       --data-dir data --out-dir depth/ \
                       --depths 20,40,60,80,120 --seed 42
plasbench run --samples depth/depth_ladder.samples.tsv --local-inputs
plasbench depth-report --scores results/scores.tsv \
                       --manifest depth/depth_ladder.manifest.tsv \
                       --out-prefix results/depth --metric plasmid_recall
```

Deterministic subsampling (fixed `--seed`) to each target depth, then the same benchmark
at every level. `--metric` chooses what the SVG plots — `plasmid_recall` is usually the
one that matters, since it answers "how deep must I sequence to recover whole plasmids?"
rather than "how deep to recover most plasmid bases?".

Aggregation knows subsamples of one isolate are correlated and does not treat them as
independent evidence.

---

### 4.8 Extending and releasing a cohort

Adding an isolate is one row plus re-validation:

```bash
# append the row, then:
plasbench validate-cohort --samples cohorts/my-cohort.tsv --online \
                          --write-lock cohorts/my-cohort.lock.json
plasbench run --cohort my-cohort        # only the new isolate is processed
```

Everything already computed is reused, so growing a cohort costs only the new isolates.

To release one, ship `cohorts/<name>.tsv` and `<name>.lock.json` together, and cite the
version used. Anyone can then re-verify the panel, the evidence behind it, and the
checksum tying them together with a single `--verify-lock`.

---


### 4.9 Long-read and hybrid tools, and the circularity constraint

Five tools reconstruct from **long reads**, optionally plus short reads, and
none is on by default: `flye_mob_recon` and `trycycler_mob_recon`
(long-read-only; two independent assembler paths, since assembler choice
materially affects plasmid completeness on ONT data), `plassembler` and
`hybracter_hybrid` (hybrid: long + short reads), and `hybracter_long`
(long-read-only, Hybracter's own assembler). All five need one thing the
short-read tools do not: a cohort where the long reads are not the reads the
truth came from.

**Install and run any combination:**

```bash
plasbench install-tools long-read      # flye_mob_recon
plasbench install-tools trycycler      # trycycler_mob_recon
plasbench install-tools plassembler; bash env/download_plassembler_db.sh   # plassembler
plasbench install-tools hybracter      # hybracter_long, hybracter_hybrid (reuses the Plassembler DB)

# Stage the long reads for each sample as data/<sample>/long_reads.fastq.gz
# (stage 1 already downloaded the short reads), then run any combination:
plasbench run --cohort my-cohort --plassembler on --hybracter-long on
```

That produces `results/benchmark.long_read.leaderboard.tsv` and/or
`.hybrid.leaderboard.tsv` (each tool's track comes from
`config/tool_capabilities.tsv`, never a flag you have to remember to pass).
Stage 7 is part of the default stage list, so one invocation scores every
enabled tool -- long-read, hybrid, and short-read -- in the same pass, and
aggregation writes one leaderboard per track and never mixes them, so a
long-read or hybrid tool is never ranked against a short-read-only one.
Nothing about `plasbench run --cohort public-v2` changes if you enable none
of these: the short-read benchmark is exactly what it was.

**The constraint.** PlasBench's truth labels come from a complete long-read or
hybrid assembly. Give one of these tools the same long reads that produced
that assembly and you are scoring it against its own input: it will look
near-perfect for reasons that say nothing about the tool. Short-read tools
have no such exposure, which is why this never came up for them.

So a sample is only eligible when the cohort says so explicitly:

```
sample_id  assembly_accession  sra_run  ...  truth_independent_of_long_reads
s1         GCF_...             SRR...   ...  yes
```

Anything else — column absent, value empty, `no` — is skipped and recorded as
`circular truth: truth_technology=<X> derives from the supplied long reads`.

Each tool has its own override variable
(`FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH`, `PLASSEMBLER_ALLOW_CIRCULAR_TRUTH`,
`HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH`, `HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH`,
`TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH`) that overrides this for every
sample and stamps each affected row in `tool_status.tsv`, so a compromised
result cannot later be mistaken for an independent one. Use it for
exploration, not for a published number.

Building an eligible cohort is a real piece of work, not a flag. See
[`docs/FINDING_DATA.md`](docs/FINDING_DATA.md) for concrete sourcing patterns
(orthogonal-technology truth, optical-mapping-confirmed assemblies, held-out
long reads, multi-run BioProjects) and [`docs/METHODS.md`](docs/METHODS.md)
for what each costs you in review.

Long-read plasmid recovery is at least as sensitive to read length and
quality (R9 vs R10 chemistry) as to depth. To measure that, use the
read-quality ladder in [4.10](#410-read-lengthquality-sweep-the-long-read-analog-of-the-depth-ladder)
below — the long-read analog of the depth sweep in
[4.7](#47-depth-sweep-how-far-can-you-cut-sequencing).

---

### 4.10 Read-length/quality sweep: the long-read analog of the depth ladder

On ONT data, plasmid recovery is at least as sensitive to **read length and
quality** (R9 vs R10 chemistry) as it is to depth. The depth ladder in
[4.7](#47-depth-sweep-how-far-can-you-cut-sequencing) cannot answer that: it
subsamples reads at random, which changes how many reads you have, not how good
they are. The read-quality ladder filters instead, with `filtlong`.

```bash
plasbench install-tools long-read      # brings flye + filtlong, if you have not already

plasbench read-quality-ladder --samples cohorts/my-cohort.tsv \
                              --data-dir data --out-dir read-quality/ \
                              --rungs 1000:8,5000:10,20000:15

plasbench run --samples read-quality/read_quality_ladder.samples.tsv \
              --data-dir read-quality/data --results-dir read-quality/results \
              --local-inputs --flye-mob-recon on

plasbench read-quality-report --scores read-quality/results/scores.tsv \
                              --manifest read-quality/read_quality_ladder.manifest.tsv \
                              --out-prefix read-quality/results/read_quality \
                              --metric plasmid_recall
```

**`--rungs` is a list of `MIN_LENGTH:MIN_MEAN_Q` pairs, one derived cohort per
rung.** They are *combined* cutoffs, not two independent axes — `5000:10` means
"reads at least 5 kb long **and** of mean quality at least 10". The default
`1000:8,5000:10,20000:15` is a rough "raw ONT / R9-typical / R10-typical"
progression. Pick your own rungs to match the chemistries you are deciding
between.

There is no `--seed` here, and that is not an omission: `filtlong` applies
absolute thresholds rather than sampling, so every rung is already
deterministic. That is the one real difference from the depth ladder, which
needs a seed because it samples.

**A strict rung can legitimately filter out everything.** Rather than hand you
a cohort that scores zero for a reason that has nothing to do with the tool,
the ladder stops with an error naming the sample and the rung that emptied it,
so you can loosen that rung or drop that sample. The floor is one surviving
read by default; to demand a realistic minimum, call the script directly, which
also exposes the `filtlong` binary path:

```bash
python3 python/make_read_quality_ladder.py --samples cohorts/my-cohort.tsv \
        --data-dir data --out-dir read-quality/ --rungs 5000:10,20000:15 \
        --min-retained-reads 500
```

This ladder is for the long-read and hybrid tools (`flye_mob_recon`,
`plassembler`, `hybracter_long`, `hybracter_hybrid`, `trycycler_mob_recon`) —
run it with those switched on, as above. Running it against the short-read
tools measures nothing, since they never read the long-read file the ladder
filters. Everything in [4.9](#49-long-read-and-hybrid-tools-and-the-circularity-constraint)
still applies: the derived cohort inherits its parent's
`truth_independent_of_long_reads`, so if the parent was ineligible every rung
is skipped too.

Like the depth ladder, aggregation knows the rungs of one isolate are
correlated and does not count them as independent evidence.

---

### 4.11 ML classifiers, and reading a precision–recall curve

Three machine-learning tools sit alongside the classical short-read ones, all
off by default and independently switchable:

| Tool | What it is | Input |
|---|---|---|
| `genomad` | Gene-based neural classifier | assembly contigs |
| `plasme` | Alignment + transformer hybrid | assembly contigs |
| `plasgraph2` | Graph neural network over assembly-graph nodes | assembly graph |

**geNomad installs from bioconda; the other two do not** — PLASMe and plASgraph2
are git checkouts with their own environments, so `plasbench install-tools`
prints the exact commands instead of attempting an install that would fail:

```bash
plasbench install-tools genomad; bash env/download_genomad_db.sh
plasbench run --cohort my-cohort --genomad on

plasbench install-tools plasme          # prints the git clone + conda steps
bash env/download_plasme_db.sh          # ~12.4 GB
plasbench run --cohort my-cohort --plasme on

plasbench install-tools plasgraph2      # prints the git clone + pip steps
plasbench run --cohort my-cohort --plasgraph2 on \
              --plasgraph2-model-dir /path/to/plASgraph2/model/ESKAPEE_model
```

All three are short-read-track tools, so they appear in
`benchmark.short_read.leaderboard.tsv` next to MOB-Recon and Platon and are
ranked on the same `mean_f1`. All three are contig **classifiers**, not
binners: they say "this contig is plasmid", never "these three contigs are one
plasmid". The report labels their bin diagnostics *not applicable* rather than
inventing a bin score — see [`adapters/REGISTRY.md`](adapters/REGISTRY.md).

**What is genuinely new: PR-AUC.** A classical tool gives one hard answer. An
ML tool scores *every* contig it looked at and then applies a threshold, so it
has a whole curve of possible answers, and the single F1 you see is just the
one point its default threshold happens to land on. Where a tool exposes those
per-contig probabilities, PlasBench sweeps every one of them as a threshold and
reports the area under the resulting precision–recall curve:

```bash
cut -f1,2,3,4,5 results/scores.tsv | head    # per sample+tool, now incl. pr_auc
grep pr_auc results/benchmark.leaderboard.tsv
```

- `mean_pr_auc` and `n_pr_scored` appear in the leaderboard, and the HTML report
  draws the curve itself on each per-sample view.
- Tools without probabilities show **`not probability-scored`**, not a zero.
  Nothing is penalised for being a hard-call tool.
- **Ranking is still `mean_f1`.** PR-AUC is a supplementary column, because it
  only exists for some tools and comparing it against tools that have none
  would not be a like-for-like ranking.

Read it as *"how good could this tool be if I tuned its threshold?"* against
F1's *"how good is it out of the box?"*. A tool with mediocre F1 but high PR-AUC
is one whose default threshold is wrong for your data, not one that cannot find
your plasmids — and that is an actionable difference.

The mechanism is an adapter contract, documented in
[`adapters/SCORES.md`](adapters/SCORES.md): an adapter may additionally write
`pred_<tool>.candidates.fasta` (every contig the tool scored, not just the ones
it called plasmid) and `pred_<tool>.scores.tsv` (`record_id`, `probability`).
When both exist, the curve is computed; when they do not, the tool is scored
exactly as before. `pred_<tool>.plasmid.fasta` keeps its meaning — the tool's
actual hard call — so adding a curve never moves the F1 that was already
there.

---

## 5. Running PlasBench on your own FASTQ files

Everything so far downloads isolates from NCBI. This section is for benchmarking
**your own sequencing data**. Every command is complete; copy it as written.

### 5.1 Two modes — pick one first

**Benchmarking** scores tools, so it needs a known answer. FASTQ alone is not
enough: PlasBench has to be told which sequences really are plasmids, or there is
nothing to be right or wrong about. Per isolate you supply **four** files.

**Operational reconstruction** just recovers plasmids from a new isolate and
scores nothing. That needs only the two FASTQ files — see
[§5.9](#59-operational-mode-reconstruct-without-scoring).

| File | What it is |
|---|---|
| `<prefix>_1.fastq.gz` | your forward reads |
| `<prefix>_2.fastq.gz` | your reverse reads |
| `reference.fna` | the **complete** assembly of that same isolate — the ground truth |
| `truth.tsv` | which sequences in it are plasmid and which are chromosome |

Reads must be **paired and gzipped**. Single-end input is rejected. `<prefix>` is
any name you choose.

---

### 5.2 The easy way: `plasbench init-local`

One command puts the files where they belong, writes the truth table, and adds
the sample-sheet row:

```bash
conda activate plasbench
cd ~/plasbench-0.2.0

plasbench init-local \
    --sample my_isolate \
    --reads-1 /path/to/your_R1.fastq.gz \
    --reads-2 /path/to/your_R2.fastq.gz \
    --reference /path/to/your_assembly.fasta
```

It prints what it did:

```
reads      -> data/my_isolate/my_isolate_1.fastq.gz , my_isolate_2.fastq.gz
reference  -> data/my_isolate/reference.fna
truth      -> data/my_isolate/truth.tsv (3 sequence(s), 1 needing review)
created config/local.tsv with one row
```

**Molecule types are filled in from your FASTA headers where they say so.** A
header reading `... chromosome, complete genome` becomes `CHROMOSOME`; one reading
`... plasmid pABC, complete sequence` becomes `PLASMID`. Anything else is written
as `REVIEW` and you are told:

```
ACTION REQUIRED: 1 sequence(s) in data/my_isolate/truth.tsv say REVIEW.
Their FASTA headers did not state whether they are plasmid or chromosome, and
PlasBench will not guess -- that is the ground truth every score depends on.
```

That refusal is deliberate. Guessing from length would be easy and wrong: small
chromosomal contigs and large plasmids overlap, and a wrong label does not cause
an error, it silently changes every number in the leaderboard.

Open the file and replace each `REVIEW`:

```bash
nano data/my_isolate/truth.tsv
```

Useful options:

| Option | Use |
|---|---|
| `--prefix NAME` | Read filename prefix (default: the sample id) |
| `--link symlink` | Link instead of copying — no second copy of large FASTQ files |
| `--sequence-report FILE` | Supply NCBI's `sequence_report.jsonl` and no truth table is written by hand at all |
| `--samples PATH` | Sheet to create or append to (default `config/local.tsv`) |
| `--data-dir PATH` | Where sample directories live (default `data`) |
| `--force` | Overwrite an existing `truth.tsv` |

Run it once per isolate; rows accumulate in the same sheet.

---

### 5.3 Or do it by hand

**Make the folders.** `my_isolate` becomes a directory name, so use letters,
digits, dot, dash, underscore only:

```bash
cd ~/plasbench-0.2.0
mkdir -p data/my_isolate config
```

**Copy the files in.** The `_1`/`_2` suffixes and the name `reference.fna` are
required exactly as written:

```bash
cp /path/to/your_R1.fastq.gz    data/my_isolate/myreads_1.fastq.gz
cp /path/to/your_R2.fastq.gz    data/my_isolate/myreads_2.fastq.gz
cp /path/to/your_assembly.fasta data/my_isolate/reference.fna
```

**List your sequence names:**

```bash
grep '^>' data/my_isolate/reference.fna
```

**Write the truth table** using exactly those names:

```bash
cat > data/my_isolate/truth.tsv <<'EOF'
sequence_id	molecule_type	length
chr1	CHROMOSOME	5012345
pA	PLASMID	91234
EOF
```

Three **tab**-separated columns. `sequence_id` is the first word of the FASTA
header, without `>`, and is case-sensitive. Only `PLASMID` and `CHROMOSOME` are
recognised.

If your assembly came from NCBI, drop its `sequence_report.jsonl` into the sample
directory instead and skip this step entirely — PlasBench builds the table itself.

**Write the sample sheet:**

```bash
cat > config/local.tsv <<'EOF'
sample_id	assembly_accession	sra_run
my_isolate	LOCAL	myreads
EOF
```

`sample_id` is your folder name. `assembly_accession` can be anything non-empty
(`LOCAL`) because nothing is downloaded. `sra_run` is your read prefix **without**
`_1.fastq.gz`.

---

### 5.4 Everything is checked before the run starts

`plasbench run --local-inputs` validates all of it up front and stops if anything
is wrong — nothing is downloaded, assembled or scored until the inputs are sound.
It checks, per isolate:

- both read files exist, are non-empty, and are **really** gzipped (a `.gz` name
  is not proof), and are not the same file twice
- `reference.fna` exists, is non-empty, has FASTA records, and has no duplicate
  sequence ids
- a truth table or `sequence_report.jsonl` exists
- every truth id exists in the reference, every reference sequence appears in the
  truth table, molecule types are `PLASMID` or `CHROMOSOME`, and no `REVIEW`
  placeholder remains

Failures name the file, say what is wrong, and give the command that fixes it:

```
LOCAL INPUTS NOT USABLE -- 2 problem(s) found before anything was run:

  - [my_isolate] myreads_1.fastq.gz is not gzipped, despite the .gz name.
      Compress it:  gzip -c myreads_1.fastq.gz > myreads_1.fastq.gz.tmp && mv ...
  - [my_isolate] no truth.tsv and no sequence_report.jsonl
      PlasBench needs to know which of these sequences are plasmids:
        NZ_CP01.1
        NZ_CP02.1
      Generate a template you then edit:
      plasbench init-local --sample my_isolate ... --force
```

### 5.5 Checking by hand, before you run

Every mistake in a truth table is silent. A mistyped id becomes a plasmid no tool
recovered; an omitted sequence lets chromosomal contamination go uncounted; an
unrecognised label is scored as chromosome. None of them raise an error on their
own — they just change the result.

Check it in a second:

```bash
python3 python/validate_truth_table.py \
    --truth data/my_isolate/truth.tsv \
    --reference data/my_isolate/reference.fna \
    --check-lengths
```

```
truth table verified: 3 sequence(s), 2 plasmid, 1 chromosome
```

`plasbench run` performs this check itself in stage 2 and refuses to continue if
it fails, so a bad table costs you seconds rather than a night of compute.

---

### 5.6 Run it

```bash
conda activate plasbench
cd ~/plasbench-0.2.0

REQUIRE_CURATED_METADATA=0 plasbench run \
    --samples config/local.tsv \
    --local-inputs \
    --threads 4 \
    --memory-gb 7
```

**`REQUIRE_CURATED_METADATA=0` is not optional.** By default a sheet must carry
eight columns including `biosample` and `bioproject`, which you will not have for
an in-house isolate. Without it you get `uncurated sample-sheet row 2` and nothing
runs.

**`--local-inputs` means never contact NCBI.** A missing file becomes an error
naming the exact path, instead of an attempted download.

Set `--memory-gb` to a little under your available RAM, and `--threads` to your
core count.

---

### 5.7 Results

```bash
cat results/benchmark.leaderboard.md
cut -f1,2,3 results/tool_status.tsv
```

Check that stage 2 reported `(0 defaulted)` for each isolate. A non-zero count
means a reference sequence was not classified and was assumed to be chromosome.

---

### 5.8 More isolates

Once per isolate:

```bash
plasbench init-local --sample isolate_two \
    --reads-1 /path/to/two_R1.fastq.gz \
    --reads-2 /path/to/two_R2.fastq.gz \
    --reference /path/to/two_assembly.fasta
```

Or by hand — one directory and one sheet row each:

```
data/isolate_two/reads2_1.fastq.gz
data/isolate_two/reads2_2.fastq.gz
data/isolate_two/reference.fna
data/isolate_two/truth.tsv
```

```
isolate_two	LOCAL	reads2
```

A leaderboard over few isolates has wide confidence intervals. Read
[§3, step 11](#step-11--look-at-the-results) on interpreting them before drawing
conclusions from two or three samples.

---

### 5.9 Operational mode: reconstruct without scoring

To recover plasmids from a new isolate with no ground truth, leave
`assembly_accession` empty. The pipeline skips the reference and truth entirely
and you supply only the two FASTQ files:

```
sample_id	assembly_accession	sra_run
new_isolate		newreads
```

Better still, use the dedicated command, which runs only the method your own
benchmark selected rather than every tool:

```bash
plasbench reconstruct --sample new_isolate --sra SRR12345678
```

---

### 5.10 Mixing your isolates with a public cohort

Keep them in separate sheets and run them separately. A cohort sheet carries
curation metadata and a verification lock; a local sheet does not, and
`REQUIRE_CURATED_METADATA=0` would switch that checking off for the public rows
too. Two runs into two `--results-dir` directories keeps both honest.

---

## 6. Contributing

Contributions are welcome — bug reports, cohort additions, new tool adapters,
documentation fixes. This section says how, and what happens to your
contribution once you send it.

**Maintainer:** [@ubeffiong](https://github.com/ubeffiong). All pull requests are
reviewed and merged by the maintainer; `main` is protected and cannot be pushed
to directly, and `CODEOWNERS` requires that review even from a collaborator who
has write access.

**One reviewer is a known constraint, stated plainly rather than left for you to
discover.** Review is deliberately centralised while the benchmark's claims are
still being established — a change that quietly moves a leaderboard number is
worse than a slow merge. The cost is real: if the maintainer is unavailable,
nothing merges, and that matters more as the surface grows (this project now
carries adapters for a dozen tools across three analysis tracks and two scoring
axes). Two things follow for you as a contributor:

- **Expect review to take time, and design for it.** Small, self-contained pull
  requests with a test move faster than large ones. [§6.2](#62-suggesting-a-change-before-writing-it)
  exists so you do not write a large change before that conversation happens.
- **The test suite is the safety net that does not depend on a person.** It
  runs offline in a few minutes and every regression it catches is one that does
  not need a reviewer to notice. If you are adding behaviour, the test matters
  as much as the code.

Additional maintainers will be added as the project's contributor base grows;
if you are using PlasBench seriously and want to help carry that, open an issue
saying so.

---

### 6.1 Reporting a problem

Open an issue: <https://github.com/ubeffiong/plasbench/issues>

A benchmark result depends on the machine it ran on, so please include:

```bash
plasbench --version
conda list --export | grep -E "spades|mob_suite|platon|minimap2"
uname -a && free -g | head -2
```

…plus what you ran, what happened, and what you expected. If a stage failed,
`logs/<sample>.<stage>.log` holds the tool's own output and is usually the
fastest route to the cause.

**For a wrong or surprising *score*, include the cohort and the truth table.**
A score that looks wrong is far more often a truth-table problem than a scoring
bug, and `results/scores.tsv` plus `data/<sample>/truth.tsv` let that be settled
in minutes.

---

### 6.2 Suggesting a change before writing it

For anything larger than a fix, open an issue first and describe the change. That
is not a formality — a new tool adapter or cohort has design consequences
(analysis tracks, circularity, evidence tiers) that are much cheaper to discuss
before the code exists than after.

Particularly worth discussing first:

- a new benchmarked tool, especially one that is not short-read-only
- changes to the scoring metric or to what counts as ground truth
- new cohorts, or changes to an existing cohort's composition
- anything that changes an existing leaderboard number

---

### 6.3 Sending a pull request

```bash
# 1. Fork on GitHub, then clone your fork
git clone https://github.com/<your-username>/plasbench.git
cd plasbench

# 2. Branch
git checkout -b fix-truth-table-parsing

# 3. Set up the environment
./install.sh --tools
conda activate plasbench

# 4. Make your change, then run the full suite
bash test/run_tests.sh

# 5. Commit and push
git commit -am "fix(truth): reject a sequence id that is not in the reference"
git push origin fix-truth-table-parsing

# 6. Open the pull request against ubeffiong/plasbench, branch main
```

**The test suite must pass.** It runs entirely offline, needs no bioinformatics
tools for most modules, and takes a few minutes:

```
ALL PLASBENCH TESTS PASSED
```

**New behaviour needs a test.** Look at `test/` for the pattern: each file drives
a real script with stubbed binaries and asserts on observable output. The tests
that matter most are the ones covering things that fail *silently* — a wrong
truth label, a skipped sample, a tool that produced no output — because those
change results without raising an error.

**Line endings matter.** `.gitattributes` forces LF for `*.sh`, `*.tsv` and
`*.json`. A shell script committed with CRLF fails on Linux with
`set: pipefail: invalid option name`, and a cohort TSV with CRLF breaks the
SHA-256 its lock pins.

---

### 6.4 What the review will look at

- **Does it change any existing leaderboard number?** If so, say which and why in
  the PR description. That is not disqualifying, but it must be deliberate and
  explained.
- **Does it fail loudly?** A change that makes a bad input produce a wrong number
  instead of an error will be sent back, however convenient the behaviour.
- **Is ground truth still independent of the tools being scored?** Nothing may
  derive a truth label from the output of a tool under evaluation.
- **Does the test suite still pass, and is the new behaviour tested?**
- **Does the documentation match?** If you change a command's arguments or
  outputs, update the README section that documents it.

---

### 6.5 Contributing a cohort

Cohorts carry a higher bar than code, because every leaderboard built on one
inherits its problems. See
[§4.2](#42-build-a-cohort-of-your-own) for the tooling and
[Appendix A](#appendix-a--selection-criteria-what-makes-a-sequence-eligible) /
[Appendix B](#appendix-b--cohort-criteria-what-makes-a-set-of-sequences-a-cohort)
for the rules. A cohort PR should include:

- the sheet (`cohorts/<name>.tsv`) and its lock (`cohorts/<name>.lock.json`),
  generated with `--online --write-lock` on a **Linux** checkout so the lock pins
  the LF checksum
- the `rejected.tsv` from `curate-cohort`, so the screening is auditable
- a note on study independence: how many distinct `source_study` groups it spans,
  since leave-one-study-out validation needs at least two

---

### 6.6 Code of conduct

Be straightforward and civil. Disagreement about methods is the point of a
benchmark; personal remarks are not. The maintainer may close or lock any thread
that stops being about the work.

---

### 6.7 Licence and attribution

PlasBench is MIT licensed. By contributing you agree your contribution is
released under the same licence.

Contributors are credited in the commit history. If your contribution is
substantial and you would like to be listed in `CITATION.cff` for academic
credit, say so in the pull request.

---

## 7. How scoring works (short version)

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

Each tool is scored under **its own** analysis track, read from
`config/tool_capabilities.tsv` — so one run can score short-read, long-read and
hybrid tools together, and aggregation still writes one leaderboard per track
without ever mixing them.

A tool that also publishes a per-contig probability gets one extra, optional
metric on top of the above: `pr_auc`, the area under its precision–recall curve
swept across every threshold. It never replaces F1 and never changes it — see
[4.11](#411-ml-classifiers-and-reading-a-precisionrecall-curve) and
[`adapters/SCORES.md`](adapters/SCORES.md).

---

## 8. Extending it (good hackathon sprints)

- **Add a tool**: write a one-file adapter in `adapters/` that emits a predicted-plasmid
  FASTA, add a block in `scripts/04_run_tools.sh`, add a `RUN_*` flag. Scoring is automatic.
- **Add bin-level metrics** (did the tool get the *right number* of distinct plasmids?)
  alongside the base-level metric.
- **Stratify** results by plasmid size, replicon type (Inc group), or AMR-gene carriage.
- **Vary read depth** (subsample with `seqtk`) to chart recovery vs coverage.
- **Wrap in Nextflow/Snakemake** for cluster-scale runs (the stages map 1:1 to processes).

---

## 9. Reproducibility notes

- Regenerate the explicit lock with `bash env/lock_environment.sh`; do not overwrite it with `conda env export`.
- Record tool versions per run (add `--version` calls to a manifest — a nice sprint task).
- Deposit your curated sample sheet + truth tables on **Zenodo** for a citable dataset —
  this is the actual publishable artifact PlasBench asks for.

## 10. License
MIT — see `LICENSE`.
