# Installation (Ubuntu)

Everything installs through **conda** (via Miniforge). The Python scoring scripts use only
the standard library, so they run even without the conda env — but the bio-tools do not.

---

## 0. I already downloaded the release file

If `plasbench-<version>.tar.gz` (and `plasbench-<version>.tar.gz.sha256`) are already on this computer, for example copied from another computer because this one has no internet,
put both in one folder (in WSL, copy them from `/mnt/c/Users/<you>/Downloads/` into `~`), keep the names exactly as downloaded, and run:

```bash
cd ~
sha256sum -c plasbench-<version>.tar.gz.sha256        # must print: plasbench-<version>.tar.gz: OK
tar -xzOf plasbench-<version>.tar.gz plasbench-<version>/scripts/install_latest.sh > install_latest.sh
bash install_latest.sh --archive "$PWD/plasbench-<version>.tar.gz" --tools
```

This installs into `~/PlasBench` (or `$PLASBENCH_INSTALL_DIR/PlasBench`) without downloading PlasBench. It still needs conda (section 1) and, on a first install, the internet for the conda
packages and tools. Installing a newer file later is the same command (or `plasbench upgrade --archive FILE`); studies, settings, databases and tools are kept. The full guide, with
the Windows checksum check and the error messages, is in the README under "I already downloaded the release file".

---

## 1. Install Miniforge (conda/mamba)

If you don't already have conda, let PlasBench check and offer to install it for you:

```bash
bash env/bootstrap_conda.sh          # or: plasbench install-conda, once pip-installed
```

It detects an existing `conda`/`mamba`/`micromamba` and does nothing if one is found;
otherwise it downloads the correct Miniforge installer for your platform, verifies its
published SHA-256 checksum, and asks for confirmation before installing (pass `--yes`
to skip the prompt for scripted/CI use, or `--prefix DIR` to change the install
location from the default `$HOME/miniforge3`).

To install manually instead:

```bash
os="$(uname -s)"; [ "$os" = Darwin ] && os=MacOSX   # asset names use MacOSX, not Darwin
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-${os}-$(uname -m).sh"
bash "Miniforge3-${os}-$(uname -m).sh" -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda config --set channel_priority strict
```

> `mamba` ships with Miniforge and is a much faster drop-in for `conda`. Use whichever you
> have; the setup script auto-detects `mamba` and falls back to `conda`.

---

## 2. Create the benchmark environment

```bash
bash env/setup_conda.sh
conda activate plasbench
```

This installs: `ncbi-datasets-cli`, `sra-tools`, `entrez-direct`, `fastp`, `spades`
(provides `spades.py` **and** `plasmidspades.py`), `unicycler`, `platon`,
`minimap2`, `samtools`, `barrnap`, `mash`, `pigz`.

**MOB-suite gets its own environment.** It pins `pandas<=1.5.3` and `numpy<1.23.5`, which
cannot co-exist with the main environment: installed there, `mob_recon` crashes at start
(`cannot import name 'EmptyDataError' from 'pandas.io.common'`, or
`unexpected keyword argument 'line_terminator'`) and every run scores 0. `setup_conda.sh`
therefore also creates `plasbench-mobsuite` (MOB-suite 3.1.9, the same pins as the
Dockerfile) and puts `mob_recon`, `mob_typer`, `mob_cluster` and `mob_init` wrappers in the
main environment, so `conda activate plasbench` is still all you need. To add or repair it
on an existing install:

```bash
plasbench install-tools mobsuite      # or: bash env/install_tools.sh mobsuite
bash env/download_mobsuite_db.sh      # its database, into the new environment
```

`plasbench check` reports a MOB-suite that is installed but cannot start as `[BROKEN]`.

**Docker mode (switchable).** Set up this computer, **Environment**, chooses where the tools run: Conda or Docker (`plasbench runtime use docker`, `plasbench runtime check`). In Docker mode the window stays on your computer and each run, check and install executes in a container of `ghcr.io/ubeffiong/plasbench:v<version>` with your folders mounted at the same paths; if that image cannot be pulled, `plasbench runtime build --yes` builds it from the Dockerfile (internet, several GB, long). Tools and databases you add live in `~/.plasbench/docker/<version>/extras` and the database folder, not in the image.

