# Metagenomic Adapter Contract

This contract applies only to the metagenomic track. It is intentionally
separate from `adapters/REGISTRY.md`, whose FASTA contract is for isolate
reconstruction.

## Required preserved evidence

An adapter must retain the command, tool/version, input checksums, original
output directory, and where applicable the input GFA, contig FASTA, graph-path
file, paired-read links, coverage/abundance data, classification scores, and
long-read linkage inputs. The normalized table is a pointer to evidence, not a
replacement for it.

## Normalized output

Write one TSV at:

```text
PREDICTIONS/<tool>/<community_id>.bins.tsv
```

with exactly these required fields:

```text
predicted_bin_id  contig_id  graph_path  orientation  path_confidence  plasmid_score  ambiguity_status  source_tool
```

Do not invent values. Use `?` orientation, `unknown` ambiguity, and an empty
`graph_path` only when the upstream tool truly does not expose that evidence.
Scores must be numeric in `[0,1]`; a hard-call-only tool should declare its
real hard-call confidence convention in its adapter provenance.

## Classification-only output

For a tool that classifies contigs but does not reconstruct bins, write:

```text
PREDICTIONS/<tool>/<community_id>.classification.tsv
contig_id  predicted_class  plasmid_probability  chromosome_probability  phage_probability  uncertainty_status  source_tool  supported_classes
```

Do not create one-record bins for classifiers. `predicted_class` is
`plasmid`, `chromosome`, `virus`, or `uncertain`; `uncertainty_status` is
`resolved`, `uncertain`, `abstained`, or `unknown`. A missing biological model
must be documented in adapter provenance, never inferred from another class.
`supported_classes` states the biological classes the tool actually models.

## Integration status

| Candidate | Intended role | Status | Installation policy |
|---|---|---|---|
| metaSPAdes | graph producer and baseline | supported runtime | `plasbench install-tools metagenomics` installs SPAdes; normalization is explicit. |
| geNomad plus transparent binner | classification baseline | supported runtime | `plasbench install-tools metagenomics` installs geNomad; binning remains an explicit, versioned adapter decision. |
| SCAPP | graph/path deconvolution | planned adapter | Do not auto-install until its command, output contract, and pinned runtime have a smoke test. |
| metaplasmidSPAdes | graph/path deconvolution | planned adapter | Do not reuse isolate plasmidSPAdes output as a metagenomic bin without this contract. |
| PlasMAAG | graph-aware multi-sample recovery | planned adapter | Do not auto-install until the selected upstream input mode and output version are pinned and tested. |
| PPR-Meta | three-class contig classifier | planned container adapter | Legacy runtime; normalize raw CSV with `plasbench normalize-meta-classifier`. |
| PlasmidHunter | plasmid/chromosome classifier | supported importer | Normalize its existing probability TSV; it cannot make phage or bin claims. |
| EBI MAP | mobilome annotation evidence | supported importer | Use `plasbench import-mobilome-evidence`; annotations never alter truth scores. |
| plsMD | isolate short-read reconstruction | planned adapter | Require image digest, PLSDB identity, and normalized final FASTA fixture first. |
| Plassembler meta | mock-community stress test | experimental | Preserve depth, resource allocation, and dataset label; do not generalize to routine metagenomes. |

“Planned” is deliberately not presented as executable. When a candidate becomes
supported, it must gain a pinned installer registry entry, native smoke test,
provenance fixture, and normalized-table regression before appearing in a
public benchmark.
