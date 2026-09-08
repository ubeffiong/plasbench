## PlasBench release documentation

Read the [changelog](https://github.com/ubeffiong/plasbench/blob/main/CHANGELOG.md)
for user-visible changes and the
[release guide](https://github.com/ubeffiong/plasbench/blob/main/docs/RELEASES.md) for installation, verification,
container use, upgrade, and rollback instructions.

### Download and verify

Download the archive and matching `.sha256` asset shown on this release page,
then run `sha256sum -c <checksum-file>` before extracting it.

The command must print `OK`. The GitHub release archive is the recommended
terminal/WSL distribution. The latest-release installer and full lab workflow
are documented in the [README](https://github.com/ubeffiong/plasbench#3-step-by-step-from-a-new-machine-to-your-first-leaderboard).

### Container

For reproducible use, select the immutable GHCR image tag matching this
release. The precise pull command belongs in the version-specific release
notes, not a generic template.

`latest` is suitable for exploration but should not be cited in a protocol.

### Before using results

A software release confirms packaging and automated test coverage; it does not
prove that a reconstructed plasmid is biologically closed or universally best.
For every study, preserve the HTML report, `run_manifest.json`, cohort lock,
tool/database versions, and execution-health table. Read the report’s
confidence and long-read-confirmation flags before downstream interpretation.

---
