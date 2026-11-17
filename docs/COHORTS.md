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

Read [`SCENARIOS.md`](SCENARIOS.md) before creating a clinical-outbreak or
metagenomic panel. Outbreak cohorts need dependence-aware holdouts.
Metagenomics has its own executable community/bin scoring track and separate
truth contract in [`METAGENOMICS.md`](METAGENOMICS.md); it must never be mixed
with this isolate cohort format or its leaderboards.

Validate locally:

```bash
python python/validate_cohort.py --samples config/accessions.tsv
python python/validate_cohort.py --samples config/accessions.tsv --online
plasbench validate-cohort --samples cohorts/public-v1.tsv --online
```

`--online` verifies that the assembly is complete and plasmid-containing, has
explicit Datasets-v2 long-read/hybrid sequencing evidence, and that the
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
  --email you@example.org
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
deposited metadata linkage only. Technology and tier are derived from NCBI
evidence, never CLI defaults. Curators must still check publications and
collection metadata before assigning origin or making a public release claim.

To discover a country-specific candidate set without loosening the benchmark
rules, add `--country`. PlasBench first narrows the Assembly query, then
requires the requested term to be present in the deposited BioSample
`geo_loc_name`. The accepted table preserves the deposited location, isolation
source, and host in `sample_origin`; the rejected table preserves the same
evidence and the exact rejection reason. This makes African and Nigerian leads
auditable without promoting Illumina-only, draft, or unmatched records to the
release cohort.

```bash
plasbench discover-cohort --out-dir curation/nigeria --country Nigeria \
  --max-assemblies 100 --organism "Klebsiella pneumoniae" \
  --organism "Acinetobacter baumannii" --organism "Pseudomonas aeruginosa" \
  --organism "Enterococcus faecium" --organism "Staphylococcus aureus"
```

Discovered rows are therefore **tier B**: every NCBI evidence check passed, but
no publication has been reviewed. A row becomes **tier A** only once a curator
replaces the placeholder `source_study` with a real study identifier, which
`validate-cohort --online` then re-derives and enforces. **Tier C** marks a row
that has not been verified online at all; online verification always resolves a
row to A or B.

## Contributed RefSeq/SRA candidate pool

`cohorts/candidates/contributed-refseq-sra/` holds a pool of 8,812 RefSeq Complete Genomes paired to SRA runs
(`assemblies.tsv.gz`, plus `plasmids.tsv.gz`, the same rows once per plasmid), supplied by a collaborator and
pinned by SHA-256 in `contributed.lock.json`. Read its `SOURCE.md` first. It is a **candidate pool, not a cohort**:
nothing in it is verified against NCBI, read quality is unassessed, there are no plasmid-free genomes, and its
`bioproject` column is the RefSeq umbrella project on every row, so independence is judged on `read_bioprojects`.

```bash
plasbench import-contributed-cohort --out-dir curation/contributed   --released-after 2025-01-01 --date-basis earliest_public --max-clusters-per-species 25 --seed 20260916
plasbench validate-cohort --online ...   # required before any row is used
```

The importer is deterministic for a given seed. It keeps long-read-first truths (add `--allow-short-read-first`
for tier-3 truths), one isolate per read-BioProject cluster, skips BioSamples already released
(`cohorts/accepted_accessions.tsv`), and writes `candidates.tsv`, `rejected.tsv` (with the reason for every
row) and `selection_summary.tsv` (clusters per species against the headline's `MIN_SPECIES_CLUSTERS`).
`--released-before` builds an older comparison arm. `--date-basis` is `assembly`, `read`, or `earliest_public`
(the earlier of the two; the pool records the read release only as a year, so it is read as 1 January, the
conservative direction). Measured on this pool: with the 2025 cutoff on the assembly date only *E. coli* (35
clusters) and *K. pneumoniae* (22) reach 20 independent long-read-first clusters; over all years *E. coli*
(122), *K. pneumoniae* (70), *S. enterica* (55), *S. aureus* (39) and *E. hormaechei* (22) do. Use an older
comparison arm if more species are wanted.

### From candidates to a verified cohort (public-v4)

The importer only selects. `plasbench resolve-contributed-cohort` then checks every candidate at NCBI (it needs
`NCBI_API_KEY`; export it or keep it in the ignored `.ncbi.env`) and does the **pre-download read-QC check**:

* the assembly must be a Complete Genome that declares plasmid replicons and has a long-read platform in its
  sequencing evidence; `truth_technology` becomes NCBI's derived value;
* the row's BioProject is the SRA run's, and it must also be one of the assembly's BioProjects (the pool's own
  `bioproject` is the RefSeq umbrella);
