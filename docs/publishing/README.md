# Publishing PlasBench to other platforms

What was asked: is PlasBench fit to be published on Galaxy, bio.tools, WorkflowHub / BioContainers, F1000Research and BioBuntu? Short answer, checked on 21 November 2026
against v0.5.6: **the files each platform needs now exist and were checked, but every platform needs one step that only the maintainer can take** (an account, a token, a
submission, a DOI). Nothing here has been submitted anywhere. BioBuntu is the exception: it offers no way for a third-party tool to be added, so there is nothing to submit.

| Platform | Ready in the repository | What was verified | What only you can do |
| --- | --- | --- | --- |
| **Galaxy** (Tool Shed) | three tool wrappers (`galaxy/`), `.shed.yml`, test data | `planemo lint` on all three: no warnings or errors (planemo 0.75.48) | Bioconda must carry `plasbench` first (the wrappers require it); then `planemo test`, and `planemo shed_update` with your Tool Shed account and API key |
| **bio.tools** | `docs/publishing/biotools.json` | validates against the official biotoolsSchema JSON schema (draft 4); every EDAM term was looked up in the current EDAM release and is not deprecated | register it (bio.tools account; paste the JSON or use the API); the ID `plasbench` is the one the Bioconda recipe already declares |
| **Bioconda / BioContainers** | `recipes/bioconda/meta.yaml` for v0.5.6 with the real SHA-256 of the release archive | the recipe's build script and test commands were run on the v0.5.6 archive in an emulated prefix: build succeeds, `plasbench --version`, `plasbench-score --help`, `plasbench-aggregate --help` and the file checks pass | open the pull request to `bioconda/bioconda-recipes` from your fork; BioContainers then builds `quay.io/biocontainers/plasbench` from the merged recipe by itself |
| **WorkflowHub** | CWL workflow `workflows/cwl/plasbench-score.cwl` (+ four tools, a job file, test data), `python/make_workflow_crate.py` builds `dist/plasbench-score.crate.zip` | `cwltool --validate` passes; the workflow ran end to end in containers (minimap2 biocontainer and the PlasBench v0.5.6 image) and scored the synthetic isolate with precision, recall and F1 of 1.0 | register on workflowhub.eu (account and a project/team): upload the crate or import the Git repository |
| **F1000Research** | draft Software Tool Article `docs/publishing/f1000research-software-tool-article.md` | every claim traced to the repository (the PlasEval agreement numbers, tool counts, requirements, limits) | an archived copy with a DOI (Zenodo), your ORCID and approved affiliation, competing interests, funding, references; optionally a worked real-data example |
| **BioBuntu** | nothing: not applicable | read the project's site, README and pipeline documentation (see below) | nothing, unless the project documents a way to add a tool |

## Also changed to make this work

* **A bug found by running the workflow in the container:** `plasbench-score` and `plasbench-aggregate` could not find the pipeline files unless started in `/opt/plasbench`, which is
  how Galaxy and CWL call them. The `Dockerfile` now sets `PLASBENCH_HOME=/opt/plasbench` (images from the next release on); the CWL tools set it themselves, so they work with the
  existing v0.5.6 image.
* **The Bioconda recipe was stale** (version 0.1.5, a placeholder checksum, a second out-of-date template). It is now v0.5.6 with the release-asset URL and a real checksum;
  the template was removed so there is one source of truth.
* **`.zenodo.json`** named the licence `GPL-3.0-only`; Zenodo's own vocabulary id is `gpl-3.0-only` (the capitalised form returns 404 there), so it is corrected, and the cohort-data
  workflow's `CC-BY-4.0` became `cc-by-4.0` for the same reason. This was checked against Zenodo's public vocabulary, not by a live deposit: the first Zenodo release will show it.
* `test/test_publishing.py` keeps all of this in step with each release; `python/sync_publishing_versions.py` rewrites the versions in the bio.tools entry and the CWL files, and
  `docs/RELEASING.md` lists the steps.

## Platform by platform

### Galaxy
`galaxy/` has `plasbench_align`, `plasbench_score` and `plasbench_aggregate`: minimap2 alignment of a predicted-plasmid FASTA, scoring, and a ranked leaderboard. Stages that download
data, assemble reads or run for hours are deliberately not wrapped (`galaxy/README.md`). Remaining order of work: (1) Bioconda package merged (below); (2) `planemo test galaxy/*.xml`
(it needs the conda package, so it could not be run here); (3) `planemo shed_update` with `owner: ubeffiong` already in `.shed.yml`. Galaxy's own review of a Tool Shed repository is
outside this repository's control.

