# Open Cohorts

PlasBench does not prescribe a fixed organism, country, host, or sample source.
Every user can validate and run their own cohort. A publishable cohort sheet
requires the eight fields in `config/accessions.tsv`; aim to include diverse
organisms, hosts, geographies, plasmid sizes, and clinical/environmental sources.

Validate locally:

```bash
python python/validate_cohort.py --samples config/accessions.tsv
python python/validate_cohort.py --samples config/accessions.tsv --online
```

`--online` checks that the Assembly, SRA, BioSample, and BioProject accessions
exist at NCBI. It does not prove isolate matching; curators must confirm that
the assembly and reads derive from the same isolate using BioSample attributes,
strain/isolate names, collection metadata, and associated publications.
