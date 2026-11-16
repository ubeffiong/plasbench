# PlasBench implementation catalogue

**What this is.** One document that lists everything PlasBench implements: what each capability does, why it exists, which files hold it, which setting
turns it on, which output it writes, where the HTML report shows it, which test checks it, and what it does *not* do. It is written for a reviewer, a
funder, a collaborator or a new user who has not read the code and should not have to.

**Why it exists.** Reviewers repeatedly asked for things PlasBench already did, because the work was spread over a README, a FAQ, a scientific guide,
a methods file, a changelog and the code. This catalogue is the index to all of them. It does not replace them: each section links to the document that
explains the method in depth.

**Size at the time of writing:** {modules} analysis modules, {tools} registered tools and baselines ({real_tools} real tools), {outputs} registered
outputs, {switches} run switches, {tests} test files and {prs} merged pull requests. Sections 5 to 9 are generated from the repository itself, and a
test (`test/test_implementation_catalogue.py`) fails if a module, a tool or an output is missing from them, so they cannot silently go out of date.

## 1. How to read this document

**Status words** (the same meanings as in the FAQ and in [the reviewer assessment matrix](REVIEWER_ASSESSMENT_MATRIX.md)):

| Word | Meaning |
|---|---|
| **Implemented and tested** | The code exists and a test in `test/` exercises it. |
| **Implemented, not validated on real data** | It works on constructed or synthetic cases; no real-cohort result exists yet. |
| **Provisional** | A setting or threshold that is a stated convention, not derived from data. It is recorded with every run. |
| **Open** | Not done. The reason is given. |

**What "tested" does and does not mean.** A test shows the code does what its author intended on the cases the test builds. It does not show that the
scientific claim holds on real data. The one thing that has been checked against an independent reference implementation is the PlasEval-style binning
dissimilarity (section 3.8). No real-data run of the whole tool set has been made yet; that is the largest open item and it is stated again in section 11.

**Descriptive versus scoring.** Many analyses here are *descriptive*: they add a table or a figure and never change a score or a ranking. Where that is
true the section says so. The scores and rankings come from a small, fixed core (sections 3.2 to 3.4).

**Where to start, by question**

| If you want to know... | Open |
|---|---|
| What PlasBench claims and does not claim | [`SCIENTIFIC_GUIDE.md`](SCIENTIFIC_GUIDE.md) |
| How every score is computed | [`METHODS.md`](METHODS.md) |
| The answer to a specific reviewer question | [`../FAQ.md`](../FAQ.md) and [`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md) |
| Who reviewed the project and what validated each answer | [`EXTERNAL_REVIEW_LOG.md`](EXTERNAL_REVIEW_LOG.md) |
| A sceptical outside view of the weaknesses | [`INDEPENDENT_REVIEW.md`](INDEPENDENT_REVIEW.md) |
| How to install and run it | [`../README.md`](../README.md) |
| What changed in each release | [`../CHANGELOG.md`](../CHANGELOG.md) |

## 2. The pipeline in one table

PlasBench benchmarks tools that reconstruct or classify plasmids from sequencing data. For each isolate it has a **complete reference genome of the same
isolate** (the truth), runs the tools on a short-read assembly built from the isolate's reads, and scores each tool's predicted plasmid sequence against
the truth. It never compares one isolate's plasmids with another's, and it is not a diagnostic or an epidemiological tool.

| Stage | Script | What happens | Main outputs |
|---|---|---|---|
| 0 | `scripts/00_setup.sh` | Create folders, check required tools and databases, offer to install what is missing | `results/` layout |
| 1 | `scripts/01_download.sh` | Download each isolate's complete reference and matched Illumina reads; a failed download is recorded and skipped, not fatal | `data/<sample>/`, `download_status.tsv` |
| 2 | `scripts/02_truth.sh` | Label every reference sequence plasmid or chromosome; annotate replicons, MOB, IS elements and AMR genes; detect multimers; measure repeat content and depth anomalies | `truth.tsv`, `truth_features.tsv`, label-scheme and audit tables |
| 3 | `scripts/03_assemble.sh` | **Short-read QC gate**, quality trimming, assembly, assembly measurement and **assembly selection policy** | `short_read_qc.tsv`, `assembly_candidates.tsv`, `assembly_status.tsv` |
| 4 | `scripts/04_run_tools.sh` | Run each enabled tool; skip samples rejected by QC or without an eligible assembly, saying why; write one standard predicted-plasmid FASTA per tool | `<sample>/pred_<tool>.plasmid.fasta`, `tool_status.tsv` |
| 5 | `scripts/05_score.sh` | Map each prediction to the reference with minimap2 and score it at every layer; export bins; analyse candidate multiplicity | `scores.tsv`, per-plasmid tables, bin tables, multiplicity tables |
| 6 | `scripts/06_aggregate.sh` | Combine everything into the leaderboard, statistics, robustness analyses, audits, the PlasEval comparison gate and the HTML report | `benchmark.leaderboard.*`, `benchmark.*.tsv`, the report |
| 7 | `scripts/07_long_read_reconstruct.sh` | Optional native long-read and hybrid reconstruction (Flye, Plassembler, Hybracter, Trycycler) | long-read and hybrid predictions |
| 8 | `scripts/08_operational_reconstruct.sh` | For one new isolate with no truth, run only the single method the benchmark recommends | operational reconstruction and selection report |

`scripts/run_all.sh` runs the stages in order (`bash scripts/run_all.sh 3 4 5` runs only those). The same pipeline can be driven from a window
(`plasbench ui`, section 3.18) or from the command line (`python -m plasbench run`).