* each listed run must be the same BioSample, ILLUMINA, PAIRED. Depth (bases / genome size), read pairs and mean read
  length are estimated from SRA run-info and graded against `config/short_read_qc_thresholds.tsv`, the same provisional
  limits the post-download gate uses: below `reject` the run is dropped, below `warn` it is kept and flagged. The best run
  (pass before warn, then deepest) becomes `sra_run`; the rest stay in `alternate_paired_runs`.

This check cannot see base quality, adapters or pair integrity. Stage 3's `short_read_qc.py` does, on the downloaded
reads, and can still exclude a sample. Then `plasbench validate-cohort --online --write-lock` verifies the final sheet.

The design (decided 2026-11-16 on the project owner's instruction to add everything that is available; it is a cohort-selection
choice, not a scoring decision, so it is not in `config/prereg.tsv`): **every genome in the pool that passes the offline
filters and the NCBI verification is in `public-v4`.** That is 7,227 isolates of 943 species from 1,818 BioProjects. It is a
large panel, not a designed sample: species and studies are unequal (*E. coli* 1,360 isolates, 520 species have one), so
choose what to run with the columns and with `plasbench run --max-isolates N`, which takes a balanced N (see the README).

* **Truth strategy** (`truth_assembly_strategy`): 3,552 long-read-first (2,453 hybrid, 1,099 long-read-only), 2,522
  short-read-first, 1,153 unclassified. Only long-read-first rows belong in the headline; the others are tier 3 and are
  described, not ranked. Four species reach the headline's 20 long-read-first studies: *E. coli* (111), *K. pneumoniae*
  (58), *S. aureus* (35), *S. enterica* (34).
* **Leakage arms** (`selection_arm`): 1,539 `recent` (public on or after 2025-01-01, earlier of assembly and first read)
  and 5,688 `older`. `panel_subset` is `core` for the 98 isolates of the first, balanced selection (20 each of *E. coli*,
  *K. pneumoniae*, *S. enterica*, *S. aureus* and 18 *E. hormaechei*) and `extended` for the rest.
* **Read QC:** the pre-download check passed 7,081 rows and flagged 146 (`qc_precheck=warn`). Estimated depth is 10.7x to
  18,224x (median 139x), and 1,661 rows are above 300x. Reads for the whole panel would be about 5 TB to download
  (plus 87 GB of references); the first 100 rows in balanced order are about 84 GB. Run a slice with `--max-isolates`.
* **Not judged:** 42 candidates failed their NCBI lookup on temporary errors (503, timeouts) and are listed under
  "NCBI lookup failed" in the selection report; re-running `resolve-contributed-cohort` adds them.
* **Not done:** no tool has been run on this panel, the post-download QC (stage 3) has not run on its reads, and truth
  strategy and polishing are NCBI-derived, not curator-checked.

The sheet is written in balanced order (`balance_rank`: species take turns, recent and older alternate, long-read-first
before the rest, one isolate per study before a second), so any first N rows are a fair miniature of the whole.

The window's **Cohorts** page shows a **Selection report** pop-up for a cohort built this way: where the genomes came from, the criteria, how many were available and how many passed each stage, why the others failed (offline filters and NCBI / read-QC), a per-species table, and the sequence information of the selected genomes. It is read from `cohorts/<name>.selection.json`, written by `plasbench selection-report` from the importer's and resolver's output, so it states only what the selection run produced.

```bash
plasbench import-contributed-cohort --allow-short-read-first --all-members --arm auto --date-basis earliest_public \
  --out-dir curation/v4/full
plasbench resolve-contributed-cohort --candidates curation/v4/full/candidates.tsv --out-dir curation/v4/resolved \
  --cache curation/v4/resolve_cache.json --target-per-species 0 --allow-shared-bioproject --workers 12
plasbench validate-cohort --samples curation/v4/resolved/resolved.tsv --online --workers 8 --write-lock curation/v4/resolved.lock.json
plasbench selection-report --name public-v4 --sheet cohorts/public-v4.tsv --importer-dir curation/v4/full \
  --resolver-dir curation/v4/resolved --out cohorts/public-v4.selection.json
```

