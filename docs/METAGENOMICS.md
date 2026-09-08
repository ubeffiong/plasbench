# Metagenomic Plasmid Benchmarking

## Scope and safety boundary

Metagenomic benchmarking is a separate PlasBench mode. It does not reuse the
isolate FASTA scorer, the isolate leaderboard, or operational isolate-method
recommendations. A metagenomic candidate bin is not a host assignment, a
closed plasmid, or a clinically confirmed plasmid.

Use isolate mode for a cultured clinical isolate with matched short reads and a
complete independent reference. Use metagenomics only for mixed communities
such as wastewater, environmental, gut, or surveillance samples.

## Inputs

Create a TSV using `cohorts/metagenomics.example.tsv` as the header contract.
One row represents one source sample in a `community_id`; a multi-sample
community deliberately has several rows with the same ID. Every community has
exactly one information regime:

| Regime | Meaning |
|---|---|
| `single_sample` | A single metagenomic sample; no cross-sample evidence claim. |
| `multisample` | Several related samples, with declared abundance/coverage support. |
| `graph_aware` | An assembly graph is required and path correctness is assessable. |
| `long_read_supported` | Independent long-read links are supplied; this is not automatic closure proof. |

`truth_status` is `synthetic`, `mock`, `verified`, or `unavailable`. Only
synthetic/mock/verified truth permits a benchmark score. `unavailable` inputs
may preserve tool outputs for review but are never ranked.

For truth-backed scoring, `truth_contigs_tsv` must contain:

```text
contig_id    truth_bin_id    biological_class
```

`biological_class` must be `plasmid`, `chromosome`, `virus`, or `unknown`.
This three-class declaration prevents phage/virus calls being silently treated
as chromosome error.

## Tool output contracts

Each adapter writes `PREDICTIONS/<tool>/<community_id>.bins.tsv`:

```text
predicted_bin_id  contig_id  graph_path  orientation  path_confidence  plasmid_score  ambiguity_status  source_tool
```

`orientation` is `+`, `-`, or `?`; numeric scores are in `[0,1]`; and
`ambiguity_status` is `resolved`, `ambiguous`, `abstained`, or `unknown`.
Preserve the original GFA, tool command/version, input checksums, and selected
subgraph files beside this normalized table. Do not manufacture graph paths,
confidence, host linkage, circularity, or long-read support when a tool did not
provide them.

Classification-only methods must instead write:

```text
PREDICTIONS/<tool>/<community_id>.classification.tsv
contig_id  predicted_class  plasmid_probability  chromosome_probability  phage_probability  uncertainty_status  source_tool  supported_classes
```

`predicted_class` is `plasmid`, `chromosome`, `virus`, or `uncertain`. This
prevents classifiers such as PPR-Meta and PlasmidHunter being misreported as
reconstructed plasmid bins. Their report metrics are separate from bin metrics.
`supported_classes` is pipe-separated. A two-class tool is scored only for the
classes it models and is visibly not comparable to a complete three-class model.

## Provenance and comparability

For a released or recommendation-eligible cohort, record `dataset_class`,
`dataset_license`, `truth_provenance`, `independence_status`,
`database_overlap_status`, `read_depth_x`, `host_depletion_reference`,
`assembler`, `assembler_parameters`, `tool_mode`, `comparability_group`,
`database_identity`, `container_image`, `container_digest`, `runtime_seconds`,
and `peak_rss_mb` in the community manifest. PlasBench preserves these values,
their available file checksums, and all rows in `metagenomics.run_manifest.json`.

Use `dataset_class=mock_high_depth` for a deliberately simple, unusually deep
mock community. It cannot justify a routine-metagenome recommendation.
`database_overlap_status` must declare whether a predictor database includes
truth sequences or close derivatives; such overlap is a leakage warning.

## Commands

```bash
# Validate the cohort contract and files before spending compute.
plasbench metagenomics validate --manifest meta_samples.tsv

# Use this before publishing a scored community cohort. It rejects missing
# licensing, truth, independence, comparator, and database-leakage metadata.
plasbench metagenomics validate --manifest meta_samples.tsv --release-ready

# Score normalized outputs and write metagenomics.summary.tsv,
# metagenomics.bin_metrics.tsv, metagenomics.run_manifest.json, and HTML.
plasbench metagenomics score \
  --manifest meta_samples.tsv \
  --predictions-dir predictions_meta \
  --out-dir results_meta

# Rebuild only the report after filtering or annotating results.
plasbench metagenomics report --manifest meta_samples.tsv --results-dir results_meta
```

