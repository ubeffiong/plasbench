# PlasBench: a reproducible, evidence-calibrated framework for benchmarking plasmid-reconstruction tools

**Draft Software Tool Article for F1000Research, written from the repository at version 0.5.6.** Every statement below is checked against the code, the documentation
or a test in this repository; where the repository does not say, the text says so. Items in square brackets are for the author to fill in or confirm: they are facts
that only the author or the author's institution can supply, and none of them has been guessed.

**Author:** Ubokobong Effiong [ORCID: add]. [Affiliation: add the form your institution has authorised. `ACKNOWLEDGMENTS.md` records that no institutional ownership,
funding, sponsorship or endorsement is to be stated without written authorisation.]

**Keywords:** plasmid, benchmarking, genome assembly, plasmid reconstruction, antimicrobial resistance, reproducibility, workflow

---

## Abstract

**Background.** Many tools predict which sequences of a bacterial genome are plasmid. They are usually compared on different isolates, with different definitions of
accuracy, so the numbers cannot be put side by side. A tool can also score well on bases while returning few intact plasmids.

**Methods.** PlasBench reduces every tool, whether a classifier, a binner or a re-assembler, to one predicted-plasmid FASTA and projects it back onto a complete
(long-read or hybrid) reference whose sequences are labelled plasmid or chromosome from the NCBI sequence report, never by a tool under test. It reports base-level
precision, recall and F1 next to plasmid-level recovery and structural measures, records the evidence tier of every reference, keeps short-read, long-read and hybrid
results apart, and writes an offline HTML report. It is a Python command-line program and a local browser window around Bash and Python stages, installable with conda or
as a container image, with Galaxy and CWL wrappers for the scoring steps.

**Results.** The framework is implemented and released under GPL-3.0-only; this article describes the software and its operation, and a synthetic demonstration that
runs without the internet. It makes no claim about which plasmid tool is best.

**Conclusions.** PlasBench gives laboratories a common, auditable way to compare plasmid-reconstruction tools on their own isolates. Its limits are stated in the
Discussion.

---

## Introduction

Plasmids carry antimicrobial-resistance genes and move between bacteria, so recovering them from short-read sequencing matters for surveillance. Short reads assemble
plasmids poorly because plasmids share repeats with each other and with the chromosome, and a family of tools has appeared to classify contigs, bin them or re-assemble
them. A user choosing among them meets three problems: the tools are evaluated on different data; "accuracy" is counted differently (per contig, per base, per plasmid); and
the truth is often defined by a method that resembles one of the tools being tested.

PlasBench addresses these by fixing one scoring contract for every tool and by recording, for each reference, how good the evidence for its labels is. It is a benchmark
harness, not a plasmid caller: it does not identify the plasmids in a sample, infer outbreaks or transmission, or confirm that a candidate is a real closed plasmid.

## Methods

### Implementation

**Truth.** For each isolate a complete long-read or hybrid assembly is the reference. Each reference sequence is labelled plasmid or chromosome from the
`assigned_molecule_location_type` field of the NCBI sequence report (`python/make_truth.py`). A sequence that cannot be labelled unambiguously is written as `REVIEW`
and stops the stage until a person decides, rather than being defaulted to chromosome (`docs/METHODS.md`). An assembly without explicit evidence of long-read or hybrid
sequencing is rejected as truth: "Complete Genome" alone is not accepted.

**One contract for every tool.** Each tool's output is normalised to a single predicted-plasmid FASTA and aligned to the reference with minimap2. Every predicted base is
projected onto the reference through the alignment, giving a base-level confusion matrix with the plasmid class as positive: true positives are true plasmid bases
claimed, false positives are chromosomal bases claimed, false negatives are true plasmid bases missed. Predicted bases that do not map, or map off the labelled truth, are
reported but are never counted as false positives; redundant coverage is a diagnostic, not a penalty. The same table carries plasmid-level recovery (the fraction of
individual plasmids recovered to a completeness threshold), binning and structural measures. The best-match precision, recall and F1 and the normalised dissimilarity are
re-implemented from the published definitions of PlasEval and were compared with the original program on Linux: they agreed in all 59 constructed and random cases (44 with
repeated contigs), and on the paper's 53 *E. coli* isolates 210 of 211 pairs agree within 0.001 and none disagree (`FAQ.md`, Q2 and Q31). The comparison test runs only when
`PLASEVAL_SRC` points at a PlasEval checkout, so the project's continuous integration skips it.

**Tools.** The registry (`config/tool_capabilities.tsv`) holds 28 entries: 20 reconstruction or classification tools (among them MOB-suite `mob_recon`, Platon, plasmidSPAdes,
gplas2, geNomad, PLASMe, RFPlasmid, PlasmidHunter, Plasmer, PlaScope, plASgraph2, PlasmidEC, plsmd, plasbin-flow, and the long-read and hybrid routes Flye with MOB-suite,
Plassembler, Hybracter and Trycycler), three trivial baselines and five synthetic demonstration tools. A tool you add yourself is declared in a manifest and joins the same
scoring (`docs/ADDING_TOOLS.md`). Tools are installed on request, with consent, into isolated environments from pinned versions or exact commits.

**Reporting.** Results are never pooled across input tracks: one leaderboard per track (short-read, long-read, hybrid), ranks within each, confidence intervals from
resampling isolates, and a flag when a difference is not supported. A separate graph-aware workflow scores metagenomic community bins (`docs/METAGENOMICS.md`).

