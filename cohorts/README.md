# PlasBench public cohorts

Two panels are published here. They differ in curation grade, not in the
evidence rules applied to them — every row in both files passes the same
`validate-cohort --online` checks.

| Panel | Rows | Tier | Use it for |
|---|---:|---|---|
| [`public-v1.tsv`](public-v1.tsv) | 10 | all A | reproducible headline results and citation |
| [`public-v2.tsv`](public-v2.tsv) | 32 | 10 A + 22 B | broader organism and geographic coverage |
| [`public-v4.tsv`](public-v4.tsv) | 7,227 | all B | the large validation panel: every genome of the contributed pool that verified at NCBI (943 species, 1,818 BioProjects), with recent and older leakage arms and a balanced order; run a slice with `plasbench run --max-isolates N`; see below |
| [`pub-plsmd-novel.tsv`](pub-plsmd-novel.tsv) | 68 | all B | the plsMD paper's novel set (Lotfi et al. 2026): every isolate, truth plasmids exactly the paper's; published recall ships |
| [`pub-plsmd-filtered.tsv`](pub-plsmd-filtered.tsv) | 63 | all B | the plsMD paper's filtered benchmark (80 isolates in the paper), also in the MOB-suite benchmark; published recall ships |
| [`pub-mobsuite.tsv`](pub-mobsuite.tsv) | 95 | all B | the MOB-suite benchmark (Robertson and Nash 2018; 133 genomes in the paper) |
| [`pub-teixeira2025.tsv`](pub-teixeira2025.tsv) | 5 | all B | the 5 of Teixeira et al. 2025's 250 isolates that resolve to a deposited complete assembly (the rest need a rebuilt truth); the paper's calls ship for all 250 |
| [`publication-v1.tsv`](publication-v1.tsv) | 168 | all B | the four publication cohorts together, each isolate once (`published_studies` lists its papers); never pool the studies into one leaderboard |
| [`negative-controls-v1.tsv`](negative-controls-v1.tsv) | 136 | all B | plasmid-free negative controls: RefSeq complete genomes with a single replicon, long-read truth and a paired Illumina run (12 species, 88 BioProjects); for false-positive plasmid calling; see below |
| [`plaseval-ecoli53.tsv`](plaseval-ecoli53.tsv) | 53 | all B | replicating the PlasEval paper's binning comparison and its comparison gate; not a headline panel (truth is a Unicycler hybrid on the same reads; one species). See [`docs/PLASEVAL_REPLICATION.md`](../docs/PLASEVAL_REPLICATION.md) |

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

## public-v4 — the large validation panel (contributed pool)

Every genome of the contributed pool (`candidates/contributed-refseq-sra/`) that passed the offline filters and was verified at NCBI,
selected with `plasbench import-contributed-cohort`, checked with `plasbench resolve-contributed-cohort` and locked by
`validate-cohort --online` (`public-v4.lock.json`, all 7,227 rows passed). Every row is tier B (no source publication reviewed). It was
decided on 2026-11-16 on the project owner's instruction to add everything that is available; it is a cohort choice, not a scoring decision.
`public-v4.selection.json` records how it was selected and `candidates/contributed-refseq-sra/public-v4.precheck.tsv` records every
candidate's NCBI and read-QC outcome. The window's Cohorts page shows both as the **Selection report** pop-up.

* **Size and mix:** 7,227 isolates, 943 species, 1,818 BioProjects. It is not a balanced sample: *E. coli* has 1,360 isolates and 520
  species have one. Use `--max-isolates N` (balanced by default) or the `organism`, `selection_arm`, `panel_subset` and
  `truth_assembly_strategy` columns.
* **Truth:** 3,552 long-read-first rows (2,453 hybrid, 1,099 long-read-only), 2,522 short-read-first and 1,153 unclassified. Only the
  long-read-first rows are headline-eligible; four species have 20 or more such studies (*E. coli* 111, *K. pneumoniae* 58,
  *S. aureus* 35, *S. enterica* 34).
* **Arms:** 1,539 `recent` (public on or after 2025-01-01 on the earlier of assembly and first read) and 5,688 `older`, for the
  leakage comparison. `panel_subset=core` marks the 98 isolates of the first, balanced selection (20 each of *E. coli*, *K. pneumoniae*,
  *S. enterica*, *S. aureus*, 18 *E. hormaechei*).
* **Order:** written in balanced order (`balance_rank`), so the first N rows are a fair miniature of the cohort.
* **Read QC:** the pre-download check passed 7,081 rows and flagged 146 (depth under 30x). Estimated depth is 10.7x to 18,224x
  (median 139x); 1,661 rows are above 300x. The reads for the whole panel are about 5 TB to download, the first 100 rows about 84 GB.
  The post-download gate (stage 3 `short_read_qc.py`) has **not** been run and may still exclude samples.
