# Releasing PlasBench

This repository contains the files needed to publish PlasBench, but publishing
requires maintainer-owned accounts and cannot be performed from a source checkout.

## One-time setup

1. Create `YOUR_GITHUB_ORG/plasbench` and replace every `YOUR_GITHUB_ORG` placeholder.
2. Register the `plasbench` project on PyPI and configure GitHub OIDC trusted publishing.
3. Create a Quay repository or use the GitHub Container Registry image published by the
   release workflow; replace `YOUR_QUAY_NAMESPACE` in `galaxy/plasbench_score.xml`.
4. Fork `bioconda-recipes`, fill the source URL and SHA256 in
   `recipes/bioconda/meta.yaml.template`, then open the Bioconda pull request.
5. Create a Galaxy Tool Shed account, copy `galaxy/.shed.yml.example` to `.shed.yml`,
   replace all placeholders, and publish after Planemo tests pass.

## Release sequence

1. Update `plasbench/__init__.py` and `pyproject.toml` to the same version.
2. Run `python -m pip install --no-deps .`, `plasbench test`, and `plasbench demo`.
3. Build locally with `docker build -t plasbench:<version> .`.
4. Commit, tag `v<version>`, and push the tag. The GitHub release workflow builds the
   PyPI distribution and pushes the GHCR image after trusted publishing is configured.
5. Create or update the Bioconda and Galaxy Tool Shed submissions from that immutable tag.

## Docker use

```bash
docker build -t plasbench:local .
docker run --rm plasbench:local plasbench demo
docker run --rm -v "$PWD/config:/work/config:ro" -v "$PWD/data:/work/data" \
  -v "$PWD/logs:/work/logs" -v "$PWD/results:/work/results" plasbench:local \
  plasbench --project-root /opt/plasbench run --samples /work/config/accessions.tsv
```

The final command needs the Platon database mounted under `/work/data/db/platon/db`
when Platon is enabled. The image does not embed this large mutable database.