## Publication cohorts

The isolates of the published benchmarks (plsMD 2026, MOB-suite 2018, Teixeira 2025) are runnable cohorts, with the papers' own outcomes shipped beside them, so a run can be
compared with the paper. They are built from the candidate ledgers, `public-v4` and NCBI resolution, and each row's assembly is checked against the plasmids the paper used as
truth. How they were built, which isolates are missing and why, and how to compare are in [`PUBLICATION_COMPARISON.md`](PUBLICATION_COMPARISON.md).

## Candidate Review And Balance

Keep raw discoveries as candidates. To detect study dependence and create a
non-release balanced shortlist without deleting any coverage:

```bash
plasbench review-candidates --candidates curation/ncbi-round1/accepted.tsv \
  --out-dir curation/review --max-per-bioproject 3 --max-per-organism 8
```

This writes the full `candidates.enriched.tsv`, `study_dependence.tsv`, and a
`balanced_shortlist.pending_review.tsv`. Origin and source-study fields remain
pending until supported by deposited metadata and/or the cited publication; no
command automatically adds candidates to `public-v1.tsv`.

## Versioned public panels

Two panels ship with PlasBench, each with its own NCBI verification lock. They
apply identical evidence rules and differ only in curation grade. Read
[`cohorts/README.md`](../cohorts/README.md) before using or extending either.

| Panel | Rows | Tier | Use it for |
|---|---:|---|---|
| [`public-v1.tsv`](../cohorts/public-v1.tsv) | 10 | all A | reproducible headline results and citation |
| [`public-v2.tsv`](../cohorts/public-v2.tsv) | 32 | 10 A + 22 B | broader organism and geographic coverage |
| [`public-v3.tsv`](../cohorts/public-v3.tsv) | 98 | 10 A + 88 B | the species-balanced headline design; recorded truth provenance |
| [`public-v4.tsv`](../cohorts/public-v4.tsv) | 7,227 | all B | the large validation panel: every verified genome of the contributed pool, 943 species, recent and older arms; run a balanced slice with `--max-isolates`; see [`cohorts/README.md`](../cohorts/README.md) |
| [`pub-plsmd-novel.tsv`](../cohorts/pub-plsmd-novel.tsv) | 68 | all B | the plsMD paper's novel set; compare with the paper (`plasbench compare-published`) |
| [`pub-plsmd-filtered.tsv`](../cohorts/pub-plsmd-filtered.tsv) | 63 | all B | the plsMD paper's filtered benchmark; compare with the paper |
| [`pub-mobsuite.tsv`](../cohorts/pub-mobsuite.tsv) | 95 | all B | the MOB-suite benchmark |
| [`pub-teixeira2025.tsv`](../cohorts/pub-teixeira2025.tsv) | 5 | all B | the 5 of Teixeira's 250 isolates with a deposited complete assembly |
| [`publication-v1.tsv`](../cohorts/publication-v1.tsv) | 168 | all B | the publication cohorts together, each isolate once; see [`PUBLICATION_COMPARISON.md`](PUBLICATION_COMPARISON.md) |
| [`negative-controls-v1.tsv`](../cohorts/negative-controls-v1.tsv) | 136 | all B | plasmid-free negative controls (single-replicon complete genomes, long-read truth, paired Illumina run); see [`cohorts/README.md`](../cohorts/README.md) |

These are versioned **input cohort manifests**, not a substitute for released
performance evidence. A public performance claim requires a reproducible run,
its complete manifest and tool/database versions, generated scores/report, and
the governance review described in `docs/GOVERNANCE.md`. Do not cite a shipped
demo report as a real-cohort result.

**`public-v1` is frozen.** Published results reference it by name and its lock
certifies that exact sheet, so new isolates belong in `public-v2` or your own
panel — never appended to v1.

`public-v2` adds 22 isolates discovered from public NCBI data, extending the
panel to six organisms and five African countries. Those rows are tier B: every
deposited-evidence check passes, but no source publication has been reviewed.
Promote one to tier A by reviewing its publication, recording it in
`source_study`, and re-running `--online --write-lock`.

