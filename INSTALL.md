# Installation (Ubuntu)

Everything installs through **conda** (via Miniforge). The Python scoring scripts use only
the standard library, so they run even without the conda env — but the bio-tools do not.

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
(provides `spades.py` **and** `plasmidspades.py`), `unicycler`, `mob_suite`, `platon`,
`minimap2`, `samtools`, `pigz`.

Verify:
```bash
bash scripts/00_setup.sh
```
You should see `[ok]` next to each tool you've enabled in `config/config.sh`.

---

## 3. One-time tool databases

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
off by default. Install it the same way as any other optional tool:

```bash
plasbench install-tools gplas
# then enable RUN_GPLAS2_MOB=1 or RUN_GPLAS2_EXTERNAL=1 in config/config.sh
```
`gplas2_mob` uses deterministic MOB-recon membership from the same assembly
graph. `gplas2_external` requires one validated `<sample>.tsv` classifier table
per graph. Both need an **assembly graph**; set `ASSEMBLER=unicycler` for the
cleanest graphs. `bash scripts/00_setup.sh` (or `plasbench check`) detects a
missing `gplas` binary whenever either mode is enabled and offers to install
it for you, the same as it does for mob_recon or Platon.

---

## 5. Long-read/hybrid reconstruction (optional)

Four tools are available for native long-read (ONT/PacBio) or hybrid
(long+short) reconstruction, all off by default and independently selectable:

```bash
plasbench install-tools long-read      # Flye + MOB-suite
plasbench install-tools plassembler    # Plassembler
bash env/download_plassembler_db.sh
plasbench install-tools hybracter      # Hybracter (both modes; reuses the Plassembler database above)
# then enable any combination of:
#   RUN_FLYE_MOB_RECON=1, RUN_PLASSEMBLER=1, RUN_HYBRACTER_LONG=1, RUN_HYBRACTER_HYBRID=1
# in config/config.sh, or the equivalent --flye-mob-recon/--plassembler/
# --hybracter-long/--hybracter-hybrid CLI flags.
```
Stage the long-read FASTQ per sample as `data/<sample>/long_reads.fastq.gz`.
Every one of these tools is subject to the circularity guard (see
`docs/COHORTS.md`'s `truth_independent_of_long_reads` column): a sample is
skipped unless its long reads are declared independent of its truth assembly,
or the tool's own override variable is set.

---

## 6. Lock your versions (for reproducibility)

After a successful install:
```bash
bash env/lock_environment.sh
```
Commit that file so collaborators reproduce the exact toolchain.

---

## Troubleshooting

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