**Docker and the folder window.** The window (`plasbench ui`) opens this computer's own folder window for Browse, so run it on your computer; Docker runs the pipeline
(`scripts/docker_run.sh plasbench run ...`, see the README's Container section; no Docker yet? `plasbench install-tools docker`, see "Installing Docker"). Inside a container there is no desktop: Browse uses the built-in browser at the folders you mounted, and
the window shows the `docker run -v` command for mounting another one. If Browse does not open the folder window on your computer, run `plasbench picker-check`.

**Databases are kept once per machine.** Every tool database lives in
`PLASBENCH_DB_DIR` (default `~/.plasbench/databases`), not inside a project folder or a
conda environment, so a new checkout, a new `DATA_DIR` or a rebuilt environment reuses
what is already downloaded. MOB-suite keeps its database inside its environment; the
environment's `databases` folder is a link into the store, and a rebuilt environment is
linked again (`plasbench check` does this) instead of downloading 450 MB. Databases from an
older install under `data/db/` are adopted with:

```bash
bash env/preserve_databases.sh                       # this project's data/db
bash env/preserve_databases.sh --from /old/project/data/db   # any other folder
bash env/preserve_databases.sh --list                # what the store holds
```

Each database is moved into the store and a link is left at its old path, so older
projects keep working. Nothing is deleted.

If you built the environment another way (or `bash scripts/00_setup.sh` reports one of these
missing), two install profiles supply the rest:

```bash
plasbench install-tools utilities             # mash, samtools, barrnap
plasbench install-tools reference-annotation  # abricate, ncbi-amrfinderplus, isescan; mob_suite in its own env
amrfinder -u                                  # once, after reference-annotation
```

`mash` matters more than it looks: stage 6 uses it for clonal grouping, and without it the
independence clusters fall back to BioProject or study only. The reference-annotation callers
run in stage 2 by default (`RUN_REFERENCE_ANNOTATION=1`); a missing one leaves its feature class
`not_evaluated` (never "absent"), so the run continues but replicon, AMR or insertion-sequence
context is empty. `bash scripts/00_setup.sh` lists exactly which are missing.

Verify:
```bash
bash scripts/00_setup.sh
```
You should see `[ok]` next to each tool you've enabled in `config/config.sh`.

---

## 3. One-time tool databases

### Installer inventory and plan

The existing installer has one registry for every supported non-demo adapter;
it does not maintain a second package list. Before downloading anything, use:

```bash
plasbench install-tools list       # every supported adapter and its installer state
plasbench install-tools plan       # same machine-readable plan for records/automation
plasbench install-tools validate   # confirms registry coverage; no downloads
```

Every profile is installed on a clean Linux runner by `.github/workflows/tool-install-proof.yml` (weekly and on request, Actions tab, *Run workflow*; the
`profiles` input takes `all` or a comma list). It uses the commands above, runs each tool's verification and writes one table of every profile (pass, or
expected-manual with the reason) into the run summary; the latest result per tool is the *CI proof* column of `docs/TOOL_INSTALL_AUDIT.md`.

`plasbench install-tools all` runs every **verified automatic** profile through
its existing installer path. It deliberately does not fake an installation for
the two runtimes that cannot be installed automatically (plsMD and PPR-Meta: see
"Tools that cannot be installed automatically" below) or databases without a stable
upstream checksum. Source-built profiles (gplas2, PLASMe, plASgraph2, PlasmidEC,
PlasBin-flow, the Mobilome Annotation Pipeline) are installed from a pinned commit, with
`--yes`; see "Installing every tool".

### Installing every tool

Every tool the benchmark can run installs automatically, with your consent, in its own isolated environment, from a pinned release or an exact commit. Nothing is installed
until you agree: `--yes` on the command line, `y` at a prompt, the confirmation dialog in the window, or `INSTALL_MISSING_TOOLS=1` for an unattended run.

```bash
plasbench install-tools gplas2            # shows the plan (repository, pinned commit, size, licence, time) and stops: exit 21, nothing changed
plasbench install-tools gplas2 --yes      # clones the pinned commit, builds the environment, verifies the tool, records where it came from
plasbench install-tools gplas2,plasme --yes   # several profiles at once
plasbench install-tools all --yes         # every automatic profile, including the source-built ones
plasbench check --yes                     # installs whatever the tools enabled in config/config.sh need (tools and databases), then re-checks
plasbench run --install-missing-tools ... # a run installs its missing enabled tools first (INSTALL_MISSING_TOOLS=1)
```

