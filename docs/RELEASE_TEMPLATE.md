## PlasBench release documentation

Read the [changelog](https://github.com/ubeffiong/plasbench/blob/main/CHANGELOG.md)
for user-visible changes and the
[release guide](https://github.com/ubeffiong/plasbench/blob/main/docs/RELEASES.md) for installation, verification,
container use, upgrade, and rollback instructions.

### Download and verify

Download both release assets, then verify the archive before extracting it:

```bash
sha256sum -c plasbench-<version>.tar.gz.sha256
```

The command must print `OK`. The GitHub release archive is the recommended
terminal/WSL distribution. The latest-release installer and full lab workflow
are documented in the [README](https://github.com/ubeffiong/plasbench#3-step-by-step-from-a-new-machine-to-your-first-leaderboard).

### Container

For reproducible use, select the immutable image tag matching this release:

```bash
docker pull ghcr.io/ubeffiong/plasbench:v<version>
docker run --rm ghcr.io/ubeffiong/plasbench:v<version> plasbench --version
```

`latest` is suitable for exploration but should not be cited in a protocol.

### Before using results

A software release confirms packaging and automated test coverage; it does not
prove that a reconstructed plasmid is biologically closed or universally best.
For every study, preserve the HTML report, `run_manifest.json`, cohort lock,
tool/database versions, and execution-health table. Read the report’s
confidence and long-read-confirmation flags before downstream interpretation.

---
