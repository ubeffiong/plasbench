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
metagenomic panel. Outbreak cohorts need dependence-aware holdouts;
metagenomic benchmarking requires a separate truth and scoring design and is
not yet an executable PlasBench scenario.

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

**`public-v1` is frozen.** Published results reference it by name and its lock
certifies that exact sheet, so new isolates belong in `public-v2` or your own
panel — never appended to v1.

`public-v2` adds 22 isolates discovered from public NCBI data, extending the
panel to six organisms and five African countries. Those rows are tier B: every
deposited-evidence check passes, but no source publication has been reviewed.
Promote one to tier A by reviewing its publication, recording it in
`source_study`, and re-running `--online --write-lock`.

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
