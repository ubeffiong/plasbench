# PlasBench public cohorts

Two panels are published here. They differ in curation grade, not in the
evidence rules applied to them — every row in both files passes the same
`validate-cohort --online` checks.

| Panel | Rows | Tier | Use it for |
|---|---:|---|---|
| [`public-v1.tsv`](public-v1.tsv) | 10 | all A | reproducible headline results and citation |
| [`public-v2.tsv`](public-v2.tsv) | 32 | 10 A + 22 B | broader organism and geographic coverage |

`public-v1` is frozen. Do not add rows to it: published results reference it by
name, and its lock file certifies that exact sheet. New isolates go into
`public-v2` or a panel of your own.

## public-v1 — reviewed seed panel

Ten complete hybrid references with plasmid replicons and matched paired-end
Illumina runs: nine clinical *Escherichia coli* isolates and one food-associated
*Salmonella* Tennessee isolate. Intentionally a seed panel, not a claim of
global representativeness.

Every row is **tier A**: all deposited-evidence checks pass *and* `source_study`
names a reviewed publication or collection.

## public-v2 — extended working panel

The ten v1 rows plus 22 additional isolates discovered from public NCBI data,
covering six organisms and five African countries.

```
tier  10 A          17  Escherichia coli            9  Egypt
tier  22 B           5  Salmonella enterica         4  South Africa
                     5  Klebsiella pneumoniae       4  Nigeria
                     3  Acinetobacter baumannii     3  Tanzania
                     1  Staphylococcus aureus       2  Kenya
                     1  Salmonella ser. Tennessee
```

The 22 added rows are **tier B**: every NCBI evidence check passes — complete
assembly, declared plasmid replicons, explicit long-read sequencing evidence,
and a matched paired-end Illumina run on the same BioSample and BioProject —
but no source publication has been reviewed. Their `source_study` is empty, and
`validate-cohort --online` derives and enforces tier B accordingly.

**Promoting a row to tier A** means reviewing its publication, recording it in
`source_study`, and re-running `--online --write-lock`. The validator then
derives tier A and requires the declared value to match.

Known limitations, stated plainly:

- **Study-clustered.** The 22 rows come from 11 BioProjects, and one supplies a
  disproportionate share. Use `plasbench review-candidates` with per-BioProject
  caps before treating them as independent observations.
- **Still *E. coli*-weighted.** 17 of 32 rows. Better than v1's 9 of 10, not
  balanced.
- **No `read_depth_x`** on the added rows. Stage 2 measures observed coverage
  into `observed_depth.tsv`; run it before any depth-ladder work.
- **Geography is from deposited metadata**, not curator-verified provenance.

## Verification

Both panels ship a machine-readable lock recording the NCBI evidence retrieved
at verification time. Check a sheet against its lock before trusting it:

```bash
plasbench validate-cohort --samples cohorts/public-v1.tsv \
  --verify-lock cohorts/public-v1.lock.json
plasbench validate-cohort --samples cohorts/public-v2.tsv \
  --verify-lock cohorts/public-v2.lock.json
```

A checksum mismatch means the sheet changed after verification. Regenerate the
lock only after an intentional edit:

```bash
plasbench validate-cohort --samples cohorts/public-v2.tsv --online \
  --write-lock cohorts/public-v2.lock.json
```

## Running a panel

```bash
plasbench run --cohort public-v1    # reproducible headline results
plasbench run --cohort public-v2    # broader coverage
```

`--cohort NAME` is shorthand for `--samples cohorts/NAME.tsv`; the explicit
`--samples cohorts/public-v1.tsv` form still works identically. The pipeline
downloads source assemblies and reads on demand into the configured `data/`
directory. Raw inputs are not committed: they are large and already publicly
hosted by NCBI.

To see (or edit) the exact commands PlasBench would run instead of running
them immediately, add `--write-script`:

```bash
plasbench run --cohort public-v1 --write-script run_public_v1.sh
bash run_public_v1.sh   # after reviewing or editing it
```

## Sources

**public-v1**

- Uropathogenic *E. coli* PF isolates: NCBI BioProject
  [PRJNA636382](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA636382), which
  provides complete genomes and paired Illumina/ONT reads from recurrent UTI.
- AR Bank 0346: NCBI BioProject
  [PRJNA554345](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA554345).
- AR Bank 0349: NCBI BioProject
  [PRJNA554502](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA554502).
- Food-associated *Salmonella* Tennessee: NCBI BioProject
  [PRJNA802760](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA802760).

**public-v2 additions** span 11 BioProjects: PRJEB3215, PRJEB59926,
PRJNA186035, PRJNA231221, PRJNA287968, PRJNA503964, PRJNA593981, PRJNA1117783,
PRJNA1128891, PRJNA1266646, PRJNA1321367. Each row's own BioProject is recorded
in the sheet; per-row publication review is what remains to promote these to
tier A.

`read_depth_x`, where present, is a rounded estimate from selected SRA bases
divided by complete assembly length. It supports dashboard stratification and is
not a QC claim; stage 2 computes measured coverage independently.