`public-v3` is built for the headline design in docs/METHODS.md ("Research design"):

* **Recorded truth provenance.** Every row carries `truth_assembly_strategy` and
  `truth_polish_reads`, taken from NCBI's assembly method and sequencing technologies and
  from the Illumina runs on each BioSample (`python/collect_truth_provenance.py`), so
  reference tiers rest on recorded evidence rather than per-run guesses. Of the 32
  `public-v2` truths, 13 are long-read-first or long-read-only (tiers 1-2); 15 are
  short-read-first and 4 are genuinely ambiguous in NCBI's record, so those 19 are tier 3
  until a curator checks their source papers.
* **66 new isolates** (`python/discover_design_cohort.py`): newest-first complete genomes
  built long-read-first (Flye, Hybracter, Trycycler, Canu and similar), one isolate per
  BioProject so each is an independent cluster, and exactly one paired Illumina run on the
  BioSample -- the benchmark run, which therefore also polished the truth
  (`same_as_benchmark`: usable for labelling, not identity). All 98 rows passed
  `--online` verification.
* **Species balance.** Headline-eligible independent clusters per species: E. coli 22,
  K. pneumoniae 13, S. enterica 12, A. baumannii 11, E. faecium 10, E. hormaechei 5,
  S. aureus 1. Only E. coli reaches the default `MIN_SPECIES_CLUSTERS=20`; the other
  species ran short of qualifying public genomes within the search limits, so until they
  grow the headline remains pooled (or lower `MIN_SPECIES_CLUSTERS` and say so).

### What the shipped panels can support

`public-v1` (10 reviewed rows) is fit for reproducible workflow smoke tests,
documentation examples, and a narrow proof-of-work. `public-v2` (32 rows) is
fit for adapter integration, exploratory comparisons, and verifying that a
benchmark can span multiple organisms and deposited geographies. Neither panel
is yet fit to publish a broad operational recommendation by organism, plasmid
size, read depth, source setting, or geography: v2 remains *E. coli*-weighted,
has tier-B publication review outstanding, and has too few observations in most
strata for independent hold-out evidence.

The metagenomic track now includes one executable **truth-scored real physical
community control**: BMock12. Its source inventory is
[`metagenomics-physical-mock-v1.tsv`](../cohorts/metagenomics-physical-mock-v1.tsv)
and the checksum-pinned artifacts are declared in
[`metagenomic_truth_sources.tsv`](../config/metagenomic_truth_sources.tsv).
The materializer downloads the released CC-BY 4.0 scaffolds, assembly graph,
and contig-to-source-genome gold standard, verifies every checksum, and writes
a scoreable manifest without silently downloading BMock12's approximately 64
Gbp Illumina input:

```bash
plasbench materialize-meta-bmock12 --out-dir "$HOME/.local/share/plasbench/metagenomics/controls"
plasbench metagenomics validate \
  --manifest "$HOME/.local/share/plasbench/metagenomics/controls/bmock12/metagenomics-bmock12-verified.tsv"
```

This is a **real physical negative plasmid control**, not a positive plasmid
reconstruction leaderboard. The released truth assigns scaffolds to the 12
component genomes but does not make a validated plasmid-replicon call, so
PlasBench labels its truth as chromosome. It supports reproducible assessment
of plasmid false positives, chromosome contamination, bin purity, and tool
behavior on an independently deposited assembly graph. It cannot estimate
plasmid recall and must not be combined with a plasmid-positive ranking.

[`metagenomics-real-v1.tsv`](../cohorts/metagenomics-real-v1.tsv) remains an
accession-resolved, six-community operational-review panel: three public
physical Zymo HMW mock sequencing conditions and three public real wastewater
communities. Its companion [accession ledger](../cohorts/metagenomics-real-v1.accessions.tsv)
records the exact ENA/NCBI projects, BioSamples, and WGS/ONT/Hi-C runs.

This panel is deliberately not a leaderboard cohort. The Zymo rows lack an
independently validated component-to-contig truth projection, and the real
wastewater rows have no deposited contig-level plasmid gold standard. The
physical mock rows also share the same reference cluster and are sequencing
conditions, not independent communities. Therefore PlasBench preserves their
outputs for evidence review but blocks a release-ready operational ranking.

