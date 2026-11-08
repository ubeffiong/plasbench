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

## [Unreleased]

### Changed (breaking, experimental output only)
- **The Mash nearest-reference screen no longer claims novelty.** Its calls were renamed
  because they promised more than a Mash distance to 16 plasmids can show:
  `known_cluster` is now `close_reference_match`, `novel` is now `no_close_reference`, and
  the `confidence_score` column is now `distance_margin` (a linear margin to an uncalibrated
  threshold, not a probability). `plasmid_similarity.tsv` gains `mash_p_value` and
  `shared_hashes`. The default threshold is unchanged, but its documentation no longer calls
  it "roughly ANI >= 95%": for plasmids, two equal-size sequences sharing about 35% of their
  k-mers already reach it, and an exact piece under about 21% of a reference falls outside it.
  Anything that read the old labels or column must be updated. The feature remains off by
  default and unvalidated.
- **`make_truth.py` no longer guesses CHROMOSOME for a sequence it cannot label.** Such
  sequences are written as `REVIEW`, which `validate_truth_table.py` rejects, so stage 2 stops
  instead of silently biasing precision and recall. This now also covers location types other
  than Plasmid/Chromosome and reports that contradict themselves. `ALLOW_DEFAULTED_TRUTH=1`
  (or `--allow-default`) restores the old behaviour.
- A skipped tool run (command not installed, database missing, no assembly graph) no longer
  counts as a failure in the operational recommendation's `failure_rate`; it already lowers
  coverage, which gates eligibility.

### Added
- `n_failed_resource` and `n_unknown_overlap` leaderboard columns; `--resource-failures
  {score-zero,exclude}` and `--tool-capabilities` on `aggregate_results.py`.
