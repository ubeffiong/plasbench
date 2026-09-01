# Open Cohorts

PlasBench does not prescribe a fixed organism, country, host, or sample source.
Every user can validate and run their own cohort. A publishable cohort sheet
requires the eight core fields in `config/accessions.tsv`; aim to include diverse
organisms, hosts, geographies, plasmid sizes, and clinical/environmental sources.

`sample_origin` and `read_depth_x` are optional columns. Origin accepts your own
free-text cohort labels rather than a fixed vocabulary; depth is numeric fold
coverage. The final report uses them for filters and preserves them in its CSV
export. True plasmid-size filters are calculated directly from each reference's
truth table, rather than relying on a manually entered size.

Validate locally:

```bash
python python/validate_cohort.py --samples config/accessions.tsv
python python/validate_cohort.py --samples config/accessions.tsv --online
plasbench validate-cohort --samples cohorts/public-v1.tsv --online
```

`--online` verifies that the assembly is complete and plasmid-containing, the
selected run is paired-end Illumina, and the Assembly/SRA BioSample and
BioProject identifiers exactly match the cohort row. It cannot prove biological
identity beyond deposited metadata; curators should still review strain/isolate
names, collection metadata, and associated publications.

## Versioned public panel

[`cohorts/public-v1.tsv`](../cohorts/public-v1.tsv) is a ten-isolate, directly
runnable seed cohort with an accompanying NCBI verification lock. It includes
clinical and food-associated isolates, varies in plasmid count and read depth,
and is intentionally small enough for an initial reproducible benchmark. Read
[`cohorts/README.md`](../cohorts/README.md) before using it or extending it.

```bash
plasbench validate-cohort --samples cohorts/public-v1.tsv --online \
  --write-lock cohorts/public-v1.lock.json
plasbench run --samples cohorts/public-v1.tsv
```