Short forms are equivalent: `plasbench meta` and `plasbench beta` are aliases
for `plasbench metagenomics`; `-s`, `-p`, and `-o` mean manifest/samples,
predictions directory, and results directory. For example:

```bash
plasbench meta score -s meta_samples.tsv -p predictions_meta -o results_meta
plasbench run -m meta -s meta_samples.tsv -p predictions_meta -o results_meta
```

Normalize probability-aware classifiers after running their pinned upstream
runtime. PlasBench never fabricates bins from a classifier result:

```bash
plasbench normalize-meta-classifier --tool ppr_meta \
  --input ppr_meta.csv --threshold 0.70 \
  --out predictions_meta/ppr_meta/community_01.classification.tsv

plasbench normalize-meta-classifier --tool plasmidhunter \
  --input predictions.tsv --threshold 0.70 \
  --out predictions_meta/plasmidhunter/community_01.classification.tsv
```

Import MAP-compatible mobilome GFF3 only as supporting biological evidence:

```bash
plasbench import-mobilome-evidence \
  --gff map_results/sample/gff/sample_mobilome.gff.gz \
  --community community_01 --sample sample_01 \
  --out results_meta/metagenomics.mobilome_evidence.tsv
plasbench meta report -s meta_samples.tsv -o results_meta
```

`plasbench run --mode metagenomics` is an alias for the scoring route when
given `--samples`, `--predictions-dir`, and `--results-dir`. It intentionally
does not start an unpinned third-party assembler or deconvolution tool.

## Interpretation

Bin metrics include global one-to-one bin matching, bin precision/recall/F1,
split/merge events, unmatched bins, chromosome contamination, virus
contamination, ambiguous contigs, abstained contigs, and mean declared path
confidence. Classification metrics are separate: per-class precision/recall/F1,
macro F1, and uncertain-call fraction. Results are comparable only within the
same information regime and evaluation type.

The report is `metagenomics.report.html`; it is intentionally separate from
`benchmark.report.html`. It provides the same report-level usability expected
of the isolate dashboard while using community-appropriate views: interactive
regime/tool/evaluation filters, filtered CSV export, separate reconstruction
and classifier performance bars, a clickable community-by-tool score matrix,
bin/classifier drilldowns, mobilome-evidence table, upstream preprocessing and
assembly provenance, interpretation guidance, and a direct-download artifact
explorer. Reconstruction and classification are deliberately never pooled into
one winner.

For graph inspection, open an adapter-preserved selected-bin GFA subgraph with
one-to-two-hop neighbours. Rendering an entire metagenomic graph as a static
diagram is not scientifically interpretable.

## Tool integration roadmap

PlasBench will add independently versioned adapters for metaplasmidSPAdes,
SCAPP, a transparent binner-plus-classifier baseline, geNomad classification,
and PlasMAAG. Tool installation is added to `plasbench install-tools` only
after the upstream command, license, database location, and normalized output
contract are tested in CI. This avoids a convenience installer that silently
installs an unusable or scientifically incompatible runtime.

`plasbench install-tools metagenomics` is the convenient baseline profile for
metaSPAdes and geNomad. `plasbench install-tools all` reaches the same packages
through its existing `assembly` and `genomad` profiles without repeating a
second solver transaction.

Host linkage requires independent validated evidence such as long-read bridges,
Hi-C, methylation, or calibrated multi-sample co-abundance. It is a future
evidence layer, not a score inferred from bin membership.

## External candidates and status

| Candidate | Track | Status | Honest boundary |
|---|---|---|---|
| PPR-Meta | three-class classification | planned pinned container | Legacy runtime; normalize its CSV after a locally validated container run. |
| PlasmidHunter | classification | supported importer | Existing isolate installation profile; no phage model and no bin claims. |
| plsMD | isolate short-read reconstruction | planned | Requires a pinned Docker image and validated PLSDB release before native execution. |
| Plassembler | hybrid/isolate; mock meta stress test | experimental only | Its authors do not recommend routine metagenomic use. |
| EBI MAP | mobilome evidence | supported importer | GFF3/protein annotations are displayed but never alter truth scores. |

Use `plasbench install-tools plan` to inspect each runtime contract. Planned
tools are deliberately not silently installed or advertised as benchmark-ready.

## Cohort readiness

### Real physical truth control: BMock12

