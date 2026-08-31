# Finding matched pairs (the real curation task)

The benchmark needs isolates that have **both**:

1. a **complete** genome assembly (long-read or hybrid → closed chromosome + plasmids),
   which becomes the ground truth; and
2. the **matched Illumina** reads for the *same isolate*, which are what the tools are
   tested on.

Finding these pairs is the hardest and most valuable part of the project. Here are three
reliable routes.

---

## Route A — Start from complete assemblies (recommended)

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

---

## Route B — Start from a project that did both

Hybrid-assembly studies often deposit **both** the Nanopore/PacBio-based complete assembly
**and** the Illumina reads under one **BioProject**. Find such a BioProject (search terms
like *"hybrid assembly", "Nanopore", "complete genome", "plasmid"* for your taxon), then
pull every isolate that has the complete-assembly + Illumina pair. This is the fastest way
to get 10–20 clean pairs at once.

---

## Route C — Reference/benchmark collections

Some plasmid-benchmark papers and resources publish curated isolate sets with matched data.
Reusing (and citing) an established truth set is legitimate and saves time; you can then add
your own newly-curated pairs on top.

---

## Quality criteria (keep only good pairs)

- **Complete** assembly (not "chromosome" or "scaffold" level) — you need closed plasmids.
- Reads are **Illumina paired-end**. (Single-end works but needs a small edit in
  `01_download.sh`/`03_assemble.sh`.)
- Same isolate — confirm the assembly and the run share a **BioSample** where possible.
- Reasonable read depth (≳ 30× genome). Very low depth handicaps every tool equally but
  adds noise.
- A mix of **plasmid-carrying** isolates (needed for recall) — avoid an all-plasmid-free set.

---

## Filling in the sample sheet

Put each accepted pair in `config/accessions.tsv`:
```
sample_id	assembly_accession	sra_run
ecoli_01	GCF_012345678.1	SRR12345678
```
`sample_id` is any short unique label you choose. Comments (`#`) and blank lines are ignored.

Tip: keep a `docs/provenance.tsv` noting BioProject/BioSample/strain for each pair — you'll
want it for the methods section and the Zenodo deposit.
