# Contributed RefSeq complete genome / SRA short-read pairs

Supplied by a PlasBench collaborator (credit to be added to ACKNOWLEDGMENTS.md once they confirm the wording),
and copied here with their permission, as received on 2026-11-16.

| File | Rows | What it is |
|---|---:|---|
| `assemblies.tsv.gz` | 8,812 | One row per RefSeq Complete Genome paired to SRA runs (47 columns: assembly and read release dates, assembly method and technology, region, Africa subregion, isolation-source category, reported plasmid accessions). |
| `plasmids.tsv.gz` | 24,606 | `assemblies.tsv` repeated once per plasmid plus `plasmid_accession`, `plasmid_name`, `plasmid_index_in_assembly`. It carries no plasmid size or replicon metrics. |

`contributed.lock.json` pins the SHA-256 of each original file and of each stored `.gz`.

## Read this before using it

* **This is a candidate pool, not a cohort.** Nothing here has been verified against NCBI by PlasBench. The
  importer (`python/import_contributed_cohort.py`) feeds it into the normal curation path, and
  `plasbench validate-cohort --online` is what proves a pairing.
* **The `bioproject` column is `PRJNA224116` on every row** (NCBI's RefSeq umbrella project), so it is useless for
  independence. Use `read_bioprojects` / `sra_studies` as the cluster key.
* **Read quality has not been assessed** (the contributor's own caveat). Run the QC gate before selecting.
* `pathogen_category` is a provisional species lookup, and 6,108 of 8,812 isolation sources are "Unclassified".
* `eligible_2025_2026` is a convenience flag on the assembly release year only. About 40% of those rows had reads public
  a year or more before the assembly, so use the leakage settings (`LEAKAGE_*`), not this flag, for the leakage analysis.
* There are no plasmid-free genomes in the pool.