* **Not judged:** 42 candidates failed their NCBI lookup on temporary errors and were left out; re-run `resolve-contributed-cohort`
  to add them.
* **Not done:** no tool has been run on this panel; `truth_polish_reads` and the truth strategy are NCBI-derived, not curator-checked;
  reference tiers are not yet computed.

## Publication cohorts (compare with a paper)

`pub-*.tsv` and `publication-v1.tsv` are the isolates of published benchmarks, built by `plasbench build-publication-cohorts` from the candidate ledgers in
`candidates/`, `public-v4` and NCBI resolution, and verified online (locked). Each row records `truth_match` (whether the assembly's plasmids are the plasmids the paper
used), `paper_run_used` and `published_studies`. The papers' own outcomes are in `published/`. Every one of the 531 candidates is accounted for in
`candidates/publication_cohort_audit.tsv`. See [`../docs/PUBLICATION_COMPARISON.md`](../docs/PUBLICATION_COMPARISON.md).

## negative-controls-v1 — plasmid-free controls

Every genome of the other cohorts carries at least one plasmid, so a tool's false positives (calling plasmid on an isolate that has none) could not be measured on real data. These 136
isolates are RefSeq Complete Genomes whose deposited assembly has exactly one replicon, with a recorded long-read platform and a paired Illumina run on the assembly's BioProject at 30x to 400x
(`plasbench analysis discover-plasmid-free`; every row verified with `validate-cohort --online`, locked, and checked to declare **no** plasmid replicon). At most 15 per species and 3 per BioProject.
Species: *A. baumannii*, *E. coli*, *K. pneumoniae*, *P. aeruginosa*, *S. enterica*, *S. aureus* (15 each), *E. faecalis* (13), *S. marcescens* (13), *E. hormaechei* (7), *C. freundii* (6),
*K. oxytoca* (5), *E. faecium* (2). `candidates/negative_controls_audit.tsv` lists every candidate and why it was not taken.

**What it does not prove:** a single-replicon complete assembly shows the submitter deposited no plasmid, not that the strain has none (a plasmid can be lost or never assembled). Each row's
`plasmid_free_evidence` says so; read a tool's false positives on these as "plasmid calls with no plasmid in the reference". Tier B, no tool has been run on it. Run it with the other cohorts or
alone: its isolates score through the zero-plasmid path (`zero_plasmid_specificity`, `isolate_specificity`, chromosomal false-positive bases).

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

## Cross-cohort deduplication

`accepted_accessions.tsv` is a generated ledger (never hand-edited) of every
BioSample accepted into any released cohort here, keyed on BioSample rather
than assembly accession -- an assembly can be resubmitted under a new
accession while representing the same physical isolate, so BioSample is the
stable identity across releases. Regenerate it after every release:

```bash
plasbench build-ledger --cohorts-dir cohorts --out cohorts/accepted_accessions.tsv
```

Both `curate-cohort` and `validate-cohort` accept an optional `--ledger`
pointing at this file, rejecting a candidate/row whose BioSample is already
in a prior release rather than silently accepting the same isolate twice
under a different `sample_id`:

```bash
plasbench curate-cohort --candidates new_batch.tsv --out-dir new_batch_curated \
  --ledger cohorts/accepted_accessions.tsv
plasbench validate-cohort --samples cohorts/public-v3.tsv \
  --ledger cohorts/accepted_accessions.tsv
```

Want to add an isolate of your own to one of these panels? See
[`CONTRIBUTING.md`](../CONTRIBUTING.md) — `plasbench prepare-contribution`
wraps this ledger check (plus schema, NCBI evidence, a privacy screen, and
metric bounds) and ends in a local git branch ready for a pull request.

## Data archival (Zenodo)

This cohort metadata (`cohorts/*.tsv`, `cohorts/*.lock.json`, this README) is
archived to Zenodo as its own dataset DOI whenever a GitHub release publishes
with `ZENODO_TOKEN` configured (`.github/workflows/zenodo-upload.yml`) --
separate from any software-archive DOI a release may also carry. Recorded
here per `docs/RELEASING.md`'s own instruction, not as a claim that every
release triggers one:

| Release | Zenodo DOI |
|---|---|
| [v0.1.3](https://github.com/ubeffiong/plasbench/releases/tag/v0.1.3) | [10.5281/zenodo.22671309](https://doi.org/10.5281/zenodo.22671309) |
| [v0.1.4](https://github.com/ubeffiong/plasbench/releases/tag/v0.1.4) | [10.5281/zenodo.22671314](https://doi.org/10.5281/zenodo.22671314) |

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
