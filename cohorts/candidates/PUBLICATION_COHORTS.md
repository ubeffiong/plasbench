# Publication cohorts adopted as candidates (2026-11-16)

These files are CANDIDATE ledgers, not released benchmarks. They record which isolates three
publications used, with the accessions the publications themselves give. None has an
`assembly_accession`, so none is valid input to `plasbench curate-cohort` yet; never merge rows
into a `public-vN` cohort without resolve, curate and `validate-cohort --online`
(see `docs/COHORTS.md`, `docs/FINDING_DATA.md`). No sequencing data, FASTA or archive was
downloaded; only small supplementary tables and ENA metadata were fetched.

> **Update 2026-11-17: these candidates have since been resolved and built into runnable cohorts** (`cohorts/pub-*.tsv`, `cohorts/publication-v1.tsv`), verified
> online and locked, with the papers' own outcomes in `cohorts/published/`. See [`docs/PUBLICATION_COMPARISON.md`](../../docs/PUBLICATION_COMPARISON.md). What happened to every
> candidate is in `publication_cohort_audit.tsv`; Teixeira's 245 isolates without a deposited assembly are in `teixeira2025_self_build_candidates.tsv`. The ledgers below are unchanged.
> The commands under "Next commands" are what `plasbench build-publication-cohorts` automates; the text above that describes the ledgers as unresolved is the state on 2026-11-16.

## Counts (checked by `test/test_publication_cohort_candidates.py`)

| file | isolates | plasmids |
|---|---:|---:|
| plsmd2026_filtered_candidates.tsv | 80 | 244 |
| plsmd2026_novel_candidates.tsv | 68 | 269 |
| mobsuite_benchmark_candidates.tsv | 133 | 377 |

The existing `teixeira2025_candidates.tsv` (250 isolates; ST1 gives no plasmid counts) is unchanged.

Paper counts versus files: all agree. plsMD Table 1 (80/244 and 68/269), the per-species isolate
counts, and the plasmid size mean/min/max recomputed from the transcribed table match the paper
exactly. MOB-suite: the paper says 133 closed genomes and 377 plasmids; Table S1 has 510 records
(133 chromosome + 377 plasmid). Teixeira: ST1 has 250 isolates and the repo's `predictions.xlsx`
has 250 sample ids.

## 1. plsMD (Lotfi et al. 2026, BMC Bioinformatics, doi 10.1186/s12859-026-06585-y)

Where each field came from:

* `sra_run`, `truth_plasmid_accessions`, `organism`, plasmid sizes: Additional file 2,
  `12859_2026_6585_MOESM2_ESM.xlsx` (sheets `Dataset A` = filtered, `Dataset B` = novel),
  https://static-content.springer.com/esm/art%3A10.1186%2Fs12859-026-06585-y/MediaObjects/12859_2026_6585_MOESM2_ESM.xlsx
  (the file listed by Europe PMC PMC13474732). Identifier columns are transcribed in
  `plsmd2026_supplementary_table_1_raw.tsv`; the per-tool recall columns are not copied.
* `biosample`, `bioproject`, `ena_instrument_model`, `ena_library_layout`: ENA portal API
  `read_run` metadata for the 148 run accessions, saved in `publication_cohorts_ena_run_metadata.tsv`
  (`biosample_source = ENA_portal_read_run`). The paper does not give these.
* Dataset sizes, method, PLSDB version and truth statement: article text (Europe PMC full text).
* The plsMD GitHub repo (`Validation/`) holds only worked examples (SRR18543877, failed example
  SRR1955549) and `Validation/Synteny/sseqid_pairs.txt`; its 68 samples and 269 reference accessions
  equal Dataset B, so the repo adds no new samples. It has no sample list for Dataset A.

Not resolved, and why:

* `assembly_accession` is blank for every row. The paper lists run and plasmid GenBank accessions
  only; the chromosome record and the GenBank assembly are not listed (no guessing from
  neighbouring accession numbers). `truth_chromosome_accession` is blank for the same reason.
* Run SRR5713998 (filtered set) has SINGLE library layout in ENA, which fails PlasBench's paired-end rule.
* Five filtered rows have an ENA scientific name that differs from the paper's organism label (see `notes`).

Truth independence caveats:

* Filtered set: all 80 isolates are in the MOB-suite benchmark (80 of 80 runs shared). They were
  selected by BLAST of Unicycler assemblies against the closed genomes at 90 percent identity,
  dropping samples whose contigs are not explained by the closed genome. That selection favours
  samples that assemble cleanly and may flatter every tool. Truth is the GenBank closed genome
  from PacBio plus Illumina (see section 2).
* Novel set: the paper says only "independently resolved long-read-derived ground-truth plasmids"
  and does not state the technology, polishing, or whether polishing reused the benchmark's
  short reads. `truth_polish_reads` is therefore unknown; check the GenBank/ENA assembly
  method with `collect_truth_provenance.py` before trusting it.
* The novel runs are not independent observations: 68 runs fall in only 6 BioProjects (PRJEB76496
  alone has 37; Klebsiella pneumoniae is 55 of 68). Treat as clustered and use dependence-aware
  holdouts (docs/SCENARIOS.md). The filtered set spans 26 BioProjects.