The bundled example and high-depth mock templates remain contract fixtures.
Together with BMock12 and the real-v1 review panel, they support offline
schema, scoring, report, uncertainty, phage, contamination, split/merge, and
leakage-gate regression tests. None supports an operational recommendation for
routine environmental or clinical metagenomics until independently curated,
plasmid-positive community truth tables are released.

```bash
plasbench metagenomics validate --manifest cohorts/metagenomics-real-v1.tsv
plasbench audit-meta-cohort --manifest cohorts/metagenomics-real-v1.tsv \
  --out results_meta/metagenomics-real-v1.audit.json
```

```bash
plasbench run --cohort public-v1    # reproducible headline results
plasbench run --cohort public-v2    # broader coverage

plasbench validate-cohort --samples cohorts/public-v2.tsv \
  --verify-lock cohorts/public-v2.lock.json
```

`--cohort NAME` is shorthand for `--samples cohorts/NAME.tsv` and accepts
either panel above (or one you add under `cohorts/`); it is equivalent to the
explicit `--samples` form otherwise. Add `--write-script FILE` to either
command to see and edit the exact commands PlasBench would run instead of
running them immediately:

```bash
plasbench run --cohort public-v1 --write-script run_public_v1.sh
# review or edit run_public_v1.sh, then:
bash run_public_v1.sh
```

Because the v2 additions are study-clustered (22 rows across 11 BioProjects),
run them through `review-candidates` with per-BioProject caps before treating
them as independent observations.

## truth_independent_of_long_reads (optional)

Consulted by every long-read and hybrid tool -- any tool whose
`config/tool_capabilities.tsv` row declares
`requires_independent_long_read_truth=yes`. Today that is all five of them:

| Tool | Track | Override variable |
|---|---|---|
| `flye_mob_recon` | long_read | `FLYE_MOB_RECON_ALLOW_CIRCULAR_TRUTH` |
| `plassembler` | hybrid | `PLASSEMBLER_ALLOW_CIRCULAR_TRUTH` |
| `hybracter_long` | long_read | `HYBRACTER_LONG_ALLOW_CIRCULAR_TRUTH` |
| `hybracter_hybrid` | hybrid | `HYBRACTER_HYBRID_ALLOW_CIRCULAR_TRUTH` |
| `trycycler_mob_recon` | long_read | `TRYCYCLER_MOB_RECON_ALLOW_CIRCULAR_TRUTH` |

The registry is the authority, not this table: to check any tool, run

```bash
python3 python/tool_capabilities.py --registry config/tool_capabilities.tsv \
    --tool hybracter_long --requires-independent-long-read-truth
```

which exits 0 if the guard applies to it and 1 if it does not.

Set the column to `yes` when a sample's long reads are NOT the reads its truth
assembly was built from.

## truth_assembly_strategy / truth_polish_reads / clonal_group (optional)

These columns feed the headline design (docs/METHODS.md, "Research design"). Leave
them blank to let PlasBench derive them; set them to override a derived value.

| Column | Values | Meaning |
|---|---|---|
| `truth_assembly_strategy` | `long_read_only`, `long_read_first_hybrid`, `short_read_first_hybrid`, `unknown` | How the truth's structure was resolved. Short-read-first and unknown truth is reference tier 3 (provisional, outside the headline). Derived from NCBI's assembly method when blank. |
| `truth_polish_reads` | `none`, `independent`, `same_as_benchmark`, `unknown` | Whether the truth was polished with the same Illumina run the tools are benchmarked on. `same_as_benchmark` keeps the truth for labelling but drops identity criteria. |
| `truth_circularity_evidence` | `independent`, `reported`, `uncertain`, `unknown` | How well the truth's circular plasmids are supported (evidence record). Blank = not recorded. |
| `truth_read_support` | `supported`, `partial`, `none`, `unknown` | Whether long reads support each truth plasmid. Blank: inferred from the long-read depth in `truth_labels.tsv` when present. `none` caps a reference at Tier 2. |
| `truth_structural_integrity` | `resolved`, `unresolved_repeats`, `unknown` | Whether repeats are resolved in the truth. `unresolved_repeats` caps a reference at Tier 2. |
| `truth_independent_validation` | `none`, `long_read_reassembly`, `pcr`, `hic`, `other`, `unknown` | Independent evidence beyond the assembly. Recorded, never demotes. |
| `clonal_group` | free text, e.g. an ST or cgMLST cluster | Isolates sharing a value count as one independent unit in confidence intervals and in each species' minimum. Derived from whole-genome Mash distance when blank. |

