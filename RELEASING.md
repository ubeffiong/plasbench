# Releasing PlasBench

## Tagging a release

Push a `v*` tag (e.g. `v0.3.0`). `.github/workflows/release.yml` then:

1. Builds and pushes the container image to GHCR.
2. Publishes a **GitHub Release** for the tag (with auto-generated notes).

Step 2 is what makes the Zenodo archival below actually happen — Zenodo's
GitHub integration listens for a *published Release*, not a bare tag push.

PlasBench does not publish to PyPI. An earlier attempt at PyPI Trusted
Publishing was removed after every real attempt failed with
`invalid-publisher` and the project was never actually reachable at
pypi.org/project/plasbench -- a `continue-on-error` step that always fails
silently is worse than no step, since it lets a broken channel look
configured. The GitHub Release archive is the only Python-package
distribution; see [docs/RELEASES.md](docs/RELEASES.md) for the user-facing
release contract. Re-adding PyPI later is straightforward (register a
pending publisher at
[pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)
for project `plasbench`, owner `ubeffiong`, repository `plasbench`, workflow
filename `release.yml`, leaving the environment name blank unless a matching
`environment:` key is also added to the `publish` job) -- but do that, and
verify it against a real tag, before restoring the workflow step.

## Software archival: the zero-code Zenodo↔GitHub mirror

This is a one-time, account-level setup only the repository owner can do —
no code or workflow is needed once it's toggled on, and `.zenodo.json`
(already committed at the repo root) supplies the metadata Zenodo reads.

1. Sign in (or create an account) at [zenodo.org](https://zenodo.org) using
   your GitHub login, so the two accounts are linked.
2. Go to [zenodo.org/account/settings/github](https://zenodo.org/account/settings/github/)
   and flip the toggle on for this repository.
3. Push a `v*` tag as above. Once `release.yml` publishes the GitHub
   Release, Zenodo automatically archives that release's source snapshot,
   mints a DOI, and lists it as a new version of the same Zenodo record on
   every subsequent tag.
4. Add the resulting DOI badge to `README.md` (Zenodo's record page gives
   you the exact Markdown snippet) once the first release has archived.

Nothing else in this repository needs to change for this layer — it is
purely a GitHub-side and Zenodo-side toggle.

## Data archival: cohort snapshots via the Zenodo API

Separate from the software mirror above: `.github/workflows/zenodo-upload.yml`
uploads a tarball of the released `cohorts/*.tsv` and `*.lock.json` files as
its own citable Zenodo deposition (its own DOI, tagged `dataset` rather than
`software`), on every published GitHub Release. This is opt-in and requires
one repository secret:

1. At [zenodo.org/account/settings/applications/tokens/new](https://zenodo.org/account/settings/applications/tokens/new),
   create a personal access token with the `deposit:write` and
   `deposit:actions` scopes.
2. In this repository's GitHub settings, add it as a secret named
   `ZENODO_TOKEN` (Settings → Secrets and variables → Actions → New
   repository secret).
3. From then on, every published release triggers `zenodo-upload.yml`,
   which creates a new deposition, uploads the cohort archive, sets its
   metadata, and publishes it. If `ZENODO_TOKEN` is missing, the job fails
   with a clear error rather than silently skipping — remove the workflow
   file entirely if you don't want data archival on releases.

This is unrelated to (and does not replace) the anonymous-contributor
intake system some past design discussion considered — see
[`CONTRIBUTING.md`](CONTRIBUTING.md) for how new isolates actually get added
to a cohort today, and its "What this is not" note for why that stays a
manual, reviewed workflow rather than an automated one at the project's
current scale.