How a source-built tool is installed (gplas2, PLASMe, plASgraph2, PlasmidEC, PlasBin-flow, the Mobilome Annotation Pipeline; the pins are in `config/source_tools.json`):

1. The repository is cloned into a staging folder and the **pinned commit** (a 40-character SHA, never a branch or tag) is checked out; `git rev-parse HEAD` must print it.
2. A dedicated environment `<env>-<profile>` is created next to the main one from that commit's own dependency file (or a pinned file kept in `env/pins/`).
3. The tool's verification command runs (for gplas2 it proves that `gplas --help` lists `-P/--prediction`).
4. Only then is a small wrapper placed in the main environment's `bin/` and a provenance record written (revision, source, time, environment, SHA-256 of the checkout and of the dependency files, dependency versions) at `<env>-<profile>/plasbench-install.json`. `plasbench check` and the run manifest read it.
5. A failure at any step removes everything that step created and puts a previous working install back. Running the command again says *already installed at the pinned revision*; if the pin changed in a newer PlasBench it upgrades.

A run that needs a missing enabled tool never silently skips it: `plasbench run` stops at its first check, before any sample work, naming every missing tool and the exact command
(`plasbench install-tools <profile> --yes`), unless you asked it to install (`--install-missing-tools`, `INSTALL_MISSING_TOOLS=1`, `--yes` on `plasbench check`, or the window's dialog).
After installing it checks again in the same process, so the run carries on without a new shell.

What the runtime does not include is said per tool and reported by `plasbench check` as "runtime installed, input X missing": the PLASMe database (`plasbench check --yes` installs it),
a Gurobi licence for PlasBin-flow (free for academics; PlasBench cannot obtain it), a container engine for the Mobilome Annotation Pipeline (installing one needs administrator rights; see "Installing Docker" below and `plasbench install-tools docker`),
and the databases PlasmidEC downloads itself the first time it runs (about 20 minutes). `docs/TOOL_INSTALL_AUDIT.md` lists, per tool, how it is installed, the pinned revision, the source,
the size, the time estimate and the verification command.

### Tools that cannot be installed automatically (exit code 20)

Two profiles stay manual, each with a verified reason (checked against the upstream on 2026-11-19) and a step-by-step recipe that `plasbench install-tools NAME` prints:

- **plsmd**: upstream ships only a Dockerfile that downloads `Miniconda3-latest` and unpinned packages (two builds of one commit differ), its only tag predates the Dockerfile, it has no licence file, and Docker needs administrator rights (`plasbench install-tools docker` helps, see "Installing Docker" below).
- **ppr-meta**: its executable needs the MATLAB Runtime R2018a, which MathWorks gives out only after a click-through licence, plus Python 2.7, TensorFlow 1.4.1 and Keras 2.0.8 (all end of life).

`plasbench install-tools NAME` for these prints the reason, the evidence URLs and the steps, and exits **20**. That is information, not a failure: no `ERROR`, not red, in the window's console,
the terminal page, the job state (*Manual step needed*) and the scripts.

`plasbench install-tools` exit codes: **0** installed, already installed, or nothing to install (`baseline` is built in); **20** a manual installation step is needed (nothing failed);
**21** consent is needed (nothing was changed: read the plan, then add `--yes`); **2** an unknown profile name or a wrong option (a name close to a real one lists the nearest names); **1** the
installation failed (the messages say which step, and nothing is left half installed); **137** killed for memory (the output says how to give WSL more). `plasbench install-tools NAME --dry-run`
reports what a name is without starting conda or using the network.

### Installing Docker (optional)

Docker is optional. It runs PlasBench in a container (`scripts/docker_run.sh`, the README's Container section) and is the container engine that tools such as mobilome-map (Nextflow) and plsmd (a Dockerfile) need. It appears in `plasbench install-tools list`, in the window's **Tools** page (a *Docker* card with a live state label and **Install Docker**, **Re-check** and **Open the Docker guide**), in the Workflow view under *Check and install*, and as an optional line of `plasbench check`.

```bash
plasbench install-tools docker --dry-run   # the plan for this computer; nothing is started
plasbench install-tools docker             # diagnose, and say what to do next (exit 20 when it hands steps to you)
plasbench install-tools docker --yes       # also start the installer where a user-level process may (Windows, WSL2, macOS)
plasbench install-tools docker --hello-world   # after Docker answers, also run `docker run --rm hello-world` (needs the internet; off by default)
```

PlasBench never runs `sudo`, never asks for or stores an administrator password and never pipes a downloaded script to a shell. So it does the real install only where the operating system itself asks you to approve it, and hands you the exact steps everywhere else. It first detects the computer (native Windows, WSL 2, macOS, Linux with its package manager, or inside a container) and the Docker state, and tells you which of these applies:

| State | What it means | Next step |
| --- | --- | --- |
| Not installed | no `docker` program | the install route for your computer (below) |
| Installed, daemon stopped | `Cannot connect to the Docker daemon` | start the service (`sudo systemctl start docker`) or Docker Desktop |
| Restart needed (docker group not applied) | you ARE in the docker group now (`/etc/group`), but this window (or terminal) started before that, and a running program keeps the groups it started with, so it still gets `permission denied` on `/var/run/docker.sock` | **Restart window** (PlasBench restarts itself through `sg docker` when available), or `newgrp docker` then `plasbench ui`, or `wsl --shutdown` in Windows PowerShell and reopen Ubuntu |
| Permission needed | `permission denied ... /var/run/docker.sock` | `sudo usermod -aG docker "$USER"`, then log out and in (or `newgrp docker`) |
| WSL integration off | Docker Desktop is on Windows but this Ubuntu cannot use it | Docker Desktop > Settings > Resources > WSL integration > turn on your distro |
| Docker Desktop not running | macOS, engine unreachable | start Docker Desktop and wait until it says it is running |
| Docker Desktop installed, not started | Windows or WSL 2: `Docker Desktop.exe` is on the Windows side but is not running | **Start Docker Desktop** in the window, or `plasbench install-tools docker --start` |
| Docker Desktop starting | Docker Desktop.exe is running but `docker.exe info` does not answer yet (first start, or its licence dialog is waiting for you) | wait; if its window shows the licence, accept it there |
| WSL integration off (engine up) | WSL 2: `docker.exe info` works on Windows, but there is no `docker` in this distro (`The command 'docker' could not be found in this WSL 2 distro`) | **Open WSL integration settings**, switch your distro on, Apply & restart |
| Ready | `docker --version` and `docker info` answer | nothing; the version and context are recorded for `plasbench check` and the run manifest |

**Windows, and WSL 2 (Windows 11 with Ubuntu): Docker Desktop with the WSL 2 backend.** `install-tools docker --yes` (or **Install Docker** in the window, after its consent dialog) runs `winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements` through the Windows side (`winget.exe` is reached from WSL by its absolute path; WSL interop must be on). **Windows asks you to approve the installer** (its own UAC prompt); PlasBench never sees the password. What only you can do afterwards: start Docker Desktop once; accept Docker's subscription terms (<https://www.docker.com/legal/docker-subscription-service-agreement/>; Docker Desktop is free for personal use, education and small businesses, and paid for larger companies, and PlasBench cannot accept it for you); keep *Use the WSL 2 based engine* on; Settings > Resources > WSL integration > turn on your Ubuntu distro; and, if Docker Desktop asks, run `wsl --shutdown` in PowerShell and reopen Ubuntu. The job then shows *Waiting for you to finish in Docker Desktop* (exit 20, information, not an error) and polls `docker info` for a short time; press **Re-check** when you are done. If `winget` is missing, PlasBench prints the official download page (<https://docs.docker.com/desktop/setup/install/windows-install/>) and `wsl --install` instead; it does not download and run an installer by itself.

**Docker Engine inside WSL, without Docker Desktop (advanced).** This needs `sudo`, so PlasBench shows the exact commands from docs.docker.com (the apt repository with its signing key, whose fingerprint the script checks, then `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`, `usermod -aG docker $USER`, and `[boot] systemd=true` in `/etc/wsl.conf`) as a script you copy and run in your own Ubuntu window. The window's **Open Terminal with this command prefilled** puts the text in the Terminal tab without running it; that terminal cannot type a sudo password, so run it in a real terminal. Print the same script with `python python/docker_setup.py script apt --wsl`.

**macOS.** With Homebrew, `install-tools docker --yes` runs `brew install --cask docker-desktop` (an older Homebrew that only knows the cask `docker` is handled); the installer asks for your macOS password itself. Without Homebrew, use <https://docs.docker.com/desktop/setup/install/mac-install/>. Then `open -a Docker`, accept the terms, wait for it to run, and press Re-check.

**Linux.** PlasBench prints a script for your package manager family (apt: Ubuntu, Debian; dnf: Fedora, RHEL family; pacman: Arch; zypper: openSUSE), using Docker's own repository (<https://docs.docker.com/engine/install/>) with the signing-key check, or the distribution's own `docker.io` / `moby-engine` package as the simpler alternative. You run it with your own sudo, then `sudo systemctl enable --now docker`, join the `docker` group, and log out and in (or `newgrp docker`). Rootless Docker, which needs no root daemon, is an alternative: <https://docs.docker.com/engine/security/rootless/>. The `get.docker.com` convenience script is a download-and-run-as-root installer and is deliberately not used.

**Inside a container.** Docker-in-Docker is out of scope: install Docker on the computer that hosts the container and run PlasBench there.

**After the install on Windows and WSL 2: what PlasBench checks, starts and leaves to you.** Right after `winget` succeeds PlasBench looks at what is on the Windows side (it never prints *Not installed* for a Docker Desktop that is there) and says, for example, *Docker Desktop was installed on Windows (version 4.99.0). It is not running yet.* Nothing can answer until Docker Desktop is started, so PlasBench does not wait 90 seconds for it: it prints the next step at once (exit 20). The evidence it reads, all read-only: `C:\Program Files\Docker\Docker\Docker Desktop.exe` and `resources\bin\docker.exe` (through `/mnt/c` in WSL), `winget list --id Docker.DockerDesktop` for the version, `tasklist.exe` for whether Docker Desktop.exe is running, `docker.exe info` for whether the engine answers, and `%APPDATA%\Docker\settings-store.json` (or `settings.json`) for `IntegratedWslDistros` and the licence record.

| You want | Do this | What PlasBench does | What only you can do |
| --- | --- | --- | --- |
| Start Docker Desktop | `plasbench install-tools docker --start`, or **Start Docker Desktop** in the Tools page | asks first, runs `powershell.exe -NoProfile -Command Start-Process -FilePath '<Docker Desktop.exe>'` (an argument list, not a shell string), then checks the engine every 5 seconds for up to 90 seconds, printing a progress line every 10 seconds | accept the Docker licence in Docker Desktop's window (PlasBench never does), wait for the first start |
| Turn WSL integration on | `plasbench install-tools docker --open-integration`, or **Open WSL integration settings** then **I enabled it** | opens Docker Desktop (its `docker-desktop://` settings link, else its main window), then checks every 5 seconds for up to 3 minutes by reading the settings file and testing `docker info` in the distro | click Settings > Resources > WSL integration, switch your distro on, Apply & restart (PlasBench never edits Docker's settings), and `wsl --shutdown` if asked |
| Check again | **Re-check**, `plasbench install-tools docker`, `plasbench runtime check` | the same detector everywhere | |

`--wait SECONDS` sets how long the engine is polled afterwards: by default 90 seconds only where Docker Desktop is running (or was just started), and 0 where you have to act first. The Tools page shows the four stages as a checklist (installed, running, engine answering with the licence accepted, WSL integration), each with what was found as its hover text.

Exit codes of `plasbench install-tools docker`: **0** Docker is verified working, **20** steps were handed to you (nothing failed), **21** consent needed (add `--yes`; nothing was changed), **1** a real failure (for example the Windows approval prompt was declined: *"The Windows approval prompt (UAC) was declined or closed, so nothing was installed"*). Needs the internet only for the winget and Homebrew routes (and `--hello-world`). `scripts/docker_run.sh` checks the same state first and prints the same diagnosis when Docker is missing or not ready.

### Platon database (required if `RUN_PLATON=1`)
```bash
bash env/download_platon_db.sh
```
This downloads Platon's database (~1.4 GB) into `data/db/platon/db` and matches the
`PLATON_DB` path in `config/config.sh`.

### MOB-suite database
`mob_recon` downloads/uses its bundled databases automatically on first run. If you're on a
cluster with no internet on compute nodes, run one `mob_recon` on a login node first to
populate the cache, or set `--database_directory` in `scripts/04_run_tools.sh`.

---

## 4. gplas2 modes (optional)

PlasBench uses it only through explicit classifier-backed modes, so it remains
off by default. The legacy `gplas` conda package is **not** gplas2; do not use
it as a substitute. Inspect its explicit source-runtime contract first:

```bash
plasbench install-tools plan | grep gplas2
# then enable RUN_GPLAS2_MOB=1 or RUN_GPLAS2_EXTERNAL=1 in config/config.sh
```
`gplas2_mob` uses deterministic MOB-recon membership from the same assembly
graph. `gplas2_external` requires one validated `<sample>.tsv` classifier table
per graph. Both need an **assembly graph**; set `ASSEMBLER=unicycler` for the
cleanest graphs. `bash scripts/00_setup.sh` (or `plasbench check`) detects a
missing `gplas` (or one without the `-P` option, which is the old gplas 0.6.1) whenever
either mode is enabled and offers `plasbench install-tools gplas2 --yes`, which installs the
pinned gplas2 1.1.0 commit in its own environment instead of the incompatible legacy package.

---

## 5. Long-read/hybrid reconstruction (optional)

Five tools are available for native long-read (ONT/PacBio) or hybrid
(long+short) reconstruction, all off by default and independently selectable:

```bash
plasbench install-tools long-read      # Flye + MOB-suite
plasbench install-tools plassembler    # Plassembler
bash env/download_plassembler_db.sh
plasbench install-tools hybracter      # Hybracter (both modes; reuses the Plassembler database above)
plasbench install-tools trycycler      # own env plasbench-trycycler: Trycycler + Flye (+ Medaka, for optional polishing)
# then enable any combination of:
#   RUN_FLYE_MOB_RECON=1, RUN_PLASSEMBLER=1, RUN_HYBRACTER_LONG=1,
#   RUN_HYBRACTER_HYBRID=1, RUN_TRYCYCLER_MOB_RECON=1
# in config/config.sh, or the equivalent --flye-mob-recon/--plassembler/
# --hybracter-long/--hybracter-hybrid/--trycycler-mob-recon CLI flags.
```
`trycycler_mob_recon` is a second long-read-only assembly path alongside
`flye_mob_recon`, since assembler choice materially affects plasmid
completeness on ONT data -- it reconciles several independent Flye assemblies
of the same reads into one consensus before handing it to MOB-Recon, so it is
substantially slower (roughly `TRYCYCLER_ASSEMBLY_COUNT`x a single Flye run).
Stage the long-read FASTQ per sample as `data/<sample>/long_reads.fastq.gz`.
Every one of these tools is subject to the circularity guard (see
`docs/COHORTS.md`'s `truth_independent_of_long_reads` column): a sample is
skipped unless its long reads are declared independent of its truth assembly,
or the tool's own override variable is set.

---

## 6. ML/graph-based classifiers (optional)

geNomad is a gene-based neural classifier for plasmid detection on assembly
contigs, off by default:

```bash
plasbench install-tools genomad
bash env/download_genomad_db.sh
# then enable RUN_GENOMAD=1 in config/config.sh, or --genomad on
```
Unlike the classical tools, geNomad exposes a per-contig `plasmid_score`, so
it is scored with an optional precision-recall-curve/AUC sweep alongside its
own hard call -- see `adapters/SCORES.md` for the mechanism and
`docs/USER_GUIDE.md`'s Commands section for the leaderboard's `mean_pr_auc`
column.

PLASMe (alignment+transformer classifier) is distributed as a git checkout with its own conda
environment file rather than a bioconda package. PlasBench installs it from the pinned v1.1
commit (`ef0409bad9c8c9ee5d66d90812bf56b345d8dd1d`) into its own environment, with your consent:

```bash
plasbench install-tools plasme --yes
bash env/download_plasme_db.sh   # ~12.4 GB, via PLASMe's own PLASMe_db.py (plasbench check --yes does this too)
# then enable RUN_PLASME=1 in config/config.sh, or --plasme on
```

plASgraph2 (a GNN classifier over the assembly graph) is installed the same way, from the pinned
v1.0.0 commit (`7bc4e92df8570ac2848599e57d5e59730ed5713f`) into a Python 3.8 environment with the
exact versions in its `requirements.txt`. It needs the same `assembly_graph.gfa` gplas2 uses (set
`ASSEMBLER=unicycler` for the cleanest graphs), rather than an assembly FASTA:

```bash
plasbench install-tools plasgraph2 --yes
# The pretrained model ships inside the checkout; when PLASGRAPH2_MODEL_DIR is not set, PlasBench
# uses <env>-plasgraph2/plasbench-src/model/ESKAPEE_model.
# then enable RUN_PLASGRAPH2=1 in config/config.sh, or: plasbench run --plasgraph2 on
```

RFPlasmid (random forest over marker genes, plasmid genes, and kmers) IS a
real bioconda package, unlike the two above:

```bash
plasbench install-tools rfplasmid
# RFPlasmid bundles CheckM as a transitive dependency, and CheckM always
# needs its own ~1.4GB reference data directory set up once, regardless of
# how it was installed:
checkm data setRoot /path/to/checkm_data   # download/extract the data first
                                            # if you have not already; see
                                            # https://github.com/Ecogenomics/CheckM/wiki
# then enable RUN_RFPLASMID=1 in config/config.sh, or --rfplasmid on
```

PlasmidHunter (a Diamond+Prodigal gene-content Naive Bayes classifier, one
species-agnostic model) is a PyPI package, not a bioconda package -- only its
`diamond`/`prodigal` dependencies are conda packages:

Every PyPI release of PlasmidHunter requires Python 3.10, so it cannot go into
the Python 3.12 main environment (pip reports "No matching distribution found").
Like MOB-suite, it gets its own environment, `plasbench-plasmidhunter`, with a
`plasmidhunter` wrapper in the main one. Plasmer (Python 3.10 only) and PlaScope
(its pinned Centrifuge 1.0.3 needs Python 3.6) are handled the same way, in
`plasbench-plasmer` and `plasbench-plascope`. You still only activate `plasbench`.

```bash
plasbench install-tools plasmidhunter   # creates plasbench-plasmidhunter (python 3.10,
                                         # diamond, prodigal) and pip-installs
                                         # plasmidhunter==1.4 into it
# then enable RUN_PLASMIDHUNTER=1 in config/config.sh, or --plasmidhunter on
```

Plasmer (a kmer-db/Prodigal/HMMER/BLAST/Infernal/Diamond/Kraken2 ensemble
feeding an R random forest) is published under its own custom conda channel,
and its README documents a real **32GB system RAM minimum** for its kmer-db
step (not a PlasBench-imposed default -- see `PLASMER_MEMORY_GB` in
`config/config.sh`):

```bash
plasbench install-tools plasmer   # creates plasbench-plasmer (python 3.10) from
                                   # -c iskoldt -c bioconda -c conda-forge
# download Plasmer's database separately (Zenodo/Google Drive -- Plasmer's
# own package does not bundle it) and point PLASMER_DB at it
# then enable RUN_PLASMER=1 in config/config.sh, or --plasmer on
```

PlaScope (Centrifuge-based hard classification, E. coli/Klebsiella only --
no continuous score, so it is never PR-AUC scored like the tools above) is
also a real bioconda package, but needs a species-specific database:

```bash
plasbench install-tools plascope
bash env/download_plascope_db.sh   # E. coli and/or Klebsiella; only these two exist
# then enable RUN_PLASCOPE=1 in config/config.sh, or --plascope on
```

---

## 7. Simulated-cohort reads (optional)

For `truth_source=simulated` cohort rows (see `docs/COHORTS.md`): reads are
generated locally from a real reference assembly, using InSilicoSeq (short
reads) and Badread (long reads), both real bioconda packages:

```bash
plasbench install-tools simulate   # insilicoseq + badread
```

No database or extra setup is needed -- `python/simulate_reads.py` reads its
seed/depth/error-model parameters directly from the cohort sheet's own
`simulation_seed`/`simulation_short_depth_x`/`simulation_long_depth_x`
columns.

---

## 8. Supplementary diagnostics (optional)

Two more optional, off-by-default features (see `docs/METHODS.md`):

**`RUN_QUAST_DIAGNOSTICS`** (stage 5) needs QUAST, a real bioconda package:
```bash
plasbench install-tools quast
# then enable RUN_QUAST_DIAGNOSTICS=1 in config/config.sh
```

**`MULTIQC_REPORT`** (stage 6, optional, default `auto`) runs MultiQC over the fastp and QUAST outputs when it is installed. It has its own isolated environment and
pinned version, and it is never needed: the report's QC panel is PlasBench's own.
```bash
plasbench install-tools multiqc
```

**`RUN_DIFFICULTY_FEATURES`** (stage 3) needs three tools: `minimap2` and
`samtools` are already installed as part of the core environment (step 2
above); `mash` is a direct `env/environment.yml` dependency, also already
installed (`plasbench install-tools utilities` installs `mash` and `samtools` into an
environment built another way). The third, `deadends`
([rrwick/GFA-dead-end-counter](https://github.com/rrwick/GFA-dead-end-counter)),
has **no bioconda package** -- build it from source per that repo's own
instructions, or download a prebuilt binary from its GitHub releases page,
and put `deadends` on PATH. Each of the three difficulty-feature fields is
independently optional: a missing tool leaves that one field empty, never a
guessed value, so `RUN_DIFFICULTY_FEATURES=1` without `deadends` installed
still works, just without the dead-end-count field.
```bash
git clone https://github.com/rrwick/GFA-dead-end-counter.git && cd GFA-dead-end-counter && cargo build --release
# put the resulting target/release/deadends on PATH, then enable
# RUN_DIFFICULTY_FEATURES=1 in config/config.sh
```

---

## 9. Operational-mode plasmid novelty classification (optional)

`RUN_PLASMID_NOVELTY_CLASSIFICATION` (`plasbench reconstruct`, see
`docs/OPERATIONAL_SELECTION.md`) needs no new tool -- it reuses `mash`,
already installed in step 2. It does need a one-time reference-set build
(needs network access to NCBI; not part of any pipeline stage):

```bash
python3 python/build_plasmid_reference_set.py \
    --accessions cohorts/reference_plasmids/curated_accessions.tsv \
    --out-dir data/db/plasmid_reference
# then enable RUN_PLASMID_NOVELTY_CLASSIFICATION=1 in config/config.sh
```

---

## 10. Contributing a new isolate (optional)

`plasbench prepare-contribution` (see `CONTRIBUTING.md`) stages a contribution
as a local git branch, so it needs `git` on PATH -- unlike every step above,
this is **not** a core pipeline dependency: the tarball install in this guide
deliberately does not require a git checkout, and nothing else in PlasBench
invokes git. Install it only if you intend to contribute an isolate:
```bash
git --version   # already present on most Linux systems; if not:
sudo apt-get install -y git
```

---

## 11. Lock your versions (for reproducibility)

After a successful install:
```bash
bash env/lock_environment.sh
```
Commit that file so collaborators reproduce the exact toolchain.

---

## Finding the PlasBench folder, and the `plasbench` launcher

`plasbench` needs your PlasBench folder (the one with `scripts/run_all.sh`). It looks, in this order, at `--project-root`, the `PLASBENCH_HOME` environment variable, the current
folder and its parents, the folder recorded at install time (`~/.plasbench/install.json`, written by `./install.sh` and `plasbench upgrade`), the folder the installed program came
from, and `~/PlasBench`. When the folder is not the current one, the command says which it used and why (and any command that changes things always names its folder).

`./install.sh` and `plasbench upgrade` also write a small launcher, `~/.local/bin/plasbench`, which starts the plasbench environment's `plasbench` so the command works from any terminal
without `conda activate`. It is marked as written by PlasBench, is never written over a file PlasBench did not make, and tells you if `~/.local/bin` is not on your `PATH`.
Set `PLASBENCH_NO_LAUNCHER=1` to skip it. After an upgrade, `plasbench` checks that the installed program is the version in your folder and repairs it
(`python -m pip install --no-deps .`) if not; `plasbench ui-state` shows the evidence.

## Troubleshooting

- **The window says it is older than the page** -> run `plasbench ui-state`. If it reports two installs, run
  `conda activate plasbench && cd ~/PlasBench && python -m pip install --no-deps .`, then restart the window.
- **`datasets: command not found`** → you didn't `conda activate plasbench`.
- **SRA download stalls** → run `vdb-config --interactive` once (sets the SRA cache dir),
  or try `prefetch --max-size 100g <SRR>`.
- **SPAdes runs out of memory** → lower `MEMORY_GB` won't help; reduce input or use a bigger
  machine. Bacterial isolates usually assemble in <16 GB.
- **A tool fails on one sample** → the pipeline logs it, records it in
  `results/tool_status.tsv`, and excludes it from scoring; check
  `logs/<sample>.<tool>.log`. A successful tool that predicts no plasmids is still
  scored as an empty prediction (all true plasmid bases are FN).
- **Conda solve is slow** → use `mamba`, or `conda config --set channel_priority strict`.