`validate_cohort.py` rejects values outside these vocabularies and prints advisory
`COHORT COMPOSITION WARNING` lines when a cohort has fewer than five species, a
species above 30% of isolates, or species below the species-balanced headline's
minimum.

## truth_source / long_read_sra_run (optional): self-built hybrid truth

Every cohort row so far has downloaded an existing NCBI Complete Genome
assembly as its truth reference. Some real cohort sources instead deposit
only raw reads -- both a long-read (ONT/PacBio) run and a paired-end
Illumina run under the same BioSample -- without ever formally submitting a
finished assembly (see `docs/FINDING_DATA.md`'s Route C for a worked
example). For exactly this shape, `truth_source=self_assembled_hybrid` tells
stage 1 to fetch `long_read_sra_run` in addition to the usual short reads,
and stage 2 to build the truth reference itself with
`python/build_hybrid_truth.py` (a Unicycler hybrid assembly) instead of
downloading one. `assembly_accession` stays blank/`NA` for these rows, same
as an operational sample with no known truth.

Chromosome/plasmid labeling comes only from Unicycler's own circularity/
length output -- never a gene-content classifier, since several of those
(`mob_recon`, PlaScope, RFPlasmid, ...) ARE benchmarked prediction tools
here, and using one to build "truth" would make it trivially perfect
against itself. An assembly that does not fully circularize is rejected
outright (`HYBRID_TRUTH_MIN_CHROMOSOME_LENGTH` in `config/config.sh`,
default 1,500,000 bp) -- never accepted as a partial or uncertain truth.

**A self-built truth is never independent of the long reads that built it,
by construction.** `validate_cohort.py`'s schema check enforces this as a
hard rule, not a judgment call: a `self_assembled_hybrid` row must never
declare `truth_independent_of_long_reads=yes`. Left unset (the required
state), `long_read_truth_eligible()`'s existing default applies unchanged --
every long-read/hybrid tool above is automatically excluded from scoring on
these samples. They contribute to the short-read track only.

```bash
python3 python/build_hybrid_truth.py \
    --long-reads data/<sample>/long_reads.fastq.gz \
    --r1 data/<sample>/<run>_1.fastq.gz --r2 data/<sample>/<run>_2.fastq.gz \
    --out-reference data/<sample>/reference.fna \
    --out-truth data/<sample>/truth.tsv \
    --out-provenance data/<sample>/truth_provenance.json
```

**If you are building a cohort for any tool in that table, you almost
certainly need this column.** Leaving it out is not neutral -- every sample is
skipped, and a run that looks like it succeeded produces an empty leaderboard
for that tool. The skip is recorded per sample in `results/tool_status.tsv`
with a `circular truth:` reason, so check there first if a long-read tool
scored nothing.

PlasBench's truth labels come from a complete long-read or hybrid assembly. A
long-read or hybrid tool handed those same long reads is scored against its
own input, so a sample is skipped unless this column says otherwise -- see the
circularity section of docs/METHODS.md. An absent column, an empty value, or
`no` all mean "assume circular, skip". This is deliberately the safe default: a
benchmark that silently scores a tool on its own input is worse than one that
omits it. Each affected tool also has its own global override variable (the
right-hand column of the table above) for when you accept the compromise
anyway; using it stays visible in `tool_status.tsv`'s recorded reason.

Short-read tools ignore this column entirely; their inputs are already
independent of the truth.

## truth_source=simulated: reads generated locally from a real reference

The mirror image of `self_assembled_hybrid` above. There, the truth is BUILT
from real reads because no assembly was ever deposited. Here, the truth is a
REAL, independently-deposited Complete Genome assembly -- `assembly_accession`
is required and downloaded exactly like an `ncbi_deposited` row, unchanged --
but the reads are not real sequencing data at all: `python/simulate_reads.py`
generates them locally with InSilicoSeq (short reads) and Badread (long
reads) at a depth, seed, and error model YOU choose, rather than inheriting
whatever a real deposited run happened to have.