### bio.tools
`biotools.json` describes the tool (topics Genomics, Microbiology, Sequence assembly, Metagenomics, Antimicrobial resistance, Public health; operations Validation, Comparison, Sequence
classification, Read binning, Sequence assembly, Genome annotation, Aggregation). Choices to review before registering: the licence is written `GPL-3.0` because that is the closest
value in bio.tools' list (the repository's licence is GPL-3.0-only); the tool types are Command-line tool, Web application (the local window) and Workflow; no ELIXIR platform or
collection is claimed; no publication is listed because there is no DOI yet; no e-mail address is included.

### Bioconda and BioContainers
Copy `recipes/bioconda/` to `recipes/plasbench/` in your fork of `bioconda-recipes` and open the pull request. Bioconda's reviewers will run their own linter and a real `conda-build`,
which were not available here: the build was emulated with `pip --prefix` on Linux, so a layout difference in a real conda prefix is possible. The recipe is `noarch: generic` and
installs the pipeline under `$PREFIX/share/plasbench` (`recipes/bioconda/build.sh`).

### WorkflowHub
Run `python3 python/make_workflow_crate.py` to write `dist/plasbench-score.crate.zip` (a Workflow RO-Crate: the CWL workflow, its tools, a job file, test data, licence, README and
`ro-crate-metadata.json` following the WorkflowHub profile; the crate is checked by `--check` and by the tests). Test it yourself with
`cwltool workflows/cwl/plasbench-score.cwl workflows/cwl/plasbench-score.job.yml`. WorkflowHub's own registration form decides the project and team. Only the scoring steps are a
workflow: the full pipeline downloads data and runs for hours, which a workflow registry is a poor home for.

### F1000Research
F1000Research publishes Software Tool Articles; their guidelines require an open licence, a permanent archived copy of the software with a DOI (Zenodo is the usual one), and a
"Software availability" section. The draft follows that structure. **Before submitting:** connect the GitHub repository to Zenodo and publish a release so that
`.zenodo.json` creates the DOI (see `docs/RELEASING.md`), fill in the bracketed author items, and re-read the journal's current guidelines (the wording on licences and structure
should be checked at submission; it was read from search results, not from the full checklist). One inconsistency to settle first: `FAQ.md` Q22 says no real-data run exists, while the
repository also holds `results_real_cohort1` (10 isolates, PlasBench 0.2.3, run-level tables only, see `docs/COHORT1_REBUILD_STATUS.md`); a reviewer will see both.

### BioBuntu
BioBuntu (`biobuntu.github.io`, PyPI `biobuntu`, MIT licence) is a small Python platform with a CLI, a desktop window and a web dashboard that runs YAML pipelines of built-in tool
wrappers (FastQC, BWA, GATK, HISAT2, Samtools and others). Its pipeline file is `name`, `description` and `steps` (each with `name`, `tool`, `depends_on`, `args`), and
`biobuntu validate` checks that tool names are valid. **No page read documents how a third-party tool is added** (no wrapper API, no plugin hook, no registry or submission
process), so a PlasBench step would fail validation as an unknown tool, and nothing honest can be prepared. Other caveats: the site says v1.2.4 while the repository's own files refer
to 0.1.0; the repository showed 3 stars, 2 forks and 35 commits; the PyPI page could not be read here (a bot challenge). If you want a listing, ask the BioBuntu maintainers
(issues on `github.com/biobuntu/biobuntu`) whether they accept external tool definitions.

## What was NOT verified

* No submission, registration, upload or pull request was made on any platform, and no account was used.
* `planemo test` (needs a Bioconda package), `bioconda-utils lint` and a real `conda-build` were not run.
* The Galaxy wrappers were linted, not run inside a Galaxy server.
* The CWL workflow was run with `cwltool` in Docker on one synthetic isolate; its zero-failure result says the plumbing works, not that any tool is good.
* The F1000Research guidelines and the Zenodo licence behaviour were checked from public pages and Zenodo's public vocabulary, not by a submission or a deposit.
* Nothing was checked in a browser.
