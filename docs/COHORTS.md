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

## Strict candidate screening

For a 40-60 isolate public release, start with a broad candidate table rather
than adding unverified rows to a released cohort. It must have
`assembly_accession` and `sra_run`; `sample_id`, `sample_origin`,
`read_depth_x`, and `source_study` may be included when known:

```bash
plasbench curate-cohort --candidates candidates.tsv --out-dir curation \
  --email you@example.org --truth-technology hybrid --quality-tier A
```

This creates `curation/accepted.tsv` only when the exact complete plasmid
reference, BioSample, BioProject, Illumina platform, and paired-end rules all
pass. `curation/rejected.tsv` retains every unsuitable candidate and its reason.
Review accepted isolate names, source publication, origin, truth technology,
and read-depth calculation; then validate and lock the reviewed table:

```bash
plasbench validate-cohort --samples curation/accepted.tsv --online \
  --write-lock curation/accepted.lock.json
```

This workflow keeps cohort scope broad and user-defined while preventing a
candidate list from being misrepresented as a verified benchmark release.

## Automated NCBI discovery

With an NCBI API key, PlasBench can discover strict deposited pairs before the
manual publication review. Store credentials in a local ignored `.ncbi.env`
file or export `NCBI_API_KEY` and `NCBI_EMAIL`, then search the required broad
panel without imposing a geographic or source restriction:

```bash
plasbench discover-cohort --out-dir curation/ncbi-round1 --max-assemblies 40 \
  --organism "Klebsiella pneumoniae" \
  --organism "Acinetobacter baumannii" \
  --organism "Pseudomonas aeruginosa" \
  --organism "Enterococcus faecium" \
  --organism "Staphylococcus aureus"
```

The command writes `accepted.tsv` and `rejected.tsv`; acceptance proves the
deposited metadata linkage only. Curators must still check publications and
collection metadata before assigning origin, truth technology, quality tier, or
making a public release claim.

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
