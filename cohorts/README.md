# PlasBench public-v1 cohort

`public-v1.tsv` is a small, directly runnable public release panel. It contains
ten complete hybrid references with plasmid replicons and matched paired-end
Illumina runs: nine clinical *Escherichia coli* isolates and one food-associated
*Salmonella Tennessee* isolate. It is intentionally a seed panel, not a claim
of global representativeness.

Every row must pass `python python/validate_cohort.py --online`, which verifies:

- a complete NCBI assembly with plasmid replicon(s) in its assembly report;
- exact agreement of the recorded BioSample and BioProject between the assembly
  and selected SRA run; and
- paired-end Illumina library metadata.

The checked-in `public-v1.lock.json` is the machine-readable NCBI verification
evidence for this release. Regenerate it after intentionally changing the TSV:

```bash
python python/validate_cohort.py --samples cohorts/public-v1.tsv --online \
  --write-lock cohorts/public-v1.lock.json
```

Run the cohort without modifying the template sheet:

```bash
plasbench run --samples cohorts/public-v1.tsv
```

The pipeline downloads the source assemblies and reads on demand into the
configured `data/` directory. The raw inputs are not committed because they are
large and are already publicly hosted by NCBI.

## Sources

- Uropathogenic *E. coli* PF isolates: NCBI BioProject
  [PRJNA636382](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA636382), which
  provides complete genomes and paired Illumina/ONT reads from recurrent UTI.
- AR Bank 0346: NCBI BioProject
  [PRJNA554345](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA554345).
- AR Bank 0349: NCBI BioProject
  [PRJNA554502](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA554502).
- Food-associated *Salmonella Tennessee*: NCBI BioProject
  [PRJNA802760](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA802760).

`read_depth_x` is a rounded estimate from selected SRA bases divided by complete
assembly length; it supports dashboard stratification and is not a QC claim.