This is useful when the read-generating process itself needs to be
controlled for -- a specific depth to test how performance degrades with
coverage, a fixed seed for exact reproducibility, or a specific error
profile -- none of which you can dictate about a real SRA run.

`sra_run` still needs a value (every cohort row has one), but for a
simulated row it is NOT a real SRA accession: it is reused as the local
read-file prefix (`data/<sample>/<sra_run>_1.fastq.gz`, etc.), so
`validate_cohort.py` does not apply the usual SRR/ERR/DRR pattern to it --
any short, filesystem-safe string works (`SIMULATED`, or anything else you
choose).

Four more columns apply only to a `simulated` row:

| Column | Required? | Meaning |
|---|---|---|
| `simulation_seed` | required | integer RNG seed, passed to both InSilicoSeq and Badread |
| `simulation_short_depth_x` | required | short-read fold coverage, applied UNIFORMLY to every reference contig (chromosome and plasmid(s) alike -- a documented simplification, not a per-replicon depth model) |
| `simulation_long_depth_x` | required | long-read fold coverage, independent of the short-read one |
| `simulation_short_error_model` | optional | an InSilicoSeq `--model` value (default: `config/config.sh`'s `SIMULATE_SHORT_MODEL`, `novaseq`) |
| `simulation_long_error_model` | optional | a Badread `--error_model`/`--qscore_model` value (default: `SIMULATE_LONG_MODEL`, `nanopore2020`) |

Badread's read-length distribution is deliberately left at its own natural
default, never forced to a fixed length -- unlike some published simulation
pipelines that fix every long read to exactly 10,000 bp, a choice worth
flagging rather than copying uncritically, since real long-read runs do not
look like that.

```bash
python3 python/simulate_reads.py \
    --reference data/<sample>/reference.fna \
    --out-r1 data/<sample>/<sra_run>_1.fastq.gz --out-r2 data/<sample>/<sra_run>_2.fastq.gz \
    --out-long data/<sample>/long_reads.fastq.gz \
    --out-provenance data/<sample>/simulation_provenance.json \
    --seed 42 --short-depth 60 --long-depth 40
```

`validate_cohort.py`'s online verification checks the reference the SAME way
as an `ncbi_deposited` row -- Complete Genome, declares plasmid replicons --
since simulating from a bad or incomplete reference would be exactly as
meaningless as scoring against one. No SRA-run check applies at all, since
`sra_run` is not real here.

**A simulated isolate must never be silently read as a real-world result.**
The HTML report marks every simulated sample with a distinct "simulated
reads" badge (visually different from `self_assembled_hybrid`'s "self-built
truth" badge, since the situations are opposite: here the reference is real
and only the reads are synthetic) next to its name in the scores table, and
`data-truth-source='simulated'` on its row for filtering/styling.

### Where to find candidate reference genomes for a simulated cohort

`cohorts/candidates/simulated_reference_candidates.tsv` lists the IDENTITY
(organism/strain where stated, approximate genome size, source study) of 20
reference genomes used by a sibling benchmarking project
(gbouras13/plassembler_simulation_benchmarking), extracted from that repo's
own CSV inputs rather than vendoring its checked-in FASTA files. This list
is a **starting point, not a ready-to-run cohort**: `assembly_accession`/
`sra_run`/`biosample` are intentionally empty, since the source repo's own
files give only an internal isolate identifier, never a BioSample or NCBI
accession. Resolving each to a real assembly (organism/strain name -> a real
BioSample -> `python/resolve_ncbi_accessions.py`'s existing biosample ->
accession chain) is a separate, not-yet-done research step for whoever picks
this up next -- never fabricate a BioSample or accession to skip it.
Fourteen of the twenty rows also have their organism recorded as
`unconfirmed`, because the source repo's own files give only a bare isolate
identifier
(e.g. `MGH78578`, `RBHSTW-00059`) with no stated genus/species; confirming
those requires reading the actual cited paper (Wick et al., Houtak et al.,
Mathers et al., or De Maio et al. -- see each row's `source_study`), not a
guess from the identifier's shape.