PLSDB-novelty flag (`plsdb_novelty`): `claimed_absent_from_PLSDB_2024_05_31_v2_by_paper_unverified_here`.
The claim is the paper's; PLSDB was not downloaded here. Caution: ENA `first_public` of the novel
runs ranges 2018-12-07 to 2025-05-29, and 23 of 68 were public before the paper's June 2024
sequencing start (45 on or after 2024-06-01). So "sequenced from June 2024" does not hold for the
run accessions as listed (the reference assemblies may be newer than the reads). Verify novelty
per truth plasmid against PLSDB (Mash or BLAST) before using the set as PLSDB-novel. The filtered
set is not novel by design (older data). plsMD uses PLSDB 2024_05_31_v2 at run time, so scoring
plsMD on truth plasmids that are in PLSDB is database-dependent (the paper's reason for the novel set).

Licence and terms: article and supplements are CC BY 4.0 (Europe PMC license `cc by`); cite the paper.
The plsMD GitHub repo declares no licence (GitHub reports none), so no repo file is copied.
Accessions are INSDC public records.

## 2. MOB-suite benchmark (Robertson and Nash 2018, Microbial Genomics, doi 10.1099/mgen.0.000206)

Where each field came from:

* `sra_run`, `biosample`, `organism`, `truth_chromosome_accession`, `truth_plasmid_accessions`:
  Supplementary Table 1 (`mgen-5-206-s002.xlsx`, sheet `SupplementalTable1`), retrieved from Europe PMC
  https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6159552/supplementaryFiles ; also on Figshare,
  doi 10.6084/m9.figshare.6177188. Transcribed (identifier columns only) in `mobsuite2018_table_s1_raw.tsv`.
  The phac-nml/mob-suite repo has no benchmark accession list (checked its file tree).
* Each of the 133 isolates has one chromosome record, one run and one BioSample; 377 plasmid records.

Not resolved: `assembly_accession` (the table lists nucleotide records, not assemblies), `bioproject`,
and `ena_*` fields (ENA metadata was fetched for the plsMD runs only). 14 species appear, including
2 Enterococcus faecium, 1 Enterococcus gallinarum and 1 Aeromonas veronii.

Truth independence caveats: truth is public GenBank closed genomes from PacBio plus Illumina. The
paper does not say whether these were polished with the same Illumina reads PlasBench would use
as benchmark input; many such submissions are, which would make the reads non-independent of the
truth (`truth_polish_reads` possibly `same_as_benchmark`, unverified). Records come from many
submitters over 2013-2017 (`nucleotide_date`), so assembly method varies.

Licence and terms: CC BY 4.0 article and supplement; cite the paper and the Figshare record.

## 3. Teixeira et al. 2025 (doi 10.1093/bib/bbaf589): delta only

`github.com/broadinstitute/plasmid-detection-benchmark` (MIT licence) has `data/ani.tsv`,
`data/predictions.xlsx` and analysis scripts. It deposits no accessions. Its 250 sample ids equal the
250 isolates of `teixeira2025_candidates.tsv`, with two spelling differences (repo UCICRE123 and
UCICRE141 are ST1's UCI123 and UCI141). So there are no new isolates. The new information is added as
`teixeira2025_repo_ground_truth_summary.tsv`, derived from sheets `Ground-truth`, `Plasmid Characteristics`
and `Species` (the 2.8 MB xlsx itself is not committed): per isolate, counts of chromosome and plasmid
hybrid contigs (690 plasmid contigs in total; a few multi-valued source cells are split on `;`), total
plasmid bp, number of short-read contigs, whether the hybrid assembly is complete (205 complete, 45 not),
and the maximum Mash identity of its plasmids to PLSDB. Use it to prioritise: the 45 incomplete hybrids
are poor truth. Truth caveat: the hybrid truth is built from the same Illumina reads used as benchmark input.

## Next commands (PlasBench's own tools; set `NCBI_EMAIL`)

```bash
# 1. resolve BioSample -> complete assembly + paired Illumina run (or a self-build fallback)
for c in mobsuite_benchmark plsmd2026_filtered plsmd2026_novel; do
  python python/resolve_ncbi_accessions.py \
      --candidates cohorts/candidates/${c}_candidates.tsv \
      --out-dir results/${c}_resolution --email you@example.org
done
# 2. strict screening of the resolved rows (needs assembly_accession and sra_run)
plasbench curate-cohort --candidates results/mobsuite_benchmark_resolution/resolved.tsv \
    --out-dir results/mobsuite_benchmark_curated --ledger cohorts/accepted_accessions.tsv --email you@example.org
# 3. verify the accepted rows online and write a lock
plasbench validate-cohort --samples results/mobsuite_benchmark_curated/accepted.tsv --online \
    --write-lock results/mobsuite_benchmark_curated/accepted.lock.json
# 4. truth provenance (polish reads, strategy)
python python/collect_truth_provenance.py --help
```

Repeat steps 2 and 3 for the two plsMD sets. `resolve_ncbi_accessions.py` matches a complete assembly
by BioSample, so check that the resolved assembly contains the listed `truth_plasmid_accessions`
(plsMD) or `truth_chromosome_accession` (MOB-suite) before accepting it. Rebuild the three candidate
files offline with `python python/build_publication_cohort_candidates.py` (add `--fetch-ena` first to
refresh ENA metadata).
