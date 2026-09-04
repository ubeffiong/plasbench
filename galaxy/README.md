# PlasBench for Galaxy

Three wrappers covering the steps a Galaxy workflow needs:

| Tool | Does | Produces |
|---|---|---|
| `plasbench_align` | minimap2 a predicted-plasmid FASTA onto the complete reference | PAF |
| `plasbench_score` | score that prediction against labelled truth | per-sample/tool scores |
| `plasbench_aggregate` | combine score rows across samples and tools | ranked leaderboard |

Chain them: **align → score → aggregate**. `macros.xml` holds the shared version
tokens, the conda requirement and the alignment-filter parameters, so the align
and score steps cannot drift apart on filtering.

## Dependencies

Every tool declares a single conda requirement:

```xml
<requirement type="package" version="@TOOL_VERSION@">plasbench</requirement>
```

The conda package installs the CLI, the per-step entry points
(`plasbench-score`, `plasbench-aggregate`) and the pipeline scripts under
`$PREFIX/share/plasbench`. `plasbench/tools.py` locates them at run time, so the
wrappers call a command on `PATH` rather than an absolute path inside a
container image. The recipe is in [`../recipes/bioconda`](../recipes/bioconda).

## Deliberately out of scope

Stages that download from NCBI, assemble reads, or run for hours are **not**
wrapped. Galaxy jobs should not fetch reference data at run time, and an
opaque multi-hour tool is a poor fit for a workflow system. Use the command-line
pipeline for those, and Galaxy for the scoring and comparison steps.

Stratified breakdowns need the curated cohort sheet and stay on the command line.

## Before publishing to the Tool Shed

1. Publish the bioconda package so `plasbench` resolves as a conda requirement.
2. `planemo lint galaxy/*.xml` — currently clean.
3. `planemo test galaxy/*.xml` — requires conda dependency resolution, so run it
   after step 1.
4. `planemo shed_init`/`shed_update` against `.shed.yml` (owner already set).

A public workflow should use preloaded, versioned MOB-suite and Platon
databases; jobs must not download databases at run time.
