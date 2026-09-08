# Changelog

All notable changes to PlasBench are documented here. Version numbers follow
[Semantic Versioning](https://semver.org/). A Git tag is a source snapshot;
the matching GitHub Release is the published distribution with verified
archives, container references, and release notes.

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
