# Scenario-Specific Benchmarks

PlasBench supports broad, user-curated bacterial isolate cohorts. A released
cohort must retain the complete-reference and matched paired-Illumina evidence
requirements in `docs/COHORTS.md`, irrespective of species, Gram
classification, geography, host, plasmid type, or clinical/environmental
origin.

## General Isolate Reconstruction

This is the current fully supported scenario. Build diverse panels with
`plasbench discover-cohort`, `curate-cohort`, and `validate-cohort`, then
report organism, country, source, plasmid size/count, read depth, and truth
technology. Do not promote a candidate into a released panel until its
matched assembly/read evidence and curator-reviewed source metadata are locked.

## Clinical Outbreak Investigations

An outbreak panel can use the same isolate workflow, with a companion metadata
file recording an outbreak identifier, collection window, facility/region, and
case definition. Isolates from one outbreak are correlated, so an outbreak
panel must report that dependence and reserve independent outbreaks for
holdout validation when enough are available.

## Metagenomics

Metagenomics is **not yet an executable PlasBench scenario**. Metagenomic
reads contain multiple organisms and strains, so isolate-level reference
labels and the current one-isolate-per-row score are invalid substitutes. A
future metagenomic benchmark needs separately declared ground truth,
abundance-aware metrics, strain-resolution rules, host-assignment criteria,
and contamination controls. Do not label a metagenomic run as a PlasBench
benchmark result until those rules and a verified cohort are released.

## Strict Reference Metrics

`perfect_reference_recovery` means base F1 and plasmid recall equal 1, with
zero ambiguous, unmapped, or off-truth predicted bases.
`strict_reference_reconstruction` additionally requires perfect available bin
evidence and zero split, merge, contamination, and repeat-ambiguity events.
These are quality screens, not claims of nucleotide-identical sequence,
validated closure, or clinical fitness. They are reported with the number of
assessable samples and never replace the primary F1 ranking.
