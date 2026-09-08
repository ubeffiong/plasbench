# PlasBench Releases

This guide explains what a PlasBench release is, what users should download,
and what maintainers must verify before publishing one.

## For users

### Choose a distribution

| Need | Recommended distribution | What it includes |
| --- | --- | --- |
| A normal Linux/WSL installation | The checksum-verified GitHub release archive | Source, scripts, documentation, tests, and the CLI installer |
| A Python-only integration | PyPI `plasbench` package | CLI and Python entry points; it does not include the third-party tool stack |
| A reproducible/container run | A versioned GHCR image | The packaged runtime environment; mount data and results from the host |
| A development or audit checkout | A signed/tagged Git commit | Source history and full project context |

Start with the latest verified release installer in [README.md](../README.md).
To reproduce a past analysis, replace `latest` with the exact release version
and retain the run manifest, cohort lock, tool/database versions, and command.

### Verify before installing

Every GitHub release contains these two assets:

```text
plasbench-<version>.tar.gz
plasbench-<version>.tar.gz.sha256
```

Download both and run `sha256sum -c plasbench-<version>.tar.gz.sha256`. It
must report `OK` before extraction. A checksum verifies transport integrity;
it does not make a benchmark result biologically validated.

For containers, prefer the immutable tag:

```bash
docker pull ghcr.io/ubeffiong/plasbench:v<version>
docker run --rm ghcr.io/ubeffiong/plasbench:v<version> plasbench --version
```

`latest` is convenient for exploration but may change. Do not cite it in a
protocol or publication.

### Upgrade and rollback

Run `plasbench upgrade` from an installed release to fetch and verify the
latest published archive. The shared data directory is outside the versioned
program directory, so databases, cohorts, and downloaded reads are reused.
The previous release directory is left untouched; switch back to it if a
newer version does not suit an existing study. See the upgrade section in
[README.md](../README.md#upgrade-an-existing-installation) for commands and
data-transfer guidance.

### What a release does not guarantee

A release validates the distribution and its documented automated tests. It
does **not** certify that any reconstructed sequence is closed, that one tool
is universally best, or that a synthetic demo represents a real cohort. Read
the report’s run manifest, cohort scope, tool execution health, and selection
confidence before using output downstream.

## Release contents

Each release is expected to publish:

1. A GitHub Release with a human-readable summary, comparison notes, known
   limitations, and links to installation, documentation, and the issue
   tracker.
2. A source archive and SHA-256 checksum.
3. A PyPI package, if Trusted Publishing succeeds.
4. A versioned GHCR container image and `latest` tag.
5. A source tag whose version matches `pyproject.toml`.
6. When configured, a Zenodo software archive and separately versioned cohort
   deposition.

The GitHub release page is the source of distribution assets. The changelog is
the concise version history; [RELEASING.md](../RELEASING.md) is the maintainer
procedure.

## For maintainers

### Before tagging

1. Set the same version in `pyproject.toml` and `plasbench/__init__.py`.
2. Add user-facing notes under `CHANGELOG.md`; describe scientific limits and
   compatibility changes, not only code files.
3. Run `bash test/run_tests.sh`, `bash scripts/make_release.sh`, and the
   container/demo checks in [RELEASING.md](../RELEASING.md).
4. Confirm `plasbench install-tools validate` reports full registry coverage.
5. Confirm the release archive excludes data, result folders, credentials, and
   local configuration.

### After publishing

1. Check that the GitHub Release contains both archive assets and that the
   checksum validates.
2. Check the PyPI project version and the versioned GHCR image separately.
3. Replace generic auto-generated release notes with a concise release summary
   when needed; include changes, upgrade guidance, known limitations, and
   links to `CHANGELOG.md` and `RELEASES.md`.
4. Record any Zenodo DOI only after Zenodo has actually published it.
5. Never modify a released source archive or silently move a release tag. Issue
   a patch release for source changes.

