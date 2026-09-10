# Changelog

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

The v0.1.x series was renumbered on 2026-09-09 from an earlier, denser
v0.1.0-v0.2.8 sequence (19 tags) down to 5 milestone releases. Each entry
below folds in every change from the tags it supersedes -- nothing from that
history is lost, only the numbering is cleaner. See
[docs/releases/](docs/releases/) for the full per-version notes.

## [0.1.5] - 2026-09-10

### Added

- Optional operational-mode novel-vs-known plasmid classification
  (`RUN_PLASMID_NOVELTY_CLASSIFICATION`, `python/classify_operational_plasmid.py`,
  `python/build_plasmid_reference_set.py`): Mash distance from a truth-unknown
  isolate's own reconstructed candidate to a small, curated reference plasmid
  set, independently reimplementing santirdnd/COPLA's own known-cluster-or-
  novel pattern with PlasBench's existing Mash dependency rather than COPLA's
  code or its `graph-tool`/nested-SBM machinery. Off by default -- a purely
  supplementary, operational-only signal never wired into
  `recommendation_model.py`'s training features, since a genuinely unknown
  isolate has no truth reference, the entire reason this signal exists.
  - `python/build_plasmid_reference_set.py` builds the reference Mash sketch
    and metadata once from a committed, curated accession list
    (`cohorts/reference_plasmids/curated_accessions.tsv`, 16 real NCBI
    plasmids spanning *E. coli*, *Salmonella enterica*, *Klebsiella
    pneumoniae*, *Acinetobacter baumannii*, and *Staphylococcus aureus*, each
    with a one-line provenance justification). The built sketch/metadata are
    real downloaded data, not tracked metadata, so -- the same convention as
    `PLATON_DB`/`GENOMAD_DB`/`PLASME_DB` -- they live under `DATA_DIR/db`,
    gitignored.
  - `python/classify_operational_plasmid.py` calls the built-in `mash dist`
    against that sketch and calls `known_cluster` when the nearest reference
    is within `PLASMID_NOVELTY_SIMILARITY_THRESHOLD` (default Mash distance
    0.05, roughly ANI >= 95%) AND that reference's cluster has at least
    `PLASMID_NOVELTY_MIN_CLUSTER_MEMBERS` members (default 2); otherwise
    `novel`. A missing `mash` binary or reference set gives
    `insufficient_reference`, never a guess.
  - Wired into `scripts/08_operational_reconstruct.sh` (`plasbench
    reconstruct`); results land in `results/<sample>/plasmid_similarity.tsv`
    and under `plasmid_novelty` in `selection_report.json`. A failed or
    skipped classification never blocks reconstruction or the rest of the
    report -- it is supplementary, not a gate.
  - See `docs/OPERATIONAL_SELECTION.md`'s new "Novel-vs-known plasmid
    classification" section for the full usage walkthrough.

### Changed

- **Relicensed from MIT to the GNU General Public License, version 3
  (GPL-3.0-only)**, effective from this point forward. Releases v0.1.0
  through v0.1.4 remain published under the MIT License as distributed;
  this change is not retroactive. See `LICENSE`, `NOTICE`, and
  `CITATION.cff`.

### Documentation

