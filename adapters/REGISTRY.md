# Adapter Registry

Every PlasBench tool adapter must produce `pred_<tool>.plasmid.fasta`. An empty
FASTA is a valid completed prediction; an adapter must exit non-zero only when
its output cannot be interpreted safely. The pipeline then records a failure
rather than assigning an artificial zero score.

| Tool | Input | Adapter | Status |
|---|---|---|---|
| MOB-suite | short-read assembly | `adapt_mob_recon.sh` | supported |
| Platon | short-read assembly | `adapt_platon.sh` | supported |
| plasmidSPAdes | paired reads | `adapt_plasmidspades.sh` | supported |
| gplas | GFA graph | `adapt_gplas.sh` | experimental |
| gplas2_mob | GFA graph plus MOB-derived classifier TSV | native mode | optional |
| gplas2_external | GFA graph plus user classifier TSV | native mode | optional |

## gplas2 contract

`gplas2` is graph based and requires both an assembly graph and a binary
classifier prediction table. PlasBench deliberately does not invent this
table: it must have been generated from the same graph's extracted nodes, with
documented classifier/database versions. Place a validated plasmid FASTA at
`results/<sample>/pred_gplas2.plasmid.fasta` and its completion marker at
`results/<sample>/.gplas2.complete`; stage 5 will score it exactly like native
adapters. Record the gplas2 command and classifier provenance in the run
manifest's external notes before publication.

This contract supports current and future external methods without coupling
the core benchmark to unstable third-party command-line interfaces. Enable
`RUN_GPLAS2_MOB=1` or `RUN_GPLAS2_EXTERNAL=1`; the latter reads
`$GPLAS2_EXTERNAL_PREDICTIONS_DIR/<sample>.tsv`.