PlasBench ships a checksum-pinned source registry for [BMock12](https://www.ncbi.nlm.nih.gov/sra/SRR8073714), a real
12-strain DNA mock community sequenced on Illumina, PacBio, and Oxford Nanopore.
Its companion public artifact release contains a scaffold assembly, assembly
graph, and contig-to-source-genome gold standard. Materialize only those small
benchmark artifacts with:

```bash
plasbench materialize-meta-bmock12 \
  --out-dir "$HOME/.local/share/plasbench/metagenomics/controls"
```

The command retries transient failures, verifies MD5 values before accepting
each file, reuses verified files on later runs, decompresses the assembly and
graph, converts the GSA membership table to PlasBench truth, and writes:

```text
.../bmock12/scaffolds.fasta
.../bmock12/assembly_graph_with_scaffolds.gfa
.../bmock12/truth_contigs.tsv
.../bmock12/metagenomics-bmock12-verified.tsv
.../bmock12/provenance.json
```

The generated manifest is directly accepted by `plasbench metagenomics score`.
It is intentionally a chromosome-specificity / plasmid-false-positive control:
the independently released BMock12 gold standard contains source-genome bin
membership, not a validated list of positive plasmid replicons. Do **not** use
it to calculate plasmid recall, claim closed plasmids, or rank a tool as best
for routine metagenomics. The raw Illumina run is `SRR8073716` (`PRJNA496047`)
and is intentionally not downloaded by the materializer because it contains
roughly 64 Gbp; download it only when rerunning assembly/tool stages from reads.

`cohorts/metagenomics-physical-mock-v1.tsv` records BMock12 plus two further
physical-mock candidates found through NCBI/GitHub literature review:

- [MBARC-26](https://pmc.ncbi.nlm.nih.gov/articles/PMC5037974/) (`SRX1836716`): 26 finished component genomes, Illumina and PacBio
  reads; pending a pinned component-reference snapshot and independently
  regenerated contig projection.
- HMP even mock (`SRR072232`): published as a plasmid-positive mock candidate;
  pending a reusable, versioned component/reference and contig-truth release.

Those candidates are deliberately not scored yet. A source accession, an
assembly, or tool-predicted plasmids never substitutes for independently
versioned contig truth.

The bundled `metagenomics.example.tsv` and `metagenomics.mock_high_depth.example.tsv`
are intentionally non-runnable templates. PlasBench's regression suite creates
small deterministic truth communities covering correct recovery, split/merge,
chromosome contamination, virus contamination, unmatched bins, uncertain
classifier calls, unsupported classes, malformed inputs, and contradictory
truth labels. This is enough to test the implementation, not to publish a tool
ranking. A released community cohort needs verified truth, independent data,
licensing, database-overlap review, and adequate representation of the intended
information regimes and sample settings.

## Ecosystem intake and controlled scenario design

Do not treat a GitHub topic page, a workflow's popularity, or a tool's own
predictions as scientific evidence or recommendation-model labels. Record a
candidate tool, workflow, dataset, or evidence provider in
`config/metagenomic_ecosystem_intake.tsv`, then validate its licence, scope,
truth quality, independence, database-leakage risk, output contract, and
dependency plan before implementation:

```bash
plasbench validate-meta-intake
```

Community manifests can retain `assembly_profile`,
`assembly_profile_version`, `preprocessing_profile`, `coassembly_id`,
`source_study`, `reference_cluster_id`, community complexity, phage burden,
contamination level, and host-assignment evidence. These fields are
provenance, not tool-quality metrics. A predicted bin never establishes host
evidence by itself.

```bash
plasbench audit-meta-cohort --manifest communities.tsv --out results_meta/cohort_audit.json
plasbench audit-meta-cohort --manifest communities.tsv --out results_meta/cohort_audit.json --release-ready
```

The release-ready audit rejects mock/synthetic operational cohorts and shared
`reference_cluster_id` values across communities. Assign cluster identifiers
from an independent ANI/dereplication analysis before a release to prevent
near-identical references leaking across evaluation communities.

For controlled scenario testing, build a deterministic synthetic design from
complete local references. This command writes the design and its pinned
simulator/container provenance; it intentionally does not fabricate FASTQs.
Materialise reads later with the recorded simulator and retain the resulting
commands and checksums.

```bash
plasbench design-meta-synthetic \
  --members cohorts/metagenomics.synthetic-members.example.tsv \
  --out-dir results_meta/synthetic_design --seed 42 \
  --simulator CAMISIM --simulator-version '<validated-version>' \
  --container-image '<registry/image>' --container-digest 'sha256:<digest>'
```

Use designs that deliberately vary depth, abundance, plasmid copy number,
community complexity, phage burden, and contamination. Synthetic and mock
results must remain separate from real-community operational leaderboards.