- Recorded the two real, permanent Zenodo dataset DOIs minted by the
  existing `zenodo-upload.yml` workflow when the v0.1.3/v0.1.4 GitHub
  Releases were created during the v0.1.x renumbering
  ([10.5281/zenodo.22671309](https://doi.org/10.5281/zenodo.22671309),
  [10.5281/zenodo.22671314](https://doi.org/10.5281/zenodo.22671314)), in
  both release notes and `cohorts/README.md`, per `docs/RELEASING.md`'s own
  instruction. These are dataset-only DOIs (the archived `cohorts/*.tsv`),
  not a software citation.

### Removed

- **PyPI publishing.** `.github/workflows/release.yml`'s `pypa/gh-action-pypi-publish`
  step (and the now-unused `python -m build` step that only fed it) failed on
  every real attempt with `invalid-publisher` -- the trusted-publisher
  registration on PyPI's side never actually matched this workflow, and
  `plasbench` was never reachable at pypi.org/project/plasbench despite
  `continue-on-error` making every release job show green. A step that
  always fails silently is worse than no step: it lets a broken channel look
  configured. The GitHub Release archive remains the Python-package
  distribution; see `RELEASING.md` for how to re-add PyPI later with a
  verified trusted publisher.

## [0.1.4] - 2026-09-08

Supersedes the removed v0.2.5-v0.2.8 tags.

### Added

- A separately executable metagenomic community/bin scoring route:
  `plasbench metagenomics`, or `plasbench run --mode metagenomics`.
- Strict community manifests, three-class plasmid/chromosome/virus truth,
  normalized graph/bin tables, global one-to-one bin matching, split/merge
  and contamination diagnostics, a run manifest, and
  `metagenomics.report.html`.
- A metagenomics installer profile for the tested baseline runtime
  dependencies (`metaSPAdes` through SPAdes and geNomad).
- An auditable optional orthogonal-validation evidence validator for
  long-read, hybrid, PCR, plasmid-extraction, conjugation, Hi-C, and
  optical-mapping records. Evidence is preserved separately and cannot
  inflate a score.
- Public cohort release and governance standards, including two-reviewer,
  conflict-of-interest, versioning, representation, and annual-refresh
  rules.
- An `amr_context` decision profile that treats curated AMR-gene recovery,
  plasmid recovery, bin quality, and structural penalties as co-primary;
  it safely falls back when an AMR truth table is unavailable.
- A deterministic, offline metagenomic demonstration fixture covering bin
  recovery, merge and contamination trade-offs, three-class classifier
  calls, uncertainty, and non-scoring mobilome evidence.
- An auditable tool-installer registry covering every supported, non-demo
  adapter, with `plasbench install-tools list`, `plan`, and `validate`
  modes.
- An external-benchmark importer that preserves source data, checksums, and
  truth-definition boundaries instead of mixing external scores into native
  PlasBench results.
- A candidate-quality dataset builder for downstream research only.
  Aggregate tool scores are explicitly not converted into fabricated bin
  labels.
- Strict reference-recovery-rate metrics and nested-validation model cards.
- A complete user-facing release guide (`docs/RELEASES.md`), a reusable
  GitHub Release template, and version-specific release notes under
  `docs/releases/`.

### Changed

- Refreshed public project identity to **PlasBench: A Reproducible,
  Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction
  Tools** with the tagline *Benchmarking plasmid reconstruction from
  sequence to biological function.* The stable `plasbench` command is
  unchanged.
- The isolate and metagenomic HTML reports now carry the updated project
  identity, plus auto-sized reconstruction dashboard frames, balanced
  evidence panels, run labels, and a clearer heatmap/report handoff.
- Installation guidance defaults to the verified latest-release installer
  and separates normal laboratory use from recovery and troubleshooting.
- The CLI reports a clear recovery command when launched outside a
  PlasBench project directory.

### Fixed

- Reject duplicate or malformed BMock12 gold-standard memberships, fail
  clearly when truth-backed metagenomic scoring receives no normalized
  predictions, and safely escape cohort metadata embedded in a
  self-contained HTML dashboard.

### Safeguards

- Metagenomic and isolate reports/rankings are structurally separated.
  Candidate bins are never represented as host assignments, circular
  closure, or clinical confirmation without independent evidence.
- `gplas2` remains source-runtime-only until its upstream runtime and
  classifier provenance can be installed reproducibly. It is deliberately
  not misrepresented as a one-command package installation.

## [0.1.3] - 2026-09-07

Supersedes the removed v0.2.0-v0.2.4 tags. Nothing here is on by default --
an existing cohort run behaves exactly as before unless a new flag is
switched on.

### Added

- Three long-read/hybrid tools: `hybracter_long`, `hybracter_hybrid`, and
  `trycycler_mob_recon`, a second independent long-read assembly path
  alongside Flye+MOB-Recon and Plassembler (assembler choice materially
  affects plasmid completeness on ONT data). Hybracter reuses the
  Plassembler database.
- Three opt-in ML classifiers, all short-read-track contig classifiers, not
  binners: `genomad` (gene-based neural classifier), `plasme` (alignment +
  transformer hybrid), `plasgraph2` (GNN over assembly-graph nodes).
- A new `pr_auc` metric: where an adapter publishes a candidates universe
  plus per-record probabilities, scoring sweeps every distinct probability
  as a threshold and reports the area under the precision-recall curve.
  Ranking stays on `mean_f1`; PR-AUC is supplementary.
- A read-quality ladder, the long-read analog of the depth ladder, with
  combined length+quality `--rungs` cutoffs.
- A leave-one-study-out decision-support model and multi-track
  recommendation support.
- `./update.sh` / `plasbench upgrade` for one-command version upgrades that
  reuse shared data across releases, plus a latest-release bootstrap
  installer.

### Changed

- Each tool is now scored under its own declared `analysis_track`
  (`config/tool_capabilities.tsv`), so one run correctly scores short-read,
  long-read, and hybrid tools together instead of applying one global track
  to every tool. Stage 7 (long-read reconstruction) is now part of the
  default stage list, before scoring.
- **The circularity guard (truth independence from long reads) now applies
  to all five long-read/hybrid tools**, including retroactively to
  `flye_mob_recon`, which had no guard before. This is a real behavior
  change for existing cohorts: a sample lacking
  `truth_independent_of_long_reads=yes` is now correctly **skipped** where
  it previously ran; each tool has a `<TOOL>_ALLOW_CIRCULAR_TRUTH=1`
  override.
- `docs/COHORTS.md`/`docs/METHODS.md` now name all five guarded tools with
  their override variables, instead of the two they listed before.

### Fixed

- CI no longer lets a failed PyPI publish block the GHCR image/GitHub
  Release.
- An upgrade no longer re-fetches shared data it should reuse.

## [0.1.2] - 2026-09-05

Supersedes the removed v0.1.6-v0.1.9 tags.

### Added

- `plasbench init-local`, staging a user's own FASTQ reads and reference
  into the pipeline, writing the truth table and sample-sheet row.
  Unlabelled sequences are written as `REVIEW`, never guessed.
- Two input validators that run before any tool starts: staged reads
  (missing/empty/not actually gzipped, mates out of order) and the truth
  table (unmatched ids, unlabelled sequences, bad `molecule_type`, tabs vs.
  spaces, length mismatches).
- Cohort download-size estimation and confirmation before fetching.
- Plassembler support on the long-read/hybrid track, with a circularity
  guard.

### Changed

- `THREADS`/`MEMORY_GB` now default to 80% of the detected machine's
  cores/RAM (floor 2 GB) instead of a fixed value.
- Databases are checked for presence before being re-downloaded; a partial
  download is reported as **incomplete**, never mistaken for a working
  install. Re-downloading is opt-in via `--force`.

### Fixed

- A failed download no longer aborts the whole cohort: failures are
  recorded per sample in `results/download_status.tsv` with automatic
  linear-backoff retry (`NETWORK_RETRIES`, default 3); the stage aborts
  only when every sample fails.
- Two parallelism tests now assert that work genuinely overlaps, measured
  from the stubbed tools' own process logs, rather than comparing elapsed
  time.

## [0.1.1] - 2026-09-04

Supersedes the removed v0.1.1-v0.1.5 tags.

### Added

- The packaged install-archive distribution
  (`plasbench-<version>.tar.gz` + `.tar.gz.sha256`, installed with
  `./install.sh --tools`).
- Three Galaxy tool wrappers (align/score/aggregate) with a real bioconda
  recipe and `plasbench-score`/`plasbench-aggregate` PATH entry points.

### Fixed

- Release archives no longer ship CRLF line endings, which previously made
  `plasbench test` die with `set: pipefail: invalid option name`.
- The `public-v2` cohort lock was regenerated against LF content and
  re-verified online against NCBI (32/32 pairs).
- `plasbench run` with no stage numbers no longer exits 2 on Python <=
  3.12. `install.sh` now bootstraps Miniforge itself when no conda is
  present.
- A micromamba prefix-resolution bug that aborted `plasbench install-tools`
  with "No prefix found" against a working install. `install-tools all` no
  longer pulls the incompatible bioconda `gplas` package; the explicit
  `gplas` profile now warns and points at gplas2 instead.
- **Install-critical**: `env/setup_conda.sh` no longer destroys an existing
  environment (including MOB-suite's 450 MB database) when re-run against a
  working install -- an existing environment is detected and updated in
  place, non-destructively.

## [0.1.0] - 2026-09-01

Initial public release: the verified `public-v1` cohort, a reproducible
environment lock, capability-aware scoring metrics, and the depth-ladder
workflow.

## Release Reading Guide

- **GitHub Release assets** are the checksum-verified source distribution for
  terminal installations. There is no PyPI package (removed; see "Unreleased"
  above) -- external bioinformatics tools and databases are installed
  separately through the documented installer routes regardless.
- **GHCR** supplies the container image. Use an immutable version tag such as
  `ghcr.io/ubeffiong/plasbench:v0.1.5` for reproducible work, not `latest`.
- **Run manifests and cohort locks** are required companions when reporting or
  comparing scientific results; a software version alone is insufficient.
