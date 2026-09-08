# Changelog

## [0.2.8] - 2026-09-08

- Added a three-class metagenomic classifier contract and score path for
  plasmid, chromosome, phage/virus, and uncertainty-aware calls. It is kept
  separate from graph/bin reconstruction metrics.
- Added safe PPR-Meta and PlasmidHunter output normalization, MAP-compatible
  mobilome GFF3 import, richer community provenance fields, checksummed meta
  run manifests, and report panels for classifier and evidence results.
- Added explicit installation contracts for PPR-Meta, plsMD, experimental
  metagenomic Plassembler, and the EBI Mobilome Annotation Pipeline. Planned
  runtimes remain non-automatic until pinned and validated.

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

### Added

- A separately executable metagenomic community/bin scoring route:
  `plasbench metagenomics`, or `plasbench run --mode metagenomics`.
- Strict community manifests, three-class plasmid/chromosome/virus truth,
  normalized graph/bin tables, global one-to-one bin matching, split/merge and
  contamination diagnostics, a run manifest, and `metagenomics.report.html`.
- A metagenomics installer profile for the tested baseline runtime
  dependencies (`metaSPAdes` through SPAdes and geNomad).
- An auditable optional orthogonal-validation evidence validator for long-read,
  hybrid, PCR, plasmid-extraction, conjugation, Hi-C, and optical-mapping
  records. Evidence is preserved separately and cannot inflate a score.
- Public cohort release and governance standards, including two-reviewer,
  conflict-of-interest, versioning, representation, and annual-refresh rules.
- An `amr_context` decision profile that treats curated AMR-gene recovery,
  plasmid recovery, bin quality, and structural penalties as co-primary;
  it safely falls back when an AMR truth table is unavailable.
- A deterministic, offline metagenomic demonstration fixture covering bin
  recovery, merge and contamination trade-offs, three-class classifier calls,
  uncertainty, and non-scoring mobilome evidence.

### Changed

- Refreshed public project identity to **PlasBench: A Reproducible,
  Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction Tools**
  with the tagline *Benchmarking plasmid reconstruction from sequence to
  biological function.*
- The isolate and metagenomic HTML reports now carry the updated project
  identity; the stable `plasbench` command name is unchanged.

### Fixed

- Reject duplicate or malformed BMock12 gold-standard memberships, fail clearly
  when truth-backed metagenomic scoring receives no normalized predictions, and
  safely escape cohort metadata embedded in a self-contained HTML dashboard.

### Safeguards

- Metagenomic and isolate reports/rankings are structurally separated. Candidate
  bins are never represented as host assignments, circular closure, or clinical
  confirmation without independent evidence.

## [0.2.7] - 2026-09-08

### Changed

- Adds a complete user-facing release guide, reusable GitHub Release template,
  and version-specific release notes.
- Corrects `CITATION.cff` to the current release metadata.
- Clarifies PyPI Trusted Publishing and requires public availability checks
  before a release claims PyPI publication.

## [0.2.6] - 2026-09-08

### Added

- An auditable tool-installer registry covering every supported, non-demo
  adapter, with `plasbench install-tools list`, `plan`, and `validate` modes.
- An external-benchmark importer that preserves source data, checksums, and
  truth-definition boundaries instead of mixing external scores into native
  PlasBench results.
- A candidate-quality dataset builder for downstream research only. Aggregate
  tool scores are explicitly not converted into fabricated bin labels.
- Regression tests for installer coverage, external evidence import,
  candidate-dataset safety, README release paths, and CLI project-root errors.

### Changed

- Installation guidance now defaults to the verified latest-release installer
  and separates normal laboratory use from recovery and troubleshooting.
- The CLI now reports a clear recovery command when launched outside a
  PlasBench project directory.
- Stage 6 writes the candidate-quality data package with the other final
  benchmark artifacts.

### Notes

- `gplas2` remains source-runtime-only until its upstream runtime and
  classifier provenance can be installed reproducibly. It is deliberately not
  misrepresented as a one-command package installation.
- This release contains no claim that an external benchmark is directly
  comparable with a native PlasBench score unless its truth definition and
  metric mapping have been reviewed.

## Release Reading Guide

- **GitHub Release assets** are the checksum-verified source distribution for
  terminal installations.
- **PyPI** supplies the lightweight Python/CLI package; external
  bioinformatics tools and databases are installed separately through the
  documented installer routes.
- **GHCR** supplies the container image. Use an immutable version tag such as
  `ghcr.io/ubeffiong/plasbench:v0.2.7` for reproducible work, not `latest`.
- **Run manifests and cohort locks** are required companions when reporting or
  comparing scientific results; a software version alone is insufficient.
