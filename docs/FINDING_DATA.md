# Finding matched pairs (the real curation task)

PlasBench benchmarks two kinds of tracks, and each needs its own kind of pair.
Finding these pairs is the hardest and most valuable part of the project.

- **Short-read track** (mob_recon, Platon, plasmidSPAdes, gplas2): a **complete**
  genome assembly (long-read or hybrid → closed chromosome + plasmids) as ground
  truth, plus the **matched Illumina** reads for the *same isolate* as the input
  the tools are actually tested on.
- **Long-read/hybrid track** (Flye+MOB-Recon, Plassembler, and any future
  long-read-native tool): the same kind of complete-assembly truth, but the long
  reads you hand the tool must additionally be **independent of that truth
  assembly** — see [Finding pairs for the long-read/hybrid track](#finding-pairs-for-the-long-readhybrid-track)
  below. Skip that section entirely if you only intend to run short-read tools.

The full recognized sample-sheet schema lives in one place:
[`config/accessions.tsv`](../config/accessions.tsv)'s own header comment. Don't
duplicate that column list here — this document is about *finding* the data,
not the schema.

---

## Short-read track

### Route A — Start from complete assemblies (recommended)

1. Go to **NCBI Datasets → Genomes** (or use the `datasets` CLI). Filter for your taxon
   (e.g. *Escherichia coli*, *Klebsiella pneumoniae*) with **Assembly level = Complete
   Genome**. Prefer assemblies annotated with one or more plasmids.

2. For a candidate assembly, open its **BioSample**. Look at the SRA experiments linked to
   that BioSample. You want an **Illumina** run (platform = ILLUMINA), ideally paired-end.

3. If the same BioSample has both a complete assembly and an Illumina run, you have a pair.
   Record the **assembly accession** (GCF_/GCA_) and the **SRA run** (SRR/ERR/DRR).

CLI sketch (adapt taxon/filters):
```bash
# list complete E. coli assemblies (GCA) as a table
datasets summary genome taxon "Escherichia coli" \
  --assembly-level complete --assembly-source genbank --as-json-lines \
  | head

# for a given BioSample, find linked Illumina runs via Entrez
esearch -db biosample -query "SAMN00000000" \
  | elink -target sra | efetch -format runinfo | grep -i illumina
```

### Route B — Start from a project that did both

Hybrid-assembly studies often deposit **both** the Nanopore/PacBio-based complete assembly
**and** the Illumina reads under one **BioProject**. Find such a BioProject (search terms
like *"hybrid assembly", "Nanopore", "complete genome", "plasmid"* for your taxon), then
pull every isolate that has the complete-assembly + Illumina pair. This is the fastest way
to get 10–20 clean pairs at once.

### Route C — Reference/benchmark collections

Some plasmid-benchmark papers and resources publish curated isolate sets with matched data.
Reusing (and citing) an established truth set is legitimate and saves time; you can then add
your own newly-curated pairs on top.

### Quality criteria (keep only good pairs)

- **Complete** assembly (not "chromosome" or "scaffold" level) — you need closed plasmids.
- Reads are **Illumina paired-end**. (Single-end works but needs a small edit in
  `01_download.sh`/`03_assemble.sh`.)
- Same isolate — confirm the assembly and the run share a **BioSample** where possible.
- Reasonable read depth (≳ 30× genome). Very low depth handicaps every tool equally but
  adds noise.
- A mix of **plasmid-carrying** isolates (needed for recall) — avoid an all-plasmid-free set.

---

## Finding pairs for the long-read/hybrid track

### Why this needs its own section

`config/tool_capabilities.tsv` declares `requires_independent_long_read_truth=yes`
for every long-read/hybrid tool (today: Flye+MOB-Recon, Plassembler). PlasBench's
truth labels come from a complete long-read or hybrid assembly; handing one of
these tools the *same* long reads that built that assembly scores it against its
own input — it would look near-perfect for reasons that say nothing about the
tool. See `docs/METHODS.md`'s circularity section for the full mechanics, and
`docs/COHORTS.md` for the `truth_independent_of_long_reads` sample-sheet column
this all hinges on.

**Why this matters for scale**: most public "complete genome" records don't
declare independent long-read provenance — a BioProject typically deposits one
long-read run that both built the truth assembly *and* is the only long-read
data available. If you only ever reach for such records, your long-read-eligible
cohort will collapse toward empty the moment you generalize the guard beyond a
single tool. Actively seeking the sourcing patterns below is what keeps this
track scalable rather than self-disabling.

### Preferred sourcing patterns, in descending order of how well they withstand review

1. **Orthogonal-technology truth.** The truth assembly was built (or polished)
   from a different long-read platform than the one you're evaluating — e.g. a
   PacBio HiFi-built reference genome, with ONT reads as the reconstruction
   input for the tool under test (or vice versa). Different chemistry, different
   error modes, genuinely independent evidence. This is about as clean an
   independence argument as exists without a literal held-out-reads split.
2. **Optical-mapping-confirmed assemblies.** The assembly's completeness and
   structure is corroborated by Bionano/optical mapping independent of any
   long-read assembler. Gives an independence argument that doesn't rely on
   read-set provenance at all — useful when only one long-read platform's data
   exists for the isolate.
3. **Explicit held-out long reads.** The long-read set is split: part builds the
   truth assembly, the remainder feeds the tool. Defensible, and the split must
   be documented (record it in `source_study` or a provenance note).
4. **Multi-run BioProjects.** A study deposits more than one long-read run per
   isolate — one used for the published assembly, another that can be verified
   as held out. Worth actively searching for, since it is the most common way
   a genuinely independent pair actually exists in public data (see the CLI
   sketch below).
5. **Simulated data**, where ground truth is known by construction. Needs its
   own quality tier, since it cannot be verified against NCBI evidence the way
   tiers A and B are — see `docs/COHORTS.md`.

### CLI sketch: finding BioProjects with more than one long-read run per BioSample

```bash
# For a candidate BioProject, list every SRA run and its platform/instrument,
# so you can spot a BioSample with more than one long-read (ONT/PacBio) run --
# a candidate for an explicit held-out or orthogonal-technology split.
esearch -db bioproject -query "PRJNA000000" \
  | elink -target sra | efetch -format runinfo \
  | awk -F',' 'NR==1 || $19 ~ /OXFORD_NANOPORE|PACBIO_SMRT/'
```

If a BioSample shows two or more long-read runs, check the study's methods
section for which run (if any) built the deposited assembly — that is the one
to exclude from the tool's input, and the basis for declaring
`truth_independent_of_long_reads=yes` for that sample.

Declaring this column is always a **curator's judgment call**, never an
automated one: NCBI metadata can tell you an assembly's own sequencing
technology, but it cannot tell you whether a *specific* long-read run you plan
to feed a tool is the same physical read set that built the truth. `plasbench
discover-cohort` surfaces a hint (a candidate's BioProject run count) when more
than one long-read run exists, precisely so you notice the possibility and go
verify it manually — it never sets this column for you.

---

## Filling in the sample sheet

Put each accepted pair in `config/accessions.tsv`, following its own header
comment for the full recognized column list (short-read pairs need only the
core columns; long-read/hybrid pairs additionally want
`truth_independent_of_long_reads` once you've verified independence per the
section above):
```
sample_id	assembly_accession	sra_run	organism	truth_technology	truth_quality_tier	biosample	bioproject
ecoli_01	GCF_012345678.1	SRR12345678	Escherichia coli	hybrid	B	SAMN00000000	PRJNA000000
```
`sample_id` is any short unique label you choose. Comments (`#`) and blank lines are ignored.

Tip: keep a `docs/provenance.tsv` noting BioProject/BioSample/strain for each pair — you'll
want it for the methods section and the Zenodo deposit.

---

## Contributing new isolates

Everything above is about finding pairs for *your own* run. This section is
about growing the **shared, committed** `cohorts/` panels (`public-v1.tsv`,
`public-v2.tsv`, or a new panel you propose) via a reviewable pull request —
see [`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full step-by-step. It
requires no new infrastructure on your part beyond a normal git checkout:
`plasbench prepare-contribution` runs entirely on your own machine and ends
in a local branch, never an automatic push.

### Where to look, in priority order

1. **[NCTC 3000](https://www.sanger.ac.uk/resources/downloads/bacteria/nctc/)**
   — complete, curated reference genomes for the UK National Collection of
   Type Cultures, each with matched long-read and short-read sequencing done
   for the same physical strain by the same project. This is the single
   best source for new pairs: independence and pairing are already the
   project's own design, not something you have to reconstruct from
   incidental deposits.
2. **[GenomeTrakr](https://www.ncbi.nlm.nih.gov/pathogens/genomretrakr/) /
   [PulseNet](https://www.cdc.gov/pulsenet/index.html)** — public-health
   genomic-surveillance networks that deposit large, organized collections
   of foodborne/clinical pathogen genomes to NCBI, many with both a complete
   assembly and Illumina reads per isolate. Larger and more geographically
   diverse than NCTC 3000, but check each candidate against the quality
   criteria above individually — not every deposit in these networks carries
   a complete, plasmid-bearing assembly.
3. **A published plasmid-reconstruction tool paper's own supplementary
   cohort.** Many mob_recon/Platon/gplas-adjacent papers release their own
   benchmark isolates. Reusing one (Route C, above) grows PlasBench's cohort
   with data that already has independent scrutiny, and lets results be
   cross-checked against that paper's own reported numbers.

Whichever source you use, apply the same Route A/B quality criteria above
(complete assembly, matched paired-end Illumina, same BioSample) before
proposing a row.

### The dedup mechanism

Every isolate ever accepted into a released cohort is recorded in
`cohorts/accepted_accessions.tsv`, keyed on **BioSample** (see
[`cohorts/README.md`](../cohorts/README.md#cross-cohort-deduplication)) —
because an assembly can be resubmitted under a new accession while
representing the same physical isolate, BioSample is the identity that
actually stays stable across re-releases. `prepare-contribution` checks your
new rows against this ledger automatically; you do not need to cross-check
it by hand.

### Workflow: `plasbench prepare-contribution` → manual PR

1. Find and verify pairs (above), then benchmark them yourself: stage them
   with `plasbench init-local`/your own sample sheet, run
   `plasbench run --samples your_sheet.tsv`, and let stage 6 produce a real
   `scores.tsv` (and `tool_status.tsv`) for your new sample_id(s).
2. Write a small cohort-rows TSV for just the new isolate(s), using the same
   columns as the target cohort file (e.g. `cohorts/public-v2.tsv`'s own
   header).
3. Run:
   ```bash
   plasbench prepare-contribution --cohort public-v2 \
     --new-rows my_new_rows.tsv --scores results/scores.tsv \
     --tool-status results/tool_status.tsv
   ```
   This validates schema, NCBI-linked evidence (the same checks
   `validate-cohort --online` runs), cross-cohort BioSample dedup, a
   privacy/content screen (no local paths, environment variables, hostnames,
   or raw sequence files in any field), and metric sanity bounds — then, only
   if every check passes, appends your rows to `cohorts/public-v2.tsv`,
   `cohorts/public-v2.scores.tsv`, `cohorts/public-v2.tool_status.tsv`,
   updates `cohorts/public-v2.lock.json` and `accepted_accessions.tsv`, and
   commits all of it to a new local branch `contrib/<label>`. Any check that
   fails instead prints its reason and writes nothing.
4. Review the commit (`git show`), then push it yourself and open a pull
   request — nothing is ever pushed automatically:
   ```bash
   git push -u origin contrib/<label>
   ```
5. A maintainer reviews the PR (`.github/CODEOWNERS` gates every merge) the
   same way any other contribution is reviewed, and merges it once
   satisfied.
