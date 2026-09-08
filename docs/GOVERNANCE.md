# Governance and Cohort Releases

## Purpose

PlasBench is a neutral evaluation framework. Tool authors, database providers,
and cohort contributors can contribute evidence, but no contributor's method
receives a privileged score, default rank, or unreviewed operational claim.

## Release requirements

A public cohort release must include a versioned TSV, NCBI verification lock,
accession ledger, cohort card, tool/database versions, complete run manifest,
and rendered report. It must state sample count, species/source/geography
balance, BioProject dependence, truth technology, known exclusions, and whether
results are synthetic, mock, or real. Demo output is never release evidence.

At least two reviewers are required for a public cohort release: a maintainer
for reproducibility and a domain curator for isolate identity, study context,
and truth suitability. A conflict of interest with a benchmarked method must
be declared in the release notes.

## Refresh and retirement

Review adapters, containers, databases, and documentation at least annually.
New tools require a pinned runtime, input/output provenance contract, smoke
test, and regression fixture. Deprecate an adapter rather than silently
changing its semantics. Frozen cohort releases are never edited; corrections
ship as a new version with a migration note.

## Contributions and representation

Contributions are welcome from clinical, veterinary, food, environmental, and
community surveillance programmes. Geographic representation is an explicit
cohort attribute, not an eligibility criterion. Contributors retain appropriate
credit through cohort metadata, citations, and release notes. Raw patient-level
or restricted sequence data must not be committed; use accessions and approved
controlled-access procedures instead.

## Advisory review

For public releases, seek review from microbiology, genomic epidemiology,
bioinformatics, AMR, and data-governance expertise. This is a practical review
standard, not a claim that a formal board already exists.

## Current evidence boundary

The repository's synthetic demo is engineering evidence, not a public
performance claim. A citable real-cohort release becomes appropriate only when
the release requirements above are met and its independently reproducible run
artifacts are published alongside the cohort lock.