- A failed tool run's exit code is recorded in `tool_status.tsv`'s reason column
  (`exit_code=<n>`; the file's header is unchanged). Exit 124/137 is classed as a resource
  failure.
- The HTML report now shows the nearest-reference screen result in each sample's selection card,
  with its experimental caveat and support (p-value, shared hashes); reports from before the
  rename still display.
- `python/rank_sensitivity.py` and `benchmark.rank_robustness.tsv`: per-track sensitivity of the
  ranking to alignment filters (re-scored from the PAFs on disk) and to the metric (strict F1,
  per-plasmid recovery), with Kendall's tau and whether the top tool changes. Run from stage 6;
  `RUN_RANK_SENSITIVITY=0` skips it. It does not change the leaderboard.
- A leaderboard warning (stderr and the Markdown leaderboard) and a clearer HTML cell when the
  database-overlap screen could not judge any pair because `database_release_date` is blank.
- Tests: `test_scoring_adversarial.py`, `test_aggregate_failures.py`,
  `test_selection_undefined_metrics.py`, `test_study_groups.py`, `test_leakage_visibility.py`,
  `test_classifier_semantics.py`, `test_report_classifier_section.py`, `test_rank_sensitivity.py`, `test_failed_tool_exit_code.sh`.

### Changed -- research design (headline endpoints and reference standard)
- **Primary endpoint is now length-weighted binning F1** for binning-capable tools
  (`lw_bin_f1`, ungated Hungarian match; the count-based `bin_f1` is kept but not
  ranked). **CPRR** (Correct Plasmid Reconstruction Rate) is the secondary endpoint,
  with pre-specified `CPRR_MIN_COVERAGE`/`CPRR_MIN_SHARE`/`CPRR_MIN_IDENTITY`.
  Classifier-only tools are ranked on a separate classification track by
  base-level F1. Leaderboards add `task`, `ranking_metric`, `ranking_score` (+ CI),
  `ranking_species_basis`, `cprr` (+ CI) and `mean_lw_bin_f1`.
- **Reference standard.** `truth_provenance.py` classifies how each truth was built
  (long-read-first vs short-read-first; polished with the benchmark's own reads or
  not) and assigns reference tiers 1-3. Short-read-first and unknown-provenance truth
  (tier 3) leave the headline and become a sensitivity analysis; the CPRR identity
  criterion is dropped for truth polished with the benchmark's reads.
- **Evidence-based truth labels.** `label_truth_evidence.py` confirms each replicon
  with plasmid markers, rRNA genes (new barrnap caller) and long-read support;
  conflicting replicons (chromids, marker-free or short-read-only plasmids) are
  AMBIGUOUS and excluded from scoring via `truth.scored.tsv`. Self-built truth is no
  longer labelled by size alone.
- **Species balance.** The ranking score averages per-species means over species with
  >= `MIN_SPECIES_CLUSTERS` independent clusters; clusters join shared BioProjects and
  clonal groups (`clonal_groups.py`), and CIs/permutation tests resample whole
  clusters within species. New `benchmark.species.tsv`,
  `benchmark.reference_tiers.tsv`, `benchmark.headline_design.tsv`.
- `validate_cohort.py` prints advisory composition warnings (species count, dominant
  species, species below the minimum) and validates the new optional sheet columns
  `truth_assembly_strategy`, `truth_polish_reads` and `clonal_group`.
- HTML report: leaderboards per task with ranking score, CI and CPRR; new "Headline
  design and reference standard" section with provenance, tiers, species balance and
  a tier-sensitivity chart.

### Fixed
- **A tool that failed on every sample no longer vanishes from the leaderboard.** It now ranks
  last with F1 = 0 on every plasmid-bearing sample, in its own track.
- Equal mean F1 now ranks by tool name instead of by row order in `scores.tsv`, which made the
  "runner-up" in the significance test arbitrary.
- The operational recommendation no longer averages an undefined F1, precision or recall (an
  isolate with no true plasmid) as 0.0.
- Leave-one-study-out validation no longer silently drops samples with a blank `source_study`:
  they join the study of any sample sharing their bioproject, else use the bioproject, and
  samples with neither are reported.
- The mash query sketch now uses the same sketch size as the reference (it used Mash's default
  of 1000 against a 10000-hash reference), and mash's p-value and shared-hash count are no
  longer discarded; a close but statistically unsupported hit is no longer a match.
- `make_truth.py`: the version-less accession fallback is no longer order-dependent, and a
  `chr_name` shared by several records no longer silently resolves to the last one.
- The scorer ignores secondary alignment rows (`tp:A:S`) in a supplied PAF and warns.
- `scorable_truth.py` reads truth with the scorer's own validation.
- Removed `write_track_leaderboards`, which nothing called.
- **Empty predictions no longer inflate mean F1.** On an isolate with true
  plasmid, a tool that predicts nothing now scores F1 = 0 (precision stays
  empty). Previously F1 was left empty and the sample was dropped from the
  tool's mean, so a tool that abstained on hard isolates could tie a perfect one.
- **Tools are ranked on the same samples.** `mean_f1`, its CI and median now use
  only samples shared by every ranked tool in the track; a failed tool run
  (`tool_status.tsv`) on a plasmid-bearing sample counts as F1 = 0 for that tool,
  in both the ranking and the paired comparisons. New leaderboard columns:
  `analysis_track`, `n_ranking_samples`, `ranking_basis`, `mean_f1_all_scored`,
  `n_f1_scored`, `n_failures_scored_zero`.
- **The combined leaderboard no longer ranks across input tracks.**
  `benchmark.leaderboard.tsv/.md` now hold each track's table ranked within that
  track, and `benchmark.paired_comparisons.tsv` only compares tools within a
  track (new `analysis_track` column). Previously the combined file ranked
  short-read, long-read and hybrid tools against each other.
- `make_truth.py` no longer claims that defaulting an unclassified sequence to
  CHROMOSOME "only ever creates false negatives": if it is really a plasmid, correct
  plasmid calls on it are scored as false positives. Its warnings now say so, and
  the plasmid-free note no longer suggests excluding negative-control isolates.
- The HTML report no longer says failed tool runs are excluded from F1 aggregation
  or never become zero scores; it now describes the failure-as-zero ranking rule.
- METHODS.md now states that `unmapped_pred_bp` includes predicted sequence whose
  alignments were all removed by the alignment filters, so it lowers neither
  precision nor F1.

### Added
- **Cluster-aware statistics.** Bootstrap CIs and paired permutation tests resample
  whole BioProject clusters (sample-sheet `bioproject`, else `source_study`), so
  same-study isolates are not counted as independent. New columns
  `n_independent_clusters` (leaderboard) and `paired_clusters` (comparisons).
  Unchanged results when no cluster column is present.
- **Recall-ceiling diagnostic** (`python/scorable_truth.py`, stage 5, on by default):
  `scorable_plasmid_bp`, `recall_ceiling` and `ceiling_adjusted_recall` show how much
  plasmid sequence (shared repeats, duplicate plasmids) no prediction can be credited
  for under the alignment filters. Config: `RUN_SCORABLE_TRUTH`,
  `SCORABLE_WINDOW_BP`, `SCORABLE_STEP_BP`.
- **Strict precision** (`strict_precision`, `mean_strict_precision`): also charges
  unmapped and filter-rejected predicted bases. Supplementary, never ranking.
- **Reference-database overlap screen** (`python/flag_database_overlap.py`, stage 6,
  `config/tool_database_releases.tsv`): flags truth genomes public before a tool's
  database; leaderboard adds `n_possible_db_overlap`, `n_after_database`,
  `mean_f1_after_database`; `EXCLUDE_DATABASE_OVERLAP=1` drops flagged rows before
  ranking. Stage 1 now keeps `assembly_data_report.jsonl` for the release date.
- **HTML report "Robustness diagnostics" section** with a table and three charts
  (recall vs ceiling, precision vs strict precision, F1 vs F1 after database);
  the leaderboard shows the shared-sample basis and the comparisons table shows
  cluster counts.
- `redundant_pred_bp` score column: reference bases claimed more than once by
  retained alignments (e.g. duplicate predicted records). Diagnostic only; it never
  changes TP, FP or F1.

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