**Software.** Pipeline stages 0 to 8 in Bash and Python (setup, download, truth, assembly, tools, scoring, aggregation, long-read reconstruction, operational reconstruction), a Python package (`plasbench`) with per-step entry points (`plasbench-score`, `plasbench-aggregate`), and a
local web window served on 127.0.0.1 with a token. The Python scoring code uses the standard library only. The repository holds 475 test scripts (counted at v0.5.6); the
tests run on Python 3.9, 3.11 and 3.13 in continuous integration.

### Operation

*System requirements* (README, section 3): Linux, macOS, or Windows with WSL 2 or Docker; at least 4 CPU cores, 8 GB RAM and 30 GB free disk (16-32 GB RAM and 60-100 GB
comfortable; SPAdes memory scales with read count, and some optional tools document larger minimums, for example 32 GB for Plasmer); internet for downloading isolates and
installing tools (scoring itself is offline).

*Installation.* From the release archive or the container image `ghcr.io/ubeffiong/plasbench:v0.5.6`:

```bash
plasbench check --yes        # checks the machine, installs missing tools and databases with consent
plasbench demo               # a synthetic end-to-end run that needs no internet
plasbench run --cohort <cohort>   # download, build truth, assemble, run tools, score, report
```

`plasbench ui` opens the local window (workflow switches, tool installation, run monitoring, report). The scoring steps are also available as Galaxy tools (`galaxy/`) and as
a CWL workflow (`workflows/cwl/`, runnable with `cwltool`).

## Use cases

1. **Demonstration without data.** `plasbench demo` generates a synthetic cohort with five synthetic tools and produces the full report; a sample report is in
   `docs/sample_report/`. The demonstration shows the outputs and checks that the software runs; it says nothing about real tools.
2. **Scoring a tool's output you already have.** `plasbench-score` and `plasbench-aggregate` (or the CWL workflow) score one predicted-plasmid FASTA per tool for an isolate
   against its labelled reference. On the synthetic isolate that ships with the Galaxy wrappers (a 3,000 bp plasmid, a 4,000 bp chromosome and a prediction equal to the
   plasmid) the workflow returns precision, recall and F1 of 1.0, as it should; this was run in containers with `cwltool` on 21 November 2026.
3. **Benchmarking tools on your own isolates.** A cohort of isolates with reads and a complete reference is declared, `plasbench run` carries out the stages, and the
   report ranks the tools within each input track with the evidence tier of each reference shown. [AUTHOR: add one worked example with real isolates and the resulting
   report, with the accessions, if you want a results section; this draft contains none. The repository holds a 10-isolate real run (`results_real_cohort1`, FAQ Q22), which
   shows the pipeline works on real reads but is too small to rank tools.]

## Discussion

PlasBench makes the comparison of plasmid tools comparable and auditable; it does not decide which tool is best, and no such claim is made here.

*Limitations.* Truth labels depend on the quality of the reference and the NCBI annotation, which is why each reference carries an evidence tier and why the primary analysis
admits only references that pass both a quality and an independence check. Results on a small or species-skewed cohort are not general: the repository documents that few
species reach the species-balanced minimum in the current public cohorts. The synthetic demonstration validates the software, not the tools. Several optional tools document
large memory requirements, and Docker or conda installation of tools can fail for reasons outside PlasBench (network, disk, permissions); the program classifies the common
failures and says what to do. The graphical window and the container route have been tested with fakes and in continuous integration, not by a user study.

*Related work.* PlasBench re-implements, from the published definitions, the quantities of PlasEval (Mane et al., BMC Bioinformatics 2024; no PlasEval code is used) and
checks itself against that program as described in the Methods [AUTHOR: confirm the citation details before submission]. It does not replace the individual tools it runs.

*Future work.* More species in the cohorts, a completed real-data run with published results, and Galaxy Tool Shed, Bioconda and WorkflowHub releases.

## Software availability

- **Software available from:** https://github.com/ubeffiong/plasbench (release v0.5.6: https://github.com/ubeffiong/plasbench/releases/tag/v0.5.6)
- **Container image:** `ghcr.io/ubeffiong/plasbench:v0.5.6`
- **Source code available from:** https://github.com/ubeffiong/plasbench
- **Archived source code at time of publication:** [DOI: create it by archiving a release with Zenodo, see `docs/publishing/README.md`; F1000Research requires an archived copy with a
  DOI at submission]
- **License:** GPL-3.0-only (an OSI-approved open-source licence)
- **Operating systems:** Linux, macOS; Windows through WSL 2 or Docker
- **Programming languages:** Python (3.9 or newer), Bash
- **Other requirements:** conda or Docker for the third-party tools; internet for downloading data and installing tools

## Data availability

The synthetic demonstration data are generated by the software and need no download. The public cohorts are lists of NCBI accessions with their checksummed locks under
`cohorts/` (for example `public-v4`, 7,227 candidate isolates resolved from NCBI); the reads and reference assemblies are downloaded from NCBI at run time and are not
redistributed. [AUTHOR: if a worked example is added, deposit its accession list and result tables in a repository such as Zenodo and cite the DOI here.]

## Competing interests

[AUTHOR: state your competing interests, or "No competing interests were disclosed."]

## Grant information

[AUTHOR: state funding, or "The author(s) declared that no grants were involved in supporting this work."]

## Acknowledgements

[AUTHOR: confirm the wording with your institution; `ACKNOWLEDGMENTS.md` holds the approved text for the repository.]

## References

[AUTHOR: add the references for the tools named above, for minimap2 (Li, Bioinformatics 2018, doi:10.1093/bioinformatics/bty191) and for PlasEval. This draft does not
reproduce references it has not verified.]
